"""
Automatic collection scheduler for the direct GeM public collector.

One background thread, started with the backend (see ``app.main`` lifespan),
that wakes every ``GEM_DIRECT_SCHEDULER_INTERVAL_MINUTES`` and performs a
single bounded collection through the *existing* pipeline::

    gem_scheduler tick -> ingest_gem_direct_bids(...)   # same entry point
                        -> existing validation / normalization / dedup
                        -> existing 11-product matching + notifications
                        -> existing CollectionRun audit row

There is no second collector, no second deduplication path and no second
persistence path. The scheduler only decides *when* a collection happens.

DESIGN RULES
    * One collection at a time. A tick calls the service's own non-blocking
      lock, so a scheduled run can never overlap a manual fetch (and vice
      versa). When the lock is busy the tick is recorded as ``BUSY`` and
      skipped; it is never queued and never forced.
    * Bounded scope. A scheduled run walks at most the existing configured
      page budget (``GEM_DIRECT_MAX_PAGES``) at the existing request
      interval. The full ongoing listing is never crawled: the default
      budget is 250 of ~4,365 pages, and truncation is reported honestly
      through the run's ``limit_reached`` / ``stop_reason`` audit keys.
    * Failure isolation. A run that ends ``ERROR`` or ``BLOCKED`` is
      recorded and the loop simply waits for the next scheduled tick.
      There is no retry loop of any kind: at most one attempt per
      interval, so a temporarily unavailable source cannot cause a
      request storm and no exception is allowed to kill the thread.
    * Audit. After every tick the run's counters (validated, inserted,
      updated, duplicates, rejected, errors, duration, truncation) are
      appended to its ``CollectionRun.notes`` in the same ``key=value``
      convention the service already uses, so the audit row carries the
      full statistics even though the in-process status payload is lost
      on restart.
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.collection import CollectionRun
# Imported into this namespace (rather than called off the module) so tests
# can substitute the collection entry point without touching the service.
from app.services.ingestion.gem_direct_service import ingest_gem_direct_bids

logger = logging.getLogger(__name__)

# Single scheduler thread state. The stop event doubles as the sleep signal:
# stop() sets it, which wakes the loop immediately instead of waiting out
# the remaining interval.
_state_lock = threading.Lock()
_stop_event = threading.Event()
_thread: Optional[threading.Thread] = None
_next_run_at: Optional[datetime] = None
_last_attempt: Dict[str, Any] = {}
_consecutive_failures = 0
_skipped_ticks = 0
_total_runs = 0
_successful_runs = 0
_was_stopped = False  # True when stop() was called; used to detect restart


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
def is_enabled() -> bool:
    """Whether automatic scheduled collection is switched on."""
    return bool(getattr(settings, "GEM_DIRECT_SCHEDULER_ENABLED", False))


def interval_minutes() -> int:
    """Configured interval, clamped to at least one minute."""
    try:
        minutes = int(getattr(settings, "GEM_DIRECT_SCHEDULER_INTERVAL_MINUTES", 5) or 0)
    except (TypeError, ValueError):
        minutes = 5
    return max(1, minutes)


def interval_seconds() -> float:
    return interval_minutes() * 60.0


# ---------------------------------------------------------------------------
# Introspection (Data Source page / tests)
# ---------------------------------------------------------------------------
def is_alive() -> bool:
    """True while the scheduler thread is running."""
    thread = _thread
    return bool(thread is not None and thread.is_alive())


def next_run_at() -> Optional[str]:
    """ISO-8601 UTC time of the next scheduled tick, or None when not scheduled."""
    with _state_lock:
        return _next_run_at.isoformat() if _next_run_at is not None else None


def last_attempt() -> Dict[str, Any]:
    """Most recent scheduled attempt (status, counters, message). Never full results."""
    with _state_lock:
        return dict(_last_attempt)


def consecutive_failures() -> int:
    with _state_lock:
        return _consecutive_failures


def skipped_ticks() -> int:
    """Number of scheduled ticks skipped because a previous run was still running."""
    with _state_lock:
        return _skipped_ticks


def total_runs() -> int:
    """Total number of scheduler ticks attempted (including skipped/failed)."""
    with _state_lock:
        return _total_runs


def successful_runs() -> int:
    """Number of scheduler ticks that completed with status SUCCESS."""
    with _state_lock:
        return _successful_runs


def was_stopped() -> bool:
    """True if the scheduler has been stopped at least once (restart detection)."""
    with _state_lock:
        return _was_stopped


def scheduler_status() -> Dict[str, Any]:
    """Secret-free scheduler description for the Data Source page."""
    return {
        "enabled": is_enabled(),
        "interval_minutes": interval_minutes(),
        "thread_alive": is_alive(),
        "next_run": next_run_at(),
        "last_attempt": last_attempt(),
        "consecutive_failures": consecutive_failures(),
        "skipped_ticks": skipped_ticks(),
        "total_runs": total_runs(),
        "successful_runs": successful_runs(),
        "was_stopped": was_stopped(),
    }


# ---------------------------------------------------------------------------
# Run statistics audit (CollectionRun)
# ---------------------------------------------------------------------------
_RUN_STAT_KEYS = (
    "validated",
    "inserted",
    "updated",
    "duplicates",
    "rejected",
    "errors",
    "duration_seconds",
)


def _append_missing_kv(notes: str, key: str, value: Any) -> str:
    """Append ``key=value`` unless the notes already carry that key."""
    if f"{key}=" in notes:
        return notes
    return f"{notes};{key}={value}"


def augment_collection_run_stats(
    db: Session, run_id: Optional[str], result: Dict[str, Any]
) -> bool:
    """
    Record the full counter set of a finished run on its CollectionRun row.

    The service already writes start/end time, rows_seen, stop_reason and
    limit_reached into the audit row; this adds the persistence counters the
    audit requirement calls for (validated / inserted / updated / duplicates /
    rejected / errors / duration) plus an explicit ``truncated`` flag. Keys
    already present are never overwritten, so calling this twice is a no-op.
    Returns True when the row was updated.
    """
    if not run_id or not result:
        return False
    try:
        run_uuid = uuid.UUID(str(run_id))
    except (TypeError, ValueError):
        return False
    try:
        run = db.get(CollectionRun, run_uuid)
        if run is None:
            return False
        notes = run.notes or ""
        if "validated=" in notes:
            return False
        notes = _append_missing_kv(notes, "validated", int(result.get("validated") or 0))
        notes = _append_missing_kv(notes, "inserted", int(result.get("inserted") or 0))
        notes = _append_missing_kv(notes, "updated", int(result.get("updated") or 0))
        notes = _append_missing_kv(notes, "duplicates", int(result.get("duplicates") or 0))
        notes = _append_missing_kv(notes, "rejected", int(result.get("rejected") or 0))
        notes = _append_missing_kv(notes, "errors", len(result.get("errors") or []))
        notes = _append_missing_kv(
            notes, "duration_seconds", float(result.get("duration_seconds") or 0.0)
        )
        notes = _append_missing_kv(
            notes, "truncated", bool(result.get("limit_reached"))
        )
        run.notes = notes
        db.commit()
        return True
    except Exception:  # noqa: BLE001 - audit enrichment must never fail a run
        try:
            db.rollback()
        except Exception:  # noqa: BLE001
            pass
        logger.exception("Could not append run statistics to CollectionRun %s", run_id)
        return False


def _record_attempt(result: Dict[str, Any]) -> None:
    global _last_attempt, _consecutive_failures, _skipped_ticks
    status = str(result.get("status") or "UNKNOWN")
    with _state_lock:
        _last_attempt = {
            "at": datetime.now(timezone.utc).isoformat(),
            "status": status,
            "run_id": result.get("run_id"),
            "message": str(result.get("message") or "")[:400],
            "inserted": int(result.get("inserted") or 0),
            "updated": int(result.get("updated") or 0),
            "duplicates": int(result.get("duplicates") or 0),
            "rejected": int(result.get("rejected") or 0),
            "duration_seconds": float(result.get("duration_seconds") or 0.0),
            "stop_reason": result.get("stop_reason"),
            "limit_reached": bool(result.get("limit_reached")),
        }
        if status == "BUSY":
            # A busy tick means the previous run was still running; skip and record.
            _skipped_ticks += 1
        if status in ("ERROR", "BLOCKED"):
            _consecutive_failures += 1
        elif status != "BUSY":
            _consecutive_failures = 0


# ---------------------------------------------------------------------------
# One scheduled attempt
# ---------------------------------------------------------------------------
def run_once(db: Optional[Session] = None) -> Dict[str, Any]:
    """
    Perform one scheduled collection attempt and record its outcome.

    Never raises: any failure is converted into an ``ERROR`` result and
    recorded, so the calling loop always survives. ``db`` may be supplied
    (tests); otherwise a private session is opened and closed here. The
    service's non-overlap lock decides whether the attempt actually runs --
    a concurrent manual fetch yields ``BUSY`` and this tick is skipped.
    """
    owns_session = db is None
    session = db if db is not None else SessionLocal()
    try:
        global _total_runs, _successful_runs
        _total_runs += 1
        result = ingest_gem_direct_bids(
            db=session,
            triggered_by="scheduler",
            # Always start from page 1 (newest bids first under
            # GEM_DIRECT_SORT_ORDER="Bid-Start-Date-Latest"). This ensures
            # every scheduled run revisits the newest listings to discover
            # newly published bids. Historical backlog scanning continues
            # via manual runs with auto-resume from checkpoint.
            max_pages=None,
            start_page=1,
        )
        augment_collection_run_stats(session, result.get("run_id"), result)
        _record_attempt(result)
        if result.get("status") == "SUCCESS":
            _successful_runs += 1
        logger.info(
            "Scheduled GeM collection finished: status=%s inserted=%s updated=%s "
            "duplicates=%s rejected=%s duration=%ss",
            result.get("status"),
            result.get("inserted"),
            result.get("updated"),
            result.get("duplicates"),
            result.get("rejected"),
            result.get("duration_seconds"),
        )
        return result
    except Exception as exc:  # noqa: BLE001 - a tick must never kill the loop
        try:
            session.rollback()
        except Exception:  # noqa: BLE001
            pass
        logger.exception("Scheduled GeM collection attempt failed")
        result = {
            "status": "ERROR",
            "source": "gem_direct",
            "message": f"Scheduled collection failed: {exc}",
            "run_id": None,
            "inserted": 0,
            "updated": 0,
            "duplicates": 0,
            "rejected": 0,
            "duration_seconds": 0.0,
            "stop_reason": "error",
            "limit_reached": False,
            "errors": [{"field": "scheduler", "message": str(exc)}],
        }
        _record_attempt(result)
        return result
    finally:
        if owns_session:
            try:
                session.close()
            except Exception:  # noqa: BLE001
                pass


# ---------------------------------------------------------------------------
# Thread lifecycle
# ---------------------------------------------------------------------------
def _loop() -> None:
    global _next_run_at
    logger.info(
        "GeM direct scheduler loop started (interval=%d minute(s), enabled=%s)",
        interval_minutes(),
        is_enabled(),
    )
    try:
        while not _stop_event.is_set():
            delay = interval_seconds()
            with _state_lock:
                _next_run_at = datetime.now(timezone.utc) + timedelta(seconds=delay)
            # Sleep until the tick or until stop(); stop() wakes immediately.
            if _stop_event.wait(timeout=delay):
                break
            with _state_lock:
                _next_run_at = None
            if _stop_event.is_set():
                break
            try:
                run_once()
            except Exception:  # noqa: BLE001 - defensive; run_once never raises
                logger.exception("Scheduled run raised unexpectedly; loop continues")
    except Exception:  # noqa: BLE001 - last-resort guard; loop must stay alive
        logger.exception("GeM direct scheduler loop crashed")
    finally:
        with _state_lock:
            _next_run_at = None
        logger.info("GeM direct scheduler loop stopped")


def start() -> bool:
    """
    Start the scheduler thread if enabled. Idempotent.

    Returns True when a thread is (now) running, False when the scheduler
    is disabled by configuration.
    """
    global _thread, _was_stopped
    if not is_enabled():
        logger.info(
            "GeM direct scheduler disabled (GEM_DIRECT_SCHEDULER_ENABLED=false); "
            "collections remain manual."
        )
        return False
    with _state_lock:
        if _thread is not None and _thread.is_alive():
            return True
        _stop_event.clear()
        _was_stopped = False
        _thread = threading.Thread(
            target=_loop, name="gem-direct-scheduler", daemon=True
        )
        _thread.start()
    logger.info(
        "GeM direct scheduler started (every %d minute(s))", interval_minutes()
    )
    return True


def stop(timeout: Optional[float] = None) -> None:
    """Stop the scheduler thread and wait briefly for it to exit. Idempotent.

    When ``timeout`` is None, uses ``GEM_DIRECT_SCHEDULER_STOP_TIMEOUT`` from
    settings (default 60 seconds). A long-running collection (e.g. 250 pages
    at 3s/page = 750s) needs more than the previous 15s default to finish
    gracefully. The thread is daemon, so the process will still exit on
    interpreter shutdown, but a longer timeout allows graceful completion.
    """
    global _thread, _next_run_at, _was_stopped
    if timeout is None:
        try:
            timeout = float(getattr(settings, "GEM_DIRECT_SCHEDULER_STOP_TIMEOUT", 60.0) or 60.0)
        except (TypeError, ValueError):
            timeout = 60.0
    _stop_event.set()
    thread = _thread
    if thread is not None and thread.is_alive() and thread is not threading.current_thread():
        thread.join(timeout=timeout)
    with _state_lock:
        _next_run_at = None
        _was_stopped = True
        if _thread is thread and (thread is None or not thread.is_alive()):
            _thread = None
