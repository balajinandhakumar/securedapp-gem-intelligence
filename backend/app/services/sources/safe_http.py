"""
SSRF-safe HTTP transport for source adapters.

Every outbound request a configurable source makes goes through this module.
Guards applied before, during and after each request:

* ``https`` / ``http`` schemes only; URLs carrying userinfo credentials are
  rejected.
* Hostname-based blocks: ``localhost``, ``*.local``, ``*.internal``,
  ``*.home.arpa``, single-label hostnames and bare IP literals are checked
  against blocked private/reserved ranges.
* DNS resolution is checked immediately before the request and every returned
  address must be public unicast space. The transport then *pins* the checked
  address so the actual socket connects to exactly that IP (never a
  re-resolved one), closing the DNS-rebinding / split-horizon window.
* Redirects are followed one jump at a time with the *next* destination fully
  re-validated before it is requested, so a public URL cannot bounce you to an
  internal address.
* Hard timeouts, bounded retries with backoff, ``Retry-After`` honoured, and
  ``403`` / ``429`` short-circuited without aggressive retrying.
* Optional host allowlist (``SOURCE_ALLOWED_HOSTS``). Empty = any public host
  is permitted; when non-empty only listed hosts or their subdomains are
  reachable.

The transport is injectable (``session=...``) so tests exercise the exact
code path with fake responses and no network.
"""

from __future__ import annotations

import datetime as _dt
import ipaddress
import logging
import socket
import sys
import threading
import time
import urllib.parse
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def url_for_log(url: Any) -> str:
    """Return a URL safe to log / show to users.

    A configured source may legitimately carry an API key in the query string
    (``auth.type=query``), so every user-visible message strips the query,
    fragment and any credentials. Only the origin + path remain.
    """
    text = str(url or "")
    try:
        parsed = urllib.parse.urlsplit(text)
    except ValueError:
        return (text or "(unset)")[:160]
    if not parsed.scheme or not parsed.hostname:
        return (text or "(unset)")[:160]
    scheme = parsed.scheme.lower()
    host = parsed.hostname
    port = None
    try:
        port = parsed.port
    except ValueError:
        port = None
    netloc = host
    if port is not None and not (
        (scheme == "http" and port == 80) or (scheme == "https" and port == 443)
    ):
        netloc = f"{host}:{port}"
    path = parsed.path or "/"
    return f"{scheme}://{netloc}{path}"


class SafeFetchError(Exception):
    """Transport-level failure that was not an SSRF guard."""

    def __init__(self, message: str, *, url: Optional[str] = None) -> None:
        super().__init__(message)
        self.message = message
        self.url = url


class UrlNotPermittedError(SafeFetchError):
    """The requested URL is not permitted by the SSRF policy."""

    def __init__(
        self, message: str, *, url: Optional[str] = None, reason: str = ""
    ) -> None:
        super().__init__(message, url=url)
        self.reason = reason


class BlockedResponseError(SafeFetchError):
    """The source refused automated collection (HTTP 403 / 429)."""

    def __init__(
        self, message: str, *, url: Optional[str] = None, http_status: int = 0
    ) -> None:
        super().__init__(message, url=url)
        self.http_status = http_status


# ---------------------------------------------------------------------------
# Policy tables
# ---------------------------------------------------------------------------
_DEFAULT_BLOCKED_IP_NETWORKS: List[ipaddress._BaseNetwork] = [
    ipaddress.ip_network("0.0.0.0/8"),  # "this" network
    ipaddress.ip_network("10.0.0.0/8"),  # private
    ipaddress.ip_network("100.64.0.0/10"),  # CGNAT / carrier-grade NAT
    ipaddress.ip_network("127.0.0.0/8"),  # loopback
    ipaddress.ip_network(
        "169.254.0.0/16"
    ),  # link-local incl. cloud metadata 169.254.169.254
    ipaddress.ip_network("172.16.0.0/12"),  # private
    ipaddress.ip_network("192.0.0.0/24"),  # IETF protocol assignments
    ipaddress.ip_network("192.168.0.0/16"),  # private
    ipaddress.ip_network("198.18.0.0/15"),  # benchmarking
    ipaddress.ip_network("198.51.100.0/24"),  # TEST-NET-2 documentation
    ipaddress.ip_network("203.0.113.0/24"),  # TEST-NET-3 documentation
    ipaddress.ip_network("224.0.0.0/4"),  # multicast
    ipaddress.ip_network("240.0.0.0/4"),  # reserved
    ipaddress.ip_network("::/128"),  # unspecified
    ipaddress.ip_network("::1/128"),  # loopback
    ipaddress.ip_network("::ffff:0:0/96"),  # IPv4-mapped (incl. ::ffff:127.x / 10.x)
    ipaddress.ip_network("100::/64"),  # discard-only
    ipaddress.ip_network("2001:db8::/32"),  # documentation
    ipaddress.ip_network("fc00::/7"),  # unique local
    ipaddress.ip_network("fe80::/10"),  # link-local
    ipaddress.ip_network("ff00::/8"),  # multicast
]

_HOST_SUFFIX_BLOCKS = (
    ".localhost",
    ".local",
    ".internal",
    ".lan",
    ".home.arpa",
)

_BLOCKED_HOST_EXACT = {
    "localhost",
    "localhost.localdomain",
    "ip6-localhost",
    "ip6-loopback",
    "metadata.google.internal",
    "metadata.google.internal.",
    "metadata",
    "metadata.google.internal.com",
}

_MAX_REDIRECTS = 5


def _ip_is_blocked(
    address_text: str, blocked_networks: List[ipaddress._BaseNetwork]
) -> bool:
    try:
        ip = ipaddress.ip_address(address_text.split("%")[0])
    except ValueError:
        return True  # not even parseable as an IP -> fail closed
    for net in blocked_networks:
        try:
            if ip.version == net.version and ip in net:
                return True
        except Exception:  # pragma: no cover - version mismatch safety
            continue
    return bool(
        ip.is_loopback
        or ip.is_private
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def _is_private_hostname(host: str) -> bool:
    host = host.rstrip(".").lower()
    if host in _BLOCKED_HOST_EXACT:
        return True
    if host.startswith("localhost") or host in ("localhost",):
        return True
    if host in ("::1", "0:0:0:0:0:0:0:1"):
        return True
    if any(host.endswith(suffix) for suffix in _HOST_SUFFIX_BLOCKS):
        return True
    # Single-label hosts (e.g. "db", "router", "internal-svc") have no public
    # DNS space -> fail closed.
    if host.count(".") == 0:
        return True
    return False


def _resolve_host(host: str) -> List[str]:
    """Resolve ``host`` to IP strings. Returns [] when unresolved.

    This is the hook tests replace with a fake resolver; ``getaddrinfo``
    covers both A and AAAA records.
    """
    try:
        info = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return []
    return (
        sorted({item[4][0].split("%")[0] for item in info if item[4] and item[4][0]})
        if info
        else []
    )


def validate_public_url(
    url: str,
    *,
    allowed_hosts: Optional[List[str]] = None,
    allow_insecure: bool = False,
) -> str:
    """Validate ``url`` against the SSRF policy.

    Returns the normalized URL (the caller may request any allowed host; the
    returned value has no fragment / trailing-safe identity). Raises
    :class:`UrlNotPermittedError` on any violation.

    ``allowed_hosts``: when a non-empty list is passed, the URL's host (or a
    suffix of it) must be present.
    """
    raw = str(url or "").strip()
    if not raw:
        raise UrlNotPermittedError("No URL provided.", url=raw, reason="empty_url")
    parsed = urllib.parse.urlsplit(raw)
    if parsed.scheme.lower() not in ("http", "https"):
        raise UrlNotPermittedError(
            f"Only http/https destinations are permitted, got scheme '{parsed.scheme or 'none'}'.",
            url=raw,
            reason="bad_scheme",
        )
    if parsed.username or parsed.password:
        raise UrlNotPermittedError(
            "URLs must not embed credentials in the request URL.",
            url=raw,
            reason="userinfo",
        )
    if not parsed.hostname:
        raise UrlNotPermittedError("URL has no host.", url=raw, reason="no_host")
    port = parsed.port
    if port is not None and port not in (80, 443):
        raise UrlNotPermittedError(
            f"Only standard web ports are permitted, got port {port}.",
            url=raw,
            reason="bad_port",
        )

    host = parsed.hostname.rstrip(".").lower()
    if _is_private_hostname(host):
        raise UrlNotPermittedError(
            f"Host '{host}' is not a public destination (localhost/private/reserved name).",
            url=raw,
            reason="private_hostname",
        )

    # Optional explicit host allowlist.
    if allowed_hosts:
        allowlist = [
            h.strip().lower().lstrip(".") for h in allowed_hosts if h and h.strip()
        ]
        if not any(host == h or host.endswith("." + h) for h in allowlist):
            raise UrlNotPermittedError(
                f"Host '{host}' is not in the configured source host allowlist.",
                url=raw,
                reason="host_not_allowed",
            )

    # Resolve and require at least one public unicast address.
    ips = _resolve_host(host)
    if not ips:
        raise UrlNotPermittedError(
            f"Host '{host}' could not be resolved to any IPv4/IPv6 address.",
            url=raw,
            reason="resolved_none",
        )
    blocked = [ip for ip in ips if _ip_is_blocked(ip, _DEFAULT_BLOCKED_IP_NETWORKS)]
    if blocked:
        raise UrlNotPermittedError(
            f"Host '{host}' resolves to a non-public address ({', '.join(blocked[:4])}); "
            "refusing to connect.",
            url=raw,
            reason="resolved_private",
        )

    return raw


class SafeResponse:
    """Immutable response object passed to adapters (never the raw session object)."""

    __slots__ = (
        "status_code",
        "final_url",
        "requested_url",
        "headers",
        "text",
        "reason",
        "elapsed_ms",
        "redirects",
    )

    def __init__(
        self,
        status_code: int,
        final_url: str,
        requested_url: str,
        headers: Dict[str, str],
        text: str,
        reason: str = "",
        elapsed_ms: float = 0.0,
        redirects: int = 0,
    ) -> None:
        self.status_code = int(status_code)
        self.final_url = final_url
        self.requested_url = requested_url
        self.headers = headers
        self.text = text or ""
        self.reason = reason or ""
        self.elapsed_ms = float(elapsed_ms)
        self.redirects = int(redirects)

    def is_success(self) -> bool:
        return 200 <= self.status_code < 300


def safe_get(
    url: str,
    *,
    session: Any = None,
    headers: Optional[Dict[str, str]] = None,
    timeout_s: float = 30.0,
    max_retries: int = 2,
    retry_delay_s: float = 1.0,
    allowed_hosts: Optional[List[str]] = None,
    _redirect_depth: int = 0,
) -> SafeResponse:
    """Fetch ``url`` safely. See module docstring for the guard set."""
    target = validate_public_url(url, allowed_hosts=allowed_hosts)
    if session is None:
        session = _default_session()

    # Resolve once more, immediately before the request, and pin the transport
    # socket to the *exact* public address that was checked. The connection
    # then opens a socket to that IP instead of re-resolving the hostname,
    # closing the DNS-rebinding / split-horizon window between validation and
    # transport. A second resolution that is refused is fail-closed.
    pins = _pins_for_target(target, allowed_hosts=allowed_hosts)
    if pins:
        _set_pins(pins)
    try:
        attempt = 0
        while True:
            attempt += 1
            started = time.perf_counter()
            try:
                resp = session.get(
                    target,
                    headers=headers or {},
                    timeout=float(timeout_s),
                    allow_redirects=False,
                )
            except UrlNotPermittedError:
                raise
            except Exception as exc:  # requests.RequestException and friends
                if attempt <= max_retries:
                    logger.warning(
                        "safe_get %s attempt %d failed: %s",
                        url_for_log(target),
                        attempt,
                        exc,
                    )
                    time.sleep(retry_delay_s * attempt)
                    continue
                raise SafeFetchError(
                    f"Request to {url_for_log(target)} failed after {attempt} attempt(s): {exc}",
                    url=target,
                ) from exc

            elapsed = (time.perf_counter() - started) * 1000.0
            status = getattr(resp, "status_code", 0)
            resp_url = getattr(resp, "url", None) or target
            # If the transport followed something anyway, re-validate the final URL.
            if resp_url != target:
                validate_public_url(resp_url, allowed_hosts=allowed_hosts)

            location = resp.headers.get("Location") or resp.headers.get("location")
            if status in (301, 302, 303, 307, 308) and location:
                if _redirect_depth >= _MAX_REDIRECTS:
                    raise SafeFetchError(
                        f"Too many redirects fetching {url_for_log(target)}.",
                        url=target,
                    )
                next_url = urllib.parse.urljoin(resp_url, location)
                # The next hop is fully validated before it is requested.
                validate_public_url(next_url, allowed_hosts=allowed_hosts)
                time.sleep(min(retry_delay_s, 2.0))
                return safe_get(
                    next_url,
                    session=session,
                    headers=headers,
                    timeout_s=timeout_s,
                    max_retries=max_retries,
                    retry_delay_s=retry_delay_s,
                    allowed_hosts=allowed_hosts,
                    _redirect_depth=_redirect_depth + 1,
                )

            if status in (403, 429):
                retry_after = _header_seconds(resp.headers.get("Retry-After"))
                if (
                    attempt <= max_retries
                    and retry_after is not None
                    and retry_after <= 300
                ):
                    time.sleep(retry_after)
                    continue
                raise BlockedResponseError(
                    f"{url_for_log(target)} refused automated collection (HTTP {status}). No bypass attempted.",
                    url=target,
                    http_status=status,
                )

            if status >= 500 and attempt <= max_retries:
                time.sleep(retry_delay_s * attempt)
                continue

            return SafeResponse(
                status_code=status,
                final_url=resp_url,
                requested_url=target,
                headers=dict(resp.headers or {}),
                text=getattr(resp, "text", "") or "",
                reason=str(getattr(resp, "reason", "") or ""),
                elapsed_ms=elapsed,
                redirects=_redirect_depth,
            )
    finally:
        _clear_pins(pins)


def _header_seconds(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(str(value).strip())
    except ValueError:
        try:
            return float(
                (
                    _dt.datetime.fromisoformat(str(value).strip())
                    - _dt.datetime.now(_dt.timezone.utc)
                ).total_seconds()
            )
        except ValueError:
            return None


# ---------------------------------------------------------------------------
# Module-level default session (injectable for tests)
# ---------------------------------------------------------------------------
import requests  # noqa: E402 - imported after policy helpers for clarity
from requests.adapters import DEFAULT_POOLBLOCK, HTTPAdapter  # noqa: E402

from urllib3.connection import (  # noqa: E402 - pinned transport imports live with the default session below
    HTTPConnection as _UrllibHTTPConnection,
    HTTPSConnection as _UrllibHTTPSConnection,
)
from urllib3.connectionpool import (  # noqa: E402
    HTTPConnectionPool as _UrllibHTTPConnectionPool,
    HTTPSConnectionPool as _UrllibHTTPSConnectionPool,
)
from urllib3.exceptions import (  # noqa: E402
    ConnectTimeoutError,
    NameResolutionError,
    NewConnectionError,
)
from urllib3.poolmanager import PoolManager  # noqa: E402
import urllib3.util.connection as _u3conn  # noqa: E402


# Pinned-IP context ------------------------------------------------------
# ``safe_get`` pre-resolves a public address and records it here so the
# transport socket connects to exactly that IP (thread-local: concurrent
# requests in separate threads never share pins).
_pin_state = threading.local()


def _set_pins(pins: Dict[tuple, str]) -> None:
    _pin_state.pins = pins


def _clear_pins(pins: Optional[Dict[tuple, str]]) -> None:
    if pins is not None:
        _pin_state.pins = None


def _pinned_ip_for(host: str, port: int) -> Optional[str]:
    pins = getattr(_pin_state, "pins", None)
    if not pins:
        return None
    return pins.get((host.rstrip(".").lower(), int(port)))


def _pins_for_target(
    target: str, *, allowed_hosts: Optional[List[str]] = None
) -> Dict[tuple, str]:
    """Resolve ``target`` a second time and pin the exact address to connect to.

    Returns ``{(host, port): public_ip}``. Every resolved address must again be
    public unicast space; a private/absent re-resolution refuses the request
    (fail-closed) rather than handing the connection back to the OS resolver.
    """
    parsed = urllib.parse.urlsplit(target)
    host = (parsed.hostname or "").rstrip(".").lower()
    if not host:
        return {}
    ips = _resolve_host(host)
    if not ips:
        raise UrlNotPermittedError(
            f"Host '{host}' could not be resolved when preparing the connection; refusing to connect.",
            url=target,
            reason="resolved_none",
        )
    blocked = [ip for ip in ips if _ip_is_blocked(ip, _DEFAULT_BLOCKED_IP_NETWORKS)]
    if blocked:
        raise UrlNotPermittedError(
            f"Host '{host}' resolves to a non-public address ({', '.join(blocked[:4])}); "
            "refusing to connect.",
            url=target,
            reason="resolved_private",
        )
    choice = next((ip for ip in ips if ":" not in ip), None) or ips[0]
    port = int(parsed.port or (443 if parsed.scheme.lower() == "https" else 80))
    return {(host, port): choice}


class _PinnedHTTPConnection(_UrllibHTTPConnection):
    """HTTP connection that connects to the pre-validated public IP.

    When ``safe_get`` pinning is active for ``(host, port)`` the socket is
    opened against that exact IP while the Host header keeps the hostname.
    Without a pin it falls back to the standard resolution path.
    """

    def _new_conn(self) -> socket.socket:
        pin = _pinned_ip_for(self.host, self.port)
        if pin is None:
            return _UrllibHTTPConnection._new_conn(self)
        if _ip_is_blocked(pin, _DEFAULT_BLOCKED_IP_NETWORKS):
            raise NewConnectionError(
                self, f"Refusing to connect: pinned address {pin} is not public."
            )
        try:
            sock = _u3conn.create_connection(
                (pin, self.port),
                self.timeout,
                source_address=self.source_address,
                socket_options=self.socket_options,
            )
        except socket.gaierror as exc:
            raise NameResolutionError(self.host, self, exc) from exc
        except socket.timeout as exc:
            raise ConnectTimeoutError(
                self,
                f"Connection to {self.host} timed out. (connect timeout={self.timeout})",
            ) from exc
        except OSError as exc:
            raise NewConnectionError(
                self, f"Failed to establish a new connection: {exc}"
            ) from exc
        sys.audit("http.client.connect", self, self.host, self.port)
        return sock


class _PinnedHTTPSConnection(_UrllibHTTPSConnection):
    """HTTPS twin of :class:`_PinnedHTTPConnection`.

    TLS SNI and certificate hostname validation still use the hostname, only
    the TCP socket targets the pinned public IP.
    """

    _new_conn = _PinnedHTTPConnection._new_conn


class _PinnedHTTPConnectionPool(_UrllibHTTPConnectionPool):
    ConnectionCls = _PinnedHTTPConnection


class _PinnedHTTPSConnectionPool(_UrllibHTTPSConnectionPool):
    ConnectionCls = _PinnedHTTPSConnection


class _PinnedPoolManager(PoolManager):
    """Pool manager that builds only pinned-connection pools."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.pool_classes_by_scheme = {
            "http": _PinnedHTTPConnectionPool,
            "https": _PinnedHTTPSConnectionPool,
        }


class _PinnedHTTPAdapter(HTTPAdapter):
    """requests adapter whose pools connect only through pinned connections."""

    def init_poolmanager(
        self,
        connections: int,
        maxsize: int,
        block: bool = DEFAULT_POOLBLOCK,
        **pool_kwargs: Any,
    ) -> None:
        self.poolmanager = _PinnedPoolManager(
            num_pools=connections, maxsize=maxsize, block=block
        )


def _session_factory() -> Any:
    sess = requests.Session()
    sess.max_redirects = 0  # we handle redirects ourselves in safe_get
    adapter = _PinnedHTTPAdapter()
    sess.mount("http://", adapter)
    sess.mount("https://", adapter)
    return sess


def _default_session() -> Any:
    if _DEFAULT_SESSION is None:
        configure_default_session()
    return _DEFAULT_SESSION


_DEFAULT_SESSION: Any = None


def configure_default_session() -> None:
    global _DEFAULT_SESSION
    if _DEFAULT_SESSION is None:
        _DEFAULT_SESSION = _session_factory()


def set_default_session(session: Any) -> None:
    """Test hook: replace the module-level default session."""
    global _DEFAULT_SESSION
    _DEFAULT_SESSION = session


# Make sure a real session is available when the app runs (tests may set their
# own fake before first use, in which case this is a no-op).
configure_default_session()
