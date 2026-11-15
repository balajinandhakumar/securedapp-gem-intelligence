# Production-Readiness — Interrupted Run: Recovery & Completion Record

Last updated: 2026-10-11 (resumed session)

Full narrative results live in `docs/PRODUCTION_READINESS_REVIEW.md`. This file
records the exact resumption point of the interrupted Production Readiness &
Deployment Preparation run and the work completed after recovery.

## Where the previous run stopped (recovered)

- §1–§10 of `docs/PRODUCTION_READINESS_REVIEW.md` were complete: security
  hardening, credential-reference allowlist, GePNIC identity (opt-in), real
  11-product catalog matching, 30-portal URL verification, and two controlled
  live batches (§7.2 Odisha/TN/WB, §7.5 Kerala/HP/Rajasthan).
- The regression suites had been run green (628 backend tests; frontend build).
- **Interrupted step:** a third controlled live batch ("Batch #3", internal name
  **P4**) against the next three verified NIC GePNIC hosts —
  `arunachaltenders.gov.in`, `assamtenders.gov.in`, `etenders.hry.nic.in`.
  Interruption evidence (newest artifacts of the run):
  - `%TEMP%\opencode\p4_batch_test.py` (2026-10-11 11:29:51)
  - `%TEMP%\opencode\p4_scratch.db` (2026-10-11 11:30:54)
  - **No `p4_report.json`** — the script never reached its final write, so the
    gated-endpoint probe and dashboard read never ran.
- The scratch DB proved collection + matching **had** completed: 6
  `data_sources`, 9 `source_runs`, 12 bids, 12 `bid_analysis`, 12 `bid_scores`,
  11 real products.

## Work done after recovery (all completed)

1. Resumed against the **existing** `p4_scratch.db` (no re-collection):
   - reconstructed per-run counters from `source_runs` (default syncs #1/#2 and
     the opt-in composite run),
   - re-checked `test_connection` live (3 GETs — ephemeral result not persisted),
   - ran the gated-endpoint probe (3 read-only GETs),
   - recomputed the real 11-product matching rows locally,
   - read the dashboard summary,
   - wrote `docs/test-artifacts/2026-10-11-live-source-testing/p4_report.json`.
2. Retained the reproducibility scripts `p4_batch_test.py` and `p4_resume.py` in
   the evidence directory and updated its `README.md`.
3. Updated `docs/PRODUCTION_READINESS_REVIEW.md` (§3 table, §7.4, §7.6, §10).
4. Re-verified: clean-install app workflow `backend/fresh_db_check.py` → **15/15
   passed**; focused regression subset (source security + identity +
   evidence-gated matching) → **198 passed**. No production code changed, so the
   recorded full-suite result (628 passed) stands.
5. Removed the temporary `%TEMP%` scratch DB after its evidence was retained.

## Results summary

| Item | Result |
| --- | --- |
| Batch #3 test-connection | 3/3 HTTP 200 (Arunachal 2 rows, Assam 10, Haryana 10) |
| Batch #3 default sync #1 | 12 inserted (2 + 5 + 5) |
| Batch #3 default sync #2 | 0 inserted, 12 duplicates — idempotent |
| Batch #3 composite run | 0 new inserts (default identity already unique) |
| Batch #3 catalog/matching | 11 products evaluated per bid; 0 matches (evidence-gated) |
| Batch #3 dashboard | `total_bids=12`, `analyzed_bids=12`, `closing_soon_bids=3` |
| Batch #3 gated probe | `FrontEndLatestActiveTenders` HTTP 200 + CAPTCHA on all 3 |
| Clean-install app workflow | 15/15 passed |
| Focused regression subset | 198 passed |

## Follow-on — Batch #4 (Punjab), separate session

Before any collection, the Punjab home page was probed with **one** controlled
request (`punjab_probe.py`): HTTP 200, public `table#activeTenders`, no CAPTCHA,
4 columns (title / Reference No / Published / Closing), dates `21-Oct-2026
02:00 PM`. Because access was confirmed, the portal then ran through the real
adapter pipeline against a disposable scratch DB (`punjab_batch_test.py`):
test-connection 200 (10 rows); default sync #1 = 3 inserted (5 rows → 3 unique,
`8128/28A` repeated); sync #2 = 0 inserted, 3 duplicates (idempotent); opt-in
composite = 5 discovered, 2 inserted + 3 updated (recovered the full set);
`FrontEndLatestActiveTenders` HTTP 200 + CAPTCHA (gated); 11 products evaluated
per bid, 0 matches; dashboard `total_bids=5`. Artifacts: `punjab_probe.py`,
`punjab_batch_test.py`, `punjab_report.json` in the evidence directory. No
interruption. No production code, `.env`, `dev.db` or scheduler setting changed.
Reusable pattern for the next portal: probe one host → if public, run the batch
script (incremental report writes) → retain artifacts → update §7.

## Follow-on — Batch #5 (Maharashtra), separate session

Maharashtra (`mahatenders.gov.in`) is the next individually-unverified NIC GePNIC
portal. Probe (one request): HTTP 200, public `table#activeTenders`, no CAPTCHA,
4 columns (title / Reference No / Published / Closing), dates `dd-Mon-yyyy hh:mm
AM/PM`. Access confirmed, so the portal ran through the real adapter pipeline
against a disposable scratch DB (`maharashtra_batch_test.py`): test-connection 200
(10 rows); default sync #1 = 5 discovered, 5 inserted (SUCCESS); sync #2 = 0
inserted, 5 duplicates (idempotent); opt-in composite = 5 discovered, 0 inserted,
5 duplicates, 5 updated (re-identified same rows in place); a one-request census
(`maharashtra_census.py`) confirmed **10 rows, 10 distinct Reference Nos, 10
distinct (ref,title), 0 collisions** — so, unlike Punjab/Rajasthan, the default
`bid_number` identity does **not** collapse tenders here and the composite run was
a no-op; `FrontEndLatestActiveTenders` HTTP 200 + CAPTCHA (gated); 11 products
evaluated per bid, 0 matches; dashboard `total_bids=5`, `closing_soon_bids=3`.
Artifacts: `maharashtra_batch_test.py`, `maharashtra_census.py`,
`maharashtra_report.json` in the evidence directory. No interruption. No
production code, `.env`, `dev.db` or scheduler setting changed. The §7.4 allowlist
now has **eleven** individually verified hostnames (added `mahatenders.gov.in`).

## Safety state (unchanged)

- `SOURCE_SCHEDULER_ENABLED=false` throughout.
- `SOURCE_ALLOWED_HOSTS` set **in-process only**, to the exact host(s) being
  batch-tested; no wildcard; no production `.env` modified.
- `SOURCE_ALLOWED_SECRET_ENVS=""`; GeM not contacted.
- Scratch SQLite only; `backend/dev.db` and production env untouched.
- No secrets printed, copied or stored.
