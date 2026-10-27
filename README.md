# SecuredApp GeM Bid Intelligence

Ingests publicly available Government e-Marketplace (GeM) bids, enriches them with
Bill-of-Quantities (BoQ) evidence, scores each bid against SecuredApp's 11 cyber-security
products, and surfaces the results on a dashboard with relevance explanations and
high-relevance notifications.

## Architecture

| Layer | Technology |
| --- | --- |
| Backend API | FastAPI + Uvicorn (Python 3.10+; validated on 3.14.3) |
| ORM / migrations | SQLAlchemy 2.x + Alembic |
| Validation | Pydantic v2 / pydantic-settings |
| GeM ingestion | Playwright (Chromium) driven public-page collector |
| Database | SQLite by default (`backend/dev.db`); PostgreSQL supported via `DATABASE_URL` |
| Frontend | React 18 + TypeScript + Vite 5 |

Backend CWD is `backend/`. Configuration is loaded from the repository-root `.env`
and `backend/.env` (see `backend/app/core/config.py`). Copies are created from
`.env.example` where present; **never commit `.env` or `backend/.env`** (both in
`.gitignore`).

## Prerequisites

- Python 3.10+ (developed/validated on 3.14.3)
- Node.js 18+ (validated on 24.14.0) and npm
- (Optional) Docker & Docker Compose

## Backend setup

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r backend\requirements.txt
# one-off browser download for the GeM public collector:
python -m playwright install chromium
```

## Frontend setup

```powershell
cd frontend
npm install
```

## Database & seed

```powershell
cd backend
alembic upgrade head        # apply migrations (head: 0004_bid_boq_checked_at)
python app/seed.py          # seed the 11 SecuredApp products
```

## Run (two terminals)

```powershell
# Terminal 1 - API on http://127.0.0.1:8000  (docs: /docs)
cd backend
python -m uvicorn app.main:app --reload --port 8000
```

```powershell
# Terminal 2 - UI on http://localhost:3000  (proxies /api -> 127.0.0.1:8000)
cd frontend
npm run dev
```

Open <http://localhost:3000>.

## Verify

```powershell
cd backend
python -m pytest -q                    # full suite

cd ..\frontend
npm run build                          # tsc && vite build
```

## Triggering a real GeM collection

The GeM Direct collector is manual-triggered from the UI (Ingestion → GeM Direct) or via
the API. A minimal, safe real run uses `max_pages=1` and `preview=false`:

```powershell
$body = @{ urls = @(); keywords = @(); apply_keyword_filter = $false; max_pages = 1; allow_update = $true; auto_notify = $true; preview = $false } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/v1/ingestion/gem-direct/fetch `
  -ContentType 'application/json' -Body $body
```

`preview=true` performs a non-persisting probe. If GeM responds with a block/rate-limit
(401/403/429/451), the run stops with status `BLOCKED` and does not attempt to bypass it.

## Documentation

See [`docs/`](docs/) — start with [`docs/development.md`](docs/development.md),
[`docs/architecture.md`](docs/architecture.md), [`docs/dashboard.md`](docs/dashboard.md),
and [`docs/FINAL_SUBMISSION_REPORT.md`](docs/FINAL_SUBMISSION_REPORT.md).

## Notes & limitations

- Notifications are **generated** and persisted (deduplicated per bid/type) with
  explicit delivery status: `delivery_state` (QUEUED/DELIVERED/FAILED),
  `delivery_configured` (false in this build) and `delivery_note`. **No external
  delivery provider is configured** in this build, so queued alerts are not dispatched
  and no email/SMS delivery is claimed.
- BoQ evidence is persisted with provenance (`source_url`, `retrieved_at`) and used by
  the matching engine; it is also surfaced in the bid-detail API (`boq_items`,
  `boq_checked_at`) and rendered in the bid-detail drawer.
- Matching accuracy is now measurable via `GET /api/v1/analytics/evaluation` and
  `scripts/evaluate_matching.py` (with valid labels only; `MAYBE` excluded, latest-per-bid).
  On the current dataset only 4 distinct bids are labelled, so accuracy is reported as
  **unmeasured** (see `docs/FINAL_SUBMISSION_REPORT.md`).
