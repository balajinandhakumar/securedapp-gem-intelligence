"""Focused tests for automatic, bounded BoQ enrichment during GeM collection.

Verifies the integration guarantees (see ``gem_boq_auto``):
  1. OFF by default: no network, nothing attempted.
  2. When enabled, an eligible freshly collected bid is enriched and the
     attempt is recorded on ``Bid.boq_checked_at``.
  3. A bid that already carries BoQ evidence is skipped (idempotent).
  4. A bid that was already attempted is skipped, so no bid is ever re-fetched
     across repeated collection runs.
  5. Non bid-document URLs are skipped.
  6. The per-run budget is a hard cap.
  7. A fetch failure is recorded, does not raise, and still marks the attempt.
  8. The direct-collection pipeline invokes enrichment before matching and
     reports the counters.

All bids live only in the isolated in-memory test DB; no network is used.
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from app.core.config import settings
from app.models.bid import Bid
from app.services.ingestion import gem_direct_service as svc
from app.services.ingestion.gem_boq_auto import (
    enrich_collected_bids,
    is_gem_bid_document_url,
)
from app.services.ingestion.gem_boq_evidence import BoQEvidenceError
from tests.test_gem_direct_service import LISTING_HTML, canned_listing

BID_URL = "https://bidplus.gem.gov.in/showbidDocument/9981740"
CSV_URL = (
    "https://mkp.gem.gov.in/uploaded_documents/51/16/877/OrderItem/"
    "BoqLineItemsDocument/2026/10/3/boq_item_sample_file.csv"
)
CSV_TEXT = (
    "Item Number,Item Title,Item Description,Item Quantity,Unit of Measure,"
    "Consignee ID,Delivery Period (In number of days)\n"
    "1,Cryptocurrency Transaction Tracing Software,"
    "Cryptocurrency Transaction Tracing Software,1,pieces,medara.rajarao,10\n"
)


class _FakeResponse:
    def __init__(self, content: bytes, status_code: int = 200):
        self.content = content
        self.status_code = status_code
        self.text = content.decode("utf-8", errors="ignore")


class _FakeSession:
    """Records every URL it is asked for; fails the test on an unexpected one."""

    def __init__(self, mapping):
        self.mapping = mapping
        self.calls = []

    def get(self, url, timeout=None, allow_redirects=True):
        self.calls.append(url)
        if url not in self.mapping:
            raise AssertionError(f"unexpected fetch: {url}")
        return self.mapping[url]


def _pdf_bytes(*urls: str) -> bytes:
    return ("%PDF-1.4\n" + "\n".join(urls) + "\n%%EOF").encode("latin-1")


def _session_with_csv() -> _FakeSession:
    return _FakeSession(
        {
            BID_URL: _FakeResponse(_pdf_bytes(CSV_URL)),
            CSV_URL: _FakeResponse(CSV_TEXT.encode("utf-8")),
        }
    )


@pytest.fixture
def auto_enabled(monkeypatch):
    monkeypatch.setattr(settings, "GEM_BOQ_AUTO_ENRICH_ENABLED", True)


def _bid(db, **kwargs) -> Bid:
    bid = Bid(title=kwargs.pop("title", "Some tender"), **kwargs)
    db.add(bid)
    db.commit()
    return bid


# ---------------------------------------------------------------------------
# URL eligibility
# ---------------------------------------------------------------------------
class TestEligibility:
    def test_gem_bid_document_is_eligible(self):
        assert is_gem_bid_document_url(BID_URL) is True

    @pytest.mark.parametrize(
        "url",
        [
            None,
            "",
            "https://bidplus.gem.gov.in/all-bids",
            "https://example.com/showbidDocument/1",
            "https://mkp.gem.gov.in/foo.csv",
        ],
    )
    def test_other_urls_are_not_eligible(self, url):
        assert is_gem_bid_document_url(url) is False


# ---------------------------------------------------------------------------
# Core behaviour
# ---------------------------------------------------------------------------
class TestEnrichCollectedBids:
    def test_disabled_makes_no_fetch(self, db):
        bid = _bid(db, source_url=BID_URL)
        # A session that would raise on ANY call proves nothing is fetched.
        # conftest forces GEM_BOQ_AUTO_ENRICH_ENABLED off for every test.
        summary = enrich_collected_bids([bid], session=_FakeSession({}))
        assert summary["attempted"] == 0
        assert bid.boq_items is None
        assert bid.boq_checked_at is None

    def test_enabled_enriches_and_records_attempt(self, db, auto_enabled):
        bid = _bid(db, source_url=BID_URL)
        session = _session_with_csv()
        when = datetime(2026, 10, 13, 22, 0, tzinfo=timezone.utc)

        summary = enrich_collected_bids([bid], session=session, now=when)

        assert summary == {
            "eligible": 1,
            "attempted": 1,
            "enriched": 1,
            "skipped": 0,
            "failed": 0,
        }
        assert bid.boq_items["item_count"] == 1
        assert bid.boq_items["source_url"] == CSV_URL
        assert bid.boq_checked_at == when
        assert session.calls == [BID_URL, CSV_URL]

    def test_already_enriched_bid_is_skipped(self, db, auto_enabled):
        bid = _bid(db, source_url=BID_URL, boq_items={"items": [{"title": "x"}], "item_count": 1})
        session = _FakeSession({})
        summary = enrich_collected_bids([bid], session=session)
        assert summary["skipped"] == 1
        assert summary["attempted"] == 0
        assert session.calls == []

    def test_already_attempted_bid_is_not_refetched(self, db, auto_enabled):
        bid = _bid(
            db,
            source_url=BID_URL,
            boq_checked_at=datetime(2026, 10, 12, tzinfo=timezone.utc),
        )
        session = _FakeSession({})
        summary = enrich_collected_bids([bid], session=session)
        assert summary["skipped"] == 1
        assert summary["attempted"] == 0
        assert session.calls == []

    def test_non_bid_document_url_is_skipped(self, db, auto_enabled):
        bid = _bid(db, source_url="https://bidplus.gem.gov.in/all-bids")
        session = _FakeSession({})
        summary = enrich_collected_bids([bid], session=session)
        assert summary["skipped"] == 1
        assert summary["attempted"] == 0
        assert session.calls == []

    def test_budget_is_a_hard_cap(self, db, auto_enabled):
        bids = [_bid(db, source_url=BID_URL) for _ in range(3)]
        session = _session_with_csv()
        summary = enrich_collected_bids(bids, session=session, max_per_run=2)
        assert summary["eligible"] == 3
        assert summary["attempted"] == 2
        # The third bid is untouched and stays eligible for a later run.
        assert bids[2].boq_checked_at is None
        assert bids[2].boq_items is None

    def test_fetch_failure_is_recorded_and_marks_attempt(self, db, auto_enabled):
        bid = _bid(db, source_url=BID_URL)

        class _FailingSession:
            def get(self, *a, **k):
                raise BoQEvidenceError("no BoQ CSV linked")

        summary = enrich_collected_bids([bid], session=_FailingSession())
        assert summary["failed"] == 1
        assert summary["attempted"] == 1
        assert bid.boq_items is None
        # Attempt is still recorded: never re-fetch a bid with no published BoQ.
        assert bid.boq_checked_at is not None

    def test_unexpected_error_never_raises(self, db, auto_enabled):
        bid = _bid(db, source_url=BID_URL)

        class _ExplodingSession:
            def get(self, *a, **k):
                raise RuntimeError("connection reset")

        summary = enrich_collected_bids([bid], session=_ExplodingSession())
        assert summary["failed"] == 1
        assert bid.boq_checked_at is not None


# ---------------------------------------------------------------------------
# Pipeline integration
# ---------------------------------------------------------------------------
class TestPipelineIntegration:
    def test_collection_runs_enrichment_before_matching(self, db):
        captured = {}

        def spy(bids):
            captured["count"] = len(bids)
            return {"eligible": len(bids), "attempted": 0, "enriched": 0, "skipped": 0, "failed": 0}

        with patch.object(svc, "enrich_collected_bids", side_effect=spy), \
                patch.object(svc, "process_bid_intelligence") as mock_intel, \
                canned_listing(LISTING_HTML):
            result = svc.ingest_gem_direct_bids(
                db=db,
                keywords=None,
                allow_update_duplicates=True,
                auto_notify=False,
                triggered_by="test",
                preview=False,
                apply_keyword_filter=False,
            )

        assert result["inserted"] == 2
        # Enrichment is invoked with the freshly persisted bids, before matching.
        assert captured["count"] == 2
        assert mock_intel.call_count == 2
        assert result["boq_enrichment"] == {
            "eligible": 2,
            "attempted": 0,
            "enriched": 0,
            "skipped": 0,
            "failed": 0,
        }
