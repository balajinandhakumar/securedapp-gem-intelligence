"""
Source registry API tests: CRUD, enable/disable, adapter catalog, secret-free
responses, run history wiring.
"""

from __future__ import annotations

import pytest

from app.models.source import DataSource
from tests.source_test_utils import make_resolver

HOST = "tenders.example.com"
RSS_URL = f"https://{HOST}/feed.xml"


@pytest.fixture(autouse=True)
def _patch_dns(monkeypatch):
    from app.services import sources as package

    monkeypatch.setattr(package.safe_http, "_resolve_host", make_resolver())
    yield


def _rss_payload(source_id="rss-1", url=RSS_URL, **overrides):
    payload = {
        "source_id": source_id,
        "name": "Example Tenders RSS",
        "source_type": "rss",
        "config": {"url": url, "max_records": 100},
        "collection_interval_minutes": 60,
    }
    payload.update(overrides)
    return payload


def test_create_and_list_source(client):
    resp = client.post("/api/v1/sources", json=_rss_payload())
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["source_id"] == "rss-1"
    assert body["adapter_key"] == "rss_feed"
    assert body["adapter_label"] == "RSS / Atom feed"
    assert body["status"] == "IDLE"
    assert body["last_discovered"] == 0

    listing = client.get("/api/v1/sources").json()
    assert [s["source_id"] for s in listing] == ["rss-1"]


def test_create_derives_adapter_prefixing_works(client):
    resp = client.post(
        "/api/v1/sources",
        json=_rss_payload(source_id="feed-2", name="Atom feed", source_type="atom"),
    )
    assert resp.status_code == 201
    assert resp.json()["adapter_key"] == "rss_feed"


def test_create_duplicate_source_id_conflicts(client):
    client.post("/api/v1/sources", json=_rss_payload())
    resp = client.post("/api/v1/sources", json=_rss_payload())
    assert resp.status_code == 409


def test_create_rejects_invalid_url_and_missing_row_selector(client):
    bad_url = client.post(
        "/api/v1/sources",
        json={
            "source_id": "x",
            "name": "X",
            "source_type": "rss",
            "config": {"url": "http://localhost/f"},
        },
    )
    assert bad_url.status_code == 422

    bad_html = client.post(
        "/api/v1/sources",
        json={
            "source_id": "h",
            "name": "H",
            "source_type": "html_listing",
            "config": {"url": RSS_URL},
        },
    )
    assert bad_html.status_code == 422


def test_response_config_is_secret_free(monkeypatch, client):
    from app.core.config import settings

    monkeypatch.setattr(settings, "SOURCE_ALLOWED_SECRET_ENVS", "SOURCE_BEARER_KEY")
    resp = client.post(
        "/api/v1/sources",
        json=_rss_payload(
            source_id="sec-1",
            source_type="json_api",
            config={
                "url": f"https://{HOST}/api",
                "records_path": "items",
                "auth": {"type": "bearer", "env_ref": "SOURCE_BEARER_KEY"},
                "password": "hunter2",
                "api_token": "raw-token",
            },
        ),
    )
    assert resp.status_code == 201, resp.text
    config = resp.json()["config"]
    assert config["password"] == "***"
    assert config["api_token"] == "***"
    assert config["auth"]["env_ref"] == "SOURCE_BEARER_KEY"
    assert config["auth"]["type"] == "bearer"
    assert "hunter2" not in resp.text
    assert "raw-token" not in resp.text


def test_update_patches_source(client):
    client.post("/api/v1/sources", json=_rss_payload())
    resp = client.put(
        "/api/v1/sources/rss-1",
        json={"enabled": False, "collection_interval_minutes": 240, "name": "Renamed"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["enabled"] is False
    assert body["collection_interval_minutes"] == 240
    assert body["name"] == "Renamed"


def test_enable_disable_toggle(client):
    client.post("/api/v1/sources", json=_rss_payload())
    assert client.post("/api/v1/sources/rss-1/disable").json()["enabled"] is False
    assert client.post("/api/v1/sources/rss-1/enable").json()["enabled"] is True


def test_delete_source(client):
    client.post("/api/v1/sources", json=_rss_payload())
    assert client.delete("/api/v1/sources/rss-1").status_code == 204
    assert client.get("/api/v1/sources/rss-1").status_code == 404
    assert client.get("/api/v1/sources").json() == []


def test_get_missing_source_404(client):
    assert client.get("/api/v1/sources/nope").status_code == 404


def test_sources_meta_catalog(client):
    body = client.get("/api/v1/sources/meta").json()
    keys = {a["adapter_key"] for a in body["adapters"]}
    assert keys == {"rss_feed", "json_api", "html_listing", "playwright_html"}
    for adapter in body["adapters"]:
        assert "integration_note" in adapter
        assert "requires_browser" in adapter
        assert "requires_credentials" in adapter


def test_sources_meta_scheduler_exposes_status(client):
    body = client.get("/api/v1/sources/meta").json()
    scheduler = body["scheduler"]
    assert scheduler["enabled"] is False
    assert "tick_seconds" in scheduler
    assert "running" in scheduler
    assert "note" in scheduler


def test_create_rejects_adapter_key_not_matching_source_type(client):
    resp = client.post(
        "/api/v1/sources",
        json=_rss_payload(source_id="mismatch", adapter_key="json_api"),
    )
    assert resp.status_code == 422
    assert "does not support source type 'rss'" in resp.json()["detail"]


def test_create_rejects_unknown_adapter_key(client):
    resp = client.post(
        "/api/v1/sources",
        json=_rss_payload(source_id="bad-adapter", adapter_key="no_such_adapter"),
    )
    assert resp.status_code == 422
    assert "No adapter registered" in resp.json()["detail"]


def test_test_connection_wires_adapter(monkeypatch, client):
    client.post("/api/v1/sources", json=_rss_payload())

    class FakeTester:
        def test_connection(self, config):
            from app.services.sources.base import ConnectionTestResult

            return ConnectionTestResult(ok=True, message="all good", http_status=200)

    monkeypatch.setattr(
        "app.api.v1.endpoints.sources.get_adapter", lambda key: FakeTester()
    )
    resp = client.post("/api/v1/sources/rss-1/test")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    assert resp.json()["message"] == "all good"


def test_sync_endpoint_wires_runner(monkeypatch, client):
    client.post("/api/v1/sources", json=_rss_payload())

    def fake_sync(db, source, **kwargs):
        return {
            "run_id": None,
            "status": "SUCCESS",
            "message": "ok",
            "inserted": 2,
            "updated": 0,
            "duplicates": 0,
            "rejected": 0,
            "errors": [],
            "discovered": 2,
            "validated": 2,
        }

    monkeypatch.setattr("app.api.v1.endpoints.sources.run_source_sync", fake_sync)
    resp = client.post("/api/v1/sources/rss-1/sync")
    assert resp.status_code == 200
    assert resp.json()["status"] == "SUCCESS"
    assert resp.json()["inserted"] == 2


def test_sync_busy_raises_409(monkeypatch, client):
    client.post("/api/v1/sources", json=_rss_payload())
    monkeypatch.setattr(
        "app.api.v1.endpoints.sources.run_source_sync",
        lambda db, source, **k: {"status": "BUSY", "message": "already running"},
    )
    assert client.post("/api/v1/sources/rss-1/sync").status_code == 409


def test_sync_confiq_error_raises_400(monkeypatch, client):
    client.post("/api/v1/sources", json=_rss_payload())
    monkeypatch.setattr(
        "app.api.v1.endpoints.sources.run_source_sync",
        lambda db, source, **k: {"status": "CONFIG_ERROR", "message": "bad config"},
    )
    assert client.post("/api/v1/sources/rss-1/sync").status_code == 400


def test_runs_list_and_detail(client, db):
    source = DataSource(
        source_id="run-src",
        name="Run Source",
        source_type="rss",
        adapter_key="rss_feed",
        config={"url": RSS_URL},
        enabled=True,
    )
    db.add(source)
    db.commit()
    db.refresh(source)

    from app.models.source import SourceRun
    import uuid

    run = SourceRun(
        id=uuid.uuid4(),
        source_id=source.id,
        trigger="manual",
        status="SUCCESS",
        records_discovered=5,
        inserted=4,
        validated=5,
        errors=[{"field": "dedup", "message": "1 repeated"}],
    )
    db.add(run)
    db.commit()

    listing = client.get("/api/v1/sources/run-src/runs").json()
    assert len(listing) == 1
    assert listing[0]["inserted"] == 4
    assert listing[0]["errors"][0]["field"] == "dedup"

    detail = client.get(f"/api/v1/sources/runs/{run.id}").json()
    assert detail["id"] == str(run.id)
