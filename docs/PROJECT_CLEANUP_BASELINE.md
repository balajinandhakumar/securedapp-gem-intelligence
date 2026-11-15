# Project Cleanup Baseline

**Repository:** `C:\Users\Balaji\Desktop\securedapp-gem-intelligence`
**Branch:** `main` (2 commits, no remote configured)
**Baseline captured before any cleanup changes.**

## Running processes at baseline

| PID | Command line | Working directory | Port |
| --- | --- | --- | --- |
| 27476 | `"C:\Python314\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8000` | `...\backend` | 8000 |
| 9624 | `node ...\frontend\node_modules\.bin\..\vite\bin\vitee.js --port 3001` | `...\frontend` | 3001 |

Both processes were already running and were reused; no servers were started, killed, or duplicated.

## Git state at baseline

- Branch: `main`, commits: `4db0a93` (feat: complete automatic GeM scheduler...), `c077d22` (fix: reset service module state between scheduler tests)
- Remote: none configured
- Working tree: **55 modified tracked files, 323 untracked files, 0 staged**
- Tracked root files: `.gitignore`, `AUDIT_TRACKING.md`, `docker-compose.yml`, `README.md`, `backend/`, `frontend/`

## Root-folder clutter at baseline

Loose historical phase reports at repo root (untracked): `AUDIT_TRACKING.md`, `FINAL_DIAGNOSTIC_REPORT.md`, `PRODUCTION_READINESS_AUDIT_REPORT.md` and ~60 `PHASE_*.md` files, plus `PHASE_*_EVIDENCE/` directories.

Temporary runtime outputs at repo root: ~70 files — `*.log`, `*.err`, `uvicorn.*`, `vite-*.log`, `browser_*.log`, `frontend_*.log`, `backend_*.log`, and `.txt` dumps (`pytest_*.txt`, `*_out.txt`, `*_results.txt`, `stage2.txt`, `batch.txt`, `focused*.txt`, `intel_*.txt`, `pag_*.txt`, `phase42_db_output*.txt`, `matches_output.txt`, `eval_*.txt`, `verify_*.txt`, ...).

Caches: root `.pytest_cache/`, `.ruff_cache/`; `backend/.pytest_cache/`, `backend/.ruff_cache/`; `__pycache__/` directories and `*.pyc` under `backend/`.

Frontend: `node_modules/` (huge, gitignored), `dist/` (build output, gitignored), `playwright-report/`, `screenshots/`, `test-results/`; temp files `frontend/build.txt`, `build_audit.txt`, `npm_install.txt`, `tsc_audit.txt`, `tsc_check.txt`, `vitest_results.txt`, `vite-dev_p54.out`, `capture_screenshot_tmp.js`.

`logs/` directory with `backend-uvicorn.log`, `frontend-dev.log`, `startup.log`, etc.; empty `general/` directory.

Environment files present locally and correctly gitignored: root `.env` (contains dev `SECRET_KEY`), `backend/.env`, `frontend/.env` (contains demo password `VITE_DEMO_PASSWORD`).

Databases kept locally and gitignored (`*.db`): `dev.db`, `backend/dev.db` (+ `-shm`/`-wal`), `backend/test.db`, dated `dev.db.backup-*` files, `data/dev.db`.

`.gitignore` at baseline covered caches, venvs, IDE, `node_modules`, `frontend/dist/`, `*.db`, `.env`, but was missing `.ruff_cache/`, `*.log`, `*.err`, `test-results/`, `playwright-report/`, `screenshots/`, editor backups (`*.bak*`), SQLite sidecars (`*.shm`, `*.wal`), and local data/backup files.

Loose utility scripts at repo root: `check_*.py`, `cleanup_kw.py`, `gem_full_collect_resumable.py`, `inspect_*.py`, `start_services.ps1`, `stop_services.ps1`, `test_*.py`, `verify_clean.py` (untracked, not under `scripts/`).