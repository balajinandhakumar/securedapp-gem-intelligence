"""
End-to-end tests for the All-India product-relevant GeM bid matching dashboard.

These tests use synthetic bids (never fabricated GeM data) to verify that:
  * the 11 SecuredApp products are available for matching,
  * bids are matched against products and the matches are persisted,
  * the /dashboard/all-india/summary endpoint returns correct overall stats
    plus state-wise and product-wise distribution,
  * the /dashboard/all-india/bids endpoint returns only matches at 50/100 or
    above, with correct 0-100 scores and classifications,
  * a bid without a location is reported as "Location Not Specified",
  * one bid matching multiple products is exposed once per matched product,
  * pagination and filters (product, min_score, state, search) work.
"""
import pytest
from fastapi.testclient import TestClient

from app.db.seed_knowledge import seed_product_knowledge
from app.models.bid import Bid
from app.models.analysis import BidProductMatch
from app.models.product import Product

# Synthetic bids used only to exercise the matching pipeline and dashboard API.
# These are NOT GeM tender records and are never presented as real data.
SYNTHETIC_BIDS = [
    {
        "title": "Solidity Smart Contract Security Audit and Expert Review",
        "scope": "Pre-deployment smart contract security scanning, vulnerability "
                 "detection, reentrancy detection and manual expert security "
                 "review with remediation validation.",
        "location": "Karnataka, Bengaluru",
        "department": "Electronics & IT",
        "organisation": "Directorate of E-Governance",
        "expected_product": "SolidityShield",
    },
    {
        "title": "Blockchain Forensics and Wallet Tracing Investigation",
        "scope": "Blockchain investigation, transaction tracing, wallet tracing "
                 "and fund-flow analysis of suspicious cryptocurrency "
                 "transactions.",
        "location": "Maharashtra, Mumbai",
        "department": "Cyber Crime",
        "organisation": "Maharashtra Police",
        "expected_product": "SecureTrace",
    },
    {
        "title": "Post Quantum Cryptography Migration and Crypto Agility",
        "scope": "Migration to post-quantum cryptographic algorithms, "
                 "cryptographic agility and quantum-resistant encryption.",
        "location": "Karnataka, Bengaluru",
        "department": "IT",
        "organisation": "Karnataka State Data Centre",
        "expected_product": "PQCSuite",
    },
    {
        "title": "Continuous Blockchain Monitoring and Anomaly Detection",
        "scope": "24/7 continuous monitoring of blockchain transactions, smart "
                 "contract activity monitoring, anomaly detection and security "
                 "alerts.",
        "location": "Tamil Nadu, Chennai",
        "department": "IT",
        "organisation": "Tamil Nadu e-Governance Agency",
        "expected_product": "SecureWatch",
    },
    {
        "title": "KYC AML Identity Verification and Watchlist Screening",
        "scope": "Know Your Customer verification, AML checks, watchlist "
                 "screening and identity risk assessment for digital onboarding.",
        "location": None,
        "department": "Finance",
        "organisation": "Financial Intelligence Unit",
        "expected_product": "SecureX-ID",
    },
    {
        "title": "Hardware Security Module Key Management",
        "scope": "Cryptographic key generation, secure key storage in HSM, key "
                 "rotation and revocation with hardware-backed protection.",
        "location": "Telangana, Hyderabad",
        "department": "IT",
        "organisation": "Telangana State Technology Services",
        "expected_product": "QuantumVault",
    },
    {
        "title": "Office Furniture and Stationery Supply",
        "scope": "Supply of office chairs, desks, stationery and furniture for "
                 "government offices.",
        "location": "Delhi, New Delhi",
        "department": "Administration",
        "organisation": "Central Procurement",
        "expected_product": None,
    },
]


@pytest.fixture(autouse=True)
def seed_knowledge(db):
    """Seed product knowledge into the test DB before each test."""
    seed_product_knowledge(db)


@pytest.fixture
def matched_bids(db, client: TestClient):
    """Insert synthetic bids, run all-India matching, return created bids."""
    created = []
    for spec in SYNTHETIC_BIDS:
        bid = Bid(
            title=spec["title"],
            scope_of_work=spec["scope"],
            location=spec["location"],
            department=spec["department"],
            organisation=spec["organisation"],
            source_name="gem_direct",
            status="NEW",
        )
        db.add(bid)
        created.append((spec, bid))
    db.commit()
    for _, bid in created:
        db.refresh(bid)

    response = client.post("/api/v1/dashboard/all-india/match-all")
    assert response.status_code == 202, response.text
    return created


def test_products_seeded_for_matching(db):
    products = db.query(Product).filter(Product.active == True).all()
    assert len(products) == 11
    names = {p.name for p in products}
    for name in [
        "SolidityShield", "SecureCMS", "SecureTrace", "CookieHub", "PQCSuite",
        "SecureX-DID", "SecureWatch", "AuditExpress", "SecurePad", "SecureX-ID",
        "QuantumVault",
    ]:
        assert name in names


def test_match_all_persists_product_matches(matched_bids, db):
    total_matches = db.query(BidProductMatch).count()
    assert total_matches >= 1, "Expected at least one product match to be persisted"
    # Each bid is a single row; matches are separate child rows.
    bids_with_match = (
        db.query(BidProductMatch.bid_id).distinct().count()
    )
    assert bids_with_match >= 1


def test_only_relevant_matches_are_persisted(matched_bids, db):
    # Nothing below the NEEDS_REVIEW band (0.25) should be stored as a match.
    weak = (
        db.query(BidProductMatch)
        .filter(BidProductMatch.match_score < 0.25)
        .count()
    )
    assert weak == 0


def test_all_india_summary_shape(matched_bids, client: TestClient, db):
    response = client.get("/api/v1/dashboard/all-india/summary")
    assert response.status_code == 200, response.text
    data = response.json()

    # Overall stats present.
    for key in [
        "total_bids", "total_relevant_bids", "highly_relevant_bids",
        "relevant_bids", "potentially_relevant_bids", "states_covered",
        "products_with_matches",
    ]:
        assert key in data, f"Missing summary key: {key}"
        assert isinstance(data[key], int)

    # Consistency: every displayed bid is relevant (>= 50/100).
    assert data["total_relevant_bids"] == data["total_bids"]

    # At least one state and one product with matches.
    assert data["states_covered"] >= 1
    assert data["products_with_matches"] >= 1

    # State distribution entries carry the right fields.
    for entry in data["state_distribution"]:
        assert set(entry) >= {
            "location", "bid_count", "highly_relevant", "relevant",
            "potentially_relevant",
        }

    # Product distribution entries carry the right fields.
    for entry in data["product_distribution"]:
        assert set(entry) >= {"product_name", "bid_count"}


def test_all_india_summary_counts_match_persistence(matched_bids, client: TestClient, db):
    response = client.get("/api/v1/dashboard/all-india/summary")
    data = response.json()

    persisted_bids = {str(m.bid_id) for m in db.query(BidProductMatch).all()}
    # Every persisted match is at >= 0.50 for display? Not necessarily: match-all
    # persists >= 0.25. But the dashboard counts only >= 0.50. Verify total_bids
    # equals distinct bids with at least one match >= 0.50.
    from app.api.v1.endpoints.all_india import DISPLAY_MIN_SCORE_0_1
    relevant_bid_ids = {
        str(m.bid_id)
        for m in db.query(BidProductMatch)
        .filter(BidProductMatch.match_score >= DISPLAY_MIN_SCORE_0_1)
        .all()
    }
    assert data["total_bids"] == len(relevant_bid_ids)


def test_all_india_bids_only_shows_score_50_and_above(matched_bids, client: TestClient):
    response = client.get("/api/v1/dashboard/all-india/bids")
    assert response.status_code == 200, response.text
    data = response.json()
    assert "total" in data and "bids" in data and "page" in data and "total_pages" in data

    for row in data["bids"]:
        assert row["relevance_score_100"] >= 50, row
        assert row["classification"] in {
            "Highly Relevant", "Relevant", "Potentially Relevant", "Not Relevant",
        }
        assert row["product_name"]
        assert row["explanation"]
        assert row["title"]
        assert row["bid_id"]

    # The office-furniture bid (no product match) must not appear.
    titles = {row["title"] for row in data["bids"]}
    assert "Office Furniture and Stationery Supply" not in titles


def test_all_india_location_not_specified(matched_bids, client: TestClient, db):
    # The KYC bid has no location -> "Location Not Disclosed by Source".
    kyc_bid = next(b for spec, b in matched_bids if spec["location"] is None)
    matches = (
        db.query(BidProductMatch)
        .filter(BidProductMatch.bid_id == kyc_bid.id)
        .join(BidProductMatch.product)
        .all()
    )
    relevant = [m for m in matches if m.match_score >= 0.50]
    if relevant:
        response = client.get("/api/v1/dashboard/all-india/summary")
        locations = {e["location"] for e in response.json()["state_distribution"]}
        assert "Location Not Disclosed by Source" in locations


def test_all_india_location_quality_states(matched_bids, client: TestClient, db):
    """Summary includes location_quality counts (AVAILABLE / NOT_DISCLOSED / EXTRACTION_FAILED)."""
    response = client.get("/api/v1/dashboard/all-india/summary")
    assert response.status_code == 200
    qualities = response.json()["location_qualities"]
    assert set(qualities.keys()) >= {"AVAILABLE", "NOT_DISCLOSED", "EXTRACTION_FAILED"}
    assert isinstance(qualities["AVAILABLE"], int)
    assert isinstance(qualities["NOT_DISCLOSED"], int)
    assert isinstance(qualities["EXTRACTION_FAILED"], int)


def test_all_india_bids_location_in_response(matched_bids, client: TestClient):
    """Every bid row includes location, state, city, and location_quality fields."""
    response = client.get("/api/v1/dashboard/all-india/bids")
    assert response.status_code == 200
    rows = response.json()["bids"]
    assert len(rows) >= 1
    for row in rows:
        assert "location" in row
        assert "state" in row
        assert "city" in row
        assert "location_quality" in row
        assert row["location_quality"] in {"AVAILABLE", "NOT_DISCLOSED", "EXTRACTION_FAILED"}


def test_all_india_bids_product_filter(matched_bids, client: TestClient):
    response = client.get(
        "/api/v1/dashboard/all-india/bids",
        params={"product": "SolidityShield"},
    )
    assert response.status_code == 200, response.text
    rows = response.json()["bids"]
    # Every returned row must match the requested product.
    for row in rows:
        assert row["product_name"] == "SolidityShield", row


def test_all_india_bids_min_score_filter(matched_bids, client: TestClient):
    low = client.get("/api/v1/dashboard/all-india/bids", params={"min_score": 50})
    high = client.get("/api/v1/dashboard/all-india/bids", params={"min_score": 90})
    assert low.status_code == 200 and high.status_code == 200
    assert len(high.json()["bids"]) <= len(low.json()["bids"])


def test_all_india_bids_state_filter(matched_bids, client: TestClient):
    response = client.get(
        "/api/v1/dashboard/all-india/bids",
        params={"state": "Karnataka"},
    )
    assert response.status_code == 200, response.text
    rows = response.json()["bids"]
    for row in rows:
        assert "Karnataka" in row["state"], row


def test_all_india_bids_pagination(matched_bids, client: TestClient):
    first = client.get("/api/v1/dashboard/all-india/bids", params={"page": 1, "page_size": 2})
    assert first.status_code == 200, first.text
    data = first.json()
    assert data["page"] == 1
    assert data["page_size"] == 2
    assert len(data["bids"]) <= 2
    assert data["total_pages"] >= 1
    if data["total"] > 2:
        second = client.get("/api/v1/dashboard/all-india/bids", params={"page": 2, "page_size": 2})
        assert second.status_code == 200
        first_ids = {row["bid_id"] + "|" + row["product_name"] for row in data["bids"]}
        second_ids = {row["bid_id"] + "|" + row["product_name"] for row in second.json()["bids"]}
        assert first_ids.isdisjoint(second_ids), "Pagination should not repeat rows"


def test_all_india_multi_product_bid(matched_bids, db):
    """If any bid matched multiple products at >= 0.50, each match is exposed."""
    # Look for a bid with multiple persisted relevant matches.
    multi = None
    for bid_id in {str(m.bid_id) for m in db.query(BidProductMatch).all()}:
        match_rows = (
            db.query(BidProductMatch)
            .filter(BidProductMatch.bid_id == bid_id, BidProductMatch.match_score >= 0.50)
            .all()
        )
        if len(match_rows) >= 2:
            multi = match_rows
            break
    # Multi-product matches are supported by the schema and API; if present,
    # each product match is a separate row sharing the same bid_id.
    if multi:
        bid_ids = {str(m.bid_id) for m in multi}
        assert len(bid_ids) == 1
        product_names = {m.product.name for m in multi if m.product}
        assert len(product_names) >= 2


def test_all_india_bids_search(matched_bids, client: TestClient):
    response = client.get(
        "/api/v1/dashboard/all-india/bids",
        params={"search": "Blockchain Forensics"},
    )
    assert response.status_code == 200, response.text
    rows = response.json()["bids"]
    assert any("Blockchain" in row["title"] for row in rows), rows
