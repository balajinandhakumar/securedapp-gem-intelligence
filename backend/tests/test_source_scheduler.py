"""
Scheduler tests: due-source selection, sequential single-threaded runs with
per-source failure isolation, restart-safe timing, and opt-in starting.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import app.services.sources.scheduler as sched
from app.models.source import DataSource
from app.services.sources.scheduler import (
    _due,
    _interval_seconds,
    next_run_at,
    run_due_sources,
    scheduler_status,
    start,
    stop,
)


def _source(
    db,
    source_id,
    *,
    enabled=True,
    interval_minutes=60,
    last_attempt: datetime | None = None,
):
    source = DataSource(
        source_id=source_id,
        name=f"Source {source_id}",
        source_type="json_api",
        adapter_key="json_api",
        enabled=enabled,
        collection_interval_minutes=interval_minutes,
        config={"url": "https://tenders.example.com/api/tenders", "records_path": "items", "field_map": {}},
        last_attempt_at=last_attempt,
    )
    db.add(source)
    db.commit()
    db.refresh(source)
    return source


def test_interval_seconds_floored_at_minimum():
    assert _interval_seconds(SimpleNamespace(collection_interval_minutes=1)) == 300
    assert _interval_seconds(SimpleNamespace(collection_interval_minutes=-5)) == 300
    assert _interval_seconds(SimpleNamespace(collection_interval_minutes=5)) == 300
    assert _interval_seconds(SimpleNamespace(collection_interval_minutes=60)) == 3600
    assert _interval_seconds(SimpleNamespace(collection_interval_minutes=None)) == 3600


def test_due_predicate(db):
    now = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)
    old = _source(db, "s-old", last_attempt=now - timedelta(minutes=120))
    recent = _source(db, "s-recent", last_attempt=now - timedelta(minutes=5))
    never = _source(db, "s-never", last_attempt=None)
    due_ids = {s.source_id for s in _due([old, recent, never], now)}
    assert due_ids == {"s-old", "s-never"}


def test_next_run_at_never_ran_returns_something_soon():
    source = DataSource(collection_interval_minutes=60, enabled=True)
    value = next_run_at(source)
    assert value is not None
    assert datetime.fromisoformat(value) > datetime.now(timezone.utc)


def test_next_run_at_after_attempt(db):
    attempt = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)
    source = _source(db, "s1", last_attempt=attempt)
    value = next_run_at(source)
    # SQLite round-trips datetimes as naive; compare instants.
    assert datetime.fromisoformat(value).timestamp() == (attempt + timedelta(minutes=60)).timestamp()


def test_next_run_at_none_and_disabled():
    assert next_run_at(None) is None
    source = DataSource(collection_interval_minutes=60, enabled=False, last_attempt_at=datetime.now(timezone.utc))
    assert next_run_at(source) is None


def test_run_due_sources_selects_only_due(db, monkeypatch):
    now = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)
    _source(db, "s-due", last_attempt=now - timedelta(minutes=120))
    _source(db, "s-recent", last_attempt=now - timedelta(minutes=5))
    _source(db, "s-disabled", enabled=False, last_attempt=None)

    calls = []

    def fake_run(db, source, **kwargs):
        calls.append(source.source_id)
        return {"status": "SUCCESS", "inserted": 1}

    monkeypatch.setattr(sched, "run_source_sync", fake_run)
    summary = run_due_sources(db, now=now)
    assert "s-due" in calls
    assert "s-recent" not in calls
    assert "s-disabled" not in calls
    assert summary["ran"] == 1
    assert summary["failed"] == 0
    assert summary["scheduler"] is True


def test_run_due_sources_runs_all_due_sequentially(db, monkeypatch):
    now = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)
    _source(db, "s-a", last_attempt=now - timedelta(hours=3))
    _source(db, "s-b", last_attempt=now - timedelta(hours=3))

    order = []

    def fake_run(db, source, **kwargs):
        assert kwargs.get("trigger") == "scheduler"
        order.append(source.source_id)
        return {"status": "SUCCESS", "inserted": 0}

    monkeypatch.setattr(sched, "run_source_sync", fake_run)
    summary = run_due_sources(db, now=now)
    assert summary["ran"] == 2
    assert order == ["s-a", "s-b"]


def test_run_due_sources_isolates_failures(db, monkeypatch):
    now = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)
    _source(db, "s-ok", last_attempt=now - timedelta(hours=1))
    _source(db, "s-bad", last_attempt=now - timedelta(hours=1))

    def fake_run(db, source, **kwargs):
        if source.source_id == "s-bad":
            raise RuntimeError("boom")
        return {"status": "SUCCESS", "inserted": 1}

    monkeypatch.setattr(sched, "run_source_sync", fake_run)
    summary = run_due_sources(db, now=now)
    # Only completed runs increment "ran"; a crashed source is still failed.
    assert summary["failed"] == 1
    statuses = {r["status"] for r in summary["results"]}
    assert statuses == {"SUCCESS", "ERROR"}


def test_start_returns_false_when_disabled(monkeypatch):
    stop()
    monkeypatch.setattr(sched, "settings", SimpleNamespace(SOURCE_SCHEDULER_ENABLED=False, SOURCE_SCHEDULER_TICK_SECONDS=30))
    assert start() is False
    stop()


def test_scheduler_status_reflects_disabled(monkeypatch):
    monkeypatch.setattr(sched, "settings", SimpleNamespace(SOURCE_SCHEDULER_ENABLED=False, SOURCE_SCHEDULER_TICK_SECONDS=30))
    status = scheduler_status()
    assert isinstance(status, dict)
    assert status["enabled"] is False
    assert status["tick_seconds"] == 30