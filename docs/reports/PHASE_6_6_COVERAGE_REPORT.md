# Phase 6.6 Phase 2 — Evaluation Coverage Audit Report

**Repository:** `C:\Users\Balaji\Desktop\securedapp-gem-intelligence`  
**Database:** `backend/dev.db`  
**Audit script:** `audit_phase_6_6_coverage_v3.py`  
**Date:** 2026-11-13

---

## 1. Executive Summary

All 45,186 bids have complete evaluation evidence (bid_scores + bid_analysis for all 14 active products). Zero bids are PENDING or genuinely unevaluated. All matching_status values are COMPLETED with matched_at timestamps set. No duplicate bid_analysis rows remain.

---

## 2. Coverage Results

| Metric | Count | Percentage |
|--------|-------|------------|
| Total bids | 45,186 | 100.00% |
| Bids with bid_scores | 45,186 | 100.00% |
| Bids with bid_analysis | 45,186 | 100.00% |
| Bids with both score + analysis | 45,186 | 100.00% |
| Bids with bid_product_matches | 52 | 0.12% |
| Bids with incorrect matching_status | 0 | 0.00% |
| Genuinely pending bids | 0 | 0.00% |
| Bids with matched_at set | 45,186 | 100.00% |

### Matching-Status Distribution

| Status | Count |
|--------|-------|
| COMPLETED | 45,186 |
| PENDING | 0 |
| PROCESSING | 0 |
| FAILED | 0 |
| Other | 0 |

---

## 3. Root Cause and Fix

**Root cause:** `process_bid_intelligence()` in `batch_processor.py` never persisted `matching_status` or `matched_at` to the `bids` table. The function computed scores and stored them in `bid_scores`/`bid_product_matches` but left `bids.matching_status` at its default value.

**Fix applied (Phase 6.6 code fix):**
- Added PROCESSING concurrency guard: if `bid.matching_status == "PROCESSING"`, return early to prevent duplicate score/analysis rows from concurrent scheduler and manual runs
- Set `bid.matching_status = "PROCESSING"` at start of evaluation, committed immediately
- Set `bid.matching_status = "COMPLETED"` and `bid.matched_at` at end of evaluation, committed

**Database fix (fix_status_v3.py):**
- 225 PENDING bids with complete evidence → marked COMPLETED with matched_at
- 44,911 COMPLETED bids missing matched_at → matched_at populated

---

## 4. Duplicate bid_analysis Removal

| Metric | Before Fix | After Fix |
|--------|------------|-----------|
| Bids with duplicate bid_analysis rows | 2,275 | 0 |
| Extra bid_analysis rows | 4,443 | 0 |
| Total bid_analysis rows | 49,629 | 45,186 |
| Bids with bid_analysis | 45,186 | 45,186 |

**Fix applied (fix_duplicates.py):** Kept the latest `bid_analysis` per bid (by `analyzed_at DESC, id DESC`), deleted 4,443 duplicate rows.

---

## 5. Classification by Verifiable Evidence

| Classification | Count | Status |
|----------------|-------|--------|
| COMPLETED + complete evidence (correct) | 45,186 | ✅ |
| COMPLETED + missing evidence (incorrect) | 0 | ✅ |
| PENDING + complete evidence (persistence gap) | 0 | ✅ |
| PENDING + missing evidence (genuinely unevaluated) | 0 | ✅ |
| **Total** | **45,186** | |

**Sum check:** 45,186 + 0 + 0 + 0 = 45,186 ✅

---

## 6. Data Integrity Verification

| Rule | Status |
|------|--------|
| No fabricated bids | ✅ All 45,186 bids are real collected records |
| No fabricated match results | ✅ All scores from deterministic engine |
| No matching thresholds reduced | ✅ MATCH≥0.70, POSSIBLE≥0.45, REVIEW≥0.25 unchanged |
| No database reset/truncation | ✅ Backup verified |
| No historical data deletion | ✅ All bids preserved |
| Phase 6.3 login fix preserved | ✅ No auth code changes |
| No commits/pushes | ✅ All changes uncommitted |

---

## 7. Conclusion

Evaluation coverage is complete: 100% of bids have verifiable evidence (bid_scores + bid_analysis), all matching_status values are correct (COMPLETED), matched_at is set for all bids, and no duplicate analysis rows remain.
