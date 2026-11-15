# PHASE 6.1 — DATABASE RECONCILIATION

**Project:** SecuredApp GeM Bid Intelligence Platform  
**Database:** `backend/dev.db` (SQLite WAL, Alembic at `0011_bid_source_id`)  
**Date:** 2026-11-11  
**Reference time (UTC):** 2026-11-11T09:54:51  

---

## 1. Total Bids — Reconciled

| Source | Count |
|--------|-------|
| Database census (`SELECT COUNT(*) FROM bids`) | **44,511** |
| Dashboard API (`/api/v1/dashboard/summary` total_bids) | **44,511** |
| Difference | **0** ✅ |

**Root cause (Phase 6.0, now verified fixed):** `total_bids` previously applied a source filter that excluded 55 records. It now counts ALL bids. No records were modified, deleted, or fabricated to force agreement.

---

## 2. Open / Closed Split — Reconciled

`closing_date` is stored as **text with space separator** (`2026-11-11 10:00:00.000000`), not ISO T-format. Comparison must use the same space-separator format; ISO T-format (`...T09:54:51...+00:00`) misclassifies today's bids because in SQLite lexicographic ordering, space (ASCII 32) < `T` (ASCII 84).

| Criterion (space-separator format) | SQL count | API count | Match |
|------------------------------------|-----------|-----------|-------|
| `closing_date IS NULL` | 7 | included in open | — |
| `closing_date >= now` (future) | 3,362 | — | — |
| **OPEN total** (`NULL OR >= now`) | **3,369** | **3,369** | ✅ |
| `closing_date < now` (past) | **41,142** | **41,142** | ✅ |
| **Sum** | **44,511** | **44,511** | ✅ |

**Verification of the 241-record ambiguous range:** Bids with `closing_date` on 2026-11-11 (today) span 09:00–21:00. Using ISO T-format comparison, bids later in the day were incorrectly classified as closed. Using space-separator format (matching DB storage), they are correctly open.

---

## 3. GeM vs State Breakdown

| Source class | source_id | Count |
|--------------|-----------|-------|
| GeM (Direct GeM Public Collector) | NULL | 41,811 |
| State sources (non-null source_id) | 31 distinct IDs | 2,700 |
| **Total** | | **44,511** |

31 data sources are registered in `data_sources`; 41,811 bids came from the GeM direct collection (source_id NULL), 2,700 from state sources.

---

## 4. Scoring and Matching

| Table / metric | Count |
|----------------|-------|
| `bid_scores` rows | (correlated with `bids.matching_status` below) |
| `bid_product_matches` rows | 80 |
| Distinct bids with ≥1 match | 46 |

### Matching status distribution

| matching_status | Bid count | Has match records |
|-----------------|-----------|-------------------|
| COMPLETED | 2,351 | 2 have matches; 2,349 have 0 matches (legitimate) |
| PENDING | 42,160 | 44 have match records (documented inconsistency) |
| PROCESSING | 0 | — |
| FAILED | 0 | — |
| **Total** | **44,511** | — |

### Consistency detail

| Check | Count | Assessment |
|-------|-------|------------|
| COMPLETED bids with ≥1 match | 2 | Both state-source bids; correctly evaluated |
| COMPLETED bids with 0 matches | 2,349 | Legitimate — evaluated against catalogue, no product matched |
| PENDING bids with match records | 44 | **Inconsistency documented** — match rows written but status not advanced to COMPLETED; GeM bids only |
| Match records on COMPLETED bids | 3 | — |
| Match records on PENDING bids | 77 | Belong to the 44 inconsistent PENDING GeM bids |

### Remaining workload
- **42,160 bids** in PENDING status require matching evaluation against the 15-product catalogue.
- No bids stuck in PROCESSING or FAILED.

---

## 5. Original Bid URL Coverage

| Classification | Count | % |
|----------------|-------|----|
| Valid showbiddocument URL (GeM per-bid) | 41,759 | 93.8% |
| Other original URL (state/NIC portals) | 1,818 | 4.1% |
| Missing original_url | 934 | 2.1% |
| Invalid URL | 0 | 0.0% |
| **Total** | **44,511** | **100.0%** |

No missing URLs were fabricated. No invalid URLs exist. `showbiddocument/<id>` links are specific to individual bids, not portal homepages.

---

## 6. Methodology

- All counts derived from independent `sqlite3` queries against `backend/dev.db`.
- API counts obtained from live `GET /api/v1/dashboard/summary` (authenticated as `demo@securedapp.io`).
- Datetime comparison uses space-separator format matching DB storage, not ISO T-format.
- No `DELETE`, `TRUNCATE`, `UPDATE`, or `INSERT` on historical bid records.
- No commit/push performed; all changes uncommitted on `main`.
