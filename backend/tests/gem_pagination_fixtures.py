"""
Deterministic, offline fixtures for the direct GeM collector's pagination.

Everything here is built from recorded/hand-written markup that mirrors the real
public listing's structure:

    <div id="bidCard">
      <div class="row row-flex">
        <div class="col-md-6 totalRecord">
          <span class="pos-bottom">Showing 1 - 10 records of 34 records</span>
        </div>
        ...
      </div>
      <div class="card"> ... one bid row ... </div>
      <div id="light-pagination" class="pagination2 light-theme">
        <span class="current prev">Prev</span>
        <span class="current">1</span>
        <a href="#page-2" class="page-link">2</a>
        ...
        <a href="#page-4" class="page-link">4</a>
        <a href="#page-2" class="page-link next">Next</a>
      </div>
    </div>

No test in this package performs a real GeM request. The browser is faked at the
``open_listing_session`` boundary and the walk is exercised through
``collect_paginated_listing``, so page counts, failures and limits are exact.
"""
from __future__ import annotations

import re
from typing import Any, Callable, Dict, List, Optional

from app.services.ingestion.gem_public_collector import (
    GEM_PAGE_SIZE,
    GeMBlockedError,
    GeMListingPageError,
    ListingPageState,
    extract_bid_references,
    extract_card_fragments,
    html_to_text,
    parse_pagination_state,
    parse_showing_count,
)

LISTING_URL = "https://bidplus.gem.gov.in/all-bids"


# ---------------------------------------------------------------------------
# Row markup
# ---------------------------------------------------------------------------
def bid_card(
    bid_number: str,
    item: str,
    bid_id: int,
    org: str = "Ministry of Defence",
    dept: str = "Department of Military Affairs",
    start: str = "04-08-2026 10:43 AM",
    end: str = "05-10-2026 9:00 AM",
) -> str:
    """One rendered bid row, shaped like the real listing card."""
    return f"""
<div class="card">
 <div class="block_header">
  <p class="bid_no pull-left"><span class="bid_title">BID NO:&nbsp;</span>
   <a class="bid_no_hover" href="/showbidDocument/{bid_id}" target="_blank">{bid_number}</a></p>
  <p class="pull-right otherDetails" id="other-details-{bid_id}" data-bid="{bid_id}"
     onclick="getOtherDetails({bid_id})"><a><i class="fa fa-arrow-circle-left"></i> View Corrigendum</a></p>
 </div>
 <div class="card-body">
  <div class="row">
   <div class="col-md-4">
    <div class="row"><strong>Items:</strong>&nbsp;
     <a data-toggle="popover" data-content="{item}">{item[:40]}...</a></div>
    <div class="row"><strong>Quantity:</strong>&nbsp;1</div>
   </div>
   <div class="col-md-5">
    <div class="row"><strong>Department Name And Address:</strong>&nbsp;</div>
    <div class="row">{org}<br>{dept}</div>
   </div>
   <div class="col-md-3">
    <div class="row"><strong>Start Date:</strong>&nbsp;<span class="start_date">{start}</span></div>
    <div class="row"><strong>End Date:</strong>&nbsp;<span class="end_date">{end}</span></div>
   </div>
  </div>
 </div>
</div>
"""


def bid_card_with_group_label(
    bid_number: str = "GEM/2026/B/8060200",
    bid_id: int = 8060200,
    item: str = "Almonds,Walnuts,Raisin,Cashew,Pistachio",
    group_label: str = "Nutritional Supplement",
    org: str = "Ministry of Defence",
    dept: str = "Department of Military Affairs",
    start: str = "19-09-2026 9:09 PM",
    end: str = "05-10-2026 9:00 PM",
) -> str:
    """
    One rendered bid row that also carries GeM's own item-group label.

    Live listing markup was verified to stamp the real category/group text in
    ``data-original-title`` while the visible ``title`` attribute is empty, e.g.
    ``data-original-title="Nutritional Supplement"``. ``group_label=None`` omits
    the attribute entirely, which is what most listing rows look like.
    """
    label_attr = "" if group_label is None else f' data-original-title="{group_label}"'
    return f"""
<div class="card">
 <div class="block_header">
  <p class="bid_no pull-left"><span class="bid_title">BID NO:&nbsp;</span>
   <a class="bid_no_hover" href="/showbidDocument/{bid_id}" target="_blank">{bid_number}</a></p>
  <p class="pull-right otherDetails" id="other-details-{bid_id}" data-bid="{bid_id}"></p>
 </div>
 <div class="card-body">
  <div class="row">
   <div class="col-md-4">
    <div class="row"><strong>Items:</strong>&nbsp;
     <a data-toggle="popover" title=""{label_attr} data-content="{item}">{item[:40]}...</a></div>
    <div class="row"><strong>Quantity:</strong>&nbsp;1</div>
   </div>
   <div class="col-md-5">
    <div class="row"><strong>Department Name And Address:</strong>&nbsp;</div>
    <div class="row">{org}<br>{dept}</div>
   </div>
   <div class="col-md-3">
    <div class="row"><strong>Start Date:</strong>&nbsp;<span class="start_date">{start}</span></div>
    <div class="row"><strong>End Date:</strong>&nbsp;<span class="end_date">{end}</span></div>
   </div>
  </div>
 </div>
</div>
"""


def malformed_bid_card(bid_number: str, bid_id: int = 5555555) -> str:
    """
    A row that prints a real bid reference but no usable item description.

    The element is deliberately well formed and balanced: an unclosed tag would
    make the row splitter swallow its neighbours, which would hide exactly the
    row-loss bugs these tests exist to catch. This row still counts as a row and
    still yields a bid reference, but it carries no title, so it must be reported
    as a loss instead of disappearing.
    """
    return f"""
<div class="card">
 <div class="block_header">
  <p class="bid_no pull-left"><span class="bid_title">BID NO:&nbsp;</span>
   <a class="bid_no_hover" href="/showbidDocument/{bid_id}" target="_blank">{bid_number}</a></p>
 </div>
 <div class="card-body">
  <div class="row"><div class="col-md-12"></div></div>
 </div>
</div>
"""


def showing_block(page: int, total: int) -> str:
    """GeM's own result counter for a given 1-based page."""
    start = (page - 1) * GEM_PAGE_SIZE + 1
    end = min(start + GEM_PAGE_SIZE - 1, total)
    return (
        '<div class="row row-flex"><div class="col-md-6 totalRecord">'
        f'<span class="pos-bottom">Showing {start} - {end} records of {total} records</span>'
        "</div></div>"
    )


def pagination_widget(page: int, total_pages: int) -> str:
    """
    The ``#light-pagination`` widget as GeM builds it.

    Real widget behaviour the parser depends on: the first and last page are
    always printed as numbered links, the window is at most four pages wide, and
    ``prev``/``next`` degrade to ``span.current`` when they are not available.
    """
    parts: List[str] = []
    if page > 1:
        parts.append(f'<a href="#page-{page - 1}" class="page-link prev">Prev</a>')
    else:
        parts.append('<span class="current prev">Prev</span>')

    window = [page]
    if page > 2:
        window.append(1)
    window.extend(p for p in range(page + 1, page + 4) if p < total_pages)
    if total_pages > page and total_pages not in window:
        window.append(total_pages)

    for candidate in window:
        if candidate == page:
            parts.append(f'<span class="current">{candidate}</span>')
        else:
            parts.append(f'<a href="#page-{candidate}" class="page-link">{candidate}</a>')

    if page < total_pages:
        parts.append(f'<a href="#page-{page + 1}" class="page-link next">Next</a>')
    else:
        parts.append('<span class="current next">Next</span>')

    return (
        '<div id="light-pagination" class="pagination2 light-theme">'
        + "".join(parts)
        + "</div>"
    )


def bid_card_container(page: int, total: int, total_pages: int, cards: List[str]) -> str:
    """The rendered #bidCard fragment for one page."""
    return (
        f'<div class="col-md-10 bids" id="bidCard">'
        f"{showing_block(page, total)}{''.join(cards)}{pagination_widget(page, total_pages)}"
        "</div>"
    )


# Real GeM rows carry unrelated item descriptions. The fixture cycles this pool of
# genuinely distinct, hand-written titles instead of templating them: the
# project's existing duplicate detection compares bid titles with a fuzzy ratio,
# and templated titles that share a long prefix would be collapsed into one bid.
# That is correct matching behaviour, not a pagination fault, so the fixture
# stays realistic rather than distorting the matcher. Tests that persist rows
# therefore stay within one cycle of this pool (see ``pages_for``).
_ITEM_TITLES = (
    "Smart Contract Security Audit and Vulnerability Detection",
    "Cryptographic Key Management System with HSM Protection",
    "Blockchain Investigation and Transaction Tracing Platform",
    "Continuous Monitoring and Anomaly Detection System",
    "User Consent Management and Privacy Compliance Platform",
    "Cookie Consent and Tracking Script Management System",
    "Decentralized Identity and Verifiable Credentials Issuance",
    "Identity Verification and KYC AML Compliance Platform",
    "Web3 Infrastructure and Decentralized Finance Platform",
    "Post Quantum Cryptography Migration and Crypto Agility Framework",
    "Smart Contract Vulnerability Scanning and Expert Security Review",
    "Blockchain Monitoring and Smart Contract Activity Observation",
    "Privacy Compliance Records and Data Consent Management System",
    "Website Cookie Consent and Tracking Script Management Platform",
    "Web3 Infrastructure Token Creation and Staking Platform",
    "Post Quantum Cryptography Algorithm Migration Framework",
    "Application Security Testing and Web Application Security Audit",
    "Information Security and IT Security Audit Services",
    "Security Alerts and Abnormal Token Movement Detection System",
    "Transaction Monitoring and Smart Contract Activity Observation",
    "Consent Management and User Consent Records Platform",
    "Data Consent and Privacy Management System",
    "Identity Verification and Watchlist Checks System",
    "Fraud Risk Monitoring and Transaction History Analysis",
    "Web3 Compliance and DeFi Compliance Platform",
    "Token Creation and Token Management Platform",
    "Lending Borrowing and Governance Platform",
    "Decentralized Finance Infrastructure Platform",
    "Cryptographic Key Protection and Hardware Backed Protection",
    "Key Access Control and Key Rotation System",
    "Key Revocation and Cryptographic Key Security",
    "Post Quantum Key Protection and Hardware Security Module",
    "Cryptographic Key Protection and Key Generation System",
    "Risk Assessment and Identity Verification System",
    "Transaction Alerts and Security Alerts System",
    "Smart Contract Activity Monitoring System",
    "Digital Identity and Verifiable Credentials Platform",
    "Transaction Relationships and Wallet Investigation Platform",
    "Fund Flow Analysis and Suspicious Transaction Investigation",
    "Application Security Testing and Web Application Security Assessment",
)


def item_title(index: int) -> str:
    """A distinct, plausible item description for row ``index``."""
    return _ITEM_TITLES[index % len(_ITEM_TITLES)]


def pages_for(total: int, start_number: int = 7000000) -> List[str]:
    """
    Build every rendered #bidCard fragment for a result set of ``total``.

    Bid numbers are unique across the whole set. Item descriptions cycle through
    ``_ITEM_TITLES``; tests that persist rows must stay within one cycle so the
    project's existing fuzzy-title duplicate detection does not merge distinct
    fixture rows into a single bid.
    """
    total_pages = max(1, -(-total // GEM_PAGE_SIZE))
    fragments: List[str] = []
    index = 0
    for page in range(1, total_pages + 1):
        remaining = total - (page - 1) * GEM_PAGE_SIZE
        cards: List[str] = []
        for _ in range(min(GEM_PAGE_SIZE, remaining)):
            number = start_number + index * 100 + 10
            cards.append(
                bid_card(
                    f"GEM/2026/B/{number}",
                    item_title(index),
                    9000000 + index,
                )
            )
            index += 1
        fragments.append(bid_card_container(page, total, total_pages, cards))
    return fragments


def snapshot_from_container(container_html: str) -> Dict[str, Any]:
    """
    Mimic what the browser read-back returns for a rendered page.

    The browser hands back each row's ``outerHTML``, so the split here uses the
    production splitter rather than a local regex: a fixture that cut rows short
    would hide exactly the parsing bugs these tests exist to catch.
    """
    showing = parse_showing_count(container_html)
    cards = extract_card_fragments(container_html)
    showing_text = ""
    if showing:
        showing_text = (
            f"Showing {showing['start']} - {showing['end']} records of "
            f"{showing['total']} records"
        )
    return {
        "inner": container_html,
        "html": "\n".join(cards),
        "cards": len(cards),
        "showing": showing_text,
    }


# ---------------------------------------------------------------------------
# Fake listing session
# ---------------------------------------------------------------------------
class FakeListingSession:
    """
    Deterministic stand-in for the rendered public listing page.

    ``fragments`` are the rendered #bidCard HTML for pages 1..N, in order. A page
    listed in ``failing_pages`` raises, and a page whose index exceeds the
    available fragments renders zero rows -- exactly what GeM does past the end
    of the result set.
    """

    def __init__(
        self,
        fragments: List[str],
        failing_pages: Optional[Dict[int, Exception]] = None,
        read_error: Optional[Exception] = None,
    ) -> None:
        self.fragments = list(fragments)
        self.failing_pages = dict(failing_pages or {})
        self.read_error = read_error
        self.requested: List[int] = []

    def _state(self, page: int) -> ListingPageState:
        self.requested.append(page)
        if page in self.failing_pages:
            raise self.failing_pages[page]
        if page < 1 or page > len(self.fragments):
            # Past the end: the request succeeds but renders nothing.
            container = (
                '<div id="bidCard">' + showing_block(page, len(self.fragments) * GEM_PAGE_SIZE)
                + "</div>"
            )
            snapshot = snapshot_from_container(container)
            showing = parse_showing_count(snapshot["showing"])
            return ListingPageState(
                page=page,
                html=snapshot["html"],
                rows=0,
                current_page=page,
                total_pages=len(self.fragments),
                total_records=showing["total"] if showing else None,
                has_next=False,
            )
        snapshot = snapshot_from_container(self.fragments[page - 1])
        showing = parse_showing_count(snapshot["showing"])
        widget = parse_pagination_state(snapshot["inner"])
        total_records = showing["total"] if showing else None
        total_pages = widget.get("total_pages")
        if total_records:
            derived = max(1, -(-total_records // GEM_PAGE_SIZE))
            total_pages = derived if total_pages is None else max(total_pages, derived)
        return ListingPageState(
            page=page,
            html=snapshot["html"],
            rows=int(snapshot["cards"]),
            current_page=widget.get("current_page"),
            total_pages=total_pages,
            total_records=total_records,
            has_next=bool(widget.get("has_next")),
        )

    def read(self) -> ListingPageState:
        if self.read_error is not None:
            raise self.read_error
        return self._state(1)

    def go_to(self, page: int) -> ListingPageState:
        return self._state(page)

    def close(self) -> None:
        return None


class FakeBrowser:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class FakeDriver:
    def __init__(self) -> None:
        self.stopped = False

    def stop(self) -> None:
        self.stopped = True


def patch_open_listing_session(
    patcher: Any,
    session: FakeListingSession,
) -> Callable[[], Any]:
    """Point ``open_listing_session`` at a fake session; returns the browser."""
    browser = FakeBrowser()
    driver = FakeDriver()
    patcher(
        "app.services.ingestion.gem_direct_service.open_listing_session",
        return_value=(driver, browser, session),
    )
    return browser


__all__ = [
    "FakeBrowser",
    "FakeDriver",
    "FakeListingSession",
    "GEM_PAGE_SIZE",
    "GeMBlockedError",
    "GeMListingPageError",
    "LISTING_URL",
    "bid_card",
    "bid_card_container",
    "extract_bid_references",
    "malformed_bid_card",
    "pages_for",
    "pagination_widget",
    "patch_open_listing_session",
    "showing_block",
    "snapshot_from_container",
]