"""
Direct GeM Public Collector Endpoints.

The manual control surface for the direct GeM collector on the Data Source
page. Collection can be triggered manually ("Fetch GeM Bids") and, when
``GEM_DIRECT_SCHEDULER_ENABLED`` is on, also runs automatically on the
configured interval via ``app.services.ingestion.gem_scheduler`` (started
with the backend). Both paths use the same service entry point, so scheduled
and manual runs share one deduplication, update and audit behaviour.

No endpoint in this module requires, accepts, returns or stores a GeM
credential. Status output is derived from configuration only.

SCOPE
    This collects publicly reachable GeM pages. It is not a GeM API client and
    must never be described as an "official GeM API".
"""
from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.services.ingestion.gem_direct_service import (
    DEFAULT_KEYWORDS,
    get_last_gem_direct_run_info,
    gem_direct_status_payload,
    ingest_gem_direct_bids,
)
from app.services.ingestion.gem_scheduler import (
    augment_collection_run_stats,
    next_run_at as scheduler_next_run_at,
)

router = APIRouter()


class GeMDirectFetchRequest(BaseModel):
    urls: Optional[List[str]] = Field(
        default=None,
        description=(
            "Optional explicit allowlisted public GeM URLs. When omitted the "
            "configured public listing page is collected."
        ),
    )
    keywords: Optional[List[str]] = Field(
        default=None,
        description=(
            "Optional keyword pre-filter terms. Only used when apply_keyword_filter is true."
        ),
    )
    apply_keyword_filter: bool = Field(
        default=False,
        description=(
            "Enable the optional source-side keyword pre-filter. Off by default: a small "
            "hardcoded vocabulary removes almost the entire public GeM set, and relevance "
            "belongs to the existing 11-product matching engine, which is unchanged."
        ),
    )
    max_pages: Optional[int] = Field(
        default=None,
        ge=0,
        le=10000,
        description=(
            "Explicit operational budget of listing pages to walk in this run. "
            "0 = unlimited (walk until GeM runs out of pages). Omitted uses "
            "GEM_DIRECT_MAX_PAGES. When the budget truncates the walk the response "
            "reports limit_reached=true."
        ),
    )
    allow_update: bool = Field(
        default=True, description="Apply corrigendum/update changes to existing duplicate bids."
    )
    enrich_detail_pages: Optional[bool] = Field(
        default=None,
        description=(
            "Optionally fetch public detail pages to fill gaps in the listing rows. "
            "Off by default and strictly additive: it can only add fields to bids the "
            "listing already proved exist, never add or remove a bid. Bounded by "
            "GEM_DIRECT_MAX_DETAIL_PAGES. Omitted uses GEM_DIRECT_ENRICH_DETAIL_PAGES."
        ),
    )
    auto_notify: bool = Field(default=True, description="Run existing notification rules.")
    preview: bool = Field(
        default=False, description="Validate and report only; persist nothing."
    )


class GeMDirectFetchResponse(BaseModel):
    run_id: Optional[str] = None
    status: str
    source: str = "gem_direct"
    source_name: str = "GeM"
    source_type: str = "direct_public"
    message: str
    requested_urls: int = 0
    rejected_urls: int = 0
    scrape_errors: int = 0
    pages_visited: int = 0
    pages_available: Optional[int] = None
    records_available: Optional[int] = None
    stop_reason: Optional[str] = None
    limit_reached: bool = False
    # GeM's own Advance Search scope used for this run (bid status, bid kind,
    # sort), so the caller can see which population the counters describe.
    scope: Dict[str, Any] = Field(default_factory=dict)
    rows_seen: int = 0
    duplicate_rows: int = 0
    unique_bids: int = 0
    parser_failures: int = 0
    page_failures: int = 0
    detail_enriched: int = 0
    detail_failures: int = 0
    keyword_skipped: int = 0
    received: int = 0
    validated: int = 0
    rejected: int = 0
    inserted: int = 0
    updated: int = 0
    duplicates: int = 0
    # Fuzzy-title dedup activity reported by the detector for this run.
    fuzzy_candidates: int = 0
    fuzzy_suppressed: int = 0
    intelligence_processed: int = 0
    notifications_created: int = 0
    duration_seconds: float = 0.0
    collection_method: Optional[str] = None
    blocked_stage: Optional[str] = None
    http_status: Optional[int] = None
    errors: List[Dict[str, Any]] = []
    extracted_fields: List[Dict[str, Any]] = []
    records: List[Any] = []


class GeMDirectStatusResponse(BaseModel):
    source: str
    provider: str
    source_name: str
    source_type: str
    source_label: str
    configured: bool
    status: str  # NOT_CONFIGURED | READY | RUNNING | SUCCESS | BLOCKED | ERROR
    allowed_hosts: List[str] = []
    listing_url: str
    timeout_seconds: int = 0
    max_retries: int = 0
    request_interval_seconds: float = 0.0
    max_urls_per_run: int = 0
    pagination_enabled: bool = False
    max_pages: int = 0
    max_pages_unlimited: bool = False
    records_per_page: int = 0
    max_bids_per_run: int = 0
    bid_status_type: str = "ongoing_bids"
    sort_order: str = "Bid-Start-Date-Latest"
    keyword_filter_enabled: bool = False
    detail_enrichment_enabled: bool = False
    max_detail_pages: int = 0
    scheduler_enabled: bool = False
    scheduler_interval_minutes: int = 0
    scheduler_note: str = ""
    scheduler_next_run: Optional[str] = None
    requires_credentials: bool = False
    blocked: bool = False
    is_running: bool = False
    default_keywords: List[str] = []
    last_run: Dict[str, Any] = {}
    last_run_stats: Dict[str, Any] = {}


# Counters from the most recent run that the Data Source page renders under
# "Latest statistics". Taken from the in-process run record (cleared on
# restart, same as ``last_run``); never includes fetched records themselves.
_LAST_RUN_STAT_KEYS = (
    "rows_seen",
    "received",
    "validated",
    "rejected",
    "inserted",
    "updated",
    "duplicates",
    "intelligence_processed",
    "notifications_created",
    "duration_seconds",
    "stop_reason",
    "limit_reached",
)


def _last_run_stats() -> Dict[str, Any]:
    last_result = get_last_gem_direct_run_info().get("last_result") or {}
    return {key: last_result.get(key) for key in _LAST_RUN_STAT_KEYS if key in last_result}


@router.get("/gem-direct/status", response_model=GeMDirectStatusResponse, status_code=status.HTTP_200_OK)
def get_gem_direct_status():
    """Return the configuration and last-run state of the direct GeM collector."""
    payload = gem_direct_status_payload()
    payload["default_keywords"] = list(DEFAULT_KEYWORDS)
    if payload.get("is_running"):
        payload["status"] = "RUNNING"
    if payload.get("scheduler_enabled"):
        interval = int(payload.get("scheduler_interval_minutes") or 60)
        payload["scheduler_note"] = (
            f"Automatic collection is enabled: a collection runs every {interval} minute(s) "
            "using the existing bounded page budget, at the configured request interval. "
            "Scheduled and manual runs never overlap."
        )
        payload["scheduler_next_run"] = scheduler_next_run_at()
    else:
        payload["scheduler_next_run"] = None
    payload["last_run_stats"] = _last_run_stats()
    return payload


@router.post("/gem-direct/fetch", response_model=GeMDirectFetchResponse, status_code=status.HTTP_200_OK)
def fetch_gem_bids(payload: GeMDirectFetchRequest, db: Session = Depends(get_db)):
    """
    Manually collect public GeM bid records and push them through the existing
    ingestion and intelligence pipeline.

    The collector walks the listing's real pagination, so it collects every page
    the source makes available up to the configured page budget. If the budget
    truncates the walk, ``limit_reached`` is true and the reason is reported.

    If GeM refuses automated collection the run stops with status ``BLOCKED``
    and the blocking stage is reported. No bypass is attempted.
    """
    result = ingest_gem_direct_bids(
        db=db,
        urls=payload.urls,
        keywords=payload.keywords,
        allow_update_duplicates=payload.allow_update,
        auto_notify=payload.auto_notify,
        triggered_by="data_source_ui",
        preview=payload.preview,
        apply_keyword_filter=payload.apply_keyword_filter,
        max_pages=payload.max_pages,
        enrich_detail_pages=payload.enrich_detail_pages,
    )
    # Persist the full counter set on the audit row (validated / inserted /
    # updated / duplicates / rejected / errors / duration / truncated), the
    # same augmentation every scheduled run records. No-op without a run_id.
    augment_collection_run_stats(db, result.get("run_id"), result)

    if result.get("status") == "BUSY":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=result.get("message"))
    if result.get("status") == "NOT_CONFIGURED":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=result.get("message"))
    return result