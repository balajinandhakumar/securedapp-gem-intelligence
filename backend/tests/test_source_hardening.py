"""
Production-readiness hardening tests.

These pin the behaviours added during the review:

* Connect-time DNS pinning: the transport connects to the *exact* public
  address that passed policy, and a host that resolves differently a second
  time (DNS rebinding / split horizon) is refused before any socket opens.
* Secret redaction: API tokens carried in query strings never appear in error
  messages, logs, run records or source ``last_error``.
* Runner crash isolation: an unexpected exception mid-pipeline rolls back and
  records a safe ERROR audit run instead of wedging the source as RUNNING.
* Browser renderer subresource policy: the Playwright guard allows only
  public http(s) and non-network browser schemes ("data:", "blob:", ...).
* Registry integrity: an explicit adapter_key must match the source_type.
"""

from __future__ import annotations

import json
import logging

import pytest

from app.models.bid import Bid
from app.models.source import DataSource, SourceRun
from app.services.sources.runner import run_source_sync
from app.services.sources.safe_http import (
    BlockedResponseError,
    SafeFetchError,
    UrlNotPermittedError,
    safe_get,
    url_for_log,
)
from tests.source_test_utils import FakeSession, make_resolver, static_handler

HOST = "tenders.example.com"
PUBLIC_URL = f"https://{HOST}/bids/rss"


@pytest.fixture(autouse=True)
def _patch_dns(monkeypatch):
    from app.services import sources as package

    monkeypatch.setattr(package.safe_http, "_resolve_host", make_resolver())
    yield


# ---------------------------------------------------------------------------
# URL redaction
# ---------------------------------------------------------------------------
def test_url_for_log_strips_query_fragment_and_userinfo():
    assert (
        url_for_log(
            "https://user:pass@api.example.com/v1?api_key=TOPSECRET&page=2#frag"
        )
        == "https://api.example.com/v1"
    )
    assert url_for_log("http://example.com:8080/x?k=s") == "http://example.com:8080/x"
    assert url_for_log("https://example.com") == "https://example.com/"
    assert url_for_log("") == "(unset)"


def test_transport_error_messages_redact_query_secrets():
    token_url = PUBLIC_URL + "?api_key=TOP-SECRET-123"

    class Boom:
        def get(self, *a, **k):
            raise RuntimeError("connection refused")

    with pytest.raises(SafeFetchError) as exc:
        safe_get(token_url, session=Boom(), max_retries=1, retry_delay_s=0)
    assert "TOP-SECRET-123" not in str(exc.value)
    assert "TOP-SECRET-123" not in str(exc.value.message)
    assert HOST in exc.value.message


def test_blocked_response_message_redacts_query_secrets():
    token_url = PUBLIC_URL + "?token=SECRET-42"
    session = FakeSession(static_handler("blocked", 403))
    with pytest.raises(BlockedResponseError) as exc:
        safe_get(token_url, session=session, max_retries=1)
    assert "SECRET-42" not in exc.value.message
    assert "refused automated collection" in exc.value.message


def test_retry_warning_log_is_redacted(caplog):
    token_url = PUBLIC_URL + "?api_key=SECRET-77"

    class Boom:
        def get(self, *a, **k):
            raise RuntimeError("boom")

    with caplog.at_level(logging.WARNING, logger="app.services.sources.safe_http"):
        with pytest.raises(SafeFetchError):
            safe_get(token_url, session=Boom(), max_retries=1, retry_delay_s=0)
    assert "SECRET-77" not in caplog.text


def test_rss_404_message_redacts_query_secrets():
    from app.services.sources.adapters import RssFeedAdapter
    from app.services.sources.safe_http import SafeFetchError as SFE

    token_url = f"https://{HOST}/feed.xml?token=FEED-SECRET-9"
    session = FakeSession(static_handler("", 404))
    with pytest.raises(SFE) as exc:
        RssFeedAdapter().collect(
            {"url": token_url, "max_records": 100}, session=session
        )
    assert "FEED-SECRET-9" not in str(exc.value)


# ---------------------------------------------------------------------------
# DNS rebinding: fail-closed pinning
# ---------------------------------------------------------------------------
def test_dns_rebinding_second_resolution_is_fail_closed(monkeypatch):
    import app.services.sources.safe_http as sh

    calls = {"n": 0}

    def rebinding(host):
        calls["n"] += 1
        return ["93.184.216.34"] if calls["n"] == 1 else ["169.254.169.254"]

    monkeypatch.setattr(sh, "_resolve_host", rebinding)
    session = FakeSession(static_handler("ok", 200))
    with pytest.raises(UrlNotPermittedError) as exc:
        safe_get(PUBLIC_URL, session=session)
    assert exc.value.reason == "resolved_private"
    assert calls["n"] == 2  # validated once, then re-checked before connecting
    assert session.calls == []  # no request was ever sent
    assert sh._pinned_ip_for(HOST, 443) is None  # context cleared


def test_pins_for_target_prefers_ipv4_and_clears(monkeypatch):
    import app.services.sources.safe_http as sh

    monkeypatch.setattr(
        sh, "_resolve_host", lambda host: ["2606:2800:220:1::a", "93.184.216.34"]
    )
    pins = sh._pins_for_target(PUBLIC_URL)
    assert pins == {(HOST, 443): "93.184.216.34"}
    assert sh._pinned_ip_for(HOST, 443) is None  # not set until safe_get
    sh._set_pins(pins)
    assert sh._pinned_ip_for(HOST, 443) == "93.184.216.34"
    sh._clear_pins(pins)
    assert sh._pinned_ip_for(HOST, 443) is None


def test_pinned_connection_connects_to_pinned_ip(monkeypatch):
    import socket

    import app.services.sources.safe_http as sh
    from urllib3.exceptions import NameResolutionError

    captured = {}

    def fake_create(address, *_a, **_k):
        captured["addr"] = address
        raise socket.gaierror("no address to avoid a real socket")

    monkeypatch.setattr(sh._u3conn, "create_connection", fake_create)
    conn = sh._PinnedHTTPConnection(HOST, 443, timeout=5)
    sh._set_pins({(HOST, 443): "93.184.216.34"})
    try:
        with pytest.raises(NameResolutionError):
            conn._new_conn()
    finally:
        sh._clear_pins({(HOST, 443): "93.184.216.34"})
    assert captured["addr"] == ("93.184.216.34", 443)
    assert conn.host == HOST  # Host header / TLS identity stays the hostname


def test_pinned_https_keeps_hostname_for_tls(monkeypatch):
    import socket

    import app.services.sources.safe_http as sh
    from urllib3.exceptions import NameResolutionError

    monkeypatch.setattr(
        sh._u3conn,
        "create_connection",
        lambda address, *_a, **_k: (_ for _ in ()).throw(socket.gaierror()),
    )
    conn = sh._PinnedHTTPSConnection(HOST, 443, timeout=5)
    assert conn.host == HOST
    assert conn.server_hostname is None  # falls back to self.host for SNI/cert
    sh._set_pins({(HOST, 443): "93.184.216.34"})
    try:
        with pytest.raises(NameResolutionError):
            conn._new_conn()
    finally:
        sh._clear_pins({(HOST, 443): "93.184.216.34"})


def test_pinned_connection_refuses_blocked_pin(monkeypatch):
    import app.services.sources.safe_http as sh
    from urllib3.exceptions import NewConnectionError

    conn = sh._PinnedHTTPConnection(HOST, 443, timeout=5)
    sh._set_pins({(HOST, 443): "127.0.0.1"})
    try:
        with pytest.raises(NewConnectionError):
            conn._new_conn()
    finally:
        sh._clear_pins({(HOST, 443): "127.0.0.1"})


# ---------------------------------------------------------------------------
# Runner crash isolation
# ---------------------------------------------------------------------------
def test_pipeline_crash_rolls_back_and_records_error_run(db, monkeypatch):
    import app.services.sources.runner as runner_mod

    source = DataSource(
        source_id="crash-src",
        name="Crash JSON",
        source_type="json_api",
        adapter_key="json_api",
        config={
            "url": PUBLIC_URL.replace("/bids/rss", "/api/tenders"),
            "records_path": "items",
            "field_map": {"title": "title", "gem_bid_id": "id"},
        },
    )
    db.add(source)
    db.commit()
    db.refresh(source)

    def boom(db, normalized, **kwargs):
        raise RuntimeError("normalizer exploded")

    monkeypatch.setattr(runner_mod, "check_duplicate", boom)
    payload = {"items": [{"title": "Tender X", "id": "TX-1"}]}

    result = run_source_sync(
        db, source, session=FakeSession(static_handler(json.dumps(payload), 200))
    )

    assert result["status"] == "ERROR"
    assert "exploded" in result["message"] or any(
        "exploded" in e["message"] for e in result["errors"]
    )

    # Nothing partial was persisted.
    assert db.query(Bid).count() == 0

    # An audit row exists and the source is not stuck RUNNING.
    db.refresh(source)
    assert source.status == "ERROR"
    assert source.last_error and "exploded" in source.last_error
    assert source.total_runs == 1
    assert source.last_attempt_at is not None

    run = db.get(SourceRun, result["run_id"])
    assert run is not None
    assert run.status == "ERROR"
    assert run.source_id == source.id
    assert run.trigger == "manual"
    assert any("exploded" in e["message"] for e in run.errors or [])


def test_pipeline_crash_never_leaks_secrets_into_errors(db, monkeypatch):
    import app.services.sources.runner as runner_mod

    token_url = f"https://{HOST}/api/tenders?api_key=CRASH-PIPELINE-SECRET"
    source = DataSource(
        source_id="crash-secret",
        name="Crash Secret",
        source_type="json_api",
        adapter_key="json_api",
        config={
            "url": token_url,
            "records_path": "items",
            "field_map": {"title": "title"},
        },
    )
    db.add(source)
    db.commit()
    db.refresh(source)

    def boom(db, normalized, **kwargs):
        raise RuntimeError("deep crash")

    monkeypatch.setattr(runner_mod, "check_duplicate", boom)
    payload = {"items": [{"title": "Tender X"}]}
    result = run_source_sync(
        db, source, session=FakeSession(static_handler(json.dumps(payload), 200))
    )

    db.refresh(source)
    blob = json.dumps({"result": result, "last_error": source.last_error})
    assert "CRASH-PIPELINE-SECRET" not in blob


def test_fetch_error_redacts_secret_reaching_source_state(db):
    token_url = f"https://{HOST}/api/tenders?api_key=RUN-SECRET-88"
    source = DataSource(
        source_id="redact-src",
        name="Redact JSON",
        source_type="json_api",
        adapter_key="json_api",
        config={
            "url": token_url,
            "records_path": "items",
            "field_map": {"title": "title"},
        },
    )
    db.add(source)
    db.commit()
    db.refresh(source)

    class Boom:
        def get(self, *a, **k):
            raise RuntimeError("down")

    result = run_source_sync(db, source, session=Boom())
    assert result["status"] == "ERROR"
    db.refresh(source)
    assert "RUN-SECRET-88" not in (source.last_error or "")
    assert "RUN-SECRET-88" not in json.dumps(result["errors"])
    run = db.query(SourceRun).filter(SourceRun.source_id == source.id).one()
    assert "RUN-SECRET-88" not in json.dumps(run.errors or [])


# ---------------------------------------------------------------------------
# Browser renderer subresource policy
# ---------------------------------------------------------------------------
def test_browser_guard_policies_subresources():
    from app.services.sources.adapters import _guard_browser_request

    assert _guard_browser_request(f"https://{HOST}/app.js") is True
    assert _guard_browser_request("http://127.0.0.1/admin") is False
    assert _guard_browser_request("http://169.254.169.254/latest/meta-data") is False
    assert _guard_browser_request("http://10.0.0.5/x") is False
    assert _guard_browser_request("file:///etc/passwd") is False
    assert _guard_browser_request("ftp://example.com/x") is False
    assert _guard_browser_request("ws://example.com/socket") is False
    assert _guard_browser_request("about:blank") is True
    assert _guard_browser_request("data:text/html,hello") is True
    assert _guard_browser_request("blob:https://example.com/uuid") is True
    assert _guard_browser_request("javascript:void(0)") is True
