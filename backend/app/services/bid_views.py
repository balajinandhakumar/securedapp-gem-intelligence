"""
Read-only projections of a bid together with its real persisted analysis state.

This module is the single source of truth for "what does the intelligence
pipeline actually know about this bid". Both the dashboard summary and the bid
intelligence feed are built from these helpers, so no screen has to invent a
score, a match or a product.

A bid that has never been analysed is reported as `analyzed: False` with
`None` scores, which the UI renders as an explicit "not yet analyzed" state.
"""
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from app.models.analysis import BidScore
from app.models.bid import Bid

# Mirrors the deadline intelligence window used by the deterministic provider:
# <= 3 days -> CLOSING_SOON, <= 7 days -> URGENT.
CLOSING_SOON_DAYS = 7

# States in which the pipeline positively identified one of our products for a
# bid. The matching engine evaluates *every* active product, so the record it
# persists as `highest_product_match` names the top-ranked candidate whether or
# not that candidate was accepted. Only these three states mean "this bid
# matched this product"; NO_MATCH means the top candidate was evaluated and
# rejected, so its name must never be surfaced as the bid's product match.
MATCHED_STATES = frozenset({"MATCH", "POSSIBLE_MATCH", "NEEDS_REVIEW"})

# Bid lifecycle states used consistently across backend APIs, dashboard queries,
# summary counts, and notifications. A bid is "closed" when its closing_date has
# passed; "closing soon" when the deadline is within the configured window and
# still in the future; "unknown" when no closing date is recorded. Closed bids
# are preserved in the database for historical auditing but must never appear in
# active dashboard lists, opportunity counts, or new notifications.
BID_STATUS_OPEN = "OPEN"
BID_STATUS_CLOSING_SOON = "CLOSING_SOON"
BID_STATUS_CLOSED = "CLOSED"
BID_STATUS_UNKNOWN = "UNKNOWN"


def days_remaining(closing_date: Optional[datetime]) -> Optional[int]:
    if closing_date is None:
        return None
    now = datetime.now(timezone.utc)
    due = closing_date if closing_date.tzinfo else closing_date.replace(tzinfo=timezone.utc)
    return int((due - now).total_seconds() // 86400)


def deadline_status(days: Optional[int]) -> str:
    if days is None:
        return BID_STATUS_UNKNOWN
    if days < 0:
        return BID_STATUS_CLOSED
    if days <= 3:
        return BID_STATUS_CLOSING_SOON
    if days <= CLOSING_SOON_DAYS:
        return "URGENT"
    return BID_STATUS_OPEN


def bid_lifecycle_status(bid: Bid) -> str:
    """Determine a bid's lifecycle status from its closing date.

    A bid with no closing_date is ``UNKNOWN`` (not closed, not closing soon).
    A bid whose closing_date has passed is ``CLOSED``. A bid whose closing_date
    is within the configured window and still in the future is ``CLOSING_SOON``
    (or ``URGENT`` within 3 days). All other bids are ``OPEN``.

    Closed bids are preserved in the database for historical auditing but must
    never appear in active dashboard lists, opportunity counts, or new
    notifications.
    """
    days = days_remaining(bid.closing_date)
    return deadline_status(days)


def is_bid_closed(bid: Bid) -> bool:
    """True when the bid's closing date has passed (expired/cancelled)."""
    days = days_remaining(bid.closing_date)
    return days is not None and days < 0


def is_bid_closing_soon(bid: Bid, window_days: int = CLOSING_SOON_DAYS) -> bool:
    """True when the bid is still open but its deadline is within the window."""
    days = days_remaining(bid.closing_date)
    if days is None:
        return False
    return 0 <= days <= window_days


def is_bid_open(bid: Bid) -> bool:
    """True when the bid is not closed (open, closing soon, or unknown)."""
    return not is_bid_closed(bid)


def latest_scores(db: Session) -> Dict[str, BidScore]:
    """Map bid_id -> its most recent BidScore row."""
    latest: Dict[str, BidScore] = {}
    for score in db.query(BidScore).order_by(BidScore.bid_id, BidScore.created_at).all():
        latest[str(score.bid_id)] = score
    return latest


def serialise_bid(bid: Bid, score: Optional[BidScore]) -> Dict[str, Any]:
    """Project a bid plus its real analysis state into a flat payload."""
    days = days_remaining(bid.closing_date)

    highest_match = None
    if score is not None and isinstance(score.score_breakdown, dict):
        highest_match = score.score_breakdown.get("highest_product_match")

    match_state = highest_match.get("match_state") if isinstance(highest_match, dict) else None

    # Report a product only when the pipeline actually matched one. For a
    # NO_MATCH bid the stored candidate is just the first catalogue product
    # (every product scores 0.0, so the ranking is a tie), and naming it here
    # would present an arbitrary product as a real match. `match_state` is still
    # returned so the client can render an explicit "no relevant product".
    matched_product = (
        highest_match.get("product_name")
        if isinstance(highest_match, dict) and match_state in MATCHED_STATES
        else None
    )

    return {
        "id": str(bid.id),
        "gem_bid_id": bid.gem_bid_id,
        "bid_number": bid.bid_number,
        "title": bid.title,
        "organisation": bid.organisation,
        "department": bid.department,
        "category": bid.category,
        "location": bid.location,
        "status": bid.status,
        "published_date": bid.published_date.isoformat() if bid.published_date else None,
        "closing_date": bid.closing_date.isoformat() if bid.closing_date else None,
        "last_updated_at": bid.last_updated_at.isoformat() if bid.last_updated_at else None,
        "days_remaining": days,
        "deadline_status": deadline_status(days),
        "estimated_value": float(bid.estimated_value) if bid.estimated_value is not None else None,
        "currency": bid.currency,
        "scope_of_work": bid.scope_of_work,
        "analyzed": score is not None,
        "relevance_score": round(score.relevance_score, 3) if score else None,
        "relevance_label": score.relevance_label if score else None,
        "opportunity_score": round(score.opportunity_score, 3) if score else None,
        "urgency": score.urgency if score else None,
        "matched_product": matched_product,
        "match_state": match_state,
    }


def serialise_all_bids(
    db: Session,
    include_closed: bool = False,
) -> list:
    """Return every bid row enriched with its latest real analysis state.

    By default closed bids (past closing_date) are excluded. Set
    ``include_closed=true`` to include closed bids for historical auditing.
    """
    scores = latest_scores(db)
    rows = []
    for bid in db.query(Bid).all():
        if not include_closed and is_bid_closed(bid):
            continue
        rows.append(serialise_bid(bid, scores.get(str(bid.id))))
    return rows
