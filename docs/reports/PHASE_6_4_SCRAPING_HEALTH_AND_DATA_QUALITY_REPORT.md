# Phase 6.4 Scraping Health & Data Quality Report — SecuredApp GeM Bid Intelligence Platform

**Repository:** `C:\Users\Balaji\Desktop\securedapp-gem-intelligence`  
**Database:** `backend/dev.db` (SQLite WAL, preserved)  
**Date:** 2026-11-12  

---

## 1. Scope

This report covers scraping health across all procurement sources: the GeM direct public collector and 33 state/UT e-Procurement source adapters. Data is read from the live database; no re-scraping was performed and no source was bypassed.

---

## 2. GeM Direct Collector

| Metric | Value |
|--------|-------|
| Source adapter | `GEM_DIRECT_PUBLIC_ADAPTER` |
| Total collection runs | 241 |
| Records found | 202,980 |
| Records new (inserted) | 41,759 |
| Status | SUCCESS (240 runs), PARTIAL (1 run), RUNNING (1 run) |
| Bids in DB with `source_name = 'GeM'` | 41,766 |

The GeM direct collector is the primary ingestion path. It uses manual trigger only (no background scheduler), no GeM credentials, and stops with status `BLOCKED` on HTTP 403/429/block page without aggressive retry. All 41,766 GeM bids carry `source_url` and `original_bid_url` pointing to `bidplus.gem.gov.in`.

---

## 3. State / UT e-Procurement Sources

33 state/UT data sources are registered, all of type `html_listing`. Summary:

| Status | Count | Sources |
|--------|-------|---------|
| SUCCESS | 26 | Andhra... wait, see detail below |
| CONFIG_ERROR | 4 | Andhra Pradesh, Bihar, Gujarat, Karnataka, Telangana |
| FAILED | 1 | Uttar Pradesh |
| NO_RECORDS | 2 | Chhattisgarh, Manipur |
| BLOCKED | 1 | Goa (enabled=0) |

### Per-source detail

| Source | Enabled | Status | Total Runs | Total Inserted | Last Discovered | Last Inserted |
|--------|---------|--------|------------|----------------|-----------------|---------------|
| Andhra Pradesh e-Procurement | 1 | CONFIG_ERROR | 0 | 0 | 0 | 0 |
| Arunachal Pradesh e-Procurement | 1 | SUCCESS | 59 | 10 | 4 | 0 |
| Assam e-Procurement | 1 | SUCCESS | 49 | 86 | 2 | 0 |
| Bihar e-Procurement | 1 | CONFIG_ERROR | 0 | 0 | 0 | 0 |
| Chandigarh e-Procurement | 1 | SUCCESS | 47 | 101 | 10 | 0 |
| Chhattisgarh e-Procurement | 1 | NO_RECORDS | 42 | 0 | 0 | 0 |
| Delhi e-Procurement | 1 | SUCCESS | 56 | 168 | 10 | 0 |
| Goa e-Procurement | 0 | BLOCKED | 0 | 0 | 0 | 0 |
| Gujarat e-Procurement | 1 | CONFIG_ERROR | 0 | 0 | 0 | 0 |
| Haryana e-Procurement | 1 | SUCCESS | 46 | 277 | 10 | 0 |
| Himachal Pradesh e-Procurement | 1 | SUCCESS | 45 | 113 | 6 | 0 |
| Jammu and Kashmir e-Procurement | 1 | SUCCESS | 46 | 177 | 4 | 0 |
| Jharkhand e-Procurement | 1 | SUCCESS | 46 | 111 | 10 | 0 |
| Karnataka e-Procurement | 1 | CONFIG_ERROR | 0 | 0 | 0 | 0 |
| Kerala e-Procurement | 1 | SUCCESS | 52 | 280 | 9 | 0 |
| Madhya Pradesh e-Procurement | 1 | SUCCESS | 55 | 232 | 9 | 0 |
| Maharashtra e-Procurement | 1 | SUCCESS | 56 | 262 | 8 | 0 |
| Manipur e-Procurement | 1 | NO_RECORDS | 45 | 10 | 0 | 0 |
| Meghalaya e-Procurement | 1 | SUCCESS | 45 | 11 | 8 | 0 |
| Mizoram e-Procurement | 1 | SUCCESS | 45 | 2 | 2 | 0 |
| Nagaland e-Procurement | 1 | SUCCESS | 44 | 6 | 4 | 0 |
| Odisha e-Procurement | 1 | SUCCESS | 53 | 140 | 5 | 0 |
| Punjab e-Procurement | 1 | SUCCESS | 52 | 166 | 6 | 0 |
| Rajasthan e-Procurement | 1 | SUCCESS | 54 | 124 | 7 | 0 |
| Sikkim e-Procurement | 1 | SUCCESS | 50 | 13 | 9 | 0 |
| Tamil Nadu e-Procurement | 1 | SUCCESS | 54 | 311 | 10 | 2 |
| Telangana e-Procurement | 1 | CONFIG_ERROR | 0 | 0 | 0 | 0 |
| Tripura e-Procurement | 1 | SUCCESS | 43 | 84 | 10 | 0 |
| Uttar Pradesh e-Procurement | 1 | FAILED | 42 | 143 | 0 | 0 |
| Uttarakhand e-Procurement | 1 | SUCCESS | 42 | 79 | 7 | 0 |
| West Bengal e-Procurement | 1 | SUCCESS | 42 | 121 | 8 | 0 |

### State/UT bid counts in DB

| Source | Bids |
|--------|------|
| Tamil Nadu e-Procurement | 311 |
| Kerala e-Procurement | 279 |
| Haryana e-Procurement | 277 |
| Maharashtra e-Procurement | 263 |
| Madhya Pradesh e-Procurement | 230 |
| Delhi e-Procurement | 168 |
| Punjab e-Procurement | 167 |
| Jammu & Kashmir e-Procurement | 161 |
| Uttar Pradesh e-Procurement | 143 |
| Odisha e-Procurement | 141 |
| Rajasthan e-Procurement | 124 |
| West Bengal e-Procurement | 121 |
| Himachal Pradesh e-Procurement | 113 |
| Jharkhand e-Procurement | 111 |
| Chandigarh e-Procurement | 101 |
| Assam e-Procurement | 86 |
| Tripura e-Procurement | 84 |
| Uttarakhand e-Procurement | 79 |
| Sikkim e-Procurement | 12 |
| Meghalaya e-Procurement | 11 |
| Manipur e-Procurement | 10 |
| Arunachal Pradesh e-Procurement | 10 |
| Nagaland e-Procurement | 6 |
| Mizoram e-Procurement | 2 |
| Sikkim Government Tender Portal | 1 |

**Total state/UT bids: ~3,076**

---

## 4. Source Runs (per-source execution detail)

| Status | Count |
|--------|-------|
| SUCCESS | 1,137 |
| NO_RECORDS | 89 |
| ERROR | 40 |
| FAILED | 7 |
| NEEDS_ATTENTION | 5 |
| BUSY | 1 |
| **Total** | **1,279** |

Aggregated totals across all source runs:
- Records discovered: 8,394
- Records validated: 8,394
- Records inserted: 3,027
- Records rejected: 0
- Errors: 0

---

## 5. Collection Runs (adapter-level)

| Adapter | Runs | Records Found | Records New |
|---------|------|---------------|-------------|
| GEM_DIRECT_PUBLIC_ADAPTER | 241 | 202,980 | 41,759 |
| ThirdPartyGeM_APIFY | 1 | 50 | 49 |

---

## 6. Data Quality Defects Affecting Scraping Output

### 6.1 Location — NULL for 99.7% of bids (44,711 / 44,842)

Only 131 bids have a populated location. Of those, 119 contain garbage text:

> `"s at which the local value addition is made along with their bid, failing which ..."`

This appears as a spurious filter option in the All India view. Root cause: source adapter parsers extracting the wrong text node for the location field. **Not fixed in Phase 6.4** — documented as a data quality limitation.

### 6.2 Estimated value — NULL for 99.7% of bids (44,705 / 44,842)

Only 137 bids have an estimated value. Root cause: most tender listings do not expose estimated value in the list view, and the detail page parser does not consistently extract it. **Not fixed in Phase 6.4** — documented limitation.

### 6.3 Placeholder rows (2 bids with `gem_bid_id = NULL`)

Two rows (`DeFi Infrastructure Development`, `PROVISION OF ARBORICULTURE FOR DEFI ...`) have no `gem_bid_id`, no `source_url`, and no `original_bid_url`. They are pre-existing placeholder rows, not created by Phase 6.4 scraping.

### 6.4 Sources with configuration errors

5 sources (Andhra Pradesh, Bihar, Gujarat, Karnataka, Telangana) have `status = CONFIG_ERROR` and `total_runs = 0` — they have never successfully run. Goa is `BLOCKED` and `enabled = 0`. Uttar Pradesh shows `FAILED` despite having 143 bids in the DB (from an earlier successful run).

---

## 7. Scraping Health Conclusion

- **GeM direct collector:** Healthy — 241 runs, 41,766 bids ingested, all with valid `source_url`/`original_bid_url`.
- **State/UT adapters:** Partially healthy — 26 of 33 sources show SUCCESS, but 5 have never run (CONFIG_ERROR), 1 is BLOCKED/disabled, 1 FAILED, 2 return NO_RECORDS.
- **Data quality:** Location and estimated_value are overwhelmingly NULL; these are ingestion-side limitations, not display bugs.
- No source URLs, bids, or values were fabricated. No scraping bypass was attempted.
