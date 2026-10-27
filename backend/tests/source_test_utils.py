"""
Shared fakes for the multi-source test suite.

The global ``requests.Session.request`` guard in conftest makes it impossible
for a test to reach the real network by accident. These fakes let tests drive
the *exact* SSRF-safe transport code path (``safe_http.safe_get``) and the
pipeline integration without any socket.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

PUBLIC_IP = "93.184.216.34"


class FakeResponse:
    def __init__(
        self,
        status: int = 200,
        text: str = "",
        headers: Optional[Dict[str, str]] = None,
        url: Optional[str] = None,
        reason: str = "OK",
        content: Optional[bytes] = None,
    ) -> None:
        self.status_code = status
        self.headers = headers or {}
        self.url = url
        self.text = text
        self.reason = reason
        self.content = content if content is not None else text.encode("utf-8")


class FakeSession:
    """Minimal stand-in for ``requests.Session`` used by safe_http.safe_get."""

    def __init__(self, handler: Optional[Callable[[str, Dict[str, Any]], FakeResponse]] = None) -> None:
        self.handler = handler
        self.calls: List[Dict[str, Any]] = []
        self.max_redirects = 0

    def get(self, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append({"url": url, "headers": kwargs.get("headers"), "timeout": kwargs.get("timeout")})
        if self.handler is None:
            resp = FakeResponse(200, "{}", url=url)
        else:
            resp = self.handler(url, kwargs)
        if resp.url is None:
            resp.url = url
        return resp


def make_resolver(ip: str = PUBLIC_IP) -> Callable[[str], List[str]]:
    """Fake DNS: IP literals resolve to themselves (real behaviour), so the
    SSRF check still sees literal private addresses as private; hostnames
    resolve to a single public unicast IP."""

    def _resolver(host: str) -> List[str]:
        try:
            import ipaddress

            ipaddress.ip_address(host)
            return [host]
        except ValueError:
            return [ip]

    return _resolver


def static_handler(text: str, status: int = 200, headers: Optional[Dict[str, str]] = None) -> Callable:
    def _handler(url: str, kwargs: Dict[str, Any]) -> FakeResponse:
        return FakeResponse(status, text, headers, url=url)

    return _handler


def json_handler(payload: Any, status: int = 200) -> Callable:
    import json

    def _handler(url: str, kwargs: Dict[str, Any]) -> FakeResponse:
        return FakeResponse(status, json.dumps(payload), url=url)

    return _handler