import hashlib
from typing import List
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.models.bid import Bid
from app.schemas.bid import BidCreate, BidDetailResponse, BidResponse
from app.services.bid_views import is_bid_closed, serialise_all_bids

router = APIRouter()

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
    db: Session = Depends(get_db),
):
    """
    Every stored bid joined with its latest persisted analysis state.

    Each row carries either a real score set produced by the analysis pipeline or
    `analyzed: false` with null scores. Nothing is inferred client-side, so the
    feed can never display a fabricated product match or relevance figure.

    By default only open bids are returned (closed/expired bids are excluded
    from the active view). Set ``include_closed=true`` to include closed bids
    for historical auditing.
    """
    rows = serialise_all_bids(db, include_closed=include_closed)
    rows.sort(
        key=lambda r: (r["published_date"] or r["last_updated_at"] or ""),
        reverse=True,
    )
    return {"total": len(rows), "bids": rows}


@router.post("", response_model=BidResponse, status_code=status.HTTP_201_CREATED)
def create_bid(bid_in: BidCreate, db: Session = Depends(get_db)):
    content_str = f"{bid_in.title}|{bid_in.gem_bid_id}|{bid_in.bid_number}"
    content_hash = hashlib.sha256(content_str.encode("utf-8")).hexdigest()

    bid = Bid(**bid_in.model_dump(), content_hash=content_hash)
    db.add(bid)
    db.commit()
    db.refresh(bid)
    return bid


@router.get("/{bid_id}", response_model=BidDetailResponse)
def get_bid(bid_id: UUID, db: Session = Depends(get_db)):
    bid = db.query(Bid).filter(Bid.id == bid_id).first()
    if not bid:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Bid not found")
    return bid


@router.post("/{bid_id}/match-products", status_code=status.HTTP_200_OK)
def match_products_for_bid(bid_id: UUID, db: Session = Depends(get_db)):
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


from app.api.v1.endpoints.ingestion import import_bids_file
router.add_api_route("/import", import_bids_file, methods=["POST"], response_model=BidResponse if False else None, tags=["Bids"])


