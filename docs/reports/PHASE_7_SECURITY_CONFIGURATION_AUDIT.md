# PHASE 7 — SECURITY CONFIGURATION AUDIT

**SecuredApp GeM Bid Intelligence Platform**
**Version:** 1.0 — Phase 7 (Security Audit)
**Status:** Development configuration hardened; production template prepared

---

## 1. Audit Scope

This audit reviews the security configuration of the SecuredApp GeM Bid Intelligence Platform, covering:

- Authentication and authorization
- Secrets management
- Trusted hosts and CORS
- Security headers and rate limiting
- SSRF protection
- Error handling and logging

**No real secrets, passwords, tokens, or personal data are included in this report.**

---

## 2. Authentication and Authorization

### 2.1 Current state (development)

| Setting | Value | Notes |
|---------|-------|-------|
| `AUTH_REQUIRED` | `false` | Development only — must be `true` for production |
| `SECRET_KEY` | dev default | Must be replaced with strong random value in production |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | 30 | Reasonable |
| `REFRESH_TOKEN_EXPIRE_DAYS` | 7 | Reasonable |
| Password hashing | bcrypt | Verified in `app/core/auth.py` |
| Account lockout | Configurable | `LOGIN_MAX_ATTEMPTS`, `LOGIN_LOCKOUT_MINUTES` |
| Role-based access control | Admin / Operator / Viewer | Verified |
| Refresh token revocation on logout | Yes | `POST /api/v1/auth/logout` revokes access + refresh |

### 2.2 Protected routes

All protected endpoints return 401 without a valid token and 403 for insufficient role:

- `POST /api/v1/auth/login` — rate limited, tracks failures for lockout
- `POST /api/v1/auth/logout` — revokes tokens
- `GET /api/v1/auth/me` — auth required
- `POST /api/v1/auth/refresh` — refresh token required
- Bid, product, keyword, source endpoints — auth + RBAC

### 2.3 Demo Login

Demo Login authenticates through the **real backend** (`POST /api/v1/auth/login`). It does:
- Not bypass JWT authentication.
- Not expose credentials in frontend source code.
- Not grant unnecessary administrator permissions beyond the demo user's actual role.
- Is controlled by environment configuration (`VITE_DEMO_LOGIN_ENABLED`, `VITE_DEMO_LOGIN_AUTHORIZED`).
- Can be disabled for production.

**Security fix applied:** Removed hardcoded `VITE_DEMO_PASSWORD=DemoPass123!` from `frontend/.env`. Replaced with placeholder comment. The owner must set the password locally.

---

## 3. Secrets Management

### 3.1 Environment files

| File | Status | Notes |
|------|--------|-------|
| `frontend/.env` | gitignored | Demo password removed; placeholder added |
| `frontend/.env.example` | tracked | No real secrets; placeholders only |
| `backend/.env` | gitignored | No secrets committed |
| `backend/.env.example` | tracked | Production placeholders only (SECRET_KEY, AUTH_REQUIRED, DATABASE_URL, etc.) |

### 3.2 Gitignore coverage

`.gitignore` covers:
- `.env`
- `.env.local`
- `backend/.env`
- `*.db`, `*.sqlite`, `*.sqlite3`

### 3.3 Frontend Vite variables

No JWT secrets in `VITE_` variables. Only non-secret deployment values:
- `VITE_ENVIRONMENT`
- `VITE_BACKEND_URL`
- `VITE_DEMO_LOGIN_ENABLED`
- `VITE_DEMO_LOGIN_AUTHORIZED`
- `VITE_DEMO_EMAIL` (demo only, no password)

### 3.4 No credentials in source code

Verified: no passwords, tokens, or secrets hardcoded in frontend or backend source code. The demo user exists in the database, not in source.

---

## 4. Trusted Hosts and CORS

### 4.1 TrustedHostMiddleware

Implemented in `backend/app/main.py`. Rejects requests with unknown `Host` headers.

| Environment | Configuration |
|-------------|---------------|
| Development | Unset (allows all hosts) |
| Production | Set to exact production host(s) via `TRUSTED_HOSTS` |

### 4.2 CORS

Implemented via `CORSMiddleware` in `backend/app/main.py`.

| Environment | Configuration |
|-------------|---------------|
| Development | `localhost:3000`, `localhost:5173`, `127.0.0.1:3000`, `127.0.0.1:5173` |
| Production | Exact production frontend origin(s) via `BACKEND_CORS_ORIGINS` |

No wildcard CORS (`*`). Allowed methods: GET, POST, PUT, DELETE, OPTIONS. Allowed headers: Content-Type, Authorization, etc.

---

## 5. Security Headers

Implemented in `backend/app/main.py` response middleware:

| Header | Value | Purpose |
|--------|-------|---------|
| `X-Content-Type-Options` | `nosniff` | Prevent MIME-type sniffing |
| `X-Frame-Options` | `DENY` | Prevent clickjacking |
| `Referrer-Policy` | `strict-origin-when-cross-origin` | Control referrer information |
| `Cache-Control` | `no-store` (on sensitive responses) | Prevent caching of sensitive data |
| `X-Request-ID` | unique per request | Request tracing |

### 5.1 Verified

- Content-type protection: ✅
- Frame protection: ✅
- Referrer policy: ✅
- Cache policy: ✅

No weakening of these protections.

---

## 6. Rate Limiting

Implemented as in-memory sliding-window rate limiter per client IP in `backend/app/main.py`.

| Setting | Value |
|---------|-------|
| Enabled | `true` |
| Requests per minute | 60 |
| Burst | 10 |

**Limitation:** Single-process, in-memory. For multi-instance production deployments, replace with Redis-backed rate limiting.

Login endpoint is rate limited and tracks failures for brute-force protection and account lockout.

---

## 7. SSRF Protection

Server-Side Request Forgery protection implemented in the GeM direct collector:

| Protection | Implementation |
|------------|----------------|
| Allowed hosts | `gem.gov.in`, `bidplus.gem.gov.in` only |
| Credentials | No GeM credentials used |
| Block handling | Stops with status `BLOCKED` on 403/429/block page |
| Retry policy | No aggressive retry; no bypass attempted |

Original source URLs are allowlisted. PDF downloads are restricted to allowlisted sources.

---

## 8. Error Handling and Logging

| Feature | Implementation |
|---------|----------------|
| Error response sanitization | Generic error messages to client; no stack traces |
| Request ID logging | `X-Request-ID` on every request |
| Login failure tracking | Tracked for brute-force and lockout |
| Passwords in logs | Never logged |
| Sensitive data in logs | Not logged |

---

## 9. Security Checklist

| Item | Status |
|------|--------|
| `AUTH_REQUIRED=true` for production | Template ready (dev: false) |
| Strong `SECRET_KEY` via env var | Template ready |
| JWT token expiration configured | ✅ (30 min access, 7 day refresh) |
| Refresh token revocation on logout | ✅ |
| Password hashing (bcrypt) | ✅ |
| Account lockout | ✅ (configurable) |
| Role-based access control | ✅ |
| Protected administrative endpoints | ✅ |
| No real secrets in source code | ✅ |
| No passwords in frontend code | ✅ |
| No JWT secrets in Vite variables | ✅ |
| No credentials in Git-tracked config | ✅ |
| `.env` files gitignored | ✅ |
| `.env.example` placeholders only | ✅ |
| Strict production trusted hosts | Template ready |
| Exact production CORS origin | Template ready |
| No wildcard CORS | ✅ |
| Secure cookie configuration | N/A (token in header) |
| HTTPS requirements | Guidance provided |
| Content-type protection | ✅ |
| Frame protection | ✅ |
| Referrer policy | ✅ |
| Cache policies | ✅ |
| Rate limiting | ✅ (in-memory; Redis for multi-instance) |
| Request ID logging | ✅ |
| Error response sanitization | ✅ |
| SSRF protection | ✅ |
| Original source URL allowlisting | ✅ |
| PDF download restrictions | ✅ |
| No credentials in reports/screenshots | ✅ |

---

## 10. Known Gaps (Production)

| Gap | Impact | Mitigation |
|-----|--------|------------|
| Rate limiting is in-memory (single-process) | Not distributed across instances | Replace with Redis-backed for multi-instance |
| `AUTH_REQUIRED=false` in development | Not suitable for production | Set `AUTH_REQUIRED=true` in production |
| Dev `SECRET_KEY` default | Insecure if used in production | Replace with strong random key |
| SQLite dev database | Single-user only | Use PostgreSQL for production |

---

## 11. What Not to Do

- Do not disable authentication for convenience.
- Do not hardcode `SECRET_KEY` or database passwords.
- Do not use wildcard CORS in production.
- Do not weaken security headers, rate limiting, CORS, or SSRF protection.
- Do not print secrets in reports or screenshots.
- Do not commit `.env` files.

---

*End of Security Configuration Audit*
