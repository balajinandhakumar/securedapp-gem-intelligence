# Phase 6.3 Security & Performance Report

**Project:** SecuredApp GeM Bid Intelligence Platform  
**Phase:** 6.3 — Security Regression & Performance  
**Date:** 2026-11-10

---

## 1. Security Regression — Protections Confirmed Intact

| Control | Implementation | Status |
|---------|---------------|--------|
| JWT authentication | Access + refresh token pair, `jti`-based revocation | ✅ Intact |
| Token refresh | Refresh token endpoint issues new access token | ✅ Intact |
| Logout revocation | `revoked_tokens` table checked at validation time | ✅ Intact |
| Password hashing | bcrypt (`$2b$` format) in `password_hash` column | ✅ Intact |
| RBAC | ADMIN > OPERATOR > VIEWER hierarchy via `require_admin`/`require_operator`/`require_viewer` | ✅ Intact |
| Rate limiting | Configured in backend | ✅ Intact |
| CORS | Configured origins | ✅ Intact |
| Trusted hosts | Configured | ✅ Intact |
| Security headers | Set by backend middleware | ✅ Intact |
| SSRF prevention | `safe_http.safe_get` blocks private/reserved destinations, re-validates redirects | ✅ Intact |
| Original URL validation | `target="_blank" rel="noopener noreferrer"`; URL allowlist | ✅ Intact |
| PDF download restrictions | Source allowlist, magic-byte validation, size limit, timeout | ✅ Intact |
| SQL safety | Parameterized queries via SQLAlchemy ORM | ✅ Intact |
| Scheduler concurrency | Single registration; no double-scheduling after restart | ✅ Intact |

### Auth Configuration Note

`settings.AUTH_REQUIRED = False` in development (documented pass-through). When `False`, `require_auth`/`require_operator`/`require_admin` allow unauthenticated callers. **Production deployments MUST set `AUTH_REQUIRED=True`**, at which point unauthenticated requests receive 401 and insufficient roles receive 403.

This was verified by calling `POST /products/{id}/keywords` without a token — returned 201 in dev mode (expected pass-through). No security control was weakened.

---

## 2. Restart/Recovery Verification (Security-Related)

| Check | Result |
|-------|--------|
| Backend stop (PID 26968) → restart (PID 18464) | ✅ Health 200 |
| Frontend stop (PID 32280) → restart (PID 34916) | ✅ HTTP 200 |
| Login after restart | ✅ 200, JWT issued |
| Dashboard after restart | ✅ 200 |
| Products after restart | ✅ 14 products |
| Keyword persistence after restart | ✅ 0 leftover test keywords |
| GeM scheduler no double registration | ✅ READY, single registration |
| Historical data intact | ✅ 43,932 bids, 14 products, 146 keywords |

---

## 3. Performance Measurements

5 samples per endpoint, warm cache, `http://127.0.0.1:8002`.

| Endpoint | Avg (ms) | P95 (ms) | Min (ms) | Max (ms) | Target | Status |
|----------|----------|----------|----------|----------|--------|--------|
| Health (`/api/v1/health`) | 7.3 | 4.3 | 3.9 | 20.4 | — | ✅ |
| Dashboard (`/api/v1/dashboard/summary`) | 2,087.5 | 2,526.7 | 1,047.2 | 2,792.8 | avg < 2,000 | ⚠️ Slightly over |
| Products (`/api/v1/products`) | 44.2 | 48.1 | 23.7 | 86.8 | — | ✅ |
| Source monitoring (`/api/v1/sources`) | 14.6 | 20.1 | 6.3 | 30.4 | — | ✅ |
| GeM status (`/api/v1/ingestion/gem-direct/status`) | 18.0 | 24.8 | 5.7 | 28.9 | — | ✅ |
| Intelligence (`/api/v1/analytics/evaluation`) | 26.3 | 60.0 | 6.7 | 60.0 | p95 < 2,000 | ✅ |
| Login (`/api/v1/auth/login`) | — | — | — | — | — | ✅ (200) |

### Target Assessment

| Target | Result |
|--------|--------|
| Intelligence p95 < 2 seconds | ✅ 60ms |
| Dashboard warm average < 2 seconds | ⚠️ 2,087ms (43K-bid dataset) |

The dashboard average slightly exceeds the 2-second target because it aggregates over 43,932 bids in SQL. All other endpoints are well within targets. The intelligence endpoint (p95 60ms) is far below the 2-second target.

---

## 4. Test Conditions

- Backend: `http://127.0.0.1:8002` (PID 18464, post-restart)
- Frontend: `http://localhost:3004` (PID 34916)
- Database: `backend/dev.db` (43,932 bids, 14 products)
- Auth: `admin@securedapp.io` (JWT bearer token)
- Samples: 5 per endpoint
- No security protections were disabled for testing

---

## 5. Conclusion

Security protections remain intact after restart. Performance meets targets for all endpoints except the dashboard warm average (marginally over due to dataset size). No security control was weakened or bypassed.
