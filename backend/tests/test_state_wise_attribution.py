"""
Phase 8 backend tests: state-wise attribution (source_id) and summary API.

Covers:
  * Bids are attributed to a state via Bid.source_id -> DataSource.id, so portal
    name variants (e.g. "Jammu & Kashmir" vs "Jammu and Kashmir") no longer
    split one state across two rows.
  * GET /api/v1/bids/state-wise/summary returns per-state collected/matched
    counts, last run info, and source status.
  * GET /api/v1/bids/state-wise include_no_match toggles collected vs matched
    views.

Tests use the conftest in-memory SQLite DB (StaticPool, shared across
connections) and the existing TestClient; no live network.
"""

from __future__ import annotations

from uuid import uuid4

from app.models.bid import Bid
from app.models.source import DataSource
from app.models.analysis import BidProductMatch
from app.models.product import Product


def _seed(db):
    # Two data sources for the same state under variant display names.
    jk_amp = DataSource(
        source_id="jammu_kashmir",
        name="Jammu and Kashmir e-Procurement",
        source_type="html_listing",
        adapter_key="html_listing",
        config={},
        enabled=True,
        status="SUCCESS",
    )
    db.add(jk_amp)
    db.flush()

    assam = DataSource(
        source_id="assam",
        name="Assam e-Procurement",
        source_type="html_listing",
        adapter_key="html_listing",
        config={},
        enabled=True,
        status="SUCCESS",
    )
    db.add(assam)
    db.flush()

    prod = Product(
        id=uuid4(),
        name="Consulting Services",
        description="Consulting",
        capabilities=[],
        keywords=[],
        technologies=[],
        categories=[],
    )
    db.add(prod)
    db.flush()

    # J&K bid under the "&" variant name -> attributed to jammu_kashmir via source_id.
    b1 = Bid(
        id=uuid4(),
        bid_number="JK-1",
        title="J&K consulting tender",
        source_name="Jammu & Kashmir e-Procurement",
        source_id=jk_amp.id,
        status="NEW",
        matching_status="COMPLETED",
    )
    db.add(b1)
    # J&K bid under the "and" variant name -> same state via source_id.
    b2 = Bid(
        id=uuid4(),
        bid_number="JK-2",
        title="J&K consulting tender 2",
        source_name="Jammu and Kashmir e-Procurement",
        source_id=jk_amp.id,
        status="NEW",
        matching_status="COMPLETED",
    )
    db.add(b2)
    # Assam bid with a product match.
    b3 = Bid(
        id=uuid4(),
        bid_number="AS-1",
        title="Assam consulting tender",
        source_name="Assam e-Procurement",
        source_id=assam.id,
        status="NEW",
        matching_status="COMPLETED",
    )
    db.add(b3)
    db.flush()

    db.add(
        BidProductMatch(
            bid_id=b3.id,
            product_id=prod.id,
            match_score=0.5,
            match_type="DETERMINISTIC_PHASE3",
            confidence=0.9,
            evidence={
                "match_state": "POSSIBLE_MATCH",
                "signals": [],
                "reason": "x",
            },
        )
    )
    db.commit()
    return {"jk": jk_amp.id, "assam": assam.id, "prod": prod.id, "b3": b3.id}


def test_state_wise_summary_counts(db, client):
    _seed(db)
    resp = client.get("/api/v1/bids/state-wise/summary")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    states = {s["source_id"]: s for s in body["states"]}
    assert states["jammu_kashmir"]["collected"] == 2
    assert states["jammu_kashmir"]["matched"] == 0
    assert states["jammu_kashmir"]["status"] == "SUCCESS"
    assert states["assam"]["collected"] == 1
    assert states["assam"]["matched"] == 1


def test_state_wise_collected_includes_no_match(db, client):
    _seed(db)
    # Collected view: include_no_match=true -> both J&K bids.
    resp = client.get(
        "/api/v1/bids/state-wise?state=jammu_kashmir&include_no_match=true"
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["total"] == 2

    # Assam collected view includes its one bid.
    resp = client.get("/api/v1/bids/state-wise?state=assam&include_no_match=true")
    assert resp.json()["total"] == 1


def test_state_wise_matched_only(db, client):
    _seed(db)
    # Matched view (default): only bids with at least one product match.
    resp = client.get("/api/v1/bids/state-wise?state=assam")
    assert resp.status_code == 200, resp.text
    assert resp.json()["total"] == 1
    assert resp.json()["bids"][0]["matched_product"] == "Consulting Services"

    # J&K has no matches -> matched view is empty.
    resp = client.get("/api/v1/bids/state-wise?state=jammu_kashmir")
    assert resp.json()["total"] == 0


def test_state_wise_attribution_not_split_by_name_variant(db, client):
    """Both J&K name variants roll up to one state via source_id join."""
    _seed(db)
    resp = client.get(
        "/api/v1/bids/state-wise?state=jammu_kashmir&include_no_match=true"
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 2
    assert all(b["state_id"] == "jammu_kashmir" for b in body["bids"])
    assert {b["bid_number"] for b in body["bids"]} == {"JK-1", "JK-2"}
