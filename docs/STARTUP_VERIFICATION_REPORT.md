# Startup Verification Report

**Repository:** `C:\Users\Balaji\Desktop\securedapp-gem-intelligence`
**Both applications were already running and were reused** — no processes were killed and no duplicate servers were started.

## Processes and URLs

| Process | PID | Command line | Working directory | URL |
| --- | --- | --- | --- | --- |
| Backend (uvicorn) | 27476 | `"C:\Python314\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8000` | `...\backend` | `http://127.0.0.1:8000` |
| Frontend (Vite dev server) | 9624 | `node ...\frontend\node_modules\.bin\..\vite\bin\vitee.js --port 3001` | `...\frontend` | `http://localhost:3001` |

Notes: backend runs without `--reload` (pre-existing process, reused as-is). Frontend proxies `/api` → `http://127.0.0.1:8000` (`vite.config.ts`); `VITE_BACKEND_URL=http://127.0.0.1:8000` in local `frontend/.env`.
Swagger UI: `http://127.0.0.1:8000/docs`; OpenAPI: `http://127.0.0.1:8000/api/v1/openapi.json`.

## Backend verification

- `GET /` → `{"message":"Welcome to SecuredApp GeM Bid Intelligence Platform API","docs":"/docs","version":"0.1.0"}`
- `GET /api/v1/health` → `{"status":"ok","project_name":"...","environment":"development","database_connected":true}` — **database connectivity verified (SQLite `backend/dev.db`)**.
- `GET /api/v1/openapi.json` → 55 routes across 22 dirs, including:

  - `GET /api/v1/health` — health + DB status
  - `POST /api/v1/auth/login`, `/auth/logout`, `/auth/me`, `/auth/refresh`, `/auth/users` — auth + RBAC (admin/operator/viewer)
  - `GET /api/v1/products`, `GET|PUT|DELETE /api/v1/products/{id}` — **Product Catalogue** (14 products seeded)
  - `GET /api/v1/bids/intelligence`, `GET|POST /api/v1/bids/state-wise`, `GET /api/v1/bids/{id}`, `/analyze`, `/match-products`, `/analysis`, `/review` — bids and matching
  - `GET /api/v1/dashboard/summary`, `GET|POST /api/v1/dashboard/all-india/{bids,match-all,summary}` — **Dashboard + All India**
  - `POST /api/v1/ingestion/gem-direct/fetch`, `/status`, `/checkpoint`, `/reconcile` — GeM ingestion
  - `GET /api/v1/analytics/evaluation` — matching evaluation

- **Login verified:** `POST /api/v1/auth/login` with `demo@securedapp.io` issued a JWT access + refresh token pair; user role `admin`, active. `GET /api/v1/auth/me` returns the profile.
- **Dashboard verified:** `GET /api/v1/dashboard/summary` returns match bands, action-required bids, recent activity.
- **All India verified:** `GET /api/v1/dashboard/all-india/bids` → 48 bids with product match, relevance score, explanation.
- **State-wise verified:** `GET /api/v1/bids/state-wise/summary` → 31 state e-procurement sources with collection status (e.g. Assam 134 collected, Delhi 217, Maharashtra 366, Tamil Nadu 415; Goa BLOCKED 403).
- **API communication (frontend→backend):** Vite dev server at `:3001` proxies `/api` to `:8000`; frontend HTML loads and `src/lib/api.ts` calls relative `/api/v1/*` paths through the proxy.

## Frontend verification

- `http://localhost:3001` serves the React app (`index.html`, Vite dev).
- Configured routes/views: Login, Dashboard, ProductsView, AllIndiaMatchesView, StateWiseBidsView, BidsFeedView, IngestionView, NotificationsView, SourceManagementPanel, GeMDirectSourcePanel, BidDetailDrawer, AccessDenied.
- Frontend tests: **7 files, 61 passed, 0 failed** (`npm run test` / vitest 3.2.7).
- TypeScript + production build: **`npm run build` (`tsc && vite build`) succeeded** — `dist/index.html`, `assets/index-*.css` (31.62 kB), `assets/index-*.js` (336.71 kB).

## Backend test results

Backend suite: `python -m pytest -q` from `backend/` (in-memory SQLite, live GeM/Playwright boundaries guarded):

- 706 tests passed (core suite, excludes scheduler modules)
- 72 tests passed (`test_gem_scheduler.py`, `test_source_scheduler.py`, `test_gem_windows_event_loop.py`, `test_source_hardening.py`)
- **Total: 778 passed, 0 failed.**

Playwright E2E tests exist under `frontend/tests/e2e` (5 specs) with Chromium browsers installed, but were **not executed against the live development database** to avoid mutating real bid/audit records — listed as a known limitation, not a regression.

## Known limitations (pre-existing, not caused by this session)

- Backend process runs without `--reload`; AUTH_REQUIRED defaults to `false` in development (protected endpoints enforce auth only in production or when enabled).
- Email notification delivery is not configured (notifications persisted, never dispatched).
- GeM Direct collector is page-budgeted (default 250 pages) and stops on GeM 401/403/429/451; not complete coverage.