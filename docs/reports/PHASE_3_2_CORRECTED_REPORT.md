# Phase 3.2 — Corrected Production Matching Audit Report

## Executive Summary

This report corrects four discrepancies identified in the Phase 3.1 production audit:

1. **matches_persisted=0 is correct** — The counter counts new qualifying matches from the current batch run only. None of the 12 reprocessed bids produced qualifying matches; the 2 existing BidProductMatch records belong to bid `1003c57a` (Punjab), which was NOT among the 12 reprocessed bids.

2. **Karnataka IS configured** — Karnataka e-Procurement exists in the DataSource table (31 total sources), enabled=True, status=CONFIG_ERROR, bids=0. It is NOT in the adapter registry (no `KarnatakaTenderAdapter`). The Phase 3.1 report incorrectly stated Karnataka is "not among the 22 configured state sources."

3. **There are 31 configured sources, not 22** — 22 sources have bids > 0; 9 sources have bids = 0.

4. **No matching-quality defects found** — All 629 NO_MATCH tenders are correctly classified; the 8 security-terminology NO_MATCH tenders are physical security/CCTV/IT-infrastructure tenders that do not match cybersecurity products.

---

## 1. Zero Persistence Counter Investigation

### The 12 Reprocessed Bid IDs

All 12 bids were reset from COMPLETED → PENDING, then reprocessed via `POST /api/v1/bids/state-wise/match-all`:

| # | Bid ID (prefix) | State | matches_before | matches_after |
|---|-----------------|-------|---------------|---------------|
| 1 | 862dc5bc | Punjab e-Procurement | 0 | 0 |
| 2 | a2c88f10 | Punjab e-Procurement | 0 | 0 |
| 3 | 5ac630b9 | Maharashtra e-Procurement | 0 | 0 |
| 4 | 54b73b7d | Maharashtra e-Procurement | 0 | 0 |
| 5 | 097793cd | Tamil Nadu e-Procurement | 0 | 0 |
| 6 | 1f745352 | Tamil Nadu e-Procurement | 0 | 0 |
| 7 | 261b0f3e | Kerala e-Procurement | 0 | 0 |
| 8 | 0212f367 | Kerala e-Procurement | 0 | 0 |
| 9 | f470b630 | Delhi e-Procurement | 0 | 0 |
| 10 | e90061e3 | Delhi e-Procurement | 0 | 0 |
| 11 | 5588d148 | Mizoram e-Procurement | 0 | 0 |
| 12 | 9b31412a | Mizoram e-Procurement | 0 | 0 |

### The Only State Bid With Matches (NOT Reprocessed)

| Bid ID | State | Product | Score | Classification |
|--------|-------|---------|-------|----------------|
| 1003c57a | Punjab e-Procurement | SolidityShield | 0.5000 | POSSIBLE_MATCH |
| 1003c57a | Punjab e-Procurement | AuditExpress | 0.5000 | POSSIBLE_MATCH |

Bid `1003c57a` ("7. Tender for hiring Consultancy for Maintenance of the existing Infor...") was processed during the original run (matched_at: 2026-11-05 12:10:26.693674) and was NOT among the 12 reprocessed bids. It retained its 2 BidProductMatch records.

### Counter Implementation

**File:** `backend/app/api/v1/endpoints/bids.py`, lines 420, 446-463, 490

```python
matches_persisted = 0   # Line 420
...
for res in match_results:
    if not _candidate_has_confirmed_interest(res):
        continue        # Line 447 — skip non-qualifying matches
    db.add(BidProductMatch(...))   # Line 448-461
    matches_persisted += 1         # Line 463 — only incremented on persistence
...
"matches_persisted": matches_persisted   # Line 490
```

**Persistence threshold** (`_candidate_has_confirmed_interest`, line 396-399):
```python
def _candidate_has_confirmed_interest(res) -> bool:
    if res.match_state not in _PERSISTABLE_STATES or res.relevance_score < 0.25:
        return False
    return any(s.get("strength") != "EXCLUSION" for s in res.signals)
```

A match is persisted only if:
- `match_state` is in `{MATCH, POSSIBLE_MATCH, NEEDS_REVIEW}`
- `relevance_score >= 0.25`
- At least one signal has strength other than "EXCLUSION"

### Delete-Then-Reinsert Pattern

Line 442:
```python
db.query(BidProductMatch).filter(BidProductMatch.bid_id == bid.id).delete()
```

This deletes ALL existing BidProductMatch rows for a bid before reinserting new ones. No duplicates can be created during reprocessing.

### Why matches_persisted=0

1. **None of the 12 reprocessed bids produced qualifying matches.** All 12 are civil works/construction tenders (pond fabrication, drainage, road repair, borewell, transformer installation) that score below the 0.25 threshold for all 11 cybersecurity products.

2. **The counter counts new matches from THIS run only.** The 2 existing records belong to bid `1003c57a`, which was processed in the original run, not the reprocessing run.

3. **`matches_persisted=0` is correct behavior**, not a bug. The API documented it as "persisted N product-match record(s)" meaning N new rows added in this invocation.

---

## 2. Correct Comparison Accounting

All figures verified against actual database records:

| Metric | Value | Source |
|--------|-------|--------|
| Unique tenders evaluated | 630 | State-source bids joined with DataSource |
| Unique products per tender | 11 | Active Product records |
| Unique tender-product pairs per full run | 6,930 | 630 × 11 |
| Total evaluation executions (original run) | 6,930 | One full pass over all 630 bids |
| Repeat evaluations (reprocessing run) | 132 | 12 bids × 11 products |
| Grand total tender-product comparisons | 7,062 | 6,930 + 132 |
| Persisted product-match rows (state bids) | 2 | BidProductMatch table |
| Bids with at least 1 match | 1 | Punjab bid 1003c57a |
| Bids with 0 matches (NO_MATCH) | 629 | All other state bids |

### Timestamps
- Original processing matched_at range: 2026-11-05 12:10:20 – 12:11:24
- Reprocessing matched_at range: 2026-11-05 12:16:30 – 12:16:33
- All 630 bids verified to have BidAnalysis records with exactly 11 `product_matches` entries each

---

## 3. Karnataka Source Configuration

### DataSource Table (31 total sources)

| # | Source ID | Name | Adapter | Enabled | Status | Bids |
|---|-----------|------|---------|---------|--------|------|
| 1 | andhra_pradesh | Andhra Pradesh e-Procurement | html_listing | Yes | CONFIG_ERROR | 0 |
| 2 | arunachal_pradesh | Arunachal Pradesh e-Procurement | arunachal_pradesh | Yes | SUCCESS | 8 |
| 3 | assam | Assam e-Procurement | assam | Yes | SUCCESS | 15 |
| 4 | bihar | Bihar e-Procurement | html_listing | Yes | CONFIG_ERROR | 0 |
| 5 | chandigarh | Chandigarh e-Procurement | chandigarh | Yes | SUCCESS | 20 |
| 6 | chhattisgarh | Chhattisgarh e-Procurement | chhattisgarh | Yes | NO_RECORDS | 0 |
| 7 | delhi | Delhi e-Procurement | delhi | Yes | SUCCESS | 35 |
| 8 | goa | Goa e-Procurement | html_listing | **No** | BLOCKED | 0 |
| 9 | gujarat | Gujarat e-Procurement | html_listing | Yes | CONFIG_ERROR | 0 |
| 10 | haryana | Haryana e-Procurement | haryana | Yes | SUCCESS | 30 |
| 11 | himachal_pradesh | Himachal Pradesh e-Procurement | himachal_pradesh | Yes | SUCCESS | 13 |
| 12 | jammu_kashmir | Jammu and Kashmir e-Procurement | jammu_kashmir | Yes | SUCCESS | 0 |
| 13 | jharkhand | Jharkhand e-Procurement | jharkhand | Yes | SUCCESS | 13 |
| 14 | **karnataka** | **Karnataka e-Procurement** | **html_listing** | **Yes** | **CONFIG_ERROR** | **0** |
| 15 | kerala | Kerala e-Procurement | kerala | Yes | SUCCESS | 47 |
| 16 | madhya_pradesh | Madhya Pradesh e-Procurement | madhya_pradesh | Yes | SUCCESS | 66 |
| 17 | maharashtra | Maharashtra e-Procurement | maharashtra | Yes | SUCCESS | 104 |
| 18 | manipur | Manipur e-Procurement | manipur | Yes | NO_RECORDS | 10 |
| 19 | meghalaya | Meghalaya e-Procurement | meghalaya | Yes | SUCCESS | 9 |
| 20 | mizoram | Mizoram e-Procurement | mizoram | Yes | SUCCESS | 2 |
| 21 | nagaland | Nagaland e-Procurement | nagaland | Yes | SUCCESS | 5 |
| 22 | odisha | Odisha e-Procurement | odisha | Yes | SUCCESS | 37 |
| 23 | punjab | Punjab e-Procurement | punjab | Yes | SUCCESS | 30 |
| 24 | rajasthan | Rajasthan e-Procurement | rajasthan | Yes | SUCCESS | 36 |
| 25 | sikkim | Sikkim e-Procurement | sikkim | Yes | SUCCESS | 0 |
| 26 | tamil_nadu | Tamil Nadu e-Procurement | tamil_nadu | Yes | SUCCESS | 85 |
| 27 | telangana | Telangana e-Procurement | html_listing | Yes | CONFIG_ERROR | 0 |
| 28 | tripura | Tripura e-Procurement | tripura | Yes | SUCCESS | 17 |
| 29 | uttar_pradesh | Uttar Pradesh e-Procurement | uttar_pradesh | Yes | SUCCESS | 18 |
| 30 | uttarakhand | Uttarakhand e-Procurement | uttarakhand | Yes | SUCCESS | 16 |
| 31 | west_bengal | West Bengal e-Procurement | west_bengal | Yes | SUCCESS | 14 |

### Summary Counts

| Category | Count |
|----------|-------|
| Total configured sources | 31 |
| Enabled sources | 30 |
| Disabled/blocked sources | 1 (Goa) |
| Sources with bids > 0 | 22 |
| Sources with bids = 0 | 9 |
| Successfully tested (SUCCESS + bids > 0) | 22 |
| CONFIG_ERROR (enabled but no working adapter) | 6 (Andhra Pradesh, Bihar, Gujarat, Karnataka, Telangana + Goa disabled) |
| NO_RECORDS | 2 (Chhattisgarh, Manipur) |

### Adapter Registry Check

**File:** `backend/app/services/sources/adapters.py`, lines 6266-6300

The `all_adapters()` function registers 26 adapters. **KarnatakaTenderAdapter is NOT registered.** The `html_listing` adapter is used as a fallback for Andhra Pradesh, Bihar, Goa, Gujarat, Karnataka, and Telangana, but none of these have a dedicated state-specific adapter.

### Why the Discrepancy

The Phase 3.1 report stated "Karnataka e-Procurement is NOT among the 22 configured state sources." This was **incorrect**. Karnataka IS in the DataSource table:
- `source_id=karnataka`
- `name=Karnataka e-Procurement`
- `enabled=True`
- `status=CONFIG_ERROR`
- `bids=0`

The confusion arises because:
1. There are **31** configured sources in DataSource, not 22.
2. **22** sources have bids > 0 (Karnataka has 0 bids).
3. Karnataka is **not in the adapter registry** (no `KarnatakaTenderAdapter` class), so even though it's enabled in DataSource, it cannot be crawled — hence `status=CONFIG_ERROR`.

No source was deleted or disabled during this investigation.

---

## 4. Matching Quality Audit

### All Currently Matched State Tenders (1 total)

| Bid ID | State | Title | Product | Score | Classification | Evidence |
|--------|-------|-------|---------|-------|----------------|----------|
| 1003c57a | Punjab e-Procurement | "7. Tender for hiring Consultancy for Maintenance of the existing Infor..." | SolidityShield | 0.5000 | POSSIBLE_MATCH | match_state=POSSIBLE_MATCH |
| 1003c57a | Punjab e-Procurement | "7. Tender for hiring Consultancy for Maintenance of the existing Infor..." | AuditExpress | 0.5000 | POSSIBLE_MATCH | match_state=POSSIBLE_MATCH |

### NO_MATCH Tenders with Security-Related Terminology (8 total)

| Bid ID | State | Title | Keywords Found | Correctly NO_MATCH? | Reason |
|--------|-------|-------|----------------|---------------------|--------|
| 5911c53e | Rajasthan | "5. Work of Garden Maintenance, Cleaning of Complete Premises and Provi..." | security | Yes | Physical security/cleaning, not cybersecurity product |
| 2c290b94 | Maharashtra | "6. prepare an estimate for the work of providing and installing CCTV c..." | security | Yes | CCTV installation (physical security), not software/cybersecurity |
| dff478bc | Delhi | "5. Maintenance and Operation of Street Light/High Mast at PWD Road und..." | monitoring | Yes | Street light maintenance, not IT/cybersecurity monitoring |
| 1b19e65a | Odisha | "5. Construction of 6 Nos. Of Recharge Shaft cum Monitoring Station in ..." | monitoring | Yes | Water recharge shaft monitoring, not cybersecurity |
| 50983f27 | Punjab | "9. Installation for Online Continuous Effluent Monitoring System (OCMS..." | monitoring | Yes | Effluent/water monitoring, not IT/cybersecurity |
| 5d32ddfb | Manipur | "7. Selection of Agency for Providing IT Infrastructure Operation and M..." | cyber | Yes | IT infrastructure operations management, not cybersecurity products |
| c2903db7 | West Bengal | "10. Internal Audit of the accounts of the WBTDCCL including its 8 Regi..." | audit | Yes | Financial/internal audit, not smart contract/cybersecurity audit |
| 07a5d2c7 | Delhi | "1. Providing and Fixing of Security Gate at different locations in R.K..." | security | Yes | Physical security gate installation, not cybersecurity |

### Matching Quality Findings

- **Total matched state tenders:** 1 (Punjab bid 1003c57a)
- **Total NO_MATCH state tenders:** 629
- **NO_MATCH tenders with security terminology:** 8
- **Incorrectly classified NO_MATCH tenders:** **0**

All 8 security-terminology NO_MATCH tenders are correctly classified. They involve physical security (CCTV, gates, street lights), water/effluent monitoring, IT infrastructure operations, and financial audit — none relate to the 11 cybersecurity products (smart contract security, privacy/compliance, blockchain forensics, cookie management, post-quantum cryptography, decentralized identity, blockchain security, automated smart contract audit, Web3 infrastructure, compliance/identity verification, key management/hardware security).

One tender can match multiple products: Punjab bid 1003c57a matches both SolidityShield and AuditExpress at 0.50 each (POSSIBLE_MATCH).

---

## 5. Remaining Defects

### Defect 1: Route Ordering — Already Fixed

`/catalogue-stats` was moved before `/{product_id}` in `backend/app/api/v1/endpoints/products.py`. Verified working — endpoint returns HTTP 200 with correct catalogue statistics.

### Defect 2: Karnataka Source — Configuration Gap

Karnataka e-Procurement is enabled in DataSource (status=CONFIG_ERROR) but has no dedicated adapter in `all_adapters()`. It cannot be crawled. This is a pre-existing configuration gap, not introduced by Phase 3. No code change was made.

### Defect 3: Data Quality in `location` Field

Some GeM bids have non-state text in the `location` column (e.g., "s at which the local value addition is made along with their bid, failing which"). This appears in `catalogue-stats` `matched_states` output. Pre-existing data quality issue.

### Defect 4: No Eligible Tend Remain

All 630 state bids are COMPLETED. New tenders collected from state sources will be PENDING and processed on the next batch match-all run.

---

## Corrected Database Counts Summary

| Metric | Value |
|--------|-------|
| Total bids in DB | 42,461 |
| State-source bids | 630 |
| GeM bids | 41,801 |
| Distinct state sources (with bids) | 22 |
| Total configured sources (DataSource table) | 31 |
| Active products | 11 |
| Total BidProductMatch records (state) | 2 |
| State bids with matches | 1 |
| State bids without matches | 629 |
| Unique tender-product pairs evaluated | 6,930 |
| Repeat evaluations (reprocessing) | 132 |
| Grand total comparisons | 7,062 |
| matches_persisted (reprocessing run) | 0 (correct) |
| Karnataka source status | CONFIG_ERROR, enabled, no adapter, 0 bids |
| Incorrectly classified NO_MATCH tenders | 0 |
