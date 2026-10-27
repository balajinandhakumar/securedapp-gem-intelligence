"""
Mocked test suite for the direct GeM public collector.

No test in this module performs real network access. HTTP is faked at the
``requests.Session`` boundary and the browser render is faked at the
Playwright boundary, so the suite is deterministic and offline.
"""
import time
from unittest.mock import MagicMock

import pytest
import requests

from app.services.ingestion import gem_public_collector as col
from app.services.ingestion.gem_public_collector import (
    DEFAULT_LISTING_URL,
    GeMBlockedError,
    GeMCollectorError,
    GeMPublicCollector,
    GeMUrlNotPermittedError,
    allowed_hosts,
    extract_bid_reference,
    html_to_text,
    is_detail_url,
    looks_blocked,
    resolve_collection_targets,
    validate_public_url,
)

# --------------------------------------------------------------------------
# Fixtures / helpers
# --------------------------------------------------------------------------

# The listing card markup below mirrors the real public GeM "All Bids" page
# structure (div.card -> block_header / card-body) so the tests exercise the
# same selectors the live page uses.
_CARD_ONE = """
<div class="card">
 <div class="block_header">
  <p class="bid_no pull-left">
   <span class="bid_title">BID NO:&nbsp;</span>
   <a class="bid_no_hover" href="/showbidDocument/9673281" target="_blank">GEM/2026/B/7845020</a>
  </p>
  <p class="pull-right otherDetails" id="other-details-9673281" data-bid="9673281"
     onclick="getOtherDetails(9673281)">
   <a><i class="fa fa-arrow-circle-left"></i>&nbsp;&nbsp;View Corrigendum/Representation</a>
  </p>
 </div>
 <div class="clearfix"></div>
 <div class="card-body">
  <div class="row">
   <div class="col-md-4">
    <div class="row">
     <strong>Items:</strong>&nbsp;
     <a data-toggle="popover" title="" data-trigger="hover"
        data-content="Repair and Overhauling Service - UPGRADATION OF MCS 5 CONTROLS OF BOTH MAIN ENGINES ONBOARD IN SHIP"
        data-original-title="">Repair and Overhauling Service...</a>
    </div>
    <div class="row"><strong>Quantity:</strong>&nbsp;1</div>
   </div>
   <div class="col-md-5">
    <div class="row"><strong>Department Name And Address:</strong>&nbsp;</div>
    <div class="row">Ministry of Defence<br>Department of Military Affairs</div>
   </div>
   <div class="col-md-3">
    <div class="row"><strong>Start Date:</strong>&nbsp;<span class="start_date">04-08-2026 10:43 AM</span></div>
    <div class="row"><strong>End Date:</strong>&nbsp;&nbsp;&nbsp;<span class="end_date">05-10-2026 9:00 AM</span></div>
   </div>
   <div class="clearfix"></div>
  </div>
 </div>
</div>
"""

_CARD_TWO = _CARD_ONE.replace("7845020", "8065592").replace("9673281", "9852416")

LISTING_HTML = (
    "<html><body><h1>All Bids</h1>"
    '<div class="dropdown sort">Sort by: Bid End Date: Oldest First</div>'
    f"{_CARD_ONE}{_CARD_TWO}</body></html>"
)

DETAIL_HTML = """
<html><body>
  <h1>GeM Bid Notice</h1>
  <div class="bid_detail">
    <p>Bid Number: GEM/2026/B/7845020</p>
    <p>Bid Title: Repair and Overhauling Service</p>
    <p>Organisation: Ministry of Defence</p>
    <p>Ministry: Ministry of Defence</p>
    <p>Department Name: Department of Military Affairs</p>
    <p>Start Date: 04-08-2026 10:43 AM</p>
    <p>End Date: 05-10-2026 9:00 AM</p>
    <p>Estimated Bid Value: INR 12,50,000</p>
  </div>
  <script>var ignored = "GEM/2026/B/9999999";</script>
</body></html>
"""

CHROME_ONLY_HTML = """
<html><body>
  <nav>Home About Us Contact Us Bid/RA Status Login Sign Up Buyers Sellers</nav>
</body></html>
"""


class FakeResponse:
    """Minimal stand-in for ``requests.Response``."""

    def __init__(self, status_code=200, text="", headers=None):
        self.status_code = status_code
        self.text = text
        self.content = text.encode("utf-8", "replace")
        self.headers = headers or {}
        self.url = DEFAULT_LISTING_URL
        self.encoding = "utf-8"

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.exceptions.HTTPError(f"HTTP {self.status_code}")

    def json(self):
        raise ValueError("not json")


def make_session(responses):
    """Build a fake Session whose ``get`` walks ``responses`` in order."""
    session = MagicMock(spec=requests.Session)
    calls = []

    def _get(url, **kwargs):
        calls.append(url)
        item = responses[min(len(calls) - 1, len(responses) - 1)]
        if isinstance(item, Exception):
            raise item
        return item

    session.get.side_effect = _get
    session.calls = calls
    return session


@pytest.fixture
def collector():
    """Collector wired for fast, deterministic tests (no real sleeping)."""
    return GeMPublicCollector(
        timeout=1,
        max_retries=0,
        request_interval=0,
        backoff_base=0,
        session=make_session([FakeResponse(200, LISTING_HTML)]),
    )


# --------------------------------------------------------------------------
# 1. Listing-page parsing
# --------------------------------------------------------------------------

def test_listing_page_yields_one_record_per_bid_card():
    from app.services.ingestion.gem_direct_adapter import GeMPublicAdapter

    parsed = GeMPublicAdapter().parse_page(LISTING_HTML, source_url=DEFAULT_LISTING_URL)
    assert len(parsed) == 2
    assert [r.bid_number for r in parsed] == [
        "GEM/2026/B/7845020",
        "GEM/2026/B/8065592",
    ]


def test_listing_record_maps_core_fields():
    from app.services.ingestion.gem_direct_adapter import GeMPublicAdapter

    parsed = GeMPublicAdapter().parse_page(LISTING_HTML, source_url=DEFAULT_LISTING_URL)
    r = parsed[0]
    assert r.bid_number == "GEM/2026/B/7845020"
    assert r.title.startswith("Repair and Overhauling Service")
    assert r.organisation == "Ministry of Defence Department of Military Affairs"
    assert r.ministry == "Ministry of Defence"
    assert r.department == "Department of Military Affairs"
    assert r.source_url == "https://bidplus.gem.gov.in/showbidDocument/9673281"
    assert r.published_date is not None
    assert r.closing_date is not None


def test_listing_records_are_distinct_when_numbers_differ():
    from app.services.ingestion.gem_direct_adapter import GeMPublicAdapter

    html = LISTING_HTML.replace("7845020", "7845021", 1)
    parsed = GeMPublicAdapter().parse_page(html, source_url=DEFAULT_LISTING_URL)
    numbers = {r.bid_number for r in parsed}
    assert numbers == {"GEM/2026/B/7845021", "GEM/2026/B/8065592"}


# --------------------------------------------------------------------------
# 2. Detail-page parsing
# --------------------------------------------------------------------------

def test_detail_page_maps_labelled_table_fields():
    from app.services.ingestion.gem_direct_adapter import GeMPublicAdapter

    url = "https://bidplus.gem.gov.in/showbidDocument/9673281"
    parsed = GeMPublicAdapter().parse_page(DETAIL_HTML, source_url=url)
    assert len(parsed) == 1
    r = parsed[0]
    assert r.bid_number == "GEM/2026/B/7845020"
    assert r.title == "Repair and Overhauling Service"
    assert r.organisation == "Ministry of Defence"
    assert r.ministry == "Ministry of Defence"
    assert r.department == "Department of Military Affairs"


def test_detail_page_ignores_script_content():
    from app.services.ingestion.gem_direct_adapter import GeMPublicAdapter

    url = "https://bidplus.gem.gov.in/showbidDocument/9673281"
    parsed = GeMPublicAdapter().parse_page(DETAIL_HTML, source_url=url)
    assert all(r.bid_number != "GEM/2026/B/9999999" for r in parsed)


# --------------------------------------------------------------------------
# 3. Missing fields
# --------------------------------------------------------------------------

def test_missing_fields_are_left_none_and_reported():
    from app.services.ingestion.gem_direct_adapter import GeMPublicAdapter

    sparse = """
    <div class="card">
     <div class="block_header">
      <p class="bid_no"><span class="bid_title">BID NO:&nbsp;</span>
       <a class="bid_no_hover" href="/showbidDocument/1111111">GEM/2026/B/1111111</a></p>
     </div>
     <div class="card-body">
      <div class="row"><strong>Items:</strong>&nbsp;<a data-content="Only a title">Only a title</a></div>
     </div>
    </div>
    """
    parsed = GeMPublicAdapter().parse_page(sparse, source_url=DEFAULT_LISTING_URL)
    assert len(parsed) == 1
    r = parsed[0]
    assert r.bid_number == "GEM/2026/B/1111111"
    assert r.title == "Only a title"
    assert r.ministry is None
    assert r.closing_date is None
    assert r.contact_information is None
    assert "closing_date" in r._raw["missing_fields"]


def test_site_chrome_alone_produces_no_records():
    from app.services.ingestion.gem_direct_adapter import GeMPublicAdapter

    assert GeMPublicAdapter().parse_page(
        CHROME_ONLY_HTML, source_url=DEFAULT_LISTING_URL
    ) == []


# --------------------------------------------------------------------------
# 4. Invalid HTML / unusable responses
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "markup",
    ["", "   ", "not html at all", "<html><body></body></html>", None],
)
def test_invalid_or_empty_markup_yields_no_records(markup):
    from app.services.ingestion.gem_direct_adapter import GeMPublicAdapter

    assert GeMPublicAdapter().parse_page(markup, source_url=DEFAULT_LISTING_URL) == []


def test_malformed_markup_does_not_raise():
    from app.services.ingestion.gem_direct_adapter import GeMPublicAdapter

    broken = '<div class="card"><span>BID NO: GEM/2026/B/7845020<div class="card-title">x'
    assert isinstance(GeMPublicAdapter().parse_page(broken, source_url=DEFAULT_LISTING_URL), list)


# --------------------------------------------------------------------------
# 5. Timeouts and connection errors
# --------------------------------------------------------------------------

def test_timeout_propagates_without_retry_when_max_retries_is_zero():
    session = make_session([requests.exceptions.Timeout("slow")])
    c = GeMPublicCollector(timeout=1, max_retries=0, session=session)
    with pytest.raises(GeMCollectorError):
        c.fetch(DEFAULT_LISTING_URL)


def test_timeout_is_retried_up_to_max_retries_then_raises():
    session = make_session([requests.exceptions.Timeout("slow")])
    c = GeMPublicCollector(timeout=1, max_retries=2, session=session)
    with pytest.raises(GeMCollectorError):
        c.fetch(DEFAULT_LISTING_URL)
    # max_retries counts retries after the initial attempt: 1 + 2 = 3 calls.
    assert len(session.calls) == 3


def test_connection_error_is_reported_as_fetch_failure():
    session = make_session([requests.exceptions.ConnectionError("dns")])
    c = GeMPublicCollector(timeout=1, max_retries=0, session=session)
    with pytest.raises(GeMCollectorError):
        c.fetch(DEFAULT_LISTING_URL)


def test_transient_timeout_then_success():
    session = make_session(
        [requests.exceptions.Timeout("slow"), FakeResponse(200, LISTING_HTML)]
    )
    c = GeMPublicCollector(timeout=1, max_retries=1, session=session)
    status, markup = c.fetch(DEFAULT_LISTING_URL)
    assert status == 200
    assert "GEM/2026/B/7845020" in markup


# --------------------------------------------------------------------------
# 6. 403 / 429 - immediate stop, no retries
# --------------------------------------------------------------------------

@pytest.mark.parametrize("code", [403, 429])
def test_403_and_429_raise_blocked_without_retrying(code):
    session = make_session([FakeResponse(code, "denied")])
    c = GeMPublicCollector(timeout=1, max_retries=3, session=session)
    with pytest.raises(GeMBlockedError) as exc:
        c.fetch(DEFAULT_LISTING_URL)
    assert exc.value.status_code == code
    assert len(session.calls) == 1, "403/429 must not be retried"


def test_blocked_flag_is_latched_after_403():
    session = make_session([FakeResponse(403, "denied"), FakeResponse(200, LISTING_HTML)])
    c = GeMPublicCollector(timeout=1, max_retries=0, session=session)
    with pytest.raises(GeMBlockedError):
        c.fetch(DEFAULT_LISTING_URL)
    assert c.blocked is True
    with pytest.raises(GeMBlockedError):
        c.fetch(DEFAULT_LISTING_URL)
    # A latched block must short-circuit without a second network call.
    assert len(session.calls) == 1


# --------------------------------------------------------------------------
# 7. 5xx - retried
# --------------------------------------------------------------------------

def test_5xx_is_retried_then_succeeds():
    session = make_session([FakeResponse(503, "busy"), FakeResponse(200, LISTING_HTML)])
    c = GeMPublicCollector(timeout=1, max_retries=2, session=session)
    status, _ = c.fetch(DEFAULT_LISTING_URL)
    assert status == 200
    assert len(session.calls) == 2


def test_persistent_5xx_raises_after_max_retries():
    session = make_session([FakeResponse(500, "broken")])
    c = GeMPublicCollector(timeout=1, max_retries=1, session=session)
    with pytest.raises(GeMCollectorError):
        c.fetch(DEFAULT_LISTING_URL)
    assert len(session.calls) == 2  # initial attempt + 1 retry


def test_retry_after_hint_is_honoured_in_backoff():
    session = make_session([
        FakeResponse(503, "busy", headers={"Retry-After": "7"}),
        FakeResponse(200, LISTING_HTML),
    ])
    c = GeMPublicCollector(timeout=1, max_retries=1, session=session)
    start = time.perf_counter()
    status, _ = c.fetch(DEFAULT_LISTING_URL)
    elapsed = time.perf_counter() - start
    assert status == 200
    # The hint is capped, so this must wait but never for a full 7 seconds of
    # unbounded sleeping.
    assert elapsed < 30


# --------------------------------------------------------------------------
# 8. Rate limiting
# --------------------------------------------------------------------------

def test_request_interval_enforces_minimum_delay_between_calls():
    session = make_session([FakeResponse(200, LISTING_HTML)])
    c = GeMPublicCollector(timeout=1, max_retries=0, request_interval=0.25, session=session)
    start = time.perf_counter()
    c.fetch(DEFAULT_LISTING_URL)
    c.fetch(DEFAULT_LISTING_URL)
    elapsed = time.perf_counter() - start
    assert elapsed >= 0.25, "second request must wait out the configured interval"


def test_respect_interval_is_a_noop_when_interval_is_zero():
    c = GeMPublicCollector(timeout=1, max_retries=0, request_interval=0,
                           session=make_session([FakeResponse(200, "")]))
    start = time.perf_counter()
    for _ in range(5):
        c._respect_interval()
    assert time.perf_counter() - start < 0.2


# --------------------------------------------------------------------------
# 9. URL allowlist / SSRF guardrails
# --------------------------------------------------------------------------

def test_allowed_hosts_default_to_public_gem_hosts():
    hosts = allowed_hosts()
    assert "bidplus.gem.gov.in" in hosts
    assert "gem.gov.in" in hosts


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.com/x",
        "https://gem.gov.in.evil.com/x",
        "http://169.254.169.254/latest/meta-data/",
        "http://127.0.0.1/admin",
        "http://localhost:8000/",
        "http://10.0.0.5/internal",
        "http://192.168.1.1/",
        "file:///etc/passwd",
        "ftp://bidplus.gem.gov.in/x",
        "",
        None,
    ],
)
def test_non_public_or_non_gem_urls_are_rejected(url):
    with pytest.raises(GeMUrlNotPermittedError):
        validate_public_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "https://bidplus.gem.gov.in/all-bids",
        "https://bidplus.gem.gov.in/showbidDocument/9673281",
        "https://gem.gov.in/",
    ],
)
def test_public_gem_urls_are_accepted(url):
    assert validate_public_url(url) == url


def test_collector_refuses_disallowed_host_without_requesting_it():
    session = make_session([FakeResponse(200, LISTING_HTML)])
    c = GeMPublicCollector(timeout=1, max_retries=0, session=session)
    with pytest.raises(GeMUrlNotPermittedError):
        c.fetch("https://evil.com/x")
    assert session.calls == [], "disallowed URL must be rejected before any request"


def test_resolve_targets_separates_permitted_from_rejected():
    permitted, rejected, errors = resolve_collection_targets(
        [
            "https://bidplus.gem.gov.in/all-bids",
            "https://evil.com/x",
            "https://bidplus.gem.gov.in/showbidDocument/9673281",
        ]
    )
    assert len(permitted) == 2
    assert rejected == ["https://evil.com/x"]
    assert len(errors) == 1
    assert errors[0]["field"] == "url"


def test_resolve_targets_returns_nothing_when_none_configured():
    # The default-listing fallback lives in the service layer, not here, so the
    # low-level resolver must not invent a URL of its own.
    assert resolve_collection_targets(None) == ([], [], [])


def test_service_defaults_to_the_public_listing_url_when_no_urls_given():
    import inspect

    from app.services.ingestion import gem_direct_service as svc

    source = inspect.getsource(svc.ingest_gem_direct_bids)
    assert "DEFAULT_LISTING_URL" in source


def test_max_urls_per_run_is_enforced():
    from app.core.config import settings

    original = settings.GEM_DIRECT_MAX_URLS_PER_RUN
    settings.GEM_DIRECT_MAX_URLS_PER_RUN = 1
    try:
        permitted, rejected, errors = resolve_collection_targets(
            [
                "https://bidplus.gem.gov.in/all-bids",
                "https://bidplus.gem.gov.in/showbidDocument/9673281",
            ]
        )
        assert len(permitted) == 1
        assert len(rejected) == 1
        assert errors
    finally:
        settings.GEM_DIRECT_MAX_URLS_PER_RUN = original


# --------------------------------------------------------------------------
# 10. Blocking detection helpers
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "status,markup,expected",
    [
        (401, "", True),
        (403, "", True),
        (429, "", True),
        (451, "", True),
        (200, "Access Denied", True),
        (200, "please solve the captcha", True),
        (200, "unusual traffic detected", True),
        (200, LISTING_HTML, False),
        # 5xx is a transient server fault, not a refusal: it must stay retryable.
        (500, "", False),
        (503, "", False),
        # A JavaScript-required shell is not a refusal either - it is handled by
        # falling back to the browser render instead of aborting the run.
        (200, "Please enable JavaScript and cookies to continue", False),
    ],
)
def test_looks_blocked(status, markup, expected):
    assert looks_blocked(status, markup) is expected


def test_html_to_text_strips_scripts_and_styles():
    markup = "<div>keep<script>drop()</script><style>.x{}</style></div>"
    text = html_to_text(markup)
    assert "keep" in text
    assert "drop()" not in text
    assert ".x{}" not in text


@pytest.mark.parametrize(
    "text,expected",
    [
        ("BID NO: GEM/2026/B/7845020", "GEM/2026/B/7845020"),
        ("gem/2025/a/123456", "gem/2025/a/123456"),
        ("Bid/RA Status", None),
        ("no reference here", None),
        (None, None),
    ],
)
def test_extract_bid_reference(text, expected):
    assert extract_bid_reference(text) == expected


def test_is_detail_url():
    assert is_detail_url("https://bidplus.gem.gov.in/showbidDocument/9673281") is True
    assert is_detail_url("https://bidplus.gem.gov.in/all-bids") is False
    assert is_detail_url(None) is False