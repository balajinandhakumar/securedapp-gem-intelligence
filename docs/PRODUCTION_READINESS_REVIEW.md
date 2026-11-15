# Production-Readiness Review — Configurable Multi-Source Bid Intelligence

Date: 2026-10-11 (updated 2026-10-11 with the credential-reference policy pass and the
30-portal onboarding verification + 3-portal live batch test)
Reviewer scope: adversarial read-through + hardening of the multi-source collection
layer added in `docs/MULTI_SOURCE_BID_INTELLIGENCE_REPORT.md`, plus onboarding
verification of the operator-supplied 30-portal state/UT inventory.

The first two passes (hardening, then the credential-reference policy) were verified
with fakes only. **This update adds a controlled live batch test**: three authorized
public state portals (Odisha, Tamil Nadu, West Bengal) were contacted over the network,
their public listing tables collected through the real adapter pipeline, and the results
persisted to a **scratch** SQLite DB (never `dev.db`). GeM was not contacted. See §7.

The second pass closed the previously-documented `auth.env_ref` exfiltration gap with a
strict server-side allowlist. See §2.6 and §6.

---

## 1. Verdict

The collection layer is functionally complete and its regression suite is green
(618 backend tests, frontend production build; 594 at the end of the first pass,
+24 from the new credential-policy suite). This review found **five real
defects/weaknesses** in the "hardening" claims of the original report and fixed them
with targeted, adversarially-tested changes. After these fixes the layer's stated
guarantees (public-host-only egress, secret-free errors, audit-every-run,
operator-cannot-exfiltrate-credentials) hold under the tests that exercise them.

Nothing here has been validated against a live collection site (no live GeM / no live
external feed was contacted). See §6 for what that leaves unverified.

> **Update (30-portal onboarding).** In addition to the fakes-only review above, the
> operator-supplied 30 state/UT inventory was verified against authoritative sources
> (§7.1) and a **controlled live batch test** was run against three approved public
> portals — Odisha, Tamil Nadu and West Bengal (§7.2). Real records were collected,
> persisted to a scratch DB and surfaced by the dashboard; the second sync was fully
> idempotent. This is the first live-site evidence in this document and it is reported
> separately from the fakes-based suite. GeM was **not** contacted.

## 2. Confirmed issues and fixes

### 2.1 `SECRET` — credentials embedded in error messages and logs (HIGH)
`apply_auth` injects API tokens into the request as query parameters
(`auth.type=query`). On failure, `safe_http` built its messages from the *full* URL —
`SafeFetchError(f"Request to {target} failed ...")`, `BlockedResponseError`,
"Too many redirects", the retry `logger.warning`, and the RSS 404/parse messages.
Because the UI renders `source.last_error`, `run.message` and `run.errors[].message`
verbatim, a token could be displayed or logged.

Fix: added `url_for_log(url)` (strips userinfo, query string and fragment; bounded
length) and routed every user-visible/logged string through it across
`safe_http.safe_get`, the redirect + block paths, and the RSS adapter. Request URLs
sent on the wire are unchanged.

### 2.2 `SSRF` — DNS check and connection were not coupled (HIGH)
`validate_public_url` resolved the host and checked it was public, but the socket was
opened later by a *second*, independent resolver lookup. A host using DNS rebinding /
split-horizon could resolve public for the check and private at connect time
(e.g. `169.254.169.254` metadata).

Fix: `safe_get` now resolves a second time immediately before the request
(`_pins_for_target`), fails closed if the result is empty or non-public, and records
the checked IPv4 (preferred) address in a thread-local pin. A custom urllib3
connection class reads the pin and opens the socket against that exact IP, re-checking
the address against the blocked ranges before dialing. TLS SNI / certificate hostname
stay on the original hostname (`server_hostname` falls back to `self.host` in the
installed urllib3 2.6.3), so pinning does not weaken certificate validation. Pins are
cleared in a `finally` block, including on redirect chains.

### 2.3 `SSRF` — headless renderer fetched unvalidated subresources (MEDIUM)
`PlaywrightListingAdapter._safe_fetch` validated only the initial navigation URL. The
headless browser then fetched scripts, images, iframes and XHRs on its own, so the
initial URL could pull in an internal address.

Fix: installed a `page.route("**/*", _route_guard)` before `goto`. `_guard_browser_request`
allows `http(s)` only when `validate_public_url(...)` passes, allows non-network browser
schemes (`about:`, `data:`, `blob:`, `javascript:`, `chrome`, `chromium`), and aborts
everything else (`file:`, `ftp:`, `ws:`, `wss:`, unknown).

### 2.4 `AUDIT` — a mid-pipeline crash silently lost the run (MEDIUM)
An unexpected exception between successful collection and the final commit (e.g. an
`IntegrityError` when two sources yield the same `gem_bid_id`, a normalizer edge case)
was not handled by `run_source_sync`. Manual sync returned an opaque 500; the
scheduler path logged and rolled back on connection close, leaving **no** `SourceRun`
audit row — contradicting the original report's "every run writes an audit row" claim.

Fix: the whole post-collection pipeline is wrapped; on crash `_record_crashed_run`
snapshots the counters *before* rollback, discards the partial transaction (no
half-inserted bids), writes a fresh `SourceRun` (same id, `status="ERROR"`, counters,
trimmed secret-free errors), sets the source to `ERROR` with `last_error`, and commits
an `_result`-shaped response.

### 2.5 `INTEGRITY` — adapter_key could contradict source_type (LOW)
An explicit `adapter_key` was accepted without checking it supports the declared
`source_type`. Fix: `_adapter_key_for` now rejects unknown keys and mismatches with a
422. Also replaced the hardcoded `scheduler:{enabled:false}` in `/sources/meta` with the
real `scheduler_status()` (still off by default, now truthful if enabled).

### 2.6 `EXFIL` — credential references could name any environment variable (CRITICAL)
`apply_auth`/`resolve_auth_secret` read any `os.environ` name supplied in
`config["auth"]["env_ref"]`. An operator who can register a JSON source could name
`DATABASE_URL`, `SECRET_KEY`, `FIRECRAWL_API_KEY` or any other process variable and
arrange for the source's request to deliver that value to a host they control — a
pure exfiltration primitive with an operator-trusted API as the trigger.

Fix — strict server-side allowlist, enforced twice:
- **Policy**: a new setting `SOURCE_ALLOWED_SECRET_ENVS` lists the exact
  environment-variable names a source may reference. **Empty (default) = deny every
  secret reference** (fail-closed). Names must be valid shell identifiers
  (`[A-Za-z_][A-Za-z0-9_]*`, ≤128 chars), are matched exactly (case-sensitive), and a
  name that merely *contains* an allowed name is not allowed.
- **At save time**: adapter `validate_config` (JSON API) calls `validate_secret_ref`,
  so an unauthorized/malformed reference is rejected with a 422 before it is stored.
- **At collection time**: `apply_auth` → `resolve_auth_secret` re-enforces the same
  allowlist every run, so a row that was valid when saved cannot read a variable once
  the policy is tightened (or the variable removed from the allowlist). Failures become
  `source.status == "CONFIG_ERROR"` with a message that names the variable only.
- **Response safety**: `sanitize_config` now reduces the `auth` block to its known
  reference keys (`type`/`env_ref`/`param`/`header_name`) and **drops** any other key
  (e.g. a raw header map or a literal value) so a credential can never be echoed back.
  Secret *values* never appear in responses, errors, logs, run errors or
  `source.last_error`; `env_ref` (a reference name) is returned so the UI can show
  which variable a source uses.

## 3. Verification (what was actually run)

| Check | Result |
| --- | --- |
| `python -m pytest -q` (backend, fakes only, no network) | **628 passed** |
| New secret-policy suite `tests/test_source_secret_policy.py` | 24 passed |
| New tender-identity suite `tests/test_gepnic_identity.py` | 10 passed |
| Focused source-security subset (adapters, registry API, runner, SSRF, hardening, scheduler, integration) | 149 passed |
| Evidence-gated matching suites (stage1, matcher, intelligence) | 79 passed |
| New hardening suite `tests/test_source_hardening.py` | 14 passed |
| New registry checks (mismatch/unknown key, scheduler meta) | 3 passed |
| Clean-install app workflow `backend/fresh_db_check.py` (fresh temp DB, real HTTP API: seed, ingest, analyze, match, dashboard, product lifecycle) | **15/15 checks passed** |
| Focused regression re-run (source security + identity + evidence-gated matching) | **198 passed** |
| Controlled live batch #3 (Arunachal/Assam/Haryana; resumed after interruption) | 3/3 HTTP 200; 12 inserted; idempotent; 0 matches; see §7.6 |
| Controlled live batch #4 (Punjab; probe + full pipeline, scratch DB) | HTTP 200; 3 default / 5 composite tenders; idempotent; 0 matches; see §7.7 |
| Controlled live batch #5 (Maharashtra; probe + census + full pipeline, scratch DB) | HTTP 200; 5/5 unique (no collision); idempotent; 0 matches; see §7.8 |
| `ruff check` on all files changed by this work | clean |
| `ruff format --check` on all files changed by this work | clean for new code; see note |
| `npm run build` (frontend, `tsc` + `vite`) | success |
| Secret-exposure search (backend/app + frontend/src) | no logging/printing/echo of credential values |

> **Format note.** `ruff` (0.15.4, no `[tool.ruff]` config → defaults) flags pre-existing
> formatting in some older files (e.g. `normalizer.py` json-block wrapping, docstring
> spacing) that predates this work — confirmed against the pre-change backup. New code
> introduced here is format-clean; pre-existing style in untouched regions was **not**
> mass-reformatted, to keep the diff reviewable.

Adversarial cases now covered: DNS-rebinding second resolution refused **before any
request is sent** (`session.calls == []`); pinned socket address equals the checked
public IP while `conn.host` stays the hostname; a blocked pin raises
`NewConnectionError`; pin context is cleared; tokens in query strings never appear in
`SafeFetchError`/`BlockedResponseError`/retry logs/RSS errors/`run.errors`/`source.last_error`;
crash path persists an `ERROR` `SourceRun`, leaves zero partial bids and the source not
`RUNNING`; browser guard blocks loopback/link-local/`file:`/`ftp:`/`ws:` and allows
public http(s) + `data:`/`about:`/`blob:`/`javascript:`.

Credential-policy adversarial cases: an environment variable **that is actually set**
(`SUPER_SECRET_TOKEN`) is rejected without an allowlist entry; malformed references
(whitespace, `/`, `=`, leading digits, 200-char) are rejected; matching is exact and
case-sensitive (`APP_KEY_BACKUP` ≠ `APP_KEY`); approved-but-unset fails with the name
only; a value never appears in a `SourceConfigError`, logs, run records, API responses
or `source.last_error`; a row saved under an allowed ref refuses to read after the
allowlist is emptied (`CONFIG_ERROR`); non-reference keys inside `auth` are dropped by
`sanitize_config`.

## 4. Files changed in this review

- `backend/app/services/sources/safe_http.py` — `url_for_log`, pinned transport
  (`_PinnedHTTPConnection`/`_PinnedHTTPSConnection`/pools/`_PinnedHTTPAdapter`), second
  resolution + fail-closed pinning in `safe_get`, redacted messages, pin clear in `finally`.
- `backend/app/services/sources/adapters.py` — `_guard_browser_request` + Playwright
  route guard; redacted RSS 404/parse messages; config-time `validate_secret_ref` in the
  JSON adapter.
- `backend/app/services/sources/runner.py` — pipeline `try/except` + `_record_crashed_run`.
- `backend/app/services/sources/base.py` — `allowed_secret_envs()`/`validate_secret_ref()`
  credential allowlist; `resolve_auth_secret`/`apply_auth` enforce it every call;
  `sanitize_config` drops non-reference keys inside `auth`.
- `backend/app/core/config.py` — `SOURCE_ALLOWED_SECRET_ENVS` setting +
  `source_allowed_secret_envs` property; removed dead imports so `ruff check` stays clean.
- `backend/app/api/v1/endpoints/sources.py` — adapter/source_type 422, real scheduler meta.
- `.env.example` — documented multi-source block incl. the credential allowlist.
- `backend/tests/test_source_secret_policy.py` — new adversarial suite (24 tests).
- `backend/tests/test_source_hardening.py` — new adversarial suite.
- `backend/tests/test_source_registry_api.py` — mismatch/unknown-key/scheduler-meta tests +
  allowlist wiring for the secret-free-response test.
- `backend/tests/test_source_adapters.py` — allowlist wiring for existing auth tests.

No existing tests were weakened or deleted; the one pre-existing assertion that a
request URL still contains `api_key=...` remains green (transport input is intentionally
not redacted).

## 5. Security findings (documented, not code-fixed)

- **Raw payload storage**: records are stored normalized; the original payload is not
  retained (a deviation from the earlier design note). Fine for matching, weaker for
  later re-parsing; use backups/`source_runs` for audit.
- **Scraping terms**: `robots`/ToS are not enforced by the transport; operators are
  responsible for the sources they register.
- **Literal secrets under arbitrary config keys**: `sanitize_config` masks keys that
  *look* secret-bearing and now drops unknown `auth` keys, but an operator could still
  store a literal secret under an innocently-named config key (e.g. `headers` at top
  level) and it would persist and round-trip. This is an operator-trust boundary, not an
  external attack path; the credential path itself is locked down via the allowlist.
- **`env_ref` names are returned**: the UI can read which variable a source references
  (a name, never a value). Acceptable for editing; if internal env naming is sensitive,
  restrict who can view `/api/v1/sources`.

## 6. Remaining before production (not verifiable without live sites)

1. One end-to-end run against a real, approved feed per adapter (RSS, JSON, HTML,
   Playwright) to confirm selectors/field maps and browser rendering outside fakes.
   **Partially done:** the HTML-listing adapter now has a real, controlled run against
   three approved portals (§7.2). RSS, JSON and Playwright still have no live run.
2. Confirm the pinned transport against a real TLS host (SNI/cert chain, redirect +
   `Retry-After`) — logic is unit-tested but never dialed for real here.
3. Deploy with an explicit `SOURCE_ALLOWED_SECRET_ENVS` (at least the names each
   approved source needs) and an explicit `SOURCE_ALLOWED_HOSTS`; keep both empty only
   in development.
4. Keep `SOURCE_SCHEDULER_ENABLED` off until a run-monitoring/alerts story exists;
   the new `ERROR` audit rows make failures visible but nothing pages on them yet.

### 6.1 Live-source readiness — exact procedure (Priority 3)

No live source was validated in this review. To validate one **authorized** real source
per adapter (operator-supplied public URL that permits automated collection), the exact
procedure is:

**Preparation (once, per environment).** In the backend `.env`:
- `SOURCE_ALLOWED_HOSTS=` the real feed host (or leave empty to allow any public host;
  private/reserved space is still blocked),
- `SOURCE_ALLOWED_SECRET_ENVS=` the exact name(s) of any env var an approved feed
  needs (e.g. `TENDER_FEED_TOKEN`), and set that variable in the same env.

**Per adapter (operator already has the authorized URL + field mapping):**

1. **RSS/Atom** — config: `{"url": "<authorized feed URL>"}` (optional `max_records`,
   `timeout_seconds`). Create + smoke test through the API, then one preview sync:
   ```bash
   curl -s http://localhost:8000/api/v1/sources \
     -H 'content-type: application/json' \
     -d '{"source_id":"rss-live","name":"RSS live","source_type":"rss",
          "config":{"url":"<authorized feed URL>","max_records":50}}'
   curl -s http://localhost:8000/api/v1/sources/rss-live/test
   curl -s http://localhost:8000/api/v1/sources/rss-live/sync
   ```
   Stop if `BLOCKED` (403/429) — never bypass.
2. **JSON API** — same, with `config.url`, `records_path`, `field_map`, and optional
   `auth` (`{"type":"bearer|header|query","env_ref":"TENDER_FEED_TOKEN", ...}`) using an
   allowlisted variable.
3. **HTML listing** — config requires `url`, `row_selector` (CSS), `field_map` mapping
   `RawBidRecord` fields (e.g. `title`, `closing_date`, `organisation`,
   `scope_of_work`, `source_url`); a row must yield a `title` to survive.
4. **Browser-rendered listing** — same selectors as (3); requires the page to
   genuinely need JavaScript, and Playwright installed.

**Acceptance for a live run:** `test` ok AND `sync` returns `SUCCESS`/`PARTIAL`/`NEEDS_ATTENTION`
with `inserted > 0`; the bid appears in the dashboard; `runs/<id>` shows clean non-secret
errors; a duplicate second `sync` reports `duplicates >= inserted` (idempotence) and
`updated == 0` unless content changed.

**Separation of evidence:** automated results (this suite, fakes/network-isolated) are
reported in §3. A live result must be recorded separately with the source id, the
authorized URL's host, status JSON, and run id from a real `sync` — none of that exists
yet, so no live-site success is claimed anywhere in this document.

_Sections 1–6 above are limited to test/static verification; no live tender site was
contacted for that review. The separate 30-portal onboarding verification and the
controlled 3-portal live batch test are reported in §7._

---

## 7. State/UT portal onboarding (30-portal inventory)

### 7.1 URL verification (against authoritative sources)

The operator-supplied candidate URLs were checked against official/national
procurement sources (NIC eProcurement / GePNIC listings, CPPP `eprocure.gov.in`,
state finance/procurement pages). **24 of 30 candidates were correct as given; 6 were
wrong** (did not resolve, or resolved to a non-canonical/look-alike host). Corrected
canonical URLs are marked **(corrected)**.

| # | State / UT | Verified URL | Platform | Note |
| --- | --- | --- | --- | --- |
| 1 | Andhra Pradesh | `https://apeprocurement.gov.in` | custom | landing public; tender subdomain `tender.apeprocurement.gov.in` is login-gated |
| 2 | Arunachal Pradesh | `https://arunachaltenders.gov.in/nicgep/app` | NIC GePNIC | |
| 3 | Assam | `https://assamtenders.gov.in/nicgep/app` | NIC GePNIC | |
| 4 | Bihar | `https://eproc2.bihar.gov.in` **(corrected)** | eProc 2.0 / mjunction | candidate `eproc.bihar.gov.in` did not resolve |
| 5 | Chhattisgarh | `https://cgeproc.cgstate.gov.in/nicgep/app` **(corrected)** | NIC GePNIC | candidate `cgtenders.gov.in` did not resolve |
| 6 | Delhi (NCT) | `https://govtprocurement.delhi.gov.in` | custom | root returns a 165-byte JS shell → JS-rendered |
| 7 | Goa | `https://eprocure.goa.gov.in/nicgep/app` **(corrected)** | NIC GePNIC | candidate `goaenivida.gov.in` did not resolve |
| 8 | Gujarat | `https://www.nprocure.com` | nProcure ((n)Code / GIL) | **policy-sensitive**: non-`gov.in`, PSU-operated platform |
| 9 | Haryana | `https://etenders.hry.nic.in/nicgep/app` | NIC | |
| 10 | Himachal Pradesh | `https://hptenders.gov.in/nicgep/app` | NIC GePNIC | |
| 11 | Jammu & Kashmir | `https://jktenders.gov.in/nicgep/app` | NIC GePNIC | |
| 12 | Jharkhand | `https://jharkhandtenders.gov.in/nicgep/app` | NIC GePNIC | |
| 13 | Karnataka | `https://eproc.karnataka.gov.in` | CeG KPPP | list `.seam` is JSF/AJAX (no plain HTML rows) → needs browser |
| 14 | Kerala | `https://etenders.kerala.gov.in/nicgep/app` | NIC GePNIC | |
| 15 | Madhya Pradesh | `https://mptenders.gov.in/nicgep/app` | NIC GePNIC | |
| 16 | Maharashtra | `https://mahatenders.gov.in/nicgep/app` | NIC GePNIC | **batch-tested** (§7.8) |
| 17 | Manipur | `https://manipurtenders.gov.in/nicgep/app` | NIC GePNIC | |
| 18 | Meghalaya | `https://meghalayatenders.gov.in/nicgep/app` | NIC GePNIC | |
| 19 | Mizoram | `https://mizoramtenders.gov.in/nicgep/app` | NIC GePNIC | |
| 20 | Nagaland | `https://nagalandtenders.gov.in/nicgep/app` | NIC GePNIC | |
| 21 | Odisha | `https://tendersodisha.gov.in/nicgep/app` | NIC GePNIC | **batch-tested** (§7.2) |
| 22 | Punjab | `https://eproc.punjab.gov.in/nicgep/app` | NIC GePNIC | |
| 23 | Rajasthan | `https://eproc.rajasthan.gov.in/nicgep/app` | NIC GePNIC | |
| 24 | Sikkim | `https://sikkimtender.gov.in/nicgep/app` **(corrected)** | NIC GePNIC | candidate `sikkimtenders.gov.in` (plural) did not resolve |
| 25 | Tamil Nadu | `https://tntenders.gov.in/nicgep/app` | NIC GePNIC | **batch-tested** (§7.2) |
| 26 | Telangana | `https://eprocurement.telangana.gov.in` **(corrected)** | Vupadhi (custom) | candidate `tenders.telangana.gov.in` did not resolve; JS + registration |
| 27 | Tripura | `https://tripuratenders.gov.in/nicgep/app` | NIC GePNIC | |
| 28 | Uttar Pradesh | `https://etender.up.nic.in/nicgep/app` | NIC GePNIC | |
| 29 | Uttarakhand | `https://uktenders.gov.in/nicgep/app` **(corrected)** | NIC GePNIC | candidate `uketenders.gov.in` did not resolve |
| 30 | West Bengal | `https://wbtenders.gov.in/nicgep/app` | NIC GePNIC | **batch-tested** (§7.2) |

Platform summary: **24 NIC GePNIC** (the near-identical `/nicgep/app` stack), plus
Andhra Pradesh (custom), Bihar (eProc 2.0/mjunction), Delhi (custom JS shell),
Gujarat (nProcure), Karnataka (CeG JSF/AJAX) and Telangana (Vupadhi).

### 7.2 Controlled live batch test (Odisha, Tamil Nadu, West Bengal)

Three distinct-state NIC GePNIC portals were selected because each exposes a **public,
server-rendered** listing table on its home page (`table#activeTenders`, no CAPTCHA,
no login). They were driven through the **real** code path — `get_adapter`,
`adapter.test_connection`, `run_source_sync`, `get_dashboard_summary` — with
`SOURCE_ALLOWED_HOSTS=tendersodisha.gov.in,tntenders.gov.in,wbtenders.gov.in` set in the
process env and `DATABASE_URL` pointed at a scratch SQLite file. `dev.db` and the
production env files were not touched; `SOURCE_SCHEDULER_ENABLED` stayed `false`.

Config used per source: `row_selector="table#activeTenders tr"`,
`field_map={title: "td:nth-of-type(1)", bid_number: "td:nth-of-type(2)",
closing_date: "td:nth-of-type(3)", source_url: "td:nth-of-type(1) a@href"}`,
`max_records=5`, `max_pages=1`, `timeout_seconds=20`.

| Source | Test connection | Sync #1 | Sync #2 (idempotence) |
| --- | --- | --- | --- |
| Odisha `tendersodisha.gov.in` | ok, HTTP 200, 10 rows matched | 3 inserted | 0 inserted, 3 duplicates |
| Tamil Nadu `tntenders.gov.in` | ok, HTTP 200, 10 rows matched | 2 inserted | 0 inserted, 2 duplicates |
| West Bengal `wbtenders.gov.in` | ok, HTTP 200, 10 rows matched | 4 inserted | 0 inserted, 4 duplicates |

Aggregate after both syncs (scratch DB): **9 bids persisted**, **9 analysed / 9 scored**
by the intelligence pipeline, dashboard `metrics.total_bids == 9`,
`closing_soon_bids == 3`, recent-bids list populated. Second sync inserted nothing and
reported every record as a duplicate — the identity/`content_hash` dedupe is idempotent
on real data. No run error contained an `env_ref` or any secret; the only recorded
issues were legitimate dedupe notes.

Real data sample (verbatim from the run, not synthetic):
- Odisha — *"Repair and maintenance of left parallel road from OERC to Hatiasuni"*,
  ref `e-TCN-NO-25-OF-2026-2027`, closing `2026-10-16 14:00`.
- Tamil Nadu — *"Providing Distribution pipeline at Kalaingar nagar …"*,
  ref `Panchayat General Fund Siruvanthadu / 2026-2027`, closing `2026-10-29 15:00`.
- West Bengal — *"NIT No- 682/PWD/ROAD/BMC (2ND Call) …"*, closing `2026-10-28 15:00`.

**Finding — GePNIC "Reference No" is not row-unique.** Within one home-page table some
organisations re-use the same reference number across multiple rows (e.g. Odisha rows
sharing `RWD Ctc-14/2026-27`; Tamil Nadu's `Panchayat General Fund …` group). Because
identity dedupe keys on `bid_number`/`gem_bid_id`, those distinct rows collapse to one
within a run — TN's 5 visible rows reduced to 2 unique. This is correct *dedupe*
behaviour but means `bid_number` is a lossy identity for these portals; a per-row unique
key (the session-tokenized `DirectLink`, or title+ref) would preserve them. Recorded, not
changed.

**Finding — product matches are 0 in the batch.** The scratch DB had no product catalog,
so the 11-product matching engine had nothing to match (`BidProductMatch == 0`). Scoring
still ran (9 `BidScore` rows). This is expected for the isolated test and does **not**
indicate a matching defect. The same 9 records were later re-run **against the real
11-product catalog** on a fresh scratch DB — see §9.

### 7.3 GePNIC accessibility constraints (why not all 24)

Only the **home-page** `#activeTenders` table is publicly collectable. The deeper
tender-level pages were probed and are gated:
- `FrontEndLatestActiveTenders`, `FrontEndTendersInArchive`, `WebTenderStatusLists` —
  **CAPTCHA-gated**.
- `FrontEndTendersByOrganisation` — public but returns organisation names + counts only,
  no per-tender rows.
- `service=direct&sp=…` direct links are **session-bound** (redirect to a "clear
  session" page), so they cannot be deep-linked for records.

The remaining portals are blocked for automated collection without registration/DSC or a
JS-rendered page: Andhra Pradesh (`tender.apeprocurement.gov.in` → 721-byte login
redirect), Delhi (JS shell), Telangana (custom JS + registration), Karnataka
(JSF/AJAX listing). These are **documented as gated, not bypassed**.

### 7.4 Allowlist entries (documented, not applied)

Three controlled multi-portal live batches (§7.2, §7.5, §7.6) plus two controlled
single-portal verifications (§7.7, §7.8) have now exercised **eleven** distinct-state NIC
GePNIC portals. The hosts verified to work through the real code path:

```
SOURCE_ALLOWED_HOSTS=tendersodisha.gov.in,tntenders.gov.in,wbtenders.gov.in,etenders.kerala.gov.in,hptenders.gov.in,eproc.rajasthan.gov.in,arunachaltenders.gov.in,assamtenders.gov.in,etenders.hry.nic.in,eproc.punjab.gov.in,mahatenders.gov.in
```

Kerala, Himachal Pradesh and Rajasthan were added after the second batch (§7.5); Arunachal
Pradesh, Assam and Haryana after the third (§7.6); Punjab after the fourth (§7.7);
Maharashtra after the fifth (§7.8). The
remaining NIC GePNIC portals are
strong candidates because they share the same platform
and (untested) home-page structure, but **each must be verified individually** before
adding its host — never a wildcard, per the task constraints. No wildcard host and no
third-party subresource host was added; `SOURCE_ALLOWED_SECRET_ENVS` remains empty (no
approved source needs a secret). These values are **documented only** — no production
`.env` was modified.

### 7.5 Controlled live batch #2 (Kerala, Himachal Pradesh, Rajasthan) — Priority 3

Same method as §7.2 (real `get_adapter` → `validate_config` → `test_connection` →
`run_source_sync` ×2, scratch SQLite, `SOURCE_ALLOWED_HOSTS` set in-process,
`SOURCE_SCHEDULER_ENABLED=false`, `dev.db`/prod env untouched). Config identical except
`max_records=10`. All three return HTTP 200 with a public, server-rendered
`table#activeTenders` (no CAPTCHA, no login). An independent census parsed the live page
separately from the runner to count **distinct tenders** = distinct `(Reference No, title)`
pairs.

| Portal | Rows | Distinct refs | Distinct tenders (census) | Default sync #1 | Default sync #2 | Opt-in composite sync #1 |
| --- | --- | --- | --- | --- | --- | --- |
| Kerala `etenders.kerala.gov.in` | 10 | 10 | 10 | 10 inserted | 0 inserted, 10 duplicates | 10 discovered |
| Himachal `hptenders.gov.in` | 10 | 7 | 10 | 7 inserted | 0 inserted, 7 duplicates | 10 discovered |
| Rajasthan `eproc.rajasthan.gov.in` | 10 | 1 | 10 | 1 inserted | 0 inserted, 1 duplicate | 10 discovered |

**Findings.**
1. **Idempotence holds** on all three: sync #2 inserted 0 and reported every record as a
   duplicate (Kerala 10/10, HP 7/7, Rajasthan 1/1). First insert run `SUCCESS`, dedupe/
   update run `NEEDS_ATTENTION` — expected.
2. **The Reference-No identity problem is systemic and worse than §7.2 showed.**
   Rajasthan's entire home page (10 distinct tenders) shares **one** Reference No, so the
    default pipeline collects just **1 of 10**; Himachal collapses 10 rows to **7**. The
    independent census proves 10 distinct tenders exist in both. Same root cause fixed
    behind the opt-in flag in §8 — the opt-in composite run discovered all 10 in each case
    (Rajasthan recovered 9 lost tenders, HP recovered 3).
 3. **Tender-level pages remain gated.** `FrontEndLatestActiveTenders` and
    `WebTenderStatusLists` return HTTP 200 but contain a CAPTCHA on both Kerala and
    Rajasthan (re-confirming §7.3); only the home-page table is collectable.

### 7.6 Controlled live batch #3 (Arunachal Pradesh, Assam, Haryana) — Priority 3

A third controlled batch was **started** against the next three verified NIC GePNIC hosts
(`arunachaltenders.gov.in`, `assamtenders.gov.in`, `etenders.hry.nic.in`). The run
completed the collection and matching stages and persisted them to a scratch SQLite DB
(6 `data_sources`, 9 `source_runs`, 12 bids, 12 `bid_analysis`, 12 `bid_score`, 11 real
products), but was **interrupted before it could run the gated-endpoint probe, read the
dashboard and write `p4_report.json`**. It was **resumed against the same scratch DB
without re-collecting**; per-run counters were reconstructed from the `source_runs` audit
rows, `test_connection` was re-checked live at resume time, and the missing gated probe +
dashboard + report write were completed.

| Portal | Test connection | Default sync #1 | Default sync #2 | Opt-in composite |
| --- | --- | --- | --- | --- |
| Arunachal `arunachaltenders.gov.in` | HTTP 200, 2 rows matched | 2 inserted | 0 inserted, 2 duplicates | 0 ins, 2 dup (updated) |
| Assam `assamtenders.gov.in` | HTTP 200, 10 rows matched | 5 inserted | 0 inserted, 5 duplicates | 0 ins, 5 dup (updated) |
| Haryana `etenders.hry.nic.in` | HTTP 200, 10 rows matched | 5 inserted | 0 inserted, 5 duplicates | 0 ins, 5 dup (updated) |

**Findings.**
1. **Idempotence holds** on all three: the second default sync inserted 0 and reported
   every record as a duplicate (Arunachal 2/2, Assam 5/5, Haryana 5/5).
2. **No default-identity loss in this batch.** Unlike Rajasthan (10→1) and Himachal
   (10→7), the five visible rows on each of these home pages had distinct Reference Nos,
   so the default pipeline captured every distinct tender (Arunachal 2, Assam 5,
   Haryana 5 = **12 persisted**). The opt-in composite run re-identified the same rows
   (0 new inserts), confirming it is a no-op when the default identity is already unique.
3. **All 12 records evaluated against the real 11-product catalog; 0 matches** — the
   records are construction / road-maintenance / flood-material / civic tenders with zero
   cybersecurity signal tokens, so `NO_MATCH` under the evidence gate is correct, not a
   defect. 12 `BidAnalysis` + 12 `BidScore` rows persisted; dashboard `total_bids=12`,
   `analyzed_bids=12`, `closing_soon_bids=3`.
4. **Tender-level pages remain gated.** `FrontEndLatestActiveTenders` returned HTTP 200
   with a CAPTCHA on all three hosts (re-confirming §7.3); only the home-page
   `#activeTenders` table is collectable.
5. **No run error contained an `env_ref` or any secret**; the only recorded issues were
   legitimate dedupe notes.

The controlled live evidence directory now holds `p4_report.json` alongside the earlier
`batch_report.json`, `p2_report.json` and `p3_report.json`. This batch raises the number of
individually verified NIC GePNIC hostnames from **six to nine**.

### 7.7 Controlled single-portal batch #4 (Punjab) — Priority 3

Punjab (`eproc.punjab.gov.in`) is the next individually-unverified NIC GePNIC portal. Access
was probed first with a **single** controlled request (`punjab_probe.py`) before any
collection; only then was the portal run through the real adapter pipeline.

**Probe (1 request).** HTTP 200, server-rendered public `table#activeTenders`, **no CAPTCHA**.
The home-page table has **four** columns — `td1` title (ordinal + anchor), `td2` Reference
No, `td3` Published, `td4` Closing — with dates in the `dd-Mon-yyyy hh:mm AM/PM` shape
(e.g. `21-Oct-2026 02:00 PM`), which the existing normalizer parses via `%d-%b-%Y %I:%M %p`.
The field map was adapted to the observed layout (`published_date = td:nth-of-type(3)`,
`closing_date = td:nth-of-type(4)`).

**Run** (`punjab_batch_test.py`, scratch SQLite, `SOURCE_SCHEDULER_ENABLED=false`,
`SOURCE_ALLOWED_HOSTS=eproc.punjab.gov.in` in-process only, home page only, max 5 records):

| Stage | Result |
| --- | --- |
| Test connection | HTTP 200, 10 rows matched |
| Default sync #1 | 3 discovered, 3 inserted (5 rows → 3 unique; 2 in-run repeats noted) |
| Default sync #2 | 0 inserted, 3 duplicates — **idempotent** |
| Opt-in composite (`bid_number`+`title`) | 5 discovered, 2 inserted, 3 duplicates, 3 updated |
| Gated probe (`FrontEndLatestActiveTenders`) | HTTP 200 + CAPTCHA — gated, not bypassed |
| Real 11-product catalog | 11 products, all active; 11 evaluated per bid; **0 matches** |
| Dashboard | `total_bids=5`, `analyzed_bids=5`, `closing_soon_bids=0` |

**Findings.**
1. **The Reference-No collision recurs on Punjab**, independent of the §7.5 states. The
   home page contains a row group sharing Reference No `8128/28A`; keying on `bid_number`
   collapsed the 5 visible rows to **3**. The opt-in composite identity recovered the full
   set (5 distinct: 2 inserted + 3 updated) — the §8 identity fix generalises.
2. **Idempotence holds**: the second default sync inserted 0 and reported every record as a
   duplicate.
3. **0 product matches** — the records are construction / canal-regulation-hut / vehicle-
   hire / electrical-substation civil works, carrying zero cybersecurity signal tokens;
   `NO_MATCH` under the evidence gate is correct. 5 `BidAnalysis` + 5 `BidScore` rows
   persisted.
4. **Tender-level pages remain gated** (`FrontEndLatestActiveTenders` → HTTP 200 + CAPTCHA),
   re-confirming §7.3; only the home-page table is collectable.
5. **No run error contained an `env_ref` or any secret.**

This raises the number of individually verified NIC GePNIC hostnames from **nine to ten**
(§7.4).

### 7.8 Controlled single-portal batch #5 (Maharashtra) — Priority 3

Maharashtra (`mahatenders.gov.in`) is the next individually-unverified NIC GePNIC portal.
Access was probed with a **single** controlled request before any collection; the public
home page carries a `table#activeTenders` with **four** columns (title / Reference No /
Published / Closing) and `dd-Mon-yyyy hh:mm AM/PM` dates — the same layout as Punjab.
A second **single** read-only request (`maharashtra_census.py`) censused the full visible
listing for Reference-No collisions.

**Run** (`maharashtra_batch_test.py`, scratch SQLite, `SOURCE_SCHEDULER_ENABLED=false`,
`SOURCE_ALLOWED_HOSTS=mahatenders.gov.in` in-process only, home page only, max 5 rows):

| Stage | Result |
| --- | --- |
| Test connection | HTTP 200, 10 rows matched |
| Default sync #1 | 5 discovered, 5 inserted, 0 duplicates — `SUCCESS` |
| Default sync #2 | 0 inserted, 5 duplicates — **idempotent** |
| Opt-in composite (`bid_number`+`title`) | 5 discovered, 0 inserted, 5 duplicates, 5 updated |
| Gated probe (`FrontEndLatestActiveTenders`) | HTTP 200 + CAPTCHA — gated, not bypassed |
| Real 11-product catalog | 11 products, all active; 11 evaluated per bid; **0 matches** |
| Dashboard | `total_bids=5`, `analyzed_bids=5`, `closing_soon_bids=3` |

**Findings.**
1. **No Reference-No collision on Maharashtra.** The census found 10 rows with **10
   distinct Reference Nos and 10 distinct (Reference No, title) pairs** — so the default
   `bid_number` identity does **not** collapse distinct tenders here, unlike Punjab (§7.7)
   and Rajasthan/Himachal (§7.5). The collision is genuinely portal-specific, not a
   GePNIC-wide constant.
2. **Default vs composite counters.** Default sync #1 inserted all 5 collected rows
   (`SUCCESS`, 0 duplicates; no in-run dedupe note). The composite run then **discovered 5,
   inserted 0, counted 5 duplicates and updated 5** — i.e. it recovered nothing, because
   there was nothing lost; it re-identified the same 5 rows in place as `srcid-*`. This is
   the expected no-op shape when default identity is already unique (contrast Punjab, where
   composite inserted +2 and recovered a collision group).
3. **Repeated titles are not collisions.** Rows 5/7/9/10 all read `BEAT NO. 209` but carry
   different Reference Nos, so the composite `(bid_number, title)` key remains unique — a
   title-only identity would have wrongly merged them.
4. **Idempotence holds**: the second default sync inserted 0 and reported every record as a
   duplicate.
5. **0 product matches** — road/drainage/pipe-repair/civic-maintenance tenders with zero
   cybersecurity signal tokens; `NO_MATCH` under the evidence gate is correct. 5
   `BidAnalysis` + 5 `BidScore` rows persisted.
6. **No run error contained an `env_ref` or any secret.**

This raises the number of individually verified NIC GePNIC hostnames from **ten to eleven**
(§7.4).

---

## 8. Tender identity strategy (Priority 1)

**Problem.** GePNIC home-page listings expose no stable, row-unique tender id. The
"Reference No" (`td2`) is frequently **re-used across multiple rows** by the same
organisation, and the per-row anchors are session-tokenized (not stable). Because
`normalize_record` cross-fills `gem_bid_id` from `bid_number` and dedupe keys on
`gem_bid_id`/`bid_number`, **distinct tenders collapse to one** — measured live as 10→1
(Rajasthan), 10→7 (Himachal), 10→2 (Tamil Nadu), 10→3 (Odisha). Silently dropping 90% of
a portal's tenders is a correctness failure, not just a dedupe nuance.

**Investigated alternatives.** `DirectLink` `sp=` token — session-bound, not stable;
`informal_N` row anchors — positional, not stable; a hidden Tender ID — **not present** on
the public home page; deeper listings that do carry ids — CAPTCHA-gated. The only stable
composite available from the public page is **`(Reference No, title)`**.

**Implemented fix — opt-in, default-off.** A new `identity_fields` source-config key lets a
source declare which canonical `RawBidRecord` fields form its composite identity. When
present and valid, the pipeline derives a stable `srcid-<sha1>` identity from those fields
(leading ordinal `"1. "` stripped, case-folded) and uses it for `gem_bid_id`, run dedupe
and duplicate checks. When **absent**, behaviour is **unchanged** (existing
`bid_number`/`gem_bid_id`/`content_hash` path). No production source sets it; no migration
was run.

- `normalizer.py` — `derive_composite_identity(identity_fields, values)` +
  `normalize_record(..., *, identity_fields=None)`.
- `duplicate_detector.py` — `check_duplicate(..., *, use_bid_number_identity=True)` so the
  composite path does not also exact-match the shared `bid_number`.
- `runner.py` — `_source_identity_fields(...)`, `_dedupe_run(..., *, identity_fields=None)`.
- `base.py` — `_validate_identity_fields(...)`; rejects a non-list/empty/unknown field set
  with a safe `SourceConfigError`. (Also corrected a latent `cfg`→`config` typo here.)
- `tests/test_gepnic_identity.py` — 10 tests (unit semantics, default unchanged, real
  Odisha/TN shapes, config validation, idempotence).

**Migration risk (documented, not applied).** Switching a source to composite identity
changes future identity only; already-collapsed rows are not reconstructable, and a
one-time historical re-collect would be required to recover past losses. That is why it
ships **off by default** and no production source was switched.

## 9. Product matching against the real catalog (Priority 2)

Goal: confirm the 11-product matcher behaves correctly and persists results, using the
**real** catalog and the **9 real** records — not synthetic products or forced matches.

**Setup.** Fresh scratch SQLite (`p2_scratch.db`; `dev.db` untouched); seeded the real
catalog via `bootstrap_product_knowledge(db)` (asserted **11** products, all active); the
**9 real** records from the §7.2 batch were copied in; each was evaluated with
`match_bid_against_products` and then persisted with `process_bid_intelligence`.

**Result.**
- Catalog: 11 real products loaded (`SolidityShield, SecureCMS, SecureTrace, CookieHub,
  PQCSuite, SecureX-DID, SecureWatch, AuditExpress, SecurePad, SecureX-ID, QuantumVault`).
- All 9 records were evaluated against all 11 products.
- **Matches: 0.** Every product scored `NO_MATCH` (0.0), with `Matched 0 signal(s)` under
  the evidence gate. This is **correct, not a defect**: the 9 are road/construction,
  toilet-renovation, packaged-food-supply and motor-rewinding tenders carrying **zero**
  cybersecurity signal tokens. No match was forced; no synthetic bid text was injected.
- **Persistence verified:** 9 `BidAnalysis` rows + 9 `BidScore` rows; each analysis's
  `product_matches` JSON holds the full 11-product evaluation.
- The positive path (a bid *with* security evidence **does** match and pass the gate) is
  covered by the repo suites `test_stage1_evidence_gated_matching`, `test_matcher*`,
  `test_intelligence` — **79 passed**.

**Persistence-path note.** `process_bid_intelligence` writes `BidAnalysis.product_matches`
(JSON) + `BidScore`; it does **not** insert `BidProductMatch` rows (that table is written
only by the manual endpoint at `bids.py:103`). So an empty `BidProductMatch` on the batch
path is expected.

## 10. Priority status summary

| Priority | Status | Detail |
| --- | --- | --- |
| P1 — GePNIC identity | Investigated + fixed **opt-in, default-off**, 10 tests | §8 |
| P2 — product matching | Verified vs real catalog; 0 matches (correctly evidence-gated) | §9 |
| P3 — next 3 portals | Kerala / HP / Rajasthan live-tested; idempotent; identity loss quantified | §7.5 |
| P3 — batch #3 | Arunachal / Assam / Haryana live-tested (run resumed after interruption); idempotent; no identity loss; 12 bids, 0 matches | §7.6 |
| P3 — batch #4 | Punjab live-tested (single portal, probe-then-collect); idempotent; Reference-No collision recovered by composite identity; 5 bids, 0 matches | §7.7 |
| P3 — batch #5 | Maharashtra live-tested (single portal, probe + census); idempotent; **no** Reference-No collision (composite no-op); 5 bids, 0 matches | §7.8 |

Unchanged throughout: production identity behaviour, `dev.db`, production `.env`,
`SOURCE_SCHEDULER_ENABLED` (still `false`). Full backend suite: **628 passed**. Batches #3,
#4 and #5 were verification-only — no production code changed, so that suite result stands
unchanged. Eleven NIC GePNIC hostnames are now individually verified (§7.4).


