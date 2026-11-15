import hashlib
import io
import logging
import re
import sqlite3
import time
from datetime import datetime, timezone
from typing import List, Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy import and_, asc, desc, func, or_
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.api.v1.dependencies import require_admin, require_operator, require_viewer
from app.models.bid import Bid
from app.models.source import DataSource
from app.models.analysis import BidScore, BidProductMatch
from app.schemas.bid import BidCreate, BidDetailResponse, BidResponse
from app.services.bid_views import is_bid_closed, serialise_all_bids, serialise_bid, days_remaining, deadline_status
from app.models.user import User
from app.services.ingestion.gem_document_extractor import download_document, is_pdf_document_url
from app.services.ingestion.gem_public_collector import validate_public_url

logger = logging.getLogger(__name__)
router = APIRouter()

# ---------------------------------------------------------------------------
# SQLite concurrency retry helper
# ---------------------------------------------------------------------------
# When the per-source scheduler threads and API requests both write to the
# shared SQLite database, ``sqlite3.OperationalError: database is locked`` can
# occur. WAL mode + busy_timeout (set in database.py) handle most contention,
# but a bounded retry with backoff makes the match-all endpoint robust under
# concurrent load.
def _retry_on_db_lock(fn, max_retries: int = 5, base_delay: float = 0.25):
    """Retry a callable on sqlite3 'database is locked' errors with backoff."""
    last_exc = None
    for attempt in range(max_retries):
        try:
            return fn()
        except sqlite3.OperationalError as exc:
            last_exc = exc
            if "locked" not in str(exc).lower():
                raise
            delay = base_delay * (2 ** attempt)
            logger.warning(
                "Database locked on attempt %d/%d, retrying in %.2fs: %s",
                attempt + 1, max_retries, delay, exc,
            )
            time.sleep(delay)
    raise last_exc

# A stored product match must rest on real bidding evidence. Only candidates the
# engine positively classified (at least NEEDS_REVIEW, i.e. score >= 0.25) with a
# genuine positive/regular signal may be persisted. A NO_MATCH candidate -- or a
# candidate whose only signals are exclusions -- carries no evidence of relevance
# and must never be stored as if it matched.
_PERSISTABLE_STATES = frozenset({"MATCH", "POSSIBLE_MATCH", "NEEDS_REVIEW"})


def _candidate_has_confirmed_interest(res) -> bool:
    """True when a match result is a genuine, evidence-backed product candidate."""
    if res.match_state not in _PERSISTABLE_STATES or res.relevance_score < 0.25:
        return False
    return any(s.get("strength") != "EXCLUSION" for s in res.signals)


@router.get("", response_model=List[BidResponse])
def list_bids(
    include_closed: bool = False,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(require_viewer),
):
    """
    Return stored bids, ordered newest-first.

    By default only open bids are returned (closed/expired bids are excluded
    from the active view). Set ``include_closed=true`` to include closed bids
    for historical auditing.

    No artificial row cap is applied: the bid volume is a property of the data,
    not a hardcoded constant. Use `/intelligence` when the client also needs the
    real analysis state of each bid.
    """
    query = db.query(Bid).order_by(Bid.last_updated_at.desc())
    if not include_closed:
        # Filter in Python because closed status is derived from closing_date,
        # not a stored column. For large datasets this could be moved to SQL.
        all_bids = query.all()
        return [b for b in all_bids if not is_bid_closed(b)]
    return query.all()


@router.get("/intelligence")
def list_bid_intelligence(
    include_closed: bool = False,
    page: Optional[int] = None,
    page_size: Optional[int] = None,
    search: Optional[str] = None,
    sort: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(require_viewer),
):
    """
    Every stored bid joined with its latest persisted analysis state.

    Each row carries either a real score set produced by the analysis pipeline or
    `analyzed: false` with null scores. Nothing is inferred client-side, so the
    feed can never display a fabricated product match or relevance figure.

    When neither ``page`` nor ``page_size`` is supplied, every matching bid is
    returned (backward compatible with the pre-pagination behaviour). When either
    is supplied, server-side pagination is applied so the client never has to load
    the entire bid table (tens of thousands of rows) into the browser; only the
    scores for the bids on the current page are fetched, which keeps the endpoint
    fast even as the bid table grows.

    By default only open bids are returned (closed/expired bids are excluded
    from the active view). Set ``include_closed=true`` to include closed bids
    for historical auditing.

    Query params:
      - ``page``: 1-based page number (required together with ``page_size`` to
        enable pagination; omitted returns all matching bids)
      - ``page_size``: rows per page, capped at 100 (default 50 when paginating)
      - ``search``: substring filter on title / bid number / GeM bid ID /
        organisation (applied in SQL)
      - ``sort``: ``published`` (newest first), ``relevance``, ``deadline``,
        ``value`` (default ``published``)
    """
    now = datetime.now(timezone.utc)
    paginating = page is not None or page_size is not None
    if paginating:
        page = max(1, page or 1)
        page_size = max(1, min(100, page_size or 50))
    else:
        page = 1
        page_size = None  # sentinel: no cap, return all

    # Open-bid condition (closing_date in the future or NULL).
    open_cond = or_(
        Bid.closing_date.is_(None),
        Bid.closing_date >= now,
    )
    if include_closed:
        open_cond = or_(open_cond, and_(
            Bid.closing_date.is_not(None),
            Bid.closing_date < now,
        ))

    base_query = db.query(Bid).filter(open_cond)
    if search:
        term = f"%{search}%"
        base_query = base_query.filter(
            or_(
                Bid.title.ilike(term),
                Bid.bid_number.ilike(term),
                Bid.gem_bid_id.ilike(term),
                Bid.organisation.ilike(term),
            )
        )

    # Total count before pagination (SQL count, no rows materialised).
    total = base_query.with_entities(func.count(Bid.id)).scalar() or 0

    # Ordering (mirrors the frontend sort keys so results are stable).
    if sort == "relevance":
        # Cannot order by relevance in SQL without joining scores; keep newest
        # first and let the client re-sort the small page if needed.
        order_clauses = [desc(Bid.published_date).nullslast(), desc(Bid.last_updated_at).nullslast()]
    elif sort == "deadline":
        order_clauses = [asc(Bid.closing_date).nullslast(), desc(Bid.published_date).nullslast()]
    elif sort == "value":
        order_clauses = [desc(Bid.estimated_value).nullslast(), desc(Bid.published_date).nullslast()]
    else:
        order_clauses = [desc(Bid.published_date).nullslast(), desc(Bid.last_updated_at).nullslast()]

    if paginating:
        bid_rows = (
            base_query.order_by(*order_clauses)
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
    else:
        # Backward compatible: return every matching bid (no row cap).
        bid_rows = base_query.order_by(*order_clauses).all()

    # Only load the latest score for the bids actually on this page (or all bids
    # when not paginating).
    bid_ids = [str(b.id) for b in bid_rows]
    scores: dict = {}
    if bid_ids:
        latest_subq = (
            db.query(
                BidScore.bid_id,
                func.max(BidScore.created_at).label("max_created"),
            )
            .filter(BidScore.bid_id.in_(bid_ids))
            .group_by(BidScore.bid_id)
            .subquery("latest_score")
        )
        scores = {
            str(s.bid_id): s
            for s in db.query(BidScore).join(
                latest_subq,
                and_(
                    BidScore.bid_id == latest_subq.c.bid_id,
                    BidScore.created_at == latest_subq.c.max_created,
                ),
            ).all()
        }

    rows = [serialise_bid(b, scores.get(str(b.id))) for b in bid_rows]

    # Client-friendly re-sort for relevance (needs scores) when requested.
    if sort == "relevance" and not paginating:
        rows.sort(
            key=lambda r: (r["relevance_score"] or -1),
            reverse=True,
        )

    if paginating:
        total_pages = (total + page_size - 1) // page_size
        return_page_size = page_size
    else:
        total_pages = 1
        return_page_size = len(rows)

    return {
        "total": total,
        "page": page,
        "page_size": return_page_size,
        "total_pages": total_pages,
        "bids": rows,
    }


@router.get("/state-wise")
def list_state_wise_bids(
    state: Optional[str] = None,
    source: Optional[str] = None,
    search: Optional[str] = None,
    product: Optional[str] = None,
    match_status: Optional[str] = None,
    bid_status: Optional[str] = None,
    page: int = 1,
    page_size: int = 50,
    include_no_match: bool = False,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(require_viewer),
):
    """
    Return state-wise bids (excludes GeM bids).

    Each row includes state identity from the data source registry and all
    persisted product matches (one row per matched product). Supports filtering
    by state, source, search, product, match status, bid status, with pagination.

    Set include_no_match=true to also surface tenders with NO_MATCH or no
    analysis at all (for auditing). By default only bids with at least one
    qualifying product match are returned.
    """
    from app.models.product import Product

    # Base query: bids joined with data sources (state sources only).
    # Join on Bid.source_id == DataSource.id (authoritative attribution set at
    # collection time) instead of the fragile Bid.source_name == DataSource.name
    # string join, which split states whose portal display name has variants
    # (e.g. "Jammu & Kashmir" vs "Jammu and Kashmir"). Bids without a source_id
    # still match via source_name for backward compatibility; GeM bids (source_id
    # NULL) are excluded explicitly below, so GeM never appears in state views.
    #
    # .distinct() prevents duplicate (Bid, DataSource) rows when a bid satisfies
    # both the source_id and source_name join conditions, which would otherwise
    # produce duplicate bid cards in the state-wise view.
    query = db.query(Bid, DataSource).join(
        DataSource,
        or_(Bid.source_id == DataSource.id, Bid.source_name == DataSource.name),
    ).distinct()

    # Belt-and-suspenders: exclude GeM bids explicitly
    query = query.filter(~Bid.source_name.ilike('%gem%'))

    # Filter by state (DataSource.source_id)
    if state:
        query = query.filter(DataSource.source_id == state)

    # Filter by source (same as state, for API compatibility)
    if source:
        query = query.filter(DataSource.source_id == source)

    # Search by bid number, tender ID, title, organisation
    if search:
        search_term = f"%{search}%"
        query = query.filter(
            or_(
                Bid.bid_number.ilike(search_term),
                Bid.gem_bid_id.ilike(search_term),
                Bid.title.ilike(search_term),
                Bid.organisation.ilike(search_term),
            )
        )

    results = query.all()

    # Get scores for all matching bids
    bid_ids = [str(bid.id) for bid, _ in results]
    scores = {}
    if bid_ids:
        score_rows = db.query(BidScore).filter(BidScore.bid_id.in_(bid_ids)).all()
        for sr in score_rows:
            scores[str(sr.bid_id)] = sr

    # Get all product matches for these bids, joined with product name
    product_matches: dict[str, list] = {str(bid.id): [] for bid, _ in results}
    if bid_ids:
        pm_rows = (
            db.query(BidProductMatch, Product.name.label("product_name"))
            .join(Product, BidProductMatch.product_id == Product.id)
            .filter(BidProductMatch.bid_id.in_(bid_ids))
            .all()
        )
        for pm, pname in pm_rows:
            product_matches.setdefault(str(pm.bid_id), []).append({
                "product_id": str(pm.product_id),
                "product_name": pname,
                "match_score": pm.match_score,
                "match_type": pm.match_type,
                "confidence": pm.confidence,
                "evidence": pm.evidence,
            })

    # Build serialized rows — one row per (bid, product_match) combination,
    # plus one row for bids with no matches (when include_no_match=true).
    rows = []
    for bid, ds in results:
        score = scores.get(str(bid.id))
        matches = product_matches.get(str(bid.id), [])

        # Compute deadline status
        days = days_remaining(bid.closing_date)
        dl_status = deadline_status(days)

        # Filter by bid status: OPEN, CLOSED, CLOSING_SOON
        if bid_status:
            if bid_status == 'OPEN' and dl_status != 'OPEN':
                continue
            elif bid_status == 'CLOSED' and dl_status != 'CLOSED':
                continue
            elif bid_status == 'CLOSING_SOON' and dl_status not in ('CLOSING_SOON', 'URGENT'):
                continue

        # If no matches and not including no-match bids, skip entirely
        if not matches and not include_no_match:
            continue

        # Determine best match for top-level display fields
        best_match = None
        best_score = None
        best_state = None
        if matches:
            best_match = max(matches, key=lambda m: m["match_score"])
            best_score = best_match["match_score"]
            best_state = (best_match.get("evidence") or {}).get("match_state")

        # Filter by product (match against any product match on this bid)
        if product:
            if not any(m["product_name"] == product for m in matches):
                continue

        # Filter by match status (match against any product match on this bid)
        if match_status:
            if not any(
                (m.get("evidence") or {}).get("match_state") == match_status
                for m in matches
            ):
                continue

        base_row = {
            "id": str(bid.id),
            "state": ds.name,
            "state_id": ds.source_id,
            "source": ds.name,
            "source_id": ds.source_id,
            "adapter_key": ds.adapter_key,
            "bid_number": bid.bid_number,
            "gem_bid_id": bid.gem_bid_id,
            "tender_id": bid.bid_number or bid.gem_bid_id,
            "title": bid.title,
            "organisation": bid.organisation,
            "department": bid.department,
            "matched_product": best_match["product_name"] if best_match else None,
            "match_state": best_state,
            "relevance_score": round(best_score, 3) if best_score is not None else None,
            "analyzed": score is not None,
            "estimated_value": float(bid.estimated_value) if bid.estimated_value is not None else None,
            "currency": bid.currency,
            "published_date": bid.published_date.isoformat() if bid.published_date else None,
            "closing_date": bid.closing_date.isoformat() if bid.closing_date else None,
            "days_remaining": days,
            "deadline_status": dl_status,
            "status": bid.status,
            "matching_status": bid.matching_status,
            "matched_at": bid.matched_at.isoformat() if bid.matched_at else None,
            "source_url": bid.source_url,
            "original_bid_url": bid.original_bid_url,
            "product_matches": matches,
            "matched_product_count": len(matches),
        }

        if matches:
            # One row per matched product (each product match gets its own row)
            for m in matches:
                row = dict(base_row)
                row["matched_product"] = m["product_name"]
                row["product_id"] = m["product_id"]
                row["match_score"] = m["match_score"]
                row["match_type"] = m["match_type"]
                row["confidence"] = m["confidence"]
                row["match_state"] = (m.get("evidence") or {}).get("match_state")
                row["explanation"] = (m.get("evidence") or {}).get("reason", "")
                row["matching_keywords"] = [
                    s.get("keyword", "")
                    for s in (m.get("evidence") or {}).get("signals", [])
                    if s.get("strength") != "EXCLUSION"
                ]
                rows.append(row)
        else:
            # No matches — include as a single row when include_no_match=true
            row = dict(base_row)
            row["product_id"] = None
            row["match_score"] = None
            row["match_type"] = None
            row["confidence"] = None
            row["match_state"] = None
            row["explanation"] = ""
            row["matching_keywords"] = []
            rows.append(row)

    # Sort by published date descending
    rows.sort(key=lambda r: (r['published_date'] or r.get('last_updated_at') or ''), reverse=True)

    # Paginate
    total = len(rows)
    page = max(1, page)
    page_size = max(1, min(100, page_size))
    start = (page - 1) * page_size
    end = start + page_size
    paginated = rows[start:end]

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size,
        "bids": paginated,
    }


@router.get("/state-wise/summary")
def state_wise_summary(
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(require_viewer),
):
    """
    Per-state summary of collected and matched bids.

    Returns one row per configured data source with: collected bid count,
    matched bid count (bids with at least one persisted product match), match
    record count, the source's collection status, last successful run, last
    error, and the last SourceRun status. GeM bids are excluded.
    """
    from sqlalchemy import func

    # Collected bids per state (authoritative source_id attribution).
    collected_subq = (
        db.query(Bid.source_id, func.count(Bid.id).label("collected"))
        .filter(Bid.source_id.is_not(None))
        .group_by(Bid.source_id)
        .subquery()
    )

    # Matched bids per state (distinct bids with at least one product match).
    matched_subq = (
        db.query(Bid.source_id, func.count(func.distinct(BidProductMatch.bid_id)).label("matched"))
        .join(BidProductMatch, BidProductMatch.bid_id == Bid.id)
        .filter(Bid.source_id.is_not(None))
        .group_by(Bid.source_id)
        .subquery()
    )

    rows = (
        db.query(
            DataSource,
            func.coalesce(collected_subq.c.collected, 0).label("collected"),
            func.coalesce(matched_subq.c.matched, 0).label("matched"),
        )
        .outerjoin(collected_subq, collected_subq.c.source_id == DataSource.id)
        .outerjoin(matched_subq, matched_subq.c.source_id == DataSource.id)
        .order_by(DataSource.name.asc())
        .all()
    )

    summary = []
    for ds, collected, matched in rows:
        summary.append(
            {
                "source_id": ds.source_id,
                "name": ds.name,
                "status": ds.status or "IDLE",
                "enabled": ds.enabled,
                "collected": int(collected or 0),
                "matched": int(matched or 0),
                "last_success_at": ds.last_success_at.isoformat()
                if ds.last_success_at
                else None,
                "last_attempt_at": ds.last_attempt_at.isoformat()
                if ds.last_attempt_at
                else None,
                "last_error": ds.last_error,
                "last_inserted": ds.last_inserted or 0,
                "total_inserted": ds.total_inserted or 0,
            }
        )

    return {"states": summary, "total_states": len(summary)}


@router.post("", response_model=BidResponse, status_code=status.HTTP_201_CREATED)
def create_bid(
    bid_in: BidCreate,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(require_operator),
):
    content_str = f"{bid_in.title}|{bid_in.gem_bid_id}|{bid_in.bid_number}"
    content_hash = hashlib.sha256(content_str.encode("utf-8")).hexdigest()

    bid = Bid(**bid_in.model_dump(), content_hash=content_hash)
    db.add(bid)
    db.commit()
    db.refresh(bid)
    return bid


@router.get("/{bid_id}", response_model=BidDetailResponse)
def get_bid(
    bid_id: UUID,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(require_viewer),
):
    bid = db.query(Bid).filter(Bid.id == bid_id).first()
    if not bid:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Bid not found")
    return bid


@router.get("/{bid_id}/download-pdf")
def download_bid_pdf(
    bid_id: UUID,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(require_viewer),
):
    """
    Download the original bid document (PDF) from the source portal.

    Only GeM bid-document URLs (``showbidDocument/<id>``) are served. Every
    target passes the public-URL / host-allowlist guard before any socket is
    opened, so the endpoint cannot be turned into an SSRF or arbitrary-file
    fetcher. Downloaded bytes are validated as a real PDF (magic bytes, size
    and timeout caps) before being streamed back with a safe filename that
    carries the bid reference.

    Returns 404 ("Original PDF not available") when the bid has no downloadable
    original document on record.
    """
    bid = db.query(Bid).filter(Bid.id == bid_id).first()
    if not bid:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Bid not found")

    # The original bid portal URL is the authoritative source of the document.
    url = bid.original_bid_url or bid.source_url
    if not url or not is_pdf_document_url(url):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Original PDF not available for this bid.",
        )

    # SSRF / trusted-domain guard: only public http(s) GeM hosts may be fetched.
    try:
        validate_public_url(url)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Document URL is not fetchable: {exc}",
        ) from exc

    # Download + validate (magic bytes, size, timeout). Never raises on failure.
    result = download_document(url)
    if not result.success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Original PDF not available: {result.error or 'download failed'}",
        )

    raw = getattr(result, "_raw_bytes", None)
    if not raw:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Original PDF not available: no document content.",
        )

    # Safe filename carrying the bid reference; strip any unsafe characters.
    ref = bid.gem_bid_id or bid.bid_number or str(bid.id)
    safe_ref = re.sub(r"[^A-Za-z0-9._-]", "_", ref)[:60] or "unknown"
    filename = f"bid_{safe_ref}_original.pdf"

    return StreamingResponse(
        io.BytesIO(raw),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length": str(len(raw)),
            "Cache-Control": "no-store",
        },
    )


@router.post("/{bid_id}/match-products", status_code=status.HTTP_200_OK)
def match_products_for_bid(
    bid_id: UUID,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(require_operator),
):
    """
    Run deterministic bid-to-product matching engine for a bid and persist the results.
    """
    bid = db.query(Bid).filter(Bid.id == bid_id).first()
    if not bid:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Bid not found")

    from app.services.intelligence import match_bid_against_products
    from app.models.analysis import BidProductMatch, BidAnalysis

    match_results = match_bid_against_products(db, bid)

    # Clean existing matches for this bid to persist fresh analysis
    db.query(BidProductMatch).filter(BidProductMatch.bid_id == bid.id).delete()

    persisted_matches = []
    for res in match_results:
        # A stored product match must rest on real matching evidence. Reject the
        # two ways a candidate could otherwise be persisted without earning it:
        #  * a NO_MATCH candidate (score below the NEEDS_REVIEW band), and
        #  * a candidate whose signals are only exclusions (score dragged above
        #    the band would be impossible; this guards the stored record anyway).
        if not _candidate_has_confirmed_interest(res):
            continue
        match_rec = BidProductMatch(
            bid_id=bid.id,
            product_id=UUID(res.product_id),
            match_score=res.relevance_score,
            match_type="DETERMINISTIC_PHASE3",
            confidence=res.confidence,
            evidence={
                "match_state": res.match_state,
                "signals": res.signals,
                "score_breakdown": res.score_breakdown,
                "reason": res.reason,
            },
        )
        db.add(match_rec)
        persisted_matches.append(res)

    # Persist BidAnalysis aggregate
    analysis = BidAnalysis(
        bid_id=bid.id,
        engine_version="Phase3-Deterministic",
        model_used="None (Deterministic Engine)",
        product_matches=[r.to_dict() for r in match_results],
        evidence=[r.signals for r in match_results if r.signals],
    )
    db.add(analysis)
    db.commit()

    return {
        "bid_id": str(bid.id),
        "bid_title": bid.title,
        "total_products_evaluated": len(match_results),
        "candidate_products": [r.to_dict() for r in match_results],
    }


@router.post("/state-wise/match-all")
def match_all_state_wise_tenders(
    batch_size: int = 50,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(require_operator),
):
    """
    Batch-match every eligible state-wise tender against all 11 SecuredApp products.

    For each state-source bid (GeM bids are excluded), the deterministic matching
    engine evaluates the tender against every active product. Qualifying matches
    (score >= 0.25 / NEEDS_REVIEW band with at least one non-exclusion signal)
    are persisted as BidProductMatch records. Each bid's matching_status is
    updated to track batch progress (PENDING -> PROCESSING -> COMPLETED/FAILED).

    Supports retry: bids with matching_status='FAILED' are reprocessed.
    Batches are processed sequentially to avoid overloading the application.

    Returns a summary of processing results.
    """
    from app.services.intelligence import match_bid_against_products
    from app.models.analysis import BidProductMatch, BidAnalysis
    from datetime import datetime, timezone

    _PERSISTABLE_STATES = frozenset({"MATCH", "POSSIBLE_MATCH", "NEEDS_REVIEW"})

    def _candidate_has_confirmed_interest(res) -> bool:
        if res.match_state not in _PERSISTABLE_STATES or res.relevance_score < 0.25:
            return False
        return any(s.get("strength") != "EXCLUSION" for s in res.signals)

    # Base query: state-source bids only (exclude GeM bids).
    # Join on Bid.source_id == DataSource.id (authoritative attribution), with
    # source_name fallback for bids collected before source_id was backfilled.
    # Include PENDING (never processed) and FAILED (retry) bids.
    query = db.query(Bid).join(
        DataSource,
        or_(Bid.source_id == DataSource.id, Bid.source_name == DataSource.name),
    ).filter(
        Bid.matching_status.in_(["PENDING", "FAILED"]),
    )

    total_eligible = query.count()
    if total_eligible == 0:
        return {
            "processed": 0,
            "matches_persisted": 0,
            "total_eligible": 0,
            "detail": "No eligible state-wise tenders to match.",
        }

    processed = 0
    matches_persisted = 0
    failed = 0
    batch_count = 0

    # Process in batches
    offset = 0
    while True:
        batch = query.offset(offset).limit(batch_size).all()
        if not batch:
            break
        batch_count += 1

        for bid in batch:
            try:
                bid.matching_status = "PROCESSING"
                bid.matched_at = datetime.now(timezone.utc)
                db.add(bid)
                db.flush()

                match_results = match_bid_against_products(db, bid)

                # Clean existing matches for this bid to persist fresh analysis
                db.query(BidProductMatch).filter(BidProductMatch.bid_id == bid.id).delete()

                persisted_for_bid = 0
                for res in match_results:
                    if not _candidate_has_confirmed_interest(res):
                        continue
                    db.add(
                        BidProductMatch(
                            bid_id=bid.id,
                            product_id=UUID(res.product_id),
                            match_score=res.relevance_score,
                            match_type="DETERMINISTIC_PHASE3",
                            confidence=res.confidence,
                            evidence={
                                "match_state": res.match_state,
                                "signals": res.signals,
                                "score_breakdown": res.score_breakdown,
                                "reason": res.reason,
                            },
                        )
                    )
                    matches_persisted += 1
                    persisted_for_bid += 1

                # Persist BidAnalysis aggregate
                analysis = BidAnalysis(
                    bid_id=bid.id,
                    engine_version="Phase3-Deterministic",
                    model_used="None (Deterministic Engine)",
                    product_matches=[r.to_dict() for r in match_results],
                    evidence=[r.signals for r in match_results if r.signals],
                )
                db.add(analysis)

                bid.matching_status = "COMPLETED"
                db.add(bid)
                processed += 1

            except Exception:
                bid.matching_status = "FAILED"
                db.add(bid)
                failed += 1

        _retry_on_db_lock(lambda: db.commit())
        offset += batch_size

    return {
        "processed": processed,
        "matches_persisted": matches_persisted,
        "failed": failed,
        "total_eligible": total_eligible,
        "batches": batch_count,
        "detail": f"Matched {processed} of {total_eligible} state-wise tender(s); "
                  f"persisted {matches_persisted} product-match record(s).",
    }


from app.api.v1.endpoints.ingestion import import_bids_file
router.add_api_route("/import", import_bids_file, methods=["POST"], response_model=BidResponse if False else None, tags=["Bids"])
