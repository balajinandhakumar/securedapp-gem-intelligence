"""
Product management tests: create, read, update, deactivate and the guarantee
that product knowledge actually drives bid matching.
"""
import pytest

from app.db.seed_knowledge import (
    PRODUCTS_KNOWLEDGE,
    bootstrap_product_knowledge,
    seed_product_knowledge,
)
from app.models.analysis import BidAnalysis, BidProductMatch
from app.models.bid import Bid
from app.models.product import (
    Product,
    ProductCapability,
    ProductCategory,
    ProductKeyword,
    ProductTechnology,
)
from app.models.product import Product as ProductModel
from app.seed import OFFICIAL_SECUREDAPP_PRODUCTS
from app.services.intelligence import match_bid_against_products


def test_seed_products_directly(db):
    from app.seed import OFFICIAL_SECUREDAPP_PRODUCTS
    for name in OFFICIAL_SECUREDAPP_PRODUCTS:
        product = Product(name=name, active=True)
        db.add(product)
    db.commit()

    products = db.query(Product).all()
    assert len(products) == 11
    product_names = [p.name for p in products]
    for expected_name in OFFICIAL_SECUREDAPP_PRODUCTS:
        assert expected_name in product_names


def test_product_api_create_and_read(client):
    # Create product
    payload = {"name": "TestProduct1", "description": "Test product description", "priority": 5}
    response = client.post("/api/v1/products", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "TestProduct1"
    assert data["description"] == "Test product description"
    assert data["priority"] == 5
    product_id = data["id"]

    # Read product
    get_res = client.get(f"/api/v1/products/{product_id}")
    assert get_res.status_code == 200
    assert get_res.json()["name"] == "TestProduct1"

    # Add capability
    cap_payload = {"name": "Audit Scanning", "description": "Scans code for vulnerabilities", "weight": 1.5}
    cap_res = client.post(f"/api/v1/products/{product_id}/capabilities", json=cap_payload)
    assert cap_res.status_code == 201
    cap_data = cap_res.json()
    assert cap_data["name"] == "Audit Scanning"
    assert cap_data["weight"] == 1.5


# ---------------------------------------------------------------------------
# Create product with a full knowledge vector
# ---------------------------------------------------------------------------
def test_create_product_with_knowledge_vector(client, db):
    payload = {
        "name": "ThreatMesh",
        "description": "Continuous attack-surface monitoring for web3 estates.",
        "priority": 7,
        "capabilities": [
            {"name": "Attack surface monitoring", "description": "Continuous scanning", "weight": 1.0},
        ],
        "keywords": [
            {"keyword": "attack surface", "weight": 1.0, "type": "positive_signal"},
            {"keyword": "exposure monitoring", "weight": 0.8, "type": "positive_signal"},
            {"keyword": "pentest engagement", "weight": -0.5, "type": "exclusion"},
        ],
        "technologies": [{"technology": "Attack Surface Management"}],
        "categories": [{"category": "Cybersecurity"}],
    }
    res = client.post("/api/v1/products", json=payload)
    assert res.status_code == 201
    body = res.json()

    assert len(body["capabilities"]) == 1
    assert len(body["keywords"]) == 3
    assert len(body["technologies"]) == 1
    assert len(body["categories"]) == 1
    assert body["active"] is True

    # Persisted in the database, not just echoed back.
    product = db.query(Product).filter(Product.name == "ThreatMesh").first()
    assert product is not None
    assert db.query(ProductCapability).filter(ProductCapability.product_id == product.id).count() == 1
    assert db.query(ProductKeyword).filter(ProductKeyword.product_id == product.id).count() == 3
    assert db.query(ProductTechnology).filter(ProductTechnology.product_id == product.id).count() == 1
    assert db.query(ProductCategory).filter(ProductCategory.product_id == product.id).count() == 1


def test_new_product_is_available_to_matching_engine(client, db):
    res = client.post(
        "/api/v1/products",
        json={
            "name": "ThreatMesh",
            "description": "Continuous attack-surface monitoring.",
            "keywords": [
                {"keyword": "attack surface", "weight": 1.0, "type": "positive_signal"},
            ],
            "capabilities": [
                {"name": "Attack surface monitoring", "weight": 1.0},
            ],
        },
    )
    assert res.status_code == 201

    bid = Bid(
        title="Attack surface monitoring for blockchain services",
        scope_of_work="Deploy continuous attack surface monitoring across our web3 estate.",
    )
    db.add(bid)
    db.commit()

    results = match_bid_against_products(db, bid)
    assert any(r.product_name == "ThreatMesh" for r in results)


# ---------------------------------------------------------------------------
# Read / list
# ---------------------------------------------------------------------------
def test_list_products_returns_full_catalogue(client, db):
    seed_product_knowledge(db)
    res = client.get("/api/v1/products")
    assert res.status_code == 200
    assert len(res.json()) == 11


def test_list_products_supports_active_filter_and_search(client, db):
    seed_product_knowledge(db)
    sol = db.query(Product).filter(Product.name == "SolidityShield").first()
    sol.active = False
    db.commit()

    active_only = client.get("/api/v1/products", params={"active": True}).json()
    assert "SolidityShield" not in {p["name"] for p in active_only}

    inactive_only = client.get("/api/v1/products", params={"active": False}).json()
    assert {p["name"] for p in inactive_only} == {"SolidityShield"}

    search = client.get("/api/v1/products", params={"search": "secure"}).json()
    assert search
    # The endpoint searches both name and description; verify each result
    # matches on at least one of those fields (which is the correct behaviour).
    assert all(
        "secure" in p["name"].lower() or "secure" in (p.get("description") or "").lower()
        for p in search
    )


def test_get_unknown_product_returns_404(client):
    res = client.get("/api/v1/products/00000000-0000-0000-0000-000000000000")
    assert res.status_code == 404


# ---------------------------------------------------------------------------
# Update product
# ---------------------------------------------------------------------------
def test_update_product_persists_scalar_and_knowledge_changes(client, db):
    created = client.post(
        "/api/v1/products",
        json={
            "name": "ThreatMesh",
            "description": "Original description",
            "priority": 3,
            "capabilities": [{"name": "Attack surface monitoring", "weight": 1.0}],
            "keywords": [{"keyword": "attack surface", "weight": 1.0, "type": "positive_signal"}],
        },
    ).json()

    res = client.put(
        f"/api/v1/products/{created['id']}",
        json={
            "name": "ThreatMesh Pro",
            "description": "Updated description",
            "priority": 9,
            "capabilities": [
                {"name": "Attack surface monitoring", "weight": 1.0},
                {"name": "Breach simulation", "weight": 0.9},
            ],
            "keywords": [
                {"keyword": "attack surface", "weight": 1.0, "type": "positive_signal"},
                {"keyword": "breach simulation", "weight": 1.0, "type": "positive_signal"},
            ],
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert body["name"] == "ThreatMesh Pro"
    assert body["description"] == "Updated description"
    assert body["priority"] == 9
    assert len(body["capabilities"]) == 2
    assert len(body["keywords"]) == 2

    # Change is committed to the database.
    db.expire_all()
    product = db.query(Product).filter(Product.name == "ThreatMesh Pro").first()
    assert product is not None
    assert product.priority == 9
    assert db.query(ProductCapability).filter(ProductCapability.product_id == product.id).count() == 2
    assert db.query(ProductKeyword).filter(ProductKeyword.product_id == product.id).count() == 2
    assert db.query(Product).filter(Product.name == "ThreatMesh").first() is None


def test_partial_update_leaves_untouched_fields_and_knowledge_intact(client, db):
    created = client.post(
        "/api/v1/products",
        json={
            "name": "ThreatMesh",
            "description": "Original description",
            "priority": 3,
            "capabilities": [{"name": "Attack surface monitoring", "weight": 1.0}],
            "keywords": [{"keyword": "attack surface", "weight": 1.0, "type": "positive_signal"}],
            "technologies": [{"technology": "ASM"}],
        },
    ).json()

    res = client.put(f"/api/v1/products/{created['id']}", json={"description": "Only the description moved"})
    assert res.status_code == 200
    body = res.json()

    assert body["name"] == "ThreatMesh"
    assert body["description"] == "Only the description moved"
    assert body["priority"] == 3
    assert len(body["capabilities"]) == 1
    assert len(body["keywords"]) == 1
    assert len(body["technologies"]) == 1


def test_updated_knowledge_is_used_for_future_bid_matching(client, db):
    created = client.post(
        "/api/v1/products",
        json={
            "name": "ThreatMesh",
            "description": "Monitoring product.",
            "capabilities": [{"name": "Attack surface monitoring", "weight": 1.0}],
            "keywords": [{"keyword": "attack surface", "weight": 1.0, "type": "positive_signal"}],
        },
    ).json()

    bid = Bid(
        title="Supply of Managed Firewall Appliances",
        scope_of_work="Deployment and management of perimeter firewalls.",
    )
    db.add(bid)
    db.commit()

    before = next(
        r for r in match_bid_against_products(db, bid) if r.product_name == "ThreatMesh"
    )
    assert before.relevance_score == 0.0

    # Admin teaches the product a new capability through the API.
    res = client.put(
        f"/api/v1/products/{created['id']}",
        json={
            "capabilities": [
                {"name": "Attack surface monitoring", "weight": 1.0},
                {"name": "Managed firewall", "weight": 1.0},
            ],
            "keywords": [
                {"keyword": "attack surface", "weight": 1.0, "type": "positive_signal"},
                {"keyword": "perimeter firewall", "weight": 1.0, "type": "positive_signal"},
            ],
        },
    )
    assert res.status_code == 200

    after = next(
        r for r in match_bid_against_products(db, bid) if r.product_name == "ThreatMesh"
    )
    assert after.relevance_score > before.relevance_score
    assert after.match_state != "NO_MATCH"


# ---------------------------------------------------------------------------
# Deactivate / remove
# ---------------------------------------------------------------------------
def test_deactivate_product_stops_it_participating_in_matching(client, db):
    created = client.post(
        "/api/v1/products",
        json={
            "name": "ThreatMesh",
            "keywords": [{"keyword": "attack surface", "weight": 1.0, "type": "positive_signal"}],
        },
    ).json()

    res = client.delete(f"/api/v1/products/{created['id']}")
    assert res.status_code == 200
    assert res.json()["active"] is False

    db.expire_all()
    assert db.query(Product).filter(Product.id == created["id"]).first().active is False

    bid = Bid(title="Attack surface monitoring platform", scope_of_work="Attack surface monitoring rollout.")
    db.add(bid)
    db.commit()

    results = match_bid_against_products(db, bid)
    assert "ThreatMesh" not in {r.product_name for r in results}


def test_deactivated_product_remains_readable_for_history(client, db):
    created = client.post("/api/v1/products", json={"name": "ThreatMesh"}).json()
    assert client.delete(f"/api/v1/products/{created['id']}").status_code == 200

    res = client.get(f"/api/v1/products/{created['id']}")
    assert res.status_code == 200
    assert res.json()["name"] == "ThreatMesh"
    assert res.json()["active"] is False


def test_inactive_product_can_be_reactivated_and_matches_again(client, db):
    created = client.post(
        "/api/v1/products",
        json={
            "name": "ThreatMesh",
            "keywords": [{"keyword": "attack surface", "weight": 1.0, "type": "positive_signal"}],
        },
    ).json()
    client.delete(f"/api/v1/products/{created['id']}")

    res = client.put(f"/api/v1/products/{created['id']}", json={"active": True})
    assert res.status_code == 200
    assert res.json()["active"] is True

    bid = Bid(title="Attack surface monitoring platform", scope_of_work="Attack surface monitoring rollout.")
    db.add(bid)
    db.commit()
    assert "ThreatMesh" in {r.product_name for r in match_bid_against_products(db, bid)}


def test_hard_delete_refused_when_historical_matches_reference_product(client, db):
    created = client.post("/api/v1/products", json={"name": "ThreatMesh"}).json()
    product_id = created["id"]

    bid = Bid(title="Attack surface monitoring", scope_of_work="Attack surface monitoring.")
    db.add(bid)
    db.commit()
    db.add(
        BidProductMatch(
            bid_id=bid.id,
            product_id=product_id,
            match_score=0.9,
            match_type="DETERMINISTIC",
            confidence=0.8,
        )
    )
    db.commit()

    res = client.delete(f"/api/v1/products/{product_id}", params={"hard": True})
    assert res.status_code == 409
    assert "historical" in res.json()["detail"].lower()

    # History is intact.
    assert db.query(BidProductMatch).filter(BidProductMatch.product_id == product_id).count() == 1

    # Soft delete still works and keeps the historical row.
    soft = client.delete(f"/api/v1/products/{product_id}")
    assert soft.status_code == 200
    assert db.query(BidProductMatch).filter(BidProductMatch.product_id == product_id).count() == 1


def test_hard_delete_refused_when_only_a_json_analysis_snapshot_references_product(client, db):
    """
    `bid_analysis.product_matches` is a JSON snapshot with no foreign key, so a
    stored analysis alone must still block a permanent delete.
    """
    created = client.post("/api/v1/products", json={"name": "ThreatMesh"}).json()
    product_id = created["id"]

    bid = Bid(title="Attack surface monitoring", scope_of_work="Attack surface monitoring.")
    db.add(bid)
    db.commit()
    db.add(
        BidAnalysis(
            bid_id=bid.id,
            engine_version="test",
            model_used="test",
            product_matches=[
                {"product_id": product_id, "product_name": "ThreatMesh", "match_state": "MATCH"}
            ],
        )
    )
    db.commit()

    res = client.delete(f"/api/v1/products/{product_id}", params={"hard": True})
    assert res.status_code == 409
    assert "bid analysis" in res.json()["detail"].lower()
    assert client.get(f"/api/v1/products/{product_id}").status_code == 200


def test_hard_delete_allowed_when_no_history_exists(client, db):
    created = client.post("/api/v1/products", json={"name": "ThreatMesh"}).json()
    res = client.delete(f"/api/v1/products/{created['id']}", params={"hard": True})
    assert res.status_code == 200
    assert res.json()["deleted"] is True
    assert client.get(f"/api/v1/products/{created['id']}").status_code == 404


def test_deactivating_every_product_does_not_resurrect_them(client, db):
    created = client.post("/api/v1/products", json={"name": "ThreatMesh"}).json()
    assert client.delete(f"/api/v1/products/{created['id']}").status_code == 200

    bid = Bid(title="Anything at all", scope_of_work="Office furniture supply.")
    db.add(bid)
    db.commit()

    assert match_bid_against_products(db, bid) == []


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
def test_duplicate_product_name_returns_409(client, db):
    payload = {"name": "ThreatMesh", "description": "First"}
    assert client.post("/api/v1/products", json=payload).status_code == 201

    res = client.post("/api/v1/products", json={"name": "ThreatMesh", "description": "Second"})
    assert res.status_code == 409
    assert "already exists" in res.json()["detail"]


def test_duplicate_name_on_rename_returns_409(client, db):
    client.post("/api/v1/products", json={"name": "ThreatMesh"})
    second = client.post("/api/v1/products", json={"name": "ThreatGrid"}).json()

    res = client.put(f"/api/v1/products/{second['id']}", json={"name": "ThreatMesh"})
    assert res.status_code == 409


def test_rename_to_own_name_is_allowed(client, db):
    created = client.post("/api/v1/products", json={"name": "ThreatMesh"}).json()
    res = client.put(f"/api/v1/products/{created['id']}", json={"name": "ThreatMesh", "priority": 4})
    assert res.status_code == 200
    assert res.json()["priority"] == 4


@pytest.mark.parametrize(
    "payload",
    [
        {"name": "   "},
        {"name": ""},
        {"name": "Valid", "priority": -1},
    ],
)
def test_invalid_product_payloads_are_rejected(client, db, payload):
    assert client.post("/api/v1/products", json=payload).status_code == 422


def test_invalid_keyword_weight_and_type_are_rejected(client, db):
    created = client.post("/api/v1/products", json={"name": "ThreatMesh"}).json()

    bad_type = client.post(
        f"/api/v1/products/{created['id']}/keywords",
        json={"keyword": "thing", "type": "not-a-real-type"},
    )
    assert bad_type.status_code == 422

    bad_weight = client.post(
        f"/api/v1/products/{created['id']}/keywords",
        json={"keyword": "thing", "weight": -1.0, "type": "positive_signal"},
    )
    assert bad_weight.status_code == 422

    ok_exclusion = client.post(
        f"/api/v1/products/{created['id']}/keywords",
        json={"keyword": "out of scope thing", "weight": -0.5, "type": "exclusion"},
    )
    assert ok_exclusion.status_code == 201


def test_duplicate_knowledge_entries_are_rejected(client, db):
    created = client.post("/api/v1/products", json={"name": "ThreatMesh"}).json()
    pid = created["id"]

    assert client.post(f"/api/v1/products/{pid}/capabilities", json={"name": "Cap One"}).status_code == 201
    assert client.post(f"/api/v1/products/{pid}/capabilities", json={"name": "cap one"}).status_code == 409

    assert client.post(f"/api/v1/products/{pid}/keywords", json={"keyword": "kw"}).status_code == 201
    assert client.post(f"/api/v1/products/{pid}/keywords", json={"keyword": "KW"}).status_code == 409

    assert client.post(f"/api/v1/products/{pid}/technologies", json={"technology": "Tech"}).status_code == 201
    assert client.post(f"/api/v1/products/{pid}/technologies", json={"technology": "tech"}).status_code == 409

    assert client.post(f"/api/v1/products/{pid}/categories", json={"category": "Cat"}).status_code == 201
    assert client.post(f"/api/v1/products/{pid}/categories", json={"category": "cat"}).status_code == 409


def test_duplicate_entries_inside_one_payload_are_rejected(client, db):
    res = client.post(
        "/api/v1/products",
        json={
            "name": "ThreatMesh",
            "capabilities": [{"name": "Cap"}, {"name": "cap"}],
        },
    )
    assert res.status_code == 400
    assert "duplicate" in res.json()["detail"].lower()


def test_knowledge_add_endpoints_return_404_for_unknown_product(client, db):
    missing = "00000000-0000-0000-0000-000000000000"
    assert client.post(f"/api/v1/products/{missing}/capabilities", json={"name": "x"}).status_code == 404
    assert client.post(f"/api/v1/products/{missing}/keywords", json={"keyword": "x"}).status_code == 404
    assert client.post(f"/api/v1/products/{missing}/technologies", json={"technology": "x"}).status_code == 404
    assert client.post(f"/api/v1/products/{missing}/categories", json={"category": "x"}).status_code == 404
    assert client.put(f"/api/v1/products/{missing}", json={"name": "x"}).status_code == 404
    assert client.delete(f"/api/v1/products/{missing}").status_code == 404


# ---------------------------------------------------------------------------
# Seed bootstrap
# ---------------------------------------------------------------------------
def test_bootstrap_seeds_all_eleven_products_with_knowledge(db):
    result = bootstrap_product_knowledge(db)
    assert result["created"] == 11
    assert result["backfilled"] == 0
    assert result["preserved"] == 0

    products = db.query(Product).all()
    assert len(products) == 11
    assert all(p.description for p in products)
    assert db.query(ProductCapability).count() > 0
    assert db.query(ProductKeyword).count() > 0
    assert db.query(ProductTechnology).count() > 0
    assert db.query(ProductCategory).count() > 0


def test_bootstrap_is_idempotent_and_creates_no_duplicates(db):
    bootstrap_product_knowledge(db)
    caps_after_first = db.query(ProductCapability).count()

    result = bootstrap_product_knowledge(db)
    assert result["created"] == 0
    assert result["backfilled"] == 0
    assert result["preserved"] == 11

    assert db.query(Product).count() == 11
    assert db.query(ProductCapability).count() == caps_after_first


def test_bootstrap_repairs_the_legacy_name_only_seed(db):
    # Reproduce the legacy deployment seed: names only, no knowledge vectors.
    for name in OFFICIAL_SECUREDAPP_PRODUCTS:
        db.add(Product(name=name, active=True, description=None, priority=0))
    db.commit()

    assert db.query(ProductCapability).count() == 0

    result = bootstrap_product_knowledge(db)
    assert result["backfilled"] == 11

    assert db.query(Product).count() == 11
    assert all(p.description for p in db.query(Product).all())
    assert db.query(ProductCapability).count() > 0

    # And the repaired catalogue actually drives matching.
    bid = Bid(
        title="Smart Contract Security Audit and Manual Expert Review",
        scope_of_work="Expert security review of Solidity smart contracts.",
    )
    db.add(bid)
    db.commit()
    top = match_bid_against_products(db, bid)[0]
    assert top.product_name == "SolidityShield"
    assert top.match_state == "MATCH"


def test_bootstrap_preserves_admin_edits(db):
    bootstrap_product_knowledge(db)

    product = db.query(ProductModel).filter(ProductModel.name == "SecurePad").first()
    product.description = "Edited by an administrator"
    product.priority = 42
    db.query(ProductCapability).filter(ProductCapability.product_id == product.id).delete()
    db.add(
        ProductCapability(
            product_id=product.id,
            name="Admin Added Capability",
            description="Only the administrator knows about this",
            weight=1.0,
            active=True,
        )
    )
    db.commit()

    result = bootstrap_product_knowledge(db)
    assert result["preserved"] == 11
    assert result["backfilled"] == 0

    db.expire_all()
    product = db.query(ProductModel).filter(ProductModel.name == "SecurePad").first()
    assert product.description == "Edited by an administrator"
    assert product.priority == 42

    capabilities = db.query(ProductCapability).filter(ProductCapability.product_id == product.id).all()
    assert [c.name for c in capabilities] == ["Admin Added Capability"]


def test_knowledge_definitions_cover_every_official_product():
    names = {info["name"] for info in PRODUCTS_KNOWLEDGE}
    assert names == set(OFFICIAL_SECUREDAPP_PRODUCTS)
    for info in PRODUCTS_KNOWLEDGE:
        assert info["capabilities"], f"{info['name']} has no capabilities"
        assert info["keywords"], f"{info['name']} has no keywords"
        assert info["technologies"], f"{info['name']} has no technologies"
        assert info["categories"], f"{info['name']} has no categories"


# ---------------------------------------------------------------------------
# Keyword add / remove / update lifecycle (Issue 3 — Product Keyword Management)
# ---------------------------------------------------------------------------

def test_keyword_add_then_remove_persists(client, db):
    """Add a keyword to a product, then remove it — both persist in the DB."""
    created = client.post("/api/v1/products", json={"name": "KwLifecycleTest", "description": "test"}).json()
    pid = created["id"]

    # Add keyword
    add_res = client.post(f"/api/v1/products/{pid}/keywords", json={"keyword": "test keyword alpha", "weight": 1.5, "type": "keyword"})
    assert add_res.status_code == 201, add_res.text
    kw_id = add_res.json()["id"]

    # Verify persisted
    from app.models.product import ProductKeyword
    from uuid import UUID
    kw = db.query(ProductKeyword).filter(ProductKeyword.id == kw_id).first()
    assert kw is not None
    assert kw.keyword == "test keyword alpha"
    assert kw.product_id == UUID(pid)

    # Remove keyword
    del_res = client.delete(f"/api/v1/products/{pid}/keywords/{kw_id}")
    assert del_res.status_code == 204, del_res.text

    # Verify removed
    kw_after = db.query(ProductKeyword).filter(ProductKeyword.id == kw_id).first()
    assert kw_after is None


def test_keyword_removal_affects_only_selected_product(client, db):
    """Removing a keyword from product A must not touch product B's keywords."""
    pa = client.post("/api/v1/products", json={"name": "KwProductA"}).json()
    pb = client.post("/api/v1/products", json={"name": "KwProductB"}).json()

    ka = client.post(f"/api/v1/products/{pa['id']}/keywords", json={"keyword": "shared keyword"}).json()
    kb = client.post(f"/api/v1/products/{pb['id']}/keywords", json={"keyword": "shared keyword"}).json()

    # Remove from A only
    res = client.delete(f"/api/v1/products/{pa['id']}/keywords/{ka['id']}")
    assert res.status_code == 204

    # B still has its keyword
    from app.models.product import ProductKeyword
    b_kws = db.query(ProductKeyword).filter(ProductKeyword.product_id == pb["id"]).all()
    assert len(b_kws) == 1
    assert b_kws[0].keyword == "shared keyword"

    # A has none
    a_kws = db.query(ProductKeyword).filter(ProductKeyword.product_id == pa["id"]).all()
    assert len(a_kws) == 0


def test_duplicate_keyword_rejection_case_insensitive(client, db):
    """Adding the same keyword with different case returns 409."""
    created = client.post("/api/v1/products", json={"name": "KwDupTest"}).json()
    pid = created["id"]

    assert client.post(f"/api/v1/products/{pid}/keywords", json={"keyword": "Vulnerability Scan"}).status_code == 201
    assert client.post(f"/api/v1/products/{pid}/keywords", json={"keyword": "vulnerability scan"}).status_code == 409
    assert client.post(f"/api/v1/products/{pid}/keywords", json={"keyword": "  VULNERABILITY SCAN  "}).status_code == 409


def test_update_keyword_endpoint(client, db):
    """PUT /{product_id}/keywords/{keyword_id} updates the keyword."""
    created = client.post("/api/v1/products", json={"name": "KwUpdateTest"}).json()
    pid = created["id"]

    add_res = client.post(f"/api/v1/products/{pid}/keywords", json={"keyword": "old keyword"}).json()
    kw_id = add_res["id"]

    upd_res = client.put(f"/api/v1/products/{pid}/keywords/{kw_id}", json={"keyword": "new keyword", "weight": 2.0})
    assert upd_res.status_code == 200, upd_res.text
    assert upd_res.json()["keyword"] == "new keyword"
    assert upd_res.json()["weight"] == 2.0

    # Verify persisted
    from app.models.product import ProductKeyword
    kw = db.query(ProductKeyword).filter(ProductKeyword.id == kw_id).first()
    assert kw.keyword == "new keyword"
    assert kw.weight == 2.0


def test_delete_unknown_keyword_returns_404(client, db):
    """DELETE with a keyword_id not on the product returns 404."""
    created = client.post("/api/v1/products", json={"name": "Kw404Test"}).json()
    pid = created["id"]

    missing_kw = "00000000-0000-0000-0000-000000000000"
    res = client.delete(f"/api/v1/products/{pid}/keywords/{missing_kw}")
    assert res.status_code == 404, res.text
    assert "not found" in res.json()["detail"].lower()


def test_add_keyword_empty_string_rejected(client, db):
    """Adding an empty keyword is rejected with 422."""
    created = client.post("/api/v1/products", json={"name": "KwEmptyTest"}).json()
    pid = created["id"]

    res = client.post(f"/api/v1/products/{pid}/keywords", json={"keyword": "   "})
    assert res.status_code == 422, res.text
