"""
Per-source collection scheduler.

Extends the existing GeM scheduler philosophy rather than competing with it:

* One background thread, no per-source jobs to register -> nothing to leak
  across restarts.
* Next-run time for a source is derived from its ``last_attempt_at`` in the
  database, so a backend restart simply recomputes due sources; there is no
  in-memory schedule to duplicate or lose.
* ``run_due_sources`` is a normal function over a session, so tests drive it
  directly with a fake clock; ``start()`` / ``stop()`` are thin thread
  wrappers.
* ``runner.run_source_sync`` holds a per-source lock, so a manual trigger and
  the scheduler can never collect the same source at once.
* One source failing does not stop the others (each runs in its own
  try/except).

Scheduled collection is **off by default** (``SOURCE_SCHEDULER_ENABLED=false``)
and must be switched on by an operator -- no live sync ever happens during
development or automated testing.
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.source import DataSource
from app.services.sources.runner import run_source_sync

logger = logging.getLogger(__name__)

MIN_INTERVAL_SECONDS = 300.0  # 5 minutes

_scheduler_thread: Optional[threading.Thread] = None
_stop_event = threading.Event()
_thread_lock = threading.Lock()


def _as_utc(dt: Optional[datetime]) -> Optional[datetime]:
    """Normalize naive datetimes (as returned by SQLite) to UTC-aware."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _due(sources: List[DataSource], now: datetime) -> List[DataSource]:
    due: List[DataSource] = []
    for source in sources:
        interval = _interval_seconds(source)
        last = _as_utc(source.last_attempt_at)
        if last is None or (now - last).total_seconds() >= interval:
            due.append(source)
    return due


def _interval_seconds(source: DataSource) -> float:
    minutes = int(source.collection_interval_minutes or 60)
    return max(MIN_INTERVAL_SECONDS, float(minutes * 60))


def run_due_sources(
    db: Session,
    *,
    now: Optional[datetime] = None,
    session: Any = None,
    max_sources: int = 0,
) -> Dict[str, Any]:
    """Run every due enabled source once, sequentially, isolating failures.

    Returns a summary dict (no secrets, no records).
    """
    now = now or datetime.now(timezone.utc)
    enabled = db.query(DataSource).filter(DataSource.enabled.is_(True)).all()
    due = _due(enabled, now)
    if max_sources and len(due) > max_sources:
        due = due[:max_sources]

    summary: Dict[str, Any] = {
        "scheduler": True,
        "now": now.isoformat(),
        "enabled_sources": len(enabled),
        "due_sources": len(due),
        "ran": 0,
        "skipped_busy": 0,
        "failed": 0,
        "results": [],
    }
    for source in due:
        # Re-read the source so we don't race another writer on last_attempt_at.
        fresh = db.get(DataSource, source.id)
        if fresh is None:
            continue
        fresh_attempt = _as_utc(fresh.last_attempt_at)
        if fresh_attempt and (now - fresh_attempt).total_seconds() < _interval_seconds(fresh):
            continue
        try:
            result = run_source_sync(
                db,
                fresh,
                trigger="scheduler",
                session=session,
                now=now,
                auto_notify=True,
            )
            summary["results"].append(
                {k: result.get(k) for k in ("source_id", "status", "message", "inserted", "updated", "duplicates", "rejected", "duration_seconds")}
            )
            if result.get("status") == "BUSY":
                summary["skipped_busy"] += 1
            elif result.get("status") in ("ERROR", "FAILED", "BLOCKED", "CONFIG_ERROR"):
                summary["failed"] += 1
            summary["ran"] += 1
        except Exception as exc:  # noqa: BLE001 - scheduler must keep ticking
            logger.exception("Scheduler failed for source %s", source.source_id)
            summary["failed"] += 1
            summary["results"].append({"source_id": source.source_id, "status": "ERROR", "message": str(exc)[:200]})
    return summary


def next_run_at(source: Optional[DataSource] = None) -> Optional[str]:
    """ISO date of the next scheduled run for ``source`` (or None)."""
    if source is None:
        return None
    if not source.enabled:
        return None
    last = _as_utc(source.last_attempt_at)
    interval = _interval_seconds(source)
    base = last if last is not None else datetime.now(timezone.utc)
    return (base + timedelta(seconds=interval)).isoformat()


def start() -> bool:
    """Start the scheduler thread. Restart-safe idempotent."""
    global _scheduler_thread
    if not getattr(settings, "SOURCE_SCHEDULER_ENABLED", False):
        return False
    with _thread_lock:
        if _scheduler_thread is not None and _scheduler_thread.is_alive():
            return True
        _stop_event.clear()
        _scheduler_thread = threading.Thread(
            target=_loop, name="multi-source-scheduler", daemon=True
        )
        _scheduler_thread.start()
        return True


def stop() -> None:
    global _scheduler_thread
    with _thread_lock:
        _stop_event.set()
        _scheduler_thread = None


def _loop() -> None:
    tick = max(30.0, float(getattr(settings, "SOURCE_SCHEDULER_TICK_SECONDS", 60) or 60))
    while not _stop_event.wait(tick):
        try:
            db = SessionLocal()
            try:
                run_due_sources(db)
            finally:
                db.close()
        except Exception:  # noqa: BLE001 - never let one tick kill the thread
            logger.exception("Scheduler tick failed")


def scheduler_status() -> Dict[str, Any]:
    return {
        "enabled": bool(getattr(settings, "SOURCE_SCHEDULER_ENABLED", False)),
        "tick_seconds": max(30.0, float(getattr(settings, "SOURCE_SCHEDULER_TICK_SECONDS", 60) or 60)),
        "running": _scheduler_thread is not None and _scheduler_thread.is_alive(),
        "note": (
            "Automatic per-source collection. Off by default; enable with "
            "SOURCE_SCHEDULER_ENABLED=true."
        ),
    }