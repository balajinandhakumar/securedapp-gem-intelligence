# Security Architecture & Verification Audit

This document records what is actually implemented today. Where a control is
absent, it is listed as absent rather than marked verified.

## 1. Implemented Security Controls

| Control Area | Implementation Mechanism | Status |
| :--- | :--- | :--- |
| **Password Hashing** | `app/core/security.py` provides `hash_password` / `verify_password` with `passlib` (`bcrypt`, `pbkdf2_sha256`). Exercised by `tests/test_models.py`. | `IMPLEMENTED (helper only)` |
| **Secret Loading** | Pydantic `BaseSettings` reads configuration from the environment / `.env`; `.env` is in `.gitignore`. | `IMPLEMENTED` |
| **Input Validation** | Pydantic v2 models enforce types, length, and numeric bounds on every request body, including the product management payloads. | `VERIFIED` |
| **SQL Injection Prevention** | All database access goes through the SQLAlchemy ORM. | `VERIFIED` |
| **Data Ingestion Safety** | Upload size checks, guarded file parsing, and errors surfaced without stack traces. | `VERIFIED` |
| **Audit Logging** | Operations recorded in `audit_logs`, `collection_runs`, and `raw_bid_payloads`. | `VERIFIED` |
| **GeM Access Control** | No scraping, CAPTCHA bypass, rate-limit evasion, or credential misuse is implemented. The live connector is deliberately not built. | `VERIFIED` |

## 2. Known Gaps

These are real and unresolved. They must not be described as implemented.

| Gap | Impact | Required to close |
| :--- | :--- | :--- |
| **No API authentication or authorization** | Every endpoint, including Product Management write operations, is open to any client that can reach the API. Nothing enforces that a caller is an authorized administrator. | Add an auth dependency (session or token), an admin role check, and protect all mutating routes. |
| **No transport security** | The app serves plain HTTP; no TLS termination, HSTS, or secure-cookie policy is configured. | Terminate TLS at the ingress/reverse proxy and set `SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE`, and related flags. |
| **Database URL has an insecure default** | `DATABASE_URL` falls back to a local SQLite file, so a misconfigured deployment silently runs without any external secret. | Fail fast at startup when `ENVIRONMENT` is production and the URL is the default. |
| **Development secret defaults** | `SECRET_KEY` and other settings fall back to development placeholders. A production launch that forgets to set them will run with a publicly known signing key. | Remove the development defaults for production settings, or make startup fail when they are still in place. |
| **No secret scanning in CI** | There is no automated check preventing credentials from being committed. | Add a secret scanner (for example `gitleaks` or `detect-secrets`) to CI and to the pre-commit hook. |
| **CORS is localhost-only** | `BACKEND_CORS_ORIGINS` defaults to the four loopback dev origins, so a real deployment will be blocked from the browser until an operator sets it. This fails closed, which is the safe default, but it is easy to misdiagnose. | Set `BACKEND_CORS_ORIGINS` to the deployed frontend origin at deploy time. |

## 3. Verification Performed

- `.env` is ignored by git; `.env.example` contains templates only.
- Input validation is covered by the test suite for empty/malformed uploads,
  nonexistent IDs, and invalid product payloads.
- Product knowledge management is covered by `tests/test_products.py`,
  including validation, deactivation, and history-preserving deletion.
- Dashboard and bid-intelligence reporting are covered by
  `tests/test_dashboard.py`, which asserts that unanalyzed bids are reported
  honestly rather than being given a fabricated score.
