# PHASE 8 — STATE-WISE FRONTEND REPORT (8D)

**SecuredApp GeM Bid Intelligence Platform**
**Version:** 1.0 — Phase 8 (State/UT Scraper Pipeline)
**Date:** 2026-11-10
**Scope:** Frontend State-wise Bids page with Collected / Matched tabs

---

## 1. Executive Summary

Phase 8D rewrote `frontend/src/components/StateWiseBidsView.tsx` into an
individual State/UT scraper view with two tabs:

- **Collected Bids** — every genuinely collected state bid for the selected
  state, including bids with no product match (zero-match states still show
  their collected bids). Uses `include_no_match=true`.
- **Matched Bids** — only bids with at least one persisted product match.

Each bid retains its state and source identity (from the data-source registry).
GeM bids are excluded. The page supports pagination, search, state/product/
match-status/bid-status filters, and loading / error / empty / retry states.
Clicking a bid opens its existing detail drawer.

Wired into the navigation rail (`activeTab === 'state-wise-bids'`, rail label
"State-wise Bids") in `frontend/src/App.tsx`.

TypeScript clean, `npm run build` passed, all 54 frontend tests pass
(StateWiseBidsView extended to 10 tests incl. 4 tab tests).

---

## 2. Component behavior

| State | Behavior |
|-------|----------|
| Loading | Skeleton "Loading state-wise bids…" shell |
| Error | Error banner + Retry button |
| Empty (collected) | "No state-wise bids found" with guidance |
| Empty (matched, state has collected bids) | Explains the state has N collected bids but none matched; suggests switching to Collected Bids |
| Success | Bid table + pagination (Prev/Next) |

Filters: search (bid number/tender ID/title/organisation), state, product,
match status (All / MATCH / POSSIBLE_MATCH / NEEDS_REVIEW / NO_MATCH /
NOT_ANALYZED), bid status (All / OPEN / CLOSING_SOON / CLOSED).

Each row: state (+ state_id), bid/tender number, title, organisation, matched
product(s) with score + keywords, match-state badge, relevance score, est.
value, published/closing dates, source, Inspect → button + View Original link.

A bid matching multiple products renders one row per (bid, product_match)
combination; the tender is never duplicated. Row keys are unique per
`{bid.id}-{index}`.

---

## 3. Data source

All data comes from the live backend APIs (Phase 8B):
- `GET /api/v1/bids/state-wise?…` (bids list, pagination, filters)
- `GET /api/v1/sources` (state list + status)
- `GET /api/v1/products` (product filter options)

The Collected tab passes `include_no_match=true`; the Matched tab uses the
default (matched-only) view. No bids are fabricated — the table reflects
genuinely collected and matched records.

---

## 4. Tests

`frontend/src/components/StateWiseBidsView.test.tsx` — 10 tests:
- Existing coverage (types, search, state filter, pagination, etc.)
- 4 new tab tests:
  - renders Collected and Matched tabs
  - Collected tab shows all collected bids including no-match bids
  - Matched tab shows only bids with ≥1 product match
  - switching back to Collected shows no-match bids again

Frontend suite: **54 passed, 0 failed**. `npm run build` passed. `tsc --noEmit`
clean.

---

## 5. Evidence

| File | Description |
|------|-------------|
| `PHASE_8_EVIDENCE/screenshots/state_wise_collected.png` | Collected Bids tab (live data) |
| `PHASE_8_EVIDENCE/screenshots/state_wise_matched.png` | Matched Bids tab (live data) |
| `PHASE_8_EVIDENCE/tests/playwright_e2e.txt` | E2E: login → State-wise Bids → tabs render (1 passed) |
| `frontend/src/components/StateWiseBidsView.tsx` | Rewritten component |
| `frontend/src/components/StateWiseBidsView.test.tsx` | Extended tests (10) |
| `frontend/src/App.tsx` | Rail wired to `state-wise-bids` |

---

## 6. Preservation statement

- Existing bid-detail drawer, search, and filter behavior preserved
- All-India / bids / products views untouched
- No commits or pushes made

---

*End of Phase 8 State-Wise Frontend Report*
