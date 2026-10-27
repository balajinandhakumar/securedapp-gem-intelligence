"""Regression tests for fuzzy-title deduplication policy.

Title similarity alone must never suppress a record: two distinct GeM tenders
can share an item title ("Chair for General Purpose"). Exact bid-number /
gem_bid_id / content-hash duplicates keep collapsing as before, and a fuzzy hit
is only treated as the same tender when corroborating evidence (same source URL,
or same organisation *and* closing date) supports it.
"""
from __future__ import annotations

from datetime import datetime

from app.models.bid import Bid
from app.services.ingestion.duplicate_detector import check_duplicate


TITLE = "Chair for General Purpose"


def _existing(db, **kwargs):
    defaults = dict(
        title=TITLE,
        bid_number="GEM/2026/B/8003747",
        gem_bid_id="GEM/2026/B/8003747",
        organisation="Ministry of Railways Indian Railways",
        closing_date=datetime(2026, 10, 7, 11, 0),
        source_url="https://bidplus.gem.gov.in/showbidDetails?bid=8003747",
    )
    defaults.update(kwargs)
    bid = Bid(**defaults)
    db.add(bid)
    db.commit()
    return bid


class TestDistinctSameTitleBids:
    def test_different_bid_number_is_not_suppressed(self, db):
        _existing(db)
        res = check_duplicate(
            db,
            {
                "title": TITLE,
                "bid_number": "GEM/2026/B/8028774",
                "gem_bid_id": "GEM/2026/B/8028774",
                "organisation": "Ministry of Railways Indian Railways",
                "closing_date": datetime(2026, 10, 7, 11, 0),
            },
        )
        assert res.status == "NEW"
        assert not res.is_duplicate
        assert res.fuzzy_candidates >= 1
        assert res.fuzzy_rejected >= 1

    def test_different_bid_number_wins_over_identical_metadata(self, db):
        """Even identical org + closing date, distinct GeM ids stay distinct."""
        _existing(db)
        res = check_duplicate(
            db,
            {
                "title": TITLE,
                "bid_number": "GEM/2026/B/8028775",
                "gem_bid_id": "GEM/2026/B/8028775",
                "organisation": "Ministry of Railways Indian Railways",
                "closing_date": datetime(2026, 10, 7, 11, 0),
            },
        )
        assert not res.is_duplicate

    def test_organisational_difference_is_not_suppressed(self, db):
        _existing(db, bid_number="GEM/2026/B/8003747", gem_bid_id="GEM/2026/B/8003747")
        res = check_duplicate(
            db,
            {
                "title": TITLE,
                "organisation": "Ministry of Home Affairs",
                "closing_date": datetime(2026, 11, 1, 11, 0),
            },
        )
        assert not res.is_duplicate


class TestSameTenderStillDeduplicated:
    def test_repeated_identical_bid_number_is_an_exact_duplicate(self, db):
        _existing(db)
        res = check_duplicate(
            db,
            {"title": TITLE, "bid_number": "GEM/2026/B/8003747", "gem_bid_id": "GEM/2026/B/8003747"},
        )
        assert res.status == "EXACT_MATCH"
        assert res.is_duplicate
        assert res.existing_bid is not None

    def test_identical_content_hash_is_an_exact_duplicate(self, db):
        _existing(db, bid_number="GEM/2026/B/1111", gem_bid_id="GEM/2026/B/1111",
                  content_hash="hash-abc")
        res = check_duplicate(db, {"title": "Anything else entirely", "hash": "hash-abc"})
        assert res.status == "EXACT_MATCH"

    def test_same_source_url_backs_a_fuzzy_hit(self, db):
        _existing(db, bid_number=None, gem_bid_id=None)
        res = check_duplicate(
            db,
            {
                "title": TITLE,
                "source_url": "https://bidplus.gem.gov.in/showbidDetails?bid=8003747",
            },
        )
        assert res.status == "FUZZY_MATCH"
        assert res.is_duplicate

    def test_same_organisation_and_closing_date_backs_a_fuzzy_hit(self, db):
        _existing(db, bid_number=None, gem_bid_id=None)
        res = check_duplicate(
            db,
            {
                "title": TITLE,
                "organisation": "Ministry of Railways  Indian Railways",
                "closing_date": datetime(2026, 10, 7, 11, 0),
            },
        )
        assert res.status == "FUZZY_MATCH"


def test_short_titles_skip_the_fuzzy_path(db):
    _existing(db)
    res = check_duplicate(db, {"title": "Chair", "bid_number": "GEM/2026/B/9999"})
    assert res.status == "NEW"
    assert res.fuzzy_candidates == 0
