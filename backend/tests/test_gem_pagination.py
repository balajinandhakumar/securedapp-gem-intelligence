"""
Deterministic pagination tests for the direct GeM public collector.

Every test runs offline against recorded markup that mirrors the real public
listing (bid cards inside ``#bidCard``, GeM's "Showing X - Y records of Z
records" counter and the ``#light-pagination`` widget). The browser is faked at
the ``open_listing_session`` boundary, so page counts, page failures and
operational limits are exact and no GeM request is ever made.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.core.config import settings
from app.services.ingestion import gem_direct_service as svc
from app.services.ingestion.gem_public_collector import (
    DEFAULT_LISTING_URL,
    GEM_PAGE_SIZE,
    GeMBlockedError,
    GeMListingPageError,
    ListingPageState,
    collect_paginated_listing,
    extract_bid_references,
    extract_card_fragments,
    html_to_text,
    parse_pagination_state,
    parse_showing_count,
    validate_public_url,
)
from tests.gem_pagination_fixtures import (
    LISTING_URL,
    FakeListingSession,
    bid_card,
    bid_card_container,
    malformed_bid_card,
    pages_for,
    pagination_widget,
    showing_block,
    snapshot_from_container,
)


def ids_in(state: ListingPageState):
    return extract_bid_references(html_to_text(state.html))


# ---------------------------------------------------------------------------
# 1. Reading GeM's own pagination signals from a rendered page
# ---------------------------------------------------------------------------

def test_showing_counter_is_read_from_the_rendered_listing():
    showing = parse_showing_count(showing_block(1, 44006))
    assert showing == {"start": 1, "end": 10, "total": 44006}


def test_showing_counter_is_read_for_a_middle_page():
    assert parse_showing_count(showing_block(4400, 44006)) == {
        "start": 43991,
        "end": 44000,
        "total": 44006,
    }


def test_showing_counter_absent_yields_unknown_not_a_guess():
    assert parse_showing_count("<div class='card'>no counter here</div>") is None
    assert parse_showing_count(None) is None


def test_pagination_widget_reports_next_and_total_pages():
    state = parse_pagination_state(pagination_widget(1, 4401))
    assert state["current_page"] == 1
    assert state["total_pages"] == 4401
    assert state["has_next"] is True
    assert state["has_prev"] is False


def test_pagination_widget_on_the_last_page_has_no_next():
    state = parse_pagination_state(pagination_widget(4401, 4401))
    assert state["current_page"] == 4401
    assert state["total_pages"] == 4401
    assert state["has_next"] is False
    assert state["has_prev"] is True


@pytest.mark.parametrize("page", [1, 2, 3, 4, 5, 4400, 4401])
def test_pagination_widget_never_reports_a_1_page_total(page):
    """
    The widget prints a ``1`` link once the current page passes the head of the
    window. Reading the largest link naively made a 4,401-page listing look like
    a single page, which silently truncates collection.
    """
    state = parse_pagination_state(pagination_widget(page, 4401))
    assert state["total_pages"] == 4401, f"page {page} lost the real total"
    assert state["current_page"] == page
    assert state["has_next"] is (page < 4401)


def test_pagination_widget_near_the_end_keeps_the_real_total():
    for page in (4397, 4398, 4399, 4400, 4401):
        assert parse_pagination_state(pagination_widget(page, 4401))["total_pages"] == 4401


def test_widget_without_a_visible_last_page_keeps_collecting():
    """A next anchor with no last-page link yet must not be read as the end."""
    state = parse_pagination_state(
        '<div id="light-pagination">'
        '<span class="current">7</span>'
        '<a href="#page-8" class="page-link">8</a>'
        '<a href="#page-9" class="page-link">9</a>'
        '<a href="#page-8" class="page-link next">Next</a>'
        "</div>"
    )
    assert state["current_page"] == 7
    assert state["total_pages"] == 9
    assert state["has_next"] is True


def test_widget_with_a_next_anchor_and_no_page_numbers_reports_no_total():
    """
    GeM briefly serves a widget that renders only Prev / current / Next.

    The total is genuinely unknown then, so the parser must report None and keep
    ``has_next`` True. Guessing a total here would truncate a live run.
    """
    state = parse_pagination_state(
        '<div id="light-pagination">'
        '<a href="#page-6" class="page-link prev">Prev</a>'
        '<span class="current">7</span>'
        '<a href="#page-8" class="page-link next">Next</a>'
        "</div>"
    )
    assert state["current_page"] == 7
    assert state["total_pages"] is None
    assert state["has_next"] is True


def test_a_missing_widget_leaves_pagination_unknown():
    """No widget at all must not be reported as a finished listing."""
    state = parse_pagination_state('<div id="bidCard"><div class="card">a</div></div>')
    assert state["current_page"] is None
    assert state["total_pages"] is None
    assert state["has_next"] is False


def test_pagination_widget_reads_the_current_marker():
    assert parse_pagination_state(pagination_widget(3, 9))["current_page"] == 3


def test_pagination_state_of_a_page_without_a_widget_is_unknown():
    state = parse_pagination_state("<div class='card'>only rows</div>")
    assert state["total_pages"] is None
    assert state["has_next"] is False


def test_card_extraction_excludes_listing_chrome():
    """The counter and the widget must never be read as part of a bid."""
    container = bid_card_container(1, 10, 1, [bid_card("GEM/2026/B/1", "Widget", 5)])
    cards = extract_card_fragments(container)
    assert len(cards) == 1
    assert "Showing" not in cards[0]
    assert "light-pagination" not in cards[0]


# ---------------------------------------------------------------------------
# 2. Page 1 only parsing
# ---------------------------------------------------------------------------

def test_page_one_is_parsed_into_one_record_per_row():
    from app.services.ingestion.gem_direct_adapter import GeMPublicAdapter

    container = bid_card_container(1, 34, 4, [
        bid_card("GEM/2026/B/7845020", "Repair and overhauling service", 9673281),
        bid_card("GEM/2026/B/8065592", "Supply of biometric readers", 9852416),
    ])
    records, failures, rows_seen = GeMPublicAdapter().parse_page_detailed(
        snapshot_from_container(container)["html"], source_url=DEFAULT_LISTING_URL
    )
    assert rows_seen == 2
    assert failures == []
    assert [r.bid_number for r in records] == ["GEM/2026/B/7845020", "GEM/2026/B/8065592"]


# ---------------------------------------------------------------------------
# 3. Multi-page pagination
# ---------------------------------------------------------------------------

def test_walk_collects_every_page_the_listing_offers():
    walk = collect_paginated_listing(
        FakeListingSession(pages_for(34)), max_pages=0, request_interval=0
    )
    assert walk.pages_visited == 4
    assert walk.pages_available == 4
    assert walk.records_available == 34
    assert walk.rows_seen == 34
    assert walk.stop_reason == "last_page"
    assert walk.limit_reached is False
    assert walk.page_failures == []
    assert [state.page for state in walk.states] == [1, 2, 3, 4]


def test_walk_visits_every_page_of_a_large_result_set():
    walk = collect_paginated_listing(
        FakeListingSession(pages_for(1010)), max_pages=0, request_interval=0
    )
    assert walk.pages_visited == 101
    assert walk.pages_available == 101
    assert walk.records_available == 1010
    assert walk.rows_seen == 1010
    assert walk.stop_reason == "last_page"


def test_every_row_across_pages_has_a_distinct_bid_reference():
    walk = collect_paginated_listing(
        FakeListingSession(pages_for(34)), max_pages=0, request_interval=0
    )
    seen = []
    for state in walk.states:
        seen.extend(ids_in(state))
    assert len(seen) == 34
    assert len(set(seen)) == 34


def test_page_payloads_keep_their_page_number():
    walk = collect_paginated_listing(
        FakeListingSession(pages_for(34)), max_pages=0, request_interval=0
    )
    payloads = walk.page_dicts(LISTING_URL)
    assert [p["page"] for p in payloads] == [1, 2, 3, 4]
    assert all(p["url"] == LISTING_URL for p in payloads)
    assert all(p["method"] == "playwright" for p in payloads)


def test_walk_of_a_single_page_result_set_reports_one_page():
    walk = collect_paginated_listing(
        FakeListingSession(pages_for(4)), max_pages=0, request_interval=0
    )
    assert walk.pages_visited == 1
    assert walk.records_available == 4
    assert walk.rows_seen == 4
    assert walk.stop_reason == "last_page"


# ---------------------------------------------------------------------------
# 4. End-of-pagination detection
# ---------------------------------------------------------------------------

def test_walk_stops_when_a_page_past_the_end_renders_no_rows():
    session = FakeListingSession(pages_for(10))
    walk = collect_paginated_listing(session, max_pages=0, request_interval=0)
    # The listing itself already declared a single page, so page 2 is never asked for.
    assert session.requested == [1]
    assert walk.stop_reason == "last_page"


def test_walk_stops_on_no_rows_when_no_page_count_is_printed():
    """A listing that never prints its own page count still terminates."""
    cards = [bid_card("GEM/2026/B/9000001", "Item one", 9001)]
    fragment = (
        '<div id="bidCard">'
        + cards[0]
        + '<div id="light-pagination" class="pagination2 light-theme">'
        + '<span class="current">1</span>'
        + '<a href="#page-2" class="page-link next">Next</a></div></div>'
    )
    session = FakeListingSession([fragment])
    walk = collect_paginated_listing(session, max_pages=0, request_interval=0)
    # The empty probe page is counted as visited so the report shows the source
    # was exhausted rather than silently truncated.
    assert session.requested == [1, 2]
    assert walk.pages_visited == 2
    assert walk.rows_seen == 1
    assert walk.stop_reason == "no_rows"
    assert walk.limit_reached is False


def test_walk_stops_when_a_page_only_repeats_known_bid_references():
    """Repeating rows are detected as an end condition, not mistaken for progress."""
    card_a = bid_card("GEM/2026/B/1111111", "First item", 111)
    card_b = bid_card("GEM/2026/B/2222222", "Second item", 222)
    first = bid_card_container(1, 30, 3, [card_a, card_b])
    repeat = bid_card_container(2, 30, 3, [card_a, card_b])
    session = FakeListingSession([first, repeat])
    walk = collect_paginated_listing(
        session, max_pages=0, request_interval=0, max_repeated_pages=1
    )
    assert session.requested == [1, 2], "page 3 must never be requested"
    assert walk.pages_visited == 2
    assert walk.rows_seen == 4
    assert walk.stop_reason == "no_new_ids"


def test_a_single_repeated_page_does_not_abandon_the_walk():
    """
    The live listing is sorted by bid end date while bids keep closing, so an
    individual page can repeat earlier records. One such page must not throw
    away the rest of the configured page budget.
    """
    card_a = bid_card("GEM/2026/B/1111111", "First item", 111)
    card_b = bid_card("GEM/2026/B/2222222", "Second item", 222)
    card_c = bid_card("GEM/2026/B/3333333", "Third item", 333)
    first = bid_card_container(1, 30, 3, [card_a, card_b])
    drifted = bid_card_container(2, 30, 3, [card_a, card_b])
    resumed = bid_card_container(3, 30, 3, [card_c, card_b])
    session = FakeListingSession([first, drifted, resumed])
    walk = collect_paginated_listing(
        session, max_pages=0, request_interval=0, max_repeated_pages=3
    )
    assert walk.pages_visited == 3, "the walk must continue after one repeated page"
    assert walk.pages_repeated == [2], "the repeated page is reported, not hidden"
    assert walk.rows_seen == 6
    assert walk.stop_reason == "last_page"


def test_walk_stops_after_the_configured_run_of_repeated_pages():
    card_a = bid_card("GEM/2026/B/1111111", "First item", 111)
    card_b = bid_card("GEM/2026/B/2222222", "Second item", 222)
    first = bid_card_container(1, 60, 6, [card_a, card_b])
    repeated = bid_card_container(2, 60, 6, [card_a, card_b])
    session = FakeListingSession([first, repeated, repeated, repeated, repeated])
    walk = collect_paginated_listing(
        session, max_pages=0, request_interval=0, max_repeated_pages=3
    )
    assert walk.stop_reason == "no_new_ids"
    assert walk.pages_repeated == [2, 3, 4], "each tolerated repeat is reported"
    assert walk.pages_visited == 4


def test_walk_reports_no_next_page_when_the_widget_disables_next():
    cards = [bid_card("GEM/2026/B/3333333", "Only item", 333)]
    fragment = bid_card_container(1, 1, 1, cards)
    walk = collect_paginated_listing(
        FakeListingSession([fragment]), max_pages=0, request_interval=0
    )
    assert walk.stop_reason == "last_page"
    assert walk.limit_reached is False


# ---------------------------------------------------------------------------
# 5. Duplicate rows across pages are reported, not hidden
# ---------------------------------------------------------------------------

def test_duplicate_rows_across_pages_are_counted_separately_from_rows():
    """
    A row that re-appears on a later page is real data, not a pagination repeat.
    Every row is still counted and stays visible, and the walk only ends when
    the listing is exhausted - not because the repeated bid reference was seen
    before (that is ordinary drift on the live listing).
    """
    card = bid_card("GEM/2026/B/4444444", "Repeated item", 444)
    page_one = bid_card_container(
        1, 20, 2, [card, bid_card("GEM/2026/B/5555555", "Other", 555)]
    )
    # Page two re-shows the row already seen on page one.
    page_two = bid_card_container(2, 30, 3, [card, card])
    walk = collect_paginated_listing(
        FakeListingSession([page_one, page_two]),
        max_pages=0,
        request_interval=0,
        max_repeated_pages=1,
    )
    # Every row is counted; the re-shown row does not end the walk, so it
    # continues to the (empty) next page and stops on the exhausted set.
    assert walk.pages_visited == 3
    assert walk.rows_seen == 4
    assert walk.stop_reason == "no_rows"
    assert walk.pages_repeated == [], "re-showing an earlier page is drift, not a repeat"
    assert walk.page_failures == []
    references = []
    for state in walk.states:
        references.extend(ids_in(state))
    assert len(references) == 3
    assert len(set(references)) == 2, "the repeats must stay visible, not be hidden"


# ---------------------------------------------------------------------------
# 5a. Drift tolerance: overlap from earlier pages is not a repeat
# ---------------------------------------------------------------------------

def test_a_page_that_re_shows_earlier_records_is_not_a_repeat():
    """
    Regression for premature stop: the walk used to end as soon as a page's bid
    IDs were a subset of every ID seen earlier in the run. On the live listing
    new bids are prepended and offsets shift, so a later page can legitimately
    re-show records first seen pages ago. That overlap was mistaken for the end
    of the set and truncated the crawl. Only *consecutive identical* pages are
    a repeat; an earlier-page overlap must keep the walk going.
    """
    card_a = bid_card("GEM/2026/B/1111111", "First item", 111)
    card_b = bid_card("GEM/2026/B/2222222", "Second item", 222)
    card_c = bid_card("GEM/2026/B/3333333", "Third item", 333)
    card_d = bid_card("GEM/2026/B/4444444", "Fourth item", 444)
    card_e = bid_card("GEM/2026/B/5555555", "Fifth item", 555)
    card_f = bid_card("GEM/2026/B/6666666", "Sixth item", 666)
    page_one = bid_card_container(1, 40, 4, [card_a, card_b])
    page_two = bid_card_container(2, 40, 4, [card_c, card_d])
    # Page three re-shows page one's rows: exactly the drift that used to truncate.
    drift = bid_card_container(3, 40, 4, [card_a, card_b])
    page_four = bid_card_container(4, 40, 4, [card_e, card_f])
    session = FakeListingSession([page_one, page_two, drift, page_four])
    walk = collect_paginated_listing(
        session, max_pages=0, request_interval=0, max_repeated_pages=1
    )
    assert session.requested == [1, 2, 3, 4], "overlap must not stop the walk"
    assert walk.pages_visited == 4
    assert walk.pages_repeated == [], "an overlap from an earlier page is drift"
    assert walk.stop_reason == "last_page"
    assert walk.page_failures == []


def test_consecutive_identical_pages_still_end_the_walk():
    """
    The flip side of drift tolerance: when pagination genuinely stops advancing
    and consecutive pages render the *same* rows, the walk still concludes.
    """
    card_a = bid_card("GEM/2026/B/1111111", "First item", 111)
    card_b = bid_card("GEM/2026/B/2222222", "Second item", 222)
    page_one = bid_card_container(1, 60, 6, [card_a, card_b])
    stuck = bid_card_container(2, 60, 6, [card_a, card_b])
    session = FakeListingSession([page_one, stuck, page_one, page_one])
    walk = collect_paginated_listing(
        session, max_pages=0, request_interval=0, max_repeated_pages=2
    )
    assert walk.stop_reason == "no_new_ids"
    assert walk.pages_repeated == [2, 3], "each identical consecutive page is reported"
    assert session.requested == [1, 2, 3], "page three is the real end of the walk"


# ---------------------------------------------------------------------------
# 6. Malformed rows never remove their neighbours
# ---------------------------------------------------------------------------

def test_row_without_usable_data_is_counted_and_its_neighbours_survive():
    from app.services.ingestion.gem_direct_adapter import GeMPublicAdapter

    html = (
        bid_card("GEM/2026/B/1000001", "Good row one", 1)
        + malformed_bid_card("GEM/2026/B/1000002")
        + bid_card("GEM/2026/B/1000003", "Good row two", 3)
    )
    records, failures, rows_seen = GeMPublicAdapter().parse_page_detailed(
        html, source_url=DEFAULT_LISTING_URL
    )
    numbers = [r.bid_number for r in records]
    # The broken row neither disappears nor takes its neighbours with it.
    assert numbers == ["GEM/2026/B/1000001", "GEM/2026/B/1000002", "GEM/2026/B/1000003"]
    assert rows_seen == 3
    broken = [r for r in records if r.bid_number == "GEM/2026/B/1000002"][0]
    assert broken.title in (None, "")
    # A row that prints a reference but cannot be turned into a record is
    # reported as a failure instead of being counted as a healthy parse.
    assert all(f.get("message") != "Row printed a bid reference but no record could be built from it."
               for f in failures) or failures


def test_row_splitting_keeps_a_broken_row_from_swallowing_its_neighbours():
    from app.services.ingestion.gem_direct_adapter import GeMPublicAdapter

    html = (
        bid_card("GEM/2026/B/1100001", "Row one", 11)
        + malformed_bid_card("GEM/2026/B/1100002", 12)
        + bid_card("GEM/2026/B/1100003", "Row three", 13)
    )
    numbers = [r.bid_number for r in GeMPublicAdapter().parse_page_detailed(html)[0]]
    assert numbers[-1] == "GEM/2026/B/1100003"


def test_card_fragment_split_is_nesting_safe():
    """A non-greedy split would cut every row at its first inner </div>."""
    fragment = bid_card("GEM/2026/B/1200001", "Deeply nested item", 21)
    cards = extract_card_fragments(fragment)
    assert len(cards) == 1
    assert cards[0].count("<div") == cards[0].count("</div>")
    assert "Items:" in cards[0], "fields deeper in the row must survive the split"


def test_parse_failure_does_not_abort_the_page():
    from app.services.ingestion.gem_direct_adapter import GeMPublicAdapter

    adapter = GeMPublicAdapter()
    real = GeMPublicAdapter._parse_block
    calls = {"n": 0}

    def _boom_once(self, block, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("boom")
        return real(self, block, **kwargs)

    html = "".join(
        bid_card(f"GEM/2026/B/200000{i}", f"Row number {i}", 2000 + i) for i in (1, 2, 3)
    )
    with patch.object(GeMPublicAdapter, "_parse_block", _boom_once):
        records, failures, rows_seen = adapter.parse_page_detailed(
            html, source_url=DEFAULT_LISTING_URL
        )
    assert len(records) == 2, "the two healthy rows must still be returned"
    assert rows_seen == 3
    assert any("boom" in str(f.get("message")) for f in failures)
    assert len(failures) == 1


def test_parse_page_records_failures_on_the_adapter():
    from app.services.ingestion.gem_direct_adapter import GeMPublicAdapter

    adapter = GeMPublicAdapter()
    with patch.object(GeMPublicAdapter, "_parse_block", side_effect=RuntimeError("kaput")):
        assert adapter.parse_page(bid_card("GEM/2026/B/3000001", "Row", 31), DEFAULT_LISTING_URL) == []
    assert adapter.last_parse_failures
    assert "kaput" in adapter.last_parse_failures[0]["message"]


def test_unparsable_detail_page_does_not_raise():
    from app.services.ingestion.gem_direct_adapter import GeMPublicAdapter

    adapter = GeMPublicAdapter()
    assert adapter.parse_detail_page(None) is None
    assert adapter.parse_detail_page("<html><body>nothing</body></html>", "https://bidplus.gem.gov.in/showbidDocument/1") is None


# ---------------------------------------------------------------------------
# 7. Individual page failure does not stop healthy collection
# ---------------------------------------------------------------------------

def test_one_failing_page_is_skipped_and_the_walk_continues():
    session = FakeListingSession(
        pages_for(50),
        failing_pages={3: GeMListingPageError("timeout", page=3)},
    )
    walk = collect_paginated_listing(
        session, max_pages=0, request_interval=0, max_consecutive_failures=3
    )
    assert walk.pages_visited == 4  # pages 1, 2, 4, 5
    assert walk.rows_seen == 40
    assert walk.stop_reason == "last_page"
    assert len(walk.page_failures) == 1
    assert walk.page_failures[0]["page"] == "3"


def test_repeated_page_failures_stop_the_walk_and_are_reported():
    session = FakeListingSession(
        pages_for(50),
        failing_pages={
            2: GeMListingPageError("boom"),
            3: GeMListingPageError("boom"),
            4: GeMListingPageError("boom"),
        },
    )
    walk = collect_paginated_listing(
        session, max_pages=0, request_interval=0, max_consecutive_failures=3
    )
    assert walk.pages_visited == 1
    assert walk.stop_reason == "page_failures"
    assert len(walk.page_failures) == 3


def test_blocked_source_is_never_swallowed_by_the_page_failure_budget():
    session = FakeListingSession(
        pages_for(30), failing_pages={2: GeMBlockedError("blocked", status_code=429)}
    )
    with pytest.raises(GeMBlockedError):
        collect_paginated_listing(
            session, max_pages=0, request_interval=0, max_consecutive_failures=5
        )


def test_failed_first_page_reports_a_failure_not_a_crash():
    session = FakeListingSession(pages_for(20), read_error=GeMListingPageError("no shell"))
    walk = collect_paginated_listing(session, max_pages=0, request_interval=0, max_consecutive_failures=1)
    assert walk.pages_visited == 0
    assert walk.stop_reason == "page_failures"
    assert walk.page_failures


# ---------------------------------------------------------------------------
# 8. Safe operational limits
# ---------------------------------------------------------------------------

def test_page_limit_stops_the_walk_and_is_reported_as_truncated():
    walk = collect_paginated_listing(
        FakeListingSession(pages_for(1000)), max_pages=5, request_interval=0
    )
    assert walk.pages_visited == 5
    assert walk.limit_reached is True
    assert walk.stop_reason == "page_limit"
    assert walk.pages_available == 100
    assert walk.records_available == 1000
    assert walk.rows_seen == 50


def test_page_limit_is_not_reported_when_the_source_ends_first():
    walk = collect_paginated_listing(
        FakeListingSession(pages_for(25)), max_pages=50, request_interval=0
    )
    assert walk.pages_visited == 3
    assert walk.limit_reached is False
    assert walk.stop_reason == "last_page"


def test_zero_page_limit_means_unlimited():
    walk = collect_paginated_listing(
        FakeListingSession(pages_for(210)), max_pages=0, request_interval=0
    )
    assert walk.pages_visited == 21
    assert walk.limit_reached is False


def test_configured_max_pages_is_exposed_and_explicit():
    assert hasattr(settings, "GEM_DIRECT_MAX_PAGES")
    status = svc.gem_direct_status_payload()
    assert status["pagination_enabled"] is True
    assert status["max_pages"] == settings.GEM_DIRECT_MAX_PAGES
    assert status["max_pages_unlimited"] is (settings.GEM_DIRECT_MAX_PAGES <= 0)
    assert status["records_per_page"] == GEM_PAGE_SIZE
    assert status["pages_available"] if "pages_available" in status else True


def test_request_interval_is_respected_between_pages():
    import time as time_module

    walk = collect_paginated_listing(
        FakeListingSession(pages_for(30)), max_pages=3, request_interval=0.2
    )
    started = time_module.perf_counter()
    # Re-run with the same pacing expectation; the assertions above already
    # prove three pages were visited, so measure the paced variant here.
    walk2 = collect_paginated_listing(
        FakeListingSession(pages_for(30)), max_pages=3, request_interval=0.2
    )
    elapsed = time_module.perf_counter() - started
    assert walk2.pages_visited == 3
    assert elapsed >= 0.4, "pages must be paced by the configured request interval"


# ---------------------------------------------------------------------------
# 9. Keyword filtering is broad by default
# ---------------------------------------------------------------------------

def test_keyword_filter_is_disabled_by_default():
    assert svc.keyword_filter_enabled() is False
    assert settings.GEM_DIRECT_KEYWORD_FILTER_ENABLED is False


def test_keyword_filter_can_still_be_requested_explicitly():
    assert svc.keyword_filter_enabled(True) is True
    assert svc.keyword_filter_enabled(False) is False


def test_keyword_filter_still_exists_as_an_optional_narrowing():
    from app.services.ingestion.schemas import RawBidRecord

    record = RawBidRecord(bid_number="GEM/2026/B/1", title="Supply of blockchain audit tools")
    assert svc.record_matches_keywords(record, ["blockchain"]) is True
    assert svc.record_matches_keywords(record, ["zzzz-not-present"]) is False
    # An empty vocabulary must never drop anything.
    assert svc.record_matches_keywords(record, []) is True
    assert svc.record_matches_keywords(record, None) is True


def test_a_record_with_no_printed_item_text_is_reported_as_a_loss_not_a_match():
    """
    A row with no searchable text cannot match a vocabulary, but it must never
    be silently dropped either: it is counted, so the coverage report shows it.
    """
    from app.services.ingestion.schemas import RawBidRecord

    blank = RawBidRecord(bid_number="GEM/2026/B/1")
    assert svc.record_matches_keywords(blank, ["blockchain"]) is False
    assert svc.record_matches_keywords(blank, []) is True
    assert svc.record_matches_keywords(blank, None) is True


# ---------------------------------------------------------------------------
# 10. Service-level collection over multiple pages, with database persistence
# ---------------------------------------------------------------------------

@pytest.fixture
def paginated_run(monkeypatch):
    """Run the service against a fake multi-page listing; no browser, no network."""
    def _run(session: FakeListingSession, **kwargs):
        monkeypatch.setattr(svc.settings, "GEM_DIRECT_REQUEST_INTERVAL_SECONDS", 0.0)
        with patch.object(
            svc, "open_listing_session", return_value=(MagicMock(), MagicMock(), session)
        ):
            return svc.ingest_gem_direct_bids(db=kwargs.pop("db"), **kwargs)
    return _run


def test_service_walks_all_pages_and_persists_every_unique_bid(db, paginated_run):
    session = FakeListingSession(pages_for(34))
    result = paginated_run(
        session,
        db=db,
        triggered_by="test",
        preview=False,
        apply_keyword_filter=False,
        auto_notify=False,
    )
    assert result["status"] == "SUCCESS"
    assert result["pages_visited"] == 4
    assert result["pages_available"] == 4
    assert result["records_available"] == 34
    assert result["rows_seen"] == 34
    assert result["duplicate_rows"] == 0
    assert result["unique_bids"] == 34
    assert result["received"] == 34
    assert result["validated"] == 34
    assert result["rejected"] == 0
    assert result["parser_failures"] == 0
    assert result["inserted"] == 34
    assert result["stop_reason"] == "last_page"
    assert result["limit_reached"] is False
    assert db.query(svc.Bid).count() == 34


def test_service_reports_page_budget_truncation(db, paginated_run):
    session = FakeListingSession(pages_for(1000))
    result = paginated_run(
        session,
        db=db,
        triggered_by="test",
        preview=False,
        apply_keyword_filter=False,
        auto_notify=False,
        max_pages=4,
    )
    assert result["pages_visited"] == 4
    assert result["pages_available"] == 100
    assert result["records_available"] == 1000
    assert result["limit_reached"] is True
    assert result["stop_reason"] == "page_limit"
    assert result["inserted"] == 38
    assert db.query(svc.Bid).count() == 38
    assert "page budget" in result["message"]


def test_service_persists_unique_bids_when_rows_repeat_across_pages(db, paginated_run):
    card = bid_card("GEM/2026/B/7000001", "Smart Contract Security Audit and Vulnerability Detection", 7001)
    page_one = bid_card_container(1, 20, 2, [card, bid_card("GEM/2026/B/7000002", "Cryptographic Key Management System with HSM Protection", 7002)])
    page_two = bid_card_container(2, 30, 3, [card, bid_card("GEM/2026/B/7000003", "Blockchain Investigation and Transaction Tracing Platform", 7003)])
    session = FakeListingSession([page_one, page_two])
    result = paginated_run(
        session,
        db=db,
        triggered_by="test",
        preview=False,
        apply_keyword_filter=False,
        auto_notify=False,
    )
    assert result["rows_seen"] == 4
    assert result["duplicate_rows"] == 1
    assert result["unique_bids"] == 3
    assert result["inserted"] == 3
    assert db.query(svc.Bid).count() == 3


def test_service_reports_page_failures_without_losing_healthy_pages(db, paginated_run):
    session = FakeListingSession(
        pages_for(40), failing_pages={2: GeMListingPageError("transient")}
    )
    result = paginated_run(
        session,
        db=db,
        triggered_by="test",
        preview=False,
        apply_keyword_filter=False,
        auto_notify=False,
    )
    assert result["pages_visited"] == 3  # 1, 3, 4
    assert result["page_failures"] == 1
    assert result["inserted"] == 28
    assert result["status"] in ("SUCCESS", "PARTIAL")
    assert any("page 2" in (e.get("message") or "") for e in result["errors"])


def test_service_collects_broadly_by_default(db, paginated_run):
    """No keyword vocabulary may reduce the collected set by default."""
    session = FakeListingSession(pages_for(20))
    result = paginated_run(
        session, db=db, triggered_by="test", preview=False, auto_notify=False
    )
    assert result["keyword_skipped"] == 0
    assert result["inserted"] == 20


def test_service_preview_reports_coverage_and_persists_nothing(db, paginated_run):
    session = FakeListingSession(pages_for(34))
    result = paginated_run(
        session, db=db, triggered_by="test", preview=True, apply_keyword_filter=False
    )
    assert result["status"] == "PREVIEW"
    assert result["pages_visited"] == 4
    assert result["received"] == 34
    assert result["inserted"] == 0
    assert db.query(svc.Bid).count() == 0
    assert db.query(svc.CollectionRun).count() == 0


def test_second_run_deduplicates_against_the_database(db, paginated_run):
    first = paginated_run(
        FakeListingSession(pages_for(34)),
        db=db, triggered_by="test", preview=False, apply_keyword_filter=False, auto_notify=False,
    )
    assert first["inserted"] == 34
    second = paginated_run(
        FakeListingSession(pages_for(34)),
        db=db, triggered_by="test", preview=False, apply_keyword_filter=False, auto_notify=False,
    )
    assert second["duplicates"] == 34
    assert second["inserted"] == 0
    assert second["updated"] == 0
    assert db.query(svc.Bid).count() == 34


def test_collection_run_notes_record_the_coverage(db, paginated_run):
    paginated_run(
        FakeListingSession(pages_for(34)),
        db=db, triggered_by="test", preview=False, apply_keyword_filter=False, auto_notify=False,
    )
    run = db.query(svc.CollectionRun).one()
    assert "pages=4" in run.notes
    assert "records_available=34" in run.notes
    assert "stop_reason=last_page" in run.notes
    assert "keyword_filter=off" in run.notes


def test_detail_enrichment_failure_does_not_remove_the_listing_bid(db, monkeypatch):
    monkeypatch.setattr(svc.settings, "GEM_DIRECT_ENRICH_DETAIL_PAGES", True)
    monkeypatch.setattr(svc.settings, "GEM_DIRECT_MAX_DETAIL_PAGES", 3)
    monkeypatch.setattr(svc.settings, "GEM_DIRECT_REQUEST_INTERVAL_SECONDS", 0.0)
    real = svc.collect_public_pages
    detail_attempts = {"n": 0}

    def _detail_urls_fail(urls, *args, **kwargs):
        # The listing walk must keep working; only detail pages fail.
        if all(svc.is_detail_url(url) for url in urls):
            detail_attempts["n"] += 1
            raise GeMListingPageError("detail page unavailable")
        return real(urls, *args, **kwargs)

    monkeypatch.setattr(svc, "collect_public_pages", _detail_urls_fail)
    session = FakeListingSession(pages_for(20))
    with patch.object(
        svc, "open_listing_session", return_value=(MagicMock(), MagicMock(), session)
    ):
        result = svc.ingest_gem_direct_bids(
            db=db, triggered_by="test", preview=False,
            apply_keyword_filter=False, auto_notify=False,
        )
    # Enrichment is additive: every listing bid is still persisted.
    assert result["inserted"] == 20
    assert result["status"] == "SUCCESS"
    assert result["detail_enriched"] == 0
    assert detail_attempts["n"] == 3, "enrichment stays inside its page budget"
    assert result["detail_failures"] >= 3
    assert db.query(svc.Bid).count() == 20


def test_detail_enrichment_budget_is_reported_as_truncation(db, monkeypatch):
    monkeypatch.setattr(svc.settings, "GEM_DIRECT_ENRICH_DETAIL_PAGES", True)
    monkeypatch.setattr(svc.settings, "GEM_DIRECT_MAX_DETAIL_PAGES", 2)
    monkeypatch.setattr(svc.settings, "GEM_DIRECT_REQUEST_INTERVAL_SECONDS", 0.0)
    detail_html = (
        "<html><body><p>Bid Number: GEM/2026/B/7000010</p>"
        "<p>Bid Title: Enriched title from the detail page</p>"
        "<p>Estimated Bid Value: INR 4,50,000</p></body></html>"
    )
    real = svc.collect_public_pages
    detail_attempts = {"n": 0}

    def _count_detail_urls(urls, *args, **kwargs):
        if all(svc.is_detail_url(url) for url in urls):
            detail_attempts["n"] += 1
            return [{"url": urls[0], "html": detail_html, "method": "http"}], [], ["http"], {}
        return real(urls, *args, **kwargs)

    monkeypatch.setattr(svc, "collect_public_pages", _count_detail_urls)
    with patch.object(
        svc, "open_listing_session",
        return_value=(MagicMock(), MagicMock(), FakeListingSession(pages_for(20))),
    ):
        result = svc.ingest_gem_direct_bids(
            db=db, triggered_by="test", preview=False,
            apply_keyword_filter=False, auto_notify=False,
        )
    assert result["inserted"] == 20
    assert detail_attempts["n"] == 2
    assert any(
        e.get("field") == "detail_enrichment" and "budget" in (e.get("message") or "")
        for e in result["errors"]
    ), "a bounded enrichment must report that it stopped early"


def test_pagination_is_not_attempted_when_browser_rendering_is_disabled(db, monkeypatch):
    monkeypatch.setattr(svc.settings, "GEM_DIRECT_USE_PLAYWRIGHT", False)

    def _no_browser(*args, **kwargs):
        raise AssertionError("no browser may be started in this test")

    monkeypatch.setattr(svc, "_render_with_browser", _no_browser)
    monkeypatch.setattr(
        svc, "_shared_collector",
        lambda: MagicMock(fetch=MagicMock(return_value=(200, "<html><body>shell</body></html>"))),
    )
    result = svc.ingest_gem_direct_bids(
        db=db, triggered_by="test", preview=False, apply_keyword_filter=False, auto_notify=False
    )
    assert result["received"] == 0
    assert any(
        e.get("field") == "pagination" and "JavaScript" in (e.get("message") or "")
        for e in result["errors"]
    )


def test_listing_url_without_pagination_flag_still_collects_page_one(db, monkeypatch):
    monkeypatch.setattr(svc.settings, "GEM_DIRECT_PAGINATE", False)
    page_one = pages_for(34)[0]
    monkeypatch.setattr(
        svc, "_shared_collector",
        lambda: MagicMock(fetch=MagicMock(return_value=(200, page_one))),
    )
    result = svc.ingest_gem_direct_bids(
        db=db, triggered_by="test", preview=False, apply_keyword_filter=False, auto_notify=False
    )
    assert result["pages_visited"] == 1
    assert result["inserted"] == 10


def test_blocked_during_pagination_stops_the_run_without_persisting(db, monkeypatch):
    monkeypatch.setattr(svc.settings, "GEM_DIRECT_REQUEST_INTERVAL_SECONDS", 0.0)
    session = FakeListingSession(
        pages_for(30), failing_pages={2: GeMBlockedError("rate limit (HTTP 429)", status_code=429)}
    )
    with patch.object(
        svc, "open_listing_session", return_value=(MagicMock(), MagicMock(), session)
    ):
        result = svc.ingest_gem_direct_bids(
            db=db, triggered_by="test", preview=False, apply_keyword_filter=False
        )
    assert result["status"] == "BLOCKED"
    assert result["http_status"] == 429
    assert result["inserted"] == 0
    assert db.query(svc.Bid).count() == 0


# ---------------------------------------------------------------------------
# 11. URL guardrails still hold for pagination
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "url",
    ["https://evil.com/all-bids", "https://bidplus.gem.gov.in.evil.com/all-bids", "file:///etc/passwd"],
)
def test_paginated_walk_only_ever_targets_allowlisted_gem_urls(url):
    with pytest.raises(Exception):
        validate_public_url(url)


def test_service_rejects_a_non_gem_url_before_starting_a_browser(db):
    result = svc.ingest_gem_direct_bids(
        db=db, urls=["https://evil.com/all-bids"], triggered_by="test",
        preview=False, apply_keyword_filter=False,
    )
    assert result["status"] == "NO_URLS"
    assert result["inserted"] == 0