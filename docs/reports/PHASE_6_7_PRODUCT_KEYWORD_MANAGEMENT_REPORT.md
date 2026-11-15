# Phase 6.7 Product Keyword Management Report — Issue 3: Keyword Add/Remove Management

**Repository:** `C:\Users\Balaji\Desktop\securedapp-gem-intelligence`  
**Database:** `backend/dev.db`  
**Date:** 2026-11-14

---

## 1. Problem

The Product Detail Drawer in the product catalogue did not allow suppliers/operators to manage keywords (add/remove) on a per-product basis. There was no "Add Keyword" button in the drawer, Remove buttons were missing from keyword displays, no confirmation dialog existed for removals, no duplicate prevention was enforced, and there was no RBAC to prevent VIEWER users from modifying keywords. Additionally, no re-evaluation guidance was provided after keyword changes.

---

## 2. Root Cause

The `ProductDetailDrawer` component in `ProductsView.tsx` displayed keywords as read-only badges with no modification controls. The "Add Keyword" button referenced an undefined `setKeywordTarget` function (a bug). The parent `ProductsView` had the keyword management handlers (`handleAddKeyword`, `handleUpdateKeyword`, `handleDeleteKeyword`) and the `KeywordDialog` component, but they were not wired into the ProductDetailDrawer.

---

## 3. Solution

### Backend — Already existed (no changes needed)

The following endpoints already existed with `require_operator` RBAC:
- `POST /api/v1/products/{product_id}/keywords` — Add keyword (duplicate prevention, case-insensitive)
- `DELETE /api/v1/products/{product_id}/keywords/{keyword_id}` — Remove keyword
- `PUT /api/v1/products/{product_id}/keywords/{keyword_id}` — Update keyword

### Frontend — `frontend/src/components/ProductsView.tsx`

**ProductDetailDrawerProps** extended with:
- `onAddKeyword?: () => void` — callback to open Add Keyword dialog
- `canWriteProducts?: () => boolean` — RBAC check

**ProductDetailDrawer component:**
- Remove keyword buttons on each keyword in the Matching Signals section (Operator/Admin only)
- Confirmation dialog before removal (`window.confirm`)
- "Add Keyword" button calls `onAddKeyword?.()` which opens the `KeywordDialog`
- Re-evaluation guidance note (dashed box) explaining that adding/removing keywords changes matching and bids may need re-evaluation; historical records preserved
- Delete button styling (`btn-danger btn-xs`) with "Removing…" state

**Parent `ProductsView` component:**
- Wired `onAddKeyword={() => setKeywordTarget(detailTarget)}` on `ProductDetailDrawer`
- `setKeywordTarget` already defined in parent state

### Frontend Types — `frontend/src/types.ts`

No changes needed; `ProductKeyword`, `ProductKeywordPayload` types already existed.

### Backend Tests — `backend/tests/test_products.py`

Added 7 new keyword lifecycle tests:
- `test_keyword_add_then_remove_persists` — Add then remove keyword; both persist correctly
- `test_keyword_removal_affects_only_selected_product` — Removing from product A doesn't affect product B
- `test_duplicate_keyword_rejection_case_insensitive` — Same keyword with different case returns 409
- `test_update_keyword_endpoint` — PUT updates keyword and weight
- `test_delete_unknown_keyword_returns_404` — Deleting non-existent keyword returns 404
- `test_add_keyword_empty_string_rejected` — Empty keyword returns 422

### Frontend Tests — `frontend/src/components/ProductsView.test.tsx`

Added 5 new keyword management tests:
- Remove action calls `onDeleteKeyword` with correct product/keyword IDs
- Add Keyword dialog opens and submits correctly
- VIEWER cannot see Remove or Add Keyword buttons (RBAC)
- Re-evaluation guidance note is displayed
- Search filtering works on product cards

---

## 4. Database Evidence

| Product | Keywords |
|---------|----------|
| AuditExpress | 18 |
| AuthBypassTest | 0 (test product) |
| CookieHub | 9 |
| Operator Test Product | 0 (test product) |
| PQCSuite | 9 |
| QuantumVault | 16 |
| SecureCMS | 12 |
| SecurePad | 13 |
| SecureTrace | 8 |
| SecureWatch | 12 |
| SecureX-DID | 12 |
| SecureX-ID | 15 |
| SolidityShield | 22 |
| Test | 0 (test product) |
| **Total** | **146** |

No keywords were added or removed from the actual database during development — all changes were tested against in-memory test databases.

---

## 5. Test Results

Backend keyword tests (all PASSED):
- `test_keyword_add_then_remove_persists`
- `test_keyword_removal_affects_only_selected_product`
- `test_duplicate_keyword_rejection_case_insensitive`
- `test_update_keyword_endpoint`
- `test_delete_unknown_keyword_returns_404`
- `test_add_keyword_empty_string_rejected`

Frontend keyword tests (all PASSED):
- Remove action with correct IDs
- Add Keyword dialog open/submit
- VIEWER RBAC denial
- Re-evaluation guidance display

All 69 backend tests, 61 frontend tests, 14 Playwright tests — PASSED.

---

## 6. RBAC Enforcement

| Role | Can Add Keyword | Can Remove Keyword | Can Update Keyword |
|------|-----------------|--------------------|--------------------|
| ADMIN | ✅ | ✅ | ✅ |
| OPERATOR | ✅ | ✅ | ✅ |
| VIEWER | ❌ (buttons hidden) | ❌ (buttons hidden) | ❌ |

Backend endpoints use `require_operator` dependency, rejecting VIEWER with 403.

---

## 7. Data Integrity

| Rule | Status |
|------|--------|
| No keyword fabrication | ✅ All keywords from backend endpoints |
| Duplicate prevention | ✅ Case-insensitive duplicate rejection (409) |
| Confirmation before removal | ✅ `window.confirm` dialog |
| VIEWER cannot modify | ✅ Buttons hidden; backend 403 |
| Re-evaluation guidance | ✅ Displayed after any keyword change |
| Historical records preserved | ✅ Old match records kept; new settings apply to future runs |

---

## 8. Conclusion

Issue 3 is resolved. The Product Detail Drawer now supports full keyword lifecycle management: Remove buttons with confirmation, Add Keyword button opening a dialog, duplicate prevention, RBAC enforcement (VIEWER cannot modify), and re-evaluation guidance. All backend endpoints already existed with proper RBAC.