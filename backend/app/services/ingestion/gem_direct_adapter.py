"""
Direct GeM Public Source Adapter.

Converts bid records discovered on publicly reachable GeM pages into the
canonical ``RawBidRecord`` objects used by every other source in the
application. Registered in ``adapters.ADAPTER_MAP`` under ``gem_direct`` so it
is reachable through the same ``get_adapter()`` factory as JSON / CSV / XLSX.

Flow::

    GeM public page markup (HTML)
        -> GeMPublicAdapter
        -> List[RawBidRecord]
        -> existing ingestion pipeline

EXTRACTION PRINCIPLE
    Only values that literally appear on the page are mapped. A field the page
    does not print stays ``None`` and is reported as a missing field so the
    existing validator can reject or accept the record on evidence rather than
    on assumption. Nothing is inferred, completed or derived from another
    field.

FAILURE ISOLATION
    A malformed row never removes its neighbours. Each row is parsed inside its
    own guard; a row that raises is recorded and skipped, and the remaining rows
    on the page are still returned. ``parse_page_detailed`` and ``last_parse_
    failures`` expose exactly how many rows were lost and why, so a run can never
    quietly lose records without saying so.

SCOPE
    This is a public-page collector. It is *not* a GeM API client and its
    output must never be presented as "official GeM API" data.
"""
from __future__ import annotations

import html as html_lib
import logging
import re
from typing import Any, Dict, List, Optional, Tuple, Union
from urllib.parse import urljoin

from app.services.ingestion.schemas import RawBidRecord

logger = logging.getLogger(__name__)

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
# Script/style bodies are code, not page content.
_SCRIPT_STYLE_RE = re.compile(
    r"<(script|style|noscript)\b[^>]*>.*?</\1\s*>",
    re.IGNORECASE | re.DOTALL,
)

# Canonical fields the page parser may populate.
_EXTRACTABLE_FIELDS = (
    "gem_bid_id",
    "bid_number",
    "title",
    "organisation",
    "department",
    "ministry",
    "category",
    "bid_type",
    "published_date",
    "closing_date",
    "location",
    "estimated_value",
    "currency",
    "scope_of_work",
    "technical_requirements",
    "eligibility_criteria",
    "qualification_requirements",
    "experience_requirements",
    "certification_requirements",
    "emd_information",
    "tender_fee_information",
    "contact_information",
    "source_url",
)

# ---------------------------------------------------------------------------
# Row / card discovery
# ---------------------------------------------------------------------------
# ``card`` must be a whole whitespace-delimited class token, otherwise
# ``card-body`` / ``card-header`` would split a bid record in half.
_CARD_START_RE = re.compile(
    r"<div\b[^>]*\bclass\s*=\s*[\"'](?:[^\"']*\s)?card(?:\s[^\"']*)?[\"'][^>]*>",
    re.IGNORECASE,
)
_ROW_START_RE = re.compile(r"<tr\b[^>]*>", re.IGNORECASE)

# Field-level patterns, applied inside a single bid row.
_BID_NO_ANCHOR_RE = re.compile(
    r"<a\b[^>]*\bclass\s*=\s*[\"'][^\"']*\bbid_no_hover\b[^\"']*[\"'][^>]*>(?P<text>.*?)</a>",
    re.IGNORECASE | re.DOTALL,
)
_HREF_RE = re.compile(r"\bhref\s*=\s*[\"'](?P<href>[^\"']+)[\"']", re.IGNORECASE)
_DATA_BID_RE = re.compile(r"\bdata-bid\s*=\s*[\"'](?P<bid>\d+)[\"']", re.IGNORECASE)
_ITEMS_BLOCK_RE = re.compile(
    r"<strong>\s*Items?\s*:?\s*</strong>(?P<body>.*?)</div>",
    re.IGNORECASE | re.DOTALL,
)
_DATA_CONTENT_RE = re.compile(r"\bdata-content\s*=\s*[\"'](?P<content>[^\"']*)[\"']", re.IGNORECASE)
# GeM stamps its own item-group label here (e.g. "Nutritional Supplement",
# "ACSFP", "book PRINTING publication"). The visible ``title`` attribute is
# always empty; this one carries the real category text.
_DATA_ORIGINAL_TITLE_RE = re.compile(
    r"\bdata-original-title\s*=\s*[\"'](?P<value>[^\"']*)[\"']", re.IGNORECASE
)
_ANCHOR_TEXT_RE = re.compile(r"<a\b[^>]*>(?P<text>.*?)</a>", re.IGNORECASE | re.DOTALL)
_QUANTITY_RE = re.compile(
    r"<strong>\s*Quantity\s*:?\s*</strong>\s*(?P<value>[^<]*)",
    re.IGNORECASE,
)
_DEPARTMENT_RE = re.compile(
    r"<strong>\s*Department\s+Name\s+And\s+Address\s*:?\s*</strong>.*?"
    r"</div>\s*<div\b[^>]*>(?P<value>.*?)</div>",
    re.IGNORECASE | re.DOTALL,
)
_START_DATE_RE = re.compile(
    r"<span\b[^>]*\bclass\s*=\s*[\"'][^\"']*\bstart_date\b[^\"']*[\"'][^>]*>(?P<value>.*?)</span>",
    re.IGNORECASE | re.DOTALL,
)
_END_DATE_RE = re.compile(
    r"<span\b[^>]*\bclass\s*=\s*[\"'][^\"']*\bend_date\b[^\"']*[\"'][^>]*>(?P<value>.*?)</span>",
    re.IGNORECASE | re.DOTALL,
)
_CORRIGENDUM_RE = re.compile(r"view\s+corrigendum", re.IGNORECASE)

# Generic labelled fallbacks, used when a page revision does not use the
# card/table markup above. Only a label literally printed on the page counts.
_LABEL_RES = (
    ("closing_date", re.compile(r"(?:Bid\s+End\s+Date|End\s+Date|Due\s+Date)\s*:?\s*</?[^>]*>?\s*([^<]{4,60})", re.IGNORECASE)),
    ("published_date", re.compile(r"(?:Bid\s+Start\s+Date|Start\s+Date|Published\s+Date|Issue\s+Date)\s*:?\s*</?[^>]*>?\s*([^<]{4,60})", re.IGNORECASE)),
    ("organisation", re.compile(r"(?:Department\s+Name\s+And\s+Address|Organisation|Organization|Buyer)\s*:?\s*</?[^>]*>?\s*([^<]{2,200})", re.IGNORECASE)),
    ("title", re.compile(r"(?:Bid\s+Title|Title|Subject)\s*:?\s*</?[^>]*>?\s*([^<]{2,300})", re.IGNORECASE)),
    ("bid_number", re.compile(r"(?:Bid\s+(?:No|Number|Reference)|Tender\s+(?:No|Number|Reference))\s*:?\s*</?[^>]*>?\s*([^<]{2,80})", re.IGNORECASE)),
    ("estimated_value", re.compile(r"(?:Estimated\s+(?:Bid\s+)?Value|Bid\s+Value|Estimated\s+Cost)\s*:?\s*</?[^>]*>?\s*([^<]{2,80})", re.IGNORECASE)),
    ("location", re.compile(r"(?:Location|Place\s+of\s+Delivery|Supply\s+Location)\s*:?\s*</?[^>]*>?\s*([^<]{2,120})", re.IGNORECASE)),
    ("ministry", re.compile(r"(?:Ministry)\s*:?\s*</?[^>]*>?\s*([^<]{2,200})", re.IGNORECASE)),
    ("department", re.compile(r"(?:Department\s+Name|Department)\s*:?\s*</?[^>]*>?\s*([^<]{2,200})", re.IGNORECASE)),
)

# Label names GeM prints in prose/detail views. Used to bound the plain-text
# label scan below so a captured value stops at the *next* label instead of
# running to the end of the block.
_ALL_LABEL_NAMES = (
    r"Bid\s+End\s+Date|End\s+Date|Due\s+Date|Bid\s+Start\s+Date|Start\s+Date|"
    r"Published\s+Date|Issue\s+Date|Department\s+Name\s+And\s+Address|Department\s+Name|"
    r"Department|Organisation|Organization|Buyer|Ministry|Bid\s+Title|Title|Subject|"
    r"Bid\s+(?:No|Number|Reference)|Tender\s+(?:No|Number|Reference)|"
    r"Estimated\s+(?:Bid\s+)?Value|Bid\s+Value|Estimated\s+Cost|"
    r"Location|Place\s+of\s+Delivery|Supply\s+Location"
)

# Second-pass patterns applied to the *plain text* of a block. GeM prints
# "Label: value" without any separating tag on some views, which the
# tag-oriented patterns above cannot see.
_TEXT_LABEL_RES = (
    ("bid_number", re.compile(rf"(?:Bid\s+(?:No|Number|Reference)|Tender\s+(?:No|Number|Reference))\s*:\s*(.+?)(?=\s*(?:{_ALL_LABEL_NAMES})\s*:|\s*$)", re.IGNORECASE)),
    ("title", re.compile(rf"(?:Bid\s+Title|Title|Subject)\s*:\s*(.+?)(?=\s*(?:{_ALL_LABEL_NAMES})\s*:|\s*$)", re.IGNORECASE)),
    ("published_date", re.compile(rf"(?:Bid\s+Start\s+Date|Start\s+Date|Published\s+Date|Issue\s+Date)\s*:\s*(.+?)(?=\s*(?:{_ALL_LABEL_NAMES})\s*:|\s*$)", re.IGNORECASE)),
    ("closing_date", re.compile(rf"(?:Bid\s+End\s+Date|End\s+Date|Due\s+Date)\s*:\s*(.+?)(?=\s*(?:{_ALL_LABEL_NAMES})\s*:|\s*$)", re.IGNORECASE)),
    ("estimated_value", re.compile(rf"(?:Estimated\s+(?:Bid\s+)?Value|Bid\s+Value|Estimated\s+Cost)\s*:\s*(.+?)(?=\s*(?:{_ALL_LABEL_NAMES})\s*:|\s*$)", re.IGNORECASE)),
    ("location", re.compile(rf"(?:Location|Place\s+of\s+Delivery|Supply\s+Location)\s*:\s*(.+?)(?=\s*(?:{_ALL_LABEL_NAMES})\s*:|\s*$)", re.IGNORECASE)),
    ("organisation", re.compile(rf"(?:Department\s+Name\s+And\s+Address|Organisation|Organization|Buyer)\s*:\s*(.+?)(?=\s*(?:{_ALL_LABEL_NAMES})\s*:|\s*$)", re.IGNORECASE)),
    ("department", re.compile(rf"(?:Department\s+Name|Department)\s*:\s*(.+?)(?=\s*(?:{_ALL_LABEL_NAMES})\s*:|\s*$)", re.IGNORECASE)),
    ("ministry", re.compile(rf"(?:Ministry)\s*:\s*(.+?)(?=\s*(?:{_ALL_LABEL_NAMES})\s*:|\s*$)", re.IGNORECASE)),
)

# A genuine GeM bid reference has the shape GEM/<year>/<type>/<number>, e.g.
# GEM/2026/B/7845020. The strict shape is required on purpose: a loose pattern
# also matches navigation labels such as "Bid/RA", which would turn site chrome
# into a fake bid record.
_BID_REF_RE = re.compile(
    r"\bGEM\s*[/\\-]\s*\d{4}\s*[/\\-]\s*[A-Z0-9]{1,4}\s*[/\\-]\s*\d+\b",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _text(fragment: Optional[str]) -> Optional[str]:
    """Flatten an HTML fragment to plain text, or ``None`` when it is empty."""
    if fragment is None:
        return None
    without_tags = _TAG_RE.sub(" ", fragment)
    decoded = html_lib.unescape(without_tags).replace("\u00a0", " ")
    cleaned = _WS_RE.sub(" ", decoded).strip()
    return cleaned or None


def _lines(fragment: Optional[str]) -> List[str]:
    """Return the meaningful printed lines of an HTML fragment."""
    if fragment is None:
        return []
    with_breaks = re.sub(r"<\s*br\s*/?\s*>", "\n", fragment, flags=re.IGNORECASE)
    with_breaks = re.sub(r"</\s*(?:div|p|li|tr)\s*>", "\n", with_breaks, flags=re.IGNORECASE)
    decoded = html_lib.unescape(_TAG_RE.sub(" ", with_breaks)).replace("\u00a0", " ")
    out: List[str] = []
    for line in decoded.splitlines():
        cleaned = _WS_RE.sub(" ", line).strip()
        if cleaned:
            out.append(cleaned)
    return out


def _split_org_lines(lines: List[str]) -> Dict[str, Optional[str]]:
    """
    Decompose the printed department block into ministry / department.

    GeM prints the block as one or more literal lines. A line that literally
    starts with "Ministry" becomes ``ministry``; when exactly one other line
    remains it becomes ``department``. Anything else is left to ``organisation``
    so no structure is invented.
    """
    result: Dict[str, Optional[str]] = {"ministry": None, "department": None}
    if not lines:
        return result
    ministry_lines = [ln for ln in lines if ln.lower().startswith("ministry")]
    other_lines = [ln for ln in lines if not ln.lower().startswith("ministry")]
    if len(ministry_lines) == 1:
        result["ministry"] = ministry_lines[0]
    elif len(ministry_lines) > 1:
        result["ministry"] = None
    if len(other_lines) == 1:
        result["department"] = other_lines[0]
    return result


def _iter_blocks(markup: str) -> List[str]:
    """
    Split markup into candidate bid blocks.

    Prefers ``div.card`` blocks (the current public listing markup) and falls
    back to table rows so a markup revision does not silently produce zero
    records.
    """
    starts = [m.start() for m in _CARD_START_RE.finditer(markup)]
    if starts:
        bounds = starts + [len(markup)]
        return [markup[bounds[i]: bounds[i + 1]] for i in range(len(starts))]

    row_starts = [m.start() for m in _ROW_START_RE.finditer(markup)]
    if row_starts:
        bounds = row_starts + [len(markup)]
        return [markup[bounds[i]: bounds[i + 1]] for i in range(len(row_starts))]

    return [markup]


def _apply_label_fallbacks(block: str, fields: Dict[str, Any]) -> None:
    """Fill still-missing fields from labels literally present in the block.

    Two passes are used. The first works on the raw markup and covers
    tag-separated labels such as ``<td>Bid Title</td><td>Value</td>``. The
    second works on the plain text and covers bare ``Label: value`` prose,
    which is how some GeM views print fields.
    """
    for canonical, pattern in _LABEL_RES:
        if fields.get(canonical):
            continue
        match = pattern.search(block)
        if not match:
            continue
        value = _text(match.group(1))
        if value:
            fields[canonical] = value

    text = _text(block)
    if not text:
        return
    for canonical, pattern in _TEXT_LABEL_RES:
        if fields.get(canonical):
            continue
        match = pattern.search(text)
        if not match:
            continue
        value = _text(match.group(1))
        if value:
            fields[canonical] = value


def missing_fields(record: RawBidRecord) -> List[str]:
    """Canonical fields that the page did not actually print."""
    return [
        field
        for field in _EXTRACTABLE_FIELDS
        if getattr(record, field, None) in (None, "")
    ]


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------
class GeMPublicAdapter:
    """
    Converts rendered public GeM page markup into canonical ``RawBidRecord``s.

    Registered in ``adapters.ADAPTER_MAP`` under ``gem_direct``.
    """

    adapter_name = "GeMPublicAdapter"

    def __init__(self) -> None:
        #: Parse failures recorded by the most recent parse call, oldest first.
        self.last_parse_failures: List[Dict[str, Any]] = []

    def parse(
        self,
        data: Union[bytes, str, Dict[str, Any], List[Dict[str, Any]]],
        source_name: str = "gem_direct",
        **kwargs: Any,
    ) -> List[RawBidRecord]:
        """
        Parse one or more collected GeM pages into canonical records.

        ``data`` may be raw HTML (``bytes``/``str``) or the collector's payload
        dictionaries (``{"url": ..., "html": ...}``).
        """
        return self.parse_detailed(data, source_name=source_name, **kwargs)[0]

    def parse_detailed(
        self,
        data: Union[bytes, str, Dict[str, Any], List[Dict[str, Any]]],
        source_name: str = "gem_direct",
        **kwargs: Any,
    ) -> Tuple[List[RawBidRecord], List[Dict[str, Any]], int]:
        """
        Parse collected pages and report what could not be parsed.

        Returns ``(records, parse_failures, rows_seen)``. ``rows_seen`` counts
        every bid row encountered, including rows that were skipped, so a caller
        can distinguish "the source had nothing" from "the parser dropped rows".
        """
        if isinstance(data, (bytes, bytearray)):
            data = data.decode("utf-8", errors="replace")

        if isinstance(data, dict):
            data = [data]
        elif isinstance(data, str):
            data = [{"url": kwargs.get("source_url"), "html": data}]
        elif not isinstance(data, list):
            raise ValueError(
                f"{self.adapter_name} expects page markup or collected page dicts, got {type(data)}"
            )

        records: List[RawBidRecord] = []
        failures: List[Dict[str, Any]] = []
        rows_seen = 0
        for page_index, payload in enumerate(data):
            if not isinstance(payload, dict):
                failures.append(
                    {"page": page_index, "row": None, "message": f"Page payload {page_index} is not a mapping."}
                )
                continue
            markup = payload.get("html")
            if markup is None:
                markup = payload.get("content")
            if not isinstance(markup, str):
                failures.append(
                    {"page": page_index, "row": None, "message": f"Page payload {page_index} carried no HTML."}
                )
                continue
            page_url = payload.get("url") or payload.get("source_url") or kwargs.get("source_url")
            page_records, page_failures, page_rows = self.parse_page_detailed(
                markup, page_url, source_name=source_name
            )
            records.extend(page_records)
            rows_seen += page_rows
            for failure in page_failures:
                failures.append({"page": payload.get("page", page_index), **failure})

        self.last_parse_failures = failures
        return records, failures, rows_seen

    # ------------------------------------------------------------------
    def parse_page(
        self,
        markup: str,
        source_url: Optional[str] = None,
        source_name: str = "gem_direct",
    ) -> List[RawBidRecord]:
        """
        Parse a single rendered GeM page into zero or more canonical records.

        A block only becomes a record when a bid reference is genuinely printed
        inside it; blocks without one are skipped rather than turned into
        partial, invented bids. A block that cannot be parsed is recorded and
        skipped without affecting the other blocks on the page.
        """
        records, failures, _rows = self.parse_page_detailed(
            markup, source_url=source_url, source_name=source_name
        )
        self.last_parse_failures = failures
        return records

    def parse_page_detailed(
        self,
        markup: str,
        source_url: Optional[str] = None,
        source_name: str = "gem_direct",
    ) -> Tuple[List[RawBidRecord], List[Dict[str, Any]], int]:
        """
        Parse one page and report per-row failures.

        Returns ``(records, failures, rows_seen)``. A row is counted in
        ``rows_seen`` whenever it carries a bid reference, whether or not it
        could be turned into a record.
        """
        failures: List[Dict[str, Any]] = []
        if not markup or not isinstance(markup, str):
            return [], failures, 0

        # JavaScript/CSS source is not page content. The public listing builds
        # its cards from string templates inside <script>, so those blocks are
        # removed before parsing to avoid reading code as a bid record.
        markup = _SCRIPT_STYLE_RE.sub(" ", markup)

        blocks = _iter_blocks(markup)
        records: List[RawBidRecord] = []
        rows_seen = 0
        for index, block in enumerate(blocks):
            has_reference = bool(_extract_reference(_text(block)))
            if has_reference:
                rows_seen += 1
            try:
                record = self._parse_block(block, source_url=source_url, source_name=source_name)
            except Exception as exc:  # noqa: BLE001 - one bad row must not lose the page
                logger.warning(
                    "Skipping unparsable GeM bid row %d on %s: %s", index, source_url, exc
                )
                failures.append(
                    {
                        "row": index,
                        "bid_reference": _extract_reference(_text(block)),
                        "message": f"{type(exc).__name__}: {exc}",
                    }
                )
                continue
            if record is not None:
                records.append(record)
            elif has_reference:
                failures.append(
                    {
                        "row": index,
                        "bid_reference": _extract_reference(_text(block)),
                        "message": "Row printed a bid reference but no record could be built from it.",
                    }
                )
        return records, failures, rows_seen

    # ------------------------------------------------------------------
    def parse_detail_page(
        self,
        markup: Optional[str],
        source_url: Optional[str] = None,
        source_name: str = "gem_direct",
    ) -> Optional[RawBidRecord]:
        """
        Parse an optional detail page.

        Returns ``None`` when the detail page yields nothing usable. Callers must
        keep the listing-derived record: detail data enriches a bid, it never
        decides whether the bid exists.
        """
        if not markup or not isinstance(markup, str):
            return None
        try:
            records = self.parse_page(markup, source_url=source_url, source_name=source_name)
        except Exception as exc:  # noqa: BLE001 - enrichment must never fail a run
            logger.warning("GeM detail page %s could not be parsed: %s", source_url, exc)
            return None
        return records[0] if records else None

    # ------------------------------------------------------------------
    def _parse_block(
        self,
        block: str,
        source_url: Optional[str],
        source_name: str,
    ) -> Optional[RawBidRecord]:
        fields: Dict[str, Any] = {}

        anchor = _BID_NO_ANCHOR_RE.search(block)
        bid_reference = _text(anchor.group("text")) if anchor else None
        if not bid_reference:
            # Fall back to any printed GeM-style reference in the block.
            bid_reference = _extract_reference(_text(block))

        detail_href = None
        if anchor is not None:
            href_match = _HREF_RE.search(anchor.group(0))
            if href_match:
                detail_href = html_lib.unescape(href_match.group("href")).strip()

        if not bid_reference:
            return None

        fields["bid_number"] = bid_reference
        fields["gem_bid_id"] = bid_reference

        # --- Items / description ------------------------------------------
        items_block = _ITEMS_BLOCK_RE.search(block)
        if items_block:
            body = items_block.group("body")
            content_attr = _DATA_CONTENT_RE.search(body)
            items_full = html_lib.unescape(content_attr.group("content")).strip() if content_attr else None
            items_link = _ANCHOR_TEXT_RE.search(body)
            items_short = _text(items_link.group("text")) if items_link else None
            # Some rows print the item description as plain text with no anchor.
            items_plain = _text(body)
            items = items_full or items_short or items_plain
            if items:
                fields["title"] = items
                if items_full and items_short and items_full != items_short:
                    fields["scope_of_work"] = items_full

            # GeM's own item-group label. The matcher reads ``category``, and
            # this is the only category-like text the listing exposes, so it
            # is recorded verbatim rather than left empty.
            category_match = _DATA_ORIGINAL_TITLE_RE.search(block)
            if category_match:
                category_value = _text(category_match.group("value"))
                if category_value:
                    fields["category"] = category_value

        quantity = _QUANTITY_RE.search(block)
        if quantity:
            quantity_value = _text(quantity.group("value"))
            if quantity_value:
                fields.setdefault("contact_information", None)
                fields["_quantity"] = quantity_value

        department_match = _DEPARTMENT_RE.search(block)
        org_fragments: List[str] = []
        if department_match:
            org_fragments = _lines(department_match.group("value"))
        org_text = _text(" ".join(org_fragments)) if org_fragments else None
        if org_text:
            fields["organisation"] = org_text
            org_split = _split_org_lines(org_fragments)
            if org_split["ministry"]:
                fields["ministry"] = org_split["ministry"]
            if org_split["department"]:
                fields["department"] = org_split["department"]

        start_date = _START_DATE_RE.search(block)
        if start_date:
            value = _text(start_date.group("value"))
            if value:
                fields["published_date"] = value

        end_date = _END_DATE_RE.search(block)
        if end_date:
            value = _text(end_date.group("value"))
            if value:
                fields["closing_date"] = value

        _apply_label_fallbacks(block, fields)

        # --- Provenance ---------------------------------------------------
        detail_url = None
        if detail_href and source_url:
            detail_url = urljoin(source_url, detail_href)
        fields["source_url"] = detail_url or source_url

        internal_bid_id = None
        data_bid = _DATA_BID_RE.search(block)
        if data_bid:
            internal_bid_id = data_bid.group("bid")

        has_corrigendum_link = bool(_CORRIGENDUM_RE.search(block))
        quantity_value = fields.pop("_quantity", None)

        audit: Dict[str, Any] = {
            "adapter": self.adapter_name,
            "collection_method": "direct_public_page",
            "listing_url": source_url,
            "detail_url": detail_url,
            "gem_internal_bid_id": internal_bid_id,
            "quantity": quantity_value,
            "corrigendum_link_present": has_corrigendum_link,
            "detail_document_content_type": fields.pop("_detail_content_type", None),
        }

        record = RawBidRecord(
            **{
                key: value
                for key, value in fields.items()
                if key in RawBidRecord.model_fields
            },
            source_name=source_name,
        )
        record._raw = {
            **audit,
            "extracted_fields": [f for f in _EXTRACTABLE_FIELDS if getattr(record, f, None)],
            "missing_fields": missing_fields(record),
            "page_excerpt": (_text(block) or "")[:2000],
        }
        return record


def _extract_reference(text: Optional[str]) -> Optional[str]:
    """Return the first GeM-style bid reference printed in ``text``."""
    if not text:
        return None
    match = _BID_REF_RE.search(text)
    return match.group(0).strip() if match else None


# Backwards-compatible alias matching the naming of the other adapters.
GeMDirectAdapter = GeMPublicAdapter