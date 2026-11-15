from pathlib import Path
from typing import List, Optional, Tuple, Union
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Directory containing the `app` package (i.e. <repo>/backend).
_BACKEND_DIR = Path(__file__).resolve().parents[2]
_REPO_ROOT = _BACKEND_DIR.parent


def _resolve_env_files() -> Tuple[str, ...]:
    """
    Build the ordered list of .env files to load.

    A bare ``env_file=".env"`` is resolved relative to the *current working
    directory*, so running the backend from ``backend/`` (uvicorn, pytest,
    alembic) never sees the repository-root ``.env`` that actually holds the
    deployment configuration -- including data-source credentials.  Resolve the
    paths against the package location instead so configuration loads the same
    way from any working directory.

    Later entries take precedence, so a deployment-specific
    ``backend/.env`` overrides the shared repository-root ``.env``.
    """
    candidates = (_REPO_ROOT / ".env", _BACKEND_DIR / ".env")
    found = tuple(str(p) for p in candidates if p.is_file())
    return found or (".env",)


class Settings(BaseSettings):
    PROJECT_NAME: str = "SecuredApp GeM Bid Intelligence Platform"
    API_V1_STR: str = "/api/v1"
    ENVIRONMENT: str = "development"
    LOG_LEVEL: str = "INFO"
    SECRET_KEY: str = "dev_secret_key_securedapp_gem_bid_intelligence_2026_key"

    # ------------------------------------------------------------------
    # Authentication (Task A)
    # ------------------------------------------------------------------
    # JWT algorithm and token lifetimes. Access tokens are short-lived;
    # refresh tokens are longer-lived and are used only to obtain new
    # access tokens.
    AUTH_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # When True, all endpoints protected by require_auth / require_admin
    # / require_operator reject unauthenticated requests with 401. Defaults
    # to False for backward compatibility with existing unauthenticated
    # callers; production deployments MUST set this to True.
    AUTH_REQUIRED: bool = False

    # Brute-force protection (Task A).
    LOGIN_MAX_ATTEMPTS: int = 5
    LOGIN_LOCKOUT_MINUTES: int = 15

    # Rate limiting (Task E).
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_REQUESTS_PER_MINUTE: int = 60
    RATE_LIMIT_BURST: int = 10

    # Database URLs
    DATABASE_URL: str = "sqlite:///./dev.db"
    TEST_DATABASE_URL: str = "sqlite:///./test.db"

    # CORS
    BACKEND_CORS_ORIGINS: List[str] = [
        "http://localhost:3000",
        "http://localhost:5173",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:5173",
    ]

    # -------------------------------------------------------------------------
    # Bid Source Selector
    # Only selects the manual file-import adapter. The live GeM data source is
    # the Direct GeM Public Collector, which does not read this setting.
    # Allowed values: file_import
    # The downstream pipeline (validation -> normalization -> dedup -> DB ->
    # 11-product matching -> analysis -> notifications -> dashboard) is identical
    # for every value.
    # -------------------------------------------------------------------------
    BID_SOURCE_TYPE: str = "file_import"



    # Direct GeM Public Collector
    GEM_DIRECT_ENABLED: bool = True
    GEM_DIRECT_ALLOWED_HOSTS: str = "gem.gov.in,bidplus.gem.gov.in"
    GEM_DIRECT_APPROVED_URLS: Union[str, None] = None
    GEM_DIRECT_MAX_URLS_PER_RUN: int = 10
    GEM_DIRECT_REQUEST_INTERVAL_SECONDS: float = 3.0
    GEM_DIRECT_MAX_CONCURRENCY: int = 1
    GEM_DIRECT_TIMEOUT_SECONDS: int = 60
    GEM_DIRECT_MAX_RETRIES: int = 2
    # The public bid listing renders its rows with JavaScript, so a browser is
    # genuinely required for it. This flag only permits that render; it does not
    # change any access rights and no evasion is applied.
    GEM_DIRECT_USE_PLAYWRIGHT: bool = True
    # Automatic scheduled collection. One background thread starts with the
    # backend (app.main lifespan) and runs the existing direct collector once
    # per interval: bounded by GEM_DIRECT_MAX_PAGES, never overlapping a
    # manual fetch, one attempt per tick (no retry storms).
    GEM_DIRECT_SCHEDULER_ENABLED: bool = True
    GEM_DIRECT_SCHEDULER_INTERVAL_MINUTES: int = 20
    GEM_DIRECT_USER_AGENT: str = "SecuredApp-GeM-Intelligence/1.0"

    # ------------------------------------------------------------------
    # Direct GeM collector: coverage (pagination) settings
    #
    # The public "All Bids" listing is a JavaScript shell. It POSTs to
    # https://bidplus.gem.gov.in/all-bids-data with {"page": n, ...} and
    # renders GEM_PAGE_SIZE cards per page, printing
    # "Showing X - Y records of Z records" plus a #light-pagination widget
    # whose last numbered link is the final page. The collector walks those
    # real pages instead of reading page 1 only.
    # ------------------------------------------------------------------
    # Walk beyond page 1. Disabling this collects exactly one page.
    GEM_DIRECT_PAGINATE: bool = True
    # Explicit, configurable operational safety limit on listing pages per
    # run. 0 disables the limit (walk until GeM runs out of pages). This is a
    # pacing/runtime guard only: it never reduces the per-page result set, and
    # a run that stops on it reports limit_reached=True so truncation is never
    # silent.
    #
    # Default 250 pages = 2,500 bids at GeM's 10 rows per page. That is a real
    # working population rather than a demo, and combined with the default
    # Bid-Start-Date-Latest sort it collects the bids that started most recently,
    # which is the newest end of the listing. At the configured 3s pacing
    # this is roughly 13 minutes of requests. A full walk of the 4,365-page
    # ongoing listing is never attempted by default.
    GEM_DIRECT_MAX_PAGES: int = 250
    # Optional cap on total rows carried forward in one run. 0 = no cap.
    GEM_DIRECT_MAX_BIDS_PER_RUN: int = 0
    # Time allowed for a single page's data request to settle (ms).
    GEM_DIRECT_PAGE_SETTLE_MS: int = 45000
    # How many consecutive page failures abort pagination instead of just
    # being recorded and skipped.
    GEM_DIRECT_MAX_CONSECUTIVE_PAGE_FAILURES: int = 3
    # How many consecutive listing pages may render the *same* bid IDs as the
    # page before them before pagination reports no_new_ids. This detects a
    # listing whose pagination has genuinely stopped advancing. It deliberately
    # does NOT trigger on pages that merely re-show records already collected
    # earlier in the run: the listing is live (new bids are prepended, older
    # ones close), so offsets drift under a walk and such overlap is expected.
    # Each repeated page is still counted and reported. 1 restores "any two
    # identical consecutive pages end the walk".
    GEM_DIRECT_MAX_REPEATED_PAGES: int = 3
    # How many times a single listing page read is retried when the data request
    # lands but the listing has not repainted its cards yet (or briefly shows a
    # previous page). GeM repaints asynchronously, so an empty snapshot on its
    # own is not proof that the result set ended; the walk only concludes
    # ``no_rows`` once the pagination widget also advertises no further page.
    GEM_DIRECT_PAGE_READ_RETRIES: int = 2
    # Overlap-resume for the durable batch runner
    # (scripts/gem_full_collect_resumable.py). Each batch restarts this many
    # pages *before* the checkpoint's next_page so that bids which drifted down
    # past the checkpoint while the previous batch ran are re-read rather than
    # skipped. Re-read rows are deduplicated/updated by the existing upsert, and
    # the checkpoint still only ever advances forward. 0 resumes exactly at
    # next_page. Capped below the batch size so a batch always makes progress.
    GEM_COLLECT_OVERLAP_PAGES: int = 5

    # Automatic checkpoint resume for the direct GeM collector.
    # When enabled and no explicit start_page is supplied, the collector
    # resumes from the last successfully completed page recorded in the
    # most recent CollectionRun notes. Disabled by default so manual runs
    # always start from page 1 unless the caller opts in.
    GEM_DIRECT_AUTO_RESUME: bool = False

    # Scheduler stop timeout in seconds. How long stop() waits for an
    # in-progress collection to finish before returning. Long-running
    # collections (e.g. 250 pages at 3s/page = 750s) need more than the
    # default 15s. The thread is daemon, so the process will still exit,
    # but a longer timeout allows graceful completion.
    GEM_DIRECT_SCHEDULER_STOP_TIMEOUT: float = 60.0
    # Scope of the public listing, exactly as GeM's own tabs define it:
    # ongoing_bids | bidrastatus | cancelled_bids
    GEM_DIRECT_BID_STATUS_TYPE: str = "ongoing_bids"
    # GeM's own listing sort options, passed verbatim to the page's own
    # sort() function. The required production order is Bid Start Date: Latest
    # First, whose exact portal id is ``Bid-Start-Date-Latest`` (verified
    # against the live all-bids markup:
    #   <a id="Bid-Start-Date-Latest" onclick="sort(`Bid-Start-Date-Latest`)">
    #     Bid Start Date: Latest First</a>).
    # The other portal ids are Bid-Start-Date-Oldest, Bid-End-Date-Latest and
    # Bid-End-Date-Oldest. No id is invented here.
    GEM_DIRECT_SORT_ORDER: str = "Bid-Start-Date-Latest"
    # GeM's own bid-kind scope, set through the listing's public filter state
    # exactly as the site's Advance Search box does. Measured live:
    #   all      -> 43,664 ongoing records (4,365 pages)
    #   product  -> 33,098 records (3,310 pages)   goods
    #   service  -> 10,566 records (1,057 pages)   services and works
    # "all" keeps coverage broad, so the 11-product matcher sees the full
    # current opportunity set. Narrow to "service" when a buyer only sells
    # services. Empty string means "do not narrow".
    GEM_DIRECT_BID_TYPE: str = "all"
    # Broad collection is the default. The keyword pre-filter is OFF by
    # default because a small hardcoded vocabulary silently removed almost
    # every public GeM bid. Relevance is decided by the 11-product matching
    # engine downstream, which is unchanged.
    GEM_DIRECT_KEYWORD_FILTER_ENABLED: bool = False
    # Optional detail-page enrichment. Listing data alone is enough to persist
    # a valid bid, so enrichment is additive and off by default. A detail-page
    # failure is recorded and never removes the listing bid.
    GEM_DIRECT_ENRICH_DETAIL_PAGES: bool = False
    GEM_DIRECT_MAX_DETAIL_PAGES: int = 20

    # Document-aware extraction for GeM bid documents (PDF downloads served at
    # showbidDocument/<id> URLs). The existing detail-enrichment path tried to
    # render these as HTML in Playwright, which fails because GeM serves them
    # as file downloads. When enabled, the collector downloads the PDF over
    # plain HTTP, extracts its text with pypdf, and maps the extracted content
    # into the canonical bid fields used by the existing matching engine.
    # Off by default: listing data alone is sufficient to persist a bid, and
    # document extraction performs per-bid network calls.
    GEM_DIRECT_DOC_EXTRACTION_ENABLED: bool = False
    # Maximum document size in MB before extraction is refused.
    GEM_DIRECT_MAX_DOC_SIZE_MB: int = 10
    # Per-document fetch timeout in seconds.
    GEM_DIRECT_DOC_FETCH_TIMEOUT_SECONDS: float = 30.0
    # Maximum PDF pages to read for text extraction (0 = no limit).
    GEM_DIRECT_MAX_DOC_PAGES: int = 0

    # BoQ (Bill of Quantities) evidence enrichment. The public listing truncates
    # the item list to ~99 chars, so the full line items are fetched separately
    # from the BoQ CSV linked from the bid document and stored on
    # ``Bid.boq_items``. Bounded: at most GEM_BOQ_MAX_ITEMS line items (0 = no
    # cap) and a single request timeout for both the document and the CSV.
    GEM_BOQ_MAX_ITEMS: int = 500
    GEM_BOQ_FETCH_TIMEOUT_SECONDS: int = 45

    # Automatic BoQ enrichment during direct GeM collection. OFF by default,
    # exactly like the optional detail-page enrichment above: it performs
    # per-bid network calls, so it only runs where an operator has enabled it.
    # When on, each collection run enriches at most
    # GEM_BOQ_AUTO_ENRICH_MAX_PER_RUN freshly collected bids that do not already
    # carry BoQ evidence, so it can never become a request storm. A bid is
    # attempted at most once (``Bid.boq_checked_at`` records the attempt), so
    # repeated collections never re-fetch the same bid. The manual CLI
    # (scripts/enrich_bid_boq.py) is unaffected.
    GEM_BOQ_AUTO_ENRICH_ENABLED: bool = False
    GEM_BOQ_AUTO_ENRICH_MAX_PER_RUN: int = 25

    # ------------------------------------------------------------------
    # Bid-to-product matching engine
    #
    # The relevance score is already normalized to 0.0-1.0 by the engine
    # (raw weighted keyword/capability sum divided by 12.0, then clamped).
    # This is the single relevance threshold the engine consults; there is no
    # second threshold setting.
    #
    #   None (default): keep the engine's existing four-band classification
    #                    (MATCH >= 0.70, POSSIBLE_MATCH >= 0.45,
    #                     NEEDS_REVIEW >= 0.25, NO_MATCH below).
    #   float:          collapse to a single binary cut on the same 0-1 score
    #                   at that value: score >= threshold -> MATCH, else
    #                   NO_MATCH. Used to run the matching test at 0.5.
    #
    # Changing this never alters the scoring algorithm or keyword weights.
    # ------------------------------------------------------------------
    MATCHING_RELEVANCE_THRESHOLD: Optional[float] = None

    # ------------------------------------------------------------------
    # Configurable multi-source platform
    #
    # Any number of RSS/Atom feeds, JSON APIs and public HTML listing pages
    # can be added from the Data Source UI and persist in the source registry.
    # Every outbound request goes through the SSRF-safe transport and any
    # credential a source needs is referenced by environment-variable name.
    # Scheduled collection is ON by default in production: automatic per-source
    # collection runs once per tick, checking which enabled sources are due.
    # Safe defaults: 60-second tick, 5-minute minimum interval between runs of
    # the same source (MIN_INTERVAL_SECONDS in scheduler.py), per-source locks
    # to prevent concurrent manual+scheduler collection, and per-source try/except
    # so one blocked portal never stops the others.
    # ------------------------------------------------------------------
    SOURCE_SCHEDULER_ENABLED: bool = True
    SOURCE_SCHEDULER_TICK_SECONDS: int = 60
    # Optional comma-separated host allowlist for ALL configured sources.
    # Empty = any public host is permitted (still blocked from private /
    # reserved / link-local space by the SSRF transport). When set, only the
    # listed hosts or their subdomains are reachable.
    SOURCE_ALLOWED_HOSTS: str = ""
    # Comma-separated allowlist of environment-variable names a configured
    # source may reference through ``config["auth"]["env_ref"]``. This is a
    # hard security boundary: a source can only ever read a credential whose
    # variable is listed here, so an operator cannot turn source creation into
    # an environment-variable exfiltration mechanism (DATABASE_URL, SECRET_KEY,
    # ...). Empty (the default) means NO secret reference is
    # permitted at all -- deny-by-default. Names are matched exactly
    # (case-sensitive), must be valid shell env-var identifiers and are
    # validated both when a source is saved and again at collection time.
    SOURCE_ALLOWED_SECRET_ENVS: str = ""

    # ------------------------------------------------------------------
    # Email notification delivery (SMTP)
    #
    # Server-side only. These values are read exclusively by the notification
    # delivery service; no endpoint serializes them and the frontend only ever
    # receives the derived delivery_state / delivery_configured flags.
    #
    # Delivery is "configured" only when both SMTP_HOST and SMTP_FROM are set.
    # With no credentials the application keeps its explicit not-configured
    # state: notifications stay QUEUED and nothing is dispatched.
    #
    #   SMTP_HOST       e.g. smtp.example.com
    #   SMTP_PORT       587 (STARTTLS) or 465 (implicit TLS is not used)
    #   SMTP_USERNAME   optional; required by most real relays
    #   SMTP_PASSWORD   optional; NEVER logged, never returned by any API
    #   SMTP_FROM       sender address (required for configured state)
    #   SMTP_STARTTLS   upgrade the connection before auth (default on)
    # ------------------------------------------------------------------
    SMTP_HOST: Union[str, None] = None
    SMTP_PORT: int = 587
    SMTP_USERNAME: Union[str, None] = None
    SMTP_PASSWORD: Union[str, None] = None
    SMTP_FROM: Union[str, None] = None
    SMTP_STARTTLS: bool = True
    SMTP_TIMEOUT_SECONDS: int = 15
    # Bounded retry: one connection attempt per try, then FAILED if all fail.
    SMTP_MAX_ATTEMPTS: int = 3
    # Seconds waited between retry attempts (0 disables sleeping).
    SMTP_RETRY_BACKOFF_SECONDS: float = 1.0

    # ------------------------------------------------------------------
    # Derived helpers
    # ------------------------------------------------------------------
    @property
    def effective_bid_source(self) -> str:
        """Normalized manual-import selector. Always ``file_import``.

        The live GeM source is the Direct GeM Public Collector, which does not
        read this setting. Keeping only the manual file import selectable means
        no configuration value can silently point ingestion at a removed adapter.
        """
        return "file_import"

    @property
    def gem_direct_configured(self) -> bool:
        return bool(self.gem_direct_enabled and self.gem_direct_allowed_hosts)

    @property
    def source_allowed_secret_envs(self) -> List[str]:
        """Ordered, de-duplicated allowlist of permitted ``auth.env_ref`` names.

        Empty list = deny every secret reference (secure default).
        """
        raw = getattr(self, "SOURCE_ALLOWED_SECRET_ENVS", "") or ""
        seen: List[str] = []
        for name in str(raw).split(","):
            name = name.strip()
            if name and name not in seen:
                seen.append(name)
        return seen

    @property
    def gem_direct_allowed_hosts_list(self) -> List[str]:
        hosts = getattr(
            self, "GEM_DIRECT_ALLOWED_HOSTS", "gem.gov.in,bidplus.gem.gov.in"
        )
        if isinstance(hosts, str):
            hosts_list = [h.strip().lower().lstrip(".") for h in hosts.split(",")]
        else:
            hosts_list = [str(h).strip().lower().lstrip(".") for h in hosts]
        return [h for h in hosts_list if h]

    @property
    def gem_direct_approved_urls_list(self) -> List[str]:
        raw = getattr(self, "GEM_DIRECT_APPROVED_URLS", None) or ""
        if isinstance(raw, str):
            return [u.strip() for u in raw.split(",") if u.strip()]
        return [str(u).strip() for u in raw if str(u).strip()]

    @model_validator(mode="after")
    def _validate_production_settings(self) -> "Settings":
        """Reject known-development defaults when running in production.

        A bare default SECRET_KEY in production would allow trivial session
        forgery and other attacks. Fail fast at startup rather than silently
        deploying with an insecure key.
        """
        default_secret = (
            "dev_secret_key_securedapp_gem_bid_intelligence_2026_key"
        )
        if self.ENVIRONMENT == "production":
            if self.SECRET_KEY == default_secret:
                raise ValueError(
                    "SECRET_KEY must not be the development default when "
                    "ENVIRONMENT=production. Set SECRET_KEY to a strong random "
                    "value (32+ bytes) via environment variable or secret manager."
                )
            if len(self.SECRET_KEY) < 32:
                raise ValueError(
                    "SECRET_KEY must be at least 32 characters when "
                    "ENVIRONMENT=production. Set SECRET_KEY via environment "
                    "variable or secret manager."
                )
            if not self.AUTH_REQUIRED:
                raise ValueError(
                    "AUTH_REQUIRED must be True when ENVIRONMENT=production. "
                    "Set AUTH_REQUIRED=true to enforce authentication on "
                    "protected endpoints."
                )
        return self

    model_config = SettingsConfigDict(
        env_file=_resolve_env_files(),
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )


settings = Settings()
