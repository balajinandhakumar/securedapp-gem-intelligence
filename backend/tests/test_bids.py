def test_create_and_list_bids(client):
    bid_payload = {
        "gem_bid_id": "GEM/2026/B/99999",
        "bid_number": "GEM-99999",
        "title": "Cybersecurity Vulnerability Assessment & Penetration Testing",
        "organisation": "Ministry of Electronics & Information Technology",
        "department": "CERT-In",
        "category": "IT Security Services",
        "estimated_value": 5000000.00,
        "currency": "INR",
        "scope_of_work": "Comprehensive VAPT of web applications and mobile apps.",
        "status": "NEW"
    }

    create_res = client.post("/api/v1/bids", json=bid_payload)
    assert create_res.status_code == 201
    created_data = create_res.json()
    assert created_data["title"] == bid_payload["title"]
    assert created_data["gem_bid_id"] == "GEM/2026/B/99999"
    assert created_data["content_hash"] is not None

    bid_id = created_data["id"]

    # Get single bid
    get_res = client.get(f"/api/v1/bids/{bid_id}")
    assert get_res.status_code == 200
    assert get_res.json()["bid_number"] == "GEM-99999"

    # List bids
    list_res = client.get("/api/v1/bids")
    assert list_res.status_code == 200
    assert len(list_res.json()) >= 1


def test_bid_detail_exposes_boq_provenance(client, db):
    """GET /bids/{id} surfaces persisted BoQ evidence and its provenance."""
    from datetime import datetime, timezone

    from app.models.bid import Bid

    retrieved = datetime(2026, 10, 12, 9, 30, tzinfo=timezone.utc)
    checked = datetime(2026, 10, 12, 9, 31, tzinfo=timezone.utc)
    bid = Bid(
        gem_bid_id="GEM/2026/B/BOQ-1",
        title="Supply of enterprise security appliances",
        source_url="https://bidplus.gem.gov.in/showbidDocument/1",
        boq_checked_at=checked,
        boq_items={
            "items": [
                {
                    "item_number": "1",
                    "title": "Next-Generation Firewall",
                    "description": "NG firewall with IPS",
                    "quantity": "2",
                    "unit": "Nos",
                }
            ],
            "item_count": 1,
            "source_url": "https://bidplus.gem.gov.in/showbiddocument/1/boq",
            "retrieved_at": retrieved.isoformat(),
        },
    )
    db.add(bid)
    db.commit()

    res = client.get(f"/api/v1/bids/{bid.id}")
    assert res.status_code == 200
    body = res.json()
    assert body["boq_items"] is not None
    assert body["boq_items"]["item_count"] == 1
    assert body["boq_items"]["source_url"] == "https://bidplus.gem.gov.in/showbiddocument/1/boq"
    assert body["boq_items"]["items"][0]["title"] == "Next-Generation Firewall"
    assert body["boq_items"]["retrieved_at"] == retrieved.isoformat()
    assert body["boq_checked_at"] is not None


def test_bid_detail_handles_missing_boq(client, db):
    """A bid with no stored BoQ reports null provenance rather than erroring."""
    from app.models.bid import Bid

    bid = Bid(gem_bid_id="GEM/2026/B/NOBOQ", title="Plain procurement notice")
    db.add(bid)
    db.commit()

    res = client.get(f"/api/v1/bids/{bid.id}")
    assert res.status_code == 200
    body = res.json()
    assert body["boq_items"] is None
    assert body["boq_checked_at"] is None
