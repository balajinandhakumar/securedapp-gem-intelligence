# SecuredApp GeM Bid Intelligence

Ingests publicly available Government e-Marketplace (GeM) bids, enriches them with
Bill-of-Quantities (BoQ) evidence, scores each bid against SecuredApp's cyber-security
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

Backend working directory is `backend/`. Configuration is loaded from the repository-root
`.env`, `backend/.env`, and `frontend/.env`. Copies are created from the matching
`.env.example` files; **never commit `.env`** (all are in `.gitignore`).

## Prerequisites

- Python 3.10+ (validated on 3.14.3)
- Node.js 18+ and npm (validated on Node 24)
- (Optional) Docker & Docker Compose

## Backend setup (Windows PowerShell)

```powershell
cd backend
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
# One-off browser download for the GeM public collector:
python -m playwright install chromium
# Copy environment template and adjust locally (never commit backend/.env):
copy ..\.env.example .env   # optional; root .env is the deployment config
copy ..\.env.example backend/.env  # if a backend-specific override is needed
# Database:
alembic upgrade head        # head: 0004_bid_boq_checked_at
python app/seed.py          # seed the SecuredApp product catalogue
```

## Frontend setup (Windows PowerShell)

```powershell
cd frontend
npm install
copy .env.example .env   # adjust VITE_BACKEND_URL if needed; never commit .env
```

## Run (two terminals)

Terminal 1 — Backend API on `http://127.0.0.1:8000` (Swagger docs at `/docs`):

```powershell
cd backend
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

Terminal 2 — Frontend on `http://localhost:3001` (proxies `/api` to `127.0.0.1:8000`):

```powershell
cd frontend
npm run dev -- --host 127.0.0.1 --port 3001
```

## Verify

```powershell
cd backend
python -m pytest -q              # backend suite: 778 tests

cd ..\frontend
npm run test                     # vitest: 61 tests, 7 files
npm run build                    # tsc + vite production build
```

API routes live under `/api/v1`: `health`, `auth` (login/logout/me/refresh/users),
`products` (catalogue), `bids` (intelligence, state-wise, detail/analysis), `dashboard`
(summary + all-india), `ingestion` (GeM Direct fetch/runs/checkpoint), `sources`,
`analysis`, `notifications`. `GET /api/v1/health` reports `database_connected`.

Demo login (development only): `POST /api/v1/auth/login` with the demo account configured
in `frontend/.env` (credentials are local-only, never committed). The Demo Login button on
the frontend is hidden in production unless explicitly authorized.

## Documentation

See [`docs/`](docs/):
- `docs/architecture.md`, `docs/dashboard.md`, `docs/development.md`, `docs/security.md`
  and other operational notes.
- `docs/reports/` — historical phase reports and evidence (PHASE_3_2 … PHASE_8, plus
  `FINAL_DIAGNOSTIC_REPORT.md`, `AUDIT_TRACKING.md`, `PRODUCTION_READINESS_AUDIT_REPORT.md`).
- `docs/PROJECT_CLEANUP_BASELINE.md`, `PROJECT_CLEANUP_REPORT.md`,
  `GITHUB_SECURITY_AUDIT.md`, `STARTUP_VERIFICATION_REPORT.md`,
  `GITHUB_READINESS_REPORT.md` — produced for the startup/cleanup/GitHub-preparation work.

## Docker Compose (recommended for deployment)

The complete application (frontend, backend, PostgreSQL, Redis) can be run with
Docker Compose. This is the recommended deployment method.

### Prerequisites

- Docker Desktop (Windows/macOS) or Docker Engine + Docker Compose (Linux)
- At least 4 GB RAM available for containers

### Environment setup

1. Copy the environment template:
   ```powershell
   copy .env.example .env
   ```
2. Edit `.env` and set at minimum:
   - `SECRET_KEY` — a strong random secret (32+ bytes), e.g.
     `python -c "import secrets; print(secrets.token_urlsafe(32))"`
   - `POSTGRES_PASSWORD` — a strong database password
   - `ENVIRONMENT=production` — enables authentication and production validation
   - `AUTH_REQUIRED=true` — required in production by the backend config validator

### Build and start

```powershell
# Build all services
docker compose build

# Start all services in detached mode
docker compose up -d

# View logs
docker compose logs -f

# Stop all services
docker compose down

# Stop and remove volumes (destroys database data!)
docker compose down -v
```

### Application URLs

| Service | URL |
|---------|-----|
| Frontend | http://localhost:3001 |
| Backend API | http://localhost:8000 |
| Backend API docs (Swagger) | http://localhost:8000/docs |
| Backend health | http://localhost:8000/api/v1/health |
| Backend readiness | http://localhost:8000/api/v1/ready |
| PostgreSQL | localhost:5432 (internal only) |
| Redis | localhost:6379 (internal only) |

### Database configuration

The Docker Compose deployment uses PostgreSQL (image `postgres:15-alpine`) with a
persisted named volume (`postgres_data`). Database credentials are configured via
environment variables in `.env`:

- `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`
- `DATABASE_URL` — full SQLAlchemy connection string

The backend runs `alembic upgrade head` and `python app/seed.py` on startup to
apply migrations and seed the product catalogue. The local development database
(`backend/dev.db`) is never touched or copied into Docker images.

### Migration instructions

Database migrations are applied automatically on backend startup via Alembic.
To run migrations manually:

```powershell
docker compose exec backend python -m alembic upgrade head
```

### Stop and restart

```powershell
# Stop all services (preserves data)
docker compose stop

# Start all services
docker compose start

# Full restart
docker compose restart
```

### Logs and troubleshooting

```powershell
# All service logs
docker compose logs -f

# Backend logs only
docker compose logs -f backend

# Frontend logs only
docker compose logs -f frontend

# Database logs only
docker compose logs -f db
```

### Backup and restore

```powershell
# Backup the PostgreSQL data volume
docker run --rm \
  -v securedapp-gem-intelligence_postgres_data:/source:ro \
  -v C:\path\to\backup:/destination \
  alpine tar czf /destination/postgres_backup.tar.gz -C /source .

# Restore (replace the volume contents)
docker run --rm \
  -v securedapp-gem-intelligence_postgres_data:/destination \
  -v C:\path\to\backup:/source:ro \
  alpine tar xzf /source/postgres_backup.tar.gz -C /destination
```

### Production security notes

- `SECRET_KEY` must be set to a strong random value (32+ bytes) in `.env`
- `AUTH_REQUIRED=true` is required in production; the backend refuses to start
  with the default SECRET_KEY in production mode
- `TRUSTED_HOSTS` should be set to your production domain(s)
- `BACKEND_CORS_ORIGINS` should be set to your frontend's production URL(s)
- `.env` files are gitignored and must never be committed
- The database is not exposed publicly (only accessible internally via Docker network)
- Containers run as non-root where practical (backend runs as `securedapp` user)

## Security notes & known limitations

- `.env` files hold real development values and are **gitignored**; `.env.example`
  templates contain placeholders only.
- `SECRET_KEY` has a development default in `backend/app/core/config.py`; the application
  refuses to start in `ENVIRONMENT=production` with the default key and requires
  `AUTH_REQUIRED=true`. Production deployments must set a strong `SECRET_KEY` (32+ bytes)
  via environment/secret manager.
- `AUTH_REQUIRED` defaults to `false` in development for backward compatibility; protected
  endpoints enforce authentication only when set to `true`.
- Email delivery is not configured (`delivery_configured=false`); notifications are
  persisted with a delivery state but never dispatched.
- The GeM Direct collector is bounded (`GEM_DIRECT_MAX_PAGES`, default 250) and stops on
  GeM blocks/rate-limits (401/403/429/451); no bypass, proxy rotation, or challenge
  solving is attempted. It covers a slice of the public listing, not complete coverage.
- Playwright E2E tests exist under `frontend/tests/e2e` but are not executed against the
  live development database in this build, to avoid mutating real bid/audit records.