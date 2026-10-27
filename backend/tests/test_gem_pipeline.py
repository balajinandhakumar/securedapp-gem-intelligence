"""
Stage-1: GeM Ingestion Pipeline Tests
======================================

Tests the GeM data source ingestion path end-to-end using structured mock/dev data
(the only path available without authorized GeM API credentials).

Architecture verified here:
    GeM Structured Data (mock/JSON) → ApprovedGeMAdapter → RawBidRecord
    → Validation → Normalization → Duplicate Detection → Bid (DB)

BLOCKED items are documented at module level; no fake live-API code is included.

BLOCKED — requires authorized GeM access:
    - Live GeM API polling / scheduled fetch
    - GeM OAuth token acquisition
    - GeM buyer/seller dashboard scraping (unauthorized)
    Any attempt to implement these without official credentials is prohibited.
"""
from __future__ import annotations

import json
import pytest

from app.models.bid import Bid
from app.models.collection import CollectionRun
from app.services.ingestion import (
    ApprovedGeMAdapter,
    LicensedProviderAdapter,
    RawBidRecord,
    normalize_record,
    run_ingestion_pipeline,
    validate_record,
)

# ---------------------------------------------------------------------------
# Shared test fixtures / data
# ---------------------------------------------------------------------------

GEM_MOCK_PAYLOAD = [
    {
        "gem_bid_id": "GEM/2026/B/10001",
        "bid_number": "GEM-10001",
        "title": "Comprehensive Cyber Security Audit & Smart Contract Assessment Services",
        "organisation": "National Smart Grid Mission",
        "department": "Department of Energy",
        "ministry": "Ministry of Power",
        "category": "Cyber Security Consultancy Services",
        "published_date": "2026-09-20T10:00:00Z",
        "closing_date": "2026-10-15T15:00:00Z",
        "location": "New Delhi",
        "estimated_value": 7500000.0,
        "currency": "INR",
        "scope_of_work": (
            "Conducting source code security review, smart contract vulnerability "
            "assessments, and web portal VAPT."
        ),
        "technical_requirements": {
            "certifications_required": ["CERT-In Empanelled", "ISO 27001"],
            "minimum_experience_years": 5,
        },
        "eligibility_criteria": {
            "annual_turnover_inr": 20_000_000.0,
            "prior_govt_projects": 3,
        },
        "source_url": "https://gem.gov.in/bids/GEM-10001",
        "source_name": "gem_mock_dev",
    },
    {
        "gem_bid_id": "GEM/2026/B/10002",
        "title": "SIEM Implementation and SOC-as-a-Service",
        "organisation": "Ministry of Home Affairs",
        "department": "Cybersecurity Division",
        "category": "Security Operations",
        "published_date": "2026-09-22T09:00:00Z",
        "closing_date": "2026-11-01T17:00:00Z",
        "estimated_value": "₹ 2,50,00,000",
        "currency": "INR",
        "scope_of_work": "24x7 security operations centre with SIEM platform and threat intelligence feeds.",
        "source_name": "gem_mock_dev",
    },
]


def _mock_bytes(payload=None) -> bytes:
    return json.dumps(payload or GEM_MOCK_PAYLOAD).encode("utf-8")


# ---------------------------------------------------------------------------
# 1. ApprovedGeMAdapter – unit tests
# ---------------------------------------------------------------------------

class TestApprovedGeMAdapter:
    """ApprovedGeMAdapter wraps JSONBidAdapter for structured GeM-format payloads."""

    def test_adapter_name(self):
        assert ApprovedGeMAdapter.adapter_name == "ApprovedGeMAdapter"

    def test_parses_list_payload(self):
        adapter = ApprovedGeMAdapter()
        records = adapter.parse(_mock_bytes())
        assert len(records) == 2

    def test_parses_single_object_payload(self):
        single = json.dumps(GEM_MOCK_PAYLOAD[0]).encode("utf-8")
        adapter = ApprovedGeMAdapter()
        records = adapter.parse(single)
        assert len(records) == 1

    def test_record_fields_mapped_correctly(self):
        adapter = ApprovedGeMAdapter()
        records = adapter.parse(_mock_bytes())
        r = records[0]
        assert r.gem_bid_id == "GEM/2026/B/10001"
        assert r.title == "Comprehensive Cyber Security Audit & Smart Contract Assessment Services"
        assert r.organisation == "National Smart Grid Mission"
        assert r.ministry == "Ministry of Power"
        assert r.category == "Cyber Security Consultancy Services"
        assert r.currency == "INR"

    def test_nested_json_fields_preserved(self):
        adapter = ApprovedGeMAdapter()
        records = adapter.parse(_mock_bytes())
        r = records[0]
        assert r.technical_requirements is not None
        assert r.eligibility_criteria is not None

    def test_invalid_json_raises(self):
        adapter = ApprovedGeMAdapter()
        with pytest.raises(ValueError, match="Invalid JSON"):
            adapter.parse(b"not valid json at all }{")

    def test_empty_list_returns_empty(self):
        adapter = ApprovedGeMAdapter()
        records = adapter.parse(b"[]")
        assert records == []


# ---------------------------------------------------------------------------
# 2. LicensedProviderAdapter – smoke test
# ---------------------------------------------------------------------------

class TestLicensedProviderAdapter:
    def test_adapter_name(self):
        assert LicensedProviderAdapter.adapter_name == "LicensedProviderAdapter"

    def test_parses_same_payload(self):
        adapter = LicensedProviderAdapter()
        records = adapter.parse(_mock_bytes())
        assert len(records) == 2
        assert records[0].gem_bid_id == "GEM/2026/B/10001"


# ---------------------------------------------------------------------------
# 3. Validation of GeM-structured records
# ---------------------------------------------------------------------------

class TestGeMRecordValidation:
    def test_valid_gem_record_passes(self):
        adapter = ApprovedGeMAdapter()
        records = adapter.parse(_mock_bytes())
        for idx, rec in enumerate(records):
            result = validate_record(rec, idx)
            assert result.is_valid, f"Record {idx} failed validation: {result.errors}"

    def test_record_missing_title_fails(self):
        bad = [{"gem_bid_id": "GEM/2026/B/NOTITLE", "title": ""}]
        adapter = ApprovedGeMAdapter()
        records = adapter.parse(json.dumps(bad).encode())
        result = validate_record(records[0], 0)
        assert not result.is_valid
        assert any(e.field == "title" for e in result.errors)

    def test_record_invalid_value_fails(self):
        bad = [{"gem_bid_id": "GEM/TEST", "title": "Test Bid", "estimated_value": "NOT_A_NUMBER_XYZ"}]
        adapter = ApprovedGeMAdapter()
        records = adapter.parse(json.dumps(bad).encode())
        result = validate_record(records[0], 0)
        assert not result.is_valid
        assert any(e.field == "estimated_value" for e in result.errors)


# ---------------------------------------------------------------------------
# 4. Normalization of GeM-structured records
# ---------------------------------------------------------------------------

class TestGeMRecordNormalization:
    def test_normalizes_estimated_value_float(self):
        adapter = ApprovedGeMAdapter()
        records = adapter.parse(_mock_bytes())
        norm = normalize_record(records[0])
        assert norm["estimated_value"] == 7_500_000.0

    def test_normalizes_estimated_value_currency_string(self):
        adapter = ApprovedGeMAdapter()
        records = adapter.parse(_mock_bytes())
        norm = normalize_record(records[1])
        # "₹ 2,50,00,000" = 25,000,000
        assert norm["estimated_value"] == 25_000_000.0

    def test_dates_parsed_to_utc(self):
        from datetime import timezone
        adapter = ApprovedGeMAdapter()
        records = adapter.parse(_mock_bytes())
        norm = normalize_record(records[0])
        assert norm["published_date"] is not None
        assert norm["published_date"].tzinfo is not None
        assert norm["closing_date"] is not None

    def test_search_text_generated(self):
        adapter = ApprovedGeMAdapter()
        records = adapter.parse(_mock_bytes())
        norm = normalize_record(records[0])
        assert norm["search_text"] is not None
        assert "GEM/2026/B/10001" in norm["search_text"]
        assert "Cyber Security" in norm["search_text"]

    def test_content_hash_deterministic(self):
        adapter = ApprovedGeMAdapter()
        records = adapter.parse(_mock_bytes())
        norm1 = normalize_record(records[0])
        norm2 = normalize_record(records[0])
        assert norm1["hash"] == norm2["hash"]

    def test_json_fields_become_dicts(self):
        adapter = ApprovedGeMAdapter()
        records = adapter.parse(_mock_bytes())
        norm = normalize_record(records[0])
        assert isinstance(norm["technical_requirements"], dict)
        assert isinstance(norm["eligibility_criteria"], dict)

    def test_source_name_preserved(self):
        adapter = ApprovedGeMAdapter()
        records = adapter.parse(_mock_bytes())
        norm = normalize_record(records[0])
        assert norm["source_name"] == "gem_mock_dev"


# ---------------------------------------------------------------------------
# 5. Full Pipeline: GeM mock data → DB persistence
# ---------------------------------------------------------------------------

class TestGeMFullPipeline:
    def test_pipeline_creates_bids_from_gem_mock(self, db):
        result = run_ingestion_pipeline(
            db=db,
            file_content=_mock_bytes(),
            file_type="json",
            source_name="gem_mock_dev",
        )
        assert result.status in ("success", "completed", "SUCCESS")
        assert result.total_records == 2
        assert result.created == 2
        assert result.duplicates == 0
        assert result.failed == 0

    def test_bids_persisted_with_correct_fields(self, db):
        run_ingestion_pipeline(db=db, file_content=_mock_bytes(), file_type="json", source_name="gem_mock_dev")
        bid = db.query(Bid).filter(Bid.gem_bid_id == "GEM/2026/B/10001").first()
        assert bid is not None
        assert bid.title == "Comprehensive Cyber Security Audit & Smart Contract Assessment Services"
        assert bid.organisation == "National Smart Grid Mission"
        assert float(bid.estimated_value) == 7_500_000.0
        assert bid.status == "NEW"
        assert bid.content_hash is not None

    def test_search_text_persisted_on_bid(self, db):
        """search_text must now reach the DB via the new Bid.search_text column."""
        run_ingestion_pipeline(db=db, file_content=_mock_bytes(), file_type="json", source_name="gem_mock_dev")
        bid = db.query(Bid).filter(Bid.gem_bid_id == "GEM/2026/B/10001").first()
        assert bid is not None
        assert bid.search_text is not None
        assert "Cyber Security" in bid.search_text

    def test_source_name_persisted_on_bid(self, db):
        """source_name must now reach the DB via the new Bid.source_name column."""
        run_ingestion_pipeline(db=db, file_content=_mock_bytes(), file_type="json", source_name="gem_mock_dev")
        bid = db.query(Bid).filter(Bid.gem_bid_id == "GEM/2026/B/10001").first()
        assert bid is not None
        assert bid.source_name == "gem_mock_dev"

    def test_collection_run_recorded(self, db):
        result = run_ingestion_pipeline(db=db, file_content=_mock_bytes(), file_type="json", source_name="gem_mock_dev")
        run = db.query(CollectionRun).filter(CollectionRun.id == result.run_id).first()
        assert run is not None
        assert run.records_found == 2
        assert run.records_new == 2
        assert run.status == "SUCCESS"

    def test_pipeline_deduplicates_gem_bid_id(self, db):
        """Second ingestion of same data must count as duplicates, not create new rows."""
        run_ingestion_pipeline(db=db, file_content=_mock_bytes(), file_type="json", source_name="gem_mock_dev_run1")
        result2 = run_ingestion_pipeline(db=db, file_content=_mock_bytes(), file_type="json", source_name="gem_mock_dev_run2")
        assert result2.created == 0
        assert result2.duplicates == 2
        total_bids = db.query(Bid).filter(Bid.gem_bid_id.in_(["GEM/2026/B/10001", "GEM/2026/B/10002"])).count()
        assert total_bids == 2  # no duplication

    def test_pipeline_update_duplicate_with_flag(self, db):
        """allow_update_duplicates=True must update existing bids that match."""
        run_ingestion_pipeline(db=db, file_content=_mock_bytes(), file_type="json", source_name="initial")

        # Only update bid[0]; keep bid[1] unchanged but send both to test mixed update
        updated_payload = list(GEM_MOCK_PAYLOAD)
        updated_payload[0] = dict(GEM_MOCK_PAYLOAD[0])
        updated_payload[0]["title"] = "Updated Security Audit Title v2"
        updated_payload[0]["estimated_value"] = 9_999_999.0

        result = run_ingestion_pipeline(
            db=db,
            file_content=json.dumps(updated_payload).encode("utf-8"),
            file_type="json",
            source_name="gem_mock_update",
            allow_update_duplicates=True,
        )
        # Both bids are duplicates → both are updated (updated >= 1)
        assert result.updated >= 1
        assert result.duplicates == 2
        assert result.created == 0
        bid = db.query(Bid).filter(Bid.gem_bid_id == "GEM/2026/B/10001").first()
        assert "Updated Security Audit Title v2" in bid.title

    def test_gem_adapter_registered_in_registry(self):
        """The gem_api key in the adapter registry must resolve to ApprovedGeMAdapter."""
        from app.services.ingestion.adapters import ADAPTER_MAP
        assert "gem_api" in ADAPTER_MAP
        assert ADAPTER_MAP["gem_api"] is ApprovedGeMAdapter

    def test_approved_gem_adapter_via_get_adapter(self):
        from app.services.ingestion.adapters import get_adapter
        adapter = get_adapter("gem_api")
        assert isinstance(adapter, ApprovedGeMAdapter)


# ---------------------------------------------------------------------------
# 6. BLOCKED – Live GeM API Access
# ---------------------------------------------------------------------------
# The following capabilities are NOT implemented because they require
# official GeM API credentials or authorized access, which SecuredApp
# does not currently have.
#
#   BLOCKED: GET https://gem.gov.in/api/v1/bids  → requires API key/OAuth
#   BLOCKED: Scheduled polling of GeM portal      → requires authorized session
#   BLOCKED: GeM Buyer/Seller dashboard scraping  → unauthorized; CAPTCHA protected
#   BLOCKED: GeM API token acquisition flow       → no credentials issued yet
#
# When official GeM API access is granted:
#   1. Implement GeMAPIClient in app/services/ingestion/gem_api_client.py
#   2. Parse responses using ApprovedGeMAdapter (already implemented)
#   3. Wire GeMAPIClient → ApprovedGeMAdapter → run_ingestion_pipeline (already implemented)
#   4. Add scheduler trigger (Stage 2 task)
# ---------------------------------------------------------------------------
