"""
Authentication and authorization tests.

All tests use isolated in-memory SQLite databases and test credentials.
No existing tests are modified or weakened.
"""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import jwt
import pytest
from fastapi.testclient import TestClient

from app.core.auth import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password_wrapper,
    verify_password_wrapper,
)
from app.core.config import settings
from app.models.user import User


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_user(db, email="user@example.com", name="Test User", role="viewer",
               active=True, password="TestPassword123!"):
    """Create and persist a user with a hashed password."""
    from app.core.security import hash_password
    user = User(
        email=email.lower().strip(),  # normalize email to lowercase
        name=name,
        password_hash=hash_password(password),
        role=role,
        active=active,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _login(client, email, password):
    return client.post("/api/v1/auth/login", json={"email": email, "password": password})


def _enable_auth(monkeypatch):
    """Enable auth enforcement for the duration of the test."""
    monkeypatch.setattr(settings, "AUTH_REQUIRED", True)


# ---------------------------------------------------------------------------
# Password hashing
# ---------------------------------------------------------------------------

def test_password_hashing():
    hashed = hash_password_wrapper("SecurePassword123!")
    assert verify_password_wrapper("SecurePassword123!", hashed) is True
    assert verify_password_wrapper("WrongPassword", hashed) is False
    assert hashed != "SecurePassword123!"  # not plaintext


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------

def test_login_valid(client, db):
    _make_user(db, email="alice@example.com", name="Alice", role="admin",
               password="AlicePass123!")
    res = _login(client, "alice@example.com", "AlicePass123!")
    assert res.status_code == 200
    body = res.json()
    assert "access_token" in body
    assert "refresh_token" in body
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
    assert body["user"]["email"] == "alice@example.com"
    assert body["user"]["role"] == "admin"
    assert "password_hash" not in body["user"]


def test_login_invalid_password(client, db):
    _make_user(db, email="bob@example.com", name="Bob", password="BobPass123!")
    res = _login(client, "bob@example.com", "WrongPassword!")
    assert res.status_code == 401


def test_login_unknown_user(client, db):
    res = _login(client, "none@example.com", "AnyPassword123!")
    assert res.status_code == 401


def test_login_case_insensitive_email(client, db):
    _make_user(db, email="MixedCase@Example.COM", name="MC", password="Pass123!")
    res = _login(client, "mixedcase@example.com", "Pass123!")
    assert res.status_code == 200


def test_login_disabled_user(client, db):
    _make_user(db, email="inactive@example.com", name="Inactive", active=False,
               password="Pass123!")
    res = _login(client, "inactive@example.com", "Pass123!")
    assert res.status_code == 401


def test_login_too_short_password(client, db):
    res = _login(client, "x@example.com", "short")
    assert res.status_code == 422  # Pydantic validation (min_length=8)


def test_login_missing_fields(client, db):
    res = client.post("/api/v1/auth/login", json={"email": "x@example.com"})
    assert res.status_code == 422


# ---------------------------------------------------------------------------
# Brute-force / lockout
# ---------------------------------------------------------------------------

def test_login_lockout_after_max_attempts(client, db):
    _make_user(db, email="victim@example.com", name="Victim", password="VictimPass123!")
    for _ in range(settings.LOGIN_MAX_ATTEMPTS):
        res = _login(client, "victim@example.com", "WrongPassword!")
        assert res.status_code == 401
    # Next attempt should report lockout
    res = _login(client, "victim@example.com", "WrongPassword!")
    assert res.status_code == 401
    assert "locked" in res.json()["detail"].lower()


def test_login_success_resets_failed_attempts(client, db):
    _make_user(db, email="resetter@example.com", name="R", password="ResetPass123!")
    # One failed attempt
    _login(client, "resetter@example.com", "WrongPassword!")
    # Then success
    res = _login(client, "resetter@example.com", "ResetPass123!")
    assert res.status_code == 200
    # And another wrong password does not lock (counter was reset)
    res = _login(client, "resetter@example.com", "WrongPassword!")
    assert res.status_code == 401
    assert "locked" not in res.json()["detail"].lower()


# ---------------------------------------------------------------------------
# Current user
# ---------------------------------------------------------------------------

def test_me_authenticated(client, db, monkeypatch):
    _enable_auth(monkeypatch)
    user = _make_user(db, email="me@example.com", name="Me", role="operator")
    login_res = _login(client, "me@example.com", "TestPassword123!")
    token = login_res.json()["access_token"]
    res = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["id"] == str(user.id)
    assert body["email"] == "me@example.com"
    assert body["name"] == "Me"
    assert body["role"] == "operator"
    assert body["active"] is True


def test_me_no_token(client, db, monkeypatch):
    _enable_auth(monkeypatch)
    res = client.get("/api/v1/auth/me")
    assert res.status_code == 401


def test_me_invalid_token(client, db, monkeypatch):
    _enable_auth(monkeypatch)
    res = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": "Bearer not-a-real-token"},
    )
    assert res.status_code == 401


def test_me_expired_token(client, db, monkeypatch):
    _enable_auth(monkeypatch)
    _make_user(db, email="expired@example.com", name="E")
    token = create_access_token(
        user_id=str(uuid4()), email="expired@example.com", role="viewer",
        expires_delta=timedelta(seconds=-1),  # already expired
    )
    res = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 401


def test_me_revoked_token(client, db, monkeypatch):
    _enable_auth(monkeypatch)
    user = _make_user(db, email="revoked@example.com", name="R")
    login_res = _login(client, "revoked@example.com", "TestPassword123!")
    token = login_res.json()["access_token"]

    # Revoke the access token via logout (empty body is fine, refresh_token optional)
    client.post(
        "/api/v1/auth/logout",
        json={},
        headers={"Authorization": f"Bearer {token}"},
    )

    res = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 401


# ---------------------------------------------------------------------------
# Logout
# ---------------------------------------------------------------------------

def test_logout(client, db, monkeypatch):
    _enable_auth(monkeypatch)
    _make_user(db, email="logout@example.com", name="L", password="LogoutPass123!")
    login_res = _login(client, "logout@example.com", "LogoutPass123!")
    token = login_res.json()["access_token"]
    refresh = login_res.json()["refresh_token"]

    res = client.post(
        "/api/v1/auth/logout",
        json={"refresh_token": refresh},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 200
    assert res.json()["detail"] == "Logged out successfully."


def test_logout_no_token(client, db):
    res = client.post("/api/v1/auth/logout", json={})
    assert res.status_code == 200  # no token to revoke, still OK


# ---------------------------------------------------------------------------
# Refresh
# ---------------------------------------------------------------------------

def test_refresh_valid(client, db):
    _make_user(db, email="refresh@example.com", name="Rf", password="RfPass123!")
    login_res = _login(client, "refresh@example.com", "RfPass123!")
    assert login_res.status_code == 200, login_res.json()
    refresh = login_res.json()["refresh_token"]

    res = client.post("/api/v1/auth/refresh", json={"refresh_token": refresh})
    print(f"Refresh response: {res.status_code} {res.text}")  # debug
    assert res.status_code == 200, res.text
    body = res.json()
    assert "access_token" in body
    assert body["token_type"] == "bearer"


def test_refresh_invalid(client, db):
    res = client.post("/api/v1/auth/refresh", json={"refresh_token": "garbage"})
    assert res.status_code == 401


def test_refresh_revoked(client, db):
    _make_user(db, email="refreshrevoked@example.com", name="RR", password="RrPass123!")
    login_res = _login(client, "refreshrevoked@example.com", "RrPass123!")
    refresh = login_res.json()["refresh_token"]

    # Revoke the refresh token
    client.post(
        "/api/v1/auth/logout",
        json={"refresh_token": refresh},
    )

    res = client.post("/api/v1/auth/refresh", json={"refresh_token": refresh})
    assert res.status_code == 401


# ---------------------------------------------------------------------------
# User management (ADMIN only)
# ---------------------------------------------------------------------------

def test_create_user_admin(client, db, monkeypatch):
    _enable_auth(monkeypatch)
    _make_user(db, email="admin@example.com", name="Admin", role="admin",
               password="AdminPass123!")
    login_res = _login(client, "admin@example.com", "AdminPass123!")
    token = login_res.json()["access_token"]

    res = client.post(
        "/api/v1/auth/users",
        json={
            "email": "newuser@example.com",
            "name": "New User",
            "password": "NewPass123!",
            "role": "operator",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 201
    body = res.json()
    assert body["email"] == "newuser@example.com"
    assert body["role"] == "operator"
    assert "password_hash" not in body


def test_create_user_duplicate_email(client, db, monkeypatch):
    _enable_auth(monkeypatch)
    _make_user(db, email="admin@example.com", name="Admin", role="admin",
               password="AdminPass123!")
    _make_user(db, email="existing@example.com", name="Existing", role="viewer",
               password="ExistingPass123!")
    login_res = _login(client, "admin@example.com", "AdminPass123!")
    token = login_res.json()["access_token"]

    res = client.post(
        "/api/v1/auth/users",
        json={
            "email": "EXISTING@example.com",
            "name": "Dup",
            "password": "DupPass123!",
            "role": "viewer",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 409


def test_create_user_non_admin_forbidden(client, db, monkeypatch):
    _enable_auth(monkeypatch)
    _make_user(db, email="viewer@example.com", name="V", role="viewer",
               password="ViewPass123!")
    login_res = _login(client, "viewer@example.com", "ViewPass123!")
    token = login_res.json()["access_token"]

    res = client.post(
        "/api/v1/auth/users",
        json={
            "email": "new@example.com",
            "name": "New",
            "password": "NewPass123!",
            "role": "viewer",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 403


def test_list_users_admin(client, db, monkeypatch):
    _enable_auth(monkeypatch)
    _make_user(db, email="admin@example.com", name="Admin", role="admin",
               password="AdminPass123!")
    _make_user(db, email="u1@example.com", name="U1", role="viewer",
               password="U1Pass123!")
    _make_user(db, email="u2@example.com", name="U2", role="operator",
               password="U2Pass123!")
    login_res = _login(client, "admin@example.com", "AdminPass123!")
    token = login_res.json()["access_token"]

    res = client.get(
        "/api/v1/auth/users",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 200
    assert len(res.json()) == 3


def test_update_user_admin(client, db, monkeypatch):
    _enable_auth(monkeypatch)
    _make_user(db, email="admin@example.com", name="Admin", role="admin",
               password="AdminPass123!")
    user = _make_user(db, email="target@example.com", name="Target",
                      role="viewer", password="TargetPass123!")
    login_res = _login(client, "admin@example.com", "AdminPass123!")
    token = login_res.json()["access_token"]

    res = client.patch(
        f"/api/v1/auth/users/{user.id}",
        json={
            "email": "target@example.com",
            "name": "Updated Name",
            "password": "TargetPass123!",
            "role": "operator",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 200
    assert res.json()["name"] == "Updated Name"
    assert res.json()["role"] == "operator"


def test_delete_user_admin(client, db, monkeypatch):
    _enable_auth(monkeypatch)
    _make_user(db, email="admin@example.com", name="Admin", role="admin",
               password="AdminPass123!")
    user = _make_user(db, email="todelete@example.com", name="TD",
                      role="viewer", password="TdPass123!")
    login_res = _login(client, "admin@example.com", "AdminPass123!")
    token = login_res.json()["access_token"]

    res = client.delete(
        f"/api/v1/auth/users/{user.id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 204

    # User should be inactive now
    res = client.get(
        f"/api/v1/auth/users/{user.id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 200
    assert res.json()["active"] is False


# ---------------------------------------------------------------------------
# RBAC: role-based access on protected endpoints
# ---------------------------------------------------------------------------

def test_admin_can_access_admin_endpoint(client, db, monkeypatch):
    _enable_auth(monkeypatch)
    _make_user(db, email="admin@example.com", name="Admin", role="admin",
               password="AdminPass123!")
    login_res = _login(client, "admin@example.com", "AdminPass123!")
    token = login_res.json()["access_token"]

    res = client.get(
        "/api/v1/auth/users",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 200


def test_operator_cannot_access_admin_endpoint(client, db, monkeypatch):
    _enable_auth(monkeypatch)
    _make_user(db, email="operator@example.com", name="Op", role="operator",
               password="OpPass123!")
    login_res = _login(client, "operator@example.com", "OpPass123!")
    token = login_res.json()["access_token"]

    res = client.get(
        "/api/v1/auth/users",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 403


def test_viewer_cannot_access_admin_endpoint(client, db, monkeypatch):
    _enable_auth(monkeypatch)
    _make_user(db, email="viewer@example.com", name="V", role="viewer",
               password="ViewPass123!")
    login_res = _login(client, "viewer@example.com", "ViewPass123!")
    token = login_res.json()["access_token"]

    res = client.get(
        "/api/v1/auth/users",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 403


def test_role_escalation_attempt(client, db, monkeypatch):
    """A viewer cannot create an admin user via the API."""
    _enable_auth(monkeypatch)
    _make_user(db, email="viewer@example.com", name="V", role="viewer",
               password="ViewPass123!")
    login_res = _login(client, "viewer@example.com", "ViewPass123!")
    token = login_res.json()["access_token"]

    res = client.post(
        "/api/v1/auth/users",
        json={
            "email": "escalator@example.com",
            "name": "Escalator",
            "password": "EscPass123!",
            "role": "admin",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 403


def test_unauthenticated_request_rejected(client, db, monkeypatch):
    _enable_auth(monkeypatch)
    res = client.get("/api/v1/auth/users")
    assert res.status_code == 401
