"""
Credential-reference policy tests.

``config["auth"]["env_ref"]`` lets a configured source name an environment
variable holding a credential. Without a boundary that is an exfiltration
primitive: an operator who can create a source could reference ``DATABASE_URL``,
``SECRET_KEY`` or a third-party API key and send it to a host they control. These
tests prove:

* deny-by-default: with no allowlist, every reference is rejected;
* malformed references are rejected;
* a variable that *is* set in the process environment is still rejected unless
  its name is explicitly allowlisted (the core exfiltration test);
* an allowlisted-but-unset variable fails safely (name only, never a value);
* a value never reaches error messages, logs, run records, source state or API
  responses;
* the check is enforced both when a source is saved and again at collection
  time, so a pre-existing row cannot survive a policy change.
"""

from __future__ import annotations

import json
import logging

import pytest

from app.core.config import settings
from app.models.source import DataSource, SourceRun
from app.services.sources.adapters import JsonApiAdapter
from app.services.sources.base import (
    SourceConfigError,
    apply_auth,
    resolve_auth_secret,
    sanitize_config,
    validate_secret_ref,
)
from app.services.sources.runner import run_source_sync
from tests.source_test_utils import FakeSession, make_resolver, static_handler

HOST = "tenders.example.com"
JSON_URL = f"https://{HOST}/api/tenders"
SECRET_VALUE = "EXFIL-SECRET-VALUE-9f3a"


@pytest.fixture(autouse=True)
def _patch_dns(monkeypatch):
    from app.services import sources as package

    monkeypatch.setattr(package.safe_http, "_resolve_host", make_resolver())
    yield


def _set_allowlist(monkeypatch, value: str) -> None:
    monkeypatch.setattr(settings, "SOURCE_ALLOWED_SECRET_ENVS", value)


def _json_source(db, *, env_ref=None, auth_type="bearer", source_id="sec-src"):
    config = {
        "url": JSON_URL,
        "records_path": "items",
        "field_map": {"title": "title"},
    }
    if env_ref is not None:
        config["auth"] = {"type": auth_type, "env_ref": env_ref}
    source = DataSource(
        source_id=source_id,
        name="Secret policy source",
        source_type="json_api",
        adapter_key="json_api",
        config=config,
    )
    db.add(source)
    db.commit()
    db.refresh(source)
    return source


# ---------------------------------------------------------------------------
# Deny-by-default and malformed references
# ---------------------------------------------------------------------------
def test_default_policy_denies_all_secret_refs(monkeypatch):
    _set_allowlist(monkeypatch, "")
    with pytest.raises(SourceConfigError) as exc:
        validate_secret_ref("DATABASE_URL")
    assert "not approved" in exc.value.safe_message


def test_set_environment_variable_is_still_rejected_without_allowlist(monkeypatch):
    """The core exfiltration test: being set in the environment is not enough."""
    _set_allowlist(monkeypatch, "")
    monkeypatch.setenv("SUPER_SECRET_TOKEN", SECRET_VALUE)

    with pytest.raises(SourceConfigError) as exc:
        resolve_auth_secret("SUPER_SECRET_TOKEN")
    assert SECRET_VALUE not in str(exc.value)
    assert SECRET_VALUE not in exc.value.safe_message

    # Even a well-formed, real credential cannot be applied to a request.
    with pytest.raises(SourceConfigError):
        apply_auth({"auth": {"type": "bearer", "env_ref": "SUPER_SECRET_TOKEN"}})


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "   ",
        "FOO BAR",
        "FOO=BAR",
        "../ETC_PASSWD",
        "1LEADING",
        "a" * 200,
        "FOO;BAR",
        "FOO/BAR",
    ],
)
def test_malformed_refs_are_rejected(monkeypatch, bad):
    _set_allowlist(monkeypatch, "GOOD_KEY")
    with pytest.raises(SourceConfigError):
        validate_secret_ref(bad)


def test_allowlist_is_exact_and_case_sensitive(monkeypatch):
    _set_allowlist(monkeypatch, "my_key")
    with pytest.raises(SourceConfigError):
        validate_secret_ref("MY_KEY")
    assert validate_secret_ref("my_key") == "my_key"


def test_far_end_of_allowlist_is_not_silently_matched(monkeypatch):
    """A name that merely contains an allowed name is not allowed."""
    _set_allowlist(monkeypatch, "APP_KEY")
    with pytest.raises(SourceConfigError):
        validate_secret_ref("APP_KEY_BACKUP")


# ---------------------------------------------------------------------------
# Approved references
# ---------------------------------------------------------------------------
def test_approved_reference_resolves_and_applies(monkeypatch):
    _set_allowlist(monkeypatch, "TENDER_API_KEY")
    monkeypatch.setenv("TENDER_API_KEY", SECRET_VALUE)

    assert resolve_auth_secret("TENDER_API_KEY") == SECRET_VALUE
    assert apply_auth({"auth": {"type": "bearer", "env_ref": "TENDER_API_KEY"}}) == {
        "headers": {"Authorization": f"Bearer {SECRET_VALUE}"}
    }
    assert apply_auth(
        {"auth": {"type": "query", "param": "k", "env_ref": "TENDER_API_KEY"}}
    ) == {"query": {"k": SECRET_VALUE}}
    assert apply_auth(
        {
            "auth": {
                "type": "header",
                "header_name": "X-Key",
                "env_ref": "TENDER_API_KEY",
            }
        }
    ) == {"headers": {"X-Key": SECRET_VALUE}}


def test_approved_but_unset_variable_fails_with_name_only(monkeypatch):
    _set_allowlist(monkeypatch, "MISSING_BUT_APPROVED")
    monkeypatch.delenv("MISSING_BUT_APPROVED", raising=False)

    assert resolve_auth_secret("MISSING_BUT_APPROVED") is None
    with pytest.raises(SourceConfigError) as exc:
        apply_auth({"auth": {"type": "bearer", "env_ref": "MISSING_BUT_APPROVED"}})
    assert "MISSING_BUT_APPROVED" in exc.value.safe_message


def test_secret_value_never_in_error_for_unsupported_type(monkeypatch):
    """The secret is resolved before the type check; it must not be echoed."""
    _set_allowlist(monkeypatch, "TENDER_API_KEY")
    monkeypatch.setenv("TENDER_API_KEY", SECRET_VALUE)
    with pytest.raises(SourceConfigError) as exc:
        apply_auth({"auth": {"type": "weird", "env_ref": "TENDER_API_KEY"}})
    assert SECRET_VALUE not in str(exc.value)
    assert SECRET_VALUE not in exc.value.safe_message


# ---------------------------------------------------------------------------
# Config-save-time enforcement (adapter validate_config)
# ---------------------------------------------------------------------------
def test_adapter_validate_config_rejects_unauthorized_ref(monkeypatch):
    _set_allowlist(monkeypatch, "")
    with pytest.raises(SourceConfigError):
        JsonApiAdapter().validate_config(
            {
                "url": JSON_URL,
                "records_path": "items",
                "auth": {"type": "bearer", "env_ref": "DATABASE_URL"},
            }
        )


def test_adapter_validate_config_allows_approved_ref(monkeypatch):
    _set_allowlist(monkeypatch, "TENDER_API_KEY")
    cfg = JsonApiAdapter().validate_config(
        {
            "url": JSON_URL,
            "records_path": "items",
            "auth": {"type": "bearer", "env_ref": "TENDER_API_KEY"},
        }
    )
    assert cfg["auth"]["env_ref"] == "TENDER_API_KEY"


# ---------------------------------------------------------------------------
# API enforcement: arbitrary refs rejected, values never returned
# ---------------------------------------------------------------------------
def test_api_rejects_arbitrary_env_var(monkeypatch, client):
    _set_allowlist(monkeypatch, "")
    monkeypatch.setenv("SECRET_KEY", SECRET_VALUE)
    resp = client.post(
        "/api/v1/sources",
        json={
            "source_id": "evil",
            "name": "Evil",
            "source_type": "json_api",
            "config": {
                "url": JSON_URL,
                "records_path": "items",
                "auth": {"type": "bearer", "env_ref": "SECRET_KEY"},
            },
        },
    )
    assert resp.status_code == 422
    assert SECRET_VALUE not in resp.text
    assert "not approved" in resp.json()["detail"]


def test_api_accepts_approved_ref_without_leaking_value(monkeypatch, client):
    _set_allowlist(monkeypatch, "TENDER_API_KEY")
    monkeypatch.setenv("TENDER_API_KEY", SECRET_VALUE)
    resp = client.post(
        "/api/v1/sources",
        json={
            "source_id": "good",
            "name": "Good",
            "source_type": "json_api",
            "config": {
                "url": JSON_URL,
                "records_path": "items",
                "auth": {"type": "bearer", "env_ref": "TENDER_API_KEY"},
            },
        },
    )
    assert resp.status_code == 201, resp.text
    assert SECRET_VALUE not in resp.text
    assert resp.json()["config"]["auth"]["env_ref"] == "TENDER_API_KEY"


def test_api_rejects_malformed_env_ref(monkeypatch, client):
    _set_allowlist(monkeypatch, "TENDER_API_KEY")
    resp = client.post(
        "/api/v1/sources",
        json={
            "source_id": "malformed",
            "name": "Malformed",
            "source_type": "json_api",
            "config": {
                "url": JSON_URL,
                "records_path": "items",
                "auth": {"type": "bearer", "env_ref": "../SECRETS"},
            },
        },
    )
    assert resp.status_code == 422
    assert "valid environment-variable name" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# Defense in depth: a stored row cannot bypass a policy change
# ---------------------------------------------------------------------------
def test_runtime_enforcement_after_allowlist_removed(monkeypatch, db):
    _set_allowlist(monkeypatch, "TENDER_API_KEY")
    monkeypatch.setenv("TENDER_API_KEY", SECRET_VALUE)
    source = _json_source(db, env_ref="TENDER_API_KEY")

    # Config was valid when saved. Now the policy is tightened (or the var is
    # removed from the allowlist): the row must not be able to read it.
    _set_allowlist(monkeypatch, "")

    payload = {"items": [{"title": "Tender X"}]}
    result = run_source_sync(
        db, source, session=FakeSession(static_handler(json.dumps(payload), 200))
    )

    assert result["status"] == "CONFIG_ERROR"
    db.refresh(source)
    assert source.last_error and "not approved" in source.last_error
    assert SECRET_VALUE not in json.dumps(result["errors"])
    assert SECRET_VALUE not in (source.last_error or "")
    # A pre-run config error never opens a collection run (no partial audit row).
    assert db.query(SourceRun).filter(SourceRun.source_id == source.id).count() == 0


def test_runtime_never_logs_secret_value(monkeypatch, db, caplog):
    _set_allowlist(monkeypatch, "TENDER_API_KEY")
    monkeypatch.setenv("TENDER_API_KEY", SECRET_VALUE)
    source = _json_source(db, env_ref="TENDER_API_KEY")

    class Boom:
        def get(self, *a, **k):
            raise RuntimeError("transport down")

    with caplog.at_level(logging.DEBUG):
        result = run_source_sync(db, source, session=Boom())
    assert result["status"] in {"ERROR", "CONFIG_ERROR"}
    assert SECRET_VALUE not in caplog.text
    assert SECRET_VALUE not in json.dumps(result)


# ---------------------------------------------------------------------------
# Sanitization: non-reference keys inside auth never leave the backend
# ---------------------------------------------------------------------------
def test_sanitize_drops_non_reference_keys_inside_auth():
    config = {
        "url": JSON_URL,
        "auth": {
            "type": "bearer",
            "env_ref": "TENDER_API_KEY",
            "value": SECRET_VALUE,
            "headers": {"X-API-Key": SECRET_VALUE},
        },
    }
    out = sanitize_config(config)
    assert out["auth"]["env_ref"] == "TENDER_API_KEY"
    assert out["auth"]["type"] == "bearer"
    assert "value" not in out["auth"]
    assert "headers" not in out["auth"]
    assert SECRET_VALUE not in json.dumps(out)
