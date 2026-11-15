"""
Tests for batch state-wise tender product matching.

Verifies that:
  * every eligible state-wise tender is evaluated against all 11 products,
  * product matches are persisted as BidProductMatch records,
  * the batch matching endpoint updates matching_status (PENDING -> COMPLETED/FAILED),
  * duplicate tender-product matches are prevented,
  * FAILED bids can be retried,
  * the state-wise endpoint returns all product matches per bid,
  * irrelevant tenders remain NO_MATCH (not stored as matches),
  * state-wise and product-wise filtering returns accurate results.
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.seed_knowledge import seed_product_knowledge
from app.models.bid import Bid
from app.models.analysis import BidProductMatch, BidAnalysis
from app.models.product import Product
from app.models.source import DataSource


# Synthetic state tenders (NOT GeM bids) used to exercise the batch matching pipeline.
STATE_TENDERS = [
    {
        "title": "Solidity Smart Contract Security Audit and Expert Review",
        "scope": "Pre-deployment smart contract security scanning, vulnerability "
                 "detection, reentrancy detection and manual expert security "
                 "review with remediation validation.",
        "department": "Electronics & IT",
        "organisation": "Directorate of E-Governance",
        "source_name": "karnataka_eproc",
        "expected_product": "SolidityShield",
    },
    {
        "title": "Blockchain Forensics and Wallet Tracing Investigation",
        "scope": "Blockchain investigation, transaction tracing, wallet tracing "
                 "and fund-flow analysis of suspicious cryptocurrency "
                 "transactions.",
        "department": "Cyber Crime",
        "organisation": "Kerala Police",
        "source_name": "kerala_eproc",
        "expected_product": "SecureTrace",
    },
    {
        "title": "Post Quantum Cryptography Migration and Crypto Agility",
        "scope": "Migration to post-quantum cryptographic algorithms, "
                 "cryptographic agility and quantum-resistant encryption.",
        "department": "IT",
        "organisation": "Tamil Nadu e-Governance Agency",
        "source_name": "tamilnadu_eproc",
        "expected_product": "PQCSuite",
    },
    {
        "title": "Office Furniture and Stationery Supply",
        "scope": "Supply of office chairs, desks, stationery and furniture for "
                 "government offices.",
        "department": "Administration",
        "organisation": "Central Procurement",
        "source_name": "maharashtra_eproc",
        "expected_product": None,
    },
    {
        "title": "Hardware Security Module Key Management",
        "scope": "Cryptographic key generation, secure key storage in HSM, key "
                 "rotation and revocation with hardware-backed protection.",
        "department": "IT",
        "organisation": "Telangana State Technology Services",
        "source_name": "telangana_eproc",
        "expected_product": "QuantumVault",
    },
]


@pytest.fixture(autouse=True)
def seed_knowledge(db: Session):
    """Seed product knowledge into the test DB before each test."""
    seed_product_knowledge(db)


@pytest.fixture
def state_sources(db: Session):
    """Create state data sources (not GeM)."""
    sources = []
    for spec in STATE_TENDERS:
        ds = DataSource(
            source_id=spec["source_name"],
            name=spec["source_name"],  # Must match Bid.source_name for the join
            adapter_key="html_listing",
            source_type="html_listing",
            enabled=True,
            status="SUCCESS",
        )
        db.add(ds)
        sources.append(ds)
    db.commit()
    return sources


@pytest.fixture
def state_tenders(db: Session, state_sources):
    """Insert synthetic state tenders into the DB."""
    created = []
    for spec in STATE_TENDERS:
        bid = Bid(
            title=spec["title"],
            scope_of_work=spec["scope"],
            department=spec["department"],
            organisation=spec["organisation"],
            source_name=spec["source_name"],
            status="NEW",
            matching_status="PENDING",
        )
        db.add(bid)
        created.append((spec, bid))
    db.commit()
    for _, bid in created:
        db.refresh(bid)
    return created


def test_products_seeded_for_matching(db):
    products = db.query(Product).filter(Product.active == True).all()
    assert len(products) == 11


def test_batch_match_all_state_tenders(client: TestClient, db: Session, state_tenders):
    """Batch match all state tenders against all 11 products."""
    response = client.post("/api/v1/bids/state-wise/match-all")
    assert response.status_code == 200, response.text
    data = response.json()

    assert data["total_eligible"] == len(STATE_TENDERS)
    assert data["processed"] == len(STATE_TENDERS)
    assert data["failed"] == 0
    assert data["matches_persisted"] >= 1  # At least some matches should persist

    # Verify all bids are now COMPLETED
    for _, bid in state_tenders:
        db.refresh(bid)
        assert bid.matching_status == "COMPLETED", f"Bid {bid.id} not completed"


def test_product_matches_persisted_for_state_tenders(client: TestClient, db: Session, state_tenders):
    """Verify BidProductMatch records are persisted for matched state tenders."""
    client.post("/api/v1/bids/state-wise/match-all")

    total_matches = db.query(BidProductMatch).count()
    assert total_matches >= 1, "Expected at least one product match to be persisted"

    # Verify matches reference valid products
    product_ids = {str(p.id) for p in db.query(Product).all()}
    for m in db.query(BidProductMatch).all():
        assert str(m.product_id) in product_ids
        assert m.match_score >= 0.25  # Only NEEDS_REVIEW or better are persisted


def test_irrelevant_tender_remains_no_match(client: TestClient, db: Session, state_tenders):
    """The office furniture tender should have no product matches (NO_MATCH)."""
    client.post("/api/v1/bids/state-wise/match-all")

    furniture_bid = next(b for spec, b in state_tenders if spec["expected_product"] is None)
    matches = (
        db.query(BidProductMatch)
        .filter(BidProductMatch.bid_id == furniture_bid.id)
        .all()
    )
    # No matches should be persisted for the irrelevant tender
    assert len(matches) == 0, f"Expected 0 matches for irrelevant tender, got {len(matches)}"


def test_duplicate_matches_prevented(client: TestClient, db: Session, state_tenders):
    """Running batch match twice should not create duplicate BidProductMatch records."""
    client.post("/api/v1/bids/state-wise/match-all")
    count_after_first = db.query(BidProductMatch).count()

    client.post("/api/v1/bids/state-wise/match-all")
    count_after_second = db.query(BidProductMatch).count()

    assert count_after_first == count_after_second, "Duplicate matches were created"


def test_state_wise_endpoint_returns_product_matches(client: TestClient, db: Session, state_tenders):
    """The state-wise endpoint should return all product matches per bid."""
    client.post("/api/v1/bids/state-wise/match-all")

    response = client.get("/api/v1/bids/state-wise")
    assert response.status_code == 200, response.text
    data = response.json()

    assert "bids" in data
    assert "total" in data

    # Each row should have product_matches array
    for row in data["bids"]:
        assert "product_matches" in row
        assert "matched_product_count" in row
        assert isinstance(row["product_matches"], list)


def test_state_wise_product_filter(client: TestClient, db: Session, state_tenders):
    """Filtering state-wise bids by product should return accurate results."""
    client.post("/api/v1/bids/state-wise/match-all")

    response = client.get("/api/v1/bids/state-wise", params={"product": "SolidityShield"})
    assert response.status_code == 200, response.text
    rows = response.json()["bids"]

    for row in rows:
        assert any(m["product_name"] == "SolidityShield" for m in row["product_matches"]), row


def test_state_wise_match_status_filter(client: TestClient, db: Session, state_tenders):
    """Filtering by match status should return accurate results."""
    client.post("/api/v1/bids/state-wise/match-all")

    response = client.get("/api/v1/bids/state-wise", params={"match_status": "MATCH"})
    assert response.status_code == 200, response.text
    rows = response.json()["bids"]

    for row in rows:
        assert any(
            (m.get("evidence") or {}).get("match_state") == "MATCH"
            for m in row["product_matches"]
        ), row


def test_retry_failed_bids(client: TestClient, db: Session, state_tenders):
    """FAILED bids should be retried on subsequent batch match runs."""
    client.post("/api/v1/bids/state-wise/match-all")

    # Manually set one bid to FAILED to test retry
    _, bid = state_tenders[0]
    bid.matching_status = "FAILED"
    db.add(bid)
    db.commit()

    response = client.post("/api/v1/bids/state-wise/match-all")
    assert response.status_code == 200, response.text
    data = response.json()

    # Only the FAILED bid should be reprocessed (1 eligible)
    assert data["total_eligible"] == 1
    assert data["processed"] == 1

    db.refresh(bid)
    assert bid.matching_status == "COMPLETED"


def test_matching_status_transitions(client: TestClient, db: Session, state_tenders):
    """Verify matching_status transitions from PENDING to COMPLETED."""
    # Before matching, all bids should be PENDING
    for _, bid in state_tenders:
        db.refresh(bid)
        assert bid.matching_status == "PENDING"

    client.post("/api/v1/bids/state-wise/match-all")

    # After matching, all bids should be COMPLETED
    for _, bid in state_tenders:
        db.refresh(bid)
        assert bid.matching_status == "COMPLETED"
        assert bid.matched_at is not None


def test_state_wise_endpoint_excludes_gem_bids(client: TestClient, db: Session):
    """GeM bids should be excluded from the state-wise endpoint."""
    # Create a GeM bid
    gem_bid = Bid(
        title="GeM Smart Contract Security Audit",
        scope_of_work="Smart contract security scanning and vulnerability detection.",
        source_name="gem_direct",
        status="NEW",
        matching_status="PENDING",
    )
    db.add(gem_bid)
    db.commit()

    client.post("/api/v1/bids/state-wise/match-all")

    response = client.get("/api/v1/bids/state-wise")
    assert response.status_code == 200, response.text
    data = response.json()

    # No GeM bids should appear
    for row in data["bids"]:
        assert "gem" not in (row.get("source") or "").lower(), row
        assert row["source_name"] != "gem_direct", row


def test_all_india_includes_state_tenders(client: TestClient, db: Session, state_tenders):
    """The All-India dashboard should include state-wise tender matches."""
    client.post("/api/v1/bids/state-wise/match-all")

    response = client.get("/api/v1/dashboard/all-india/summary")
    assert response.status_code == 200, response.text
    data = response.json()

    assert data["total_bids"] >= 1
    assert data["states_covered"] >= 1
    assert data["products_with_matches"] >= 1

    # State distribution should include state names from our synthetic tenders
    locations = {e["location"] for e in data["state_distribution"]}
    assert len(locations) >= 1
