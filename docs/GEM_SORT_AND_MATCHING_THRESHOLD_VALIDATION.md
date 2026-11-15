# GeM Sort Order & Matching-Threshold Validation

**Date:** 2026-10-11
**Scope:** Validate the existing GeM collection workflow's sort order and the
product-matching engine's relevance threshold, then exercise all 11 SecuredApp
products against a small controlled set of real GeM tenders.

**Evidence:** `docs/test-artifacts/2026-10-11-gem-sort-and-threshold/`
(`gem_sort_threshold_report.json`, `gem_sort_threshold_test.py`,
`gem_sort_markup_probe.py`).

---

## 1. GeM tender sorting — Bid Start Date: Latest First

### What the existing collector does

The GeM source is the **Direct GeM Public Collector**
(`backend/app/services/ingestion/gem_public_collector.py`). It is explicitly not
a GeM API client: the `all-bids` page is a JavaScript shell, so the collector
drives the page's **own** browser functions inside a real rendered session
(Playwright). Sorting is applied through GeM's own `sort()` function with the
portal's own option id (`PlaywrightListingSession.SET_SORT_JS`,
`gem_public_collector.py:872`). No endpoint or parameter is invented.

The sort id comes from one existing setting — `GEM_DIRECT_SORT_ORDER`
(`config.py`), read by `gem_direct_service.py:423` and passed into
`open_listing_session(...)`.

### The exact portal value (verified, not assumed)

A single read-only probe of the live page (`gem_sort_markup_probe.py`) found the
portal's own dropdown markup:

```html
<a id="Bid-Start-Date-Latest" onclick="sort(`Bid-Start-Date-Latest`)">Bid Start Date: Latest First</a>
<a id="Bid-Start-Date-Oldest" onclick="sort(`Bid-Start-Date-Oldest`)">Bid Start Date: Oldest First</a>
<a id="Bid-End-Date-Latest"   onclick="sort(`Bid-End-Date-Latest`)">Bid End Date: Latest First</a>
<a id="Bid-End-Date-Oldest"   onclick="sort(`Bid-End-Date-Oldest`)">Bid End Date: Oldest First</a>
```

So the required order **"Bid Start Date: Latest First"** is the portal id
**`Bid-Start-Date-Latest`**. (Note: it is `-Latest`, not a made-up `-Newest`.)

### Change made

`GEM_DIRECT_SORT_ORDER` default set to `Bid-Start-Date-Latest`:
- `backend/app/core/config.py` (value + explanatory comment)
- `.env.example`
- `backend/app/api/v1/endpoints/gem_direct.py` (status model default)
- `backend/app/services/ingestion/gem_public_collector.py` (`status()` fallback)
- `backend/tests/test_gem_date_and_scope.py` (pinned assertion + test name)

Bid End Date sorting was **not** substituted and oldest-first was **not** used.

### Verification (live)

One controlled page-1 render, 2026-10-11:

| Evidence | Result |
| --- | --- |
| `scope_applied` from the page's own session | `{"bidStatusType":"ongoing_bids","byType":"all","sort":"Bid-Start-Date-Latest"}` |
| Rendered sort button label (`#currentSort`) | **"Bid Start Date: Latest First"** |
| Portal accepted the id (`sort()` returned true) | yes |
| Listing size at capture | 46,049 ongoing records / 4,605 pages |
| Rows parsed | 10, 0 parse failures |
| Order of Bid Start Dates (render order) | `23:00, 23:00, 23:00, 22:00, 22:00, 22:00, 21:00, 21:00, 21:00, 21:00` (all 2026-10-11) |
| Newest-first (descending) | **True**, 0 violations |

**Conclusion:** Bid Start Date: Latest First is correctly applied and verified
against the live portal (the portal's own sort function, its own id, and the
portal's own visible label), and the returned rows are ordered newest bid-start
first.

---

## 2. Matching-engine relevance threshold

### What the threshold controls

The relevance threshold is the cutoff applied to a match candidate's
`relevance_score` to decide its `match_state`
(`backend/app/services/intelligence/matching_engine.py`). It is **not** a
single MATCH/NO_MATCH switch in the original code — `classify_score` used four
bands:

```
>= 0.70 MATCH | >= 0.45 POSSIBLE_MATCH | >= 0.25 NEEDS_REVIEW | else NO_MATCH
```

### Score scale (reported before changing behaviour)

The score is already **normalized to 0.0–1.0**: `raw_score / 12.0`, clamped
(`matching_engine.py:263`), where `raw_score` is a weighted sum of matched
capabilities/keywords (`FIELD_WEIGHTS × SIGNAL_WEIGHTS × catalogue weight`).
The requested `0.5` therefore applies to the same normalized 0–1 scale — no
scale mismatch.

### Change made (smallest necessary, single setting)

The threshold was **hardcoded** (no config existed). A single setting was added:

```python
MATCHING_RELEVANCE_THRESHOLD: Optional[float] = None   # config.py
```

`classify_score(score, threshold=None)` now:
- **threshold `None` (default):** unchanged four-band behaviour (backwards compatible).
- **threshold set (e.g. `0.5`):** binary cut on the same 0–1 score —
  `score >= 0.5 -> MATCH`, else `NO_MATCH`.

The test sets it to `0.5` through this one setting (`MATCHING_RELEVANCE_THRESHOLD=0.5`).
The scoring algorithm and all keyword/capability weights are untouched. The
duplicated inline band block in `_match_single_product` was removed in favour of
the single `classify_score` source of truth. No second threshold setting was
introduced.

> Transparency: several **unrelated pre-existing** hardcoded cutoffs remain for
> other purposes (notification trigger `>= 0.70` in `batch_processor.py` /
> `analysis.py`; dashboard band display `0.70/0.45/0.25` in `dashboard.py`;
> persistence gate `< 0.25` in `bids.py`). These were not changed and are
> separate from the engine's relevance classification.

### Threshold behaviour check (same process, threshold = 0.5)

`0.00→NO_MATCH, 0.25→NO_MATCH, 0.30→NO_MATCH, 0.45→NO_MATCH, 0.49→NO_MATCH,
0.50→MATCH, 0.55→MATCH, 0.70→MATCH, 0.90→MATCH`.

---

## 3. All 11 products vs real tenders

Catalog (11, all active, sourced from `seed_knowledge.py`, unchanged):
SolidityShield, SecureCMS, SecureTrace, CookieHub, PQCSuite, SecureX-DID,
SecureWatch, AuditExpress, SecurePad, SecureX-ID, QuantumVault.

**Tenders tested:** 10 real GeM tenders (one live page). Each evaluated against
all 11 products. Results are stored in the report; listing-level rows carry
`title` + item text only (no scope/eligibility/technical fields), which is the
full evidence available from the listing.

| # | Bid number | Start (bid start) | Top product / score / state | Positive-score products |
| --- | --- | --- | --- | --- |
| 1 | GEM/2026/B/7986623 | 2026-10-11 23:00 | SolidityShield / 0.0 / NO_MATCH | none |
| 2 | GEM/2026/B/8045469 | 2026-10-11 23:00 | SolidityShield / 0.0 / NO_MATCH | none |
| 3 | GEM/2026/B/8002492 | 2026-10-11 23:00 | SolidityShield / 0.0 / NO_MATCH | none |
| 4 | GEM/2026/B/8075867 | 2026-10-11 22:00 | SolidityShield / 0.0 / NO_MATCH | none |
| 5 | GEM/2026/B/8077479 | 2026-10-11 22:00 | SolidityShield / 0.0 / NO_MATCH | none |
| 6 | GEM/2026/B/8031129 | 2026-10-11 22:00 | SolidityShield / 0.0 / NO_MATCH | none |
| 7 | GEM/2026/B/7619197 | 2026-10-11 21:00 | SolidityShield / 0.0 / NO_MATCH | none |
| 8 | GEM/2026/B/7969329 | 2026-10-11 21:00 | SolidityShield / 0.0 / NO_MATCH | none |
| 9 | GEM/2026/B/8064568 | 2026-10-11 21:00 | SolidityShield / 0.0 / NO_MATCH | none |
| 10 | GEM/2026/B/8043503 | 2026-10-11 21:00 | SolidityShield / 0.0 / NO_MATCH | none |

("Top product" is the first candidate when all scores tie at 0.0; it is a
NO_MATCH and is never surfaced as a match — see §4.)

**Outcomes**
- Genuine matches (score ≥ 0.5): **0**
- Below threshold but non-zero (0 < score < 0.5): **0**
- Zero-score NO_MATCH: **10**
- Not yet analyzed: **0** (all 10 analyzed: `analyses=10`, `scores=10`)
- Matched keywords/evidence: **none** — no product keyword or capability fired
  on any tender, so no signals and no scores.
- Rejected unsupported matches: all 10 (correct — no fabricated evidence).

Dashboard after the run: `total_bids=10, analyzed_bids=10, pending_analysis=0,
relevant_bids=0, possible_match_bids=0, needs_review_bids=0, closing_soon_bids=10`.

---

## 4. Validation against the GeM portal

- **Sort vs relevance are not conflated:** portal ordering (Bid Start Date
  latest-first) is confirmed by the page's own session + label + descending
  start-date sequence; relevance ranking is the separate product-score sort
  done by the engine.
- **Newest bid-start dates appear first:** confirmed (see §1).
- **Manual product-fit review:** all tenders are generic goods/works (charcoal,
  dog-shelter construction, office/antivirus licences, garbage bags, punch set,
  shooting gear, plywood, printer/consumables, and a numeric item list). None
  carries cybersecurity / Web3-product evidence, so 0 matches is expected.
- **False positives:** **0** — no product was suggested for any tender.
- **Missed matches:** one tender deserves a note —
  **`GEM/2026/B/8043503` "Cyber Security Audit - Infrastructure Audit, STQC"**
  (Finance Department, Uttarakhand). It superficially contains the word
  "audit". The engine scored it **0.0 (NO_MATCH)**, which is defensible: the
  only catalogue product with "audit" (`AuditExpress`) is scoped to
  **automated smart-contract** security assessment, and this tender is a generic
  infrastructure/STQC IT audit with **no** smart-contract or Web3 evidence. The
  engine's whole-term/phrase evidence gate correctly refused to match on the
  bare word "audit". This is recorded as the single tender a human reviewer
  should look at, **not** as a confirmed engine miss. No catalogue or algorithm
  change was made to force it.

---

## 5. Preservation & safety

- No redesign of the dashboard, no DB-model change, no collector replacement, no
  change to the 11-product catalog, and no change to unrelated ingestion or
  notification logic.
- Runs used a **scratch SQLite DB**; production `dev.db` and production `.env`
  were not modified. `GEM_DIRECT_SCHEDULER_ENABLED=false` throughout.
- Collection was one public page with an honest user agent, respecting rate
  limits; no CAPTCHA/auth bypass; `403/429` would have stopped the run.

---

## 6. Tests & results

| Check | Result |
| --- | --- |
| Focused matching + source regression (`test_gem_date_and_scope`, `test_intelligence`, `test_matcher_token_matching`, `test_matcher_exclusion_sign`, `test_stage1_evidence_gated_matching`, `test_advanced_suite`) | **107 passed** |
| Full backend suite (`python -m pytest -q`) | **628 passed** |
| Live controlled GeM run (sort + threshold 0.5) | success; 10/10 analyzed, 0 matches |
| `ruff check` on changed files | no **new** findings; repo baseline has 43 pre-existing errors (E712/F401 in untouched lines) |
| Frontend build | **not run** — changes are backend-only; no frontend code path is affected |

---

## 7. Direct answers

- **Is Bid Start Date: Latest First correctly applied and verified?** Yes.
  `GEM_DIRECT_SORT_ORDER=Bid-Start-Date-Latest` (the portal's own id for
  "Bid Start Date: Latest First"); live page confirmed the applied sort, the
  visible label, and newest-first start dates with 0 violations.
- **Is threshold 0.5 configured, and what scale?** Yes, via the single
  `MATCHING_RELEVANCE_THRESHOLD=0.5` setting. The scale is the engine's
  normalized **0.0–1.0** relevance score; `score >= 0.5 -> MATCH`, else
  `NO_MATCH`. Default (`None`) preserves the original four-band behaviour.
- **Number of real tenders tested:** 10.
- **Matched / unmatched:** 0 matched, 10 unmatched (0 not-yet-analyzed).
- **Product matches & evidence:** none — no product keyword/capability signal
  fired on the collected goods/works tenders.
- **False positives / missed matches:** 0 false positives; 1 borderline tender
  (cyber security audit) manually reviewed and judged not a smart-contract fit.
- **Remaining blockers:** none for the requested behaviour. For higher-quality
  matching on GeM, listing-level pages provide title + item text only; enabling
  detail-page enrichment (`GEM_DIRECT_ENRICH_DETAIL_PAGES`) would supply scope/
  technical/eligibility fields, but that is a collection-coverage decision
  outside this task.
