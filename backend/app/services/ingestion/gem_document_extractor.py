"""
Document-aware extraction for real public GeM bid documents.

GeM bid detail URLs (``showbidDocument/<id>``) serve downloadable PDF documents,
not HTML pages. The existing detail-enrichment path tried to render them as HTML
in Playwright, which fails with "Download is starting". This module downloads
the PDF over plain HTTP, validates it, extracts its text with pypdf, and maps
the extracted content into the canonical bid fields used by the existing
matching engine.

Safety properties:
* **Off unless enabled** - ``GEM_DIRECT_DOC_EXTRACTION_ENABLED`` defaults to
  False, preserving current behavior exactly.
* **Bounded** - max file size, per-document timeout, and per-run budget.
* **Failure-isolated** - any download/parse error is recorded and the run
  continues; a document failure never removes a listing-derived bid.
* **No execution** - downloaded bytes are only scanned for text; nothing is
  executed or trusted as instructions.
"""
from __future__ import annotations

import io
import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, Optional

import requests

from app.core.config import settings

logger = logging.getLogger(__name__)

# pypdf is imported lazily inside extract_document_text so the module can be
# imported even when pypdf is not installed (it is an optional dependency).
try:
    from pypdf import PdfReader  # type: ignore
except ImportError:  # pragma: no cover - optional dependency
    PdfReader = None  # type: ignore

# Maximum PDF size in bytes (10 MB default). GeM bid documents are typically
# under 500 KB; this cap prevents runaway memory use on a malicious or corrupt
# document.
MAX_DOC_SIZE_BYTES: int = 10 * 1024 * 1024

# Per-document fetch timeout in seconds.
DOC_FETCH_TIMEOUT_SECONDS: float = 30.0

# Maximum number of PDF pages to extract text from (0 = no limit).
MAX_DOC_PAGES: int = 0

# PDF magic bytes.
_PDF_MAGIC = b"%PDF-"

# Fields that document text can populate. Only the matching-relevant fields are
# populated from document text; the listing already provides title, dates, and
# organisation. A field the document does not contain stays None.
_DOCUMENT_FILLABLE_FIELDS = (
    "scope_of_work",
    "technical_requirements",
    "eligibility_criteria",
    "qualification_requirements",
    "experience_requirements",
    "certification_requirements",
    "estimated_value",
    "location",
    "category",
    "bid_type",
    "contact_information",
    "tender_fee_information",
    "emd_information",
)


def is_pdf_document_url(source_url: Optional[str]) -> bool:
    """True when ``source_url`` looks like a GeM bid document (PDF download).

    Checks both the URL path marker (``showbiddocument``) and, when content
    has been fetched, the content type. This function only inspects the URL
    string; callers verify the content type after download.
    """
    if not source_url:
        return False
    try:
        from urllib.parse import urlparse
        parsed = urlparse(str(source_url).strip())
    except Exception:
        return False
    path = (parsed.path or "").lower()
    return "showbiddocument" in path


@dataclass
class DocumentExtractionResult:
    """Result of downloading and extracting a GeM bid document."""

    success: bool
    content_type: Optional[str] = None
    file_size_bytes: Optional[int] = None
    page_count: Optional[int] = None
    extracted_text: Optional[str] = None
    extracted_fields: Dict[str, Optional[str]] = None
    error: Optional[str] = None
    error_type: Optional[str] = None
    page_limit_applied: bool = False
    # Raw downloaded bytes, held only in memory during extraction. Never
    # serialized or persisted. Set by download_document(), consumed by
    # extract_document_text().
    _raw_bytes: Optional[bytes] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "content_type": self.content_type,
            "file_size_bytes": self.file_size_bytes,
            "page_count": self.page_count,
            "page_limit_applied": self.page_limit_applied,
            "extracted_text_length": len(self.extracted_text or ""),
            "extracted_fields": {
                k: v for k, v in (self.extracted_fields or {}).items() if v
            },
            "error": self.error,
            "error_type": self.error_type,
        }


def _default_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": getattr(settings, "GEM_DIRECT_USER_AGENT", "SecuredApp-GeM-Intelligence/1.0"),
            "Accept": "*/*",
        }
    )
    return session


def _validate_public_url(url: str) -> str:
    """Validate that a URL is on an allowlisted GeM host.

    Delegated to the collector's own validator so allowlist logic lives in one
    place.
    """
    from app.services.ingestion.gem_public_collector import validate_public_url

    return validate_public_url(url)


def download_document(
    url: str,
    *,
    session: Optional[requests.Session] = None,
    timeout: Optional[float] = None,
    max_size_bytes: Optional[int] = None,
) -> DocumentExtractionResult:
    """Download a document and return raw bytes with metadata.

    Never raises: failures are captured in the returned result.
    """
    result = DocumentExtractionResult(success=False)

    if not url or not str(url).strip():
        result.error = "No document URL provided."
        result.error_type = "missing_url"
        return result

    try:
        _validate_public_url(url)
    except Exception as exc:
        result.error = f"URL failed allowlist validation: {exc}"
        result.error_type = "allowlist"
        return result

    session = session or _default_session()
    effective_timeout = float(timeout or DOC_FETCH_TIMEOUT_SECONDS)
    max_size = int(max_size_bytes or MAX_DOC_SIZE_BYTES)

    try:
        response = session.get(url, timeout=effective_timeout, allow_redirects=True)
    except requests.RequestException as exc:
        result.error = f"Download failed: {type(exc).__name__}: {exc}"
        result.error_type = "download"
        return result

    status = int(getattr(response, "status_code", 0) or 0)
    if status >= 400:
        result.error = f"GeM returned HTTP {status} for the document."
        result.error_type = "http_error"
        return result

    content_type = response.headers.get("Content-Type", "").lower()
    result.content_type = content_type

    content = getattr(response, "content", None)
    if content is None:
        content = (getattr(response, "text", "") or "").encode("utf-8", errors="replace")

    result.file_size_bytes = len(content)

    # Enforce max size before any parsing.
    if len(content) > max_size:
        result.error = (
            f"Document too large: {len(content)} bytes > {max_size} bytes "
            f"(GEM_DIRECT_MAX_DOC_SIZE_MB)."
        )
        result.error_type = "too_large"
        return result

    if not content:
        result.error = "Document is empty."
        result.error_type = "empty"
        return result

    # Verify PDF magic bytes before attempting pypdf parsing.
    if not content.startswith(_PDF_MAGIC):
        result.error = (
            f"Document is not a PDF (content type {content_type or 'unknown'}, "
            f"first bytes: {content[:8]!r})."
        )
        result.error_type = "not_pdf"
        return result

    result.success = True
    # Store raw bytes on the result for the caller to parse; pypdf extraction
    # happens in extract_document_text() so the caller can decide.
    result._raw_bytes = content  # type: ignore[attr-defined]
    return result


def extract_document_text(
    result: DocumentExtractionResult,
    *,
    max_pages: Optional[int] = None,
) -> DocumentExtractionResult:
    """Extract text from a downloaded PDF result using pypdf.

    Mutates and returns the same result object with extracted text and fields.
    Never raises: parse failures are captured in the result.
    """
    if not result.success:
        return result
    raw = getattr(result, "_raw_bytes", None)
    if raw is None:
        return result

    content = result._raw_bytes
    effective_max_pages = int(max_pages or MAX_DOC_PAGES or 0)

    try:
        reader = PdfReader(io.BytesIO(content))
    except Exception as exc:
        if PdfReader is None:
            result.error = "pypdf is not installed."
            result.error_type = "missing_dependency"
        else:
            result.error = f"PDF could not be opened: {type(exc).__name__}: {exc}"
            result.error_type = "parse"
        result.success = False
        return result

    try:
        page_count = len(reader.pages)
    except Exception as exc:
        result.error = f"PDF page count unavailable: {type(exc).__name__}: {exc}"
        result.error_type = "parse"
        result.success = False
        return result

    result.page_count = page_count

    # Enforce page limit before reading any page text, so oversized PDFs
    # never incur unnecessary parsing cost.
    pages_to_read = page_count
    if effective_max_pages > 0:
        pages_to_read = min(page_count, effective_max_pages)
        result.page_limit_applied = True

    texts: list[str] = []
    for i in range(pages_to_read):
        try:
            page_text = reader.pages[i].extract_text() or ""
            if page_text.strip():
                texts.append(page_text)
        except Exception as exc:  # noqa: BLE001 - one bad page must not lose the doc
            logger.warning("PDF page %d text extraction failed: %s", i + 1, exc)
            continue

    extracted_text = "\n".join(texts)
    result.extracted_text = extracted_text or None

    if not extracted_text:
        result.error = "PDF yielded no extractable text."
        result.error_type = "no_text"
        result.success = False
        return result

    # Map extracted text to canonical fields. The document is treated as a
    # single text blob; field extraction uses label-aware heuristics that only
    # capture text literally present in the document.
    fields = _map_document_fields(extracted_text)
    result.extracted_fields = fields

    return result


# Lookahead alternatives that mark the start of a new labeled field. A label
# is only recognised when it appears at the start of a line (preceded by a
# newline or at the start of the string). This prevents mid-sentence words
# like "experience" in "years of experience" from terminating a capture
# prematurely, and prevents the first label on the text from matching itself.
_LABEL_START = r"(?:(?:\n|\r|\A)\s*(?:eligibility|qualification|experience|certification|technical|emd|tender|estimated|location|category|bid\s+type|contact)|$)"


def _field_pattern(label_prefix: str) -> re.Pattern:
    """Build a label pattern that captures until the next labeled field.

    The lookahead uses word boundaries so mid-sentence occurrences of label
    words (e.g. "experience" in "years of experience") do not prematurely end
    the capture.
    """
    return re.compile(
        rf"{label_prefix}[:\s]*(.+?)(?=\s*(?:{_LABEL_START})|$)",
        re.IGNORECASE | re.DOTALL,
    )


_LABEL_PATTERNS = (
    ("technical_requirements", _field_pattern(
        r"(?:technical\s+(?:specification|requirement)|specification|scope\s+of\s+(?:work|supply))"
    )),
    ("eligibility_criteria", _field_pattern(
        r"(?:eligibility\s+criteria|eligibility)"
    )),
    ("qualification_requirements", _field_pattern(
        r"(?:qualification\s+requirements|qualification)"
    )),
    ("experience_requirements", _field_pattern(
        r"(?:experience\s+(?:requirements|criteria)|years?\s+of\s+(?:past\s+)?experience\s*:)"
    )),
    ("certification_requirements", _field_pattern(
        r"(?:certification\s+(?:requirements|criteria)|certificate)"
    )),
    ("estimated_value", re.compile(
        r"(?:estimated\s+(?:bid\s+)?value|bid\s+value|estimated\s+cost)[:\s]*([^\n]{2,100})",
        re.IGNORECASE,
    )),
    ("location", re.compile(
        r"(?:location|place\s+of\s+delivery|supply\s+location)[:\s]*([^\n]{2,120})",
        re.IGNORECASE,
    )),
    ("category", re.compile(
        r"(?:item\s+category|category)[:\s]*([^\n]{2,200})",
        re.IGNORECASE,
    )),
    ("bid_type", re.compile(
        r"(?:bid\s+type|type\s+of\s+bid)[:\s]*([^\n]{2,80})",
        re.IGNORECASE,
    )),
    ("contact_information", re.compile(
        r"(?:contact\s+(?:information|details)|contact)[:\s]*([^\n]{2,200})",
        re.IGNORECASE,
    )),
    ("tender_fee_information", re.compile(
        r"(?:tender\s+fee|fee\s+information)[:\s]*([^\n]{2,100})",
        re.IGNORECASE,
    )),
    ("emd_information", re.compile(
        r"(?:emd\s+(?:information|amount)|earnest\s+money)[:\s]*([^\n]{2,100})",
        re.IGNORECASE,
    )),
)


def _clean_text(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    cleaned = re.sub(r"\s+", " ", value).strip()
    return cleaned or None


# Numeric/currency pattern used to validate that an extracted estimated_value
# actually contains a number, not just explanatory text.
_NUMERIC_PATTERN = re.compile(r"\d[\d,]*(\.\d+)?")


# Fields that contain prose/sentences rather than short values. These are
# checked for sentence completeness to reject incomplete fragment captures.
_PROSE_FIELDS = frozenset({
    "technical_requirements",
    "eligibility_criteria",
    "qualification_requirements",
    "experience_requirements",
    "certification_requirements",
    "scope_of_work",
})


def _has_substantive_content(
    value: Optional[str], min_chars: int = 3, field_name: Optional[str] = None
) -> bool:
    """True when ``value`` carries real content beyond a fragment."""
    if not value:
        return False
    stripped = value.strip()
    if len(stripped) < min_chars:
        return False
    # Reject values that are just a single digit, a symbol, or a bare label
    # remnant with no actual content.
    if re.fullmatch(r"[\W_]+", stripped):
        return False
    # For prose fields, reject fragments that end mid-sentence (no proper
    # sentence terminator). These are typically incomplete label captures
    # from regex heuristics.
    if field_name in _PROSE_FIELDS:
        if not re.search(r"[.!?)]\s*$", stripped):
            return False
    return True


def _validate_estimated_value(value: Optional[str]) -> Optional[str]:
    """Return ``value`` only when it looks like a real amount/currency figure.

    Rejects explanatory text that merely mentions "amount" or "EMD" without
    an actual numeric figure.
    """
    if not value:
        return None
    if not _NUMERIC_PATTERN.search(value):
        return None
    return value


def _map_document_fields(text: str) -> Dict[str, Optional[str]]:
    """Extract canonical fields from document text using label heuristics.

    Only text literally present in the document is captured. A field the
    document does not label stays None. Nothing is invented.

    Extracted values are validated conservatively:
    * estimated_value must contain an actual numeric figure
    * eligibility_criteria must be substantive (not a fragment ending mid-sentence)
    * contact_information must contain at least 3 non-symbol characters
    """
    fields: Dict[str, Optional[str]] = {field: None for field in _DOCUMENT_FILLABLE_FIELDS}

    # scope_of_work gets the full document text (it's the broadest container).
    fields["scope_of_work"] = _clean_text(text[:5000]) if text else None

    for field, pattern in _LABEL_PATTERNS:
        match = pattern.search(text)
        if match:
            value = _clean_text(match.group(1))
            if field == "estimated_value":
                value = _validate_estimated_value(value)
            if _has_substantive_content(value, field_name=field):
                fields[field] = value

    return fields


def enrich_record_from_document(
    record: Any,
    *,
    session: Optional[requests.Session] = None,
    timeout: Optional[float] = None,
    max_size_bytes: Optional[int] = None,
    max_pages: Optional[int] = None,
) -> DocumentExtractionResult:
    """Download a GeM bid document and enrich a record with extracted fields.

    This is the single entry point used by the detail-enrichment path. It
    downloads the PDF, extracts text, maps fields, and returns a result. The
    caller decides how to apply the extracted fields to the record.

    Never raises: failures are captured in the returned result.
    """
    result = DocumentExtractionResult(success=False)

    url = getattr(record, "source_url", None) or ""
    if not is_pdf_document_url(url):
        result.error = "URL is not a GeM bid document."
        result.error_type = "not_document_url"
        return result

    download_result = download_document(
        url, session=session, timeout=timeout, max_size_bytes=max_size_bytes,
    )
    if not download_result.success:
        # Copy failure info into the returned result.
        result.error = download_result.error
        result.error_type = download_result.error_type
        result.content_type = download_result.content_type
        result.file_size_bytes = download_result.file_size_bytes
        return result

    # Extract text from the downloaded bytes.
    extract_result = extract_document_text(download_result, max_pages=max_pages)

    # Copy everything into the caller's result.
    result.success = extract_result.success
    result.content_type = extract_result.content_type
    result.file_size_bytes = extract_result.file_size_bytes
    result.page_count = extract_result.page_count
    result.extracted_text = extract_result.extracted_text
    result.extracted_fields = extract_result.extracted_fields
    result.error = extract_result.error
    result.error_type = extract_result.error_type

    return result
