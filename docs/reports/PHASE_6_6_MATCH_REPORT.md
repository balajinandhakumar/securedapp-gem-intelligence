# Phase 6.6 Phase 3 — Match Records Verification Report

**Repository:** `C:\Users\Balaji\Desktop\securedapp-gem-intelligence`  
**Database:** `backend/dev.db`  
**Verification script:** `verify_scores.py`  
**Corrections file:** `score_corrections.json`  
**Date:** 2026-11-13

---

## 1. Executive Summary

All 89 match records (bid_product_matches) are structurally valid. 35 stored scores were corrected to match the current deterministic matching engine output (SolidityShield scores were overstated due to missing domain/context gates). After correction, all 89 scores verify against engine output. 52 unique bids have at least one match.

---

## 2. Match Records Overview

| Metric | Value |
|--------|-------|
| Total match records | 89 |
| Unique matched bids | 52 |
| Bids with multiple product matches | 37 (89 - 52 = 37 additional matches) |
| Match records with corrected scores | 35 |
| Match records verified after correction | 89 (100%) |

---

## 3. Score Distribution (Post-Correction)

| Score | Count |
|-------|-------|
| 1.0 (MATCH) | 6 |
| 0.625 (MATCH) | 3 |
| 0.5 (POSSIBLE_MATCH) | 29 |
| 0.3999 (NEEDS_REVIEW) | 49 |
| 0.0 (NO_MATCH) | 2 |
| **Total** | **89** |

---

## 4. Score Label Distribution (from bid_scores)

| Label | Count |
|-------|-------|
| NO_MATCH | 45,099 |
| POSSIBLE_MATCH | 61 |
| NEEDS_REVIEW | 13 |
| MATCH | 13 |
| **Total** | **45,186** |

---

## 5. Score Corrections Applied

35 match records had stored scores that disagreed with the current matching engine. All were overstated (SolidityShield domain/context gate not applied at time of original scoring). Corrections:

| Match ID (prefix) | Old Score | New Score | New State |
|-------------------|-----------|-----------|-----------|
| a823af47... | 1.0 | 0.3999 | NEEDS_REVIEW |
| cff9c59c... | 1.0 | 0.3999 | NEEDS_REVIEW |
| 0221b2bc... | 1.0 | 0.3999 | NEEDS_REVIEW |
| 032916d8... | 1.0 | 0.3999 | NEEDS_REVIEW |
| 7cd1334d... | 0.625 | 0.3999 | NEEDS_REVIEW |
| f4edb6e8... | 0.625 | 0.3999 | NEEDS_REVIEW |
| 18cf37eb... | 0.625 | 0.3999 | NEEDS_REVIEW |
| 1ea05299... | 0.625 | 0.3999 | NEEDS_REVIEW |
| 0007920c... | 0.5 | 0.3999 | NEEDS_REVIEW |
| 4d8c76b6... | 0.5 | 0.3999 | NEEDS_REVIEW |
| cf5105cd... | 0.5 | 0.3999 | NEEDS_REVIEW |
| d8c6bfca... | 0.5 | 0.3999 | NEEDS_REVIEW |
| 6e238bcb... | 0.5 | 0.3999 | NEEDS_REVIEW |
| 629dc8af... | 0.5 | 0.3999 | NEEDS_REVIEW |
| 3ec11d12... | 0.5 | 0.3999 | NEEDS_REVIEW |
| 12936e53... | 0.5 | 0.3999 | NEEDS_REVIEW |
| 0c68318a... | 0.5 | 0.3999 | NEEDS_REVIEW |
| 56186906... | 0.5 | 0.3999 | NEEDS_REVIEW |
| 24a3ec52... | 0.5 | 0.3999 | NEEDS_REVIEW |
| bc634c11... | 0.5 | 0.3999 | NEEDS_REVIEW |
| b70bc60e... | 0.5 | 0.3999 | NEEDS_REVIEW |
| a0ecfe01... | 0.5 | 0.3999 | NEEDS_REVIEW |
| 034d828b... | 0.5 | 0.3999 | NEEDS_REVIEW |
| 0938361e... | 0.5 | 0.3999 | NEEDS_REVIEW |
| 4608cb04... | 0.5 | 0.3999 | NEEDS_REVIEW |
| 63c59bf8... | 0.5 | 0.3999 | NEEDS_REVIEW |
| 5d10b1d1... | 0.5 | 0.3999 | NEEDS_REVIEW |
| (6 more) | 0.5 | 0.3999 | NEEDS_REVIEW |

All 35 corrections reduced scores from 1.0/0.625/0.5 to 0.3999 (NEEDS_REVIEW), reflecting correct application of domain/context gates.

---

## 6. Root Cause

Stored scores were computed before domain/context gates were added to the matching engine. SolidityShield (smart contract security product) was matching bids that should have been gated down to NEEDS_REVIEW because the domain/context validation was not applied at score persistence time.

---

## 7. Verification After Fix

Re-ran `verify_scores.py`:
- Checked: 89 match records
- Mismatches: 0
- All scores match: **True**
- Corrections file regenerated: 0 entries (all corrected)

---

## 8. Data Integrity Verification

| Rule | Status |
|------|--------|
| No fabricated match results | ✅ All 89 records from deterministic engine |
| No matching thresholds reduced | ✅ MATCH≥0.70, POSSIBLE≥0.45, REVIEW≥0.25 unchanged |
| No scores artificially inflated | ✅ 35 overstated scores corrected downward |
| Original scores preserved in evidence | ✅ `original_score` field in evidence JSON |
| Correction reason documented | ✅ `correction_reason` field in evidence JSON |
| No commits/pushes | ✅ All changes uncommitted |

---

## 9. Conclusion

All 89 match records verified against the deterministic matching engine. 35 overstated scores corrected. All scores now match current engine output. Match data is trustworthy for supplier demonstration.
