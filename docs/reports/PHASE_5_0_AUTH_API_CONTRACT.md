# PHASE 5.0 AUTH API CONTRACT

**Status:** Final (Session 1 handoff)  
**Date:** 2026-11-07  
**Owner:** Backend Team  
**Consumer:** Frontend Team (Session 1)

---

## 1. Overview

This document defines the authentication and authorization API contract for the
SecuredApp GeM Bid Intelligence Platform backend. All auth endpoints live under
the `/api/v1/auth` prefix. The contract is designed for frontend consumption
(Session 1) and is stable for production integration.

Base URL: `https://<backend-host>/api/v1/auth`  
Auth scheme: `Authorization: Bearer <access_token>`  
Content-Type: `application/json`

---

## 2. Authentication Model

- **JWT-based** access + refresh tokens (PyJWT, HS256).
- **Access tokens:** short-lived (default 30 minutes), carry `sub` (user id),
  `email`, `role`, `jti`, `iat`, `exp`, `type=access`.
- **Refresh tokens:** longer-lived (default 7 days), carry `sub`, `email`,
  `jti`, `iat`, `exp`, `type=refresh`. Used only to obtain new access tokens.
- **Revocation:** JTI-based revocation table. Logout revokes the access token
  (from the `Authorization` header) and/or a refresh token (from the request
  body). Revoked tokens are rejected immediately.
- **Password hashing:** PBKDF2-HMAC-SHA256 (via existing `app.core.security`).
  No plaintext passwords are stored or logged.

---

## 3. Endpoints

### 3.1 POST /login

Authenticate with email + password and receive a token pair.

**Request:**
```json
{
  "email": "user@example.com",
  "password": "SecurePassword123!"
}
```

**Response (200):**
```json
{
  "access_token": "<jwt>",
  "refresh_token": "<jwt>",
  "token_type": "bearer",
  "expires_in": 1800,
  "user": {
    "id": "<uuid>",
    "email": "user@example.com",
    "name": "User Name",
    "role": "viewer",
    "active": true
  }
}
```

**Errors:**
- `401` Invalid email or password (account may be locked).
- `401` Account temporarily locked due to failed login attempts.
- `422` Validation error (missing fields, password < 8 chars, invalid email).

**Brute-force protection:**
- Accounts lock after `LOGIN_MAX_ATTEMPTS` (default 5) consecutive failures.
- Lockout lasts `LOGIN_LOCKOUT_MINUTES` (default 15).
- Successful login resets the failure counter.
- Unknown emails and wrong passwords both return `401` (no user enumeration).

### 3.2 POST /logout

Revoke the current access token and/or a refresh token.

**Request (access token in Authorization header):**
```http
POST /api/v1/auth/logout
Authorization: Bearer <access_token>
Content-Type: application/json

{}
```

**Request (with refresh token revocation):**
```json
{
  "refresh_token": "<jwt>"
}
```

**Response (200):**
```json
{
  "detail": "Logged out successfully."
}
```

**Notes:**
- The access token's JTI is extracted from the `Authorization: Bearer` header.
- If a `refresh_token` is supplied in the body, it is revoked too.
- Access tokens are short-lived (30 min default) and self-expire; revocation
  makes logout effective immediately.

### 3.3 GET /me

Return the profile of the currently authenticated user.

**Request:**
```http
GET /api/v1/auth/me
Authorization: Bearer <access_token>
```

**Response (200):**
```json
{
  "id": "<uuid>",
  "email": "user@example.com",
  "name": "User Name",
  "role": "admin",
  "active": true
}
```

**Errors:**
- `401` No valid token presented (when `AUTH_REQUIRED=true`).

### 3.4 POST /refresh

Exchange a valid refresh token for a new access token.

**Request:**
```json
{
  "refresh_token": "<jwt>"
}
```

**Response (200):**
```json
{
  "access_token": "<new-jwt>",
  "token_type": "bearer",
  "expires_in": 1800
}
```

**Errors:**
- `401` Invalid or expired refresh token.
- `401` Invalid token type (not a refresh token).
- `401` Refresh token has been revoked.
- `401` User not found or disabled.

### 3.5 POST /users (ADMIN only)

Create a new user account.

**Request:**
```json
{
  "email": "newuser@example.com",
  "name": "New User",
  "password": "NewPass123!",
  "role": "operator",
  "active": true
}
```

**Response (201):** Same shape as `GET /me` response (no `password_hash`).

**Errors:**
- `401` Not authenticated (when `AUTH_REQUIRED=true`).
- `403` Caller is not ADMIN.
- `409` Email already exists.
- `422` Validation error.

### 3.6 GET /users (ADMIN only)

List all user accounts.

**Response (200):** Array of user objects (same shape as `GET /me`).

**Errors:**
- `401` Not authenticated.
- `403` Caller is not ADMIN.

### 3.7 GET /users/{user_id} (ADMIN only)

Get a single user by ID.

**Response (200):** User object.

**Errors:**
- `401` Not authenticated.
- `403` Caller is not ADMIN.
- `404` User not found.

### 3.8 PATCH /users/{user_id} (ADMIN only)

Update a user's name, role, or active status.

**Request:** Same fields as `POST /users` (all optional except those required
by schema).

**Response (200):** Updated user object.

**Errors:**
- `401` Not authenticated.
- `403` Caller is not ADMIN.
- `404` User not found.

### 3.9 DELETE /users/{user_id} (ADMIN only)

Deactivate a user (soft delete via `active=false`). All known tokens are
revoked.

**Response (204):** No content.

**Errors:**
- `401` Not authenticated.
- `403` Caller is not ADMIN.
- `404` User not found.

---

## 4. RBAC Model

**Roles:** `ADMIN` > `OPERATOR` > `VIEWER`

| Role | Can read | Can write products/bids | Can manage sources | Can manage users | Can run matching |
|------|----------|------------------------|--------------------|------------------|------------------|
| ADMIN | ✅ | ✅ | ✅ | ✅ | ✅ |
| OPERATOR | ✅ | ✅ | ✅ | ❌ | ✅ |
| VIEWER | ✅ | ❌ | ❌ | ❌ | ❌ |

**Authorization enforcement:**
- `require_auth`: 401 when unauthenticated (only when `AUTH_REQUIRED=true`).
- `require_admin`: 403 when caller is not ADMIN.
- `require_operator`: 403 when caller is VIEWER (or unauthenticated).
- `require_viewer`: 401 when unauthenticated (only when `AUTH_REQUIRED=true`).

**Backward compatibility:** `AUTH_REQUIRED=false` (development default) makes
all auth dependencies pass-through. Production **must** set `AUTH_REQUIRED=true`.

---

## 5. Error Response Format

All errors return a JSON body with a `detail` field:

```json
{
  "detail": "Human-readable error message"
}
```

Standard status codes:
- `401` Authentication required / invalid token / expired / revoked.
- `403` Insufficient role for the requested action.
- `404` Resource not found.
- `409` Conflict (duplicate email, etc.).
- `422` Request validation error (Pydantic).

---

## 6. Security Headers

All responses include:
- `X-Content-Type-Options: nosniff`
- `X-Frame-Options: DENY`
- `Referrer-Policy: no-referrer`
- `X-Request-ID: <uuid>` (for log correlation)

In production, the `Server` header is suppressed.

---

## 7. Initial Administrator Setup

No default administrator account is created. The first admin must be created
explicitly via the bootstrap command:

```bash
# From the backend directory
python -m app.scripts.create_admin \
    --email admin@securedapp.io \
    --name "Platform Administrator" \
    --password '<strong-password>'
```

Or via environment variable:
```bash
ADMIN_PASSWORD=<strong-password> python -m app.scripts.create_admin \
    --email admin@securedapp.io \
    --name "Platform Administrator" \
    --password-env ADMIN_PASSWORD
```

- The command is a no-op if any users already exist (prevents accidental
  overwrites).
- Password must be at least 8 characters.
- Password is never echoed or logged.

---

## 8. Configuration (Environment Variables)

| Variable | Default | Description |
|----------|---------|-------------|
| `SECRET_KEY` | dev default | JWT signing key (32+ chars required in production) |
| `AUTH_REQUIRED` | `false` | Enforce authentication on protected endpoints |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `30` | Access token lifetime |
| `REFRESH_TOKEN_EXPIRE_DAYS` | `7` | Refresh token lifetime |
| `LOGIN_MAX_ATTEMPTS` | `5` | Failed logins before lockout |
| `LOGIN_LOCKOUT_MINUTES` | `15` | Lockout duration |
| `ENVIRONMENT` | `development` | Deployment environment |
| `TRUSTED_HOSTS` | `*` | Allowed hostnames (production) |

---

## 9. Integration Notes for Frontend (Session 1)

1. Store `access_token` and `refresh_token` in memory (not localStorage) to
   reduce XSS risk. Use `sessionStorage` if persistence across page reloads is
   needed.
2. Send `Authorization: Bearer <access_token>` on all authenticated requests.
3. On `401` from a refresh request, redirect to login.
4. On `403`, show "insufficient permissions" UI.
5. Call `POST /logout` on sign-out to revoke tokens.
6. Call `POST /refresh` before access token expiry (recommend at 25 min).
7. All timestamps are ISO-8601 UTC.

---

## 10. OpenAPI / Docs

Interactive API documentation is available at `/docs` (Swagger UI) and
`/redoc` when the backend is running. The auth router is tagged
`Authentication`.
