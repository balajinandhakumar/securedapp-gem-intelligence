"""
Read-only dashboard aggregation.

Every figure returned here is derived from persisted backend data
(`bids`, `bid_scores`, `notifications`) or from the normalised bid fields
themselves. Nothing is estimated, sampled or defaulted to a placeholder
value, so the dashboard can only ever display what the intelligence pipeline
actually produced.

Bids that have not been through the analysis pipeline yet are reported
explicitly as `null`/`analyzed: false` rather than being given a score.
"""
from typing import Any, Dict, List

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.bid import Bid
from app.models.notification import Notification
from app.services.bid_views import (
    CLOSING_SOON_DAYS,
    is_bid_closed,
    latest_scores,
    serialise_bid,
)
from app.services.intelligence.matching_engine import classify_score

router = APIRouter()


@router.get("/summary")
def get_dashboard_summary(
    closing_soon_days: int = CLOSING_SOON_DAYS,
    db: Session = Depends(get_db),
):
    """
    Aggregate command-strip metrics and work queues for the main dashboard.

    Read-only: this endpoint never triggers analysis, never writes, and never
    fabricates a score. Use `POST /api/v1/bids/{id}/analyze` or the ingestion
    batch pipeline to produce analysis.
    """
    # Fetch all bids. Closed bids (past closing_date) are preserved in the
    # database for historical auditing and can appear in the recent_bids feed
    # with their CLOSED deadline_status, but are excluded from all active
    # dashboard metrics, active lists (priority_opportunities, possible_matches,
    # action_required), and notification activity.
    all_bids = db.query(Bid).all()
    open_bids = [b for b in all_bids if not is_bid_closed(b)]
    closed_bid_count = len(all_bids) - len(open_bids)

    scores = latest_scores(db)
    # recent_bids includes ALL bids (open and closed) so users can see recent
    # activity including bids that have since closed.
    recent_rows = [serialise_bid(b, scores.get(str(b.id))) for b in all_bids]
    # Active rows exclude closed bids for counts and active lists.
    active_rows = [serialise_bid(b, scores.get(str(b.id))) for b in open_bids]
    analyzed_rows = [r for r in active_rows if r["analyzed"]]

    # Buckets come from the engine's single canonical classifier, so the
    # dashboard honours whatever relevance rule is in force (the four-band rule
    # when no threshold is configured, or the configured binary cutoff). Using a
    # second hardcoded 0.70/0.45/0.25 rule here is what previously let a
    # 0.5-threshold deployment show a MATCH as "possible" on the dashboard.
    def _band(row: Dict[str, Any]) -> str:
        return classify_score(row["relevance_score"]) if row["relevance_score"] is not None else "NO_MATCH"

    relevant = [r for r in analyzed_rows if _band(r) == "MATCH"]
    possible = [r for r in analyzed_rows if _band(r) == "POSSIBLE_MATCH"]
    needs_review = [r for r in analyzed_rows if _band(r) == "NEEDS_REVIEW"]

    # Closing-soon only includes bids that are still open (not closed).
    closing_soon = [
        r
        for r in active_rows
        if r["days_remaining"] is not None
        and 0 <= r["days_remaining"] <= closing_soon_days
    ]

    notifications = db.query(Notification).all()
    notification_total = len(notifications)

    def _opportunity_rank(row: Dict[str, Any]):
        # Deterministic ordering: strongest match first, then value, then the
        # tightest deadline. Bids that were never analyzed are excluded from
        # the opportunity ranking because they carry no score to rank by.
        return (
            -(row["relevance_score"] or 0.0),
            -(row["opportunity_score"] or 0.0),
            row["days_remaining"] if row["days_remaining"] is not None else 10**6,
        )

    priority_opportunities = sorted(
        [r for r in relevant if r["relevance_score"] is not None],
        key=_opportunity_rank,
    )

    # Possible matches are genuine pipeline matches that sit just below the
    # relevant band (0.45-0.70). Surface every active possible match so the
    # displayed list matches the possible_match_bids count.
    possible_matches = sorted(possible, key=_opportunity_rank)

    # recent_bids includes ALL bids (open and closed) so users can see recent
    # activity including bids that have since closed. Closed bids show their
    # CLOSED deadline_status.
    recent_bids = sorted(
        recent_rows,
        key=lambda r: (r["published_date"] or r["last_updated_at"] or ""),
        reverse=True,
    )[:8]

    # action_required only includes open bids that are closing soon.
    action_required = sorted(
        closing_soon,
        key=lambda r: r["days_remaining"],
    )[:6]

    recent_activity: List[Dict[str, Any]] = []
    for notif in (
        db.query(Notification).order_by(Notification.id.desc()).limit(8).all()
    ):
        bid = db.get(Bid, notif.bid_id) if notif.bid_id else None
        if bid is None or is_bid_closed(bid):
            continue
        recent_activity.append({
            "id": str(notif.id),
            "bid_id": str(notif.bid_id) if notif.bid_id else None,
            "bid_title": bid.title if bid else None,
            "notification_type": notif.notification_type,
            "channel": notif.channel,
            "status": notif.status,
            "recipient": notif.recipient,
        })

    return {
        "metrics": {
            "total_bids": len(open_bids),
            "closed_bids": closed_bid_count,
            "analyzed_bids": len(analyzed_rows),
            "pending_analysis": len(open_bids) - len(analyzed_rows),
            "relevant_bids": len(relevant),
            "possible_match_bids": len(possible),
            "needs_review_bids": len(needs_review),
            "closing_soon_bids": len(closing_soon),
            "closing_soon_window_days": closing_soon_days,
            "notifications": notification_total,
        },
        "priority_opportunities": priority_opportunities,
        "possible_matches": possible_matches,
        "recent_bids": recent_bids,
        "action_required": action_required,
        "recent_activity": recent_activity,
    }
