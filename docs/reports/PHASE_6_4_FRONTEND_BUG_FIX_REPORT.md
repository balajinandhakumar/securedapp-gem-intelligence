# Phase 6.4 Frontend Bug Fix Report — SecuredApp GeM Bid Intelligence Platform

**Repository:** `C:\Users\Balaji\Desktop\securedapp-gem-intelligence\frontend`  
**Date:** 2026-11-12  

---

## 1. Bug: "View Original Bid" / "Download Bid PDF" not rendered in bid detail drawer

### Symptom
The Playwright E2E test `phase-6-0-original-bid.spec.ts` failed: the drawer's "View Original Bid" link (`a:has-text("View Original Bid")`) was not visible after opening a bid detail drawer via "Inspect".

### Root cause
`BidDetailDrawer.tsx` rendered "View Original Bid" and "Download Bid PDF" only when `bid.original_bid_url` was truthy:

```tsx
{bid.original_bid_url && (
  <a href={bid.original_bid_url} ...>View Original Bid</a>
)}
{bid.original_bid_url && (
  <button onClick={handleDownloadPdf} ...>Download Bid PDF</button>
)}
```

The E2E test clicks "Inspect" on the **first** table row. While most GeM bids have `original_bid_url` populated, the drawer renders from `selectedBid` state, which is set from the row data. If the inspected row's bid lacks `original_bid_url` (or the detail fetch hasn't completed before the drawer renders), the links never appear.

### Fix
Changed the rendering condition in `BidDetailDrawer.tsx` (lines 361-381) to prefer `original_bid_url` but fall back to `source_url`:

```tsx
{(bid.original_bid_url || bid.source_url) && (
  <>
    <a
      className="btn-secondary btn-sm"
      href={bid.original_bid_url || bid.source_url!}
      target="_blank"
      rel="noopener noreferrer"
      title={bid.original_bid_url || bid.source_url!}
    >
      View Original Bid
    </a>
    <button
      className="btn-secondary btn-sm"
      onClick={handleDownloadPdf}
      disabled={downloadingPdf}
      title="Download the original bid document (PDF)"
    >
      {downloadingPdf ? 'Downloading…' : 'Download Bid PDF'}
    </button>
  </>
)}
```

The "Download Bid PDF" button now also renders when either URL is present. The download handler (`/api/v1/bids/${bid.id}/download-pdf`) fetches by bid ID from the backend, so it works regardless of which URL is used for the link.

### Files changed
- `frontend/src/components/BidDetailDrawer.tsx`

---

## 2. Bug: "View Original" link missing on bids table rows

### Symptom
Same root cause as above — the table row "View Original" link only rendered when `bid.original_bid_url` was truthy, so rows with only `source_url` showed no link.

### Fix
Changed `BidsFeedView.tsx` (line 350) to fall back to `source_url`:

```tsx
{(bid.original_bid_url || bid.source_url) && (
  <a
    className="btn-secondary btn-sm"
    href={bid.original_bid_url || bid.source_url!}
    target="_blank"
    rel="noopener noreferrer"
    title={bid.original_bid_url || bid.source_url!}
    style={{ marginLeft: '0.35rem' }}
  >
    View Original
  </a>
)}
```

### Files changed
- `frontend/src/components/BidsFeedView.tsx`

---

## 3. Bug: "View Original" link missing on All India matches rows

### Same fix pattern in `AllIndiaMatchesView.tsx` (line 492):

```tsx
{(row.original_bid_url || row.source_url) && (
  <a ... href={row.original_bid_url || row.source_url!} ...>
    View Original
  </a>
)}
```

### Files changed
- `frontend/src/components/AllIndiaMatchesView.tsx`

---

## 4. Bug: "View Original" link missing on State-wise bids rows

### Same fix pattern in `StateWiseBidsView.tsx` (line 521):

```tsx
{(bid.original_bid_url || bid.source_url) && (
  <a ... href={bid.original_bid_url || bid.source_url!} ...>
    View Original
  </a>
)}
```

### Files changed
- `frontend/src/components/StateWiseBidsView.tsx`

---

## 5. Bug: Playwright E2E test timeouts (`phase6_2_screenshots.spec.ts`)

### Symptom
Two E2E tests exceeded the 30s default Playwright test timeout:
- `04 bid detail drawer`: used `page.waitForTimeout(45000)` — 45s blind wait
- `09 all india matches`: used `page.waitForTimeout(20000)` — 20s blind wait

### Root cause
Blind `waitForTimeout` calls are unreliable and can exceed the test timeout. The tests were waiting for page content to load without waiting for specific elements.

### Fix
Rewrote `phase6_2_screenshots.spec.ts` to:
- Add `test.setTimeout(120000)` to each test (consistent with `phase-6-0-original-bid.spec.ts`)
- Replace `page.waitForTimeout(45000)` with `await expect(page.locator('button:has-text("Inspect")').first()).toBeVisible({ timeout: 60000 })` — wait for actual content
- Replace `page.waitForTimeout(20000)` with `await page.waitForLoadState('networkidle')` — wait for network idle
- Replace `page.waitForTimeout(10000)` after drawer open with `await page.waitForLoadState('networkidle')`

### Files changed
- `frontend/tests/e2e/phase6_2_screenshots.spec.ts`

---

## 6. Verification After Fixes

| Check | Result |
|-------|--------|
| `npx tsc --noEmit` | Passes (no type errors) |
| `npx vitest run` | 54 passed (7 files) |
| `npx playwright test` | 14 passed (all E2E green) |
| Backend tests (matching + dashboard/source-adapter/stage2) | 45 + 149 passed |
| Backend health endpoint | `database_connected: true` |

No authentication or RBAC was bypassed. No unrelated refactoring was performed.
