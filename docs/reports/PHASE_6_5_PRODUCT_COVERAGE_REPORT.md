# Phase 6.5 Product Coverage Report — SecuredApp GeM Bid Intelligence Platform

**Repository:** `C:\Users\Balaji\Desktop\securedapp-gem-intelligence`  
**Database:** `backend/dev.db` (SQLite WAL, preserved)  
**Date:** 2026-11-12  

---

## 1. Product Catalogue Overview

| Metric | Value |
|--------|-------|
| Total products | 14 |
| Active products | 14 |
| Total product keywords | 146 |
| Active product keywords | 146 |
| Total product capabilities | 109 |
| Total match records | 86 |
| Unique matched bids | 50 |

---

## 2. Product-by-Product Audit

| Product | Priority | Keywords | Matches | Unique Bids | Status |
|---------|----------|----------|---------|-------------|--------|
| SolidityShield | 10 | 22 | 40 | 40 | Active, matching |
| QuantumVault | 9 | 16 | 3 | 3 | Active, matching |
| SecureTrace | 9 | 8 | 2 | 2 | Active, matching |
| AuditExpress | 8 | 18 | 36 | 36 | Active, matching |
| SecurePad | 7 | 13 | 5 | 5 | Active, matching |
| PQCSuite | 9 | 9 | 0 | 0 | Active, zero matches |
| SecureCMS | 9 | 12 | 0 | 0 | Active, zero matches |
| SecureWatch | 9 | 12 | 0 | 0 | Active, zero matches |
| CookieHub | 8 | 9 | 0 | 0 | Active, zero matches |
| SecureX-DID | 8 | 12 | 0 | 0 | Active, zero matches |
| SecureX-ID | 8 | 15 | 0 | 0 | Active, zero matches |
| AuthBypassTest | 0 | 0 | 0 | 0 | Test product, zero keywords |
| Operator Test Product | 1 | 0 | 0 | 0 | Test product, zero keywords |
| Test | 0 | 0 | 0 | 0 | Test product, zero keywords |

---

## 3. Test Products (Zero Keywords)

Three products have zero keywords and zero matches. All have no foreign-key dependencies (no bid_product_matches, product_keywords, product_capabilities, product_categories, or product_technologies records).

| Product | Description | Priority | Dependencies | Recommendation |
|---------|-------------|----------|--------------|----------------|
| AuthBypassTest | "x" | 0 | None | Deactivate from supplier-facing catalogue |
| Operator Test Product | "Test product created by operator" | 1 | None | Deactivate from supplier-facing catalogue |
| Test | "N/A" | 0 | None | Deactivate from supplier-facing catalogue |

**Assessment:** These are clearly test artifacts — descriptions are "x", "N/A", and "Test product created by operator", priorities are 0 or 1 (lowest), and they have zero keywords. They appear in no match records.

**Action recommended:** Deactivate (set active=0) from the supplier-facing product catalogue. Preserve historical records — do not delete. No foreign-key dependencies exist, so deactivation is safe.

---

## 4. Zero-Match Products with Keywords (6 products)

Six products have legitimate, product-specific keywords but zero matches. This is a genuine coverage gap — not a bug in the matching engine.

### 4.1 Product Analysis

| Product | Keywords | Sample Keywords | Domain |
|---------|----------|-----------------|--------|
| PQCSuite | 9 | post quantum cryptography, pqc, quantum resistant, crypto agility | Post-quantum cryptography |
| SecureCMS | 12 | consent management, data consent, privacy compliance, cookie consent | Consent/privacy management |
| SecureWatch | 12 | blockchain monitoring, transaction monitoring, smart contract monitoring | Blockchain transaction monitoring |
| CookieHub | 9 | cookie consent, tracking scripts, website consent | Website cookie management |
| SecureX-DID | 12 | decentralized identity, did, verifiable credential, identity wallet | Decentralized identity |
| SecureX-ID | 15 | kyc, aml, identity verification, watchlist, fraud risk | KYC/AML compliance |

### 4.2 Root Cause of Zero Matches

GeM and state/UT procurement bids are for:
- IT hardware (laptops, printers, servers)
- Civil works and construction
- Vehicle supplies and maintenance
- Office supplies and stationery
- Food and catering services
- General government procurement

None of these bids contain blockchain/Web3/cryptocurrency/privacy-consent procurement terms. The matching engine is working correctly — these products genuinely have no matching bids in the current corpus.

**This is not a keyword problem.** The keywords are specific and appropriate for each product. Adding broad or irrelevant terms just to generate matches would violate the requirement: "Do not invent keywords or add broad irrelevant terms just to generate matches."

### 4.3 Matching Algorithm Verification

The matching engine correctly:
- Uses whole-word/whole-phrase matching with word boundaries
- Applies context gates to prevent false positives from ambiguous terms
- Uses scope gates and domain anchors per product
- Classifies scores using thresholds: MATCH ≥ 0.70, POSSIBLE_MATCH ≥ 0.45, NEEDS_REVIEW ≥ 0.25

No threshold changes were made. Zero matches are accurate results.

---

## 5. Matching Engine Accuracy Verification

For each match, the engine provides:
- Bid ID, product name, matched keywords, matching text evidence, matching method, relevance score, threshold, decision, evaluation timestamp

For unmatched bids, diagnostics are available:
- No relevant keywords in bid content
- Description missing or too short
- Below threshold (< 0.25)
- Product inactive (none — all 14 are active)
- Evaluation completed (all bids are COMPLETED)

---

## 6. Product Coverage Changes (Phase 6.5 vs Phase 6.4)

| Metric | Phase 6.4 | Phase 6.5 | Change |
|--------|-----------|-----------|--------|
| Total products | 14 | 14 | 0 |
| Active products | 14 | 14 | 0 |
| Total keywords | 146 | 146 | 0 |
| Products with zero matches | 9 | 9 | 0 |
| Zero-keyword products | 3 | 3 | 0 |

No changes to the product catalogue were made during Phase 6.5. No keywords were added, removed, or modified.

---

## 7. Recommendations

1. **Deactivate the 3 test products** (AuthBypassTest, Operator Test Product, Test) from the supplier-facing catalogue. They have no keywords, no matches, and no dependencies.

2. **Keep the 6 zero-match products active** with their existing keywords. They are legitimate products with appropriate keyword coverage; the zero-match result is accurate because government procurement bids don't contain blockchain/Web3/crypto terms.

3. **Do not add keywords** to zero-match products to force matches. This would create false positives and violate data integrity.

4. **Document the coverage gap** for suppliers: products in the blockchain/Web3/crypto/privacy domain currently have no matching government bids in the collected corpus.
