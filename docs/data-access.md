# Data Access Policy & Ingestion Architecture

## 1. Compliance & Ethical Access Policy
1. **Strictly No Unauthorized Access**: The platform explicitly forbids unauthorized web scraping, CAPTCHA bypassing, rate limit evasion, anti-bot circumvention, credential sharing, or unauthorized automated crawling of the GeM portal.
2. **Source-Agnostic Core**: The entire intelligence platform operates strictly on normalized Pydantic schemas. It functions completely independently of live portal scraping.
3. **Pluggable Architecture**: Data ingestion is strictly abstracted behind the `BidSourceAdapter` interface in `app/services/ingestion/adapters.py`.

---

## 2. Ingestion Adapter Protocol

To connect an approved, authorized live GeM API, licensed data feed, or export pipeline, implement the `BidSourceAdapter` interface:

```python
class ApprovedGeMAdapter:
    adapter_name = "ApprovedGeMAdapter"

    def parse(self, data: bytes, filename: str = "gem_feed.json", **kwargs) -> list[RawBidRecord]:
        """
        Parses structured payloads from official, authorized GeM API or licensed data feeds.
        Converts raw fields via `resolve_field_name` into canonical `RawBidRecord` instances.
        """
        ...
```

### Integration Steps for Live Authorized Feed
1. Register adapter in `ADAPTER_MAP` in `app/services/ingestion/adapters.py`.
2. Configure credentials/API keys securely via environment variables (`.env`).
3. Invoke `run_ingestion_pipeline(db, payload_bytes, file_type="gem_api", source_name="official_gem_feed")`.

---

## 3. Current Ingestion Status

| Ingestion Mode | Implementation | Status |
| :--- | :--- | :--- |
| **JSON Import** | `JSONBidAdapter` | `VERIFIED` |
| **CSV Import** | `CSVBidAdapter` | `VERIFIED` |
| **XLSX Import** | `XLSXBidAdapter` | `VERIFIED` |
| **Firecrawl Public Page Scrape** | `FirecrawlGeMAdapter` | `ONLY EXTERNAL SOURCE / DISABLED BY DEFAULT` |
| **Authorized Live GeM API** | `ApprovedGeMAdapter` | `BLOCKED BY MISSING AUTHORIZED SOURCE ACCESS` |
| **Licensed Provider Feed** | `LicensedProviderAdapter` | `BLOCKED BY MISSING AUTHORIZED SOURCE ACCESS` |

> **Note**: Firecrawl is the single external GeM data-source integration. There is
> no second provider, no provider fallback, and no automatic crawler.

---

## 4. Bid Source Selector

`BID_SOURCE_TYPE` records which configured source is active.
Allowed values: `firecrawl` | `file_import`. Default is `firecrawl`.

The downstream pipeline is **identical** for every source:

```
Firecrawl (public permitted page)
        -> FirecrawlGeMAdapter -> RawBidRecord
        -> Validation      -> Normalization
        -> Deduplication   -> Database
        -> 11-Product Match -> Analysis
        -> Notifications   -> Dashboard
```

Manual file import (`file_import`) reuses the exact same pipeline through the
generic `run_ingestion_pipeline` entry point. When Firecrawl is not configured,
the source reports `NOT_CONFIGURED` — it never falls back to another provider.

---

## 5. Firecrawl Source Adapter (The Only External Source)

### What Firecrawl is — and is not

Firecrawl is a **generic third-party web-scraping API**
(<https://docs.firecrawl.dev/api-reference/endpoint/scrape>). It is:

- **NOT** a GeM API.
- **NOT** affiliated with, endorsed by, or authorized by GeM / NIC.
- **NOT** a substitute for an authorized GeM data feed or a licensed provider.

Using Firecrawl confers **no** permission to collect from GeM or any government
site. Whether automated collection of a particular page is permitted is a
decision for the operator of this application and the owner of the target site.
No such authorization has been established by this project.

### Architecture

```
Public, allowlisted URL
  -> FirecrawlClient.scrape_url()      raw Firecrawl response
  -> FirecrawlGeMAdapter.parse()       canonical RawBidRecord
  -> validate_records()                existing validator
  -> normalize_record()                existing normalizer
  -> check_duplicate()                 existing deduplication
  -> Bid + CollectionRun + RawBidPayload
  -> process_bid_intelligence()        existing 11-product matching / analysis / notifications
  -> existing dashboard
```

Components:

| Component | File |
| :--- | :--- |
| HTTP client | `backend/app/services/ingestion/firecrawl_client.py` |
| Source adapter | `backend/app/services/ingestion/firecrawl_adapter.py` |
| Orchestration | `backend/app/services/ingestion/firecrawl_service.py` |
| API endpoints | `backend/app/api/v1/endpoints/firecrawl.py` |
| UI panel | `frontend/src/components/FirecrawlSourcePanel.tsx` |

The adapter is registered in the existing `ADAPTER_MAP` under the key
`firecrawl`, so it is reachable through the same `get_adapter()` factory as
every other source. No existing abstraction was duplicated.

### API method used

`POST {FIRECRAWL_BASE_URL}/scrape` with `Authorization: Bearer <FIRECRAWL_API_KEY>`,
`formats: [{type: markdown}, {type: links}, {type: json, schema: ...}]`,
`onlyMainContent: true`, `timeout: <ms>`. This is the currently documented
Firecrawl v2 scrape method. No undocumented or private endpoint is contacted.

### Field extraction rules

1. **Structured JSON extraction** — requested with a strict JSON Schema
   (`GEM_BID_EXTRACTION_SCHEMA`) that mirrors the canonical `RawBidRecord`
   field names. Every property is nullable and the prompt instructs the
   extractor to copy only values literally present on the page.
2. **Deterministic label parsing** — only a label literally printed on the page
   can produce a value. Labels are resolved through the existing
   `resolve_field_name` alias map, so Firecrawl uses the same canonical field
   vocabulary as CSV/JSON/XLSX.
3. **Title fallback chain** — structured value → label → first markdown heading
   → Firecrawl `metadata.title`.
4. **Provenance** — the page's actual URL (`metadata.sourceURL` / `metadata.url`)
   is stored in `source_url`; Firecrawl metadata, links, document links, the
   extracted JSON and a truncated markdown excerpt are stored in the
   `RawBidPayload` audit record.

Anything not present on the page is left `None`. No bid id, date, value,
organisation, category, eligibility clause or URL is ever invented. Fields
with no canonical mapping (for example a printed "Bid Opening Date") are
dropped rather than forced into an unrelated field.

### Configuration (backend environment only)

| Variable | Default | Purpose |
| :--- | :--- | :--- |
| `FIRECRAWL_ENABLED` | `false` | Master switch for the source |
| `FIRECRAWL_API_KEY` | *(unset)* | Firecrawl API key (backend only) |
| `FIRECRAWL_BASE_URL` | `https://api.firecrawl.dev/v2` | API base |
| `FIRECRAWL_TIMEOUT_SECONDS` | `90` | Backend HTTP timeout |
| `FIRECRAWL_SCRAPE_TIMEOUT_MS` | `60000` | Page-level timeout (documented range 1000–300000) |
| `FIRECRAWL_MAX_RETRIES` | `3` | Bounded retries with backoff |
| `FIRECRAWL_REQUEST_INTERVAL_SECONDS` | `2.0` | Delay between URL requests |
| `FIRECRAWL_MAX_CONCURRENCY` | `1` | Simultaneous scrapes (clamped 1–4) |
| `FIRECRAWL_MAX_URLS_PER_RUN` | `20` | Hard URL budget per run |
| `FIRECRAWL_MAX_DETAIL_LINKS` | `20` | Listing-page link budget |
| `FIRECRAWL_ALLOWED_HOSTS` | `gem.gov.in` | Host allowlist enforced before any request |
| `FIRECRAWL_APPROVED_URLS` | *(unset)* | Explicit operator-approved URL list |
| `FIRECRAWL_STRUCTURED_EXTRACTION` | `true` | Request Firecrawl JSON extraction |
| `FIRECRAWL_SCHEDULER_ENABLED` | `false` | Reserved; **no scheduler is implemented** |

### Secret handling

The API key exists only in backend environment configuration. It never appears
in React/TypeScript, never enters the database, never appears in an API
response, and is never logged. `FirecrawlClient.status()` returns only a masked
fragment via `mask_api_key()`.

### Compliance guardrails

The integration enforces the platform's existing access policy mechanically:

- Only URLs explicitly supplied by the operator (or listed in
  `FIRECRAWL_APPROVED_URLS`) are processed. The GeM domain is never crawled.
- Every URL must pass the host allowlist before any network request is made; a
  rejected URL never reaches `requests`.
- Only `http`/`https` absolute URLs are accepted.
- Listing-page discovery is depth-limited to one level, capped by
  `FIRECRAWL_MAX_DETAIL_LINKS` and `FIRECRAWL_MAX_URLS_PER_RUN`.
- Request rate is throttled and concurrency defaults to a single worker.
- **No CAPTCHA, login, session, rate limit or other access control is bypassed,
  solved, evaded or worked around at any point.**
- No undocumented or private endpoint is probed.

### Operational limitations

- **No automated scheduler.** Firecrawl scrapes are manual only. Scheduled
  scraping is intentionally not implemented until a manual scrape has proven
  the pipeline end to end.
- **Listing-page link selection is heuristic.** Detail links are selected from
  the links Firecrawl actually returned, filtered by allowlisted host and an
  optional operator-supplied keyword. No GeM URL pattern is guessed.
- **Field reliability is page-dependent.** Fields that a given public page does
  not print are reported as `null`, not guessed. The scrape response includes
  an `extracted_fields` / `missing_fields` report so reliability can be
  inspected per page.
- **Field extraction has not been validated against live GeM pages** in this
  repository. See the project report for the current acceptance status.

