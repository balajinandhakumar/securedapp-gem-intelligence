"""
All-India product-relevant GeM bid matching dashboard.

Read-only aggregation over persisted GeM bids and their stored bid-to-product
matches. Nothing here is estimated, sampled, or fabricated: a bid only appears
when it has a genuine, persisted product match with a relevance score of 50/100
(0.50) or higher.

One GeM bid can match multiple SecuredApp products. The database holds a single
``Bid`` row with multiple ``BidProductMatch`` rows; this endpoint exposes every
matching product per bid so no relevant product match is hidden.

Geographic information comes from the bid's own ``location`` field (plus
``department`` / ``organisation``). When a tender does not specify a location it
is reported as ``Location Not Specified`` -- a state is never invented or
guessed from free text.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func, or_

from app.core.database import get_db
from app.core.logging import logger
from app.api.v1.dependencies import require_admin, require_operator, require_viewer
from app.models.analysis import BidProductMatch
from app.models.bid import Bid
from app.models.product import Product
from app.models.user import User

router = APIRouter()

# ---------------------------------------------------------------------------
# Classification (0-100 score, display bands for the All-India dashboard)
# ---------------------------------------------------------------------------
# The deterministic matching engine (app/services/intelligence/matching_engine.py)
# is intentionally left untouched: it scores on a 0-1 scale with its own
# four-band rule (MATCH >= 0.70, POSSIBLE_MATCH >= 0.45, NEEDS_REVIEW >= 0.25).
# This helper only converts that normalized score to a 0-100 figure and applies
# the All-India dashboard's display bands for presentation.
#   85-100: Highly Relevant
#   70-84 : Relevant
#   50-69 : Potentially Relevant
#   < 50  : Not Relevant
DISPLAY_MIN_SCORE_0_1 = 0.50  # only matches of 50/100 or above are displayed


def classify_all_india(score_0_1: Optional[float]) -> Dict[str, Any]:
    """Convert a normalized 0-1 score to 0-100 plus a display classification."""
    score_100 = 0
    classification = "Not Relevant"
    if score_0_1 is not None:
        score_100 = int(round(max(0.0, min(1.0, float(score_0_1))) * 100))
        if score_100 >= 85:
            classification = "Highly Relevant"
        elif score_100 >= 70:
            classification = "Relevant"
        elif score_100 >= 50:
            classification = "Potentially Relevant"
        else:
            classification = "Not Relevant"
    return {"score_100": score_100, "classification": classification}


# ---------------------------------------------------------------------------
# Location extraction (Issue 1 — All India location display)
#
# Location is extracted ONLY from the bid's own ``location`` field, which is
# the single authoritative geographic column on the Bid model. No state is
# ever invented or guessed from free text, buyer names, or source domains.
#
# Data-quality states:
#   AVAILABLE      — a genuine location value was found and normalized
#   NOT_DISCLOSED  — the source did not publish a location (null/empty)
#   EXTRACTION_FAILED — the stored value looked like boilerplate/HTML text,
#                        not a real location
# ---------------------------------------------------------------------------

# Common state abbreviations and variants → normalized full state name.
_STATE_ALIASES = {
    'tn': 'Tamil Nadu', 'tamil nadu': 'Tamil Nadu',
    'mh': 'Maharashtra', 'maharashtra': 'Maharashtra',
    'ka': 'Karnataka', 'karnataka': 'Karnataka',
    'dl': 'Delhi', 'delhi': 'Delhi', 'new delhi': 'Delhi',
    'tg': 'Telangana', 'ts': 'Telangana', 'telangana': 'Telangana',
    'wb': 'West Bengal', 'west bengal': 'West Bengal',
    'gj': 'Gujarat', 'gujarat': 'Gujarat',
    'rj': 'Rajasthan', 'rajasthan': 'Rajasthan',
    'up': 'Uttar Pradesh', 'uttar pradesh': 'Uttar Pradesh',
    'pb': 'Punjab', 'punjab': 'Punjab',
    'hr': 'Haryana', 'haryana': 'Haryana',
    'br': 'Bihar', 'bihar': 'Bihar',
    'ap': 'Andhra Pradesh', 'andhra pradesh': 'Andhra Pradesh',
    'mz': 'Mizoram', 'mizoram': 'Mizoram',
    'ml': 'Meghalaya', 'meghalaya': 'Meghalaya',
    'nl': 'Nagaland', 'nagaland': 'Nagaland',
    'sk': 'Sikkim', 'sikkim': 'Sikkim',
    'tr': 'Tripura', 'tripura': 'Tripura',
    'ar': 'Arunachal Pradesh', 'arunachal pradesh': 'Arunachal Pradesh',
    'as': 'Assam', 'assam': 'Assam',
    'mp': 'Madhya Pradesh', 'madhya pradesh': 'Madhya Pradesh',
    'or': 'Odisha', 'odisha': 'Odisha',
    'ct': 'Chhattisgarh', 'chhattisgarh': 'Chhattisgarh',
    'jk': 'Jammu & Kashmir', 'jammu & kashmir': 'Jammu & Kashmir',
    'j&k': 'Jammu & Kashmir', 'jammu and kashmir': 'Jammu & Kashmir',
    'ld': 'Ladakh', 'ladakh': 'Ladakh',
    'ch': 'Chandigarh', 'chandigarh': 'Chandigarh',
    'py': 'Puducherry', 'puducherry': 'Puducherry',
    'dn': 'Dadra & Nagar Haveli', 'dadra & nagar haveli': 'Dadra & Nagar Haveli',
    'dd': 'Daman & Diu', 'daman & diu': 'Daman & Diu',
    'an': 'Andaman & Nicobar', 'andaman & nicobar': 'Andaman & Nicobar',
    'ga': 'Goa', 'goa': 'Goa',
    'kl': 'Kerala', 'kerala': 'Kerala',
}

# Values that are clearly not locations (HTML fragments, boilerplate text).
_LOCATION_REJECT_PATTERNS = ('<', '>', 'href=', 'div', 'span', 'class=', 'id=', 'http')


def _extract_location(bid: Bid) -> Dict[str, Any]:
    """
    Extract and normalize the bid's location from authoritative fields only.

    Returns a dict with:
      label    — display string (e.g. "Bengaluru, Karnataka" or
                 "Location Not Disclosed by Source")
      quality  — "AVAILABLE" | "NOT_DISCLOSED" | "EXTRACTION_FAILED"
      state    — normalized state name or None
      city     — first location component (city/district) or None
    """
    location = (bid.location or "").strip()

    # Nothing stored → source did not disclose a location.
    if not location:
        return {
            "label": "Location Not Disclosed by Source",
            "quality": "NOT_DISCLOSED",
            "state": None,
            "city": None,
        }

    # Reject values that look like HTML fragments or boilerplate text rather
    # than a genuine location. These are not real tender locations.
    low = location.lower()
    if any(pat in low for pat in _LOCATION_REJECT_PATTERNS):
        return {
            "label": "Location Not Disclosed by Source",
            "quality": "EXTRACTION_FAILED",
            "state": None,
            "city": None,
        }

    # Reject values that are clearly not a location (too long to be a place).
    if len(location) > 200:
        return {
            "label": "Location Not Disclosed by Source",
            "quality": "EXTRACTION_FAILED",
            "state": None,
            "city": None,
        }

    # Normalize: split on comma, trim, deduplicate (case-insensitive).
    raw_parts = [p.strip() for p in location.split(',') if p.strip()]
    seen: set = set()
    parts: List[str] = []
    for p in raw_parts:
        key = p.lower()
        if key not in seen:
            seen.add(key)
            parts.append(p)

    # Build normalized components.
    normalized: List[str] = []
    state: Optional[str] = None
    city: Optional[str] = None

    for i, part in enumerate(parts):
        key = part.lower()
        mapped = _STATE_ALIASES.get(key)
        if mapped:
            state = mapped
            normalized.append(mapped)
        elif i == 0 and city is None:
            city = part
            normalized.append(part)
        else:
            normalized.append(part)

    label = ', '.join(normalized) if normalized else location

    return {
        "label": label,
        "quality": "AVAILABLE",
        "state": state,
        "city": city,
    }


def _location_label(bid: Bid) -> str:
    """Backward-compatible wrapper: return the display label for a bid's location."""
    return _extract_location(bid)["label"]


def _matching_keywords(evidence: Optional[Dict[str, Any]]) -> List[str]:
    """Extract the positive (non-exclusion) keywords that drove a match."""
    if not evidence or not isinstance(evidence, dict):
        return []
    keywords: List[str] = []
    for signal in evidence.get("signals", []) or []:
        if not isinstance(signal, dict):
            continue
        if signal.get("strength") == "EXCLUSION":
            continue
        keyword = signal.get("keyword")
        if keyword and keyword not in keywords:
            keywords.append(keyword)
    return keywords


def _technical_requirements(bid: Bid) -> str:
    """Gather the technical / scope evidence available on the bid."""
    parts: List[str] = []
    if bid.scope_of_work:
        parts.append(str(bid.scope_of_work))
    tech = bid.technical_requirements
    if isinstance(tech, dict):
        for key in ("description", "requirements", "technical_requirements", "scope"):
            value = tech.get(key)
            if isinstance(value, str) and value.strip():
                parts.append(value.strip())
        items = tech.get("items")
        if isinstance(items, list):
            for item in items[:5]:
                if isinstance(item, dict):
                    text = item.get("description") or item.get("title") or ""
                    if text.strip():
                        parts.append(str(text).strip())
    return " | ".join(parts) if parts else ""


def _match_payload(match: BidProductMatch, bid: Bid, product: Product) -> Dict[str, Any]:
    """Build a single bid-product match row for the All-India dashboard."""
    evidence = match.evidence if isinstance(match.evidence, dict) else {}
    score_info = classify_all_india(match.match_score)
    score_breakdown = evidence.get("score_breakdown", {}) if isinstance(evidence, dict) else {}
    if not isinstance(score_breakdown, dict):
        score_breakdown = {}

    loc = _extract_location(bid)
    return {
        "bid_id": str(bid.id),
        "gem_bid_id": bid.gem_bid_id,
        "bid_number": bid.bid_number,
        "tender_id": bid.bid_number or bid.gem_bid_id,
        "title": bid.title,
        "location": loc["label"],
        "state": loc["state"] or loc["label"],
        "city": loc["city"],
        "location_quality": loc["quality"],
        "department": bid.department,
        "organisation": bid.organisation,
        "procuring_authority": bid.organisation or bid.department,
        "source_name": bid.source_name,
        "is_gem_bid": bool(bid.source_name and "gem" in bid.source_name.lower()),
        "estimated_value": float(bid.estimated_value) if bid.estimated_value is not None else None,
        "currency": bid.currency,
        "published_date": bid.published_date.isoformat() if bid.published_date else None,
        "closing_date": bid.closing_date.isoformat() if bid.closing_date else None,
        "days_remaining": None,
        "product_id": str(product.id),
        "product_name": product.name,
        "relevance_score_100": score_info["score_100"],
        "classification": score_info["classification"],
        "match_state": evidence.get("match_state") or match.match_type,
        "confidence": round(float(match.confidence), 3),
        "matching_keywords": _matching_keywords(evidence),
        "explanation": evidence.get("reason") or score_breakdown.get("reason") or "",
        "technical_requirements": _technical_requirements(bid),
        "source_url": bid.source_url,
        "score_breakdown": score_breakdown,
    }


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@router.get("/dashboard/all-india/summary")
def all_india_summary(
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(require_viewer),
):
    """
    Overall statistics and state-wise / product-wise distribution for the
    All-India product-relevant bid dashboard.

    Only persisted matches with a relevance score of 50/100 (0.50) or higher
    are counted, so every figure reflects real matching evidence.
    """
    matches = (
        db.query(BidProductMatch)
        .options(
            joinedload(BidProductMatch.bid),
            joinedload(BidProductMatch.product),
        )
        .filter(BidProductMatch.match_score >= DISPLAY_MIN_SCORE_0_1)
        .all()
    )

    bid_ids: set = set()
    product_ids: set = set()
    locations: set = set()
    location_qualities: Dict[str, int] = {"AVAILABLE": 0, "NOT_DISCLOSED": 0, "EXTRACTION_FAILED": 0}
    highly_relevant = 0
    relevant = 0
    potentially_relevant = 0
    state_distribution: Dict[str, Dict[str, int]] = {}
    product_distribution: Dict[str, int] = {}

    for match in matches:
        bid = match.bid
        product = match.product
        if bid is None or product is None:
            continue
        bid_ids.add(str(bid.id))
        product_ids.add(str(product.id))

        loc = _extract_location(bid)
        location = loc["label"]
        locations.add(location)
        location_qualities[loc["quality"]] += 1

        info = classify_all_india(match.match_score)
        if info["classification"] == "Highly Relevant":
            highly_relevant += 1
        elif info["classification"] == "Relevant":
            relevant += 1
        elif info["classification"] == "Potentially Relevant":
            potentially_relevant += 1

        bucket = state_distribution.setdefault(
            location, {"bid_count": 0, "highly_relevant": 0, "relevant": 0, "potentially_relevant": 0}
        )
        # Count each bid once per location for bid_count; count matches per band.
        bucket["bid_count"] += 1
        if info["classification"] == "Highly Relevant":
            bucket["highly_relevant"] += 1
        elif info["classification"] == "Relevant":
            bucket["relevant"] += 1
        elif info["classification"] == "Potentially Relevant":
            bucket["potentially_relevant"] += 1

        product_distribution[product.name] = product_distribution.get(product.name, 0) + 1

    state_rows = [
        {
            "location": name,
            "bid_count": data["bid_count"],
            "highly_relevant": data["highly_relevant"],
            "relevant": data["relevant"],
            "potentially_relevant": data["potentially_relevant"],
        }
        for name, data in sorted(state_distribution.items(), key=lambda kv: -kv[1]["bid_count"])
    ]
    product_rows = [
        {"product_name": name, "bid_count": count}
        for name, count in sorted(product_distribution.items(), key=lambda kv: -kv[1])
    ]

    return {
        "total_bids": len(bid_ids),
        "total_relevant_bids": len(bid_ids),
        "highly_relevant_bids": highly_relevant,
        "relevant_bids": relevant,
        "potentially_relevant_bids": potentially_relevant,
        "states_covered": len(locations),
        "products_with_matches": len(product_ids),
        "location_qualities": location_qualities,
        "state_distribution": state_rows,
        "product_distribution": product_rows,
    }


@router.get("/dashboard/all-india/bids")
def all_india_bids(
    state: Optional[str] = Query(None, description='Location / state filter. Use "Location Not Specified" for bids without a location.'),
    product: Optional[str] = Query(None, description='Filter by matched SecuredApp product name.'),
    min_score: Optional[int] = Query(None, ge=0, le=100, description='Minimum relevance score (0-100). Defaults to 50.'),
    department: Optional[str] = Query(None, description='Filter by department (contains).'),
    organisation: Optional[str] = Query(None, description='Filter by organisation / procuring authority (contains).'),
    estimated_value_min: Optional[float] = Query(None, ge=0, description='Minimum estimated value (INR).'),
    estimated_value_max: Optional[float] = Query(None, ge=0, description='Maximum estimated value (INR).'),
    closing_before: Optional[str] = Query(None, description='Bids closing on or before this date (ISO-8601).'),
    closing_after: Optional[str] = Query(None, description='Bids closing on or after this date (ISO-8601).'),
    search: Optional[str] = Query(None, description='Search bid title, tender ID, organisation or matched product.'),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    sort_by: str = Query("relevance", description='relevance | closing_date | estimated_value | title'),
    sort_dir: str = Query("desc", description="asc | desc"),
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(require_viewer),
):
    """
    Paginated, searchable, sortable list of product-relevant GeM bid matches.

    Each row is one (bid, product) match with relevance score >= 50/100. A bid
    matching multiple products appears once per matched product -- the bid record
    itself is never duplicated.
    """
    from datetime import datetime, timezone

    min_score_0_1 = (min_score or 50) / 100.0

    query = (
        db.query(BidProductMatch)
        .join(BidProductMatch.bid)
        .join(BidProductMatch.product)
        .options(
            joinedload(BidProductMatch.bid),
            joinedload(BidProductMatch.product),
        )
        .filter(BidProductMatch.match_score >= min_score_0_1)
    )

    if state is not None:
        if state in ("Location Not Specified", "Location Not Disclosed by Source"):
            query = query.filter(
                or_(Bid.location.is_(None), func.trim(Bid.location) == "")
            )
        else:
            query = query.filter(Bid.location.ilike(f"%{state.strip()}%"))

    if product:
        query = query.filter(Product.name.ilike(f"%{product.strip()}%"))

    if department:
        query = query.filter(Bid.department.ilike(f"%{department.strip()}%"))

    if organisation:
        query = query.filter(Bid.organisation.ilike(f"%{organisation.strip()}%"))

    if estimated_value_min is not None:
        query = query.filter(Bid.estimated_value >= estimated_value_min)
    if estimated_value_max is not None:
        query = query.filter(Bid.estimated_value <= estimated_value_max)

    if closing_before:
        try:
            before = datetime.fromisoformat(closing_before.replace("Z", "+00:00"))
            query = query.filter(Bid.closing_date <= before)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="closing_before must be an ISO-8601 date/time.",
            )
    if closing_after:
        try:
            after = datetime.fromisoformat(closing_after.replace("Z", "+00:00"))
            query = query.filter(Bid.closing_date >= after)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="closing_after must be an ISO-8601 date/time.",
            )

    if search:
        term = f"%{search.strip()}%"
        query = query.filter(
            or_(
                Bid.title.ilike(term),
                Bid.bid_number.ilike(term),
                Bid.gem_bid_id.ilike(term),
                Bid.organisation.ilike(term),
                Product.name.ilike(term),
            )
        )

    # Ordering
    desc = sort_dir.lower() == "desc"
    if sort_by == "closing_date":
        order_col = Bid.closing_date
    elif sort_by == "estimated_value":
        order_col = Bid.estimated_value
    elif sort_by == "title":
        order_col = Bid.title
    else:
        order_col = BidProductMatch.match_score
    query = query.order_by(order_col.desc() if desc else order_col.asc())

    total = query.count()
    page = max(1, page)
    page_size = max(1, min(200, page_size))
    offset = (page - 1) * page_size
    rows = query.offset(offset).limit(page_size).all()

    bids: List[Dict[str, Any]] = []
    from datetime import datetime as _dt
    for match in rows:
        bid = match.bid
        product = match.product
        if bid is None or product is None:
            continue
        payload = _match_payload(match, bid, product)
        closing = bid.closing_date
        if closing:
            if closing.tzinfo is None:
                closing = closing.replace(tzinfo=timezone.utc)
            payload["days_remaining"] = int((closing - _dt.now(timezone.utc)).total_seconds() // 86400)
        bids.append(payload)

    total_pages = max(1, -(-total // page_size))
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
        "min_score": int(min_score_0_1 * 100),
        "bids": bids,
    }


@router.post("/dashboard/all-india/match-all", status_code=status.HTTP_202_ACCEPTED)
def match_all_bids(
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(require_operator),
):
    """
    Run the deterministic bid-to-product matching engine across every stored
    GeM bid and persist the product-match records.

    Idempotent: existing matches for a bid are replaced with fresh results.
    Only matches carrying genuine positive evidence are persisted
    (score >= 0.25 / NEEDS_REVIEW band); the All-India dashboard then displays
    those at 50/100 or above.
    """
    from app.services.intelligence import match_bid_against_products
    from app.models.analysis import BidAnalysis

    bids = db.query(Bid).all()
    processed = 0
    matches_persisted = 0

    for bid in bids:
        try:
            match_results = match_bid_against_products(db, bid)
        except Exception:
            logger.exception("Matching failed for bid %s", bid.id)
            continue

        # Replace existing matches for this bid with fresh results.
        db.query(BidProductMatch).filter(BidProductMatch.bid_id == bid.id).delete()

        persisted_for_bid = 0
        for res in match_results:
            # Persist only genuine, evidence-backed candidates (the same gate the
            # per-bid endpoint uses). NO_MATCH / exclusion-only candidates are
            # never stored as if they matched.
            if res.match_state not in {"MATCH", "POSSIBLE_MATCH", "NEEDS_REVIEW"}:
                continue
            if res.relevance_score < 0.25:
                continue
            if not any(s.get("strength") != "EXCLUSION" for s in res.signals):
                continue
            db.add(
                BidProductMatch(
                    bid_id=bid.id,
                    product_id=res.product_id,
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

        db.add(
            BidAnalysis(
                bid_id=bid.id,
                engine_version="Phase3-Deterministic",
                model_used="None (Deterministic Engine)",
                product_matches=[r.to_dict() for r in match_results],
                evidence=[r.signals for r in match_results if r.signals],
            )
        )
        processed += 1

    db.commit()
    return {
        "processed": processed,
        "matches_persisted": matches_persisted,
        "detail": f"Matched {processed} bid(s); persisted {matches_persisted} product-match record(s).",
    }
