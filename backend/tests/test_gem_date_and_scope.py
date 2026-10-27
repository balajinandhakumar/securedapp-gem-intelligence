"""Regression tests for the fixes proven necessary by live GeM evidence.

Covered here:
  * GeM's DD-MM-YYYY 12-hour dates must not be read as US month-first dates.
  * GeM's own item-group label (``data-original-title``) is the ``category``
    field the 11-product matcher reads; it was silently dropped before.
  * The listing scope (bid status / bid kind / sort) is configurable, reported
    back to the caller, and never silently widened.
"""
from __future__ import annotations

import pytest

from app.core.config import settings
from app.services.ingestion.gem_direct_adapter import GeMPublicAdapter
from app.services.ingestion.gem_public_collector import GeMPublicCollector
from app.services.ingestion.normalizer import parse_datetime

from tests.gem_pagination_fixtures import bid_card_with_group_label


# ---------------------------------------------------------------------------
# 1. Date parsing: DD-MM-YYYY, the format GeM actually renders
# ---------------------------------------------------------------------------
class TestGeMDateParsing:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            # Ongoing listing: 05-10-2026 is 5 October, not 10 May.
            ("05-10-2026 9:00 PM", (2026, 10, 5, 21, 0)),
            ("20-05-2026 3:30 PM", (2026, 5, 20, 15, 30)),
            ("24-09-2026 11:15 PM", (2026, 9, 24, 23, 15)),
            # Two-digit first component: day-first is unambiguous enough because
            # GeM renders DD-MM-YYYY (its first component reaches 24/31, which
            # no month can).
            ("08-05-2026 10:00 AM", (2026, 5, 8, 10, 0)),
            ("11-09-2026 6:05 PM", (2026, 9, 11, 18, 5)),
        ],
    )
    def test_day_first_twelve_hour_formats(self, raw, expected):
        parsed = parse_datetime(raw)
        assert parsed is not None, f"{raw!r} must parse"
        assert (parsed.year, parsed.month, parsed.day, parsed.hour, parsed.minute) == expected

    def test_day_first_is_never_swapped_to_month_first(self):
        """Regression: 05-10 used to become 10 May for ongoing bids."""
        parsed = parse_datetime("05-10-2026 9:00 PM")
        assert parsed.month == 10
        assert parsed.day == 5

    def test_ambiguous_two_digit_day_uses_source_convention(self):
        # Both are day-first; GeM renders DD-MM-YYYY and the 24/31 first-
        # component evidence rules out month-first.
        assert parse_datetime("05-10-2026 9:00 PM").day == 5
        assert parse_datetime("08-05-2026 10:00 AM").day == 8

    def test_iso_and_plain_still_parse(self):
        assert parse_datetime("2026-10-05T21:00:00").date().isoformat() == "2026-10-05"
        assert parse_datetime("2026-10-05").date().isoformat() == "2026-10-05"

    def test_unparseable_value_returns_none(self):
        assert parse_datetime("") is None
        assert parse_datetime("not a date") is None


# ---------------------------------------------------------------------------
# 2. Category extraction: GeM's item-group label reaches the matcher
# ---------------------------------------------------------------------------
LISTING_URL = "https://bidplus.gem.gov.in/all-bids"


class TestCategoryExtraction:
    def test_original_title_becomes_category(self):
        records, failures, _rows = GeMPublicAdapter().parse_detailed(
            [{"url": LISTING_URL, "html": bid_card_with_group_label(), "page": 1}],
            source_name="GeM",
        )
        assert not failures
        assert len(records) == 1
        assert records[0].category == "Nutritional Supplement"

    def test_title_and_dates_are_unaffected(self):
        records, _failures, _rows = GeMPublicAdapter().parse_detailed(
            [{"url": LISTING_URL, "html": bid_card_with_group_label(), "page": 1}],
            source_name="GeM",
        )
        record = records[0]
        assert record.title.startswith("Almonds")
        assert record.bid_number == "GEM/2026/B/8060200"
        assert record.published_date == "19-09-2026 9:09 PM"
        assert record.closing_date == "05-10-2026 9:00 PM"

    def test_card_without_group_label_still_parses(self):
        records, failures, _rows = GeMPublicAdapter().parse_detailed(
            [
                {
                    "url": LISTING_URL,
                    "html": bid_card_with_group_label(group_label=None),
                    "page": 1,
                }
            ],
            source_name="GeM",
        )
        assert not failures
        assert records[0].category is None
        assert records[0].title.startswith("Almonds")

    def test_category_does_not_leak_into_the_title(self):
        """The group label is a separate field, not title text."""
        records, _failures, _rows = GeMPublicAdapter().parse_detailed(
            [{"url": LISTING_URL, "html": bid_card_with_group_label(), "page": 1}],
            source_name="GeM",
        )
        assert "Nutritional Supplement" not in (records[0].title or "")


# ---------------------------------------------------------------------------
# 3. Configurable listing scope
# ---------------------------------------------------------------------------
class TestListingScope:
    def test_default_scope_is_ongoing_all_bids_start_date_latest_first(self):
        assert settings.GEM_DIRECT_ENABLED is True
        assert settings.GEM_DIRECT_BID_STATUS_TYPE == "ongoing_bids"
        assert settings.GEM_DIRECT_BID_TYPE == "all"
        # Required production order: Bid Start Date: Latest First, whose exact
        # portal id is "Bid-Start-Date-Latest" (GeM's own sort() argument).
        assert settings.GEM_DIRECT_SORT_ORDER == "Bid-Start-Date-Latest"

    def test_keyword_filter_stays_off(self):
        assert settings.GEM_DIRECT_KEYWORD_FILTER_ENABLED is False

    def test_bid_type_is_one_of_ge_m_own_values(self):
        assert settings.GEM_DIRECT_BID_TYPE in ("all", "product", "service")

    def test_page_budget_is_bounded_and_paced(self):
        # A deliberate bounded slice of the ~4,367-page ongoing listing, never
        # unlimited, so a truncated run cannot look like complete coverage.
        assert settings.GEM_DIRECT_MAX_PAGES == 500
        assert settings.GEM_DIRECT_REQUEST_INTERVAL_SECONDS >= 1.0

    def test_status_reports_the_public_collector_not_an_api(self):
        status = GeMPublicCollector().status()
        assert status["provider"] == "Direct GeM Public Collector"
        assert status["listing_url"].startswith("https://bidplus.gem.gov.in/")
        assert status["requires_credentials"] is False
        assert status["bid_type"] == settings.GEM_DIRECT_BID_TYPE
        # The collector needs no credential, so it never carries a secret value.
        secretish = ("api_key", "apikey", "secret", "token", "password")
        assert not any(any(word in name.lower() for word in secretish) for name in status)
        assert all(value is not True for name, value in status.items() if "credential" in name)