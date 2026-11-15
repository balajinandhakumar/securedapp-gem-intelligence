# Configurable Multi-Source Bid Intelligence — Completion Report

Date: 2026-10-10
Scope: add an operator-configurable, SSRF-safe multi-source collection layer to the
existing SecuredApp GeM Bid Intelligence MVP, reusing its validation → normalization →
dedupe → 11-product matching → notification pipeline unchanged.

---

## 1. Summary

A new "Data Sources" capability now lets an operator register arbitrary public tender
feeds (RSS/Atom, JSON API, HTML listing) as configured sources in a database-backed
registry. Each source is collected through a transport that only ever talks to public
internet addresses, then fed into the exact same pipeline the existing GeM collector
uses. A per-source scheduler is implemented but **off by default**. The existing GeM
Direct collector and Firecrawl pipeline are untouched and still pass their full
regression suites.

## 2. Files changed

New backend code:

- `backend/app/models/source.py` — `DataSource` registry + `SourceRun` audit rows (counters, statuses, error notes).
- `backend/app/services/sources/safe_http.py` — SSRF-safe transport (`validate_public_url`, `safe_get`, redirect revalidation, blocking semantics).
- `backend/app/services/sources/base.py` — adapter base class, config-budget clamps, `apply_auth` (env-var secret refs), `sanitize_config`, safe error shaping.
- `backend/app/services/sources/adapters.py` — `RssFeedAdapter`, `JsonApiAdapter`, `HtmlListingAdapter`, `PlaywrightListingAdapter`, adapter registry + catalog.
- `backend/app/services/sources/runner.py` — `run_source_sync`: per-source lock (no overlap), pipeline wiring, dedupe, counters, intelligence, preview mode.
- `backend/app/services/sources/scheduler.py` — due-source scheduler (`run_due_sources`), restart-safe (state derived from DB), off by default.
- `backend/app/api/v1/endpoints/sources.py` — `/api/v1/sources*`: CRUD, `test`, `sync`, `enable`/`disable`, run history.
- `backend/alembic/versions/0002_source_registry.py` — migration creating `data_sources` + `source_runs`.

Modified backend files:

- `backend/app/api/v1/router.py` — mounted sources router.
- `backend/app/main.py` — start/stop scheduler in lifespan (no-op while disabled).
- `backend/app/core/config.py` — `SOURCE_SCHEDULER_ENABLED=False`, `SOURCE_SCHEDULER_TICK_SECONDS`, `SOURCE_ALLOWED_HOSTS`.

New frontend files:

- `frontend/src/components/SourceManagementPanel.tsx` — registry UI (list, add/edit JSON config, Test, Sync, Runs, enable/disable, delete).
- `frontend/src/types.ts` — added `AdapterMeta`, `SourcesMeta`, `ConfiguredSource`, `SourceRunRow`, `SourceSyncResult`, payload types.
- `frontend/src/components/IngestionView.tsx` — panel mounted above the GeM/Firecrawl panels.

New tests (`backend/tests/`):

- `source_test_utils.py`, `test_source_ssrf.py` (15), `test_source_adapters.py` (19),
  `test_source_registry_api.py` (15), `test_source_runner.py` (9), `test_source_scheduler.py` (10).

## 3. Backup & rollback

The repository is **not** a git repository, so a full backup was taken before any change:

`C:\Users\Balaji\AppData\Local\Temp\opencode\securedapp-backup-20261010-222924`

It contains `backend/app`, `backend/tests`, `backend/alembic`, `frontend/src`, `docs`, the
two `.env` files (root `.env` plus `backend\.env` renamed `backend.env`), `requirements.txt`,
`pyproject.toml` and `README.md`. The production database `backend/dev.db` was itself copied
to `securedapp-backup-20261010-222924/dev.db.bak-before-0002` immediately before the migration
was applied. The migration (`0002`) is reversible (`alembic downgrade -1` drops only the two
new tables) and the new tables contain no data unless an operator adds sources.

## 4. Database / migrations

- New tables: `data_sources` (unique `source_id`, adapter key, type, config JSON, enabled flag,
  interval, per-run/total counters, status, last-attempt/success timestamps, last error) and
  `source_runs` (per-trigger audit: RUNNING/SUCCESS/PARTIAL/FAILED/SKIPPED/BUSY/BLOCKED/
  NO_RECORDS/ERROR, pages fetched, discovered/validated/rejected/inserted/updated/duplicates,
  capped error list, notes).
- Migration `0002_source_registry` applied to `backend/dev.db` (`0001_initial_schema → 0002`).
  Smoke-tested against the real DB: `GET /api/v1/sources` → 200, `GET /api/v1/sources/meta` → 200
  (4 adapters). `backend/dev.db` holds 2,771 bids; untouched by the migration.

## 5. Adapter types supported

| Adapter key | Source types | Method | Requires credentials | Notes |
|---|---|---|---|---|
| `rss_feed` | `rss`, `atom` | HTTP GET → XML | No | RSS 2.0 + Atom feeds; maps title/guid/link/pubDate/description/category/creator |
| `json_api` | `json_api` | HTTP GET → JSON | Optional (env-ref) | Dotted `records_path`, `field_map` (canonical→source field), implicit aliases, auth via `bearer`/`header`/`query`, query-param pagination with repeated-ID page-stop |
| `html_listing` | `html_listing` | HTTP GET → BeautifulSoup | No | CSS `css`/`css@attr` selectors, next-selector or query-param pagination, rows with non-public source links dropped whole |
| `playwright_html` | `playwright_html` | Headless browser after SSRF validation | No | Registered; **not part of the MVP's live-verified adapter set** |

Every adapter returns canonical `RawBidRecord`s; per-run errors are trimmed, secret-free,
and never raw payloads. Config budgets are clamped server-side (timeout 5–120 s, retries 0–5,
max pages 1–200, max records 1–2000, page delay 0–30 s, interval 5–10080 min).

## 6. Functionality delivered

- **API** (`/api/v1/sources`): list/create/read/update/delete, `enable`/`disable` (POST),
  `test` (live connection check, no ingestion), `sync` (manual collection through the real
  pipeline; 409 when busy, 400 on config error/disabled), `/runs` history, `/sources/meta`
  catalog. All responses are secret-free (`sanitize_config` masks secret-key values).
- **Runner** (`runner.py`): disabled → SKIPPED; concurrent run → BUSY (per-source lock,
  non-overlapping with the scheduler); config error → CONFIG_ERROR (source state updated,
  minimal audit); blocked/403/429 → BLOCKED honoring Retry-After without retry storms;
  transport errors → ERROR; then validation layer, same-run dedupe, per-record
  `source_name` attribution, existing `check_duplicate` (identity/hash) → insert (status NEW)
  or corrigendum update only when content changed, duplicates counted; `process_bid_intelligence`
  (DeterministicLLM + OpportunityAnalyzer) per inserted/updated bid with `auto_notify`; source
  status SUCCESS/PARTIAL/FAILED/NO_RECORDS/NEEDS_ATTENTION. `preview=True` validates without
  persisting.
- **Scheduler** (`scheduler.py`): background thread, one source at a time, next-run derived
  from `last_attempt_at` in the DB (restart-safe), per-source failure isolation,
  `run_due_sources` directly testable with a fake clock. **Off unless
  `SOURCE_SCHEDULER_ENABLED=true`** — no live sync ever happens during dev/tests.
- **UI**: "Data Sources — Configurable Bid-Source Registry" panel on the Data Source page with
  adapter catalog, per-source status badges, last-run + lifetime stats, next scheduled run,
  live **Test** and **Sync** (shows the same result grid/errors as the GeM panel), run history
  toggle, enable/disable, delete, and a JSON config editor with per-adapter templates/hints.
  A source's status badge reflects real test/sync results, never merely a saved config.

## 7. Verified sources

**None were live-verified.** The `docs/` folder contains no list of specific tender websites
or feeds to integrate (search for `https?://...` in `docs/` returns nothing), so no real
endpoint was registered or synced. Verification during this deliverable is at the protocol
level: RSS 2.0 + Atom parsing, JSON-API pagination/auth, HTML selector extraction and SSRF
policy are all exercised by 68 automated tests against fake transports and a fake DNS
resolver that can only yield public addresses (tests never touch the network; the global test
fixture forbids `requests.Session.request`). Configuring and live-syncing an actual public
feed is the operator's next step and will exercise per-site reality (blocking, structure
drift, pagination peculiarities).

## 8. Sources needing dedicated integration

- **GeM itself** already has a dedicated, allowlisted collector (`gem_direct_service` /
  `gem_scheduler`) that is the primary source — the registry is additive, not a replacement.
- Any future site whose data is not a plain public RSS/Atom feed, JSON API, or statically
  listed HTML page (e.g. login-walled, JS-only with heavy anti-bot, or needing search
  parameters) will need dedicated integration. `playwright_html` exists as a generic option
  but is explicitly unverified as part of this MVP.
- No third-party tender data provider (Firecrawl optional; a pre-existing unset
  `FIRECRAWL_API_KEY` exists in `backend/.env` but Firecrawl is disabled).

## 9. Regression results (backend + frontend)

- Full backend suite: **577 passed** (509 Stage-1 + 68 new multi-source tests), 0 failures.
- The 68 new tests cover: SSRF policy (15), adapter behaviour (19), registry API (15),
  runner/pipeline integration incl. dedupe replica-check and intelligence wiring (9), and
  scheduler logic (10).
- Ruff: all new/modified source files and tests check clean. Remaining findings are
  pre-existing (e.g. `config.py`/`main.py` unused imports) and were not touched.
- Frontend: `npm run build` (tsc + vite) passes with the new panel (56 modules).

## 10. Security & SSRF

- Only `http`/`https`, no userinfo credentials, ports 80/443; hostname blocks for
  `localhost`, `*.local`, `*.internal`, `*.lan`, `*.home.arpa` and single-label hosts.
- Private/reserved IPv4+IPv6 networks blocked (10/8, 172.16/12, 192.168/16, 127/8,
  0.0.0.0/8, 100.64/10, 198.18/15, TEST-NET, link-local 169.254/16, IPv4-mapped
  `::ffff:0:0/96`, `fc00::/7`, `fe80::/10`), including 169.254.169.254 cloud metadata.
- DNS is resolved immediately before each request and every returned address must be a
  public unicast IP (mitigates DNS-rebinding/split-horizon up to the transport's own
  resolution); redirects are re-validated one hop at a time.
- 403/429 → `BlockedResponseError` honoring `Retry-After`; bounded 5xx retries with backoff.
- Credentials are referenced only by env-var name (`config.auth.env_ref`), resolved at run
  time, never stored/returned/logged. Only names listed in `SOURCE_ALLOWED_SECRET_ENVS`
  may be referenced (empty = deny all), enforced both when a source is saved and on every
  collection; API responses are sanitized.
- The transport pins the checked public address at connect time (the socket opens against
  exactly the IP that passed policy, never a re-resolved one) and the Playwright renderer
  filters every subresource through the same SSRF policy; see the production-readiness
  review for details.

## 11. Data-quality & operational limitations

- **No per-site verification yet** (see §7) — nothing in the registry has been synced live.
- `playwright_html` is registered but unverified; prefer `html_listing`.
- No DNS pinning (see §10).
- Source runs do **not** persist raw payloads (deliberate deviation from the GeM
  `raw_bid_payloads` convention): `source_runs` is the audit trail, keeping disk/log/DB
  exposure minimal; re-fetching a site's history relies on the site still serving it.
- Deduplication is identity-based (`gem_bid_id`/link) exactly like the existing GeM pipeline;
  a feed that omits stable IDs reduces dedupe fidelity (falls back to URL/hash).
- Scheduler is single-threaded and sequential; large batches or slow sources queue their due
  runs. Interval floor is 5 minutes.
- The 20-error cap on run error lists and 500-char note trim are intentional bounds; deeper
  diagnostics require reading the backend logs.