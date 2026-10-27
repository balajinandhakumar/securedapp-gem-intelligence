"""
Notification delivery: explicit state, real SMTP dispatch, honest reporting.

This module makes the distinction between a notification being **generated /
queued** and actually **delivered** explicit, so the two are never conflated.

Architecture:

* When a bid crosses the relevance/opportunity threshold the analysis pipeline
  **generates** a :class:`~app.models.notification.Notification` row with
  ``status = "PENDING"`` (queued). Generation and de-duplication are durable;
  see ``analysis.py`` and ``services/intelligence/batch_processor.py``.
* **Email delivery** is integrated over SMTP (stdlib ``smtplib``; no third-party
  dependency) using server-side credentials from settings (``SMTP_HOST``,
  ``SMTP_PORT``, ``SMTP_USERNAME``, ``SMTP_PASSWORD``, ``SMTP_FROM``,
  ``SMTP_STARTTLS``). Credentials are read here only and are never logged,
  never serialized by any API, and never sent to the frontend.

Delivery guarantees enforced by :func:`attempt_delivery`:

* **No send without configuration.** With no SMTP host/from the row stays
  ``PENDING`` / ``QUEUED`` with the explicit not-configured note; the code
  opens no connection at all.
* **Duplicate-send prevention.** A row already ``SENT`` is never sent again --
  a repeated call returns "already delivered" without touching the network.
* **Sent only on confirmed provider success.** ``status`` becomes ``SENT``
  (state ``DELIVERED``) only after the provider accepted the message
  (``sendmail`` returned no refused recipients and raised nothing). A refused
  recipient counts as failure, never as delivery.
* **Bounded retries.** Transient transport failures are retried up to
  ``SMTP_MAX_ATTEMPTS`` with backoff, then the row is marked ``FAILED``.
  ``FAILED`` rows can be retried explicitly through the deliver endpoint.
* **Sanitized errors.** Failure text is scrubbed of the configured username and
  password before it is stored in an API response.

WhatsApp is deliberately not implemented: no WhatsApp provider or requirements
are configured, and no claim of WhatsApp delivery may be made.
"""
from __future__ import annotations

import logging
import smtplib
import time
from datetime import datetime, timezone
from email.message import EmailMessage
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.core.config import settings

logger = logging.getLogger(__name__)

# Delivery provider client code that is integrated in this build. Availability
# still depends on credentials: use delivery_provider_configured().
INTEGRATED_DELIVERY_PROVIDERS: tuple = ("smtp",)


def smtp_configured() -> bool:
    """True only when SMTP credentials sufficient for a send are present.

    Deliberately requires only the non-secret addressing pair: a local relay
    may need no username/password, while host+sender are always required to
    put a message on the wire.
    """
    return bool(
        str(getattr(settings, "SMTP_HOST", "") or "").strip()
        and str(getattr(settings, "SMTP_FROM", "") or "").strip()
    )


def delivery_provider_configured() -> bool:
    """True only when a real delivery provider is integrated AND configured."""
    return "smtp" in INTEGRATED_DELIVERY_PROVIDERS and smtp_configured()


# Stored ``status`` (set by the pipeline / dispatcher) -> explicit delivery state.
_STATE_BY_STATUS = {
    "PENDING": "QUEUED",
    "SENT": "DELIVERED",
    "FAILED": "FAILED",
}


def describe_delivery(notification: Any) -> Dict[str, Any]:
    """Derive the explicit delivery state for a persisted notification row."""
    status = (getattr(notification, "status", "") or "").upper()
    state = _STATE_BY_STATUS.get(status, status or "UNKNOWN")
    configured = delivery_provider_configured()

    if state == "DELIVERED":
        note = "Delivery confirmed by the provider."
    elif state == "FAILED":
        note = (
            "Delivery was attempted and failed after retries; it can be "
            "retried explicitly."
        )
    elif state == "QUEUED":
        if not configured:
            note = (
                "Queued for delivery; no delivery provider is configured in "
                "this deployment, so it has not been dispatched."
            )
        else:
            note = (
                "Queued for dispatch; SMTP delivery is configured. "
                "It has not been sent yet."
            )
    else:
        note = "Delivery state is unknown."

    return {
        "delivery_state": state,
        "delivery_configured": configured,
        "delivery_note": note,
    }


# --------------------------------------------------------------------------
# Dispatch
# --------------------------------------------------------------------------


def _open_smtp(host: str, port: int, timeout: float) -> smtplib.SMTP:
    """Open one SMTP connection. Isolated so tests can substitute a fake."""
    return smtplib.SMTP(host, port, timeout=timeout)


def _secrets() -> List[Optional[str]]:
    """Values that must never appear in any returned/stored error text."""
    return [
        getattr(settings, "SMTP_PASSWORD", None),
        getattr(settings, "SMTP_USERNAME", None),
    ]


def sanitize_error(exc: BaseException, extra_secrets: Optional[List[Optional[str]]] = None) -> str:
    """Human-readable failure text with configured credentials scrubbed out."""
    text = f"{type(exc).__name__}: {exc}"
    for secret in list(_secrets()) + list(extra_secrets or []):
        if secret:
            text = text.replace(str(secret), "***")
    return text[:300]


def _bid_title(db: Session, bid_id: Any) -> str:
    try:
        from app.models.bid import Bid

        bid = db.get(Bid, bid_id)
        if bid is not None:
            return (bid.title or "").strip() or "new bid"
    except Exception:  # pragma: no cover - title is cosmetic only
        pass
    return "new bid"


def _build_message(notification: Any, bid_title: str) -> EmailMessage:
    msg = EmailMessage()
    label = (getattr(notification, "notification_type", "") or "ALERT")
    msg["Subject"] = f"[GeM Intelligence] {label.replace('_', ' ').title()}: {bid_title}"
    msg["From"] = str(getattr(settings, "SMTP_FROM", "") or "")
    msg["To"] = str(getattr(notification, "recipient", "") or "")
    body = [
        f"Notification type: {label}",
        f"Bid: {bid_title}",
        f"Recipient: {msg['To']}",
        "",
        "This alert was generated by the SecuredApp GeM Bid Intelligence Bot.",
    ]
    msg.set_content("\n".join(body))
    return msg


def attempt_delivery(
    db: Session,
    notification: Any,
    *,
    max_attempts: Optional[int] = None,
    backoff_seconds: Optional[float] = None,
) -> Dict[str, Any]:
    """Dispatch one queued notification through SMTP and persist the outcome.

    Returns a dict with ``delivery_state`` / ``delivery_configured`` /
    ``delivery_note`` (same keys as :func:`describe_delivery`) plus ``sent``,
    ``attempts`` and a sanitized ``error``. Never raises for transport
    failures; never sends twice.
    """
    # Re-read the row in this session so two concurrent calls can never both
    # observe PENDING and both send (duplicate-send prevention).
    row = notification
    try:
        from app.models.notification import Notification

        fresh = db.query(Notification).filter(Notification.id == notification.id).first()
        if fresh is not None:
            row = fresh
    except Exception:  # pragma: no cover - fall back to the given object
        row = notification

    result: Dict[str, Any] = {
        **describe_delivery(row),
        "sent": False,
        "attempts": 0,
        "error": None,
    }

    status = (getattr(row, "status", "") or "").upper()
    if status == "SENT":
        result["delivery_note"] = "Already delivered; duplicate send skipped."
        return result

    if not delivery_provider_configured():
        # Explicit not-configured state: no connection is attempted at all.
        return result

    channel = str(getattr(row, "channel", "") or "").upper()
    if channel != "EMAIL":
        result["delivery_note"] = (
            f"Channel {channel or 'UNKNOWN'} has no configured provider; the "
            "notification stays queued."
        )
        return result

    attempts_limit = int(
        max_attempts if max_attempts is not None else settings.SMTP_MAX_ATTEMPTS
    )
    attempts_limit = max(1, attempts_limit)
    backoff = float(
        backoff_seconds
        if backoff_seconds is not None
        else settings.SMTP_RETRY_BACKOFF_SECONDS
    )

    msg = _build_message(row, _bid_title(db, getattr(row, "bid_id", None)))
    host = str(settings.SMTP_HOST).strip()
    port = int(settings.SMTP_PORT or 587)
    timeout = float(settings.SMTP_TIMEOUT_SECONDS or 15)
    starttls = bool(settings.SMTP_STARTTLS)
    username = getattr(settings, "SMTP_USERNAME", None) or None
    password = getattr(settings, "SMTP_PASSWORD", None) or None
    sender = str(settings.SMTP_FROM).strip()
    recipient = str(getattr(row, "recipient", "") or "").strip()

    last_error: Optional[str] = None
    for attempt in range(1, attempts_limit + 1):
        result["attempts"] = attempt
        smtp: Optional[smtplib.SMTP] = None
        try:
            smtp = _open_smtp(host, port, timeout)
            if starttls:
                smtp.ehlo()
                smtp.starttls()
                smtp.ehlo()
            if username:
                smtp.login(username, password or "")
            refused = smtp.sendmail(sender, [recipient], msg.as_string())
            if refused:
                # {recipient: (code, message)} for every refused address.
                raise RuntimeError(
                    f"Provider refused recipient(s): {sorted(refused)}"
                )
            # Provider accepted the message -> only now is it delivered.
            row.status = "SENT"
            row.sent_at = datetime.now(timezone.utc)
            db.commit()
            result.update(
                describe_delivery(row),
                sent=True,
                attempts=attempt,
                error=None,
            )
            return result
        except Exception as exc:  # noqa: BLE001 - any transport error is a failure
            last_error = sanitize_error(exc)
            logger.warning(
                "Notification %s delivery attempt %s/%s failed: %s",
                getattr(row, "id", "?"),
                attempt,
                attempts_limit,
                last_error,
            )
            if attempt < attempts_limit and backoff > 0:
                time.sleep(backoff * attempt)
        finally:
            if smtp is not None:
                try:
                    smtp.quit()
                except Exception:  # pragma: no cover - teardown best effort
                    pass

    row.status = "FAILED"
    db.commit()
    result.update(
        describe_delivery(row),
        sent=False,
        attempts=attempts_limit,
        error=last_error,
    )
    return result


def try_dispatch(db: Session, notification: Any) -> Optional[Dict[str, Any]]:
    """Best-effort automatic dispatch at creation time. Never raises.

    Returns ``None`` when SMTP is not configured (the row simply stays
    queued), so callers in the analysis pipeline are unaffected in the
    default deployment.
    """
    if not delivery_provider_configured():
        return None
    try:
        return attempt_delivery(db, notification)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Automatic dispatch failed: %s", sanitize_error(exc))
        return None


def dispatch_pending(db: Session, *, limit: int = 50) -> Dict[str, Any]:
    """Attempt delivery of up to ``limit`` queued EMAIL notifications.

    Bounded and idempotent: rows already SENT are never re-sent, and with no
    configured provider this reports ``configured: false`` without touching
    the database rows.
    """
    configured = delivery_provider_configured()
    summary: Dict[str, Any] = {
        "configured": configured,
        "processed": 0,
        "sent": 0,
        "failed": 0,
        "skipped": 0,
        "note": "",
    }
    if not configured:
        summary["note"] = (
            "No delivery provider is configured; nothing was dispatched."
        )
        return summary

    from app.models.notification import Notification

    queued = (
        db.query(Notification)
        .filter(Notification.status == "PENDING")
        .filter(Notification.channel == "EMAIL")
        .order_by(Notification.id.asc())
        .limit(max(1, min(int(limit or 50), 200)))
        .all()
    )
    for row in queued:
        summary["processed"] += 1
        outcome = attempt_delivery(db, row)
        if outcome.get("sent"):
            summary["sent"] += 1
        elif outcome.get("delivery_state") == "FAILED":
            summary["failed"] += 1
        else:
            summary["skipped"] += 1
    summary["note"] = (
        f"Dispatched {summary['sent']} of {summary['processed']} queued "
        "notification(s); "
        f"{summary['failed']} failed and {summary['skipped']} skipped."
    )
    return summary
