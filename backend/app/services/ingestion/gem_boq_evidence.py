"""Authoritative GeM Bill-of-Quantities (BoQ) evidence.

GeM's public listing renders each bid's item list inside a ``data-content``
popover whose attribute value is capped at ~99 characters at the source, so the
persisted ``title`` / ``scope_of_work`` only ever hold a prefix of the real
scope. The full line items are published as a machine-readable CSV linked from
the bid document PDF (``https://bidplus.gem.gov.in/showbidDocument/<id>`` ->
``https://mkp.gem.gov.in/.../OrderItem/BoqLineItemsDocument/...csv``).

This module fetches that CSV through the same public-host allowlist guard used
by the direct collector, parses the line items, and stores them on the bid in
``Bid.boq_items`` -- separately from the title and scope of work, with the exact
source URL and retrieval time. It never overwrites the title or scope.

It is invoked explicitly (see ``scripts/enrich_bid_boq.py``); it performs no
automatic per-bid network calls during collection.
"""
from __future__ import annotations

import csv
import io
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.core.config import settings
from app.services.boq_text import (  # re-exported for callers
    boq_evidence_text as boq_evidence_text,
    boq_item_count as boq_item_count,
    boq_item_lines as boq_item_lines,
)

# Marker that identifies the BoQ *line-item* document (the parseable CSV) within
# the links embedded in the bid PDF. The specification PDF uses ``BoqDocument``.
_BOQ_CSV_MARKER = "boqlineitemsdocument"
_BOQ_SPEC_MARKER = "boqdocument"

_URL_RE = re.compile(r"https?://[^\s\)\]<>\"'()]+", re.IGNORECASE)

# BoQ CSV header -> stable key. Unknown columns keep a canonicalised name.
_HEADER_ALIASES = {
    "item number": "item_number",
    "item title": "title",
    "item description": "description",
    "item quantity": "quantity",
    "unit of measure": "unit",
    "consignee id": "consignee_id",
    "delivery period (in number of days)": "delivery_period",
}


class BoQEvidenceError(Exception):
    """Raised when BoQ evidence cannot be located, fetched or parsed."""


def _canonical_header(raw: Optional[str]) -> str:
    key = (raw or "").lstrip("\ufeff").strip().lower()
    return _HEADER_ALIASES.get(key, key)


def _first_url(blob: str, marker: str, suffix: str) -> Optional[str]:
    for match in _URL_RE.finditer(blob):
        url = match.group(0)
        low = url.lower()
        if marker in low and low.split("?", 1)[0].endswith(suffix):
            return url
    return None


def extract_boq_document_links(document_bytes: bytes) -> Dict[str, Optional[str]]:
    """Find the BoQ CSV and specification URLs embedded in a bid document.

    The links live in the bid PDF as uncompressed URI entries, so a plain byte
    scan finds them without a PDF library. HTML documents are handled too (the
    ``&amp;`` entity is normalised).
    """
    if not document_bytes:
        return {"csv_url": None, "spec_url": None}
    blob = document_bytes.decode("latin-1", errors="ignore").replace("&amp;", "&")
    csv_url = _first_url(blob, _BOQ_CSV_MARKER, ".csv")
    spec_url = _first_url(blob, _BOQ_SPEC_MARKER, ".pdf")
    return {"csv_url": csv_url, "spec_url": spec_url}


def parse_boq_csv(csv_text: str, max_items: Optional[int] = None) -> List[Dict[str, str]]:
    """Parse a GeM BoQ line-item CSV into a list of normalised item dicts."""
    if not csv_text or not csv_text.strip():
        return []
    reader = csv.DictReader(io.StringIO(csv_text))
    items: List[Dict[str, str]] = []
    for row in reader:
        item: Dict[str, str] = {}
        for raw_key, raw_val in row.items():
            if raw_key is None:
                continue
            item[_canonical_header(raw_key)] = (raw_val or "").strip()
        if not item.get("title") and not item.get("description"):
            continue
        items.append(item)
        if max_items and max_items > 0 and len(items) >= max_items:
            break
    return items


def build_boq_evidence(
    items: List[Dict[str, str]],
    source_url: str,
    retrieved_at: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Wrap parsed items with provenance (source URL + retrieval timestamp)."""
    moment = retrieved_at or datetime.now(timezone.utc)
    return {
        "items": items,
        "item_count": len(items),
        "source_url": source_url,
        "retrieved_at": moment.isoformat() if isinstance(moment, datetime) else str(moment),
    }


def _decode(csv_bytes: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return csv_bytes.decode(encoding)
        except UnicodeDecodeError:
            continue
    return csv_bytes.decode("latin-1", errors="ignore")


def _validate(url: str) -> str:
    # Imported lazily: the collector module must not be pulled into the
    # ingestion package's import graph at engine import time.
    from app.services.ingestion.gem_public_collector import validate_public_url

    return validate_public_url(url)


def _default_session():
    import requests

    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": "SecuredApp-GeM-Intelligence/1.0",
            "Accept": "*/*",
        }
    )
    return session


def _get_bytes(session: Any, url: str, timeout: float) -> bytes:
    response = session.get(url, timeout=timeout, allow_redirects=True)
    status = int(getattr(response, "status_code", 0) or 0)
    if status >= 400:
        raise BoQEvidenceError(f"GeM returned HTTP {status} for the BoQ document {url}.")
    content = getattr(response, "content", None)
    if content is None:
        content = (getattr(response, "text", "") or "").encode("utf-8")
    return content


def fetch_boq_evidence(
    source_url: str,
    *,
    session: Any = None,
    timeout: Optional[float] = None,
    max_items: Optional[int] = None,
    retrieved_at: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Fetch and parse BoQ evidence for a bid document URL.

    ``source_url`` is normally the bid's own ``source_url`` (the public
    ``showbidDocument`` document). Both that URL and the discovered CSV URL must
    pass the GeM host allowlist. ``session`` is injectable for tests.
    """
    if not source_url or not str(source_url).strip():
        raise BoQEvidenceError("Bid has no source URL to fetch BoQ evidence from.")

    _validate(source_url)
    session = session or _default_session()
    effective_timeout = timeout or settings.GEM_BOQ_FETCH_TIMEOUT_SECONDS
    cap = max_items if max_items is not None else settings.GEM_BOQ_MAX_ITEMS

    document = _get_bytes(session, source_url, effective_timeout)
    links = extract_boq_document_links(document)
    csv_url = links.get("csv_url")
    if not csv_url:
        raise BoQEvidenceError("No BoQ line-item CSV is linked from the bid document.")

    _validate(csv_url)
    csv_bytes = _get_bytes(session, csv_url, effective_timeout)
    items = parse_boq_csv(_decode(csv_bytes), max_items=cap)
    if not items:
        raise BoQEvidenceError("The BoQ CSV contained no parseable line items.")

    return build_boq_evidence(items, csv_url, retrieved_at)


def _same_evidence(existing: Any, fresh: Dict[str, Any]) -> bool:
    return (
        isinstance(existing, dict)
        and existing.get("source_url") == fresh.get("source_url")
        and existing.get("items") == fresh.get("items")
    )


def apply_boq_evidence(bid: Any, evidence: Dict[str, Any]) -> bool:
    """Store evidence on the bid. Returns True only when something changed.

    Idempotent by design: re-applying the same evidence (same source URL and
    items) leaves the row untouched, so repeated enrichment never bumps
    ``last_updated_at`` or triggers downstream re-processing.
    """
    if _same_evidence(getattr(bid, "boq_items", None), evidence):
        return False
    bid.boq_items = evidence
    bid.last_updated_at = datetime.now(timezone.utc)
    return True


def enrich_bid_from_source(
    bid: Any,
    *,
    session: Any = None,
    timeout: Optional[float] = None,
    max_items: Optional[int] = None,
    retrieved_at: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Fetch BoQ evidence for ``bid`` and store it. Does not commit."""
    evidence = fetch_boq_evidence(
        getattr(bid, "source_url", None) or "",
        session=session,
        timeout=timeout,
        max_items=max_items,
        retrieved_at=retrieved_at,
    )
    changed = apply_boq_evidence(bid, evidence)
    return {
        "bid_id": str(getattr(bid, "id", "")),
        "changed": changed,
        "item_count": evidence["item_count"],
        "source_url": evidence["source_url"],
        "evidence": evidence,
    }
