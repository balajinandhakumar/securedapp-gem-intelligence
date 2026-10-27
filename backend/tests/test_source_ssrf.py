"""
SSRF protection tests for the source transport.

These run the exact code path used by every adapter (validate_public_url +
safe_get) with a fake resolver and a fake session, so no DNS or socket is
touched. They assert the policy that the completion report claims.
"""
from __future__ import annotations

import pytest

from app.services.sources.safe_http import (
    BlockedResponseError,
    SafeFetchError,
    UrlNotPermittedError,
    safe_get,
    validate_public_url,
)
from tests.source_test_utils import FakeResponse, FakeSession, make_resolver, static_handler

HOST = "tenders.example.org"
PUBLIC_URL = f"https://{HOST}/bids/rss"


@pytest.fixture(autouse=True)
def _patch_dns(monkeypatch):
    from app.services import sources as package

    monkeypatch.setattr(package.safe_http, "_resolve_host", make_resolver())
    monkeypatch.setattr(package.safe_http, "set_default_session", lambda s: None)
    yield


def _assert_blocked(url: str, reason_substr: str) -> None:
    with pytest.raises(UrlNotPermittedError) as exc:
        validate_public_url(url)
    assert reason_substr in exc.value.reason


# ---------------------------------------------------------------------------
# URL policy
# ---------------------------------------------------------------------------
def test_rejects_private_ipv4_ranges():
    for url in (
        "http://10.0.0.5/x",
        "http://127.0.0.1/x",
        "http://172.16.5.5/x",
        "http://192.168.1.10/x",
        "http://169.254.169.254/latest/meta-data",
        "http://0.0.0.0/x",
        "http://100.64.0.1/x",
        "http://198.18.0.1/x",
        "http://224.0.0.1/x",
        "http://240.0.0.1/x",
    ):
        _assert_blocked(url, "resolved_private")


def test_rejects_loopback_and_private_over_ipv6_mapped():
    _assert_blocked("http://[::1]/x", "private_hostname")
    _assert_blocked("http://[::ffff:127.0.0.1]/x", "resolved_private")
    _assert_blocked("http://[::ffff:10.0.0.1]/x", "resolved_private")
    _assert_blocked("http://[fc00::1]/x", "private_hostname")


def test_rejects_private_hostnames():
    for host in ("localhost", "postgres", "router", "jenkins.internal", "cache.local", "metadata.google.internal"):
        _assert_blocked(f"http://{host}/x", "private_hostname")


def test_rejects_non_http_schemes_and_userinfo_and_bad_ports():
    _assert_blocked("ftp://example.com/x", "bad_scheme")
    _assert_blocked("https://user:pass@example.com/x", "userinfo")
    _assert_blocked("http://example.com:8080/x", "bad_port")


def test_blocks_when_dns_resolves_private():
    import app.services.sources.safe_http as sh

    original = sh._resolve_host
    sh._resolve_host = lambda host: ["10.0.0.200"]
    try:
        with pytest.raises(UrlNotPermittedError) as exc:
            validate_public_url(PUBLIC_URL)
        assert exc.value.reason == "resolved_private"
    finally:
        sh._resolve_host = original


def test_blocked_when_dns_unresolved():
    import app.services.sources.safe_http as sh

    original = sh._resolve_host
    sh._resolve_host = lambda host: []
    try:
        with pytest.raises(UrlNotPermittedError) as exc:
            validate_public_url(PUBLIC_URL)
        assert exc.value.reason == "resolved_none"
    finally:
        sh._resolve_host = original


def test_host_allowlist_enforced():
    with pytest.raises(UrlNotPermittedError) as exc:
        validate_public_url(PUBLIC_URL, allowed_hosts=["gem.gov.in"])
    assert exc.value.reason == "host_not_allowed"
    assert validate_public_url("https://api.tenders.example.com/x", allowed_hosts=["tenders.example.com"]) is not None


def test_public_url_passes():
    assert validate_public_url(PUBLIC_URL)


# ---------------------------------------------------------------------------
# Transport behaviour
# ---------------------------------------------------------------------------
def test_successful_get_returns_safe_response(monkeypatch):
    session = FakeSession(static_handler("<feed></feed>", 200))
    resp = safe_get(PUBLIC_URL, session=session, timeout_s=5, max_retries=1)
    assert resp.is_success()
    assert resp.final_url == PUBLIC_URL
    assert resp.text == "<feed></feed>"
    assert len(session.calls) == 1
    assert session.calls[0]["timeout"] == 5.0


def test_retries_on_500_then_succeeds():
    calls = {"n": 0}

    def handler(url, kwargs):
        calls["n"] += 1
        return FakeResponse(500, "err", url=url) if calls["n"] == 1 else FakeResponse(200, "ok", url=url)

    session = FakeSession(handler)
    resp = safe_get(PUBLIC_URL, session=session, max_retries=2, retry_delay_s=0)
    assert resp.status_code == 200
    assert calls["n"] == 2


def test_429_with_retry_after_is_honoured_then_succeeds():
    calls = {"n": 0}

    def handler(url, kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return FakeResponse(429, "", headers={"Retry-After": "0"}, url=url)
        return FakeResponse(200, "ok", url=url)

    session = FakeSession(handler)
    resp = safe_get(PUBLIC_URL, session=session, max_retries=2, retry_delay_s=0)
    assert resp.status_code == 200
    assert calls["n"] == 2


def test_403_raises_blocked():
    session = FakeSession(static_handler("blocked", 403))
    with pytest.raises(BlockedResponseError) as exc:
        safe_get(PUBLIC_URL, session=session, max_retries=1)
    assert exc.value.http_status == 403


def test_redirect_to_private_destination_is_rejected():
    def handler(url, kwargs):
        return FakeResponse(302, "", headers={"Location": "http://127.0.0.1/evil"}, url=url)

    session = FakeSession(handler)
    with pytest.raises(UrlNotPermittedError) as exc:
        safe_get(PUBLIC_URL, session=session)
    assert "resolved_private" in exc.value.reason


def test_redirect_to_private_hostname_is_rejected():
    def handler(url, kwargs):
        return FakeResponse(302, "", headers={"Location": "http://localhost/admin"}, url=url)

    session = FakeSession(handler)
    with pytest.raises(UrlNotPermittedError) as exc:
        safe_get(PUBLIC_URL, session=session)
    assert exc.value.reason == "private_hostname"


def test_redirect_chain_to_public_destination_followed():
    hops = {"n": 0}

    def handler(url, kwargs):
        hops["n"] += 1
        if hops["n"] == 1:
            return FakeResponse(301, "", headers={"Location": f"https://{HOST}/final"}, url=url)
        return FakeResponse(200, "final", url=url)

    session = FakeSession(handler)
    resp = safe_get(PUBLIC_URL, session=session, max_retries=1)
    assert resp.status_code == 200
    assert resp.final_url == f"https://{HOST}/final"
    assert resp.redirects == 1


def test_redirect_loop_detected():
    def handler(url, kwargs):
        return FakeResponse(302, "", headers={"Location": url}, url=url)

    session = FakeSession(handler)
    with pytest.raises(SafeFetchError):
        safe_get(PUBLIC_URL, session=session)


def test_transport_failure_raises_safe_fetch_error():
    class Boom:
        def get(self, *a, **k):
            raise RuntimeError("connection refused")

    with pytest.raises(SafeFetchError):
        safe_get(PUBLIC_URL, session=Boom(), max_retries=1, retry_delay_s=0)