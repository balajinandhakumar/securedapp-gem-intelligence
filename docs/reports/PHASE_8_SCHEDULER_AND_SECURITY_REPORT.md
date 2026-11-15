# PHASE 8 — SCHEDULER AND SECURITY REPORT (8F)

**SecuredApp GeM Bid Intelligence Platform**
**Version:** 1.0 — Phase 8 (State/UT Scraper Pipeline)
**Date:** 2026-11-10
**Scope:** Scheduler safety and security posture preserved during Phase 8

---

## 1. Executive Summary

Phase 8 does not introduce any new network exposure or weaken security. The
existing per-source scheduler (Phase 7) is preserved unchanged: per-source
in-process locks, failure isolation (one source's failure never blocks another),
no concurrent duplication, safe SQLite locking, and no network calls held
inside DB write transactions. Scheduled collection remains off by default for
dev/testing (`SOURCE_SCHEDULER_ENABLED=false` in `.env.example`).

No auth, rate limiting, CORS, security headers, or SSRF protection was
weakened. No secrets appear in reports or screenshots.

---

## 2. Scheduler (`backend/app/services/sources/scheduler.py`)

| Property | Implementation |
|----------|----------------|
| Per-source lock | In-process lock per source; a source is never collected concurrently (manual vs scheduled) |
| Failure isolation | Independent sources fail/recover on their own; one source error does not block others |
| No concurrent duplication | `run_source_sync` guards against duplicate simultaneous runs for the same source |
| Min interval | `MIN_INTERVAL_SECONDS = 300.0` (5 min) between runs per source |
| Due calculation | Based on `last_attempt_at`; sources never collected (`last_attempt_at IS NULL`) are due immediately |
| Safe SQLite locking | `runner.py` commits per batch; matching runner (`run_state_matching.py`) commits per batch of 200 — no long-lived write transaction |
| No network-in-transaction | DB write transactions are committed before/during result persistence; matching engine runs outside an open write transaction |

Scheduled collection is disabled by default for development/testing
(`SOURCE_SCHEDULER_ENABLED=false` in `backend/.env.example`) and is **not**
force-enabled during dev/testing.

---

## 3. Security posture (unchanged by Phase 8)

| Item | Status |
|------|--------|
| Auth | Preserved (`require_viewer` / `require_operator` / `require_admin` on state-wise APIs) |
| Rate limiting | Preserved (implemented in code) |
| CORS | Preserved (strict, template-configured) |
| Security headers | Preserved (implemented in code) |
| SSRF protection | Preserved (`SOURCE_ALLOWED_HOSTS` allowlist; empty = deny-by-default in current config) |
| Secrets | `frontend/.env` demo password removed; `backend/.env.example` created with placeholders only; no secrets in Phase 8 reports/screenshots |
| `Bid.source_id` FK | `ondelete="SET NULL"` — historical bids remain readable if a source row is removed |

---

## 4. Evidence

| File | Description |
|------|-------------|
| `backend/app/services/sources/scheduler.py` | Scheduler (unchanged from Phase 7) |
| `backend/app/services/sources/runner.py` | Per-source lock; sets `source_id`; commits per batch |
| `backend/scripts/run_state_matching.py` | Batch commit, no network-in-transaction |
| `backend/.env.example` | `SOURCE_SCHEDULER_ENABLED=false` |

---

## 5. Preservation statement

- Scheduler behavior unchanged; no new concurrent collection paths
- No security control weakened or removed
- No commits or pushes made

---

*End of Phase 8 Scheduler and Security Report*
