# PHASE 5.7 QUICK FIX REPORT — Dashboard + Products

## Status
Fixed and verified. Backend, frontend, and GeM scheduler remain running. No database reset, no historical bids modified, no mock data introduced, authentication not disabled, scheduler not disabled, nothing committed/pushed.

---

## Root cause — Dashboard
No code defect in API mapping/response parsing.
- `GET /api/v1/dashboard/summary` returns **real persisted data** (200 OK, ~42 ms sequential): `total_bids 2,554` (open), `closed_bids 41,019`, `analyzed_bids 2,554`, `relevant_bids 3`, `possible_match_bids 15`, `needs_review_bids 3`, `closing_soon_bids 1,378`, `notifications 7`.
- Frontend `MetricsOverview` reads `summary.metrics.*` properties that exactly match the backend response; `DashboardView` consumes `priority_opportunities` / `possible_matches` / `recent_bids` / `action_required` correctly.
- Dashboard is **not** hardcoding numbers; every figure comes from SQL conditional aggregation over persisted bids.

The empty-dashboard symptom observed under concurrent load is caused by **SQLite write contention from the GeM scheduler serializing read queries** (backend log: `database is locked` on scheduler inserts). Reads eventually return (observed 14–19 s each under 12× concurrency, 200 OK) but straddle fixed e2e wait timeouts, leaving the UI on skeletons. Backend is already hardened (`PRAGMA journal_mode=WAL`, `busy_timeout=60000`). Per the rules, the scheduler was not disabled.

## Root cause — Products
No code defect in API mapping/response parsing.
- `GET /api/v1/products` returns **14 real catalogue records** (200 OK, ~42 ms sequential) with preserved IDs, descriptions, capabilities, keywords, technologies, categories. No duplicates inserted, nothing hardcoded.
- Frontend `ProductsView` consumes `products[]` and `catalogue-stats` correctly; product properties match the `Product` type.

Additional fixable bug found: the global "Retry" path (`refreshAll` in `App.tsx`) called `fetchBids()`, `fetchSummary()`, `fetchNotifications()` but **omitted `fetchProducts()`**, so after any product-load failure the catalogue was never reloaded by Retry.

## Additional fix — All-India "Inspect" button did nothing
**Root cause:** `handleSelectBid` in `App.tsx` looked the All-India `bid_id` up in the local `bids` array from `GET /api/v1/bids/intelligence`. That feed only returns **open** bids (`serialise_all_bids` applies `include_closed=false` → `open_cond`), but All-India matches surface **both open and closed** bids (the all-india endpoint has no open/closed filter). For any closed all-India bid, `bids.find()` returned `undefined` and `if (!row) return;` silently did nothing — so clicking "Inspect →" opened no drawer and produced no console error (confirmed: only 19 of 50 page-1 all-India bid IDs existed in the intelligence list).

**Fix:** when the bid isn't in the intelligence feed, fall back to `GET /api/v1/bids/{bidId}` (returns any bid, open or closed), build a bid row from the detail response, and proceed to open the bid-detail drawer.

## Files changed
- `frontend/src/App.tsx` — (1) added `fetchProducts()` to `refreshAll` (and its dependency array) so the global Retry also reloads the product catalogue; (2) `handleSelectBid` now falls back to `GET /api/v1/bids/{bidId}` when the bid is absent from the intelligence feed, so the All-India "Inspect →" button opens the bid-detail drawer for closed bids too. No rebuild; no auth/scheduler/DB impact; no mock data.

## Actual database product count
**14 products** in `backend/dev.db` table `products`.
Records (IDs preserved): AuditExpress, AuthBypassTest, CookieHub, Operator Test Product, PQCSuite, QuantumVault, SecureCMS, SecurePad, SecureTrace, SecureWatch, SecureX-DID, SecureX-ID, SolidityShield, Test.

## Dashboard API result
`GET /api/v1/dashboard/summary` → 200 OK:
```json
{
  "metrics": {
    "total_bids": 2554,
    "closed_bids": 41019,
    "analyzed_bids": 2554,
    "pending_analysis": 0,
    "relevant_bids": 3,
    "possible_match_bids": 15,
    "needs_review_bids": 3,
    "closing_soon_bids": 1378,
    "closing_soon_window_days": 7,
    "notifications": 7
  }
}
```
Total bids in DB = 43,573 (2,554 open + 41,019 closed), consistent with the historical 43,441+ figure. All figures from persisted data, not hardcoded.

## Browser verification result
PASSED (single-user Playwright against `http://localhost:3000`, backend `127.0.0.1:8000`):
- Login (demo@securedapp.io) succeeds against the real backend; session/Bearer tokens work.
- Dashboard renders real metrics (no skeletons, no "Loading", no empty state) — real bid counts displayed.
- Products page renders "SecuredApp Product Catalogue" with 14 catalogue records (e.g. SecureCMS, PQCSuite visible); not an empty/loading/error state.
- No critical browser console errors; no failed network requests.
- Refresh works via the data-fetch flow; `refreshAll` now also re-fetches products.
- All-India "Inspect →" opens the bid-detail drawer with real bid data (verified on page-1 matches including closed bids); no browser console errors.

## Remaining issues
- **SQLite write contention under concurrent load**: GeM scheduler writes + concurrent frontend readers serialize SQLite reads, slowing dashboard/products APIs to ~14–19 s each under load. Backend already uses WAL + `busy_timeout=60000`. Not disabled per rules; considered operational, not a code-mapping defect. If the dashboard/products appear stuck under heavy concurrent load, a page refresh after the scheduler tick recovers them.
- The e2e `data-verification.spec.ts` is timing-sensitive under parallel (3-worker) load because of the above SQLite slowness; it passes in single-user/single-test verification but can time out when 3 pages hammer a contended SQLite DB simultaneously.

## Verification commands used
- `curl http://127.0.0.1:8000/api/v1/health` → `{"status":"ok","database_connected":true}`
- `POST /api/v1/auth/login` → token issued (demo admin)
- `GET /api/v1/dashboard/summary` → 200, real metrics above
- `GET /api/v1/products` → 200, 14 products
- `GET /api/v1/products/catalogue-stats` → 200, total_products 14
- Playwright `data-verification.spec.ts` (single-user): dashboard real-metrics test + products catalogue test + no-console-errors test pass in isolation.
- SQLite counts: `SELECT COUNT(*) FROM bids` = 43,573; `SELECT COUNT(*) FROM products` = 14.
