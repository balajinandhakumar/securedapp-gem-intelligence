# PHASE_6_1_SCHEDULER_SECURITY_REPORT.md

**Project:** SecuredApp GeM Bid Intelligence Platform  
**Phase:** 6.1 — Final Stabilization  
**Report:** Scheduler & Security Regression  
**Status:** COMPLETE  
**Date:** 2026-11-10  
**Branch:** `main` (all changes uncommitted — never committed/pushed per requirements)  
**Git repo:** `C:\Users\Balaji\Desktop\securedapp-gem-intelligence`

---

## 1. Executive Summary

The scheduler and security regression audit is **complete**. The GeM direct scheduler is enabled and running at the configured 20-minute interval. All security controls are intact — no authentication, authorization, rate limiting, CORS, SSRF protection, or security headers were weakened or disabled.

## 2. Scheduler Verification

### 2.1 Configuration

| Setting | Value | Source |
|---------|-------|--------|
| `GEM_DIRECT_SCHEDULER_ENABLED` | `true` | `backend/app/core/config.py` |
| `GEM_DIRECT_SCHEDULER_INTERVAL_MINUTES` | `20` | `backend/app/core/config.py` |
| `GEM_DIRECT_ENABLED` | `true` | `backend/app/core/config.py` |
| `GEM_DIRECT_ALLOWED_HOSTS` | `gem.gov.in,bidplus.gem.gov.in` | `backend/app/core/config.py` |
| `SOURCE_SCHEDULER_ENABLED` | `true` | `backend/app/core/config.py` |

### 2.2 Runtime Status

The backend log confirms the scheduler is active:

```
app.services.ingestion.gem_scheduler - INFO - GeM direct scheduler loop started (interval=20 minute(s), enabled=True)
app.services.ingestion.gem_scheduler - INFO - GeM direct scheduler started (every 20 minute(s))
```

The scheduler is started in `backend/app/main.py` lifespan via `gem_scheduler.start()` and stopped on shutdown via `gem_scheduler.stop()`. The source scheduler is also started via `source_scheduler.start()`.

### 2.3 Scheduler Activity

During the stabilization window, the scheduler collected new bids (count increased from 43,796 to 43,810), confirming the scheduler is actively running and collecting data.

## 3. Security Regression Audit

### 3.1 Security Headers (verified on live API response)

| Header | Value | Purpose |
|--------|-------|---------|
| `x-content-type-options` | `nosniff` | Prevent MIME-type sniffing |
| `x-frame-options` | `DENY` | Prevent clickjacking |
| `referrer-policy` | `no-referrer` | No referrer information leaked |
| `x-request-id` | (UUID per request) | Request tracing for observability |

### 3.2 Authentication & Authorization

| Control | Status | Detail |
|---------|--------|--------|
| `AUTH_REQUIRED` | `False` (dev) | Production validation requires `True` when `ENVIRONMENT=production` |
| JWT algorithm | HS256 | `AUTH_ALGORITHM = "HS256"` |
| Access token expiry | 30 minutes | `ACCESS_TOKEN_EXPIRE_MINUTES = 30` |
| Refresh token expiry | 7 days | `REFRESH_TOKEN_EXPIRE_DAYS = 7` |
| Login brute-force protection | Enabled | `LOGIN_MAX_ATTEMPTS=5`, `LOGIN_LOCKOUT_MINUTES=15` |
| RBAC (ADMIN/OPERATOR/VIEWER) | Intact | `require_admin`, `require_operator`, `require_viewer` dependencies |

### 3.3 Rate Limiting

| Setting | Value |
|---------|-------|
| `RATE_LIMIT_ENABLED` | `True` |
| `RATE_LIMIT_REQUESTS_PER_MINUTE` | `60` |
| `RATE_LIMIT_BURST` | `10` |

Rate limiting middleware is active in `backend/app/main.py` (skips auth endpoints and health checks).

### 3.4 SSRF Protection

| Control | Status | Detail |
|---------|--------|--------|
| `validate_public_url` | Intact | Validates URLs against public http(s) only |
| `GEM_DIRECT_ALLOWED_HOSTS` | `gem.gov.in,bidplus.gem.gov.in` | SSRF allowlist for GeM document fetches |
| Bid PDF download | Protected | Only `showbidDocument/<id>` URLs served; PDF magic-byte validation |

### 3.5 CORS & Trusted Hosts

| Control | Status |
|---------|--------|
| CORS middleware | Configured with `BACKEND_CORS_ORIGINS` |
| TrustedHostMiddleware | `allowed_hosts=["*"]` in development; explicit hosts required in production |

### 3.6 Production Validation

The `Settings._validate_production_settings` model validator rejects known-development defaults when `ENVIRONMENT=production`:
- Default `SECRET_KEY` rejected
- `SECRET_KEY` must be >= 32 characters
- `AUTH_REQUIRED` must be `True`

No security controls were weakened or disabled during Phase 6.1.

## 4. Constraints Honored

| Constraint | Status |
|------------|--------|
| No auth/security disabled | ✅ All controls intact |
| Scheduler stays enabled if configured | ✅ `GEM_DIRECT_SCHEDULER_ENABLED=true`, 20 min |
| Never committed or pushed | ✅ All changes uncommitted on `main` |
| No data alteration | ✅ Read-only verification |

---

*Report generated on 2026-11-10. All changes remain uncommitted on `main` per project requirements.*
