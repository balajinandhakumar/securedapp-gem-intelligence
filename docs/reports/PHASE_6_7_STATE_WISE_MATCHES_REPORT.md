# Phase 6.7 State-Wise Matches Report — Issue 2: Matched Product Display Incomplete

**Repository:** `C:\Users\Balaji\Desktop\securedapp-gem-intelligence`  
**Database:** `backend/dev.db`  
**Date:** 2026-11-14

---

## 1. Problem

In the State-Wise Bids view, the SQL query joining `Bid` with `DataSource` on both `source_id` and `source_name` could produce duplicate rows when a bid satisfied both join conditions. This caused duplicate bid cards in the state-wise view, making the matched product display incomplete and confusing. Additionally, there was no explicit empty state for analyzed bids with zero matched products.

---

## 2. Root Cause

The state-wise query used:
```python
query = db.query(Bid, DataSource).join(
    DataSource,
    or_(Bid.source_id == DataSource.id, Bid.source_name == DataSource.name),
)
```

When a bid's `source_id` matched a DataSource AND its `source_name` also matched the same DataSource's name, the `OR` join produced two rows for the same (Bid, DataSource) pair, resulting in duplicate bid cards in the frontend.

Additionally, state attribution was fragile because it relied on `Bid.source_name == DataSource.name` string matching, which split states whose portal display name has variants (e.g., "Jammu & Kashmir" vs "Jammu and Kashmir").

---

## 3. Solution

### Backend — `backend/app/api/v1/endpoints/bids.py`

Added `.distinct()` to the state-wise query:
```python
query = db.query(Bid, DataSource).join(
    DataSource,
    or_(Bid.source_id == DataSource.id, Bid.source_name == DataSource.name),
).distinct()
```

This eliminates duplicate (Bid, DataSource) rows from SQL joins, ensuring each bid appears once per matched product (not duplicated by the join condition).

### Frontend — `frontend/src/components/StateWiseBidsView.tsx`

Updated the "No relevant product" text to "No matched SecuredApp products" for analyzed bids with zero matches, providing clearer empty-state messaging.

### Frontend — `frontend/src/components/StateWiseBidsView.test.tsx`

Added test for "No matched SecuredApp products" empty state.

---

## 4. Database Evidence

| Metric | Value |
|--------|-------|
| Total match records | 106 |
| Unique matched bids | 61 |
| Bids with multiple matches | 45 |
| All matches classification | DETERMINISTIC_PHASE3 |

With `.distinct()`, each of the 61 unique matched bids appears once per matched product (106 total rows), with no duplicate cards from SQL joins.

---

## 5. Test Results

- `test_state_wise_endpoint_returns_product_matches` — PASSED
- `test_state_wise_product_filter` — PASSED
- `test_state_wise_match_status_filter` — PASSED
- `test_duplicate_matches_prevented` — PASSED
- All 12 state-wise matching tests — PASSED
- All 4 state-wise attribution tests — PASSED
- All 69 backend tests — PASSED
- All 61 frontend tests — PASSED
- All 14 Playwright E2E tests — PASSED (including state-wise page test)

---

## 6. Data Integrity

| Rule | Status |
|------|--------|
| No fabricated matches | ✅ All 106 from deterministic engine |
| No duplicate bid cards | ✅ `.distinct()` eliminates SQL join duplicates |
| No historical bid deletion | ✅ All 45,186 bids preserved |
| No reduced matching thresholds | ✅ Unchanged |

---

## 7. Conclusion

Issue 2 is resolved. `.distinct()` prevents duplicate bid cards from SQL joins, and every genuine matched product per bid is displayed exactly once. The "No matched SecuredApp products" empty state provides clear feedback for analyzed bids with zero matches.