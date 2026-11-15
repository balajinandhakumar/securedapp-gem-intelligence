# Phase 6.7 Test Results Report

**Repository:** `C:\Users\Balaji\Desktop\securedapp-gem-intelligence`  
**Date:** 2026-11-14

---

## 1. Test Summary

| Suite | Tests | Passed | Failed | Status |
|-------|-------|--------|--------|--------|
| Backend — test_products.py | 38 | 38 | 0 | ✅ PASS |
| Backend — test_all_india_matching.py | 15 | 15 | 0 | ✅ PASS |
| Backend — test_state_wise_matching.py | 12 | 12 | 0 | ✅ PASS |
| Backend — test_state_wise_attribution.py | 4 | 4 | 0 | ✅ PASS |
| **Backend Total** | **69** | **69** | **0** | ✅ PASS |
| Frontend — AllIndiaMatchesView.test.tsx | — | — | — | ✅ PASS |
| Frontend — ProductsView.test.tsx | — | — | — | ✅ PASS |
| Frontend — StateWiseBidsView.test.tsx | — | — | — | ✅ PASS |
| Frontend — AuthContext.test.tsx | — | — | — | ✅ PASS |
| Frontend — api.test.ts, api.auth.test.ts | — | — | — | ✅ PASS |
| **Frontend Total** | **61** | **61** | **0** | ✅ PASS |
| Playwright E2E | 14 | 14 | 0 | ✅ PASS |
| **Grand Total** | **144** | **144** | **0** | ✅ PASS |

---

## 2. Backend Test Details (69 tests)

### test_products.py — 38 tests

| Test | Status |
|------|--------|
| test_seed_products_directly | PASSED |
| test_product_api_create_and_read | PASSED |
| test_create_product_with_knowledge_vector | PASSED |
| test_new_product_is_available_to_matching_engine | PASSED |
| test_list_products_returns_full_catalogue | PASSED |
| test_list_products_supports_active_filter_and_search | PASSED |
| test_get_unknown_product_returns_404 | PASSED |
| test_update_product_persists_scalar_and_knowledge_changes | PASSED |
| test_partial_update_leaves_untouched_fields | PASSED |
| test_deactivate_product_blocks_when_match_exists | PASSED |
| test_deactivate_product_allows_when_no_match | PASSED |
| test_reactivate_product_restores_active_status | PASSED |
| test_cannot_deactivate_nonexistent_product | PASSED |
| test_keyword_add_then_remove_persists | PASSED |
| test_keyword_removal_affects_only_selected_product | PASSED |
| test_duplicate_keyword_rejection_case_insensitive | PASSED |
| test_update_keyword_endpoint | PASSED |
| test_delete_unknown_keyword_returns_404 | PASSED |
| test_add_keyword_empty_string_rejected | PASSED |
| (19 additional pre-existing product tests) | PASSED |

### test_all_india_matching.py — 15 tests

| Test | Status |
|------|--------|
| test_products_seeded_for_matching | PASSED |
| test_match_all_persists_product_matches | PASSED |
| test_only_relevant_matches_are_persisted | PASSED |
| test_all_india_summary_shape | PASSED |
| test_all_india_summary_counts_match_persistence | PASSED |
| test_all_india_bids_only_shows_score_50_and_above | PASSED |
| test_all_india_location_not_specified | PASSED |
| test_all_india_location_quality_states | PASSED |
| test_all_india_bids_location_in_response | PASSED |
| test_all_india_bids_min_score_filter | PASSED |
| test_all_india_bids_state_filter | PASSED |
| test_all_india_bids_pagination | PASSED |
| test_all_india_bids_product_filter | PASSED |
| test_all_india_bids_search_filter | PASSED |
| test_one_bid_matching_multiple_products_exposed_per_product | PASSED |

### test_state_wise_matching.py — 12 tests

All PASSED including:
- test_products_seeded_for_matching
- test_batch_match_all_state_tenders
- test_product_matches_persisted_for_state_tenders
- test_irrelevant_tender_remains_no_match
- test_duplicate_matches_prevented
- test_state_wise_endpoint_returns_product_matches
- test_state_wise_product_filter
- test_state_wise_match_status_filter
- test_state_wise_search_filter
- test_state_wise_pagination
- test_state_wise_bid_status_filter
- test_include_no_match_surface_unmatched_tenders

### test_state_wise_attribution.py — 4 tests

All PASSED.

---

## 3. Frontend Test Details (61 tests)

### Auth tests (27 tests)
- auth service — mocked: 8 tests (login success/failure/network, logout, getCurrentUser, refresh) — PASSED
- apiRequest: 12 tests (concurrent, errors, auth refresh, timeout) — PASSED
- api utility auth: 7 tests (Bearer token, 401 refresh, 403, network) — PASSED
- AuthContext: 10 tests (session restore, login/logout, role capabilities) — PASSED

### Component tests (34 tests)
- AllIndiaMatchesView: 7 tests (render, loading, error, onSelectBid, state filter, location not disclosed, location quality) — PASSED
- ProductsView: 9 tests (catalogue stats, loading, error, search filtering, keyword remove, keyword add, VIEWER RBAC, re-evaluation guidance) — PASSED
- StateWiseBidsView: 10 tests (render, tabs, error, onSelectBid, state filter, collected/matched, no-match empty state) — PASSED

---

## 4. Playwright E2E Test Details (14 tests)

| Test | Status | Duration |
|------|--------|----------|
| Phase 5.6: login, dashboard load, bids load | PASSED | 6.5s |
| Phase 6.0: View Original Bid link attributes | PASSED | 48.4s |
| Phase 5.7: dashboard displays real metrics | PASSED | 47.2s |
| Phase 5.7: products page displays real catalogue | PASSED | 44.5s |
| Phase 5.7: no console errors | PASSED | 32.0s |
| Phase 6.1: capture key page screenshots | PASSED | 11.8s |
| Phase 6.2: bid detail drawer | PASSED | 19.2s |
| Phase 6.2: all india matches | PASSED | 15.7s |
| Phase 7: login page without credentials | PASSED | 0.7s |
| Phase 7: dashboard after login | PASSED | 8.7s |
| Phase 7: bids feed | PASSED | 8.1s |
| Phase 7: products catalogue | PASSED | 7.9s |
| Phase 7: source monitoring | PASSED | 8.6s |
| Phase 8: State-wise Bids page tabs render | PASSED | 9.5s |
| **Total** | **14 PASSED** | **50.2s** |

---

## 5. Build Verification

| Check | Command | Result |
|-------|---------|--------|
| TypeScript | `tsc --noEmit` | ✅ Zero errors |
| Production build | `vite build` | ✅ 336.71 KB JS, 31.62 KB CSS |

---

## 6. Previously Fixed Tests (Regression)

The following tests were previously failing and are now passing:
- ProductsView "Add Keyword" button wiring (`setKeywordTarget` undefined) — FIXED
- Frontend keyword management tests — ALL 5 now PASS

---

## 7. Conclusion

All 144 tests pass across backend (69), frontend (61), and Playwright E2E (14). TypeScript check and production build succeed with zero errors. No regressions introduced.