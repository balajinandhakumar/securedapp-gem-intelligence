"""
Focused tests for explicit notification delivery status.

They pin the mapping between the stored ``status`` and the explicit
``delivery_state`` shown to users, and confirm the API never reports a queued
alert as delivered when no provider is configured.
"""
from datetime import datetime, timezone
from types import SimpleNamespace

from app.models.bid import Bid
from app.models.notification import Notification
from app.services.notification_delivery import (
    delivery_provider_configured,
    describe_delivery,
)


def test_describe_delivery_state_mapping():
    assert describe_delivery(SimpleNamespace(status="PENDING"))["delivery_state"] == "QUEUED"
    assert describe_delivery(SimpleNamespace(status="SENT"))["delivery_state"] == "DELIVERED"
    assert describe_delivery(SimpleNamespace(status="FAILED"))["delivery_state"] == "FAILED"
    # Unexpected status is surfaced verbatim rather than guessed.
    assert describe_delivery(SimpleNamespace(status="WEIRD"))["delivery_state"] == "WEIRD"


def test_no_provider_configured_in_this_build():
    assert delivery_provider_configured() is False
    note = describe_delivery(SimpleNamespace(status="PENDING"))["delivery_note"].lower()
    assert "not been dispatched" in note or "no delivery provider" in note


def test_notifications_endpoint_reports_queued_not_delivered(client, db):
    bid = Bid(title="High relevance security tender")
    db.add(bid)
    db.flush()
    db.add(
        Notification(
            bid_id=bid.id,
            channel="EMAIL",
            recipient="security-team@securedapp.com",
            notification_type="NEW_HIGH_RELEVANCE",
            deduplication_key=f"notif_{bid.id}_high_relevance",
            status="PENDING",
        )
    )
    db.commit()

    res = client.get("/api/v1/notifications")
    assert res.status_code == 200
    rows = res.json()
    assert len(rows) == 1
    row = rows[0]
    # Raw fields preserved for existing consumers.
    assert row["status"] == "PENDING"
    assert row["sent_at"] is None
    # Explicit derived delivery fields.
    assert row["delivery_state"] == "QUEUED"
    assert row["delivery_configured"] is False
    assert row["delivery_note"]


def test_notifications_endpoint_reports_delivered_when_status_sent(client, db):
    bid = Bid(title="Confirmed alert")
    db.add(bid)
    db.flush()
    db.add(
        Notification(
            bid_id=bid.id,
            channel="EMAIL",
            recipient="security-team@securedapp.com",
            notification_type="NEW_HIGH_RELEVANCE",
            deduplication_key=f"notif_{bid.id}_high_relevance",
            status="SENT",
            sent_at=datetime.now(timezone.utc),
        )
    )
    db.commit()

    rows = client.get("/api/v1/notifications").json()
    assert rows[0]["delivery_state"] == "DELIVERED"
    assert rows[0]["sent_at"] is not None
