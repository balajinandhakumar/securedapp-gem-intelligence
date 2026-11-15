# GitHub Security Audit

**Repository:** `C:\Users\Balaji\Desktop\securedapp-gem-intelligence`
**Scope:** tracked files, untracked files, and Git history.
**Convention:** no secret values are displayed in this report.

## Git history

- Branch `main` contains 2 commits only:
  - `4db0a93` feat: complete automatic GeM scheduler with filtered ingestion pipeline
  - `c077d22` fix: reset service module state between scheduler tests
- History contains only tracked source files (`backend/app/`, `backend/tests/`, `frontend/src/`, `docker-compose.yml`, `AUDIT_TRACKING.md`, ...). No `.env` file, no `*.db`, no backup, and no log was ever committed.
- No API keys, JWT secrets, passwords, or tokens found in Git history.

## Working tree — secrets and sensitive files (all local-only, gitignored, NOT in Git)

| File | Content class | Git status |
| --- | --- | --- |
| `.env` (repo root) | Dev `SECRET_KEY`, app config | Untracked + gitignored |
| `backend/.env` | Operational GeM/collection flags (`FIRECRAWL_ENABLED=false`, page budget, scheduler flags) | Untracked + gitignored |
| `frontend/.env` | `VITE_BACKEND_URL`, demo-login flag, **demo account credentials** (`VITE_DEMO_EMAIL` / `VITE_DEMO_PASSWORD`) | Untracked + gitignored |
| `.env.example` (root, `backend/`, `frontend/`) | Placeholder templates only | Untracked (safe to add to first commit) |
| `dev.db`, `backend/dev.db`, `backend/test.db`, `data/dev.db`, `dev.db.backup-*`, `PHASE_6_2_BACKUP/` | SQLite databases and backups (real bids, matches, users, audit records) | Untracked + gitignored via `*.db` / `*.db-*` / `PHASE_6_2_BACKUP/` |
| `1000` | Local export containing real GeM bid records | Untracked + gitignored |

- Demo login (`demo@securedapp.io`) authenticates through the real backend `POST /api/v1/auth/login`; the credential exists only in local `frontend/.env` and in `backend/dev.db`. It was verified working during startup checks and must be rotated before any production use.
- `backend/app/core/config.py` ships a **development default** `SECRET_KEY`. This is a hardcoded default in source, but production is guarded: the app refuses to start with `ENVIRONMENT=production` using the default key, and requires `AUTH_REQUIRED=true`. No change was made (weakening or rotating the default could break local auth/RBAC behavior); the finding is reported for awareness.
- No hardcoded third-party API keys (e.g. Firecrawl) were found in tracked source. `FIRECRAWL_ENABLED=false` in local `backend/.env` only.

## `.gitignore` coverage

Now excludes: `.env`, `backend/.env`, `.env.local`, `*.sqlite`, `*.sqlite3`, `*.db`, `*.db-*`, `*.shm`, `*.wal`, `pgdata/`, `.pytest_cache/`, `.ruff_cache/`, `node_modules/`, `frontend/dist/`, `frontend/build/`, `playwright-report/`, `screenshots/`, `test-results/`, `coverage/`, `*.log`, `*.err`, `*.bak*`, `PHASE_6_2_BACKUP/`, `1000`, `intel_noparam.json`, OS/IDE files.

## Findings and recommendations

1. **No secrets in Git history.** Nothing to rotate for historical leakage; no history rewrite or force-push needed (and none was performed).
2. **Local `.env` files carry real dev values.** They are excluded from Git by `.gitignore`; do not `git add -A` without reviewing, and never commit them.
3. **Demo credentials are local only.** Rotate `VITE_DEMO_PASSWORD` / the `demo@securedapp.io` account before production; keep `VITE_DEMO_LOGIN_AUTHORIZED` off in production.
4. **Development `SECRET_KEY` default in source.** Production deployments must set a strong `SECRET_KEY` (32+ bytes) and `AUTH_REQUIRED=true` via environment/secret manager; startup validation enforces both.
5. **Databases and backups remain out of Git.** Confirmed excluded by `*.db`/`*.db-*` patterns.

## What was NOT done (by design)

- No secrets, databases, or backups were staged or committed.
- No Git history was rewritten or force-pushed.
- No authentication, RBAC, or matching-threshold code was weakened.