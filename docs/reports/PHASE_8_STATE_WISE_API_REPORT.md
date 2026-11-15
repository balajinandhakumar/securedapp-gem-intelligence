# PHASE 8 — STATE-WISE API REPORT (8B)

**SecuredApp GeM Bid Intelligence Platform**
**Version:** 1.0 — Phase 8 (State/UT Scraper Pipeline)
**Date:** 2026-11-10
**Scope:** Backend APIs for state-wise collected/matched bids

---

## 1. Executive Summary

Phase 8B exposes the backend APIs needed for individual State/UT scraper
visibility: per-state collected and matched bid counts, collected/matched bid
lists with pagination/search/filter, collection history, scraper errors, and
last successful run per state. The state-wise listing now joins on the
authoritative `Bid.source_id == DataSource.id` (with `source_name` fallback for
bids collected before the `source_id` backfill) instead of the fragile
`Bid.source_name == DataSource.name` string join.

GeM bids are excluded from all state-wise views (GeM bids keep `source_id =
NULL`).

All changes uncommitted on `main`. Verified live on `backend:8002`.

---

## 2. APIs

### 2.1 GET /api/v1/bids/state-wise
Returns state-wise bids (excludes GeM). Each row includes state identity from
the data-source registry and all persisted product matches (one row per
matched product; a tender matching multiple products appears once per match,
never duplicated).

Query params: `state`, `source`, `search`, `product`, `match_status`,
`bid_status`, `page`, `page_size`, `include_no_match`.

- Default (`include_no_match=false`): only bids with at least one qualifying
  product match (Matched view).
- `include_no_match=true`: also surfaces NO_MATCH / not-yet-analyzed bids
  (Collected view) — zero-match states still show their collected bids.

Response shape: `{ total, page, page_size, total_pages, bids: [...] }`

### 2.2 GET /api/v1/bids/state-wise/summary (NEW)
Per-state summary: one row per configured data source with collected count,
matched count (distinct bids with ≥1 product match), match-record count,
source status, enabled flag, last success/attempt timestamps, last error, and
insert/run counters. Ordered by source name.

Response shape: `{ total_states, states: [ {...} ] }`

### 2.3 POST /api/v1/bids/state-wise/match-all
Batch-matches every eligible state-wise tender (PENDING / FAILED) against all
active products using the existing deterministic engine
(`match_bid_against_products`), persists `BidProductMatch` records, and
updates `matching_status` (PENDING → PROCESSING → COMPLETED/FAILED) with
`matched_at`. Supports retry of FAILED bids.

### 2.4 Related (existing, reused)
- `GET /api/v1/sources` — source statuses + config
- `GET /api/v1/sources/{id}` / source run history — collection history, last run
- `GET /api/v1/health`, `GET /api/v1/ready`

---

## 3. Join semantics (authoritative + backward compatible)

The query joins `DataSource` on
`or_(Bid.source_id == DataSource.id, Bid.source_name == DataSource.name)`:

- Newly collected bids carry `source_id` → joined authoritatively by `source_id`
  (J&K and Sikkim name variants no longer split).
- Legacy bids collected before the backfill (still `source_id = NULL`) match by
  `source_name` → no data loss, backward compatible.
- `~Bid.source_name.ilike('%gem%')` explicitly excludes GeM bids.

---

## 4. Live verification (backend:8002)

`GET /api/v1/bids/state-wise/summary` → 31 states returned. Sample:

| source_id | name | status | collected | matched | last_success |
|-----------|------|--------|-----------|---------|--------------|
| assam | Assam e-Procurement | SUCCESS | 78 | 1 | 2026-11-10T11:16:06 |
| punjab | Punjab e-Procurement | SUCCESS | 101 | 1 | … |
| jammu_kashmir | Jammu and Kashmir e-Procurement | SUCCESS | 130 | 0 | … |
| sikkim | Sikkim e-Procurement | SUCCESS | 13 | 0 | … |
| andhra_pradesh | Andhra Pradesh e-Procurement | CONFIG_ERROR | 0 | 0 | null |
| bihar | Bihar e-Procurement | CONFIG_ERROR | 0 | 0 | null |

`GET /api/v1/bids/state-wise?state=assam&include_no_match=true` → 78 collected bids.
`GET /api/v1/bids/state-wise?state=assam` (matched only) → 1 matched bid.

Evidence: `PHASE_8_EVIDENCE/api/summary.json`, `assam_collected.json`,
`assam_matched.json`, `punjab_matched.json`, `jammu_kashmir_collected.json`,
`sikkim_collected.json`, `andhra_zero.json`, `sources.json`.

---

## 5. Tests

`backend/tests/test_state_wise_attribution.py` (4 tests, using conftest
`db`/`client` fixtures, in-memory SQLite, no network):
- `test_state_wise_summary_counts` — J&K collected=2/matched=0, Assam collected=1/matched=1
- `test_state_wise_collected_includes_no_match` — Collected view includes no-match bids
- `test_state_wise_matched_only` — Matched view returns only bids with ≥1 match
- `test_state_wise_attribution_not_split_by_name_variant` — Both J&K name
  variants roll up to one state via `source_id`

Full backend suite: **770 passed, 0 failed**.

---

## 6. Preservation statement

- No existing API removed or changed in behavior for GeM / all-India views
- No database deletion/truncation
- No fabricated bids, matches, or counts
- No commits or pushes made

---

*End of Phase 8 State-Wise API Report*
