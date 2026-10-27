"""
Focused tests for real SMTP notification delivery.

SMTP credentials are NOT present in this deployment, so the default path must
hold: queued, never sent, no connection opened. The configured path is
exercised against an in-process fake SMTP server -- no sockets, no real
mailbox, and therefore no claim of real delivery. Real delivery can only be
tested when actual credentials and a test recipient exist.
"""
import smtplib
from datetime import datetime, timedelta, timezone

from app.core.config import settings
from app.models.bid import Bid
from app.models.notification import Notification
from app.services import notification_delivery as nd


def _configure_smtp(
    monkeypatch,
    *,
    host="smtp.test.local",
    from_addr="alerts@securedapp.test",
):
    monkeypatch.setattr(settings, "SMTP_HOST", host)
    monkeypatch.setattr(settings, "SMTP_PORT", 587)
    monkeypatch.setattr(settings, "SMTP_FROM", from_addr)
    monkeypatch.setattr(settings, "SMTP_USERNAME", "relay-user")
    monkeypatch.setattr(settings, "SMTP_PASSWORD", "sup3r-s3cret-pass")
    monkeypatch.setattr(settings, "SMTP_STARTTLS", True)
    monkeypatch.setattr(settings, "SMTP_MAX_ATTEMPTS", 2)
    monkeypatch.setattr(settings, "SMTP_RETRY_BACKOFF_SECONDS", 0.0)


def _unconfigure_smtp(monkeypatch):
    monkeypatch.setattr(settings, "SMTP_HOST", None)
    monkeypatch.setattr(settings, "SMTP_FROM", None)


class _FakeSMTP:
    """In-process stand-in for smtplib.SMTP; records every protocol step."""

    def __init__(self, shared):
        self.shared = shared

    def ehlo(self):
        pass

    def starttls(self):
        self.shared["starttls"] = True

    def login(self, username, password):
        self.shared["logins"].append((username, password))
        if self.shared.get("login_error"):
            raise self.shared["login_error"]

    def sendmail(self, sender, recipients, message):
        if self.shared.get("refuse"):
            return {recipients[0]: (550, b"mailbox unavailable")}
        self.shared["sent"].append((sender, list(recipients), message))
        return {}

    def quit(self):
        pass


def _install_fake(monkeypatch, *, fail_opens=0, refuse=False, login_error=None):
    shared = {
        "logins": [],
        "sent": [],
        "starttls": False,
        "refuse": refuse,
        "login_error": login_error,
        "fail_opens": fail_opens,
        "open_calls": 0,
    }

    def factory(host, port, timeout):
        shared["open_calls"] += 1
        if shared["open_calls"] <= shared["fail_opens"]:
            raise ConnectionRefusedError("simulated transient connection failure")
        return _FakeSMTP(shared)

    monkeypatch.setattr(nd, "_open_smtp", factory)
    return shared


def _queued_notification(db, title="Security operations centre tender") -> Notification:
    bid = Bid(title=title)
    db.add(bid)
    db.flush()
    notif = Notification(
        bid_id=bid.id,
        channel="EMAIL",
        recipient="security-team@securedapp.com",
        notification_type="NEW_HIGH_RELEVANCE",
        deduplication_key=f"notif_{bid.id}_high_relevance",
        status="PENDING",
    )
    db.add(notif)
    db.commit()
    return notif


def test_unconfigured_attempt_never_connects(monkeypatch, db):
    _unconfigure_smtp(monkeypatch)

    def _boom(*args, **kwargs):
        raise AssertionError("SMTP connection attempted while unconfigured")

    monkeypatch.setattr(nd, "_open_smtp", _boom)
    notif = _queued_notification(db)

    out = nd.attempt_delivery(db, notif)

    assert out["sent"] is False
    assert out["attempts"] == 0
    assert out["delivery_state"] == "QUEUED"
    assert out["delivery_configured"] is False
    assert "not been dispatched" in out["delivery_note"].lower()
    db.refresh(notif)
    assert notif.status == "PENDING"
    assert notif.sent_at is None


def test_sent_only_after_provider_acceptance(monkeypatch, db):
    _configure_smtp(monkeypatch)
    shared = _install_fake(monkeypatch)
    notif = _queued_notification(db)

    out = nd.attempt_delivery(db, notif)

    assert out["sent"] is True
    assert out["delivery_state"] == "DELIVERED"
    assert out["attempts"] == 1
    assert out["error"] is None
    db.refresh(notif)
    assert notif.status == "SENT"
    assert notif.sent_at is not None
    # The provider accepted exactly one correctly addressed message, over TLS,
    # and the credential never appears on the wire payload.
    assert len(shared["sent"]) == 1
    sender, recipients, message = shared["sent"][0]
    assert sender == "alerts@securedapp.test"
    assert recipients == ["security-team@securedapp.com"]
    assert shared["starttls"] is True
    assert shared["logins"] == [("relay-user", "sup3r-s3cret-pass")]
    assert "sup3r-s3cret-pass" not in message
    assert "Security operations centre tender" in message


def test_duplicate_send_is_skipped(monkeypatch, db):
    _configure_smtp(monkeypatch)
    shared = _install_fake(monkeypatch)
    notif = _queued_notification(db)

    first = nd.attempt_delivery(db, notif)
    second = nd.attempt_delivery(db, notif)

    assert first["sent"] is True
    assert second["sent"] is False
    assert "already delivered" in second["delivery_note"].lower()
    assert shared["open_calls"] == 1, "a SENT row must never be sent again"
    assert len(shared["sent"]) == 1


def test_transient_failure_is_retried_then_succeeds(monkeypatch, db):
    _configure_smtp(monkeypatch)
    shared = _install_fake(monkeypatch, fail_opens=1)
    notif = _queued_notification(db)

    out = nd.attempt_delivery(db, notif)

    assert out["sent"] is True
    assert out["attempts"] == 2
    assert shared["open_calls"] == 2
    db.refresh(notif)
    assert notif.status == "SENT"


def test_failure_after_max_attempts_marks_failed(monkeypatch, db):
    _configure_smtp(monkeypatch)
    _install_fake(monkeypatch, fail_opens=99)
    notif = _queued_notification(db)

    out = nd.attempt_delivery(db, notif)

    assert out["sent"] is False
    assert out["attempts"] == settings.SMTP_MAX_ATTEMPTS
    assert out["delivery_state"] == "FAILED"
    assert out["error"] and "ConnectionRefusedError" in out["error"]
    db.refresh(notif)
    assert notif.status == "FAILED"
    assert notif.sent_at is None


def test_provider_refusal_is_failure_not_delivery(monkeypatch, db):
    _configure_smtp(monkeypatch)
    _install_fake(monkeypatch, refuse=True)
    notif = _queued_notification(db)

    out = nd.attempt_delivery(db, notif)

    assert out["sent"] is False
    assert out["delivery_state"] == "FAILED"
    assert out["error"] and "refused" in out["error"].lower()
    db.refresh(notif)
    assert notif.status == "FAILED"
    assert notif.sent_at is None


def test_error_never_contains_smtp_password(monkeypatch, db):
    _configure_smtp(monkeypatch)
    # A worst-case provider that echoes the credential back in its error.
    login_error = smtplib.SMTPAuthenticationError(
        535, b"5.7.8 credentials rejected for sup3r-s3cret-pass"
    )
    _install_fake(monkeypatch, login_error=login_error)
    notif = _queued_notification(db)

    out = nd.attempt_delivery(db, notif)

    assert out["delivery_state"] == "FAILED"
    assert "sup3r-s3cret-pass" not in (out["error"] or "")
    assert "***" in (out["error"] or "")
    assert "relay-user" not in (out["error"] or "")


def test_dispatch_pending_skips_when_unconfigured(monkeypatch, db):
    _unconfigure_smtp(monkeypatch)
    notif = _queued_notification(db)

    summary = nd.dispatch_pending(db)

    assert summary["configured"] is False
    assert summary["processed"] == 0
    assert summary["sent"] == 0
    db.refresh(notif)
    assert notif.status == "PENDING"


def test_dispatch_pending_sends_queued_then_becomes_noop(monkeypatch, db):
    _configure_smtp(monkeypatch)
    shared = _install_fake(monkeypatch)
    _queued_notification(db, title="First alert")
    _queued_notification(db, title="Second alert")

    first = nd.dispatch_pending(db)
    second = nd.dispatch_pending(db)

    assert first["configured"] is True
    assert first["processed"] == 2
    assert first["sent"] == 2
    assert first["failed"] == 0
    assert second["processed"] == 0, "SENT rows are never dispatched again"
    assert shared["open_calls"] == 2


def test_try_dispatch_is_noop_when_unconfigured(monkeypatch, db):
    _unconfigure_smtp(monkeypatch)

    def _boom(*args, **kwargs):
        raise AssertionError("connection attempted while unconfigured")

    monkeypatch.setattr(nd, "_open_smtp", _boom)
    notif = _queued_notification(db)

    assert nd.try_dispatch(db, notif) is None
    db.refresh(notif)
    assert notif.status == "PENDING"


def test_deliver_endpoint_reports_not_configured_without_sending(monkeypatch, client, db):
    _unconfigure_smtp(monkeypatch)

    def _boom(*args, **kwargs):
        raise AssertionError("connection attempted while unconfigured")

    monkeypatch.setattr(nd, "_open_smtp", _boom)
    notif = _queued_notification(db)

    res = client.post(f"/api/v1/notifications/{notif.id}/deliver")

    assert res.status_code == 200
    body = res.json()
    assert body["sent"] is False
    assert body["delivery_state"] == "QUEUED"
    assert body["delivery_configured"] is False
    assert body["status"] == "PENDING"
    db.refresh(notif)
    assert notif.status == "PENDING"


def test_deliver_endpoint_sends_and_prevents_duplicates(monkeypatch, client, db):
    _configure_smtp(monkeypatch)
    shared = _install_fake(monkeypatch)
    notif = _queued_notification(db)

    res = client.post(f"/api/v1/notifications/{notif.id}/deliver")
    assert res.status_code == 200
    body = res.json()
    assert body["sent"] is True
    assert body["delivery_state"] == "DELIVERED"
    assert body["status"] == "SENT"

    again = client.post(f"/api/v1/notifications/{notif.id}/deliver")
    assert again.status_code == 200
    assert again.json()["sent"] is False
    assert shared["open_calls"] == 1


def test_dispatch_endpoint_reports_not_configured(monkeypatch, client, db):
    _unconfigure_smtp(monkeypatch)
    _queued_notification(db)

    res = client.post("/api/v1/notifications/dispatch")

    assert res.status_code == 200
    body = res.json()
    assert body["configured"] is False
    assert body["processed"] == 0
    assert "no delivery provider" in body["note"].lower()


def test_notifications_listing_never_exposes_smtp_settings(monkeypatch, client, db):
    _configure_smtp(monkeypatch, host="smtp.leaked-host.test")
    notif = _queued_notification(db)

    res = client.get("/api/v1/notifications")

    assert res.status_code == 200
    text = res.text
    assert "sup3r-s3cret-pass" not in text
    assert "smtp.leaked-host.test" not in text
    assert "relay-user" not in text
    rows = res.json()
    assert len(rows) == 1
    row = rows[0]
    # Derived flags only; no key may reveal provider configuration details.
    assert not any("smtp" in key.lower() or "password" in key.lower() for key in row)
    # Configured but not yet sent: honestly QUEUED, never DELIVERED.
    assert row["delivery_configured"] is True
    assert row["delivery_state"] == "QUEUED"
    assert row["status"] == "PENDING"


def test_analyze_auto_dispatches_when_smtp_configured(monkeypatch, client, db):
    """End-to-end: high-relevance notification is sent on creation when SMTP is
    configured, and only ever with provider confirmation."""
    _configure_smtp(monkeypatch)
    shared = _install_fake(monkeypatch)
    bid = Bid(
        title="Solidity Smart Contract Audit and Security Assessment",
        scope_of_work="Comprehensive vulnerability scanning, reentrancy detection, and expert review.",
        estimated_value="2500000",
        closing_date=datetime.now(timezone.utc) + timedelta(days=12),
    )
    db.add(bid)
    db.commit()

    res = client.post(f"/api/v1/bids/{bid.id}/analyze")
    assert res.status_code == 200

    notif = db.query(Notification).filter(Notification.bid_id == bid.id).first()
    assert notif is not None
    assert notif.status == "SENT"
    assert notif.sent_at is not None
    assert len(shared["sent"]) == 1
