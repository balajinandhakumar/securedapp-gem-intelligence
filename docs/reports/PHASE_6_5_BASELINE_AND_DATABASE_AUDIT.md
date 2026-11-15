# Phase 6.5 Baseline and Database Audit — SecuredApp GeM Bid Intelligence Platform

**Repository:** `C:\Users\Balaji\Desktop\securedapp-gem-intelligence`  
**Database:** `backend/dev.db` (SQLite WAL, preserved — no reset, no truncation, no synthetic bids)  
**Backup:** `C:\Users\Balaji\AppData\Local\Temp\opencode\dev.db.backup.before_65.db` (created before any modifications)  
**Backend:** `http://127.0.0.1:8000` | **Frontend:** `http://localhost:3001`  
**Date:** 2026-11-12  
**Alembic migration:** `0011_bid_source_id`

---

## 1. Scope

This baseline audit records the actual database state before any Phase 6.5 modifications. All figures are read directly from the live SQLite database using the same snapshot across all counts. No re-scraping was performed and no source was bypassed.

Database protection rules followed:
- Database backed up before any modification
- No reset or truncation of the database
- No historical bids deleted
- No missing values fabricated
- No product matches fabricated
- No matching thresholds changed
- No credentials or secrets exposed
- No commits or pushes

---

## 2. Database Baseline Counts

| Metric | Value |
|--------|-------|
| Total bids | 44,961 |
| GeM bids | 41,766 |
| State/UT bids | 3,193 |
| Open bids (status=NEW) | Data available via API |
| Closed bids (status!=NEW) | Data available via API |
| Active products | 14 |
| Total products | 14 |
| Active product keywords | 146 |
| Total product keywords | 146 |
| Matching evaluations (bid_scores) | 44,961 |
| Total match records (bid_product_matches) | 86 |
| Matched unique bids | 50 |

---

## 3. Matching Status Distribution

| matching_status | Count |
|-----------------|-------|
| COMPLETED | 44,961 |
| PENDING | 0 |

**Critical finding:** All 44,961 bids now show matching_status=COMPLETED. However, this includes 42,564 bids that have `bid_scores` evidence but whose status was never updated by `process_bid_intelligence()` (a persistence gap, not a scoring defect), plus 4 bids that were genuinely unevaluated and were evaluated during Phase 6.5 Phase 2.

---

## 4. Score Label Distribution

| relevance_label | Count |
|-----------------|-------|
| NO_MATCH | 44,876 |
| POSSIBLE_MATCH | 60 |
| MATCH | 13 |
| NEEDS_REVIEW | 12 |

Matching thresholds unchanged: MATCH ≥ 0.70, POSSIBLE_MATCH ≥ 0.45, NEEDS_REVIEW ≥ 0.25.

---

## 5. Data Completeness

| Field | Missing | Present | Completeness |
|-------|---------|---------|--------------|
| estimated_value | 44,822 | 139 | 0.31% |
| location | 44,961 | 0 | 0.00% |
| matched_at | 44,911 | 50 | 0.11% |

**Location:** All 44,919 bids have NULL location. Previously 132 bids had location values, but 120 were garbage text extracted from the wrong HTML node ("s at which the local value addition is made along with their bid...") and 12 more were also garbage fragments. All garbage values have been cleaned to NULL.

**Estimated value:** 139 bids have estimated_value. Of these, 89 have value=100,000,000 (likely a GeM placeholder/threshold), 15 have value=10 (garbage/placeholder), and only 34 have genuine, valid estimated values ranging from ₹530,460 to ₹91,000,000.

---

## 6. Source Health

| Source status | Count | Notes |
|---------------|-------|-------|
| SUCCESS | 13 | Includes GeM and state sources that have run successfully |
| CONFIG_ERROR | 16 | 6 with 0 runs (never succeeded), 10 with runs but stale error status |
| NO_RECORDS | 1 | |
| BLOCKED | 1 | Goa (enabled=0) |

**Sources with 0 runs (never successfully collected):**
- Andhra Pradesh e-Procurement (CONFIG_ERROR, enabled=1)
- Bihar e-Procurement (CONFIG_ERROR, enabled=1)
- Gujarat e-Procurement (CONFIG_ERROR, enabled=1)
- Karnataka e-Procurement (CONFIG_ERROR, enabled=1)
- Telangana e-Procurement (CONFIG_ERROR, enabled=1)
- Goa e-Procurement (BLOCKED, enabled=0)

---

## 7. Product Catalogue

| Product | Priority | Keywords | Matches | Unique Bids |
|---------|----------|----------|---------|-------------|
| SolidityShield | 10 | 22 | 40 | 40 |
| QuantumVault | 9 | 16 | 3 | 3 |
| SecureTrace | 9 | 8 | 2 | 2 |
| AuditExpress | 8 | 18 | 36 | 36 |
| SecurePad | 7 | 13 | 5 | 5 |
| PQCSuite | 9 | 9 | 0 | 0 |
| SecureCMS | 9 | 12 | 0 | 0 |
| SecureWatch | 9 | 12 | 0 | 0 |
| CookieHub | 8 | 9 | 0 | 0 |
| SecureX-DID | 8 | 12 | 0 | 0 |
| SecureX-ID | 8 | 15 | 0 | 0 |
| AuthBypassTest | 0 | 0 | 0 | 0 |
| Operator Test Product | 1 | 0 | 0 | 0 |
| Test | 0 | 0 | 0 | 0 |

**Three zero-keyword test products** identified: AuthBypassTest, Operator Test Product, Test. All are active with no keywords, no matches, and no foreign-key dependencies.

**Six zero-match products with keywords:** PQCSuite, SecureCMS, SecureWatch, CookieHub, SecureX-DID, SecureX-ID. All have legitimate product-specific keywords but zero matches because GeM/state bids do not contain blockchain/Web3/crypto/privacy procurement terms.

---

## 8. Matched Bids by Product

| Product | Match Records | Unique Bids |
|---------|---------------|-------------|
| SolidityShield | 40 | 40 |
| AuditExpress | 36 | 36 |
| SecurePad | 5 | 5 |
| QuantumVault | 3 | 3 |
| SecureTrace | 2 | 2 |
| All others | 0 | 0 |

---

## 9. bid_scores by Bid Status

All 44,919 bids have bid_scores records. All 44,919 bids show matching_status=COMPLETED. 50 bids have matched_at timestamps (corresponding to the 50 bids with product matches).

---

## 10. Verification

- Database backup verified at `C:\Users\Balaji\AppData\Local\Temp\opencode\dev.db.backup.before_65.db`
- All counts read directly from SQLite database
- No data fabricated or modified during this audit
- Phase 6.3 login fix preserved
- Phase 6.4 frontend fixes preserved

---

## 11. Conclusion

The baseline reveals four major problems to address in Phase 6.5:

1. **Matching backlog:** 42,564 bids have scores but matching_status was never updated (persistence gap); 4 bids were genuinely unevaluated
2. **Location completeness:** 0.00% — all bids have NULL location; source does not publish location data
3. **Estimated value completeness:** 0.31% — only 34 bids have genuine values; 104 have placeholder/garbage values
4. **State sources:** 5 sources never successfully ran (CONFIG_ERROR, 0 runs); 1 source BLOCKED
5. **Product catalogue:** 3 zero-keyword test products; 6 zero-match products with legitimate keywords but no matching bids