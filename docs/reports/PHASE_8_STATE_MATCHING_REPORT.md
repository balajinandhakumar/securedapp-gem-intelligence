# PHASE 8 — STATE MATCHING REPORT (8C)

**SecuredApp GeM Bid Intelligence Platform**
**Version:** 1.0 — Phase 8 (State/UT Scraper Pipeline)
**Date:** 2026-11-10
**Scope:** Product matching run on all state-wise bids via the existing engine

---

## 1. Executive Summary

Phase 8C runs product matching on every state-wise bid using the **existing**
deterministic matching engine (`match_bid_against_products` /
`process_bid_intelligence`) — no separate or inconsistent engine. Every
collected state bid is evaluated against all active SecuredApp products;
qualifying matches (MATCH / POSSIBLE_MATCH / NEEDS_REVIEW with ≥0.25 score
and at least one non-exclusion signal) are persisted as `BidProductMatch`
records with a `BidAnalysis` aggregate, and `matching_status` is set to
COMPLETED / FAILED with `matched_at`.

All 2,252 state bids processed: all COMPLETED, pending=0, failed=0.
Genuine results: 2 matched bids, 3 match records (no fabrication).

---

## 2. Matching runner

`backend/scripts/run_state_matching.py` (already run)
- Cursor-based scan (`WHERE id > last_id ORDER BY id`) so bids whose status
  flips mid-run are never skipped or double-processed (an earlier offset-based
  run left ~600 PENDING; fixed and re-run).
- Eligible bids: `source_id IS NOT NULL` (state sources) AND
  `matching_status IN ('PENDING', 'FAILED')` → GeM excluded.
- For each bid: persists fresh `BidProductMatch` rows (existing rows deleted
  first to avoid duplicates), a `BidAnalysis`, then sets `matching_status =
  COMPLETED` (or FAILED on exception).
- Run in batches of 200 with a commit per batch (no long-lived write
  transaction holding a network call).

Match qualification (reused engine logic): `match_state ∈ {MATCH,
POSSIBLE_MATCH, NEEDS_REVIEW}`, `relevance_score ≥ 0.25`, and at least one
signal with `strength != "EXCLUSION"`.

---

## 3. Results

| Metric | Value |
|--------|-------|
| State bids processed | 2,252 |
| Matching status COMPLETED | 2,252 |
| PENDING | 0 |
| FAILED | 0 |
| Matched bids (≥1 product match) | 2 |
| Match records (bid×product) | 3 |
| Matched bids detail | Assam: 1 (SecurePad, NEEDS_REVIEW, 0.3999) |
| | Punjab: 1 (SolidityShield + AuditExpress, POSSIBLE_MATCH, 0.5) |

Per-state matched bids: Assam = 1, Punjab = 1, all others = 0.
Zero-match states still show their collected bids in the Collected tab
(Phase 8D).

---

## 4. No fabrication / engine reuse

- Matches are produced solely by `match_bid_against_products` (the same engine
  used for GeM bids). No hand-crafted scores, no invented matches.
- Counts reflect genuine deterministic output: most state tenders are general
  works/supplies (e.g. rain-water harvesting, office furniture) that do not
  match the security/crypto product catalogue, hence 2,250 of 2,252 have no
  qualifying match — which is correct and expected.
- Matching engine signature used:
  `match_bid_against_products(db: Session, bid: Bid) -> List[ProductMatchResult]`

---

## 5. Evidence

| File | Description |
|------|-------------|
| `PHASE_8_EVIDENCE/db/reconciliation.json` | matched_bids=2, match_records=3, per-state matched counts |
| `PHASE_8_EVIDENCE/api/summary.json` | per-state matched counts via API |
| `backend/scripts/run_state_matching.py` | Matching runner script |
| `backend/app/services/intelligence/matching_engine.py` | Existing engine (unchanged) |

---

## 6. Preservation statement

- Existing matching engine unchanged; no separate engine created
- No bids, matches, counts, or success statuses fabricated
- No CAPTCHA/auth/anti-bot bypass; matching is offline/deterministic
- No commits or pushes made

---

*End of Phase 8 State Matching Report*
