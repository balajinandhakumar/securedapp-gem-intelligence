"""
Runner tests: one configured source drives the existing pipeline end-to-end
(collection -> canonical records -> validation -> normalization -> dedupe ->
DB persist -> intelligence wiring), with correct run/source counters and
per-source locking.
"""
from __future__ import annotations

import json

import pytest

from app.models.bid import Bid
from app.models.source import DataSource, SourceRun
from app.services.sources.base import SourceConfigError
from app.services.sources.runner import run_source_sync
from tests.source_test_utils import FakeResponse, FakeSession, make_resolver

HOST = "tenders.example.com"
API_URL = f"https://{HOST}/api/tenders"


@pytest.fixture(autouse=True)
def _patch_dns(monkeypatch):
    from app.services import sources as package

    monkeypatch.setattr(package.safe_http, "_resolve_host", make_resolver())
    yield


def _json_source(db, source_id="src-1", **overrides):
    source = DataSource(
        source_id=source_id,
        name="JSON Tenders",
        source_type="json_api",
        adapter_key="json_api",
        enabled=overrides.pop("enabled", True),
        collection_interval_minutes=60,
        config={
            "url": API_URL,
            "records_path": "items",
            "field_map": {
                "title": "title",
                "source_url": "permalink",
                "closing_date": "deadline",
                "organisation": "agency",
                "gem_bid_id": "id",
            },
            "max_records": 500,
            "max_pages": 2,
        },
        **overrides,
    )
    db.add(source)
    db.commit()
    db.refresh(source)
    return source


def _items_page(n=3):
    return {
        "items": [
            {
                "title": f"Network security audit {i}",
                "permalink": f"{API_URL.replace('/api', '')}/t/{i}",
                "deadline": "2026-03-01",
                "agency": "Cyber Cell",
                "id": f"AUD-{i}",
            }
            for i in range(n)
        ]
    }


def _session_for(payloads):
    pages = list(payloads)

    def handler(url, kwargs):
        return FakeResponse(200, json.dumps(pages.pop(0)), url=url)

    return FakeSession(handler)


def test_full_sync_persists_bids_and_updates_counters(db):
    source = _json_source(db)
    session = _session_for([_items_page(3)])

    result = run_source_sync(db, source, session=session)

    assert result["status"] == "SUCCESS"
    assert result["inserted"] == 3
    assert result["rejected"] == 0
    assert result["discovered"] == 3

    bids = db.query(Bid).all()
    assert len(bids) == 3
    assert all(b.source_name == "JSON Tenders" for b in bids)
    assert all(b.source_url and b.source_url.startswith(f"https://{HOST}") for b in bids)
    assert {b.gem_bid_id for b in bids} == {"AUD-0", "AUD-1", "AUD-2"}

    db.refresh(source)
    assert source.total_runs == 1
    assert source.total_inserted == 3
    assert source.last_discovered == 3
    assert source.status == "SUCCESS"
    assert source.last_success_at is not None

    run = db.query(SourceRun).filter(SourceRun.source_id == source.id).order_by(SourceRun.started_at.desc()).first()
    assert run.status == "SUCCESS"
    assert run.inserted == 3
    assert run.validated == 3
    assert run.trigger == "manual"


def test_second_run_dedupes_by_identity(db):
    source = _json_source(db)
    payload = _items_page(3)
    run_source_sync(db, source, session=_session_for([dict(payload)]))
    # Same ids and URLs again, content changed -> updated, not duplicated as new.
    payload2 = {
        "items": [
            {**item, "title": item["title"] + " (amended)"}
            for item in payload["items"]
        ]
    }
    result = run_source_sync(db, source, session=_session_for([payload2]))

    db.refresh(source)
    assert result["status"] in ("SUCCESS", "NEEDS_ATTENTION")
    assert result["inserted"] == 0
    assert result["duplicates"] >= 3  # exact gem_bid_id matches each time
    assert result["updated"] == 3     # content hash changed -> corrigendum applied
    assert source.total_runs == 2
    assert len(db.query(Bid).all()) == 3  # no second copies
    assert db.query(Bid).filter(Bid.gem_bid_id == "AUD-0").one().title.endswith("(amended)")


def test_partial_validation_rejections_recorded(db):
    payload = {
        "items": [
            {"title": "Good tender", "permalink": f"https://{HOST}/good", "id": "G1"},
            {"title": "  ", "permalink": "https://x/bad", "id": "B1"},  # empty title -> rejected
        ]
    }
    source = _json_source(db)
    result = run_source_sync(db, source, session=_session_for([payload]))

    db.refresh(source)
    assert result["status"] == "PARTIAL"
    assert result["inserted"] == 1
    assert result["rejected"] == 1
    assert result["validated"] == 1
    assert source.total_rejected == 1
    assert any("validation" in (e.get("field") or "") for e in result["errors"])


def test_disabled_source_skips(db):
    source = _json_source(db, enabled=False)
    result = run_source_sync(db, source)
    assert result["status"] == "SKIPPED"
    run = db.query(SourceRun).filter(SourceRun.source_id == source.id).one()
    assert run.status == "SKIPPED"


def test_busy_lock_prevents_overlap(db):
    source = _json_source(db)
    lock = run_source_sync.__globals__["_source_lock"](str(source.id))
    assert lock.acquire(blocking=False)
    try:
        result = run_source_sync(db, source)
        assert result["status"] == "BUSY"
    finally:
        lock.release()


def test_blocked_source_raises_safe_status(db, monkeypatch):
    from app.services.sources.safe_http import BlockedResponseError
    import app.services.sources.runner as runner

    source = _json_source(db)

    class BlockedAdapter(JsonApiAdapterProxy):
        def collect(self, config, name="", session=None):
            raise BlockedResponseError("refused (HTTP 403)", url=API_URL, http_status=403)

    monkeypatch.setattr(runner, "_adapter_for", lambda s: BlockedAdapter())
    result = run_source_sync(db, source)
    assert result["status"] == "BLOCKED"
    db.refresh(source)
    assert source.status == "BLOCKED"
    assert source.last_error and "403" in source.last_error


def test_config_error_writes_no_run_records_but_source_state(db, monkeypatch):
    import app.services.sources.runner as runner

    source = _json_source(db)

    class BadAdapter(JsonApiAdapterProxy):
        def validate_config(self, config):
            raise SourceConfigError("bad", safe_message="The configuration URL points to an internal host.")

        def collect(self, config, name="", session=None):
            raise AssertionError("should not collect")

    monkeypatch.setattr(runner, "_adapter_for", lambda s: BadAdapter())
    result = run_source_sync(db, source)

    assert result["status"] == "CONFIG_ERROR"
    db.refresh(source)
    assert source.status == "CONFIG_ERROR"
    assert source.last_error and "internal host" in source.last_error


def test_intelligence_wiring_called_for_created_bids(db, monkeypatch):
    calls = {"n": 0}

    def fake_intel(db, bid, **kwargs):
        calls["n"] += 1
        return {"notification_created": False}

    import app.services.sources.runner as runner

    monkeypatch.setattr(runner, "process_bid_intelligence", fake_intel)
    source = _json_source(db)
    run_source_sync(db, source, session=_session_for([_items_page(2)]))
    assert calls["n"] == 2


def test_no_records_status(db):
    source = _json_source(db)
    result = run_source_sync(db, source, session=_session_for([{"items": []}]))
    assert result["status"] in ("NO_RECORDS", "FAILED")
    assert result["inserted"] == 0


class JsonApiAdapterProxy:
    """Delegate so per-test collect overrides are simple."""

    adapter_key = "json_api"

    def validate_config(self, config):
        return dict(config or {})

    def collect(self, config, name="", session=None):
        raise NotImplementedError