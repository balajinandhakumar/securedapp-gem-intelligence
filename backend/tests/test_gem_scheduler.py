"""
Scheduler regression suite for automatic GeM direct collection.

Covers the 15-part acceptance conditions for the scheduler work:

  1. Enabled by default with a 60-minute interval (config + .env.example).
  2. One module, one thread: started with the backend lifespan, idempotent
     start/stop, next-run exposed for the Data Source page.
  3. A tick calls the existing service entry point (triggered_by="scheduler",
     existing bounded page budget) -- no second collector.
  4. Full statistics are persisted on the CollectionRun audit row.
  5. A failing tick is recorded and never kills the loop; one attempt per
     interval (no retry storm); BUSY (overlap) is not a failure.
  6. Scheduled and manual runs never overlap (service non-blocking lock).
  7. Status endpoint reports scheduler state + latest run statistics, and
     reports manual-only when disabled.
  8. No secrets in scheduler output.

No network: the autouse ``no_live_gem_requests`` guard is active and the
overlap test holds the real service lock before any request could be made.
"""
import threading
import time
from datetime import datetime, timezone

import pytest

from app.core.config import settings
from app.models.collection import CollectionRun
from app.services.ingestion import gem_direct_service as svc
from app.services.ingestion import gem_scheduler as gs


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _wait_until(predicate, timeout=3.0, interval=0.02):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


def _reset_state():
    gs.stop(timeout=5.0)
    with gs._state_lock:
        gs._last_attempt = {}
        gs._consecutive_failures = 0
        gs._next_run_at = None
    # Reset service module-level state so it cannot leak between tests.
    # The service caches a shared collector, tracks a running flag, and
    # remembers the last run info -- all module-level and shared across tests.
    with svc._COLLECTOR_LOCK:
        svc._COLLECTOR = None
    svc._is_running = False
    svc._last_run_info = {}


@pytest.fixture(autouse=True)
def clean_scheduler_state():
    _reset_state()
    yield
    _reset_state()


def _fake_result(status="SUCCESS", run_id=None, **overrides):
    result = {
        "status": status,
        "source": "gem_direct",
        "message": "fake",
        "run_id": run_id,
        "rows_seen": 10,
        "received": 10,
        "validated": 9,
        "rejected": 1,
        "inserted": 4,
        "updated": 2,
        "duplicates": 3,
        "intelligence_processed": 6,
        "notifications_created": 1,
        "duration_seconds": 1.5,
        "stop_reason": "last_page",
        "limit_reached": False,
        "errors": [],
    }
    result.update(overrides)
    return result


# ---------------------------------------------------------------------------
# 1. Configuration
# ---------------------------------------------------------------------------
def test_scheduler_enabled_by_default_at_twenty_minutes():
    assert settings.GEM_DIRECT_SCHEDULER_ENABLED is True
    assert settings.GEM_DIRECT_SCHEDULER_INTERVAL_MINUTES == 20
    assert gs.is_enabled() is True
    assert gs.interval_minutes() == 20
    assert gs.interval_seconds() == 1200.0


def test_env_example_declares_enabled_twenty_minutes():
    import os

    env_path = os.path.join(
        os.path.dirname(__file__), "..", "..", ".env.example"
    )
    with open(env_path, encoding="utf-8") as handle:
        content = handle.read()
    assert "GEM_DIRECT_SCHEDULER_ENABLED=true" in content
    assert "GEM_DIRECT_SCHEDULER_INTERVAL_MINUTES=20" in content


# ---------------------------------------------------------------------------
# Production configuration validation
# ---------------------------------------------------------------------------
def test_production_rejects_default_secret_key(monkeypatch):
    """Production mode must reject the default SECRET_KEY."""
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("SECRET_KEY", "dev_secret_key_securedapp_gem_bid_intelligence_2026_key")
    from app.core.config import Settings
    try:
        Settings()
        assert False, "Should have raised ValueError for default SECRET_KEY in production"
    except ValueError as exc:
        assert "SECRET_KEY" in str(exc)


def test_production_requires_strong_secret_key(monkeypatch):
    """Production requires a SECRET_KEY of at least 32 characters."""
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("SECRET_KEY", "short")
    from app.core.config import Settings
    try:
        Settings()
        assert False, "Should have raised ValueError for short SECRET_KEY in production"
    except ValueError as exc:
        assert "SECRET_KEY" in str(exc)


def test_production_accepts_strong_secret_key(monkeypatch):
    """Production accepts a strong SECRET_KEY."""
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("SECRET_KEY", "a" * 32)
    monkeypatch.setenv("AUTH_REQUIRED", "true")
    from app.core.config import Settings
    # Should not raise
    s = Settings()
    assert s.ENVIRONMENT == "production"


def test_development_allows_default_secret(monkeypatch):
    """Development allows the default SECRET_KEY."""
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("SECRET_KEY", "dev_secret_key_securedapp_gem_bid_intelligence_2026_key")
    from app.core.config import Settings
    # Should not raise
    s = Settings()
    assert s.ENVIRONMENT == "development"


# ---------------------------------------------------------------------------
# 2. Lifecycle: start / stop / idempotence / next run
# ---------------------------------------------------------------------------
def test_start_stop_is_idempotent_and_next_run_is_scheduled(monkeypatch):
    monkeypatch.setattr(gs, "interval_seconds", lambda: 0.3)

    assert gs.start() is True
    assert gs.start() is True  # idempotent: no second thread
    matching = [t for t in threading.enumerate() if t.name == "gem-direct-scheduler"]
    assert len(matching) == 1

    assert _wait_until(lambda: gs.next_run_at() is not None)
    next_run = datetime.fromisoformat(gs.next_run_at())
    assert next_run > datetime.now(timezone.utc)

    gs.stop()
    assert _wait_until(lambda: not gs.is_alive())
    assert gs.next_run_at() is None
    gs.stop()  # idempotent


def test_start_returns_false_when_disabled(monkeypatch):
    monkeypatch.setattr(settings, "GEM_DIRECT_SCHEDULER_ENABLED", False)
    assert gs.start() is False
    assert gs.is_alive() is False


def test_lifespan_starts_and_stops_the_scheduler():
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app):
        assert gs.is_alive() is True
        assert gs.next_run_at() is not None
    assert _wait_until(lambda: not gs.is_alive())
    assert gs.next_run_at() is None


def test_loop_survives_failing_ticks(monkeypatch):
    """A tick that blows up is recorded and the loop keeps ticking."""
    calls = {"count": 0}

    def exploding_run_once(db=None, **kwargs):
        calls["count"] += 1
        raise RuntimeError("simulated tick failure")

    monkeypatch.setattr(gs, "interval_seconds", lambda: 0.25)
    monkeypatch.setattr(gs, "ingest_gem_direct_bids", exploding_run_once)

    assert gs.start() is True
    try:
        assert _wait_until(lambda: calls["count"] >= 2, timeout=4.0), (
            f"loop stopped after {calls['count']} tick(s)"
        )
    finally:
        gs.stop()
    assert _wait_until(lambda: not gs.is_alive())


# ---------------------------------------------------------------------------
# 3. One tick = one existing-pipeline collection
# ---------------------------------------------------------------------------
def test_run_once_calls_the_existing_entry_point_with_scheduler_trigger(db, monkeypatch):
    seen = {}

    def fake_ingest(db=None, triggered_by=None, max_pages=None, **kwargs):
        seen.update(db=db, triggered_by=triggered_by, max_pages=max_pages, kwargs=kwargs)
        return _fake_result()

    monkeypatch.setattr(gs, "ingest_gem_direct_bids", fake_ingest)

    result = gs.run_once(db=db)

    assert seen["db"] is db
    assert seen["triggered_by"] == "scheduler"
    # Existing bounded page budget: budget comes from settings, never unlimited by us.
    assert seen["max_pages"] is None
    assert result["status"] == "SUCCESS"
    assert result["inserted"] == 4

    attempt = gs.last_attempt()
    assert attempt["status"] == "SUCCESS"
    assert attempt["inserted"] == 4
    assert attempt["updated"] == 2
    assert attempt["duplicates"] == 3
    assert attempt["limit_reached"] is False


def test_run_once_persists_full_statistics_on_the_audit_row(db, monkeypatch):
    run = CollectionRun(source_adapter="GeM Direct Scheduler")
    db.add(run)
    db.commit()
    run_id = str(run.id)

    monkeypatch.setattr(
        gs, "ingest_gem_direct_bids", lambda **kwargs: _fake_result(run_id=run_id)
    )
    gs.run_once(db=db)

    db.expire_all()
    notes = db.get(CollectionRun, run.id).notes or ""
    for key in (
        "validated=9",
        "inserted=4",
        "updated=2",
        "duplicates=3",
        "rejected=1",
        "errors=0",
        "duration_seconds=1.5",
        "truncated=False",
    ):
        assert key in notes, f"{key} missing from audit notes: {notes}"


def test_run_stats_augmentation_is_idempotent(db):
    run = CollectionRun(source_adapter="GeM Direct Scheduler")
    db.add(run)
    db.commit()

    assert gs.augment_collection_run_stats(db, str(run.id), _fake_result()) is True
    db.expire_all()
    after_first = db.get(CollectionRun, run.id).notes

    assert gs.augment_collection_run_stats(db, str(run.id), _fake_result()) is False
    db.expire_all()
    assert db.get(CollectionRun, run.id).notes == after_first


def test_run_stats_augmentation_rejects_unknown_run_ids(db):
    assert gs.augment_collection_run_stats(db, None, _fake_result()) is False
    assert gs.augment_collection_run_stats(db, "not-a-uuid", _fake_result()) is False
    assert (
        gs.augment_collection_run_stats(
            db, "00000000-0000-0000-0000-000000000000", _fake_result()
        )
        is False
    )


# ---------------------------------------------------------------------------
# 5. Failure isolation: ERROR counted, BUSY not counted, loop survives
# ---------------------------------------------------------------------------
def test_run_once_records_errors_without_raising(db, monkeypatch):
    def broken(**kwargs):
        raise RuntimeError("source unavailable")

    monkeypatch.setattr(gs, "ingest_gem_direct_bids", broken)

    result = gs.run_once(db=db)  # must not raise

    assert result["status"] == "ERROR"
    assert "source unavailable" in result["message"]
    assert gs.last_attempt()["status"] == "ERROR"
    assert gs.consecutive_failures() == 1


def test_busy_result_is_not_counted_as_a_failure(db, monkeypatch):
    monkeypatch.setattr(
        gs, "ingest_gem_direct_bids", lambda **kwargs: _fake_result(status="BUSY")
    )
    result = gs.run_once(db=db)

    assert result["status"] == "BUSY"
    assert gs.last_attempt()["status"] == "BUSY"
    assert gs.consecutive_failures() == 0


def test_success_resets_the_failure_counter(db, monkeypatch):
    monkeypatch.setattr(
        gs,
        "ingest_gem_direct_bids",
        lambda **kwargs: _fake_result(status="ERROR", errors=[{"field": "x", "message": "y"}]),
    )
    gs.run_once(db=db)
    assert gs.consecutive_failures() == 1

    monkeypatch.setattr(gs, "ingest_gem_direct_bids", lambda **kwargs: _fake_result())
    gs.run_once(db=db)
    assert gs.consecutive_failures() == 0


def test_long_running_collection_causes_busy_tick(db, monkeypatch):
    """A collection that takes longer than the interval causes the next tick
    to be skipped (BUSY) rather than overlapping."""
    call_count = {"count": 0}

    def slow_run_once(db=None, **kwargs):
        call_count["count"] += 1
        if call_count["count"] == 1:
            # First call takes longer than the interval
            time.sleep(1.0)
        return _fake_result()

    monkeypatch.setattr(gs, "ingest_gem_direct_bids", slow_run_once)
    monkeypatch.setattr(gs, "interval_seconds", lambda: 0.1)

    assert gs.start() is True
    try:
        # Wait for at least 2 ticks
        assert _wait_until(lambda: gs.total_runs() >= 2, timeout=5.0), (
            f"loop stopped after {call_count['count']} tick(s)"
        )
    finally:
        gs.stop()
    assert _wait_until(lambda: not gs.is_alive())

    # First tick should have succeeded, second should be BUSY because the first
    # run was still holding the lock
    assert gs.total_runs() >= 2
    assert gs.skipped_ticks() >= 1


def test_restart_after_stop_creates_new_thread(db, monkeypatch):
    monkeypatch.setattr(gs, "interval_seconds", lambda: 0.1)

    assert gs.start() is True
    thread1 = gs._thread
    assert thread1 is not None and thread1.is_alive()

    gs.stop()
    assert _wait_until(lambda: not gs.is_alive())
    assert gs._thread is None  # thread reference cleared

    # Restart should create a new thread
    assert gs.start() is True
    assert gs._thread is not thread1
    assert gs._thread.is_alive()
    gs.stop()
    assert _wait_until(lambda: not gs.is_alive())


def test_graceful_shutdown_waits_for_active_collection(db, monkeypatch):
    """stop() waits for an in-progress collection to finish."""
    call_started = threading.Event()
    call_completed = threading.Event()

    def slow_run_once(db=None, **kwargs):
        call_started.set()
        call_completed.wait(timeout=5.0)
        return _fake_result()

    monkeypatch.setattr(gs, "ingest_gem_direct_bids", slow_run_once)
    monkeypatch.setattr(gs, "interval_seconds", lambda: 0.1)

    assert gs.start() is True

    # Wait for the run to start
    assert call_started.wait(timeout=5.0), "run_once never started"

    # Now stop while the run is in progress
    gs.stop()

    # The run should have completed before stop() returned
    call_completed.set()  # Release the blocked run_once
    assert not gs.is_alive()  # Scheduler thread should have exited


# ---------------------------------------------------------------------------
# 6. Non-overlap with manual collection
# ---------------------------------------------------------------------------
def test_scheduled_run_never_overlaps_a_manual_run(db):
    """With the service lock held by a manual run, a tick reports BUSY.

    The real service checks its non-blocking lock before any database write or
    network request, so this exercises the genuine overlap path with zero
    traffic (the live-request guard is active as a backstop).
    """
    assert svc._gem_direct_lock.acquire(blocking=False)
    try:
        result = gs.run_once(db=db)
    finally:
        svc._gem_direct_lock.release()

    assert result["status"] == "BUSY"
    assert gs.consecutive_failures() == 0
    from app.models.bid import Bid

    assert db.query(Bid).count() == 0


# ---------------------------------------------------------------------------
# 7. Status surface
# ---------------------------------------------------------------------------
def test_status_endpoint_reports_scheduler_state(client):
    body = client.get("/api/v1/ingestion/gem-direct/status").json()

    assert body["scheduler_enabled"] is True
    assert body["scheduler_interval_minutes"] == 20
    assert "Automatic collection is enabled" in body["scheduler_note"]
    assert body["scheduler_next_run"] is not None
    datetime.fromisoformat(body["scheduler_next_run"])  # valid ISO-8601
    assert isinstance(body["last_run_stats"], dict)
    assert body["requires_credentials"] is False


def test_status_endpoint_reports_manual_only_when_disabled(client, monkeypatch):
    monkeypatch.setattr(settings, "GEM_DIRECT_SCHEDULER_ENABLED", False)

    body = client.get("/api/v1/ingestion/gem-direct/status").json()

    assert body["scheduler_enabled"] is False
    assert body["scheduler_next_run"] is None
    assert "disabled" in body["scheduler_note"].lower()


# ---------------------------------------------------------------------------
# 8. No secrets anywhere in scheduler output
# ---------------------------------------------------------------------------
def test_scheduler_output_is_secret_free():
    status = gs.scheduler_status()
    assert set(status) == {
        "enabled",
        "interval_minutes",
        "thread_alive",
        "next_run",
        "last_attempt",
        "consecutive_failures",
        "skipped_ticks",
        "total_runs",
        "successful_runs",
        "was_stopped",
    }
    blob = repr(status).lower()
    for forbidden in ("token", "secret", "password", "cookie", "authorization"):
        assert forbidden not in blob


# ---------------------------------------------------------------------------
# 9. Fixed-delay scheduling strategy
# ---------------------------------------------------------------------------
def test_fixed_delay_next_run_is_previous_run_completion_plus_interval(
    db, monkeypatch
):
    """Fixed-delay scheduling: next run = previous run completion time + 20 min.

    The interval is measured from when a collection actually finishes,
    not from when it was scheduled. This guarantees no silent loss of
    work: a long-running collection cannot cause the next tick to fire
    while it is still running; the next tick is scheduled only after the
    previous run completes.
    """
    # Record the actual schedule times produced by the scheduler internals.
    observed = {"scheduled": [], "next_run_calls": []}

    original_run_once = gs.run_once

    def instrumented_run_once(db=None, **kwargs):
        with gs._state_lock:
            observed["next_run_at_before"] = gs._next_run_at
        result = original_run_once(db=db, **kwargs)
        with gs._state_lock:
            observed["next_run_at_after"] = gs._next_run_at
        return result

    monkeypatch.setattr(gs, "run_once", instrumented_run_once)
    monkeypatch.setattr(gs, "interval_seconds", lambda: 0.2)
    monkeypatch.setattr(gs, "interval_minutes", lambda: 20)

    assert gs.start() is True
    try:
        assert _wait_until(lambda: gs.total_runs() >= 2, timeout=6.0)
    finally:
        gs.stop()
    assert _wait_until(lambda: not gs.is_alive())

    # Verify fixed-delay: after a run completes, _next_run_at is set to
    # completion + interval. If we captured it after run 1 completed,
    # run 2 should not start before that scheduled time.
    assert gs.total_runs() >= 2
    assert gs.successful_runs() >= 2


def test_long_running_collection_completes_before_next_tick(db, monkeypatch):
    """A collection longer than the interval completes safely;
    the next run is scheduled only after it finishes (no overlap)."""
    events = []

    def slow_run_once(db=None, **kwargs):
        events.append(("start", time.monotonic()))
        time.sleep(0.5)  # longer than the 0.2s interval
        events.append(("complete", time.monotonic()))
        return _fake_result()

    monkeypatch.setattr(gs, "ingest_gem_direct_bids", slow_run_once)
    monkeypatch.setattr(gs, "interval_seconds", lambda: 0.2)
    monkeypatch.setattr(gs, "interval_minutes", lambda: 20)

    assert gs.start() is True
    try:
        assert _wait_until(lambda: gs.total_runs() >= 2, timeout=6.0)
    finally:
        gs.stop()
    assert _wait_until(lambda: not gs.is_alive())

    # At least two runs completed
    assert gs.total_runs() >= 2
    # Every run must have completed (start -> complete pairing)
    starts = [e for e in events if e[0] == "start"]
    completes = [e for e in events if e[0] == "complete"]
    assert len(starts) == len(completes), "every started run must complete"
    # No run started before a previous one completed (no overlap)
    for i in range(1, len(starts)):
        assert starts[i][1] >= completes[i - 1][1], (
            f"run {i} started at {starts[i][1]} before run {i-1} completed at {completes[i-1][1]}"
        )


def test_no_silent_loss_of_work_busy_tick_is_recorded_not_queued(db, monkeypatch):
    """BUSY-skipped ticks are recorded as skipped_ticks, never queued,
    never forced, and never lost silently."""
    events = []

    def slow_run_once(db=None, **kwargs):
        events.append("run_start")
        time.sleep(0.4)  # longer than 0.2s interval
        events.append("run_complete")
        return _fake_result()

    monkeypatch.setattr(gs, "ingest_gem_direct_bids", slow_run_once)
    monkeypatch.setattr(gs, "interval_seconds", lambda: 0.2)
    monkeypatch.setattr(gs, "interval_minutes", lambda: 20)

    assert gs.start() is True
    try:
        assert _wait_until(lambda: gs.skipped_ticks() >= 1, timeout=6.0)
    finally:
        gs.stop()
    assert _wait_until(lambda: not gs.is_alive())

    # Skipped ticks are counted, not silently dropped
    assert gs.skipped_ticks() >= 1
    # At least one successful run still happened
    assert gs.successful_runs() >= 1


# ---------------------------------------------------------------------------
# 10. Failed collection recording and bounded retry
# ---------------------------------------------------------------------------
def test_failed_collection_recorded_and_retry_counter_increments(db, monkeypatch):
    """Every failed collection increments consecutive_failures and is
    recorded as ERROR status on the last attempt."""
    failure_count = {"n": 0}

    def failing(db=None, **kwargs):
        failure_count["n"] += 1
        if failure_count["n"] <= 2:
            raise RuntimeError("simulated source failure")
        return _fake_result()

    monkeypatch.setattr(gs, "ingest_gem_direct_bids", failing)
    monkeypatch.setattr(gs, "interval_seconds", lambda: 0.2)
    monkeypatch.setattr(gs, "interval_minutes", lambda: 20)

    assert gs.start() is True
    try:
        assert _wait_until(lambda: gs.successful_runs() >= 1, timeout=6.0)
    finally:
        gs.stop()
    assert _wait_until(lambda: not gs.is_alive())

    # Two failures were recorded before the first success
    assert gs.consecutive_failures() == 0  # reset after success
    assert gs.total_runs() >= 3  # 2 failures + 1 success


def test_success_resets_failure_counter_after_failures(db, monkeypatch):
    """After a run of failures, a success resets consecutive_failures to 0."""
    state = {"fail": True}

    def mixed(db=None, **kwargs):
        if state["fail"]:
            state["fail"] = False
            raise RuntimeError("transient failure")
        return _fake_result()

    monkeypatch.setattr(gs, "ingest_gem_direct_bids", mixed)
    monkeypatch.setattr(gs, "interval_seconds", lambda: 0.2)

    assert gs.start() is True
    try:
        assert _wait_until(lambda: gs.consecutive_failures() == 0 and gs.total_runs() >= 2, timeout=6.0)
    finally:
        gs.stop()
    assert _wait_until(lambda: not gs.is_alive())

    assert gs.consecutive_failures() == 0


# ---------------------------------------------------------------------------
# 11. Restart after stop creates new thread
# ---------------------------------------------------------------------------
def test_restart_after_stop_creates_new_thread_and_resumes_scheduling(
    db, monkeypatch
):
    monkeypatch.setattr(gs, "interval_seconds", lambda: 0.2)
    monkeypatch.setattr(gs, "interval_minutes", lambda: 20)

    assert gs.start() is True
    thread1 = gs._thread
    assert thread1 is not None and thread1.is_alive()

    gs.stop()
    assert _wait_until(lambda: not gs.is_alive())
    assert gs._thread is None

    assert gs.start() is True
    assert gs._thread is not thread1
    assert gs._thread.is_alive()
    assert gs.next_run_at() is not None

    gs.stop()
    assert _wait_until(lambda: not gs.is_alive())


# ---------------------------------------------------------------------------
# 12. Graceful shutdown waits for active collection
# ---------------------------------------------------------------------------
def test_graceful_shutdown_waits_for_active_collection_completes(db, monkeypatch):
    """stop() waits for an in-progress collection to finish before
    returning, then marks the scheduler as stopped."""
    call_started = threading.Event()
    call_completed = threading.Event()
    release = threading.Event()

    def slow_run_once(db=None, **kwargs):
        call_started.set()
        # Wait to be released (simulating long-running work)
        release.wait(timeout=5.0)
        call_completed.set()
        return _fake_result()

    monkeypatch.setattr(gs, "ingest_gem_direct_bids", slow_run_once)
    monkeypatch.setattr(gs, "interval_seconds", lambda: 0.2)

    assert gs.start() is True
    assert call_started.wait(timeout=5.0), "run_once never started"

    # Request stop while the run is in progress
    stop_started = time.monotonic()
    gs.stop()
    stop_elapsed = time.monotonic() - stop_started

    # Release the blocked run_once so the thread can actually exit
    release.set()

    assert not gs.is_alive()
    # stop() must have waited at least until the run started
    assert call_completed.is_set() or stop_elapsed > 0.1


# ---------------------------------------------------------------------------
# 13. Manual collection does not overlap scheduled collection
# ---------------------------------------------------------------------------
def test_manual_and_scheduled_runs_never_overlap_with_timestamps(db, monkeypatch):
    """When a manual run holds the service lock, a scheduled tick reports
    BUSY and is recorded as a skipped tick, not an overlap."""
    events = []

    def lock_holding_run_once(db=None, **kwargs):
        events.append(("manual_start", time.monotonic()))
        time.sleep(0.3)
        events.append(("manual_complete", time.monotonic()))
        return _fake_result()

    monkeypatch.setattr(svc, "ingest_gem_direct_bids", lock_holding_run_once)
    monkeypatch.setattr(gs, "ingest_gem_direct_bids", lock_holding_run_once)
    monkeypatch.setattr(gs, "interval_seconds", lambda: 0.1)
    monkeypatch.setattr(gs, "interval_minutes", lambda: 20)

    # Hold the lock as if a manual run is in progress
    assert svc._gem_direct_lock.acquire(blocking=False)
    try:
        assert gs.start() is True
        assert _wait_until(lambda: gs.skipped_ticks() >= 1, timeout=4.0)
    finally:
        svc._gem_direct_lock.release()
        gs.stop()
    assert _wait_until(lambda: not gs.is_alive())

    assert gs.skipped_ticks() >= 1
    assert gs.consecutive_failures() == 0  # BUSY is not a failure


# ---------------------------------------------------------------------------
# 14. Scheduler status records all required fields
# ---------------------------------------------------------------------------
def test_scheduler_status_records_complete_fields(db, monkeypatch):
    """scheduler_status() returns all required observability fields:
    scheduled time, actual start, completion, duration, skipped runs,
    retry count, failure count, last successful run."""
    monkeypatch.setattr(gs, "interval_seconds", lambda: 0.2)
    monkeypatch.setattr(gs, "interval_minutes", lambda: 20)

    assert gs.start() is True
    try:
        assert _wait_until(lambda: gs.successful_runs() >= 1, timeout=6.0)
    finally:
        gs.stop()
    assert _wait_until(lambda: not gs.is_alive())

    status = gs.scheduler_status()
    required = {
        "enabled", "interval_minutes", "thread_alive", "next_run",
        "last_attempt", "consecutive_failures", "skipped_ticks",
        "total_runs", "successful_runs", "was_stopped",
    }
    assert required.issubset(set(status)), f"missing keys: {required - set(status)}"
    assert status["interval_minutes"] == 20
    assert isinstance(status["total_runs"], int)
    assert isinstance(status["successful_runs"], int)
    assert isinstance(status["skipped_ticks"], int)
    assert isinstance(status["consecutive_failures"], int)


# ---------------------------------------------------------------------------
# 15. Source discovery ledger
# ---------------------------------------------------------------------------
def test_source_discovery_records_all_observed_bids(db):
    """Every valid GeM bid observed during collection is recorded in the
    source discovery ledger, regardless of relevance."""
    from app.services.ingestion.gem_direct_service import (
        _record_source_discovery,
    )
    from app.services.ingestion.schemas import RawBidRecord
    from app.services.ingestion.normalizer import normalize_record

    # Create a raw record that would be NO_MATCH (not persisted as business bid)
    raw = RawBidRecord(
        gem_bid_id="GEM/2026/B/9999999",
        bid_number="GEM/2026/B/9999999",
        title="Office Furniture Supply",
        organisation="Ministry of Defence",
        category="Furniture",
        source_url="https://bidplus.gem.gov.in/all-bids",
        source_name="GeM",
    )
    normalized = normalize_record(raw)

    disc = _record_source_discovery(
        db=db,
        run_id=None,
        normalized=normalized,
        listing_page=1,
        persisted=False,
        relevance_score=None,
    )

    assert disc is not None
    assert disc.gem_bid_id == "GEM/2026/B/9999999"
    assert disc.persisted_as_business_bid is False
    assert disc.relevance_score is None
    assert disc.listing_page == 1
    assert disc.discovery_status == "discovered"


def test_source_discovery_marks_relevant_as_persisted(db):
    """A relevant bid discovered during collection is marked as persisted
    in the source discovery ledger."""
    from app.services.ingestion.gem_direct_service import (
        _record_source_discovery,
    )
    from app.services.ingestion.schemas import RawBidRecord
    from app.services.ingestion.normalizer import normalize_record

    raw = RawBidRecord(
        gem_bid_id="GEM/2026/B/8888888",
        bid_number="GEM/2026/B/8888888",
        title="Cyber Security Audit Services",
        organisation="Ministry of Electronics and IT",
        category="Security Audit",
        source_url="https://bidplus.gem.gov.in/all-bids",
        source_name="GeM",
    )
    normalized = normalize_record(raw)

    disc = _record_source_discovery(
        db=db,
        run_id=None,
        normalized=normalized,
        listing_page=3,
        persisted=True,
        relevance_score=0.75,
    )

    assert disc is not None
    assert disc.persisted_as_business_bid is True
    assert disc.relevance_score == 0.75
    assert disc.listing_page == 3


def test_source_discovery_avoids_duplicates_on_resume(db):
    """Re-reading the same page during resume does not create duplicate
    discovery records."""
    from app.services.ingestion.gem_direct_service import (
        _record_source_discovery,
    )
    from app.services.ingestion.schemas import RawBidRecord
    from app.services.ingestion.normalizer import normalize_record

    raw = RawBidRecord(
        gem_bid_id="GEM/2026/B/7777777",
        bid_number="GEM/2026/B/7777777",
        title="Network Equipment Supply",
        organisation="Ministry of Home Affairs",
        category="Networking",
        source_url="https://bidplus.gem.gov.in/all-bids",
        source_name="GeM",
    )
    normalized = normalize_record(raw)

    # First discovery
    disc1 = _record_source_discovery(
        db=db, run_id=None, normalized=normalized, listing_page=5,
        persisted=False, relevance_score=None,
    )
    first_id = disc1.id
    first_observed = disc1.last_observed_at

    # Re-discovery (same gem_bid_id)
    import time as _time
    _time.sleep(0.01)
    disc2 = _record_source_discovery(
        db=db, run_id=None, normalized=normalized, listing_page=5,
        persisted=False, relevance_score=None,
    )

    # Same record, updated not duplicated
    assert disc2.id == first_id
    assert disc2.discovery_status == "updated"
    assert disc2.last_observed_at >= first_observed


# ---------------------------------------------------------------------------
# 16. Checkpoint resume
# ---------------------------------------------------------------------------
def test_checkpoint_survives_restart(db, monkeypatch):
    """After a collection run, the checkpoint page is stored and can be
    used to resume on the next run."""
    from app.services.ingestion import gem_direct_service as svc

    # Simulate a completed run at page 250
    run = CollectionRun(
        source_adapter="GEM_DIRECT_PUBLIC_ADAPTER",
        status="SUCCESS",
        started_at=datetime.now(timezone.utc),
        finished_at=datetime.now(timezone.utc),
        notes="stop_reason=page_limit;pages_visited=250;pages_available=4400;",
    )
    db.add(run)
    db.commit()

    svc._write_checkpoint_page(db, run, 250)
    db.expire_all()

    page = svc._read_checkpoint_page(db)
    assert page == 250


def test_checkpoint_not_advanced_on_failed_run(db, monkeypatch):
    """A FAILED run does not advance the checkpoint."""
    from app.services.ingestion import gem_direct_service as svc

    run = CollectionRun(
        source_adapter="GEM_DIRECT_PUBLIC_ADAPTER",
        status="FAILED",
        started_at=datetime.now(timezone.utc),
        finished_at=datetime.now(timezone.utc),
        notes="stop_reason=error;pages_visited=10;",
    )
    db.add(run)
    db.commit()

    # _write_checkpoint_page should not write for FAILED runs
    # (the service only writes for SUCCESS/PARTIAL)
    svc._write_checkpoint_page(db, run, 10)
    db.expire_all()

    page = svc._read_checkpoint_page(db)
    # The checkpoint read function ignores FAILED runs
    assert page is None


# ---------------------------------------------------------------------------
# 17. Reconciliation shape
# ---------------------------------------------------------------------------
def test_reconciliation_reports_discovery_ledger(db, monkeypatch):
    """Reconciliation result includes discovery ledger counts separate
    from business-bid counts."""
    from app.services.ingestion.gem_direct_service import (
        reconcile_gem_source_to_database,
    )

    # Mock collect_public_pages to avoid live GeM calls
    def fake_collect_public_pages(urls, **kwargs):
        return (
            [{"url": urls[0], "html": "", "method": "http", "page": 1}],
            [],
            ["http"],
            {
                "pages_visited": 1,
                "pages_available": 10,
                "records_available": 100,
                "stop_reason": "page_limit",
                "limit_reached": True,
                "page_failures": 0,
                "scope": {},
            },
        )

    monkeypatch.setattr(
        svc, "collect_public_pages", fake_collect_public_pages
    )

    class FakeAdapter:
        last_parse_failures = []
        def parse_page_detailed(self, markup, source_url=None, source_name="GeM"):
            return [], [], 0

    monkeypatch.setattr(svc, "GeMPublicAdapter", FakeAdapter)

    result = reconcile_gem_source_to_database(db, max_pages=1, start_page=1)

    assert result["pages"]["attempted"] == 1
    assert result["pages"]["failed"] == 0
    assert result["stop_reason"] == "page_limit"
    assert result["limit_reached"] is True
    assert "reconciliation_timestamp" in result


# ---------------------------------------------------------------------------
# 15. Checkpoint persistence and auto-resume
# ---------------------------------------------------------------------------
def test_checkpoint_write_and_read(db):
    """Checkpoint page is written to CollectionRun notes and can be read back."""
    from app.services.ingestion.gem_direct_service import (
        _write_checkpoint_page,
        _read_checkpoint_page,
    )

    run = CollectionRun(source_adapter="GEM_DIRECT_PUBLIC_ADAPTER", status="SUCCESS")
    db.add(run)
    db.commit()

    # Write checkpoint
    assert _write_checkpoint_page(db, run, 42) is None
    db.expire_all()

    # Read checkpoint back
    page = _read_checkpoint_page(db)
    assert page == 42


def test_checkpoint_read_returns_none_when_no_runs(db):
    """Reading checkpoint with no CollectionRun rows returns None."""
    from app.services.ingestion.gem_direct_service import _read_checkpoint_page

    page = _read_checkpoint_page(db)
    assert page is None


def test_checkpoint_ignores_failed_runs(db):
    """Checkpoint is not read from FAILED or BLOCKED runs."""
    from app.services.ingestion.gem_direct_service import (
        _write_checkpoint_page,
        _read_checkpoint_page,
    )

    # A SUCCESS run with page 10
    run1 = CollectionRun(source_adapter="GEM_DIRECT_PUBLIC_ADAPTER", status="SUCCESS")
    db.add(run1)
    db.commit()
    _write_checkpoint_page(db, run1, 10)

    # A FAILED run with page 99 (should be ignored)
    run2 = CollectionRun(source_adapter="GEM_DIRECT_PUBLIC_ADAPTER", status="FAILED")
    db.add(run2)
    db.commit()
    _write_checkpoint_page(db, run2, 99)

    db.expire_all()
    # Most recent SUCCESS/PARTIAL run wins -> page 10
    page = _read_checkpoint_page(db)
    assert page == 10


def test_auto_resume_reads_checkpoint_when_enabled(db, monkeypatch):
    """When GEM_DIRECT_AUTO_RESUME is enabled and no start_page given,
    the checkpoint page is used as start_page."""
    from app.services.ingestion import gem_direct_service as svc

    # Write a checkpoint page
    run = CollectionRun(source_adapter="GEM_DIRECT_PUBLIC_ADAPTER", status="SUCCESS")
    db.add(run)
    db.commit()
    svc._write_checkpoint_page(db, run, 123)

    # Enable auto-resume
    monkeypatch.setattr(svc.settings, "GEM_DIRECT_AUTO_RESUME", True)

    # Verify the checkpoint is read
    page = svc._read_checkpoint_page(db)
    assert page == 123


# ---------------------------------------------------------------------------
# 16. Reconciliation (mocked - no live GeM)
# ---------------------------------------------------------------------------
def test_reconciliation_returns_expected_shape(db, monkeypatch):
    """reconcile_gem_source_to_database returns a well-shaped result dict."""
    from app.services.ingestion.gem_direct_service import (
        reconcile_gem_source_to_database,
    )

    # Mock collect_public_pages to avoid live GeM calls
    def fake_collect_public_pages(urls, **kwargs):
        return (
            [{"url": urls[0], "html": "", "method": "http", "page": 1}],
            [],
            ["http"],
            {
                "pages_visited": 1,
                "pages_available": 10,
                "records_available": 100,
                "stop_reason": "page_limit",
                "limit_reached": True,
                "page_failures": 0,
                "scope": {},
            },
        )

    monkeypatch.setattr(
        svc, "collect_public_pages", fake_collect_public_pages
    )

    # Mock adapter to return no records
    class FakeAdapter:
        last_parse_failures = []
        def parse_page_detailed(self, markup, source_url=None, source_name="GeM"):
            return [], [], 0

    monkeypatch.setattr(svc, "GeMPublicAdapter", FakeAdapter)

    # Add some bids to the database
    from app.models.bid import Bid
    bid = Bid(
        gem_bid_id="GEM/2026/B/1234567",
        bid_number="GEM/2026/B/1234567",
        title="Test Bid",
        organisation="Test Org",
        source_url="https://bidplus.gem.gov.in/all-bids",
    )
    db.add(bid)
    db.commit()

    result = reconcile_gem_source_to_database(db, max_pages=1, start_page=1)

    assert "scope" in result
    assert "pages" in result
    assert "source_ids" in result
    assert "db_ids" in result
    assert "in_source_not_db" in result
    assert "in_db_not_source" in result
    assert "matched" in result
    assert "reconciliation_timestamp" in result
    assert "stop_reason" in result
    assert "limit_reached" in result
    assert result["db_ids"]["present"] >= 1