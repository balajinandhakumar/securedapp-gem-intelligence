# PHASE 7 — PRODUCTION DEPLOYMENT GUIDE

**SecuredApp GeM Bid Intelligence Platform**
**Version:** 1.0 — Phase 7 (Production Deployment Preparation)
**Status:** PREPARED — not live

---

## 1. Overview

This guide prepares the SecuredApp GeM Bid Intelligence Platform for production deployment. The platform is designed for:

- **Local demonstration** (single-user, SQLite backend on port 8002, frontend on port 3004).
- **Controlled pilot** (small team, PostgreSQL backend, reverse proxy).
- **Public deployment** (multi-user, PostgreSQL, HTTPS, strict security configuration).

**No public deployment has been performed.** The production configuration is PREPARED but NOT LIVE. Do not deploy to a public server, modify DNS, purchase hosting, or expose ports without explicit authorization.

---

## 2. Architecture

### Development (current, verified)

```
Frontend (Vite dev, port 3004)  -->  Backend (uvicorn, port 8002)  -->  SQLite (dev.db)
```

### Production (prepared, not verified live)

```
Frontend (production build, served via reverse proxy)
        -->  Reverse Proxy (nginx/TLS termination, port 443)
        -->  Backend (uvicorn/gunicorn, port 8000)
        -->  PostgreSQL (port 5432)
        -->  Redis (optional, port 6379, for distributed rate limiting)
```

Docker configuration exists at:
- `backend/Dockerfile`
- `docker-compose.yml` (PostgreSQL 15 + Redis 7 + backend)

---

## 3. Environment Configuration

### 3.1 Backend (`backend/.env.example`)

A production-ready template exists at `backend/.env.example`. Copy to `backend/.env` and adjust:

```
ENVIRONMENT=production
LOG_LEVEL=INFO
SECRET_KEY=<generate with: python -c "import secrets; print(secrets.token_urlsafe(32))">
AUTH_REQUIRED=true
DATABASE_URL=postgresql://securedapp:CHANGE_ME@db:5432/securedapp_gem
TRUSTED_HOSTS=app.example.com
BACKEND_CORS_ORIGINS=https://app.example.com
```

**Never commit `.env`.** It is gitignored.

### 3.2 Frontend (`frontend/.env.example`)

```
VITE_ENVIRONMENT=production
VITE_BACKEND_URL=https://api.example.com
VITE_DEMO_LOGIN_ENABLED=false
```

Demo Login is disabled by default in production. Do not set `VITE_DEMO_PASSWORD` in production.

### 3.3 Secret generation (owner-supplied)

The owner must generate secrets locally:

```powershell
# Secret key
python -c "import secrets; print(secrets.token_urlsafe(32))"

# Database password (PostgreSQL)
# Use a strong random password, store in secret manager
```

**Never print secrets in reports or screenshots.**

---

## 4. Authentication (Production)

| Setting | Development | Production |
|---------|-------------|------------|
| `AUTH_REQUIRED` | `false` | **`true`** |
| `SECRET_KEY` | dev default | **strong random (32+ bytes)** |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | 30 | 30 (or shorter) |
| `REFRESH_TOKEN_EXPIRE_DAYS` | 7 | 7 |
| Demo Login | enabled | **disabled** |

Protected routes enforced:
- `POST /api/v1/auth/login` — rate limited, account lockout after failures
- `POST /api/v1/auth/logout` — revokes access + refresh tokens
- `POST /api/v1/auth/refresh` — new access token from refresh token
- `GET /api/v1/auth/me` — current user (auth required)
- All bid/product/admin endpoints — auth + RBAC

Password hashing: bcrypt. Account lockout: configurable attempts + lockout window. Role-based access control: Admin / Operator / Viewer.

---

## 5. Trusted Hosts and CORS

| Setting | Development | Production |
|---------|-------------|------------|
| `TRUSTED_HOSTS` | unset (all hosts) | **exact production host(s)** |
| `BACKEND_CORS_ORIGINS` | localhost:3000, 5173, etc. | **exact production frontend origin** |
| CORS methods | GET, POST, PUT, DELETE, OPTIONS | same, restricted |
| CORS headers | Content-Type, Authorization, etc. | same, restricted |
| Cookies | N/A (token in header) | Secure, SameSite=strict, HttpOnly |

No wildcard CORS (`*`) in production. TrustedHostMiddleware rejects requests with unknown Host headers.

---

## 6. Security Headers and Rate Limiting

Verified in `backend/app/main.py`:

- **Content-Type sniffing protection:** `X-Content-Type-Options: nosniff`
- **Frame protection:** `X-Frame-Options: DENY`
- **Referrer policy:** `Referrer-Policy: strict-origin-when-cross-origin`
- **Cache policy:** `Cache-Control: no-store` on sensitive responses
- **Rate limiting:** in-memory sliding window per client IP (single-instance); replace with Redis-backed for multi-instance
- **Request ID logging:** `X-Request-ID` on every request
- **Error sanitization:** errors return generic messages, no stack traces to client
- **SSRF protection:** original source URL allowlisting (`gem.gov.in`, `bidplus.gem.gov.in` only)
- **PDF download restrictions:** served only from allowlisted sources

Do not weaken any of these protections.

---

## 7. Database (PostgreSQL Production)

### 7.1 Configuration

```yaml
# docker-compose.yml (existing)
db:
  image: postgres:15-alpine
  environment:
    POSTGRES_USER: securedapp
    POSTGRES_PASSWORD: <owner-supplied>
    POSTGRES_DB: securedapp_gem
```

### 7.2 Alembic migrations

```bash
# From backend/
python -m alembic upgrade head
```

Migration rollback:
```bash
python -m alembic downgrade -1
```

**Do not automatically migrate or copy the live development database into production without a verified migration plan and owner approval.**

### 7.3 Connection pooling

SQLAlchemy engine with `pool_pre_ping=True`. For production multi-instance, configure pool size and overflow.

---

## 8. Deployment Steps

### 8.1 Local demonstration (verified)

```powershell
.\start_services.ps1
# Backend: http://127.0.0.1:8002
# Frontend: http://localhost:3004
.\stop_services.ps1
```

### 8.2 Controlled pilot (prepared)

1. Copy `backend/.env.example` to `backend/.env`; set `AUTH_REQUIRED=true`, `SECRET_KEY`, `DATABASE_URL=postgresql://...`
2. Start PostgreSQL (via docker-compose or existing instance).
3. Run `python -m alembic upgrade head` from `backend/`.
4. Run `python app/seed.py` from `backend/` to seed products.
5. Start backend: `uvicorn app.main:app --host 127.0.0.1 --port 8000`.
6. Build frontend: `cd frontend && npm run build` (output in `frontend/dist/`).
7. Serve frontend via reverse proxy pointing to backend API.

### 8.3 Public deployment (PREPARED, NOT LIVE)

Requirements before going live:
- [ ] Domain name selected and DNS configured
- [ ] TLS certificate obtained (Let's Encrypt or commercial)
- [ ] PostgreSQL provisioned and backed up
- [ ] `AUTH_REQUIRED=true`, strong `SECRET_KEY` set
- [ ] `TRUSTED_HOSTS` set to exact production host
- [ ] `BACKEND_CORS_ORIGINS` set to exact production frontend origin
- [ ] HTTPS enforced at reverse proxy
- [ ] Database backup tested
- [ ] Database restore tested
- [ ] Migration process verified
- [ ] Health/readiness endpoints verified
- [ ] Rollback procedure documented

Do not mark untested configuration as production-ready.

---

## 9. Reverse Proxy (nginx) — Example

```nginx
server {
    listen 443 ssl;
    server_name app.example.com;
    ssl_certificate /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;

    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location / {
        root /var/www/frontend;
        try_files $uri /index.html;
    }
}
```

---

## 10. Health and Readiness

- **Health:** `GET /api/v1/health` → `{"status":"ok", ...}`
- **GeM status:** `GET /api/v1/ingestion/gem-direct/status`
- **Database connectivity:** included in health response (`database_connected`)

---

## 11. Logging and Monitoring

- Backend logs to `logs/backend-uvicorn.log` and `logs/backend-uvicorn-err.log`.
- Frontend dev logs to `logs/vite-dev.log` and `logs/vite-dev-err.log`.
- Production: forward logs to central logging; monitor health endpoint.

---

## 12. Backup and Restore

See `PHASE_7_DATABASE_BACKUP_AND_RECOVERY_GUIDE.md`.

---

## 13. Rollback

1. Revert application code to previous version.
2. Run `python -m alembic downgrade -1` if schema changed.
3. Restore database from pre-deployment backup if needed.

---

## 14. Final Deployment Status

| Checklist Item | Status |
|----------------|--------|
| Authentication enforced (`AUTH_REQUIRED=true`) | Prepared (not verified live) |
| Production secret configured securely | Template created |
| Strict trusted hosts | Template created |
| Exact production CORS | Template created |
| HTTPS configured | Guidance provided |
| PostgreSQL deployment | Docker compose exists |
| Database backup tested | Not yet |
| Database restore tested | Not yet |
| Migration process verified | Not yet |
| Admin account secured | Prepared |
| Demo login disabled | Template has `VITE_DEMO_LOGIN_ENABLED=false` |
| No credentials in source code | Verified |
| Security headers verified | Verified in code |
| Rate limiting verified | Verified in code |
| SSRF protection verified | Verified in code |
| Health/readiness endpoints verified | Verified (HTTP 200) |
| Restart/recovery tested | Not yet (production) |
| All critical tests pass | Verified (766 backend, 50 frontend, 6/6 Playwright) |
| Deployment rollback documented | In this guide |

**Verdict: Production Configuration = PREPARED (not verified live). Public Deployment = NOT LIVE.**

---

## 15. What Not to Do

- Do not deploy to a public server without authorization.
- Do not modify DNS or purchase hosting.
- Do not expose ports beyond what is necessary.
- Do not publish credentials.
- Do not hardcode `SECRET_KEY` or database passwords.
- Do not disable authentication for convenience.
- Do not use wildcard CORS in production.
- Do not copy dev.db to production without a verified migration plan.

---

*End of Production Deployment Guide*
