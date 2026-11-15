"""
Direct GeM Public Collector Service.

Orchestrates the one live collection path for the GeM direct collector::

    GeM public page
        -> GeMPublicCollector (HTTP, browser rendering only when required)
        -> GeMPublicAdapter   -> canonical RawBidRecord
        -> existing validation -> normalization -> deduplication -> database
        -> existing 11-product matching -> relevance -> opportunity
        -> existing notifications -> dashboard

Every stage after the collector is the application's existing code; this
module only supplies public pages and reports the outcome. It creates no
parallel ingestion or matching architecture.

SCOPE AND COMPLIANCE
    * Manual trigger only. No background scheduler is started.
    * No GeM credentials of any kind are used.
    * If GeM refuses automated collection (HTTP 403 / 429 / a block page), the
      run stops with status ``BLOCKED`` and the reason is surfaced. Nothing is
      retried aggressively and no bypass is attempted.
    * Collection is BROAD by default. The keyword pre-filter is off unless it is
      explicitly switched on, because a small hardcoded vocabulary silently
      removed almost the entire public GeM result set. Relevance is decided
      downstream by the existing 11-product matching engine, which is the only
      authority for it and is unchanged by this collector.
    * One page failure, one malformed row or one failed detail page is recorded
      and skipped. None of them terminates an otherwise healthy collection.
"""
from __future__ import annotations

import hashlib
import logging
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import urlparse

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.bid import Bid
from app.models.analysis import BidScore
from app.models.collection import CollectionRun, RawBidPayload
from app.models.source_discovery import SourceDiscovery
from app.services.ingestion.duplicate_detector import check_duplicate
from app.services.ingestion.gem_boq_auto import enrich_collected_bids
from app.services.ingestion.gem_document_extractor import (
    DocumentExtractionResult,
    enrich_record_from_document,
    is_pdf_document_url,
)
from app.services.ingestion.gem_direct_adapter import GeMPublicAdapter
from app.services.ingestion.gem_public_collector import (
    DEFAULT_LISTING_URL,
    GeMBlockedError,
    GeMCollectorError,
    GeMPublicCollector,
    collect_paginated_listing,
    is_detail_url,
    open_listing_session,
    resolve_collection_targets,
    windows_proactor_loop_policy,
)
from app.services.ingestion.normalizer import normalize_record
from app.services.ingestion.schemas import RawBidRecord
from app.services.ingestion.validator import validate_records
from app.services.intelligence.batch_processor import process_bid_intelligence
from app.services.intelligence.matching_engine import match_bid_against_products
from app.services.intelligence.opportunity_analyzer import OpportunityAnalyzer
from app.services.intelligence.providers import DeterministicLLMProvider

logger = logging.getLogger(__name__)

# A single lock so two direct-collection runs can never overlap.
_gem_direct_lock = threading.Lock()
_is_running = False
_last_run_info: Dict[str, Any] = {
    "status": "IDLE",
    "last_run_id": None,
    "last_run_time": None,
    "last_successful_collection": None,
    "last_result": None,
}

# Checkpoint keys stored inside CollectionRun.notes.
# ``last_completed_page`` tracks historical backlog scanning progress
# (updated by manual runs only). ``monitoring_completed_page`` tracks
# scheduled latest-first monitoring progress (updated by scheduler runs
# only). These are independent so scheduled monitoring never overwrites
# historical progress.
_CHECKPOINT_KEY = "last_completed_page"
_MONITORING_CHECKPOINT_KEY = "monitoring_completed_page"


def _read_checkpoint_page(db: Session) -> Optional[int]:
    """
    Read the last successfully completed page from the most recent
    CollectionRun notes that carries ``last_completed_page``.

    Only runs triggered manually (not by the scheduler) write this key,
    so scheduled monitoring runs never overwrite historical checkpoint
    progress.
    """
    try:
        run = (
            db.query(CollectionRun)
            .filter(CollectionRun.source_adapter == "GEM_DIRECT_PUBLIC_ADAPTER")
            .filter(CollectionRun.status.in_(["SUCCESS", "PARTIAL"]))
            .filter(CollectionRun.notes.like("%last_completed_page=%"))
            .order_by(CollectionRun.started_at.desc())
            .first()
        )
        if run is None or not run.notes:
            return None
        import re as _re

        match = _re.search(r"last_completed_page=(\d+)", run.notes)
        if match:
            return int(match.group(1))
    except Exception:  # noqa: BLE001 - checkpoint must never block collection
        logger.warning("Could not read checkpoint page from database", exc_info=True)
    return None


def _read_monitoring_checkpoint_page(db: Session) -> Optional[int]:
    """
    Read the last completed page from the most recent scheduler monitoring run.
    Used for informational purposes only; monitoring always starts at page 1.
    """
    try:
        run = (
            db.query(CollectionRun)
            .filter(CollectionRun.source_adapter == "GEM_DIRECT_PUBLIC_ADAPTER")
            .filter(CollectionRun.status.in_(["SUCCESS", "PARTIAL"]))
            .filter(CollectionRun.notes.like("%monitoring_completed_page=%"))
            .order_by(CollectionRun.started_at.desc())
            .first()
        )
        if run is None or not run.notes:
            return None
        import re as _re

        match = _re.search(r"monitoring_completed_page=(\d+)", run.notes)
        if match:
            return int(match.group(1))
    except Exception:  # noqa: BLE001 - checkpoint must never block collection
        logger.warning("Could not read monitoring checkpoint page from database", exc_info=True)
    return None


def _write_checkpoint_page(
    db: Session,
    run: CollectionRun,
    page: int,
    key: str = "last_completed_page",
) -> None:
    """Record the last completed page on the CollectionRun row.

    ``key`` selects which checkpoint to update:
    - ``last_completed_page`` for manual/historical runs
    - ``monitoring_completed_page`` for scheduled monitoring runs
    """
    try:
        notes = run.notes or ""
        if f"{key}=" in notes:
            import re as _re

            notes = _re.sub(rf"{key}=\d+", f"{key}={page}", notes)
        else:
            notes = f"{notes};{key}={page}" if notes else f"{key}={page}"
        run.notes = notes
        db.flush()
    except Exception:  # noqa: BLE001 - checkpoint must never block collection
        logger.warning("Could not write checkpoint page to database", exc_info=True)


def _record_source_discovery(
    db: Session,
    *,
    run_id: Optional[str],
    normalized: Dict[str, Any],
    listing_page: Optional[int],
    persisted: bool,
    relevance_score: Optional[float],
) -> Optional[SourceDiscovery]:
    """
    Record or update a source discovery ledger entry for one observed GeM bid.

    Every valid bid observed during collection is recorded here, regardless of
    relevance. NO_MATCH bids are discovered but not persisted as business bids.
    Relevant bids are both discovered and persisted.

    Returns the SourceDiscovery row, or None if recording fails.
    """
    try:
        gem_bid_id = normalized.get("gem_bid_id")
        bid_number = normalized.get("bid_number")
        title = normalized.get("title", "")
        organisation = normalised = normalized.get("organisation", "")
        category = normalized.get("category")
        source_url = normalized.get("source_url")
        closing_date = normalized.get("closing_date")
        closing_iso = closing_date.isoformat() if closing_date else None

        # Build composite identity from stable fields when no GeM ID.
        composite = None
        lookup_id = None
        if gem_bid_id:
            lookup_id = str(gem_bid_id).strip().upper()
        elif bid_number:
            lookup_id = str(bid_number).strip().upper()
        else:
            basis = f"{title}|{organisation}|{closing_iso or ''}"
            composite = hashlib.sha256(basis.encode("utf-8")).hexdigest()[:64]
            lookup_id = composite

        # Look up existing discovery record by any known identity.
        existing: Optional[SourceDiscovery] = None
        if lookup_id:
            filters = [
                (SourceDiscovery.gem_bid_id == lookup_id)
                | (SourceDiscovery.bid_number == lookup_id)
            ]
            if composite is not None:
                filters.append(SourceDiscovery.composite_identity == composite)
            existing = (
                db.query(SourceDiscovery)
                .filter(or_(*filters))
                .first()
            )

        now = datetime.now(timezone.utc)

        if existing:
            existing.last_observed_at = now
            existing.discovery_status = "updated"
            db.flush()
        else:
            existing = SourceDiscovery(
                gem_bid_id=gem_bid_id,
                bid_number=bid_number,
                composite_identity=composite,
                source_url=source_url,
                listing_page=listing_page,
                collection_run_id=run_id,
                first_discovered_at=now,
                last_observed_at=now,
                discovery_status="discovered",
                persisted_as_business_bid=persisted,
                relevance_score=relevance_score,
                title=title,
                organisation=organisation,
                category=category,
            )
            db.add(existing)
            db.flush()

        # Update persistence status if this bid is relevant.
        if persisted:
            existing.persisted_as_business_bid = True
            existing.relevance_score = relevance_score
            db.flush()

        return existing
    except Exception:  # noqa: BLE001 - discovery ledger must never block collection
        logger.warning(
            "Could not record source discovery for bid %s",
            normalized.get("gem_bid_id") or normalized.get("bid_number") or "unknown",
            exc_info=True,
        )
        return None


# Optional source-side pre-filter for SecuredApp-relevant terms.
#
# This is OFF by default and must stay that way for default production
# collection. Measured against the live public listing, this vocabulary matched
# 0 of 10 bids on the first page, so enabling it by default removed the entire
# result set before the 11-product matching engine ever saw a bid. It is kept
# only as an optional operator-supplied narrowing; a keyword hit is never a
# product match, and the matching engine remains the sole relevance authority.
DEFAULT_KEYWORDS: Tuple[str, ...] = (
    "smart contract",
    "blockchain",
    "blockchain security",
    "blockchain investigation",
    "transaction monitoring",
    "decentralized identity",
    "decentralised identity",
    "verifiable credentials",
    "kyc",
    "aml",
    "web3",
    "defi",
    "post-quantum cryptography",
    "post quantum cryptography",
    "cryptographic key management",
    "cookie consent",
    "privacy compliance",
    "data protection",
    "cybersecurity",
    "information security",
    "encryption",
    "digital signature",
    "e-signature",
    "identity verification",
    "threat detection",
    "fraud detection",
)


# ---------------------------------------------------------------------------
# State helpers
# ---------------------------------------------------------------------------
def is_gem_direct_running() -> bool:
    """True while a direct GeM collection run is in progress."""
    return _is_running


def get_last_gem_direct_run_info() -> Dict[str, Any]:
    """Most recent direct-collector run metadata (never includes full results)."""
    return dict(_last_run_info)


def _remember(status: str, run_id: Optional[str], result: Dict[str, Any]) -> None:
    global _last_run_info
    previous_success = _last_run_info.get("last_successful_collection")
    _last_run_info = {
        "status": status,
        "last_run_id": run_id,
        "last_run_time": datetime.now(timezone.utc).isoformat(),
        "last_successful_collection": (
            datetime.now(timezone.utc).isoformat()
            if status == "SUCCESS"
            else previous_success
        ),
        "last_result": result,
    }


def _empty_result(status: str, message: str, **extra: Any) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "run_id": None,
        "status": status,
        "source": "gem_direct",
        "source_name": "GeM",
        "source_type": "direct_public",
        "message": message,
        "requested_urls": 0,
        "rejected_urls": 0,
        "scrape_errors": 0,
        # Coverage: what the source actually offered vs what was walked.
        "pages_visited": 0,
        "pages_available": None,
        "records_available": None,
        "stop_reason": None,
        "limit_reached": False,
        # The public listing scope this run used (GeM's own Advance Search
        # filters), so a report never implies wider coverage than was asked for.
        "scope": {},
        # Rows: discovered vs unique. ``rows_seen`` is every row encountered,
        # ``duplicate_rows`` is how many of those repeated a bid already seen in
        # this same run, and ``unique_bids`` is what reached the pipeline.
        "rows_seen": 0,
        "duplicate_rows": 0,
        "unique_bids": 0,
        "parser_failures": 0,
        "page_failures": 0,
        "detail_enriched": 0,
        "detail_failures": 0,
        "keyword_skipped": 0,
        "received": 0,
        "validated": 0,
        "rejected": 0,
        "inserted": 0,
        "updated": 0,
        "duplicates": 0,
        "irrelevant_bids": 0,
        # Fuzzy-title dedup activity: similar titles seen, and how many of them
        # were suppressed because corroborating evidence showed the same tender.
        "fuzzy_candidates": 0,
        "fuzzy_suppressed": 0,
        "intelligence_processed": 0,
        "notifications_created": 0,
        "duration_seconds": 0.0,
        "collection_method": None,
        "blocked_stage": None,
        "http_status": None,
        "errors": [],
        "extracted_fields": [],
        "records": [],
    }
    result.update(extra)
    return result


# ---------------------------------------------------------------------------
# Keyword pre-filter (kept strictly separate from the 11-product matching)
# ---------------------------------------------------------------------------
def keyword_filter_enabled(explicit: Optional[bool] = None) -> bool:
    """
    Whether the source-side keyword pre-filter applies to this run.

    ``None`` means "use the configured default", which is OFF: default
    production collection must be broad, and relevance belongs to the existing
    11-product matching engine.
    """
    if explicit is not None:
        return bool(explicit)
    return bool(getattr(settings, "GEM_DIRECT_KEYWORD_FILTER_ENABLED", False))


def record_matches_keywords(record: RawBidRecord, keywords: Optional[List[str]]) -> bool:
    """
    Cheap pre-filter over the printed text of a record.

    A keyword hit is **not** a product match. It only narrows what is worth
    handing to the existing matching engine.
    """
    active = [k.strip().lower() for k in (keywords or []) if k and k.strip()]
    if not active:
        return True

    haystack = " ".join(
        str(value or "")
        for value in (
            record.bid_number,
            record.title,
            record.organisation,
            record.department,
            record.ministry,
            record.category,
            record.scope_of_work,
        )
    ).lower()
    if not haystack.strip():
        # Nothing printed to search: do not silently drop the record.
        return True
    return any(keyword in haystack for keyword in active)


def _canonical_field_report(records: List[RawBidRecord]) -> List[Dict[str, Any]]:
    """Report which canonical fields were actually populated, per record."""
    report: List[Dict[str, Any]] = []
    for record in records:
        populated = sorted(
            field
            for field in RawBidRecord.model_fields
            if field != "certifications_required" and getattr(record, field, None)
        )
        report.append(
            {
                "source_url": record.source_url,
                "extracted_fields": populated,
                "missing_fields": sorted(
                    field
                    for field in RawBidRecord.model_fields
                    if field != "certifications_required" and not getattr(record, field, None)
                ),
            }
        )
    return report


# ---------------------------------------------------------------------------
# Collection
# ---------------------------------------------------------------------------
def _render_with_browser(url: str, timeout_ms: int) -> Tuple[int, str]:
    """
    Render a public GeM page in a real browser and return its final HTML.

    Used only when the page genuinely needs JavaScript rendering, which is the
    case for the public bid listing. This is ordinary headless browsing with an
    honest user agent: no stealth plugin, no automation-flag patching, no
    challenge solving.
    """
    try:
        from playwright.sync_api import sync_playwright  # type: ignore
    except Exception as exc:  # pragma: no cover - optional dependency
        raise GeMCollectorError(
            "Browser rendering is required for this public GeM page but Playwright is not "
            f"installed in the backend environment ({exc}).",
            status_code=501,
            stage="render",
        ) from exc

    user_agent = getattr(settings, "GEM_DIRECT_USER_AGENT", "SecuredApp-GeM-Intelligence/1.0")
    with windows_proactor_loop_policy(), sync_playwright() as driver:
        browser = driver.chromium.launch(headless=True)
        try:
            context = browser.new_context(
                user_agent=user_agent,
                locale="en-US",
                viewport={"width": 1440, "height": 1000},
            )
            page = context.new_page()
            response = page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            status_code = int(response.status) if response else 0

            if status_code in (403, 429):
                raise GeMBlockedError(
                    f"GeM refused automated collection of {url} (HTTP {status_code}). "
                    "Collection has been stopped; no bypass is attempted.",
                    status_code=status_code,
                    stage="render",
                )

            # The listing populates asynchronously after first paint. Wait for
            # bid rows to appear, then fall back to the settled DOM.
            try:
                page.wait_for_selector("#bidCard .card, table tbody tr", timeout=45000)
            except Exception:
                page.wait_for_timeout(5000)

            markup = page.content()
            return status_code, markup
        finally:
            browser.close()


# One shared collector instance for the whole process. The "blocked" latch and
# the last-request timestamp must survive between runs so that a refusal from
# GeM is honoured immediately on the next manual trigger, and so that the status
# endpoint reports the real state instead of a freshly built object.
_COLLECTOR_LOCK = threading.Lock()
_COLLECTOR: Optional[GeMPublicCollector] = None


def _shared_collector() -> GeMPublicCollector:
    global _COLLECTOR
    if _COLLECTOR is None:
        with _COLLECTOR_LOCK:
            if _COLLECTOR is None:
                _COLLECTOR = GeMPublicCollector()
    return _COLLECTOR


def _is_paginated_listing_url(url: str) -> bool:
    """
    True when the target is the paged public bid listing.

    Only this view carries a pagination widget and a page-by-page data fetch, so
    it is the only target that is walked. Any other allowlisted URL (a single
    bid detail page, a static view) is fetched once.
    """
    try:
        path = urlparse(url).path.rstrip("/").lower()
    except Exception:
        return False
    return not is_detail_url(url) and path in ("/all-bids", "/all-bids-data")


def collect_paginated_listing_pages(
    url: str,
    max_pages: Optional[int] = None,
    use_browser: Optional[bool] = None,
    search_term: Optional[str] = None,
    start_page: int = 1,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any], List[Dict[str, str]]]:
    """
    Walk the public listing's real pages and return the rendered rows.

    Returns ``(pages, pagination, errors)`` where ``pages`` carries one entry
    per visited listing page (in page order) and ``pagination`` reports exactly
    how far the walk got and why it stopped.

    A page that cannot be read is recorded in ``errors`` and skipped; the walk
    continues until the listing stops offering a next page, a page repeats
    already-collected bid IDs, or the configured operational page budget is
    reached (reported as ``limit_reached`` so truncation is never silent).
    """
    browser_allowed = (
        bool(getattr(settings, "GEM_DIRECT_USE_PLAYWRIGHT", False))
        if use_browser is None
        else bool(use_browser)
    )
    errors: List[Dict[str, str]] = []
    interval = max(0.0, float(getattr(settings, "GEM_DIRECT_REQUEST_INTERVAL_SECONDS", 3.0)))
    settle_ms = int(getattr(settings, "GEM_DIRECT_PAGE_SETTLE_MS", 45000) or 45000)
    failures_budget = int(getattr(settings, "GEM_DIRECT_MAX_CONSECUTIVE_PAGE_FAILURES", 3) or 3)
    repeats_budget = int(getattr(settings, "GEM_DIRECT_MAX_REPEATED_PAGES", 3) or 3)
    if max_pages is None:
        max_pages = int(getattr(settings, "GEM_DIRECT_MAX_PAGES", 0) or 0)
    max_pages = max(0, int(max_pages or 0))

    pagination: Dict[str, Any] = {
        "pages_visited": 0,
        "pages_available": None,
        "records_available": None,
        "rows_seen": 0,
        "stop_reason": "not_started",
        "limit_reached": False,
        "page_failures": 0,
        "pages_repeated": 0,
    }

    if not browser_allowed:
        # Without a rendered page there is no pagination to walk: the listing is
        # a JavaScript shell. Say so explicitly instead of silently reporting
        # a single page as complete coverage.
        pagination["stop_reason"] = "pagination_unavailable"
        errors.append(
            {
                "field": "pagination",
                "message": (
                    f"{url}: the public listing renders its rows with JavaScript, so pagination "
                    "requires browser rendering, which is disabled "
                    "(GEM_DIRECT_USE_PLAYWRIGHT=false). Only page 1 can be collected."
                ),
            }
        )
        return [], pagination, errors

    driver = None
    browser = None
    # GeM's own Advance Search scope, applied through the rendered page's own
    # filter state before the first read.
    bid_status_type = str(getattr(settings, "GEM_DIRECT_BID_STATUS_TYPE", "") or "").strip() or None
    bid_type = str(getattr(settings, "GEM_DIRECT_BID_TYPE", "") or "").strip() or None
    sort_order = str(getattr(settings, "GEM_DIRECT_SORT_ORDER", "") or "").strip() or None
    # Optional, empty by default: a search term narrows the walk through GeM's
    # own public search box. It is never part of the production default.
    search_term = str(search_term or "").strip() or None

    pagination["scope"] = {
        "bid_status_type": bid_status_type,
        "bid_type": bid_type,
        "sort_order": sort_order,
        "search_term": search_term,
        "listing_url": url,
    }

    try:
        driver, browser, session = open_listing_session(
            url,
            timeout_ms=settle_ms,
            bid_status_type=bid_status_type,
            bid_type=bid_type,
            sort_order=sort_order,
            search_term=search_term,
        )
        walk = collect_paginated_listing(
            session,
            max_pages=max_pages,
            request_interval=interval,
            max_consecutive_failures=failures_budget,
            max_repeated_pages=repeats_budget,
            start_page=start_page,
        )
        pages = walk.page_dicts(url, method="playwright")
        pagination = walk.summary()
        pagination["scope"] = {
            "bid_status_type": bid_status_type,
            "bid_type": bid_type,
            "sort_order": sort_order,
            "search_term": search_term,
            "listing_url": url,
            "applied": getattr(session, "scope_applied", {}) or {},
        }
        errors.extend(walk.page_failures)
    except GeMBlockedError:
        raise
    except GeMCollectorError as exc:
        pagination["stop_reason"] = "unavailable"
        errors.append({"field": "pagination", "message": f"{url}: {exc.message}"})
        return [], pagination, errors
    except Exception as exc:  # noqa: BLE001 - a render failure must stay reportable
        pagination["stop_reason"] = "unavailable"
        errors.append({"field": "pagination", "message": f"{url}: {type(exc).__name__}: {exc}"})
        return [], pagination, errors
    finally:
        try:
            if browser is not None:
                browser.close()
        except Exception:
            pass
        try:
            if driver is not None:
                driver.stop()
        except Exception:
            pass

    return pages, pagination, errors


def collect_public_pages(
    urls: List[str],
    use_browser: Optional[bool] = None,
    paginate: Optional[bool] = None,
    max_pages: Optional[int] = None,
    search_term: Optional[str] = None,
    start_page: int = 1,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, str]], List[str], Dict[str, Any]]:
    """
    Retrieve each public GeM page and return
    ``(pages, errors, methods, pagination)``.

    For the paginated listing, the rendered page's own pagination is walked so
    the whole available set is collected instead of page 1 only. When browser
    rendering is unavailable the listing falls back to a single plain-HTTP fetch
    and says so, rather than reporting page 1 as complete coverage. Other
    allowlisted URLs (a single detail page, a static view) are fetched once.

    Raises :class:`GeMBlockedError` as soon as the source refuses collection.
    """
    collector = _shared_collector()
    browser_allowed = (
        bool(getattr(settings, "GEM_DIRECT_USE_PLAYWRIGHT", False))
        if use_browser is None
        else bool(use_browser)
    )
    want_pagination = (
        bool(getattr(settings, "GEM_DIRECT_PAGINATE", True)) if paginate is None else bool(paginate)
    )

    pages: List[Dict[str, Any]] = []
    errors: List[Dict[str, str]] = []
    methods: List[str] = []
    pagination: Dict[str, Any] = {
        "pages_visited": 0,
        "pages_available": None,
        "records_available": None,
        "rows_seen": 0,
        "stop_reason": "not_paginated",
        "limit_reached": False,
        "page_failures": 0,
    }

    interval = max(0.0, float(getattr(settings, "GEM_DIRECT_REQUEST_INTERVAL_SECONDS", 3.0)))

    for index, url in enumerate(urls):
        method = "http"
        markup: Optional[str] = None

        if _is_paginated_listing_url(url) and want_pagination and browser_allowed:
            listing_pages, listing_pagination, listing_errors = collect_paginated_listing_pages(
                url, max_pages=max_pages, use_browser=use_browser, search_term=search_term,
                start_page=start_page,
            )
            pages.extend(listing_pages)
            errors.extend(listing_errors)
            methods.extend(page.get("method", "playwright") for page in listing_pages)
            pagination = listing_pagination
            if index < len(urls) - 1 and interval:
                time.sleep(interval)
            continue

        if _is_paginated_listing_url(url) and want_pagination and not browser_allowed:
            errors.append(
                {
                    "field": "pagination",
                    "message": (
                        f"{url}: the public listing renders its rows with JavaScript, so pagination "
                        "requires browser rendering, which is disabled "
                        "(GEM_DIRECT_USE_PLAYWRIGHT=false). Only a single un-paginated fetch is possible."
                    ),
                }
            )
            pagination["stop_reason"] = "pagination_unavailable"

        try:
            _status, markup = collector.fetch(url, stage="listing")
        except GeMBlockedError:
            # Stop immediately: never try to work around a block.
            raise
        except GeMCollectorError as exc:
            # One page failing is recorded; the remaining pages still run.
            errors.append({"field": "fetch", "message": f"{url}: {exc.message}"})
            if index < len(urls) - 1 and interval:
                time.sleep(interval)
            continue

        # A successful response with no bid rows usually means the rows are
        # rendered client-side. Try one browser render before giving up.
        # Document URLs (PDF downloads at showbidDocument/<id>) are not HTML
        # pages; attempting to render them in Playwright fails with
        # "Download is starting". Skip browser render for those and let the
        # document extraction path handle them instead.
        is_doc_url = is_pdf_document_url(url)
        if markup and not GeMPublicAdapter().parse_page(markup, source_url=url) and not is_doc_url:
            if browser_allowed:
                try:
                    timeout_ms = max(15, int(getattr(settings, "GEM_DIRECT_TIMEOUT_SECONDS", 60))) * 1000
                    _status, rendered = _render_with_browser(url, timeout_ms)
                    if rendered:
                        markup = rendered
                        method = "playwright"
                except GeMBlockedError:
                    raise
                except GeMCollectorError as exc:
                    errors.append({"field": "render", "message": f"{url}: {exc.message}"})
            else:
                errors.append(
                    {
                        "field": "render",
                        "message": (
                            f"{url}: returned no bid rows over plain HTTP and browser rendering "
                            "is disabled (GEM_DIRECT_USE_PLAYWRIGHT=false)."
                        ),
                    }
                )

        if markup:
            pages.append({"url": url, "html": markup, "method": method, "page": 1})
            methods.append(method)
            pagination["pages_visited"] = int(pagination.get("pages_visited") or 0) + 1

        if index < len(urls) - 1 and interval:
            time.sleep(interval)

    return pages, errors, methods, pagination


def _empty_result_preview_placeholder() -> None:  # pragma: no cover - documentation aid
    """Placeholder retained for module layout."""


# Fields a detail page can add to a listing-derived record. A bid is persisted
# from the listing alone; these only fill gaps.
_DETAIL_ENRICHABLE_FIELDS = (
    "estimated_value",
    "currency",
    "location",
    "scope_of_work",
    "technical_requirements",
    "eligibility_criteria",
    "qualification_requirements",
    "experience_requirements",
    "certification_requirements",
    "emd_information",
    "tender_fee_information",
    "contact_information",
    "bid_type",
    "category",
)


def _enrich_from_detail_pages(
    adapter: GeMPublicAdapter,
    records: List[RawBidRecord],
    page_collector: Any,
    use_browser: Optional[bool] = None,
    enabled: Optional[bool] = None,
    max_detail_pages: Optional[int] = None,
) -> Tuple[Dict[str, Dict[str, Any]], List[Dict[str, str]]]:
    """
    Optionally fetch public detail pages to fill gaps in listing-derived records.

    Enrichment is additive and strictly bounded. A detail page that fails is
    recorded and skipped: the listing-derived bid is still complete enough to
    persist, so a detail failure can never delete a bid from the run.
    ``enabled`` and ``max_detail_pages`` override the configured defaults when
    supplied.

    Detail URLs that point to GeM bid documents (PDF downloads at
    ``showbidDocument/<id>``) are handled by the document extractor
    (:mod:`app.services.ingestion.gem_document_extractor`) instead of being
    rendered as HTML in Playwright, because GeM serves them as file downloads.
    Document extraction is controlled by ``GEM_DIRECT_DOC_EXTRACTION_ENABLED``
    and is independent of the HTML detail-page setting.
    """
    if enabled is None:
        enabled = bool(getattr(settings, "GEM_DIRECT_ENRICH_DETAIL_PAGES", False))
    doc_enabled = bool(
        getattr(settings, "GEM_DIRECT_DOC_EXTRACTION_ENABLED", False)
    )
    if not enabled and not doc_enabled:
        return {}, []

    if max_detail_pages is None:
        max_detail_pages = int(getattr(settings, "GEM_DIRECT_MAX_DETAIL_PAGES", 0) or 0)
    budget = max(0, int(max_detail_pages or 0))
    if budget <= 0 and not doc_enabled:
        return {}, []

    errors: List[Dict[str, str]] = []
    enriched: Dict[str, Dict[str, Any]] = {}
    attempted = 0
    for record in records:
        url = (record.source_url or "").strip()
        if not url or not is_detail_url(url):
            continue

        is_doc = is_pdf_document_url(url)
        html_succeeded = False

        # --- HTML detail-page path (tried first when enabled) -------------
        if enabled:
            if attempted >= budget and budget > 0:
                errors.append(
                    {
                        "field": "detail_enrichment",
                        "message": (
                            f"Detail-page enrichment stopped at the configured budget of {budget} "
                            f"page(s) (GEM_DIRECT_MAX_DETAIL_PAGES). Remaining bids keep their listing data."
                        ),
                    }
                )
                break
            attempted += 1
            try:
                detail_pages, fetch_errors, _methods, _pagination = page_collector(
                    [url], use_browser=use_browser, paginate=False, max_pages=0
                )
            except GeMBlockedError:
                raise
            except Exception as exc:  # noqa: BLE001 - one detail failure must not stop the run
                errors.append({"field": "detail", "message": f"{url}: {type(exc).__name__}: {exc}"})
                continue
            errors.extend(fetch_errors)
            if not detail_pages:
                errors.append({"field": "detail", "message": f"{url}: detail page returned no content."})
            else:
                detail = adapter.parse_detail_page(
                    detail_pages[0].get("html"), source_url=url
                )
                if detail is not None:
                    html_succeeded = True
                    key = (
                        record.gem_bid_id or record.bid_number or ""
                    ).strip().upper()
                    enriched[key] = {
                        field: getattr(detail, field, None)
                        for field in _DETAIL_ENRICHABLE_FIELDS
                    }
                else:
                    errors.append(
                        {"field": "detail", "message": f"{url}: detail page yielded no bid fields."}
                    )

        # --- PDF document path (fallback when HTML yielded nothing) -------
        if not html_succeeded and is_doc and doc_enabled:
            if attempted >= budget and budget > 0:
                errors.append(
                    {
                        "field": "detail_enrichment",
                        "message": (
                            f"Detail-page enrichment stopped at the configured budget of {budget} "
                            f"page(s) (GEM_DIRECT_MAX_DETAIL_PAGES). Remaining bids keep their listing data."
                        ),
                    }
                )
                break
            attempted += 1
            try:
                doc_result = enrich_record_from_document(
                    record,
                    timeout=float(
                        getattr(
                            settings,
                            "GEM_DIRECT_DOC_FETCH_TIMEOUT_SECONDS",
                            30.0,
                        )
                    ),
                    max_size_bytes=int(
                        getattr(settings, "GEM_DIRECT_MAX_DOC_SIZE_MB", 10)
                    )
                    * 1024
                    * 1024,
                    max_pages=int(
                        getattr(settings, "GEM_DIRECT_MAX_DOC_PAGES", 0) or 0
                    ),
                )
            except Exception as exc:  # noqa: BLE001 - one doc failure must not stop the run
                errors.append(
                    {
                        "field": "detail",
                        "message": f"{url}: document extraction raised {type(exc).__name__}: {exc}",
                    }
                )
                continue

            if not doc_result.success:
                errors.append(
                    {
                        "field": "detail",
                        "message": (
                            f"{url}: document extraction failed "
                            f"({doc_result.error_type or 'unknown'}): {doc_result.error or 'no detail'}"
                        ),
                    }
                )
                continue

            key = (record.gem_bid_id or record.bid_number or "").strip().upper()
            enriched[key] = {
                field: value
                for field, value in (doc_result.extracted_fields or {}).items()
                if value is not None
            }
            continue

        # Document URL but document extraction is disabled, and HTML path
        # already failed or was skipped: record the gap.
        if is_doc and not doc_enabled and not html_succeeded:
            errors.append(
                {
                    "field": "detail",
                    "message": (
                        f"{url}: GeM bid document detected but document "
                        f"extraction is disabled "
                        f"(GEM_DIRECT_DOC_EXTRACTION_ENABLED=false)."
                    ),
                }
            )

    return enriched, errors


def ingest_gem_direct_bids(
    db: Session,
    urls: Optional[List[str]] = None,
    keywords: Optional[List[str]] = None,
    allow_update_duplicates: bool = True,
    auto_notify: bool = True,
    triggered_by: str = "manual",
    preview: bool = False,
    apply_keyword_filter: Optional[bool] = None,
    use_browser: Optional[bool] = None,
    max_pages: Optional[int] = None,
    enrich_detail_pages: Optional[bool] = None,
    search_term: Optional[str] = None,
    start_page: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Collect public GeM bids and push them through the existing pipeline.

    ``preview=True`` validates and reports extracted fields but persists
    nothing. ``apply_keyword_filter`` defaults to the configured value, which is
    OFF, so default production collection is broad and the existing 11-product
    matching engine -- the sole relevance authority -- sees the whole bid
    population. ``max_pages`` is the explicit operational page budget; when it
    truncates the walk the result reports ``limit_reached=True``.
    ``enrich_detail_pages`` overrides the configured detail-enrichment default;
    enrichment only ever adds fields to bids the listing already proved exist.
    ``start_page`` resumes the walk part-way through the listing (default 1); the
    configured sort/filter scope is still applied before the first read.
    """
    global _is_running

    if not getattr(settings, "GEM_DIRECT_ENABLED", True):
        return _empty_result(
            "NOT_CONFIGURED",
            "Direct GeM collector is disabled. Set GEM_DIRECT_ENABLED=true in the backend environment.",
        )

    if not _gem_direct_lock.acquire(blocking=False):
        return _empty_result(
            "BUSY",
            "A direct GeM collection run is already in progress. Wait for it to finish.",
        )

    _is_running = True
    start_time = time.perf_counter()
    # Capture the run start timestamp here (before page collection) so that
    # duration_seconds (perf_counter - start_time) matches finished_at -
    # started_at in the audit row. Previously start_time was captured before
    # page collection while started_at was captured after it, causing the
    # duration_seconds notes field to systematically overstate the run duration.
    run_started_at = datetime.now(timezone.utc)

    # --- Auto-resume from checkpoint --------------------------------------
    # When no explicit start_page is supplied and auto-resume is enabled,
    # resume from the last successfully completed page recorded in the
    # most recent CollectionRun notes. An explicit start_page always wins.
    if start_page is None:
        start_page = 1
    elif getattr(settings, "GEM_DIRECT_AUTO_RESUME", False):
        checkpoint_page = _read_checkpoint_page(db)
        if checkpoint_page is not None:
            start_page = checkpoint_page
            logger.info(
                "Auto-resuming GeM collection from checkpoint page %s", start_page
            )

    run: Optional[CollectionRun] = None
    all_errors: List[Dict[str, str]] = []
    adapter = GeMPublicAdapter()
    collection_method = "http"
    pagination: Dict[str, Any] = {
        "pages_visited": 0,
        "pages_available": None,
        "records_available": None,
        "rows_seen": 0,
        "stop_reason": "not_started",
        "limit_reached": False,
        "page_failures": 0,
    }

    try:
        # --- 1. Allowlist + budget --------------------------------------
        requested_urls = list(urls or []) or [DEFAULT_LISTING_URL]
        include_configured = not urls
        targets, rejected_urls, url_errors = resolve_collection_targets(
            requested_urls, include_configured=include_configured
        )
        all_errors.extend(url_errors)

        if not targets:
            result = _empty_result(
                "NO_URLS",
                "No permitted public GeM URL was available to collect.",
                rejected_urls=len(rejected_urls),
                errors=all_errors,
            )
            _remember(result["status"], None, result)
            return result

        # --- 2. Retrieve the public pages, walking real pagination ---------
        try:
            pages, fetch_errors, methods, pagination = collect_public_pages(
                targets, use_browser=use_browser, max_pages=max_pages,
                search_term=search_term, start_page=int(start_page or 1),
            )
        except GeMBlockedError as exc:
            result = _empty_result(
                "BLOCKED",
                exc.message,
                requested_urls=len(targets),
                blocked_stage=exc.stage,
                http_status=exc.status_code,
                errors=[{"field": f"blocked:{exc.stage}", "message": exc.message}],
            )
            _remember("BLOCKED", None, result)
            return result

        all_errors.extend(fetch_errors)
        if methods and "playwright" in methods:
            collection_method = "playwright"

        def _coverage(**extra: Any) -> Dict[str, Any]:
            """Coverage counters always travel with the result, never silently."""
            merged = dict(pagination)
            merged.update(extra)
            return merged

        def _result(status: str, message: str, **extra: Any) -> Dict[str, Any]:
            """Early-return helper that always reports method and elapsed time."""
            coverage = _coverage(
                pages_visited=extra.pop("pages_visited", pagination.get("pages_visited", 0)),
                pages_available=extra.pop("pages_available", pagination.get("pages_available")),
                records_available=extra.pop("records_available", pagination.get("records_available")),
                stop_reason=extra.pop("stop_reason", pagination.get("stop_reason")),
                limit_reached=extra.pop("limit_reached", bool(pagination.get("limit_reached"))),
                page_failures=extra.pop("page_failures", int(pagination.get("page_failures") or 0)),
            )
            coverage.update(extra)
            # ``scope`` travels inside the coverage mapping already, so it is
            # never passed twice.
            payload = _empty_result(
                status,
                message,
                duration_seconds=round(time.perf_counter() - start_time, 3),
                collection_method=collection_method if methods else None,
                **coverage,
            )
            _remember(status, None, payload)
            return payload

        # --- 3. Adapter -> canonical RawBidRecord ------------------------
        # Rows are parsed page by page. A malformed row is recorded and skipped;
        # it never removes the other rows of the same page or the whole run.
        raw_records, parse_failures, rows_seen = adapter.parse_detailed(pages, source_name="GeM")
        for failure in parse_failures:
            all_errors.append(
                {
                    "field": f"parse:page{failure.get('page')}:row{failure.get('row')}",
                    "message": str(failure.get("message")),
                }
            )
        pagination["rows_seen"] = max(int(pagination.get("rows_seen") or 0), rows_seen)

        # A row repeated inside this same run is a duplicate, not a new record.
        # Database-level deduplication still runs afterwards; this only stops the
        # same page from being processed twice inside one run.
        unique_records: List[RawBidRecord] = []
        seen_keys: Set[str] = set()
        duplicate_rows = 0
        for record in raw_records:
            key = (record.gem_bid_id or record.bid_number or "").strip().upper()
            if not key:
                key = f"title:{(record.title or '').strip().lower()}"
            if key in seen_keys:
                duplicate_rows += 1
                continue
            seen_keys.add(key)
            unique_records.append(record)

        if not raw_records:
            return _result(
                "NO_RECORDS",
                (
                    "The public GeM page was retrieved but no bid record could be mapped from it. "
                    "Nothing was persisted."
                ),
                requested_urls=len(targets),
                rejected_urls=len(rejected_urls),
                scrape_errors=len(fetch_errors),
                rows_seen=rows_seen,
                parser_failures=len(parse_failures),
                errors=all_errors,
            )

        # --- 3b. Optional detail-page enrichment (additive only) -----------
        enriched, enrichment_failures = _enrich_from_detail_pages(
            adapter,
            unique_records,
            collect_public_pages,
            use_browser=use_browser,
            enabled=enrich_detail_pages,
        )
        all_errors.extend(enrichment_failures)
        if enriched:
            for record in unique_records:
                detail = enriched.get(
                    (record.gem_bid_id or record.bid_number or "").strip().upper()
                )
                if not detail:
                    continue
                for field, value in detail.items():
                    if value and not getattr(record, field, None):
                        try:
                            setattr(record, field, value)
                        except Exception:  # noqa: BLE001 - never fail on enrichment
                            continue

        # --- 4. Optional keyword pre-filter ------------------------------
        filtered_records = unique_records
        keyword_skipped = 0
        if keyword_filter_enabled(apply_keyword_filter):
            active_keywords = list(keywords or DEFAULT_KEYWORDS)
            filtered_records = [
                record for record in unique_records if record_matches_keywords(record, active_keywords)
            ]
            keyword_skipped = len(unique_records) - len(filtered_records)
            if keyword_skipped:
                all_errors.append(
                    {
                        "field": "keyword_filter",
                        "message": (
                            f"{keyword_skipped} of {len(unique_records)} record(s) did not match any "
                            "configured keyword and were not sent to the matching engine."
                        ),
                    }
                )

        # Optional hard cap on how many unique records enter the pipeline.
        max_bids = int(getattr(settings, "GEM_DIRECT_MAX_BIDS_PER_RUN", 0) or 0)
        capped_at_limit = False
        if max_bids > 0 and len(filtered_records) > max_bids:
            filtered_records = filtered_records[:max_bids]
            capped_at_limit = True
            all_errors.append(
                {
                    "field": "bid_limit",
                    "message": (
                        f"Only the first {max_bids} unique record(s) of this run were carried forward "
                        "(GEM_DIRECT_MAX_BIDS_PER_RUN). Raise the limit or lower max_pages to collect more."
                    ),
                }
            )

        if not filtered_records and keyword_skipped:
            return _result(
                "NO_MATCHING_KEYWORDS",
                (
                    f"None of the {len(unique_records)} collected GeM record(s) matched the configured "
                    "keyword filter. Nothing was persisted."
                ),
                requested_urls=len(targets),
                rejected_urls=len(rejected_urls),
                scrape_errors=len(fetch_errors),
                rows_seen=rows_seen,
                duplicate_rows=duplicate_rows,
                unique_bids=len(unique_records),
                parser_failures=len(parse_failures),
                keyword_skipped=keyword_skipped,
                irrelevant_bids=0,
                detail_enriched=len(enriched),
                detail_failures=sum(1 for e in all_errors if e.get("field") == "detail"),
                received=len(unique_records),
                errors=all_errors,
                extracted_fields=_canonical_field_report(unique_records),
            )

        # --- 5. Existing validation layer --------------------------------
        valid_records, invalid_records = validate_records(filtered_records)
        validation_errors = [
            {"record_index": err.record_index, "field": err.field, "message": err.message}
            for inv in invalid_records
            for err in inv.errors
        ]

        coverage = _coverage(
            rows_seen=rows_seen,
            duplicate_rows=duplicate_rows,
            unique_bids=len(unique_records),
            parser_failures=len(parse_failures),
            keyword_skipped=keyword_skipped,
            irrelevant_bids=0,
            detail_enriched=len(enriched),
            detail_failures=sum(1 for e in all_errors if e.get("field") == "detail"),
        )

        if preview:
            return _result(
                "PREVIEW",
                (
                    f"Fetched {len(filtered_records)} unique GeM bid record(s) from "
                    f"{int(pagination.get('pages_visited') or 0)} listing page(s): "
                    f"{len(valid_records)} valid, {len(invalid_records)} rejected. "
                    "Nothing was persisted (preview mode)."
                ),
                requested_urls=len(targets),
                rejected_urls=len(rejected_urls),
                scrape_errors=len(fetch_errors),
                received=len(filtered_records),
                validated=len(valid_records),
                rejected=len(invalid_records),
                errors=validation_errors + all_errors,
                extracted_fields=_canonical_field_report(filtered_records),
                **coverage,
            )

        # --- 6. CollectionRun audit trail --------------------------------
        run_id = uuid.uuid4()
        run = CollectionRun(
            id=run_id,
            source_adapter="GEM_DIRECT_PUBLIC_ADAPTER",
            started_at=run_started_at,
            status="RUNNING",
            notes=(
                f"Direct GeM public collection by {triggered_by}; "
                f"source_type=direct_public; method={collection_method}; "
                f"urls={len(targets)}; pages={pagination.get('pages_visited')};"
                f"pages_available={pagination.get('pages_available')};"
                f"records_available={pagination.get('records_available')};"
                f"stop_reason={pagination.get('stop_reason')};"
                f"limit_reached={bool(pagination.get('limit_reached'))};"
                f"scope_bid_status_type={(pagination.get('scope') or {}).get('bid_status_type')};"
                f"scope_bid_type={(pagination.get('scope') or {}).get('bid_type')};"
                f"scope_sort={(pagination.get('scope') or {}).get('sort_order')};"
                f"rows_seen={rows_seen}; duplicate_rows={duplicate_rows};"
                f"parser_failures={len(parse_failures)}; page_failures={int(pagination.get('page_failures') or 0)};"
                f" pages_repeated={int(pagination.get('pages_repeated') or 0)};"
                f"bids_capped_at_limit={capped_at_limit};"
                f"keyword_filter={'on' if keyword_filter_enabled(apply_keyword_filter) else 'off'}"
            ),
        )
        db.add(run)
        db.flush()

        for raw_rec in filtered_records:
            db.add(
                RawBidPayload(
                    collection_run_id=run.id,
                    raw_content=raw_rec._raw or raw_rec.model_dump(exclude_none=True),
                    source_reference=raw_rec.source_url or DEFAULT_LISTING_URL,
                )
            )
        db.flush()

        # --- 7. Existing normalize + dedup + relevance filter + persistence ---
        created_bids: List[Bid] = []
        updated_bids: List[Bid] = []
        duplicate_count = 0
        fuzzy_candidates = 0
        fuzzy_suppressed = 0
        irrelevant_count = 0
        _records_since_commit = 0

        for val_rec in valid_records:
            normalized = normalize_record(val_rec.raw)
            dup_result = check_duplicate(db, normalized)
            fuzzy_candidates += dup_result.fuzzy_candidates
            if dup_result.status == "FUZZY_MATCH":
                fuzzy_suppressed += 1

            if dup_result.is_duplicate:
                duplicate_count += 1
                if allow_update_duplicates and dup_result.existing_bid:
                    bid = dup_result.existing_bid
                    if normalized.get("hash") and normalized["hash"] != bid.content_hash:
                        for key, value in normalized.items():
                            column = "content_hash" if key == "hash" else key
                            if (
                                column not in ("id", "created_at")
                                and hasattr(bid, column)
                                and value is not None
                            ):
                                setattr(bid, column, value)
                        bid.last_updated_at = datetime.now(timezone.utc)
                        db.flush()
                        updated_bids.append(bid)
                continue

            # Newly discovered bid: evaluate relevance using 11-product matching engine
            bid_data = dict(normalized)
            bid_data["content_hash"] = bid_data.pop("hash", None)
            bid_data["status"] = "NEW"
            valid_bid_keys = {c.name for c in Bid.__table__.columns}
            candidate_bid = Bid(**{k: v for k, v in bid_data.items() if k in valid_bid_keys})

            # Safe matching evaluation: candidate_bid is not yet attached to db
            try:
                match_results = match_bid_against_products(db, candidate_bid)
                top_match = match_results[0] if match_results else None
                top_score = top_match.relevance_score if top_match else 0.0
                top_state = top_match.match_state if top_match else "NO_MATCH"
                is_relevant = (
                    top_match is not None
                    and top_state in ("MATCH", "POSSIBLE_MATCH", "NEEDS_REVIEW")
                    and top_score >= 0.25
                )
            except Exception as match_exc:
                logger.warning(
                    "Matching evaluation failed for candidate bid %s: %s",
                    candidate_bid.bid_number,
                    match_exc,
                )
                all_errors.append(
                    {
                        "field": "matching",
                        "message": f"Matching evaluation failed for {candidate_bid.bid_number}: {match_exc}",
                    }
                )
                is_relevant = False

            if is_relevant:
                db.add(candidate_bid)
                db.flush()
                created_bids.append(candidate_bid)
            else:
                irrelevant_count += 1

            # Periodically release the SQLite write lock so concurrent writers
            # (e.g. login_attempts inserts during login) are not blocked for the
            # entire duration of a long collection run.
            _records_since_commit += 1
            if _records_since_commit >= 50:
                db.commit()
                _records_since_commit = 0

        coverage["irrelevant_bids"] = irrelevant_count

        # --- Source Discovery Ledger: record every observed GeM bid ----------
        # Every valid record discovered on the source is recorded here,
        # regardless of relevance. NO_MATCH bids are discovered but not
        # persisted as business bids. Relevant bids are both discovered and
        # persisted. This lets reconciliation distinguish "never seen" from
        # "seen but not relevant."
        for val_rec in valid_records:
            normalized = normalize_record(val_rec.raw)
            _record_source_discovery(
                db=db,
                run_id=str(run.id),
                normalized=normalized,
                listing_page=None,
                persisted=False,
                relevance_score=None,
            )

        # After matching decisions, mark relevant bids as persisted in the
        # discovery ledger. Relevance score comes from BidScore if available.
        for bid in created_bids + updated_bids:
            score = None
            try:
                latest = (
                    db.query(BidScore)
                    .filter(BidScore.bid_id == bid.id)
                    .order_by(BidScore.created_at.desc())
                    .first()
                )
                if latest:
                    score = latest.relevance_score
            except Exception:  # noqa: BLE001 - score lookup must not block
                pass
            _record_source_discovery(
                db=db,
                run_id=str(run.id),
                normalized={
                    "gem_bid_id": bid.gem_bid_id,
                    "bid_number": bid.bid_number,
                    "title": bid.title,
                    "organisation": bid.organisation,
                    "category": bid.category,
                    "source_url": bid.source_url,
                    "closing_date": bid.closing_date,
                },
                listing_page=None,
                persisted=True,
                relevance_score=score,
            )

        # --- Commit persisted bid data before network-bound enrichment -----
        # Releases the SQLite write lock before BoQ enrichment makes
        # per-bid network calls. Without this, a long GeM collection run
        # holds the write lock for the entire run, blocking concurrent
        # writes such as login_attempts inserts and causing login timeouts.
        db.commit()

        # --- 8. Existing matching / analysis / notifications --------------
        notifications_count = 0
        llm_provider = DeterministicLLMProvider()
        opp_analyzer = OpportunityAnalyzer()

        # Automatic, bounded BoQ enrichment BEFORE matching, so the engine sees
        # the full published scope instead of the ~99-char listing prefix. Off
        # unless GEM_BOQ_AUTO_ENRICH_ENABLED is set; capped per run; a bid is
        # attempted at most once; a failure is logged and the bid still flows
        # through matching with the data it already had.
        boq_summary = enrich_collected_bids(created_bids + updated_bids)

        for bid in created_bids + updated_bids:
            intel_res = process_bid_intelligence(
                db=db,
                bid=bid,
                llm_provider=llm_provider,
                opp_analyzer=opp_analyzer,
                auto_notify=auto_notify,
                commit=False,
            )
            if intel_res.get("notification_created"):
                notifications_count += 1

        duration = time.perf_counter() - start_time
        run.records_found = len(filtered_records)
        run.records_new = len(created_bids)
        run.records_duplicate = duplicate_count
        run.error_count = len(invalid_records)
        run.finished_at = datetime.now(timezone.utc)
        run.notes = (
            f"{run.notes};fuzzy_candidates={fuzzy_candidates};"
            f"fuzzy_suppressed={fuzzy_suppressed};"
            f"irrelevant_bids={irrelevant_count};"
            f"boq_auto_attempted={boq_summary.get('attempted', 0)};"
            f"boq_auto_enriched={boq_summary.get('enriched', 0)}"
        )

        if len(invalid_records) == len(filtered_records) and len(filtered_records) > 0:
            run.status = "FAILED"
        elif len(invalid_records) > 0:
            run.status = "PARTIAL"
        else:
            run.status = "SUCCESS"

        # Persist the last completed page as a checkpoint for auto-resume.
        # Only SUCCESS and PARTIAL runs contribute a checkpoint; FAILED/BLOCKED
        # runs may not have fully processed their last page.
        # Scheduled monitoring runs write monitoring_completed_page so they
        # never overwrite the historical last_completed_page checkpoint.
        if run.status in ("SUCCESS", "PARTIAL"):
            end_page = pagination.get("end_page")
            if not end_page:
                start = start_page if start_page is not None else 1
                end_page = start + pagination.get("pages_visited", 0) - 1
            if end_page:
                checkpoint_key = (
                    _MONITORING_CHECKPOINT_KEY
                    if triggered_by == "scheduler"
                    else _CHECKPOINT_KEY
                )
                _write_checkpoint_page(db, run, int(end_page), key=checkpoint_key)

        db.commit()

        coverage_note = ""
        if pagination.get("limit_reached") and pagination.get("pages_available"):
            coverage_note = (
                f" Stopped at the configured page budget after "
                f"{pagination.get('pages_visited')} of {pagination.get('pages_available')} "
                f"available page(s); raise GEM_DIRECT_MAX_PAGES / max_pages to collect the rest."
            )
        elif pagination.get("pages_available"):
            coverage_note = (
                f" Walked {pagination.get('pages_visited')} of "
                f"{pagination.get('pages_available')} available page(s)"
                f" covering {pagination.get('records_available')} record(s) offered by the source"
                f" (stop reason: {pagination.get('stop_reason')})."
            )

        irrelevant_note = f", {irrelevant_count} irrelevant (NO_MATCH)" if irrelevant_count else ""
        result = _empty_result(
            run.status,
            (
                f"Direct GeM collection visited {pagination.get('pages_visited')} listing page(s), "
                f"discovered {rows_seen} row(s) ({duplicate_rows} repeated), "
                f"collected {len(filtered_records)} unique bid record(s): "
                f"{len(created_bids)} new, {len(updated_bids)} updated, {duplicate_count} already in the "
                f"database{irrelevant_note}, {len(invalid_records)} rejected by validation. "
                f"{len(parse_failures)} row(s) could not be parsed and "
                f"{int(pagination.get('page_failures') or 0)} page(s) failed."
                f"{coverage_note}"
            ),
            run_id=str(run_id),
            requested_urls=len(targets),
            rejected_urls=len(rejected_urls),
            scrape_errors=len(fetch_errors),
            received=len(filtered_records),
            validated=len(valid_records),
            rejected=len(invalid_records),
            inserted=len(created_bids),
            updated=len(updated_bids),
            duplicates=duplicate_count,
            fuzzy_candidates=fuzzy_candidates,
            fuzzy_suppressed=fuzzy_suppressed,
            boq_enrichment=boq_summary,
            intelligence_processed=len(created_bids) + len(updated_bids),
            notifications_created=notifications_count,
            duration_seconds=round(duration, 3),
            collection_method=collection_method,
            errors=validation_errors + all_errors,
            extracted_fields=_canonical_field_report(filtered_records),
            **coverage,
        )

        _remember(run.status, str(run_id), result)
        return result

    except GeMBlockedError as exc:
        logger.error("Direct GeM collection blocked by the source: %s", exc)
        result = _empty_result(
            "BLOCKED",
            exc.message,
            requested_urls=len(targets) if "targets" in dir() else 0,
            blocked_stage=exc.stage,
            http_status=exc.status_code,
            pages_visited=pagination.get("pages_visited", 0),
            pages_available=pagination.get("pages_available"),
            records_available=pagination.get("records_available"),
            stop_reason="blocked",
            errors=[{"field": f"blocked:{exc.stage}", "message": exc.message}],
        )
        _remember("BLOCKED", None, result)
        return result

    except GeMCollectorError as exc:
        logger.error("Direct GeM collection error: %s", exc)
        result = _empty_result(
            "ERROR",
            exc.message,
            requested_urls=len(targets) if "targets" in dir() else 0,
            blocked_stage=None,
            pages_visited=pagination.get("pages_visited", 0),
            pages_available=pagination.get("pages_available"),
            records_available=pagination.get("records_available"),
            stop_reason="error",
            duration_seconds=round(time.perf_counter() - start_time, 3),
            errors=[{"field": exc.stage, "message": exc.message}],
        )
        _remember("ERROR", str(run.id) if run is not None else None, result)
        return result

    except Exception as exc:  # pragma: no cover - defensive
        db.rollback()
        logger.exception("Unexpected error during direct GeM collection")
        if run is not None:
            failed_run = db.get(CollectionRun, run.id)
            if failed_run:
                failed_run.status = "FAILED"
                failed_run.notes = f"Unexpected failure: {str(exc)}"
                failed_run.finished_at = datetime.now(timezone.utc)
                db.commit()
        result = _empty_result(
            "ERROR",
            f"Direct GeM collection failed: {str(exc)}",
            pages_visited=pagination.get("pages_visited", 0),
            pages_available=pagination.get("pages_available"),
            records_available=pagination.get("records_available"),
            stop_reason="error",
            duration_seconds=round(time.perf_counter() - start_time, 3),
            errors=[{"field": "system", "message": str(exc)}],
        )
        _remember("ERROR", str(run.id) if run is not None else None, result)
        return result

    finally:
        _is_running = False
        _gem_direct_lock.release()


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------
def gem_direct_status_payload() -> Dict[str, Any]:
    """Secret-free status payload for the Data Source page."""
    collector = _shared_collector()
    payload = collector.status()
    payload["source_name"] = "GeM"
    payload["source_type"] = "direct_public"
    payload["source_label"] = "Direct GeM Public Collector"
    payload["is_running"] = is_gem_direct_running()
    payload["requires_credentials"] = False
    payload["scheduler_note"] = (
        "Scheduled collection is disabled. Runs are triggered manually with 'Fetch GeM Bids' "
        "until manual collection has been proven reliable."
    )
    payload["last_run"] = {
        key: value
        for key, value in get_last_gem_direct_run_info().items()
        if key != "last_result"
    }
    return payload


# ---------------------------------------------------------------------------
# Source-to-database reconciliation
# ---------------------------------------------------------------------------
def reconcile_gem_source_to_database(
    db: Session,
    max_pages: Optional[int] = None,
    start_page: int = 1,
    use_browser: Optional[bool] = None,
) -> Dict[str, Any]:
    """
    Reconcile the public GeM listing against the database.

    Walks the GeM listing pages and compares every discovered GeM bid ID
    against the database. Returns a detailed reconciliation report showing
    which source IDs exist in the database, which are missing, and which
    database IDs were not found in the scanned source scope.

    Does NOT modify the database. Read-only.

    Returns a dict with:
      - scope: the listing scope used (URL, filters, sort)
      - pages: pages attempted, completed, failed
      - source_ids: unique GeM IDs discovered on the source
      - db_ids: unique GeM IDs present in the database
      - in_source_not_db: source IDs not found in the database
      - in_db_not_source: database IDs not found in the scanned source scope
      - matched: IDs present in both
      - reconciliation_timestamp: UTC ISO-8601
      - stop_reason: why the walk stopped
      - limit_reached: whether the page budget truncated the walk
    """
    from datetime import timezone as _tz

    # Collect all GeM bid IDs from the database
    db_rows = db.query(Bid.gem_bid_id, Bid.bid_number).all()
    db_gem_ids: Set[str] = set()
    db_bid_numbers: Set[str] = set()
    for gem_id, bid_num in db_rows:
        if gem_id:
            db_gem_ids.add(str(gem_id).strip().upper())
        if bid_num:
            db_bid_numbers.add(str(bid_num).strip().upper())

    # Walk the GeM listing and collect all source IDs
    pages, fetch_errors, methods, pagination = collect_public_pages(
        [DEFAULT_LISTING_URL],
        use_browser=use_browser,
        max_pages=max_pages,
        start_page=start_page,
    )

    # Parse all pages to extract bid references
    adapter = GeMPublicAdapter()
    source_gem_ids: Set[str] = set()
    source_bid_numbers: Set[str] = set()
    rows_seen = 0
    parse_failures = 0

    for page_payload in pages:
        markup = page_payload.get("html", "")
        page_url = page_payload.get("url", DEFAULT_LISTING_URL)
        try:
            records, failures, page_rows = adapter.parse_page_detailed(
                markup, source_url=page_url, source_name="GeM"
            )
            rows_seen += page_rows
            parse_failures += len(failures)
            for record in records:
                if record.gem_bid_id:
                    source_gem_ids.add(str(record.gem_bid_id).strip().upper())
                if record.bid_number:
                    source_bid_numbers.add(str(record.bid_number).strip().upper())
        except Exception:  # noqa: BLE001 - one bad page must not stop reconciliation
            parse_failures += 1

    # Compare sets
    in_source_not_db = source_gem_ids - db_gem_ids
    # Also check by bid_number as a fallback
    for bn in source_bid_numbers:
        if bn not in db_gem_ids and bn not in db_bid_numbers:
            in_source_not_db.add(bn)

    in_db_not_source = db_gem_ids - source_gem_ids
    matched = source_gem_ids & db_gem_ids

    return {
        "scope": pagination.get("scope", {}),
        "pages": {
            "attempted": pagination.get("pages_visited", 0),
            "completed": pagination.get("pages_visited", 0)
            - int(pagination.get("page_failures") or 0),
            "failed": int(pagination.get("page_failures") or 0),
            "available": pagination.get("pages_available"),
        },
        "source_ids": {
            "discovered": len(source_gem_ids),
            "sample": sorted(source_gem_ids)[:10],
        },
        "db_ids": {
            "present": len(db_gem_ids),
            "sample": sorted(db_gem_ids)[:10],
        },
        "in_source_not_db": {
            "count": len(in_source_not_db),
            "sample": sorted(in_source_not_db)[:20],
        },
        "in_db_not_source": {
            "count": len(in_db_not_source),
            "sample": sorted(in_db_not_source)[:20],
        },
        "matched": {
            "count": len(matched),
        },
        "reconciliation_timestamp": datetime.now(_tz.utc).isoformat(),
        "stop_reason": pagination.get("stop_reason"),
        "limit_reached": bool(pagination.get("limit_reached")),
        "rows_seen": rows_seen,
        "parse_failures": parse_failures,
        "errors": fetch_errors,
    }