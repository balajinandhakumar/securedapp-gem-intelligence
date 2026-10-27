"""
Direct GeM Public Bid Collector.

Collects bid records straight from publicly reachable GeM pages (no
third-party tender-data provider, no scraping API, no GeM credentials).

Flow::

    GeM public listing page (https://bidplus.gem.gov.in/all-bids)
        -> GeMPublicCollector  (plain HTTP; Playwright only when enabled)
        -> GeMPublicAdapter   -> canonical RawBidRecord
        -> existing validation / normalization / deduplication / persistence
        -> existing 11-product matching / relevance / opportunity
        -> existing notifications -> dashboard

SCOPE AND COMPLIANCE
    * Only pages that are publicly reachable without login are requested.
    * Every request target must pass a host allowlist (default:
      ``gem.gov.in``, ``bidplus.gem.gov.in``) before any socket is opened, so
      the collector can never be pointed at an arbitrary or internal host.
    * No CAPTCHA solving, no login, no header spoofing, no proxy rotation and
      no other access-control evasion is implemented. When GeM answers with
      403/429 or an equivalent block signal, the collector stops and reports.
    * Requests are conservative: one at a time by default, a configurable
      delay between pages, bounded retries with exponential backoff.
    * This is a public-page collector. It is **not** a GeM API client and the
      output must never be described as "official GeM API" data.
"""
from __future__ import annotations

import asyncio
import html
import logging
import re
import sys
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

import requests

from app.core.config import settings

logger = logging.getLogger(__name__)

# Only plain web schemes are ever requested. Anything else (file:, ftp:,
# data:, gopher:, ...) is rejected before a request is made.
ALLOWED_SCHEMES = ("http", "https")

# Canonical public listing page used by the manual "Fetch GeM Bids" action.
DEFAULT_LISTING_URL = "https://bidplus.gem.gov.in/all-bids"

# ---------------------------------------------------------------------------
# Pagination facts about the real public listing page
# ---------------------------------------------------------------------------
# The "All Bids" page is a JavaScript shell. On load it POSTs to
# https://bidplus.gem.gov.in/all-bids-data with
#     payload = {"page": n, "param": {...}, "filter": {...}}
# and renders a fixed number of bid cards per page into #bidCard. It prints
#     "Showing <start> - <end> records of <total> records"
# and builds a #light-pagination widget (jquery.simplePagination) whose last
# numbered link is the final available page. A page request beyond the end
# renders zero cards. Those three facts -- the card count per page, the printed
# record total and the widget's page links -- are the only pagination signals
# used here; none of them is guessed.
GEM_PAGE_SIZE = 10

# Row markup the listing renders, and the container it renders into.
_LISTING_ROW_SELECTORS = (
    "table tbody tr",
    "div.card",
    "div.bid-list-item",
    "li.bid-item",
)

# Path fragments that identify a genuine public bid detail page.
_DETAIL_PATH_MARKERS = (
    "/bid/show/",
    "/showbid",
    "/bidplus/show",
)

_BLOCK_MARKERS = (
    "captcha",
    "access denied",
    "verify you are human",
    "are you a robot",
    "request blocked",
    "too many requests",
    "security check",
)

_CAPTCHA_HINT_RE = re.compile(r"(recaptcha|hcaptcha|turnstile|g-recaptcha|captcha)", re.IGNORECASE)
_SCRIPT_RE = re.compile(r"<(script|style|noscript)\b.*?</\1>", re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_BLOCK_SIGNAL_RE = re.compile(
    r"captcha|access denied|verify you are human|are you a robot|request blocked|"
    r"too many requests|security check|forbidden|unusual traffic",
    re.IGNORECASE,
)

# Bid references GeM actually prints, e.g. GEM/2026/B/1234567. The strict
# shape is required: a looser pattern also matches navigation labels such as
# "Bid/RA", which would turn site chrome into a fake bid reference.
_BID_REF_RE = re.compile(
    r"\bGEM\s*[/\\-]\s*\d{4}\s*[/\\-]\s*[A-Z0-9]{1,4}\s*[/\\-]\s*\d+\b",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class GeMCollectorError(Exception):
    """Base error for transport / parsing failures of the direct collector."""

    def __init__(
        self,
        message: str,
        status_code: Optional[int] = None,
        stage: str = "request",
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.stage = stage


class GeMUrlNotPermittedError(GeMCollectorError):
    """Raised when a target fails the public-URL / host-allowlist checks."""


class GeMBlockedError(GeMCollectorError):
    """
    Raised when GeM refuses automated collection (403 / 429 / block page).

    The collector never attempts to work around a block; callers must stop
    and surface the condition.
    """

    def __init__(self, message: str, status_code: Optional[int] = None, stage: str = "request") -> None:
        super().__init__(message, status_code=status_code, stage=stage)


class GeMParseError(GeMCollectorError):
    """Raised when a response body cannot be interpreted as a GeM page."""

    def __init__(self, message: str, stage: str = "parse") -> None:
        super().__init__(message, status_code=None, stage=stage)


# ---------------------------------------------------------------------------
# Public URL validation (SSRF / scope guardrail)
# ---------------------------------------------------------------------------
def allowed_hosts() -> List[str]:
    """Return the normalized host allowlist for outbound GeM collection."""
    raw = getattr(settings, "GEM_DIRECT_ALLOWED_HOSTS", "") or ""
    if isinstance(raw, (list, tuple, set)):
        candidates = [str(h) for h in raw]
    else:
        candidates = str(raw).split(",")
    hosts: List[str] = []
    for host in candidates:
        cleaned = host.strip().lower().lstrip(".")
        if cleaned:
            hosts.append(cleaned)
    return hosts


def _is_private_host(host: str) -> bool:
    """Reject loopback / link-local / RFC1918 style literals."""
    if host in {"localhost", "localhost.localdomain"} or host.endswith(".local"):
        return True
    if host in {"0.0.0.0", "::1"} or host.startswith("127.") or host.startswith("10."):
        return True
    if host.startswith("192.168.") or host.startswith("169.254."):
        return True
    if host.startswith("172."):
        parts = host.split(".")
        if len(parts) > 1 and parts[1].isdigit():
            second = int(parts[1])
            if 16 <= second <= 31:
                return True
    return False


def validate_public_url(url: Optional[str]) -> str:
    """
    Validate a GeM target before any network call is made.

    Enforces an absolute http(s) URL, rejects private/loopback hosts, and
    requires the host (or one of its parents) to be inside the configured
    allowlist. This is the guardrail that prevents arbitrary URL fetching.
    """
    if url is None or not str(url).strip():
        raise GeMUrlNotPermittedError("No URL supplied for GeM collection.", status_code=400)

    candidate = str(url).strip()
    try:
        parsed = urlparse(candidate)
    except Exception as exc:  # pragma: no cover - urlparse is very tolerant
        raise GeMUrlNotPermittedError(f"Supplied URL could not be parsed: {exc}", status_code=400) from exc

    if parsed.scheme.lower() not in ALLOWED_SCHEMES:
        raise GeMUrlNotPermittedError(
            "Only public http/https URLs may be collected.", status_code=400
        )

    host = (parsed.hostname or "").lower()
    if not host:
        raise GeMUrlNotPermittedError("Supplied URL does not contain a valid host.", status_code=400)

    if _is_private_host(host):
        raise GeMUrlNotPermittedError(
            f"Host '{host}' resolves to a private or loopback address and is not collectable.",
            status_code=403,
        )

    permitted_hosts = allowed_hosts()
    if not permitted_hosts:
        raise GeMUrlNotPermittedError(
            "No GeM host allowlist is configured (GEM_DIRECT_ALLOWED_HOSTS).", status_code=403
        )

    for permitted in permitted_hosts:
        if host == permitted or host.endswith(f".{permitted}"):
            return candidate

    raise GeMUrlNotPermittedError(
        f"Host '{host}' is not in the configured GeM allowlist "
        f"({', '.join(permitted_hosts)}). Only these public GeM hosts may be collected.",
        status_code=403,
    )


def resolve_collection_targets(
    urls: Optional[Iterable[str]] = None,
    include_configured: bool = True,
) -> Tuple[List[str], List[str], List[Dict[str, str]]]:
    """
    Turn caller-supplied URLs into a validated, de-duplicated, budgeted list.

    Returns ``(accepted, rejected, errors)``. Rejected URLs never reach the
    network.
    """
    accepted: List[str] = []
    rejected: List[str] = []
    errors: List[Dict[str, str]] = []
    seen: set = set()

    candidates: List[str] = []
    for raw in urls or []:
        if raw and str(raw).strip():
            candidates.append(str(raw).strip())

    if include_configured:
        configured = getattr(settings, "GEM_DIRECT_APPROVED_URLS", "") or ""
        if isinstance(configured, (list, tuple, set)):
            extra = [str(u).strip() for u in configured]
        else:
            extra = [u.strip() for u in str(configured).split(",")]
        for url in extra:
            if url:
                candidates.append(url)

    budget = max(1, int(getattr(settings, "GEM_DIRECT_MAX_URLS_PER_RUN", 10)))
    for candidate in candidates:
        if candidate in seen:
            rejected.append(candidate)
            errors.append({"field": "url", "message": f"{candidate}: duplicate URL."})
            continue
        seen.add(candidate)
        try:
            permitted = validate_public_url(candidate)
        except GeMUrlNotPermittedError as exc:
            rejected.append(candidate)
            errors.append({"field": "url", "message": f"{candidate}: {exc.message}"})
            continue
        if len(accepted) >= budget:
            errors.append(
                {
                    "field": "url",
                    "message": (
                        f"{candidate}: skipped, per-run budget of {budget} URL(s) reached."
                    ),
                }
            )
            rejected.append(candidate)
            continue
        accepted.append(permitted)

    return accepted, rejected, errors


def is_detail_url(url: Optional[str]) -> bool:
    """True when the URL path looks like a public GeM bid detail page."""
    if not url:
        return False
    try:
        path = urlparse(url).path.lower()
    except Exception:
        return False
    return any(marker in path for marker in _DETAIL_PATH_MARKERS)


# ---------------------------------------------------------------------------
# HTML helpers (dependency-free, tolerant of malformed markup)
# ---------------------------------------------------------------------------
def html_to_text(markup: Optional[str]) -> str:
    """Flatten HTML into readable text without inventing any content."""
    if not markup:
        return ""
    stripped = _SCRIPT_RE.sub(" ", markup)
    stripped = re.sub(r"<br\s*/?>", "\n", stripped, flags=re.IGNORECASE)
    stripped = re.sub(r"</(p|div|tr|li|h[1-6]|td|th)>", "\n", stripped, flags=re.IGNORECASE)
    text = _TAG_RE.sub(" ", stripped)
    text = html.unescape(text)
    text = text.replace("\u00a0", " ")
    lines = [_WS_RE.sub(" ", line).strip() for line in text.splitlines()]
    return "\n".join([line for line in lines if line])


def extract_links(markup: Optional[str], base_url: str) -> List[Tuple[str, str]]:
    """
    Return ``(absolute_url, anchor_text)`` pairs found in the markup.

    Relative hrefs are resolved against ``base_url``. Only http(s) links on the
    allowlisted GeM hosts are returned.
    """
    if not markup:
        return []

    allowed = allowed_hosts()
    results: List[Tuple[str, str]] = []
    seen: set = set()

    for match in re.finditer(
        r"<a\b[^>]*?href\s*=\s*([\"'])(?P<href>.*?)\1[^>]*>(?P<text>.*?)</a>",
        markup,
        re.IGNORECASE | re.DOTALL,
    ):
        href = html.unescape(match.group("href").strip())
        if not href or href.lower().startswith(("javascript:", "mailto:", "#")):
            continue
        absolute = urljoin(base_url, href)
        if absolute in seen:
            continue
        try:
            parsed = urlparse(absolute)
        except Exception:
            continue
        if parsed.scheme.lower() not in ALLOWED_SCHEMES:
            continue
        host = (parsed.hostname or "").lower()
        if not host:
            continue
        if not any(host == h or host.endswith(f".{h}") for h in allowed):
            continue
        seen.add(absolute)
        results.append((absolute, html_to_text(match.group("text"))))

    return results


def looks_blocked(status_code: Optional[int], markup: Optional[str]) -> bool:
    """Detect a refusal response (status code and/or block-page body)."""
    if status_code in (401, 403, 429, 451):
        return True
    if status_code is not None and status_code >= 500:
        return False
    if not markup:
        return False
    lowered = markup[:20000].lower()
    if any(marker in lowered for marker in _BLOCK_MARKERS):
        return True
    return bool(_BLOCK_SIGNAL_RE.search(html_to_text(markup)[:4000]))


def extract_bid_reference(text: Optional[str]) -> Optional[str]:
    """Return the first GeM-style bid reference printed in ``text``."""
    if not text:
        return None
    match = _BID_REF_RE.search(text)
    if not match:
        return None
    return _WS_RE.sub(" ", match.group(0)).strip() or None


def extract_bid_references(text: Optional[str]) -> List[str]:
    """Return every distinct GeM-style bid reference printed in ``text``."""
    if not text:
        return []
    seen: List[str] = []
    known: set = set()
    for match in _BID_REF_RE.finditer(text):
        ref = _WS_RE.sub(" ", match.group(0)).strip()
        if ref and ref not in known:
            known.add(ref)
            seen.append(ref)
    return seen


# ---------------------------------------------------------------------------
# Pagination state (pure functions over the rendered listing fragment)
# ---------------------------------------------------------------------------
# "Showing 11 - 20 records of 44006 records"
_SHOWING_RE = re.compile(
    r"Showing\s+(?P<start>[\d,]+)\s*-\s*(?P<end>[\d,]+)\s+records?\s+of\s+(?P<total>[\d,]+)\s+records?",
    re.IGNORECASE,
)

# The widget container, up to the next element that carries its own id.
_PAGINATION_BLOCK_RE = re.compile(
    r"<(?:div|ul|nav)\b[^>]*\bid\s*=\s*[\"']light-pagination[\"'][^>]*>(?P<body>.*?)"
    r"(?=<(?:div|ul|nav)\b[^>]*\bid\s*=|\Z)",
    re.IGNORECASE | re.DOTALL,
)

# Anchors/links of the widget, e.g. <a href="#page-3" class="page-link">3</a>
# and <a href="#page-2" class="page-link next">Next</a>.
_PAGE_LINK_RE = re.compile(
    r"<a\b[^>]*\bclass\s*=\s*[\"'](?P<cls>[^\"']*\bpage-link\b[^\"']*)[\"'][^>]*>(?P<text>.*?)</a>",
    re.IGNORECASE | re.DOTALL,
)
_CURRENT_MARKER_RE = re.compile(
    r"<(?:span|a)\b[^>]*\bclass\s*=\s*[\"'][^\"']*\bcurrent\b[^\"']*[\"'][^>]*>(?P<text>.*?)</(?:span|a)>",
    re.IGNORECASE | re.DOTALL,
)


def _to_int(value: Optional[str]) -> Optional[int]:
    try:
        return int(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def parse_showing_count(markup: Optional[str]) -> Optional[Dict[str, int]]:
    """
    Read GeM's own result counter.

    Returns ``{"start": int, "end": int, "total": int}`` or ``None`` when the
    counter is not printed. Nothing is inferred: an absent counter yields
    ``None`` so the caller knows the total is unknown.
    """
    if not markup:
        return None
    match = _SHOWING_RE.search(html_to_text(markup)[:4000]) or _SHOWING_RE.search(markup)
    if not match:
        return None
    start, end, total = _to_int(match.group("start")), _to_int(match.group("end")), _to_int(match.group("total"))
    if start is None or end is None or total is None:
        return None
    return {"start": start, "end": end, "total": total}


def parse_pagination_state(markup: Optional[str]) -> Dict[str, Any]:
    """
    Read the listing's pagination widget.

    Returns ``{"current_page", "total_pages", "has_next", "has_prev"}`` where
    ``current_page``/``total_pages`` are ``None`` when the widget does not say.

    The widget always prints the final page as a numbered link *and* prints a
    ``1`` link once the current page has moved past the head of the window, so the
    largest numbered link is only the last page while the current page is still
    inside the leading window. The total is therefore taken from the links that
    sit ahead of the current page, never from ``1``.
    ``prev``/``next`` are rendered as ``span.current`` when disabled, so a real
    ``a.page-link.next`` anchor means a next page exists.
    """
    state: Dict[str, Any] = {
        "current_page": None,
        "total_pages": None,
        "has_next": False,
        "has_prev": False,
    }
    if not markup:
        return state

    block_match = _PAGINATION_BLOCK_RE.search(markup)
    block = block_match.group("body") if block_match else markup

    numbered: List[int] = []
    next_anchor = False
    prev_anchor = False
    for link in _PAGE_LINK_RE.finditer(block):
        classes = link.group("cls").lower()
        if "next" in classes.split():
            next_anchor = True
        if "prev" in classes.split():
            prev_anchor = True
        page_number = _to_int(html_to_text(link.group("text")))
        if page_number and page_number > 0:
            numbered.append(page_number)

    for marker in _CURRENT_MARKER_RE.finditer(block):
        text = html_to_text(marker.group("text")) or ""
        if text.lower() in ("prev", "next", "previous", ""):
            continue
        page_number = _to_int(text)
        if page_number:
            state["current_page"] = page_number
            break

    if state["current_page"] is None:
        # Without a current marker the widget is ambiguous; the highest link is
        # the best evidence available and is reported as such.
        state["total_pages"] = max(numbered) if numbered else None
    else:
        ahead = [page for page in numbered if page > state["current_page"]]
        if ahead:
            state["total_pages"] = max(ahead)
        elif not next_anchor:
            # The window has no link beyond the current page and no next anchor:
            # this is the last page the listing is willing to show.
            state["total_pages"] = state["current_page"]
        else:
            # A next page is offered but the widget has not printed the last page
            # yet. The total is genuinely unknown, and claiming otherwise would
            # truncate collection at the edge of the visible window.
            state["total_pages"] = None

    state["has_next"] = next_anchor or (
        state["total_pages"] is not None
        and state["current_page"] is not None
        and state["total_pages"] > state["current_page"]
    )
    state["has_prev"] = prev_anchor
    return state


# Opening tags of the listing's own row containers. A class attribute may carry
# several names, so "card" may appear anywhere in the quoted list.
_CARD_ELEMENT_START_RE = re.compile(
    r"<div\b[^>]*\bclass\s*=\s*[\"'][^\"']*\bcard\b[^\"']*[\"'][^>]*>",
    re.IGNORECASE,
)
_ROW_ELEMENT_START_RE = re.compile(r"<tr\b[^>]*>", re.IGNORECASE)


def _split_balanced_elements(
    markup: str,
    tag: str,
    start_pattern: "re.Pattern[str]",
) -> List[str]:
    """
    Return every element whose opening tag matches ``start_pattern``, whole.

    A bid card contains nested ``<div>``s, so a non-greedy ``.*?</div>`` would cut
    every row short at its first inner ``</div>`` and silently drop fields that
    live deeper in the row. This walks the tag stream and copies each matched
    element through to its own closing tag, which is what the browser hands back
    as ``outerHTML``.
    """
    open_tag = re.compile(rf"<{tag}\b", re.IGNORECASE)
    any_tag = re.compile(rf"<(/?){tag}\b[^>]*?(/?)>", re.IGNORECASE | re.DOTALL)
    elements: List[str] = []
    position = 0
    length = len(markup)

    while position < length:
        match = start_pattern.search(markup, position)
        if match is None:
            break
        opener = open_tag.match(markup, match.start())
        if opener is None:
            position = match.end()
            continue

        depth = 0
        cursor = opener.start()
        while cursor < length:
            tag_match = any_tag.search(markup, cursor)
            if tag_match is None:
                break
            if tag_match.group(1):  # closing tag
                depth -= 1
                if depth == 0:
                    elements.append(markup[opener.start(): tag_match.end()])
                    position = tag_match.end()
                    break
            elif not tag_match.group(2):  # opening tag, not self-closed
                depth += 1
            cursor = tag_match.end()
        else:
            # Unterminated element: keep what the page printed rather than
            # discarding the row entirely.
            elements.append(markup[opener.start():])
            position = length
            break
        if cursor >= length:
            elements.append(markup[opener.start():])
            position = length

    return elements


def extract_card_fragments(markup: Optional[str]) -> List[str]:
    """
    Split a rendered listing fragment into its individual bid-row fragments.

    Only the row containers are returned, so the surrounding page chrome (the
    result counter, the sort menu, the pagination widget) can never be read as
    part of a bid record.
    """
    if not markup:
        return []
    cards = _split_balanced_elements(markup, "div", _CARD_ELEMENT_START_RE)
    if cards:
        return cards
    rows = _split_balanced_elements(markup, "tr", _ROW_ELEMENT_START_RE)
    if rows:
        return rows
    return [markup]


class ListingPageState:
    """One rendered listing page: its row markup plus GeM's own counters."""

    __slots__ = ("page", "html", "rows", "current_page", "total_pages", "total_records", "has_next")

    def __init__(
        self,
        page: int,
        html: str,
        rows: int = 0,
        current_page: Optional[int] = None,
        total_pages: Optional[int] = None,
        total_records: Optional[int] = None,
        has_next: bool = False,
    ) -> None:
        self.page = page
        self.html = html
        self.rows = rows
        self.current_page = current_page
        self.total_pages = total_pages
        self.total_records = total_records
        self.has_next = has_next


class PaginatedListingResult:
    """Outcome of walking the listing's real pages."""

    def __init__(self) -> None:
        self.states: List[ListingPageState] = []
        self.pages_visited = 0
        self.pages_available: Optional[int] = None
        self.records_available: Optional[int] = None
        self.rows_seen = 0
        self.stop_reason = "not_started"
        self.limit_reached = False
        # The first page this walk started at and the last page it actually
        # verified. A resumed walk starts at ``start_page`` rather than page 1 so
        # an interrupted collection can continue without re-walking earlier pages.
        self.start_page = 1
        self.end_page = 0
        self.page_failures: List[Dict[str, str]] = []
        # Pages whose bid references were all already collected. They are
        # tolerated while the listing keeps drifting; the numbers are reported
        # so a run that stopped on repetition says how much it repeated.
        self.pages_repeated: List[int] = []

    @property
    def total_rows(self) -> int:
        return self.rows_seen

    def page_dicts(self, url: str, method: str = "playwright") -> List[Dict[str, Any]]:
        """Collector-shaped page payloads for the adapter to parse."""
        return [
            {"url": url, "html": state.html, "method": method, "page": state.page}
            for state in self.states
        ]

    def summary(self) -> Dict[str, Any]:
        return {
            "pages_visited": self.pages_visited,
            "pages_available": self.pages_available,
            "records_available": self.records_available,
            "rows_seen": self.rows_seen,
            "stop_reason": self.stop_reason,
            "limit_reached": self.limit_reached,
            "page_failures": len(self.page_failures),
            "pages_repeated": len(self.pages_repeated),
            "start_page": self.start_page,
            "end_page": self.end_page,
        }


class GeMListingPageError(GeMCollectorError):
    """Raised when a single listing page cannot be retrieved or read."""

    def __init__(self, message: str, page: Optional[int] = None) -> None:
        super().__init__(message, status_code=None, stage="pagination")
        self.page = page


def collect_paginated_listing(
    session: Any,
    max_pages: Optional[int] = 0,
    request_interval: float = 0.0,
    on_page: Optional[Callable[[ListingPageState], None]] = None,
    max_consecutive_failures: int = 3,
    max_repeated_pages: int = 3,
    start_page: int = 1,
) -> PaginatedListingResult:
    """
    Walk the listing's real pages and stop on an explicit, reported condition.

    Collection continues while GeM still advertises a next page. It stops when:

    * ``no_next_page``      - the listing widget no longer offers a next page
    * ``last_page``         - ``total_pages`` was reached
    * ``no_rows``           - a page rendered zero bid rows (past the end)
    * ``no_new_ids``        - ``max_repeated_pages`` pages in a row rendered the
                              *same* bid IDs as the page before them, i.e.
                              pagination stopped advancing
    * ``page_limit``        - the configured operational page budget was reached
                              (``limit_reached`` is set so truncation is visible)
    * ``page_failures``     - too many consecutive pages could not be read

    ``start_page`` resumes a walk part-way through the listing (default 1). The
    page's own filter/sort state is applied before jumping to ``start_page`` so a
    resumed walk still uses the configured scope and order rather than the
    portal default. ``max_pages`` counts pages read *from* ``start_page``.

    The public listing is live: new bids are prepended at the top while older
    ones close, so offsets shift underneath the walk and a page can legitimately
    re-show records already collected earlier in the same run. Such drift is not
    the end of the set. The walk only concludes ``no_new_ids`` when consecutive
    pages render the *same* set of bid IDs, which is the real signature of a
    listing whose pagination stopped advancing. Each repeated page is still
    recorded in ``pages_repeated`` and counted in the run summary. (A page that
    truly refuses to advance is separately caught by the ``go_to`` advance check,
    which raises and is recorded as a page failure.)

    A single unreadable page is recorded and skipped; it never aborts a run
    whose remaining pages are still healthy.
    """
    result = PaginatedListingResult()
    limit = max(0, int(max_pages or 0))
    failure_budget = max(1, int(max_consecutive_failures or 1))
    repeat_budget = max(1, int(max_repeated_pages or 1))
    consecutive_failures = 0
    consecutive_repeats = 0
    previous_page_ids: set = set()
    next_page = max(1, int(start_page or 1))
    result.start_page = next_page
    last_request_at: Optional[float] = None

    # When resuming past page 1 the page's own filter/sort state must be applied
    # before the first ``go_to`` so the resumed walk keeps the configured scope
    # and sort order (a fresh page load defaults to the portal's own order).
    if next_page > 1:
        apply_scope = getattr(session, "apply_scope", None)
        if callable(apply_scope):
            try:
                apply_scope()
            except Exception as exc:  # noqa: BLE001 - scope must not kill the walk
                logger.warning("Could not apply listing scope before resume: %s", exc)

    while True:
        # Explicit operational budget, applied before the request so the limit
        # is never reached by surprise mid-page.
        if limit and result.pages_visited >= limit:
            result.stop_reason = "page_limit"
            result.limit_reached = True
            break

        if last_request_at is not None and request_interval:
            remaining = request_interval - (time.monotonic() - last_request_at)
            if remaining > 0:
                time.sleep(remaining)

        try:
            if next_page == 1:
                state = session.read()
            else:
                state = session.go_to(next_page)
            last_request_at = time.monotonic()
            consecutive_failures = 0
        except GeMBlockedError:
            raise
        except Exception as exc:  # noqa: BLE001 - one bad page must not stop the run
            consecutive_failures += 1
            result.page_failures.append(
                {"page": str(next_page), "message": f"page {next_page} could not be read: {exc}"}
            )
            logger.warning(
                "GeM listing page %s could not be read (%s); continuing with the remaining pages.",
                next_page, exc,
            )
            if consecutive_failures >= failure_budget:
                result.stop_reason = "page_failures"
                break
            next_page += 1
            continue

        if state is None:
            consecutive_failures += 1
            result.page_failures.append(
                {"page": str(next_page), "message": f"page {next_page} returned no state."}
            )
            if consecutive_failures >= failure_budget:
                result.stop_reason = "page_failures"
                break
            next_page += 1
            continue

        result.states.append(state)
        result.pages_visited += 1
        result.rows_seen += int(state.rows or 0)
        if state.total_records is not None:
            result.records_available = state.total_records
        if state.total_pages is not None:
            result.pages_available = state.total_pages

        if on_page is not None:
            try:
                on_page(state)
            except Exception as exc:  # noqa: BLE001 - reporting must not stop collection
                logger.warning("Listing page %s reporting callback failed: %s", state.page, exc)

        # A page that rendered no rows is the end of the set, whatever the
        # widget claims. Checked before the widget so an exhausted listing is
        # reported as "no rows" instead of hiding behind a stale next link.
        if state.rows == 0:
            result.stop_reason = "no_rows"
            break

        # GeM's own counters are the authority on when the set ends.
        if state.total_pages is not None and state.page >= state.total_pages:
            result.stop_reason = "last_page"
            break
        if not state.has_next:
            result.stop_reason = "no_next_page"
            break

        page_ids = set(extract_bid_references(html_to_text(state.html)))
        # A repeat is only meaningful when the page renders the *same* bid
        # references as the immediately preceding page. A page that merely
        # re-shows IDs collected earlier in the run is normal drift on a live
        # listing (new bids are prepended and shift offsets under the walk), so
        # it must keep the walk going, not end it. The old "is a subset of every
        # ID seen so far" test stopped the walk on exactly that drift.
        if page_ids and page_ids == previous_page_ids:
            consecutive_repeats += 1
            result.pages_repeated.append(int(state.page))
            if consecutive_repeats >= repeat_budget:
                result.stop_reason = "no_new_ids"
                break
        else:
            consecutive_repeats = 0
        previous_page_ids = page_ids

        next_page = state.page + 1

    if result.stop_reason == "not_started":
        result.stop_reason = "no_pages"
    # The last page a record was actually read from (not merely attempted).
    result.end_page = result.states[-1].page if result.states else result.start_page - 1
    return result


class PlaywrightListingSession:
    """
    Drives the listing's own pagination inside a real rendered page.

    GeM's page fetches each page through its own ``loadBids(page)`` function,
    which POSTs to the listing's public data endpoint using the page's own CSRF
    token and then repaints ``#bidCard`` and the pagination widget. This session
    calls that same function, so pagination semantics, filtering and pacing are
    exactly the ones the public page uses. No endpoint is invented, no token is
    forged and no request is replayed by hand.
    """

    READ_JS = """() => {
        const container = document.getElementById('bidCard');
        if (!container) return {html: '', inner: '', cards: 0};
        let cards = container.querySelectorAll('.card');
        if (!cards.length) cards = container.querySelectorAll('table tbody tr');
        const rows = [...cards].map(c => c.outerHTML);
        return {
            inner: container.innerHTML,
            html: rows.join('\\n'),
            cards: rows.length,
            showing: (container.querySelector('.totalRecord') || {}).innerText || ''
        };
    }"""

    GO_JS = """(pageNumber) => {
        window.currentPage = pageNumber;
        if (typeof loadBids === 'function') { loadBids(pageNumber); return true; }
        return false;
    }"""

    # GeM's own Advance Search writes window.filter with exactly these keys and
    # then calls loadBids(). Setting them here is the same public narrowing a
    # human visitor applies in the search box; no endpoint is invented.
    APPLY_FILTER_JS = """(f) => {
        if (!window.filter || typeof window.filter !== 'object') { window.filter = {}; }
        if (f.bidStatusType) { window.filter.bidStatusType = f.bidStatusType; }
        if (f.byType) { window.filter.byType = f.byType; }
        if (typeof f.highBidValue === 'string') { window.filter.highBidValue = f.highBidValue; }
        if (f.byEndDate && typeof f.byEndDate === 'object') { window.filter.byEndDate = f.byEndDate; }
        return true;
    }"""

    SET_SORT_JS = """(s) => {
        if (typeof sort === 'function') { sort(s); return true; }
        return false;
    }"""

    # Setting ``window.filter`` is not enough on its own: GeM only re-requests
    # the listing when its own loadBids() runs. Calling it is exactly what the
    # search box does, and it is also what makes the reported counters describe
    # the narrowed scope instead of the wider default listing.
    RELOAD_SCOPE_JS = """() => {
        if (typeof loadBids === 'function') { loadBids(1); return true; }
        return false;
    }"""

    # GeM's own search box writes the term into ``window.param.searchBid`` and
    # its ``param.searchType`` selector, then calls loadBids(1). Setting the
    # term the same way keeps the narrowed population inside GeM's public page
    # instead of inventing a private endpoint. Empty by default, so the
    # production walk still covers the whole configured listing.
    APPLY_SEARCH_JS = """(s) => {
        if (!window.param || typeof window.param !== 'object') { window.param = {}; }
        window.param.searchBid = s.term || '';
        window.param.searchType = s.searchType || 'fullText';
        const box = document.querySelector('#searchBid');
        if (box) { box.value = window.param.searchBid; }
        return true;
    }"""

    def __init__(
        self,
        page: Any,
        url: str,
        timeout_ms: int = 45000,
        settle_ms: int = 1200,
        bid_status_type: Optional[str] = None,
        bid_type: Optional[str] = None,
        sort_order: Optional[str] = None,
        search_term: Optional[str] = None,
    ) -> None:
        self._page = page
        self._url = url
        self._timeout_ms = int(timeout_ms)
        self._settle_ms = int(settle_ms)
        self._bid_status_type = bid_status_type or None
        self._bid_type = bid_type or None
        self._sort_order = sort_order or None
        self._search_term = (search_term or "").strip() or None
        self.scope_applied: Dict[str, Any] = {}
        self._scope_done = False

    def apply_scope(self) -> None:
        """
        Apply the configured filter/sort state exactly once.

        Called by :meth:`read` for a page-1 walk and by ``collect_paginated_listing``
        before a resumed walk jumps past page 1, so a resumed run keeps the same
        scope and order as the original run.
        """
        if self._scope_done:
            return
        self._apply_scope()
        self._scope_done = True

    @staticmethod
    def _is_listing_data(response: Any) -> bool:
        try:
            if response.request.method.upper() != "POST":
                return False
            return "/all-bids-data" in response.url
        except Exception:
            return False

    def _snapshot(self) -> Dict[str, Any]:
        snapshot = self._page.evaluate(self.READ_JS)
        if not isinstance(snapshot, dict):
            raise GeMListingPageError("Listing page did not return a readable snapshot.")
        return snapshot

    def _state_for(self, page_number: int, snapshot: Dict[str, Any]) -> ListingPageState:
        showing = parse_showing_count(snapshot.get("showing") or "")
        widget = parse_pagination_state(snapshot.get("inner") or "")
        total_pages = widget.get("total_pages")
        total_records = showing["total"] if showing else None
        # GeM's own arithmetic is ceil(total / page size); prefer it so a
        # truncated widget window can never under-report the last page.
        if total_records:
            derived = max(1, -(-total_records // GEM_PAGE_SIZE))
            total_pages = derived if total_pages is None else max(total_pages, derived)
        return ListingPageState(
            page=page_number,
            html=snapshot.get("html") or "",
            rows=int(snapshot.get("cards") or 0),
            current_page=widget.get("current_page"),
            total_pages=total_pages,
            total_records=total_records,
            has_next=bool(widget.get("has_next")),
        )

    def _apply_scope(self) -> None:
        """
        Narrow the listing through GeM's own filter/sort state before reading.

        Done before the first read so the counters reported on page 1 already
        describe the configured scope rather than the unfiltered listing.
        """
        if not (
            self._bid_status_type
            or self._bid_type
            or self._sort_order
            or self._search_term
        ):
            return
        filt = {}
        if self._bid_status_type:
            filt["bidStatusType"] = self._bid_status_type
        if self._bid_type:
            filt["byType"] = self._bid_type
        sort_applied = False
        try:
            self._page.evaluate(self.APPLY_FILTER_JS, filt)
            if self._sort_order:
                sort_applied = bool(self._page.evaluate(self.SET_SORT_JS, self._sort_order))
                if sort_applied:
                    filt["sort"] = self._sort_order
            if self._search_term:
                self._page.evaluate(
                    self.APPLY_SEARCH_JS,
                    {"term": self._search_term, "searchType": "fullText"},
                )
                filt["searchBid"] = self._search_term
            # Re-run the listing request so page 1 is the narrowed population.
            if not self._page.evaluate(self.RELOAD_SCOPE_JS):
                return
        except Exception:
            # A listing revision without that state still paginates; the run
            # then covers the wider default scope, which is reported honestly.
            return
        self.scope_applied = dict(filt)
        if self._sort_order and not sort_applied:
            self.scope_applied["sort"] = None

    def read(self) -> ListingPageState:
        self.apply_scope()
        self._page.wait_for_selector("#bidCard .card, #bidCard table tbody tr", timeout=self._timeout_ms)
        self._page.wait_for_timeout(self._settle_ms)
        return self._state_for(1, self._snapshot())

    def go_to(self, page: int) -> ListingPageState:
        page = max(1, int(page))
        retries = self._page_read_retries()
        state: Optional[ListingPageState] = None
        snapshot: Dict[str, Any] = {}
        last_error: Optional[GeMListingPageError] = None

        for attempt in range(retries + 1):
            try:
                with self._page.expect_response(self._is_listing_data, timeout=self._timeout_ms):
                    invoked = self._page.evaluate(self.GO_JS, page)
                if not invoked:
                    raise GeMListingPageError(
                        "The listing page did not expose its pagination function.", page=page
                    )
                # The widget and the cards are repainted inside the success
                # handler, so give the DOM a moment to settle before reading it.
                self._page.wait_for_timeout(self._settle_ms)
                snapshot = self._snapshot()
                state = self._state_for(page, snapshot)
            except GeMListingPageError as exc:
                last_error = exc
                state = None
            except Exception as exc:  # noqa: BLE001 - transient response/DOM issue
                last_error = GeMListingPageError(f"{type(exc).__name__}: {exc}", page=page)
                state = None

            if state is not None and state.rows > 0:
                showing = parse_showing_count(snapshot.get("showing") or "")
                if showing and showing["start"] != (page - 1) * GEM_PAGE_SIZE + 1:
                    # The DOM still shows a previous page: the request did not land.
                    last_error = GeMListingPageError(
                        f"The listing still showed records {showing['start']}-{showing['end']} "
                        f"after requesting page {page}.",
                        page=page,
                    )
                else:
                    return state

            # Empty (or wrong) repaint. Retry while the widget still advertises a
            # page beyond this one; only a widget that also says there is no next
            # page makes a zero-row read the genuine end of the set.
            widget = parse_pagination_state(snapshot.get("inner") or "") if snapshot else {}
            more_pages = bool(widget.get("has_next"))
            if state is not None:
                if state.total_pages is not None and page < state.total_pages:
                    more_pages = True
                elif state.total_pages is None:
                    more_pages = True
            elif not widget:
                # No parseable state and no widget at all: treat as transient.
                more_pages = True

            if attempt < retries and more_pages:
                self._page.wait_for_timeout(max(1000, self._settle_ms))
                continue

            if state is not None:
                # Genuine past-the-end page (zero rows, no further page).
                return state
            raise last_error or GeMListingPageError("page did not render", page=page)

        if state is None:  # pragma: no cover - loop always returns or raises
            raise last_error or GeMListingPageError("page did not render", page=page)
        if state.rows == 0:
            return state
        return state

    def _page_read_retries(self) -> int:
        try:
            return max(0, int(getattr(settings, "GEM_DIRECT_PAGE_READ_RETRIES", 2)))
        except (TypeError, ValueError):
            return 2

    def close(self) -> None:
        try:
            self._page.close()
        except Exception:
            pass


# Playwright's sync API builds its own event loop with
# ``asyncio.new_event_loop()``, which honours the process-wide event loop
# policy. On Windows, uvicorn installs ``WindowsSelectorEventLoopPolicy``
# process-wide at startup (see ``uvicorn/loops/asyncio.py``), and a
# SelectorEventLoop cannot spawn subprocesses: the browser launch fails with a
# bare ``NotImplementedError`` raised from ``asyncio.base_events``. Create the
# Playwright loop under the Proactor policy instead, then restore the host's
# policy. Serialised by a lock because the policy is process-global.
_PLAYWRIGHT_LOOP_POLICY_LOCK = threading.Lock()


@contextmanager
def windows_proactor_loop_policy():
    """
    Force the Windows Proactor event loop policy for Playwright's own loop.

    A no-op on non-Windows platforms and when the Proactor policy is already
    active. The policy in force before the context is always restored, so the
    embedding application's event loop policy is left untouched.
    """
    if sys.platform != "win32":
        yield
        return

    proactor_policy_cls = getattr(asyncio, "WindowsProactorEventLoopPolicy", None)
    if proactor_policy_cls is None:  # pragma: no cover - defensive
        yield
        return

    with _PLAYWRIGHT_LOOP_POLICY_LOCK:
        previous = asyncio.get_event_loop_policy()
        if isinstance(previous, proactor_policy_cls):
            yield
            return
        asyncio.set_event_loop_policy(proactor_policy_cls())
        try:
            yield
        finally:
            asyncio.set_event_loop_policy(previous)


def open_listing_session(
    url: str = DEFAULT_LISTING_URL,
    timeout_ms: Optional[int] = None,
    settle_ms: Optional[int] = None,
    bid_status_type: Optional[str] = None,
    bid_type: Optional[str] = None,
    sort_order: Optional[str] = None,
    search_term: Optional[str] = None,
) -> Tuple[Any, Any, PlaywrightListingSession]:
    """
    Render the public listing in a real browser and return
    ``(driver, browser, session)``.

    Ordinary headless browsing with an honest user agent: no stealth plugin, no
    automation-flag patching and no challenge solving. The caller owns the
    browser and must close both the browser and the Playwright driver.
    """
    try:
        from playwright.sync_api import sync_playwright  # type: ignore
    except Exception as exc:  # pragma: no cover - optional dependency
        raise GeMCollectorError(
            "Listing pagination needs a rendered page but Playwright is not installed in the "
            f"backend environment ({exc}).",
            status_code=501,
            stage="render",
        ) from exc

    timeout_ms = int(timeout_ms or getattr(settings, "GEM_DIRECT_PAGE_SETTLE_MS", 45000))
    settle_ms = int(settle_ms if settle_ms is not None else 1200)
    user_agent = getattr(settings, "GEM_DIRECT_USER_AGENT", "SecuredApp-GeM-Intelligence/1.0")

    driver = None
    with windows_proactor_loop_policy():
        driver = sync_playwright().start()
    browser = None
    try:
        browser = driver.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=user_agent,
            locale="en-US",
            viewport={"width": 1440, "height": 1200},
        )
        page = context.new_page()
        response = page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        status_code = int(response.status) if response else 0
        if status_code in (403, 429):
            raise GeMBlockedError(
                f"GeM refused automated collection of {url} (HTTP {status_code}). "
                "Collection has been stopped; no bypass is attempted.",
                status_code=status_code,
                stage="render",
            )
        return driver, browser, PlaywrightListingSession(
            page,
            url,
            timeout_ms=timeout_ms,
            settle_ms=settle_ms,
            bid_status_type=bid_status_type,
            bid_type=bid_type,
            sort_order=sort_order,
            search_term=search_term,
        )
    except BaseException:
        try:
            if browser is not None:
                browser.close()
        except Exception:
            pass
        try:
            driver.stop()
        except Exception:
            pass
        raise


# ---------------------------------------------------------------------------
# Collector
# ---------------------------------------------------------------------------
class GeMPublicCollector:
    """
    Fetches public GeM pages with an ordinary HTTP client.

    Responsibilities are deliberately narrow: request an allowlisted public
    page, honour conservative pacing, retry transient failures with bounded
    exponential backoff, and return the response body verbatim. All parsing
    lives in the adapter so this class stays testable in isolation.
    """

    def __init__(
        self,
        timeout: Optional[int] = None,
        max_retries: Optional[int] = None,
        request_interval: Optional[float] = None,
        session: Optional[Any] = None,
        user_agent: Optional[str] = None,
    ) -> None:
        self.timeout = int(timeout if timeout is not None else getattr(settings, "GEM_DIRECT_TIMEOUT_SECONDS", 60))
        self.max_retries = int(
            max_retries if max_retries is not None else getattr(settings, "GEM_DIRECT_MAX_RETRIES", 2)
        )
        self.request_interval = float(
            request_interval
            if request_interval is not None
            else getattr(settings, "GEM_DIRECT_REQUEST_INTERVAL_SECONDS", 3.0)
        )
        self.user_agent = user_agent or getattr(settings, "GEM_DIRECT_USER_AGENT", "SecuredApp-GeM-Intelligence/1.0")
        # A plain, honest client descriptor. No browser impersonation, no
        # stealth plugin, no header spoofing to defeat bot detection.
        self.headers = {
            "User-Agent": self.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Connection": "keep-alive",
        }
        self._session = session or requests.Session()
        self._last_request_at: Optional[float] = None
        self._blocked = False

    # -- pacing ---------------------------------------------------------
    def _respect_interval(self) -> None:
        """Sleep so consecutive requests stay at least ``request_interval`` apart."""
        if self._last_request_at is None:
            return
        elapsed = time.monotonic() - self._last_request_at
        remaining = self.request_interval - elapsed
        if remaining > 0:
            time.sleep(remaining)

    @staticmethod
    def _backoff(attempt: int, response: Optional[requests.Response] = None) -> float:
        """Exponential backoff, honouring a ``Retry-After`` hint when present."""
        if response is not None:
            try:
                retry_after = response.headers.get("Retry-After")
            except Exception:
                retry_after = None
            if retry_after:
                try:
                    return min(float(retry_after), 30.0)
                except (TypeError, ValueError):
                    pass
        return float(2 ** (attempt - 1))

    # -- status ---------------------------------------------------------
    @property
    def blocked(self) -> bool:
        """True once the source has refused automated collection."""
        return self._blocked

    def status(self) -> Dict[str, Any]:
        """Secret-free description of the collector configuration."""
        max_pages = int(getattr(settings, "GEM_DIRECT_MAX_PAGES", 0) or 0)
        return {
            "source": "gem_direct",
            "provider": "Direct GeM Public Collector",
            "configured": bool(
                getattr(settings, "GEM_DIRECT_ENABLED", True) and allowed_hosts()
            ),
            "status": "READY" if allowed_hosts() else "NOT_CONFIGURED",
            "allowed_hosts": allowed_hosts(),
            "listing_url": DEFAULT_LISTING_URL,
            "timeout_seconds": self.timeout,
            "max_retries": self.max_retries,
            "request_interval_seconds": self.request_interval,
            "max_urls_per_run": int(getattr(settings, "GEM_DIRECT_MAX_URLS_PER_RUN", 10)),
            "pagination_enabled": bool(getattr(settings, "GEM_DIRECT_PAGINATE", True)),
            "max_pages": max_pages,
            "max_pages_unlimited": max_pages <= 0,
            "records_per_page": GEM_PAGE_SIZE,
            "max_bids_per_run": int(getattr(settings, "GEM_DIRECT_MAX_BIDS_PER_RUN", 0) or 0),
            "bid_status_type": getattr(settings, "GEM_DIRECT_BID_STATUS_TYPE", "ongoing_bids"),
            "bid_type": getattr(settings, "GEM_DIRECT_BID_TYPE", "all"),
            "sort_order": getattr(settings, "GEM_DIRECT_SORT_ORDER", "Bid-Start-Date-Latest"),
            "keyword_filter_enabled": bool(
                getattr(settings, "GEM_DIRECT_KEYWORD_FILTER_ENABLED", False)
            ),
            "detail_enrichment_enabled": bool(
                getattr(settings, "GEM_DIRECT_ENRICH_DETAIL_PAGES", False)
            ),
            "max_detail_pages": int(getattr(settings, "GEM_DIRECT_MAX_DETAIL_PAGES", 20)),
            "scheduler_enabled": bool(getattr(settings, "GEM_DIRECT_SCHEDULER_ENABLED", False)),
            "scheduler_interval_minutes": int(
                getattr(settings, "GEM_DIRECT_SCHEDULER_INTERVAL_MINUTES", 60)
            ),
            "blocked": self._blocked,
            "requires_credentials": False,
        }

    # -- fetch ----------------------------------------------------------
    def fetch(
        self,
        url: str,
        stage: str = "request",
        allow_block_retry: bool = False,
    ) -> Tuple[int, str]:
        """
        Fetch one allowlisted public page and return ``(status_code, html)``.

        Behaviour:
          * 403 / 429 / block page -> :class:`GeMBlockedError`, immediately.
            The collector stops; it never tries to get around a block.
          * 5xx / timeout / connection error -> bounded retries with
            exponential backoff, then a :class:`GeMCollectorError`.
          * any other 4xx -> :class:`GeMCollectorError` without retry.
        """
        permitted = validate_public_url(url)

        if self._blocked and not allow_block_retry:
            raise GeMBlockedError(
                "GeM previously refused automated collection; the direct collector has stopped.",
                status_code=403,
                stage=stage,
            )

        last_error: Optional[str] = None
        # ``max_retries`` counts retries *after* the initial attempt, so the
        # total number of attempts is one more than the configured value.
        attempts = max(1, int(self.max_retries)) + 1

        for attempt in range(1, attempts + 1):
            self._respect_interval()
            try:
                response = self._session.get(
                    permitted,
                    headers=self.headers,
                    timeout=self.timeout,
                    allow_redirects=True,
                )
            except requests.exceptions.Timeout as exc:
                last_error = f"timeout after {self.timeout}s: {exc}"
                logger.warning("GeM request timed out for %s (attempt %d/%d)", permitted, attempt, attempts)
            except requests.exceptions.ConnectionError as exc:
                last_error = f"connection error: {exc}"
                logger.warning("GeM connection error for %s (attempt %d/%d)", permitted, attempt, attempts)
            except requests.exceptions.RequestException as exc:
                last_error = f"request error: {exc}"
                logger.warning("GeM request error for %s (attempt %d/%d)", permitted, attempt, attempts)
            else:
                self._last_request_at = time.monotonic()
                status = int(getattr(response, "status_code", 0) or 0)
                markup = self._read_body(response)

                if status in (403, 429):
                    self._blocked = True
                    reason = "rate limit (HTTP 429)" if status == 429 else "access forbidden (HTTP 403)"
                    raise GeMBlockedError(
                        f"GeM refused automated collection of {permitted}: {reason}. "
                        "Collection has been stopped; no bypass is attempted.",
                        status_code=status,
                        stage=stage,
                    )

                if looks_blocked(status, markup):
                    self._blocked = True
                    raise GeMBlockedError(
                        f"GeM returned a blocking response for {permitted} (HTTP {status}). "
                        "Collection has been stopped; no bypass is attempted.",
                        status_code=status or 403,
                        stage=stage,
                    )

                if status >= 500:
                    last_error = f"server error (HTTP {status})"
                    if attempt < attempts:
                        delay = self._backoff(attempt, response)
                        logger.warning(
                            "Transient GeM error HTTP %s for %s; retrying in %.1fs",
                            status, permitted, delay,
                        )
                        time.sleep(delay)
                        continue
                    raise GeMCollectorError(
                        f"GeM server error (HTTP {status}) persisted after {attempts} attempts for {permitted}.",
                        status_code=status,
                        stage=stage,
                    )

                if status >= 400:
                    raise GeMCollectorError(
                        f"GeM rejected the request for {permitted} (HTTP {status}).",
                        status_code=status,
                        stage=stage,
                    )

                if _CAPTCHA_HINT_RE.search(markup[:20000] or ""):
                    # A challenge is reported, never solved.
                    logger.warning(
                        "GeM page for %s references a browser challenge; the collector will not attempt to solve it.",
                        permitted,
                    )

                return status, markup

            # Transient transport failure -> back off and retry if budget allows.
            if attempt < attempts:
                delay = self._backoff(attempt)
                logger.warning("Retrying %s in %.1fs after %s", permitted, delay, last_error)
                time.sleep(delay)

        raise GeMCollectorError(
            f"Failed to retrieve {permitted} after {attempts} attempt(s): {last_error}",
            status_code=504,
            stage=stage,
        )

    @staticmethod
    def _read_body(response: Any) -> str:
        """Best-effort decode of a response body, tolerating odd encodings."""
        try:
            encoding = getattr(response, "encoding", None) or "utf-8"
            text = response.text
        except Exception:
            try:
                text = response.content.decode("utf-8", errors="replace")
            except Exception:
                return ""
        if not isinstance(text, str):
            return ""
        # Some GeM pages mislabel the charset; fall back when decoding produced
        # replacement characters throughout.
        if encoding and encoding.lower() not in ("utf-8", "utf8"):
            try:
                content = getattr(response, "content", None)
                if content:
                    return content.decode(encoding, errors="replace")
            except Exception:
                pass
        return text


def get_gem_public_collector(**kwargs: Any) -> GeMPublicCollector:
    """Factory returning a configured direct collector."""
    return GeMPublicCollector(**kwargs)


def utc_now_iso() -> str:
    """UTC timestamp helper used for run bookkeeping."""
    return datetime.now(timezone.utc).isoformat()