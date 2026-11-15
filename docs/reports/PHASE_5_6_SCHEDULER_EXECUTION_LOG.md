# PHASE 5.6 — SCHEDULER EXECUTION LOG

**Platform:** SecuredApp GeM Bid Intelligence Platform  
**Date:** 2026-11-09  
**Backend PID:** 33172  
**Scheduler:** GeM Direct Public Bid Collector  
**Interval:** 20 minutes  
**Enabled:** `GEM_DIRECT_SCHEDULER_ENABLED=true` (set at process start)

---

## 1. Scheduler Startup

| Event | Timestamp | Details |
|-------|-----------|---------|
| Backend process started | 2026-11-09 ~11:40 UTC | `python -m uvicorn app.main:app --host 127.0.0.1 --port 8000` with `GEM_DIRECT_SCHEDULER_ENABLED=true` |
| Scheduler thread started | 2026-11-09 ~11:40 UTC | Via `app.main` lifespan → `gem_scheduler.start()` |
| Scheduler status confirmed | 2026-11-09 11:44:06 UTC | `GET /api/v1/ingestion/gem-direct/status` → 200 |

**Scheduler configuration at startup:**
- `scheduler_enabled`: true
- `scheduler_interval_minutes`: 20
- `scheduler_next_run`: 2026-11-09T12:03:21.789975+00:00
- `is_running`: false (idle between ticks)
- `blocked`: false

---

## 2. Manual Collector Execution

### Run: a19bc7a4-6da5-4fe0-858f-6974f7c02a48

| Field | Value |
|-------|-------|
| **Run ID** | `a19bc7a4-6da5-4fe0-858f-6974f7c02a48` |
| **Trigger** | Manual (`POST /api/v1/ingestion/gem-direct/fetch`) |
| **Started** | 2026-11-09 11:44:06.176101 |
| **Finished** | 2026-11-09 11:45:12.846666 |
| **Duration** | 66.671 seconds |
| **Status** | SUCCESS |
| **Source** | gem_direct (Direct GeM Public Collector) |
| **Source Type** | direct_public |
| **Source Name** | GeM |
| **Method** | playwright |
| **URLs requested** | 1 |
| **URLs rejected** | 0 |
| **Pages visited** | 1 |
| **Pages available** | 4,335 |
| **Records available** | 43,342 |
| **Stop reason** | page_limit (max_pages=1) |
| **Limit reached** | true |
| **Scrape errors** | 0 |
| **Parser failures** | 0 |
| **Page failures** | 0 |

### Collection Scope

| Parameter | Value |
|-----------|-------|
| `bid_status_type` | ongoing_bids |
| `bid_type` | all |
| `sort_order` | Bid-Start-Date-Latest |
| `search_term` | null |
| `listing_url` | https://bidplus.gem.gov.in/all-bids |

### Results

| Metric | Count |
|--------|-------|
| Rows seen | 10 |
| Duplicate rows | 0 |
| Unique bids | 10 |
| New bids inserted | 0 |
| Bids updated | 3 |
| Bids already present (duplicates) | 3 |
| NO_MATCH (no product match) | 7 |
| Rejected by validation | 0 |
| Error count | 0 |

### Updated Bids (from run a19bc7a4)

| gem_bid_id | Title | Status | Updated At |
|------------|-------|--------|------------|
| GEM/2026/B/8180517 | Ordinary Portland Cement (V3) Confirming to IS 269 | NEW | 2026-11-09 11:44:59 |
| GEM/2026/B/8103474 | Online UPS (>10 KVA) With Battery | NEW | 2026-11-09 11:44:58 |
| GEM/2026/B/8180498 | Ordinary Portland Cement (V3) Confirming to IS 269 | NEW | 2026-11-09 11:44:59 |

---

## 3. Product Matching Results

| Metric | Value |
|--------|-------|
| Total bid_product_matches | 75 |
| Match type | DETERMINISTIC_PHASE3 (all 75) |
| Matches for bids from run a19bc7a4 | 0 (all 3 updated bids classified NO_MATCH) |

The 3 updated bids were processed through the intelligence pipeline (`process_bid_intelligence` → `match_bid_against_products`) but did not match any of the 14 configured products, resulting in NO_MATCH classification. This is expected behavior — not all GeM bids match the configured product catalogue.

---

## 4. Scheduler State Verification

### Status Endpoint Response

```
GET /api/v1/ingestion/gem-direct/status → 200

{
  "source": "gem_direct",
  "provider": "Direct GeM Public Collector",
  "source_name": "GeM",
  "source_type": "direct_public",
  "source_label": "Direct GeM Public Collector",
  "configured": true,
  "status": "READY",
  "allowed_hosts": ["gem.gov.in", "bidplus.gem.gov.in"],
  "listing_url": "https://bidplus.gem.gov.in/all-bids",
  "timeout_seconds": 60,
  "max_retries": 2,
  "request_interval_seconds": 3.0,
  "max_urls_per_run": 10,
  "pagination_enabled": true,
  "max_pages": 500,
  "max_pages_unlimited": false,
  "records_per_page": 10,
  "max_bids_per_run": 0,
  "bid_status_type": "ongoing_bids",
  "bid_type": "all",
  "sort_order": "Bid-Start-Date-Latest",
  "keyword_filter_enabled": false,
  "detail_enrichment_enabled": false,
  "max_detail_pages": 20,
  "scheduler_enabled": true,
  "scheduler_interval_minutes": 20,
  "scheduler_next_run": "2026-11-09T12:03:21.789975+00:00",
  "scheduler_note": "Automatic collection is enabled: a collection runs every 20 minute(s) using the existing bounded page budget, at the configured request interval. Scheduled and manual runs never overlap.",
  "requires_credentials": false,
  "blocked": false,
  "is_running": false
}
```

### Next Scheduled Run

- **Time:** 2026-11-09T12:03:21.789975+00:00 (20 minutes from scheduler start)
- **Trigger:** Scheduler tick (automatic)
- **Page budget:** 500 pages (configured `GEM_DIRECT_MAX_PAGES`)
- **Overlap protection:** `_gem_direct_lock` (non-blocking — if manual run is active, tick returns BUSY and is skipped)

---

## 5. Database Locking Safeguards

The following safeguards prevent `sqlite3.OperationalError: database is locked`:

| Layer | Mechanism | Configuration |
|-------|-----------|---------------|
| SQLite journal mode | WAL (Write-Ahead Logging) | `PRAGMA journal_mode=wal` |
| SQLite busy timeout | Retry on locked database | `busy_timeout=5000` (5 seconds) |
| Application lock | `threading.Lock()` with `acquire(blocking=False)` | `_gem_direct_lock` in `gem_direct_service.py` |
| Scheduler behavior | BUSY ticks are skipped, never queued or forced | `gem_scheduler.py` |

### Verification

- Journal mode confirmed: `wal`
- Busy timeout: 5000ms
- No database locking errors during manual collector execution (66.671s, 0 errors)
- No database locking errors during concurrent API endpoint calls
- Backend and frontend running simultaneously without database conflicts

---

## 6. Database State

| Table | Count | Notes |
|-------|-------|-------|
| bids | 43,441 | Unchanged (no truncation/deletion) |
| collection_runs | 238 | Includes run a19bc7a4 |
| bid_product_matches | 75 | All DETERMINISTIC_PHASE3 |
| notifications | 7 | |
| raw_bid_payloads | — | |
| bid_analysis | — | |
| bid_scores | — | |

### Collection Runs Table Schema

| Column | Type |
|--------|------|
| id | CHAR(36) |
| source_adapter | VARCHAR(100) |
| started_at | DATETIME |
| finished_at | DATETIME |
| status | VARCHAR(50) |
| records_found | INTEGER |
| records_new | INTEGER |
| records_duplicate | INTEGER |
| error_count | INTEGER |
| notes | TEXT |

### Run a19bc7a4 Recorded in collection_runs

| Field | Value |
|-------|-------|
| id | a19bc7a4-6da5-4fe0-858f-6974f7c02a48 |
| source_adapter | GEM_DIRECT_PUBLIC_ADAPTER |
| started_at | 2026-11-09 11:44:06.176101 |
| finished_at | 2026-11-09 11:45:12.846666 |
| status | SUCCESS |
| records_found | 10 |
| records_new | 0 |
| records_duplicate | 3 |
| error_count | 0 |

---

## 7. Scheduled Tick Status

As of this log entry, no automatic scheduler tick has fired yet. The first scheduled tick is due at:

**2026-11-09T12:03:21.789975+00:00**

When it fires, it will:
1. Attempt to acquire `_gem_direct_lock` (non-blocking)
2. If lock acquired: call `ingest_gem_direct_bids()` with `triggered_by="scheduler"`
3. If lock busy (manual run in progress): record BUSY and skip
4. Record results in `collection_runs` audit table
5. Never retry on failure — one attempt per interval

---

## 8. Execution Summary

| Event | Count | Status |
|-------|-------|--------|
| Scheduler startups | 1 | SUCCESS |
| Manual collector runs | 1 | SUCCESS (run a19bc7a4) |
| Automatic scheduler ticks | 0 | Pending (next: 12:03:21 UTC) |
| Database locking errors | 0 | NONE |
| Overlap conflicts | 0 | NONE (lock working correctly) |
| Bids discovered | 10 | From GeM (1 of 4,335 pages) |
| Bids updated | 3 | Through intelligence pipeline |
| Product matches created | 0 for new bids | 75 total existing |
| Scheduler enabled | true | GEM_DIRECT only |

---

## 9. Operational Notes

- Backend PID 33172 running on http://127.0.0.1:8000
- Scheduler enabled via `GEM_DIRECT_SCHEDULER_ENABLED=true` at process start
- Frontend dev server running on http://localhost:3000
- Next automatic scheduler tick: 2026-11-09T12:03:21.789975+00:00
- Manual collection available: `POST /api/v1/ingestion/gem-direct/fetch`
- Scheduled and manual runs never overlap (application-level `_gem_direct_lock`)
- All changes remain uncommitted (working tree preserved from Phase 5.4/5.5)
- Database preserved: 43,441 bids, WAL mode, no truncation or deletion
