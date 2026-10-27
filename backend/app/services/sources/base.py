"""
SourceAdapter base class and shared result types.

Every configurable source is collected through a ``BaseSourceAdapter``. A
source row in the registry stores the adapter key + its configuration; the
adapter turns one configured source into canonical ``RawBidRecord`` rows that
the existing validation -> normalization -> deduplication -> 11-product
matching pipeline consumes unchanged.

Adapters never talk directly to the network. They use the SSRF-safe transport
(``safe_http.safe_get``) which blocks private/reserved destinations and
re-validates redirects. Any credential a source needs is resolved from an
environment variable referenced by ``config["auth"]["env_ref"]`` -- and only a
variable named in the server's ``SOURCE_ALLOWED_SECRET_ENVS`` allowlist may be
referenced (deny-by-default). Credentials are never stored, logged or returned
to the frontend.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

from app.services.ingestion.schemas import RawBidRecord
from app.services.sources.safe_http import (
    SafeResponse,
    UrlNotPermittedError,
    safe_get,
    validate_public_url,
)

logger = logging.getLogger(__name__)

# Safe operational budgets applied to every configured source. These are
# clamps, not recommendations; the Generic HTML adapter in particular must
# stay conservative about how much public listing it walks per run.
MIN_INTERVAL_MINUTES = 5
MAX_INTERVAL_MINUTES = 10080  # 7 days
DEFAULT_MAX_PAGES = 10
MAX_MAX_PAGES = 200
DEFAULT_MAX_RECORDS = 500
MAX_MAX_RECORDS = 2000
DEFAULT_TIMEOUT_S = 30.0
MAX_TIMEOUT_S = 120.0
DEFAULT_MAX_RETRIES = 2
MAX_MAX_RETRIES = 5
MAX_PAGE_DELAY_S = 30.0
MIN_PAGE_DELAY_S = 0.0


class SourceConfigError(Exception):
    """Configuration for a source is invalid or incomplete.

    ``safe_message`` is what is shown to users (never leaves module bounds with
    secrets or raw content).
    """

    def __init__(self, message: str, *, safe_message: Optional[str] = None):
        super().__init__(message)
        self.safe_message = safe_message or message


class ConnectionTestResult:
    __slots__ = (
        "ok",
        "message",
        "http_status",
        "duration_ms",
        "method",
        "needs_credentials",
        "needs_browser",
    )

    def __init__(
        self,
        ok: bool,
        message: str,
        http_status: Optional[int] = None,
        duration_ms: float = 0.0,
        method: str = "http",
        needs_credentials: bool = False,
        needs_browser: bool = False,
    ) -> None:
        self.ok = bool(ok)
        self.message = message
        self.http_status = http_status
        self.duration_ms = float(duration_ms)
        self.method = method
        self.needs_credentials = bool(needs_credentials)
        self.needs_browser = bool(needs_browser)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "message": self.message,
            "http_status": self.http_status,
            "duration_ms": self.duration_ms,
            "method": self.method,
            "needs_credentials": self.needs_credentials,
            "needs_browser": self.needs_browser,
        }


class CollectResult:
    """Outcome of one source collect: canonical records + safe per-stage info.

    ``errors`` is a list of ``{"field": str, "message": str}`` with trimmed,
    secret-free messages only (never raw payloads).
    """

    __slots__ = (
        "records",
        "pages_visited",
        "errors",
        "pagination",
        "method",
        "raw_count",
    )

    def __init__(
        self,
        records: List[RawBidRecord],
        pages_visited: int = 0,
        errors: Optional[List[Dict[str, str]]] = None,
        pagination: Optional[Dict[str, Any]] = None,
        method: str = "http",
    ) -> None:
        self.records = records
        self.pages_visited = int(pages_visited)
        self.errors = errors or []
        self.pagination = pagination or {}
        self.method = method
        self.raw_count = len(records)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "records": len(self.records),
            "pages_visited": self.pages_visited,
            "errors": self.errors,
            "pagination": self.pagination,
            "method": self.method,
        }


def clamp_int(value: Any, default: int, low: int, high: int) -> int:
    try:
        return min(high, max(low, int(value)))
    except (TypeError, ValueError):
        return default


def clamp_float(value: Any, default: float, low: float, high: float) -> float:
    try:
        return min(high, max(low, float(value)))
    except (TypeError, ValueError):
        return default


class BaseSourceAdapter:
    """Base for all source adapters.

    Subclasses implement :meth:`parsing_capabilities` (what they can do,
    reported in the source catalog) and :meth:`collect` (fetch + parse).
    :meth:`validate_config` normalizes and clamps the common operational
    budgets shared by every adapter; adapters extend it for their own fields.
    """

    adapter_key: str = "base"
    adapter_label: str = "Generic"
    source_types: tuple = ()
    requires_credentials: bool = False
    requires_browser: bool = False
    method: str = "http"
    # Human note shown in the source catalog about dedicated integration needs.
    integration_note: str = ""

    def validate_config(self, config: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        cfg = dict(config or {})
        cfg["timeout_seconds"] = clamp_float(
            cfg.get("timeout_seconds"), DEFAULT_TIMEOUT_S, 5.0, MAX_TIMEOUT_S
        )
        cfg["max_retries"] = clamp_int(
            cfg.get("max_retries"), DEFAULT_MAX_RETRIES, 0, MAX_MAX_RETRIES
        )
        cfg["max_pages"] = clamp_int(
            cfg.get("max_pages"), DEFAULT_MAX_PAGES, 1, MAX_MAX_PAGES
        )
        cfg["max_records"] = clamp_int(
            cfg.get("max_records"), DEFAULT_MAX_RECORDS, 1, MAX_MAX_RECORDS
        )
        cfg["page_delay_seconds"] = clamp_float(
            cfg.get("page_delay_seconds"), 1.0, MIN_PAGE_DELAY_S, MAX_PAGE_DELAY_S
        )
        self._validate_identity_fields(cfg)
        return cfg

    def _validate_identity_fields(self, config: Dict[str, Any]) -> None:
        """Validate the optional opt-in composite identity field list.

        ``config["identity_fields"]`` lets a source whose native identifier is
        not row-unique (e.g. a GePNIC "Reference No" reused across tenders)
        declare which canonical fields form its identity. It must be a non-empty
        list of known ``RawBidRecord`` field names. Absent -> no change.
        """
        if "identity_fields" not in config:
            return
        fields = config.get("identity_fields")
        if not isinstance(fields, list) or not fields:
            raise SourceConfigError(
                "identity_fields must be a non-empty list of record field names.",
                safe_message=(
                    "identity_fields must be a non-empty list of field names "
                    '(e.g. ["bid_number", "title"]).'
                ),
            )
        cleaned: List[str] = []
        for field in fields:
            name = str(field or "").strip()
            if not name or name not in RawBidRecord.model_fields:
                raise SourceConfigError(
                    f"identity_fields contains an unknown field: {field!r}.",
                    safe_message=f"identity_fields contains an unknown field: {name or field!r}.",
                )
            cleaned.append(name)
        # A single field is not a composite and would re-introduce the very
        # non-unique-identifier problem this exists to solve.
        if len(set(cleaned)) < 2:
            raise SourceConfigError(
                "identity_fields must name at least two distinct fields.",
                safe_message="identity_fields must name at least two distinct fields.",
            )
        config["identity_fields"] = cleaned

    def _validate_url_field(
        self, config: Dict[str, Any], field: str, *, optional: bool = False
    ) -> None:
        value = str(config.get(field) or "").strip()
        if not value:
            if optional:
                return
            raise SourceConfigError(
                f"'{field}' is required.", safe_message=f"{field} is required."
            )
        try:
            validate_public_url(value, allowed_hosts=_allowed_hosts())
        except UrlNotPermittedError as exc:
            raise SourceConfigError(
                f"Configuration URL is not permitted: {exc.reason}",
                safe_message=f"{field} is not a permitted public destination ({exc.reason}).",
            ) from exc
        config[field] = value

    # Subclass hooks ------------------------------------------------------
    def collect(
        self,
        config: Dict[str, Any],
        *,
        name: str = "",
        session: Any = None,
    ) -> CollectResult:
        raise NotImplementedError

    def test_connection(
        self,
        config: Dict[str, Any],
        *,
        session: Any = None,
    ) -> ConnectionTestResult:
        raise NotImplementedError

    def _safe_fetch(
        self,
        url: str,
        session: Any,
        config: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
    ) -> SafeResponse:
        return safe_get(
            url,
            session=session,
            headers=headers,
            timeout_s=float(config.get("timeout_seconds") or DEFAULT_TIMEOUT_S),
            max_retries=int(config.get("max_retries") or 0),
            retry_delay_s=1.5,
            allowed_hosts=_allowed_hosts(),
        )


# SSRF host allowlist from settings, resolved lazily (empty string = no
# restriction beyond the base public-IP policy).
def _allowed_hosts() -> Optional[List[str]]:
    from app.core.config import settings

    raw = str(getattr(settings, "SOURCE_ALLOWED_HOSTS", "") or "").strip()
    if not raw:
        return None
    return [h.strip() for h in raw.split(",") if h.strip()]


# ---------------------------------------------------------------------------
# Credential reference policy
#
# A configured source references a credential only by environment-variable
# name (``config["auth"]["env_ref"]``). That indirection is also an exfiltration
# risk: without a policy, an operator who can create a source could name any
# variable in the process environment (DATABASE_URL, SECRET_KEY, a third-party
# API key, ...) and point the request at a host they control. The policy below
# is a strict, server-side allowlist that is enforced both when a source is
# saved and again on every collection, so a stale database row cannot bypass a
# policy change.
# ---------------------------------------------------------------------------
_SECRET_ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
MAX_SECRET_ENV_NAME_LEN = 128


def allowed_secret_envs() -> List[str]:
    """Server-configured allowlist of permitted ``auth.env_ref`` names.

    Read lazily from settings so a deployment can change it without reimporting
    this module. Empty = no secret reference is permitted.
    """
    from app.core.config import settings

    return list(getattr(settings, "source_allowed_secret_envs", []) or [])


def validate_secret_ref(env_ref: Any) -> str:
    """Validate an ``auth.env_ref`` against the allowlist; return the clean name.

    Raises :class:`SourceConfigError` (with a secret-free ``safe_message``) for
    an empty, malformed or non-allowlisted reference. Never touches the value.
    """
    name = str(env_ref or "").strip()
    if not name:
        raise SourceConfigError(
            "auth.env_ref is required to reference a credential by environment variable.",
            safe_message="Credential references must name an environment variable (auth.env_ref).",
        )
    if len(name) > MAX_SECRET_ENV_NAME_LEN or not _SECRET_ENV_NAME_RE.match(name):
        raise SourceConfigError(
            "auth.env_ref is not a valid environment-variable name.",
            safe_message=(
                "auth.env_ref must be a valid environment-variable name "
                "(letters, digits and underscore, not starting with a digit)."
            ),
        )
    allowlist = allowed_secret_envs()
    if name not in allowlist:
        raise SourceConfigError(
            f"Environment variable '{name}' is not on the approved credential allowlist.",
            safe_message=(
                f"Credential reference '{name}' is not approved. An administrator must add "
                "it to SOURCE_ALLOWED_SECRET_ENVS before a source may use it."
            ),
        )
    return name


def resolve_auth_secret(env_ref: str) -> Optional[str]:
    """Resolve an *approved* credential by environment-variable name.

    Enforces the allowlist first, then reads the value. Returns ``None`` when the
    approved variable is not set. The value is never logged or returned to
    callers beyond the request that needs it.
    """
    import os

    name = validate_secret_ref(env_ref)
    return os.environ.get(name)


def apply_auth(config: Dict[str, Any]) -> Dict[str, str]:
    """Turn ``config["auth"]`` into request headers or query parameters.

    Returns ``{"headers": {...}}`` or ``{"query": {...}}`` consumed by the
    JSON API adapter. The referenced variable must pass the credential allowlist
    and be set; failures raise SourceConfigError with a safe message that names
    the variable only, never its value.
    """
    auth = config.get("auth") or {}
    if not auth:
        return {}

    auth_type = str(auth.get("type") or "").strip().lower()
    env_ref = validate_secret_ref(auth.get("env_ref"))
    secret = resolve_auth_secret(env_ref)
    if not secret:
        raise SourceConfigError(
            f"Environment variable '{env_ref}' is not set.",
            safe_message=f"Credential environment variable '{env_ref}' is not set.",
        )

    if auth_type == "bearer":
        return {"headers": {"Authorization": f"Bearer {secret}"}}
    if auth_type == "header":
        header_name = str(auth.get("header_name") or "").strip() or "X-API-Key"
        return {"headers": {header_name: secret}}
    if auth_type == "query":
        param = str(auth.get("param") or "").strip() or "api_key"
        return {"query": {param: secret}}
    raise SourceConfigError(
        f"Unsupported auth type '{auth_type}'.",
        safe_message=f"Unsupported auth type '{auth_type}'. Use bearer, header or query.",
    )


_TRIM = 400


def safe_error(field: str, message: Any, *, trim: int = _TRIM) -> Dict[str, str]:
    """Build a safe, trimmed error dict from an exception or string."""
    text = str(message or "").strip().replace("\n", " ")
    if len(text) > trim:
        text = text[:trim] + "..."
    return {"field": field, "message": text}


# ---------------------------------------------------------------------------
# Secret-free API representation of a source config
# ---------------------------------------------------------------------------
_SECRET_KEY_HINTS = (
    "api_key",
    "apikey",
    "secret",
    "token",
    "password",
    "authorization",
    "cookie",
    "x-api-key",
    "credential",
)

# The only keys an ``auth`` block may contain. ``env_ref`` is a *reference*
# (a variable name, never a value); the rest are non-secret identifiers. Any
# other key inside ``auth`` (a raw header/query map, a literal value) is not a
# supported reference and is dropped before the config leaves the backend.
_AUTH_REF_KEYS = ("type", "env_ref", "param", "header_name")


def _is_secret_key(key: str) -> bool:
    haystack = str(key).strip().lower().replace("_", "").replace("-", "")
    return any(hint in haystack for hint in _SECRET_KEY_HINTS)


def _sanitize_auth(auth: Any) -> Any:
    """Return only the whitelisted, non-secret keys of an ``auth`` block."""
    if not isinstance(auth, dict):
        return "***"
    return {
        str(key): auth[key]
        for key in auth
        if str(key).lower() in _AUTH_REF_KEYS
        and not isinstance(auth[key], (dict, list))
    }


def sanitize_config(config: Any) -> Any:
    """Deep-copy ``config`` replacing any secret-looking value with a placeholder.

    Value fields with a secret-like key never leave the backend. ``auth`` blocks
    are reduced to their known reference keys (type/env_ref/param/header_name),
    so a raw header map or literal credential nested under ``auth`` is dropped
    rather than returned.
    """
    if isinstance(config, dict):
        out: Dict[str, Any] = {}
        for key, value in config.items():
            if str(key) == "auth":
                out[str(key)] = _sanitize_auth(value)
            elif _is_secret_key(key) and not isinstance(value, (dict, list)):
                out[str(key)] = "***"
            elif isinstance(value, (dict, list)):
                out[str(key)] = sanitize_config(value)
            else:
                out[str(key)] = value
        return out
    if isinstance(config, list):
        return [sanitize_config(item) for item in config]
    return config


def mask_string(value: Optional[str], keep: int = 4) -> Optional[str]:
    """Replace a secret-ish string with a masked display (e.g. ``****abcd``)."""
    if not value:
        return None
    value = str(value)
    if len(value) <= keep:
        return "****"
    return "****" + value[-keep:]
