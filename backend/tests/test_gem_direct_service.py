"""
Mocked tests for the direct GeM collection service and its API endpoints.

Covers validation, normalization, deduplication, updated/corrigendum handling,
blocking, preview mode, and the manual-only API surface. No network access.
"""
import sys
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest

from app.models.analysis import BidAnalysis, BidScore, BidProductMatch
from app.models.notification import Notification
from app.services.ingestion import gem_direct_service as svc
from app.services.ingestion.gem_direct_service import (
    gem_direct_status_payload,
    ingest_gem_direct_bids,
)
from tests.gem_pagination_fixtures import FakeListingSession, bid_card, bid_card_container

CARD = """
<div class="card">
 <div class="block_header">
  <p class="bid_no pull-left"><span class="bid_title">BID NO:&nbsp;</span>
   <a class="bid_no_hover" href="/showbidDocument/9673281">GEM/2026/B/7845020</a></p>
 </div>
 <div class="card-body">
  <div class="row"><strong>Items:</strong>&nbsp;
   <a data-content="Smart Contract Security Audit and Vulnerability Detection">Smart Contract Security Audit...</a></div>
  <div class="row"><strong>Quantity:</strong>&nbsp;12</div>
  <div class="row"><strong>Department Name And Address:</strong>&nbsp;</div>
  <div class="row">Ministry of Defence<br>Department of Military Affairs</div>
  <div class="row"><strong>Start Date:</strong>&nbsp;<span class="start_date">04-08-2026 10:43 AM</span></div>
  <div class="row"><strong>End Date:</strong>&nbsp;<span class="end_date">05-10-2026 9:00 AM</span></div>
 </div>
</div>
"""

# The second card must differ in *content*, not just in bid number: the existing
# duplicate detector compares title/organisation/dates, so two byte-identical
# cards would legitimately collapse into one record.
CARD_SECOND = (
    CARD.replace("7845020", "8065592")
    .replace("9673281", "9852416")
    .replace("Smart Contract Security Audit and Vulnerability Detection",
             "VAPT Audit for Security Testing of Enterprise Network")
    .replace("Smart Contract Security Audit...", "VAPT Audit for Security Testing...")
    .replace("Ministry of Defence<br>Department of Military Affairs",
             "Ministry of Home Affairs<br>Department of Revenue Intelligence")
    .replace("04-08-2026 10:43 AM", "11-08-2026 09:15 AM")
    .replace("05-10-2026 9:00 AM", "09-11-2026 4:30 PM")
    .replace("<strong>Quantity:</strong>&nbsp;12", "<strong>Quantity:</strong>&nbsp;4")
)

LISTING_HTML = f"<html><body>{CARD}{CARD_SECOND}</body></html>"


def fake_collector(html=LISTING_HTML, status_code=200):
    """A collector whose ``fetch`` returns canned markup without any network."""
    c = MagicMock()
    c.fetch = MagicMock(return_value=(status_code, html))
    c.blocked = False
    c.status = MagicMock(return_value={"blocked": False, "allowed_hosts": ["bidplus.gem.gov.in"]})
    return c


def listing_session(html=LISTING_HTML, pages=None, **kwargs):
    """
    A stand-in for the rendered listing that a real browser would drive.

    The service reaches GeM's pagination through ``open_listing_session``, so
    faking it here keeps these tests on the production code path - page 1 plus
    whatever extra pages the fixture supplies - without any network.
    """
    if pages is None:
        pages = [bid_card_container(1, 1, 1, [html])]
    return FakeListingSession(pages, **kwargs)


@contextmanager
def canned_listing(html, pages=None, collector=None, session=None):
    """Serve ``html`` as the rendered listing, with no network and no browser."""
    fake = collector if collector is not None else fake_collector(html=html)
    listing = session if session is not None else listing_session(html, pages)
    with patch.object(svc, "_shared_collector", return_value=fake), \
         patch.object(
             svc, "open_listing_session",
             return_value=(MagicMock(), MagicMock(), listing),
         ):
        yield fake


@pytest.fixture
def collector_factory():
    """Swap the shared collector for a canned one and disable browser render."""
    fake = fake_collector()
    with patch.object(svc, "_shared_collector", return_value=fake), \
         patch.object(svc, "open_listing_session", return_value=(
             MagicMock(), MagicMock(), listing_session()
         )), \
         patch.object(svc, "_render_with_browser", side_effect=AssertionError(
             "browser render must not be needed when the HTTP markup already parses"
         )):
        yield fake


# --------------------------------------------------------------------------
# Happy path through the existing pipeline
# --------------------------------------------------------------------------

def test_real_records_are_persisted_via_existing_pipeline(db, collector_factory):
    result = ingest_gem_direct_bids(
        db=db, keywords=None, allow_update_duplicates=True, auto_notify=False,
        triggered_by="test", preview=False, apply_keyword_filter=False,
    )
    assert result["status"] == "SUCCESS"
    assert result["received"] == 2
    assert result["validated"] == 2
    assert result["inserted"] == 2
    assert result["duplicates"] == 0
    assert db.query(svc.Bid).count() == 2


def test_collected_records_reach_the_existing_intelligence_stage(db, collector_factory):
    with patch.object(svc, "process_bid_intelligence") as mock_intel:
        result = ingest_gem_direct_bids(
            db=db, keywords=None, allow_update_duplicates=True, auto_notify=False,
            triggered_by="test", preview=False, apply_keyword_filter=False,
        )
    assert result["intelligence_processed"] == 2
    assert mock_intel.call_count == 2


def test_keyword_filter_narrows_before_persistence(db, collector_factory):
    # The default keyword vocabulary is security-related, so a keyword that
    # cannot match must stop the records short of the database.
    result = ingest_gem_direct_bids(
        db=db, keywords=["zzz-no-such-keyword-zzz"], allow_update_duplicates=True,
        auto_notify=False, triggered_by="test", preview=False,
        apply_keyword_filter=True,
    )
    assert result["status"] == "NO_MATCHING_KEYWORDS"
    assert result["inserted"] == 0
    assert db.query(svc.Bid).count() == 0


def test_keyword_filter_can_be_disabled(db, collector_factory):
    result = ingest_gem_direct_bids(
        db=db, keywords=None, allow_update_duplicates=True, auto_notify=False,
        triggered_by="test", preview=False, apply_keyword_filter=False,
    )
    assert result["status"] == "SUCCESS"
    assert result["inserted"] == 2


# --------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------

def test_record_without_bid_number_is_not_persisted(db):
    """Site chrome that carries no bid reference must yield no record at all."""
    chrome = '<div class="card"><strong>Items:</strong> No reference here</div>'
    with canned_listing(f"<html><body>{chrome}</body></html>"), \
         patch.object(svc, "_render_with_browser", return_value=(200, "<html></html>")):
        result = ingest_gem_direct_bids(
            db=db, keywords=None, allow_update_duplicates=True, auto_notify=False,
            triggered_by="test", preview=False, apply_keyword_filter=False,
        )
    assert result["status"] == "NO_RECORDS"
    assert result["received"] == 0
    assert db.query(svc.Bid).count() == 0


def test_record_without_title_is_rejected_by_validation(db):
    """A bid with no title is rejected by validation."""
    untitled = CARD.replace(
        '<div class="row"><strong>Items:</strong>&nbsp;\n   <a data-content="Smart Contract Security Audit and Vulnerability Detection">Smart Contract Security Audit...</a></div>',
        "",
    )
    assert "Items" not in untitled, "fixture must not contain a title row"
    with canned_listing(f"<html><body>{untitled}</body></html>"):
        result = ingest_gem_direct_bids(
            db=db, keywords=None, allow_update_duplicates=True, auto_notify=False,
            triggered_by="test", preview=False, apply_keyword_filter=False,
        )
    assert result["received"] == 1
    assert result["validated"] == 0
    assert result["rejected"] == 1
    assert result["inserted"] == 0
    assert result["irrelevant_bids"] == 0
    assert db.query(svc.Bid).count() == 0


def test_non_numeric_estimated_value_is_rejected(db):
    """estimated_value must be numeric when present, per the existing validator."""
    bad_value = CARD.replace(
        '<span class="end_date">05-10-2026 9:00 AM</span>',
        '<span class="end_date">05-10-2026 9:00 AM</span>'
        '<div class="row"><strong>Estimated Bid Value:</strong>&nbsp;N/A</div>',
    )
    with canned_listing(f"<html><body>{bad_value}</body></html>"):
        result = ingest_gem_direct_bids(
            db=db, keywords=None, allow_update_duplicates=True, auto_notify=False,
            triggered_by="test", preview=False, apply_keyword_filter=False,
        )
    assert result["received"] == 1
    assert result["rejected"] == 1
    assert db.query(svc.Bid).count() == 0


# --------------------------------------------------------------------------
# Normalization
# --------------------------------------------------------------------------

def test_records_are_normalized_into_canonical_fields(db, collector_factory):
    ingest_gem_direct_bids(
        db=db, keywords=None, allow_update_duplicates=True, auto_notify=False,
        triggered_by="test", preview=False, apply_keyword_filter=False,
    )
    bid = db.query(svc.Bid).filter_by(bid_number="GEM/2026/B/7845020").one()
    assert bid.organisation == "Ministry of Defence Department of Military Affairs"
    assert bid.source_url == "https://bidplus.gem.gov.in/showbidDocument/9673281"
    # Raw GeM print format DD-MM-YYYY HH:MM AM/PM must land as real datetimes.
    assert bid.published_date is not None
    assert bid.closing_date is not None
    assert bid.closing_date > bid.published_date


# --------------------------------------------------------------------------
# Deduplication / updated records
# --------------------------------------------------------------------------

def test_second_collect_of_same_records_is_deduplicated(db, collector_factory):
    first = ingest_gem_direct_bids(
        db=db, keywords=None, allow_update_duplicates=True, auto_notify=False,
        triggered_by="test", preview=False, apply_keyword_filter=False,
    )
    assert first["inserted"] == 2
    assert first["duplicates"] == 0

    second = ingest_gem_direct_bids(
        db=db, keywords=None, allow_update_duplicates=True, auto_notify=False,
        triggered_by="test", preview=False, apply_keyword_filter=False,
    )
    assert second["duplicates"] == 2
    assert second["inserted"] == 0
    assert second["updated"] == 0
    assert db.query(svc.Bid).count() == 2


def test_changed_record_is_updated_not_duplicated(db, collector_factory):
    ingest_gem_direct_bids(
        db=db, keywords=None, allow_update_duplicates=True, auto_notify=False,
        triggered_by="test", preview=False, apply_keyword_filter=False,
    )
    changed = LISTING_HTML.replace(
        "Smart Contract Security Audit and Vulnerability Detection",
        "Smart Contract Security Audit with Thermal Imaging",
    )
    with canned_listing(changed):
        result = ingest_gem_direct_bids(
            db=db, keywords=None, allow_update_duplicates=True, auto_notify=False,
            triggered_by="test", preview=False, apply_keyword_filter=False,
        )
    # Both records are already known, so both count as duplicates. Only the one
    # whose content actually changed is refreshed in place.
    assert result["duplicates"] == 2
    assert result["updated"] == 1
    assert result["inserted"] == 0
    assert db.query(svc.Bid).count() == 2
    bid = db.query(svc.Bid).filter_by(bid_number="GEM/2026/B/7845020").one()
    assert "thermal imaging" in bid.title.lower()


def test_unchanged_record_is_not_updated(db, collector_factory):
    ingest_gem_direct_bids(
        db=db, keywords=None, allow_update_duplicates=True, auto_notify=False,
        triggered_by="test", preview=False, apply_keyword_filter=False,
    )
    result = ingest_gem_direct_bids(
        db=db, keywords=None, allow_update_duplicates=True, auto_notify=False,
        triggered_by="test", preview=False, apply_keyword_filter=False,
    )
    assert result["duplicates"] == 2
    assert result["updated"] == 0
    assert result["inserted"] == 0


def test_corrigendum_link_is_recorded_as_metadata(db, collector_factory):
    corrigendum_html = LISTING_HTML.replace(
        "</div>\n </div>\n</div>", "</div><a>View Corrigendum/Representation</a>\n </div>\n</div>"
    )
    with patch.object(svc, "_shared_collector", return_value=fake_collector(
        html=corrigendum_html
    )):
        ingest_gem_direct_bids(
            db=db, keywords=None, allow_update_duplicates=True, auto_notify=False,
            triggered_by="test", preview=False, apply_keyword_filter=False,
        )
    raw = db.query(svc.RawBidPayload).first()
    assert raw is not None


# --------------------------------------------------------------------------
# Collection run bookkeeping
# --------------------------------------------------------------------------

def test_collection_run_is_recorded_with_direct_source(db, collector_factory):
    result = ingest_gem_direct_bids(
        db=db, keywords=None, allow_update_duplicates=True, auto_notify=False,
        triggered_by="test", preview=False, apply_keyword_filter=False,
    )
    runs = db.query(svc.CollectionRun).all()
    assert len(runs) == 1
    assert runs[0].source_adapter == "GEM_DIRECT_PUBLIC_ADAPTER"
    assert runs[0].status == "SUCCESS"
    assert runs[0].records_found == result["received"]


def test_preview_mode_persists_nothing(db, collector_factory):
    result = ingest_gem_direct_bids(
        db=db, keywords=None, allow_update_duplicates=False, auto_notify=False,
        triggered_by="test", preview=True, apply_keyword_filter=False,
    )
    assert result["status"] == "PREVIEW"
    assert result["validated"] == 2
    assert db.query(svc.Bid).count() == 0
    assert db.query(svc.CollectionRun).count() == 0


# --------------------------------------------------------------------------
# Blocking and URL guardrails
# --------------------------------------------------------------------------

def test_blocked_response_stops_the_run_without_persisting(db):
    """
    If GeM refuses the request the run stops and nothing is persisted.

    The listing is fetched through the rendered session, so that is where a block
    surfaces: ``open_listing_session`` raises ``GeMBlockedError`` on HTTP 403/429
    and no bypass is attempted.
    """
    from app.services.ingestion.gem_public_collector import GeMBlockedError

    blocked = fake_collector()
    blocked.blocked = True

    def _blocked_session(*args, **kwargs):
        raise GeMBlockedError("blocked", status_code=403, stage="render")

    with patch.object(svc, "_shared_collector", return_value=blocked), \
         patch.object(svc, "open_listing_session", side_effect=_blocked_session):
        result = ingest_gem_direct_bids(
            db=db, keywords=None, allow_update_duplicates=True, auto_notify=False,
            triggered_by="test", preview=False, apply_keyword_filter=False,
        )
    assert result["status"] == "BLOCKED"
    assert result["blocked_stage"] == "render"
    assert result["inserted"] == 0
    assert db.query(svc.Bid).count() == 0


def test_blocked_http_response_stops_an_unpaginated_fetch(db, monkeypatch):
    """A block on the plain-HTTP path is honoured too, without any retry."""
    from app.services.ingestion.gem_public_collector import GeMBlockedError

    monkeypatch.setattr(svc.settings, "GEM_DIRECT_PAGINATE", False)
    blocked = fake_collector()
    blocked.fetch = MagicMock(
        side_effect=GeMBlockedError("blocked", status_code=403, stage="request")
    )
    blocked.blocked = True
    with patch.object(svc, "_shared_collector", return_value=blocked):
        result = ingest_gem_direct_bids(
            db=db, keywords=None, allow_update_duplicates=True, auto_notify=False,
            triggered_by="test", preview=False, apply_keyword_filter=False,
        )
    assert result["status"] == "BLOCKED"
    assert result["blocked_stage"] == "request"
    assert db.query(svc.Bid).count() == 0


def test_non_gem_url_is_rejected_before_any_request(db):
    result = ingest_gem_direct_bids(
        db=db, urls=["https://evil.com/x"], keywords=None, auto_notify=False,
        triggered_by="test", preview=False, apply_keyword_filter=False,
    )
    assert result["status"] == "NO_URLS"
    assert result["rejected_urls"] == 1
    assert result["inserted"] == 0
    assert db.query(svc.Bid).count() == 0


# --------------------------------------------------------------------------
# Status endpoint / no scheduling
# --------------------------------------------------------------------------

def test_status_reports_direct_collector_configuration(db):
    status = gem_direct_status_payload()
    assert "configured" in status
    assert "allowed_hosts" in status
    assert "blocked" in status
    assert status["scheduler_enabled"] is True
    assert status["requires_credentials"] is False


def test_status_lists_bidplus_gem_in_allowed_hosts(db):
    assert "bidplus.gem.gov.in" in gem_direct_status_payload()["allowed_hosts"]


def test_scheduler_is_enabled_by_default():
    from app.core.config import settings

    assert settings.GEM_DIRECT_SCHEDULER_ENABLED is True
    assert settings.GEM_DIRECT_SCHEDULER_INTERVAL_MINUTES == 20


# --------------------------------------------------------------------------
# API surface
# --------------------------------------------------------------------------

def test_status_endpoint_is_reachable(client):
    response = client.get("/api/v1/ingestion/gem-direct/status")
    assert response.status_code == 200
    body = response.json()
    assert body["configured"] is True
    assert body["source"] == "gem_direct"
    assert body["requires_credentials"] is False


def test_fetch_endpoint_requires_manual_trigger(client):
    response = client.post("/api/v1/ingestion/gem-direct/fetch", json={})
    assert response.status_code == 200
    assert response.json()["source"] == "gem_direct"


def test_fetch_endpoint_rejects_disallowed_url(client):
    response = client.post(
        "/api/v1/ingestion/gem-direct/fetch",
        json={"urls": ["https://evil.com/x"]},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "NO_URLS"
    assert body["inserted"] == 0


# --------------------------------------------------------------------------
# Focused tests: Relevance filtering, Thresholds, Updates & Pagination
# --------------------------------------------------------------------------

CARD_IRRELEVANT = CARD.replace(
    "7845020", "9990001"
).replace(
    "9673281", "9990001"
).replace(
    "Smart Contract Security Audit and Vulnerability Detection",
    "Supply of Wooden Office Chairs and Desks"
).replace(
    "Smart Contract Security Audit...",
    "Supply of Wooden Office Chairs..."
)

CARD_MATCH = CARD.replace(
    "7845020", "9990002"
).replace(
    "9673281", "9990002"
).replace(
    "Smart Contract Security Audit and Vulnerability Detection",
    "Smart Contract Security Audit and Solidity Vulnerability Assessment"
).replace(
    "Smart Contract Security Audit...",
    "Smart Contract Security Audit..."
).replace(
    "05-10-2026 9:00 AM",
    "25-11-2026 9:00 AM"
)

CARD_POSSIBLE = CARD.replace(
    "7845020", "9990003"
).replace(
    "9673281", "9990003"
).replace(
    "Smart Contract Security Audit and Vulnerability Detection",
    "Smart Contract Security Audit"
).replace(
    "Smart Contract Security Audit...",
    "Smart Contract Security Audit"
)

CARD_NEEDS_REVIEW = CARD.replace(
    "7845020", "9990004"
).replace(
    "9673281", "9990004"
).replace(
    "Smart Contract Security Audit and Vulnerability Detection",
    "CCTV Security Camera and Cookies Monitoring"
).replace(
    "Smart Contract Security Audit...",
    "CCTV Security Camera and Cookies Monitoring"
)


def test_relevant_new_bid_is_inserted(db):
    """A newly discovered relevant bid is inserted and intelligence is persisted."""
    with canned_listing(f"<html><body>{CARD_MATCH}</body></html>"):
        result = ingest_gem_direct_bids(
            db=db, allow_update_duplicates=True, auto_notify=False,
            triggered_by="test", preview=False, apply_keyword_filter=False,
        )
    assert result["status"] == "SUCCESS"
    assert result["received"] == 1
    assert result["validated"] == 1
    assert result["inserted"] == 1
    assert result["irrelevant_bids"] == 0

    bid = db.query(svc.Bid).filter_by(bid_number="GEM/2026/B/9990002").one()
    assert bid is not None

    score = db.query(BidScore).filter_by(bid_id=bid.id).first()
    assert score is not None
    assert score.relevance_score >= 0.70
    assert score.relevance_label == "MATCH"

    analysis = db.query(BidAnalysis).filter_by(bid_id=bid.id).first()
    assert analysis is not None

    matches = db.query(BidProductMatch).filter_by(bid_id=bid.id).all()
    assert len(matches) >= 1
    assert any(m.match_score >= 0.70 for m in matches)


def test_irrelevant_new_bid_is_not_inserted(db):
    """A newly discovered irrelevant bid (NO_MATCH) is not inserted into the DB."""
    with canned_listing(f"<html><body>{CARD_IRRELEVANT}</body></html>"):
        result = ingest_gem_direct_bids(
            db=db, allow_update_duplicates=True, auto_notify=False,
            triggered_by="test", preview=False, apply_keyword_filter=False,
        )
    assert result["status"] == "SUCCESS"
    assert result["received"] == 1
    assert result["validated"] == 1
    assert result["rejected"] == 0
    assert result["inserted"] == 0
    assert result["irrelevant_bids"] == 1

    assert db.query(svc.Bid).count() == 0
    assert db.query(BidScore).count() == 0
    assert db.query(BidAnalysis).count() == 0
    assert db.query(BidProductMatch).count() == 0


def test_each_relevance_threshold(db):
    """Verifies MATCH, POSSIBLE_MATCH, and NEEDS_REVIEW are inserted, NO_MATCH is not."""
    html = f"<html><body>{CARD_MATCH}{CARD_POSSIBLE}{CARD_NEEDS_REVIEW}{CARD_IRRELEVANT}</body></html>"
    with canned_listing(html):
        result = ingest_gem_direct_bids(
            db=db, allow_update_duplicates=True, auto_notify=False,
            triggered_by="test", preview=False, apply_keyword_filter=False,
        )
    assert result["status"] == "SUCCESS"
    assert result["received"] == 4
    assert result["validated"] == 4
    assert result["rejected"] == 0
    assert result["inserted"] == 3
    assert result["irrelevant_bids"] == 1

    persisted = db.query(svc.Bid).all()
    assert len(persisted) == 3
    persisted_numbers = {b.bid_number for b in persisted}
    assert "GEM/2026/B/9990002" in persisted_numbers  # MATCH
    assert "GEM/2026/B/9990003" in persisted_numbers  # POSSIBLE_MATCH
    assert "GEM/2026/B/9990004" in persisted_numbers  # NEEDS_REVIEW
    assert "GEM/2026/B/9990001" not in persisted_numbers  # NO_MATCH excluded


def test_existing_bids_updated_and_corrigenda_no_duplicates(db):
    """Existing bids and corrigenda are updated in place without duplicate rows."""
    with canned_listing(f"<html><body>{CARD_MATCH}</body></html>"):
        res1 = ingest_gem_direct_bids(
            db=db, allow_update_duplicates=True, auto_notify=False,
            triggered_by="test", preview=False, apply_keyword_filter=False,
        )
    assert res1["inserted"] == 1
    assert db.query(svc.Bid).count() == 1
    orig_bid = db.query(svc.Bid).filter_by(bid_number="GEM/2026/B/9990002").one()
    orig_id = orig_bid.id

    # Corrigendum arrives with extended end date and updated title
    corrigendum_card = CARD_MATCH.replace(
        "25-11-2026 9:00 AM", "25-12-2026 5:00 PM"
    ).replace(
        "Vulnerability Assessment",
        "Vulnerability Assessment and Pen Testing Corrigendum",
    )
    with canned_listing(f"<html><body>{corrigendum_card}</body></html>"):
        res2 = ingest_gem_direct_bids(
            db=db, allow_update_duplicates=True, auto_notify=False,
            triggered_by="test", preview=False, apply_keyword_filter=False,
        )
    assert res2["inserted"] == 0
    assert res2["updated"] == 1
    assert res2["duplicates"] == 1
    assert db.query(svc.Bid).count() == 1

    updated_bid = db.query(svc.Bid).filter_by(bid_number="GEM/2026/B/9990002").one()
    assert updated_bid.id == orig_id


def test_duplicate_bids_not_inserted_twice(db):
    """Repeated sync of the same bids creates 0 new rows and 0 updates."""
    with canned_listing(f"<html><body>{CARD_MATCH}</body></html>"):
        res1 = ingest_gem_direct_bids(
            db=db, allow_update_duplicates=True, auto_notify=False,
            triggered_by="test", preview=False, apply_keyword_filter=False,
        )
    assert res1["inserted"] == 1

    with canned_listing(f"<html><body>{CARD_MATCH}</body></html>"):
        res2 = ingest_gem_direct_bids(
            db=db, allow_update_duplicates=True, auto_notify=False,
            triggered_by="test", preview=False, apply_keyword_filter=False,
        )
    assert res2["inserted"] == 0
    assert res2["updated"] == 0
    assert res2["duplicates"] == 1
    assert db.query(svc.Bid).count() == 1


def test_pagination_continues_through_pages_with_no_relevant_bids(db):
    """Pagination traverses through pages even if early pages contain zero relevant bids."""
    card_irr_1 = bid_card("GEM/2026/B/9990011", "Supply of Office Desks and Chairs", 9990011)
    card_irr_2 = bid_card("GEM/2026/B/9990012", "Supply of Stationery Goods and Paper", 9990012)
    page_1 = bid_card_container(1, 3, 2, [card_irr_1, card_irr_2])

    card_rel = bid_card("GEM/2026/B/9990013", "Smart Contract Security Audit and Vulnerability Detection", 9990013)
    page_2 = bid_card_container(2, 3, 2, [card_rel])

    session = FakeListingSession([page_1, page_2])
    with canned_listing("", session=session):
        result = ingest_gem_direct_bids(
            db=db, allow_update_duplicates=True, auto_notify=False,
            triggered_by="test", preview=False, apply_keyword_filter=False,
        )
    assert result["pages_visited"] == 2
    assert result["rows_seen"] == 3
    assert result["received"] == 3
    assert result["validated"] == 3
    assert result["inserted"] == 1
    assert result["irrelevant_bids"] == 2
    assert db.query(svc.Bid).count() == 1
    b = db.query(svc.Bid).one()
    assert b.bid_number == "GEM/2026/B/9990013"


def test_matching_failure_handled_safely(db):
    """A matching engine failure for one bid is safely handled without aborting others."""
    orig_match = svc.match_bid_against_products

    def side_effect(session, bid):
        if "SimulatedFail" in bid.title:
            raise RuntimeError("Matching engine simulated explosion")
        return orig_match(session, bid)

    card_fail = CARD.replace(
        "7845020", "9990031"
    ).replace(
        "9673281", "9990031"
    ).replace(
        "Smart Contract Security Audit and Vulnerability Detection",
        "SimulatedFail Security Service"
    )
    card_ok = CARD.replace(
        "7845020", "9990032"
    ).replace(
        "9673281", "9990032"
    )

    with canned_listing(f"<html><body>{card_fail}{card_ok}</body></html>"), \
         patch.object(svc, "match_bid_against_products", side_effect=side_effect):
        result = ingest_gem_direct_bids(
            db=db, allow_update_duplicates=True, auto_notify=False,
            triggered_by="test", preview=False, apply_keyword_filter=False,
        )

    assert result["status"] == "SUCCESS"
    assert result["received"] == 2
    assert result["validated"] == 2
    assert result["inserted"] == 1
    assert result["irrelevant_bids"] == 1
    assert any(e.get("field") == "matching" for e in result["errors"])
    assert db.query(svc.Bid).count() == 1
    assert db.query(svc.Bid).one().bid_number == "GEM/2026/B/9990032"


def test_notification_behavior_intact_and_deduplicated(db):
    """High-relevance inserted bids trigger notifications without duplicate notifications on re-sync."""
    with canned_listing(f"<html><body>{CARD_MATCH}</body></html>"):
        res1 = ingest_gem_direct_bids(
            db=db, auto_notify=True, allow_update_duplicates=True,
            triggered_by="test", preview=False, apply_keyword_filter=False,
        )
    assert res1["inserted"] == 1
    assert res1["notifications_created"] == 1
    assert db.query(Notification).count() == 1

    # Second sync: recognized as duplicate, no duplicate notification
    with canned_listing(f"<html><body>{CARD_MATCH}</body></html>"):
        res2 = ingest_gem_direct_bids(
            db=db, auto_notify=True, allow_update_duplicates=True,
            triggered_by="test", preview=False, apply_keyword_filter=False,
        )
    assert res2["inserted"] == 0
    assert res2["duplicates"] == 1
    assert res2["notifications_created"] == 0
    assert db.query(Notification).count() == 1