"""
Focused tests for human-review labelling.

They pin three things: accepted labels (relevant / irrelevant / uncertain) are
validated and normalized at the API boundary, malformed labels are rejected so
they can never pollute the evaluation set, and an identical resubmission is
idempotent so duplicate labels cannot inflate evaluation counts.
"""
from app.models.bid import Bid
from app.models.review import HumanReview


def _bid(db) -> Bid:
    bid = Bid(title="Label validation target")
    db.add(bid)
    db.commit()
    return bid


def test_invalid_relevance_labels_are_rejected(client, db):
    bid = _bid(db)
    url = f"/api/v1/bids/{bid.id}/review"

    for bad in ("MAYBE_NOT", "irrelevant", "", "   ", "RELEVANTISH"):
        res = client.post(url, json={"relevance_decision": bad})
        assert res.status_code == 422, f"expected rejection for {bad!r}"

    assert db.query(HumanReview).count() == 0


def test_lowercase_and_whitespace_labels_are_normalized(client, db):
    bid = _bid(db)

    res = client.post(
        f"/api/v1/bids/{bid.id}/review",
        json={"relevance_decision": "  relevant "},
    )

    assert res.status_code == 201
    assert res.json()["relevance_decision"] == "RELEVANT"


def test_uncertain_label_is_accepted_and_stored_as_maybe(client, db):
    bid = _bid(db)

    res = client.post(
        f"/api/v1/bids/{bid.id}/review",
        json={"relevance_decision": "maybe"},
    )

    assert res.status_code == 201
    assert res.json()["relevance_decision"] == "MAYBE"


def test_invalid_pursue_decision_is_rejected(client, db):
    bid = _bid(db)

    res = client.post(
        f"/api/v1/bids/{bid.id}/review",
        json={"relevance_decision": "RELEVANT", "pursue_decision": "MAYBE"},
    )

    assert res.status_code == 422
    assert db.query(HumanReview).count() == 0


def test_identical_resubmission_is_idempotent(client, db):
    bid = _bid(db)
    url = f"/api/v1/bids/{bid.id}/review"
    payload = {
        "relevance_decision": "RELEVANT",
        "pursue_decision": "PURSUE",
        "comments": "Strong fit.",
    }

    first = client.post(url, json=payload)
    second = client.post(url, json=payload)

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["id"] == second.json()["id"]
    stored = db.query(HumanReview).filter(HumanReview.bid_id == bid.id).count()
    assert stored == 1, "an identical resubmission must not add a row"


def test_changed_label_appends_history(client, db):
    bid = _bid(db)
    url = f"/api/v1/bids/{bid.id}/review"

    res1 = client.post(
        url,
        json={"relevance_decision": "RELEVANT", "comments": "First pass."},
    )
    res2 = client.post(
        url,
        json={"relevance_decision": "NOT_RELEVANT", "comments": "Second pass."},
    )

    assert res1.status_code == 201
    assert res2.status_code == 201
    assert res1.json()["id"] != res2.json()["id"]
    history = client.get(f"/api/v1/bids/{bid.id}/reviews").json()
    assert len(history) == 2
