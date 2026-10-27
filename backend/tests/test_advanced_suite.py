"""
Comprehensive test suite covering:
- Section 29: False-positive & context sensitivity tests
- Section 30: Score boundary classification tests
- Section 31: Duplicate import and update detection tests
- Section 32: End-to-End complete workflow verification test
- Section 33: Failure mode and edge case tests
"""
import io
import json
import openpyxl
import pytest
from datetime import datetime, timedelta, timezone
from fastapi.testclient import TestClient

from app.db.seed_knowledge import seed_product_knowledge
from app.models.analysis import BidAnalysis, BidProductMatch, BidScore
from app.models.bid import Bid
from app.models.notification import Notification
from app.models.review import HumanReview
from app.services.ingestion import run_ingestion_pipeline
from app.services.intelligence import match_bid_against_products
from app.services.intelligence.matching_engine import classify_score


@pytest.fixture(autouse=True)
def seed_knowledge(db):
    seed_product_knowledge(db)


# ---------------------------------------------------------------------------
# SECTION 29: False-Positive & Context Tests
# ---------------------------------------------------------------------------
def test_generic_blockchain_keyword_not_overmatching(db):
    """'blockchain' alone should not strongly match every blockchain product."""
    bid = Bid(
        title="Supply of General Ledger Software",
        scope_of_work="Basic data entry software with standard database storage using blockchain terminology.",
    )
    db.add(bid)
    db.commit()

    results = match_bid_against_products(db, bid)
    # Generic mention of blockchain without specific forensics/monitoring should not trigger MATCH (>=0.70)
    for res in results:
        assert res.relevance_score < 0.70, f"{res.product_name} overmatched with score {res.relevance_score}"


def test_generic_security_keyword_not_overmatching(db):
    """'security' alone should not strongly match SolidityShield."""
    bid = Bid(
        title="Physical Security Services for Office Premises",
        scope_of_work="Provision of security guards and physical access gates.",
    )
    db.add(bid)
    db.commit()

    results = match_bid_against_products(db, bid)
    sol_res = next(r for r in results if r.product_name == "SolidityShield")
    assert sol_res.match_state == "NO_MATCH"
    assert sol_res.relevance_score < 0.25


def test_generic_identity_keyword_not_overmatching(db):
    """'identity' alone should not strongly match SecureX-DID or SecureX-ID."""
    bid = Bid(
        title="Print Office ID Cards and Lanyards",
        scope_of_work="Printing employee identity cards and plastic badge holders.",
    )
    db.add(bid)
    db.commit()

    results = match_bid_against_products(db, bid)
    did_res = next(r for r in results if r.product_name == "SecureX-DID")
    xid_res = next(r for r in results if r.product_name == "SecureX-ID")
    assert did_res.relevance_score < 0.45
    assert xid_res.relevance_score < 0.45


def test_generic_quantum_keyword_not_overmatching(db):
    """'quantum' alone should not strongly match PQCSuite or QuantumVault."""
    bid = Bid(
        title="Supply of High Performance Quantum Computing Physics Lab Equipment",
        scope_of_work="Supply of optical lasers and quantum physics experimental apparatus.",
    )
    db.add(bid)
    db.commit()

    results = match_bid_against_products(db, bid)
    pqc_res = next(r for r in results if r.product_name == "PQCSuite")
    qvt_res = next(r for r in results if r.product_name == "QuantumVault")
    assert pqc_res.relevance_score < 0.45
    assert qvt_res.relevance_score < 0.45


# ---------------------------------------------------------------------------
# SECTION 30: Score Boundary Tests
# ---------------------------------------------------------------------------
def test_score_boundary_exact_values():
    assert classify_score(0.249) == "NO_MATCH"
    assert classify_score(0.250) == "NEEDS_REVIEW"
    assert classify_score(0.449) == "NEEDS_REVIEW"
    assert classify_score(0.450) == "POSSIBLE_MATCH"
    assert classify_score(0.699) == "POSSIBLE_MATCH"
    assert classify_score(0.700) == "MATCH"


# ---------------------------------------------------------------------------
# SECTION 31: Duplicate & Update Ingestion Tests
# ---------------------------------------------------------------------------
def test_duplicate_import_twice_and_update(db):
    json_payload = [
        {
            "gem_bid_id": "GEM/2026/DUPTEST/100",
            "title": "Smart Contract Audit for DeFi Platform",
            "organisation": "ISRO Cyber Division",
            "estimated_value": "5000000",
            "scope_of_work": "Solidity smart contract security audit",
        }
    ]
    raw_bytes = json.dumps(json_payload).encode("utf-8")

    # First import -> NEW
    res1 = run_ingestion_pipeline(db, raw_bytes, "json", source_name="test_run_1")
    assert res1.created == 1
    assert res1.duplicates == 0

    # Second import -> DUPLICATE / UNCHANGED
    res2 = run_ingestion_pipeline(db, raw_bytes, "json", source_name="test_run_2")
    assert res2.created == 0
    assert res2.duplicates == 1

    # Update import with allow_update_duplicates=True
    updated_payload = [
        {
            "gem_bid_id": "GEM/2026/DUPTEST/100",
            "title": "Smart Contract Audit for DeFi Platform - Updated Scope",
            "organisation": "ISRO Cyber Division",
            "estimated_value": "6000000",
            "scope_of_work": "Solidity smart contract security audit and reentrancy check",
        }
    ]
    res3 = run_ingestion_pipeline(
        db, json.dumps(updated_payload).encode("utf-8"), "json", source_name="test_run_3", allow_update_duplicates=True
    )
    assert res3.updated == 1
    assert res3.duplicates == 1

    bid_in_db = db.query(Bid).filter(Bid.gem_bid_id == "GEM/2026/DUPTEST/100").first()
    assert "Updated Scope" in bid_in_db.title


# ---------------------------------------------------------------------------
# SECTION 33: Safe Failure Mode Tests
# ---------------------------------------------------------------------------
def test_malformed_csv_upload_handling(client: TestClient):
    malformed_csv = b"invalid,header,without\n\"unclosed string literal,123,456"
    files = {"file": ("bad.csv", malformed_csv, "text/csv")}
    res = client.post("/api/v1/ingestion/import", files=files)
    assert res.status_code == 200
    data = res.json()
    assert data["failed"] > 0 or data["status"] in ("failed", "partial")



def test_empty_file_upload_handling(client: TestClient):
    files = {"file": ("empty.json", b"", "application/json")}
    res = client.post("/api/v1/ingestion/import", files=files)
    assert res.status_code == 400
    assert "empty" in res.json()["detail"].lower()


def test_nonexistent_bid_analysis_404(client: TestClient):
    fake_uuid = "00000000-0000-0000-0000-000000000000"
    res = client.post(f"/api/v1/bids/{fake_uuid}/analyze")
    assert res.status_code == 404


# ---------------------------------------------------------------------------
# SECTION 32: End-to-End (E2E) Workflow Test
# ---------------------------------------------------------------------------
def test_e2e_full_procurement_intelligence_workflow(client: TestClient, db):
    """
    Complete E2E pipeline test:
    Ingest sample bid -> Validate -> Normalize -> Deduplicate -> Match products ->
    Analyze requirements & opportunity -> Human review -> Notification -> Evaluation.
    """
    # 1. Ingest Bid via API
    csv_content = (
        "gem_bid_id,title,organisation,scope_of_work,estimated_value,closing_date\n"
        "GEM/E2E/2026/99,Solidity Smart Contract Security Assessment,MeitY,Full vulnerability scanning and manual expert review of EVM contracts,10000000,2026-10-31\n"
    )
    files = {"file": ("e2e_bid.csv", csv_content.encode("utf-8"), "text/csv")}
    imp_res = client.post("/api/v1/ingestion/import", files=files)
    assert imp_res.status_code == 200
    bid_id = db.query(Bid).filter(Bid.gem_bid_id == "GEM/E2E/2026/99").first().id

    # 2. Run Phase 4 Full Analysis
    ana_res = client.post(f"/api/v1/bids/{bid_id}/analyze")
    assert ana_res.status_code == 200
    ana_data = ana_res.json()
    assert ana_data["bid_id"] == str(bid_id)

    # 3. Verify Deterministic Matching & Opportunity Results
    assert "intelligence" in ana_data
    assert "opportunity" in ana_data

    # 4. Submit Human Review Decision
    rev_res = client.post(
        f"/api/v1/bids/{bid_id}/review",
        json={
            "relevance_decision": "RELEVANT",
            "pursue_decision": "PURSUE",
            "comments": "E2E test human review approval for SolidityShield.",
        },
    )
    assert rev_res.status_code == 201

    # 5. Check Notifications Log
    notif_res = client.get("/api/v1/notifications")
    assert notif_res.status_code == 200
    notifs = notif_res.json()
    assert any(n["bid_id"] == str(bid_id) for n in notifs)

    # 6. Check Evaluation Analytics
    eval_res = client.get("/api/v1/analytics/evaluation")
    assert eval_res.status_code == 200
    eval_data = eval_res.json()
    assert eval_data["total_evaluated_reviews"] >= 1
    assert eval_data["agreement_rate"] >= 0.0
