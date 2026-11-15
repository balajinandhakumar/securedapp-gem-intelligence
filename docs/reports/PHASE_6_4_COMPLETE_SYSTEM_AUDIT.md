# Phase 6.4 Complete System Audit — SecuredApp GeM Bid Intelligence Platform

**Repository:** `C:\Users\Balaji\Desktop\securedapp-gem-intelligence`  
**Database:** `backend/dev.db` (SQLite WAL, preserved — no reset, no truncation, no synthetic bids)  
**Alembic migration:** `0011_bid_source_id`  
**Backend:** `http://127.0.0.1:8000` | **Frontend:** `http://localhost:3001`  
**Date:** 2026-11-12  

---

## 1. Scope

This audit covers the full Phase 6.4 pipeline from procurement source ingestion through matching, analysis, and frontend display:

- GeM direct public collector + 33 state/UT e-Procurement source adapters
- Deterministic bid-to-product matching engine (no LLM/embedding changes)
- Batch intelligence pipeline (matching → analysis → opportunity → notifications)
- Backend REST API (`/api/v1/bids`, `/api/v1/products`, `/api/v1/dashboard`, `/api/v1/all-india`, `/api/v1/health`, etc.)
- Frontend React application (bids feed, bid detail drawer, All India matches, state-wise bids, products, dashboard)

---

## 2. Database Baseline Counts (as of audit date)

| Table | Count | Notes |
|-------|-------|-------|
| `bids` | 44,842 | GeM=41,766; state/UT≈3,076; 2 placeholder rows with `gem_bid_id=NULL` |
| `products` | 14 | All active; 3 are test products with zero keywords |
| `product_keywords` | 146 | All active |
| `product_capabilities` | 109 | — |
| `bid_product_matches` | 80 | 46 distinct matched bids |
| `bid_scores` | 44,834 | NO_MATCH=44,757; POSSIBLE_MATCH=58; MATCH=13; NEEDS_REVIEW=10 |
| `bid_analysis` | 49,289 | — |
| `data_sources` | 34 | 33 state/UT + GeM direct |
| `collection_runs` | 242 | 240 SUCCESS, 1 PARTIAL, 1 RUNNING |
| `source_runs` | 1,279 | 1,137 SUCCESS; 89 NO_RECORDS; 40 ERROR; 7 FAILED; 5 NEEDS_ATTENTION; 1 BUSY |
| `human_reviews` | 7 | — |
| `notifications` | 7 | — |

### Bids by source (top sources)

| Source | Bids |
|--------|------|
| GeM | 41,766 |
| Tamil Nadu e-Procurement | 311 |
| Kerala e-Procurement | 279 |
| Haryana e-Procurement | 277 |
| Maharashtra e-Procurement | 263 |
| Madhya Pradesh e-Procurement | 230 |
| Delhi e-Procurement | 168 |
| Punjab e-Procurement | 167 |
| Jammu & Kashmir e-Procurement | 161 |
| (remaining 23 state/UT sources) | ~1,160 combined |

### Bid status

- All 44,842 bids have `status = NEW`
- `matching_status`: PENDING=42,491 / COMPLETED=2,351 (despite scores being persisted for all bids)

---

## 3. Data Quality Defects (confirmed, not remediated)

### 3.1 Location field — NULL and garbage text

| Condition | Count |
|-----------|-------|
| `location IS NULL` | 44,711 (99.7%) |
| `location = ''` | 0 |
| `location` populated (non-null, non-empty) | 131 |
| Garbage text `"s at which the local value addition is made..."` | 119 |

The 119 garbage location values appear as a filter option in the All India view (e.g., `"s at which the local value addition is made along with their bid, failing which (5)"`). This is ingestion-side corruption, not a display bug.

### 3.2 Estimated value — mostly NULL

| Condition | Count |
|-----------|-------|
| `estimated_value IS NULL` | 44,705 (99.7%) |
| `estimated_value SET` | 137 |

### 3.3 Placeholder / synthetic rows (2 bids with `gem_bid_id = NULL`)

| ID | Title |
|----|-------|
| `7314efa7-...` | `DeFi Infrastructure Development` |
| `6f81bbda-...` | `Custom Bid for Services - PROVISION OF ARBORICULTURE FOR DEFI SINGLE OFFRS ACCN AT MIL STN UNDER G...` |

Both have `source_url = NULL`, `original_bid_url = NULL`, `gem_bid_id = NULL`. One matches `SecurePad` (MATCH), the other matches `SecurePad` (NEEDS_REVIEW). These appear to be pre-existing placeholder rows and were **not** created or modified during Phase 6.4.

### 3.4 Matching status inconsistency

2,351 bids have `matching_status = COMPLETED` but all 44,842 bids have `status = NEW`. Scores exist for 44,834 bids (44,757 NO_MATCH + 58 POSSIBLE_MATCH + 13 MATCH + 10 NEEDS_REVIEW), yet 42,491 bids remain `matching_status = PENDING`. This is a status persistence gap: scores are written but `matching_status` is not updated to COMPLETED for all scored bids.

---

## 4. Backend Health

- `GET /api/v1/health/` → `{"status": "ok", "database_connected": true, ...}` — OK
- `GET /api/v1/dashboard/summary` → Returns full metrics (total_bids=44,840, open=3,679, closed=41,161, analyzed=3,675, relevant=2, possible_match=15, needs_review=3, notifications=7) — OK
- `GET /api/v1/bids/intelligence` → Returns paginated bid rows with scores — OK
- `GET /api/v1/products/` → Returns 14 products with keywords and capabilities — OK
- `GET /api/v1/all-india/...` → Returns product-relevant bids — OK

---

## 5. Test Results

| Suite | Result |
|-------|--------|
| Backend matching/scope-anchor/P0-exclusion tests | 45 passed |
| Backend dashboard/source-adapter/stage2 tests | 149 passed |
| Frontend `tsc --noEmit` | Passes (no errors) |
| Frontend vitest | 54 passed (7 files) |
| Frontend Playwright E2E | 14 passed (all green) |

---

## 6. Preserved Phase 6.3 Fixes (verified intact)

- `db.commit()` every 50 records in `gem_direct_service.py`
- `busy_timeout` 60s → 10s in `database.py`
- Login `db.commit()` wrapped in `execute_with_retry`
- Login verified end-to-end (200 with tokens ~0.14s, 401 ~0.06s, 422 ~0.01s)

---

## 7. Uncommitted Changes

All changes remain uncommitted on `main` (53 modified files, 267 untracked). No credentials or secrets exposed.

---

## 8. Audit Conclusion

The system is operational end-to-end: ingestion, matching, analysis, dashboard, and frontend all function. Documented data quality defects (location NULL/garbage, estimated_value NULL, matching_status inconsistency) do not prevent core flows but limit data richness. No critical defects block a controlled pilot.
