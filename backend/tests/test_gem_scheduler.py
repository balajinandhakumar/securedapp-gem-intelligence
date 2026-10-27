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
def test_scheduler_enabled_by_default_at_sixty_minutes():
    assert settings.GEM_DIRECT_SCHEDULER_ENABLED is True
    assert settings.GEM_DIRECT_SCHEDULER_INTERVAL_MINUTES == 60
    assert gs.is_enabled() is True
    assert gs.interval_minutes() == 60
    assert gs.interval_seconds() == 3600.0


def test_env_example_declares_enabled_sixty_minutes():
    import os

    env_path = os.path.join(
        os.path.dirname(__file__), "..", "..", ".env.example"
    )
    with open(env_path, encoding="utf-8") as handle:
        content = handle.read()
    assert "GEM_DIRECT_SCHEDULER_ENABLED=true" in content
    assert "GEM_DIRECT_SCHEDULER_INTERVAL_MINUTES=60" in content


def test_interval_is_clamped_to_at_least_one_minute(monkeypatch):
    monkeypatch.setattr(settings, "GEM_DIRECT_SCHEDULER_INTERVAL_MINUTES", 0)
    assert gs.interval_minutes() == 1
    monkeypatch.setattr(settings, "GEM_DIRECT_SCHEDULER_INTERVAL_MINUTES", "junk")
    assert gs.interval_minutes() == 60


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

    def exploding_run_once(db=None):
        calls["count"] += 1
        raise RuntimeError("simulated tick failure")

    monkeypatch.setattr(gs, "interval_seconds", lambda: 0.25)
    monkeypatch.setattr(gs, "run_once", exploding_run_once)

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
    assert body["scheduler_interval_minutes"] == 60
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
    }
    blob = repr(status).lower()
    for forbidden in ("token", "secret", "password", "cookie", "authorization"):
        assert forbidden not in blob


# ---------------------------------------------------------------------------
# Bid lifecycle through the scheduled path: new -> unchanged -> updated -> closed
# ---------------------------------------------------------------------------
def test_scheduled_ticks_cover_the_full_bid_lifecycle(db, monkeypatch):
    """Three real scheduled ticks through the canned public listing.

    Uses the production service (not a fake) with the HTTP/browser boundaries
    replaced by fixture markup, exactly as the manual-path tests do, so the
    scheduler path proves the same lifecycle: a first tick INSERTS (new), a
    repeat tick leaves UNCHANGED records alone, a changed record is UPDATED in
    place, and a bid whose deadline has passed is reported CLOSED at read time
    while never being deleted.
    """
    from datetime import datetime, timedelta, timezone
    from unittest.mock import MagicMock, patch

    from app.models.bid import Bid
    from app.services.bid_views import serialise_bid
    from app.services.ingestion import gem_direct_service as svc
    from tests.test_gem_direct_service import LISTING_HTML, canned_listing

    def tick(html):
        with canned_listing(html):
            return gs.run_once(db=db)

    with patch.object(svc, "_render_with_browser", side_effect=AssertionError(
        "browser render must not be needed when the HTTP markup already parses"
    )), patch.object(svc, "process_bid_intelligence") as mock_intel:
        # --- 1. new -----------------------------------------------------
        first = tick(LISTING_HTML)
        assert first["status"] == "SUCCESS"
        assert first["inserted"] == 2
        assert first["duplicates"] == 0
        assert db.query(Bid).count() == 2

        # --- 2. unchanged ----------------------------------------------
        second = tick(LISTING_HTML)
        assert second["inserted"] == 0
        assert second["updated"] == 0
        assert second["duplicates"] == 2
        assert db.query(Bid).count() == 2

        # --- 3. updated (content changed, refreshed in place) -----------
        changed = LISTING_HTML.replace(
            "Smart Contract Security Audit and Vulnerability Detection",
            "Smart Contract Security Audit with Thermal Imaging",
        )
        third = tick(changed)
        assert third["inserted"] == 0
        assert third["duplicates"] == 2
        assert third["updated"] == 1
        assert db.query(Bid).count() == 2
        bid = db.query(Bid).filter_by(bid_number="GEM/2026/B/7845020").one()
        assert "thermal imaging" in bid.title.lower()

        # intelligence ran for created + updated bids, not for duplicates
        assert mock_intel.call_count == 3

    # --- 4. closed: deadline passed, reported CLOSED, never deleted ------
    bid.closing_date = datetime.now(timezone.utc) - timedelta(days=3)
    db.commit()
    db.refresh(bid)
    view = serialise_bid(bid, None)
    assert view["deadline_status"] == "CLOSED"
    assert db.query(Bid).count() == 2  # closed bids are retained

    # one audit row per scheduled tick, each with persisted statistics
    runs = db.query(CollectionRun).all()
    assert len(runs) == 3
    for run in runs:
        assert "validated=" in (run.notes or "")
        assert "inserted=" in (run.notes or "")

    attempt = gs.last_attempt()
    assert attempt["status"] == "SUCCESS"
    assert attempt["updated"] == 1


# ---------------------------------------------------------------------------
# 9. Duration consistency: duration_seconds in notes matches timestamps
# ---------------------------------------------------------------------------
def test_duration_seconds_matches_started_finished_at(db, monkeypatch):
    """
    Regression test: ``duration_seconds`` recorded in CollectionRun.notes must
    match ``finished_at - started_at`` within a small tolerance.

    Previously ``start_time = time.perf_counter()`` was captured before page
    collection while ``started_at = datetime.now(timezone.utc)`` was captured
    after it, causing duration_seconds to systematically overstate the run
    duration. Both timestamps are now captured at the same point.
    """
    from datetime import datetime, timedelta, timezone
    from unittest.mock import patch

    from app.models.bid import Bid
    from app.services.ingestion import gem_direct_service as svc
    from tests.test_gem_direct_service import LISTING_HTML, canned_listing

    with patch.object(svc, "_render_with_browser", side_effect=AssertionError()), \
         patch.object(svc, "process_bid_intelligence"), \
         canned_listing(LISTING_HTML):
        result = gs.run_once(db=db)

    assert result["status"] == "SUCCESS"
    run_id = result["run_id"]
    assert run_id is not None

    db.expire_all()
    run = db.get(CollectionRun, run_id)
    assert run is not None
    assert run.started_at is not None
    assert run.finished_at is not None

    # Parse duration_seconds from notes
    notes = run.notes or ""
    duration_from_notes = None
    for part in notes.split(";"):
        if part.startswith("duration_seconds="):
            duration_from_notes = float(part.split("=", 1)[1])
            break
    assert duration_from_notes is not None, f"duration_seconds missing from notes: {notes}"

    # Compute duration from timestamps
    duration_from_timestamps = (run.finished_at - run.started_at).total_seconds()

    # They should match within 2 seconds (processing overhead, clock resolution)
    assert abs(duration_from_notes - duration_from_timestamps) < 2.0, (
        f"duration_seconds={duration_from_notes} does not match "
        f"finished_at - started_at={duration_from_timestamps}s"
    )
