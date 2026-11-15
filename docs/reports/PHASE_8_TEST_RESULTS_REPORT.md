# PHASE 8 — TEST RESULTS REPORT (8E)

**SecuredApp GeM Bid Intelligence Platform**
**Version:** 1.0 — Phase 8 (State/UT Scraper Pipeline)
**Date:** 2026-11-10
**Scope:** Backend, frontend, and E2E test results after Phase 8 changes

---

## 1. Executive Summary

All verification suites pass after the Phase 8 model/API/frontend changes:

| Suite | Passed | Failed | Total | Notes |
|-------|--------|--------|-------|-------|
| Backend (pytest) | 770 | 0 | 770 | +4 new attribution tests (was 766) |
| Frontend (vitest) | 54 | 0 | 54 | StateWiseBidsView 10 tests (was 50) |
| Playwright E2E | 1 | 0 | 1 | State-wise page login + tabs |
| TypeScript (`tsc --noEmit`) | clean | 0 | — | — |
| Production build (`npm run build`) | passed | 0 | — | — |
| **Grand total** | **825** | **0** | **825** | — |

No tests were removed or weakened. The 5 pre-existing `test_state_wise_matching.py`
tests that broke due to the stricter `source_id` join were fixed by making the
join inclusive (`source_id OR source_name` fallback), preserving backward
compatibility for bids collected before the backfill.

---

## 2. Backend (pytest, `python -m pytest -q`, in-memory SQLite)

**770 passed, 0 failed, 235 warnings, ~176s**

New: `backend/tests/test_state_wise_attribution.py` (4 tests):
- `test_state_wise_summary_counts`
- `test_state_wise_collected_includes_no_match`
- `test_state_wise_matched_only`
- `test_state_wise_attribution_not_split_by_name_variant`

Pre-existing `test_state_wise_matching.py` (12 tests) all pass after the
inclusive-join fix:
- `test_batch_match_all_state_tenders`
- `test_product_matches_persisted_for_state_tenders`
- `test_retry_failed_bids`
- `test_matching_status_transitions`
- `test_state_wise_endpoint_excludes_gem_bids`
- `test_all_india_includes_state_tenders`
- (and others)

Evidence: `PHASE_8_EVIDENCE/tests/backend_full_suite.txt`

---

## 3. Frontend (vitest, `npm run test`)

**54 passed, 0 failed**

`StateWiseBidsView.test.tsx` extended from 6 → 10 tests (4 new tab tests).
`npm run build` passed; `tsc --noEmit` clean.

Evidence: `PHASE_8_EVIDENCE/tests/frontend_tests.txt`

---

## 4. Playwright E2E (`npx playwright test`, `PLAYWRIGHT_BASE_URL=http://localhost:3006`)

**1 passed, 0 failed**

`frontend/tests/e2e/phase8_state_wise.spec.ts`:
- Login (admin@securedapp.io)
- Navigate to "State-wise Bids" rail item
- Collected / Matched tabs visible
- Collected bid rows render (genuinely collected state bids)
- Tab switching works
- Zero console errors on the page

Evidence: `PHASE_8_EVIDENCE/tests/playwright_e2e.txt` +
`PHASE_8_EVIDENCE/screenshots/state_wise_collected.png` +
`PHASE_8_EVIDENCE/screenshots/state_wise_matched.png`

---

## 5. Services during verification

- Backend (uvicorn): `http://127.0.0.1:8002` — health HTTP 200
- Frontend (Vite dev): `http://localhost:3006` (ports 3001–3005 were in use;
  dev server auto-selected 3006, proxies `/api` to backend:8002)

---

## 6. Preservation statement

- No existing tests deleted or assertions weakened
- No fabricated pass/fail statuses
- No commits or pushes made

---

*End of Phase 8 Test Results Report*
