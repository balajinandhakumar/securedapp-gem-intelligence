"""Focused tests for authoritative BoQ line-item evidence.

Covers the three things the fix must guarantee:
  1. the BoQ CSV linked from a bid document is parsed correctly;
  2. the parsed line items are stored separately from title/scope together with
     the source URL and retrieval time, idempotently;
  3. the matching engine uses the stored evidence -- a truncated bid that scores
     zero without BoQ evidence surfaces the product once the BoQ is attached,
     while bids without BoQ evidence are unchanged.

All bids/products live only in the isolated in-memory test DB.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.db.seed_knowledge import seed_product_knowledge
from app.models.bid import Bid
from app.services.boq_text import boq_evidence_text
from app.services.ingestion.gem_boq_evidence import (
    BoQEvidenceError,
    apply_boq_evidence,
    build_boq_evidence,
    enrich_bid_from_source,
    extract_boq_document_links,
    fetch_boq_evidence,
    parse_boq_csv,
)
from app.services.intelligence import match_bid_against_products

BID_URL = "https://bidplus.gem.gov.in/showbidDocument/9981740"
CSV_URL = (
    "https://mkp.gem.gov.in/uploaded_documents/51/16/877/OrderItem/"
    "BoqLineItemsDocument/2026/10/3/boq_item_sample_file_2026-10-03.csv"
)
SPEC_URL = (
    "https://mkp.gem.gov.in/uploaded_documents/51/16/877/OrderItem/"
    "BoqDocument/2026/10/3/spec_soft_2_2026-10-03.pdf"
)

# The real GEM/2026/B/8114104 BoQ CSV (verbatim).
CSV_TEXT = (
    "Item Number,Item Title,Item Description,Item Quantity,Unit of Measure,"
    "Consignee ID,Delivery Period (In number of days)\n"
    "1,Telegram Group Monitoring Intelligence  De anonymization software,"
    "Telegram Group Monitoring Intelligence  De anonymization software,1,pieces,"
    "medara.rajarao,10\n"
    "2,Mobile Digital Evidence Analysis Software,"
    "Mobile Digital Evidence Analysis Software,1,pieces,medara.rajarao,10\n"
    "3,Financial Fraud Analysis tool,Financial Fraud Analysis tool,1,pieces,"
    "medara.rajarao,10\n"
    "4,AIBased Deepfake Detection Software,AIBased Deepfake Detection Software,"
    "1,pieces,medara.rajarao,10\n"
    "5,Cryptocurrency Transaction Tracing  Blockchain Intelligence Analysis "
    "Software,Cryptocurrency Transaction Tracing & Blockchain Intelligence "
    "Analysis Software,1,pieces,medara.rajarao,10\n"
)


class _FakeResponse:
    def __init__(self, content: bytes, status_code: int = 200):
        self.content = content
        self.status_code = status_code
        self.text = content.decode("utf-8", errors="ignore")


class _FakeSession:
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


def _fake_session() -> _FakeSession:
    return _FakeSession(
        {
            BID_URL: _FakeResponse(_pdf_bytes(SPEC_URL, CSV_URL)),
            CSV_URL: _FakeResponse(CSV_TEXT.encode("utf-8")),
        }
    )


@pytest.fixture(autouse=True)
def seed_knowledge(db):
    seed_product_knowledge(db)


# ---------------------------------------------------------------------------
# 1. CSV parsing + link extraction
# ---------------------------------------------------------------------------
class TestParseAndExtract:
    def test_extract_finds_csv_and_spec_in_pdf_bytes(self):
        links = extract_boq_document_links(_pdf_bytes(SPEC_URL, CSV_URL))
        assert links["csv_url"] == CSV_URL
        assert links["spec_url"] == SPEC_URL

    def test_extract_returns_none_when_no_boq(self):
        assert extract_boq_document_links(_pdf_bytes("https://bidplus.gem.gov.in/x")) == {
            "csv_url": None,
            "spec_url": None,
        }

    def test_parse_real_csv(self):
        items = parse_boq_csv(CSV_TEXT)
        assert len(items) == 5
        assert items[0]["item_number"] == "1"
        assert items[0]["unit"] == "pieces"
        assert items[4]["title"] == (
            "Cryptocurrency Transaction Tracing  Blockchain Intelligence "
            "Analysis Software"
        )
        assert items[4]["description"] == (
            "Cryptocurrency Transaction Tracing & Blockchain Intelligence "
            "Analysis Software"
        )

    def test_parse_handles_bom_and_blank_rows(self):
        text = "\ufeffItem Number,Item Title\r\n1,Some Item\r\n,,\r\n2,Another\r\n"
        items = parse_boq_csv(text)
        assert [i["title"] for i in items] == ["Some Item", "Another"]

    def test_parse_respects_max_items(self):
        assert len(parse_boq_csv(CSV_TEXT, max_items=2)) == 2

    def test_parse_empty(self):
        assert parse_boq_csv("") == []


# ---------------------------------------------------------------------------
# 2. Fetching + storage (idempotent, separate from title/scope)
# ---------------------------------------------------------------------------
class TestFetchAndStore:
    def test_fetch_builds_evidence_with_provenance(self):
        when = datetime(2026, 10, 13, 12, 0, tzinfo=timezone.utc)
        evidence = fetch_boq_evidence(BID_URL, session=_fake_session(), retrieved_at=when)
        assert evidence["item_count"] == 5
        assert evidence["source_url"] == CSV_URL
        assert evidence["retrieved_at"] == when.isoformat()
        assert evidence["items"][4]["item_number"] == "5"

    def test_fetch_raises_when_no_csv_linked(self):
        session = _FakeSession({BID_URL: _FakeResponse(_pdf_bytes(SPEC_URL))})
        with pytest.raises(BoQEvidenceError):
            fetch_boq_evidence(BID_URL, session=session)

    def test_fetch_raises_for_non_allowlisted_host(self):
        with pytest.raises(Exception):
            fetch_boq_evidence("https://evil.example.com/doc.pdf")

    def test_boq_evidence_text_contains_scope_terms(self):
        text = boq_evidence_text(build_boq_evidence(parse_boq_csv(CSV_TEXT), CSV_URL))
        assert "cryptocurrency" in text
        assert "blockchain" in text
        assert "deepfake" in text

    def test_apply_is_idempotent(self, db):
        bid = Bid(title="t", source_url=BID_URL)
        db.add(bid)
        db.commit()
        evidence = build_boq_evidence(parse_boq_csv(CSV_TEXT), CSV_URL)
        assert apply_boq_evidence(bid, evidence) is True
        assert apply_boq_evidence(bid, evidence) is False

    def test_enrich_stores_separately_and_preserves_title_scope(self, db):
        title = "Telegram Group Monitoring Intelligence De anonymization software,..."
        bid = Bid(title=title, scope_of_work=title, source_url=BID_URL)
        db.add(bid)
        db.commit()

        result = enrich_bid_from_source(bid, session=_fake_session())
        db.commit()
        db.refresh(bid)

        assert result["changed"] is True
        assert result["item_count"] == 5
        assert bid.boq_items["source_url"] == CSV_URL
        assert bid.boq_items["retrieved_at"]
        # untouched
        assert bid.title == title
        assert bid.scope_of_work == title

    def test_reenrich_does_not_duplicate(self, db):
        bid = Bid(title="t", source_url=BID_URL)
        db.add(bid)
        db.commit()
        enrich_bid_from_source(bid, session=_fake_session())
        second = enrich_bid_from_source(bid, session=_fake_session())
        assert second["changed"] is False
        assert db.query(Bid).count() == 1


# ---------------------------------------------------------------------------
# 3. Matching engine integration
# ---------------------------------------------------------------------------
def _truncated_subject_bid(db) -> Bid:
    title = ",".join(
        [
            "Telegram Group Monitoring Intelligence  De anonymization software",
            "Mobile Digital Evidence Analysis Software",
            "Financial Fraud Analysis tool",
            "AIBased Deepfake Detection Software",
            "Cryptocurrency Transaction Tracing  Blockchain Intelligence Analysis Software",
        ]
    )[:99]
    bid = Bid(
        title=title,
        scope_of_work=title,
        category="Forensic software",
        source_url=BID_URL,
    )
    db.add(bid)
    db.commit()
    return bid


def _securetrace(results):
    return next(r for r in results if r.product_name == "SecureTrace")


class TestMatchingIntegration:
    def test_without_boq_the_truncated_bid_is_no_match(self, db):
        bid = _truncated_subject_bid(db)
        trace = _securetrace(match_bid_against_products(db, bid))
        assert trace.relevance_score == 0.0
        assert trace.match_state == "NO_MATCH"

    def test_with_boq_the_bid_surfaces_possible_match(self, db):
        bid = _truncated_subject_bid(db)
        enrich_bid_from_source(bid, session=_fake_session())
        db.commit()
        db.refresh(bid)

        trace = _securetrace(match_bid_against_products(db, bid))
        assert trace.relevance_score >= 0.45
        assert trace.match_state == "POSSIBLE_MATCH"
        assert any("Transaction tracing" == s["text"] for s in trace.signals)

    def test_boq_evidence_does_not_create_a_high_relevance_match(self, db):
        # BoQ evidence informs the scope channel; it must not manufacture a
        # ≥0.70 MATCH (which would auto-notify) from a single bundled item.
        bid = _truncated_subject_bid(db)
        enrich_bid_from_source(bid, session=_fake_session())
        db.commit()
        db.refresh(bid)
        assert _securetrace(match_bid_against_products(db, bid)).relevance_score < 0.70
