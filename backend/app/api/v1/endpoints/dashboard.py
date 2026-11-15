"""
Read-only dashboard aggregation (optimized).

Every figure returned here is derived from persisted backend data
(`bids`, `bid_scores`, `notifications`) or from the normalised bid fields
themselves. Nothing is estimated, sampled or defaulted to a placeholder
value, so the dashboard can only ever display what the intelligence pipeline
actually produced.

Bids that have not been through the analysis pipeline yet are reported
explicitly as `null`/`analyzed: false` rather than being given a score.

Performance approach:
- All metric counts are computed in SQL via conditional aggregation -- no
  bid rows are loaded into Python for counting.
- Lists are bounded with LIMIT and only the required rows are fetched.
- The latest-score-per-bid subquery avoids loading all BidScore rows.
- Indexes on bids(closing_date) and bid_scores(bid_id, created_at) support
  the filters and lookups (see migration 0008).
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends
from sqlalchemy import and_, asc, case, desc, func, or_
from sqlalchemy.orm import Session, aliased

from app.core.config import settings
from app.core.database import get_db
from app.api.v1.dependencies import require_admin, require_operator, require_viewer
from app.models.bid import Bid
from app.models.notification import Notification
from app.models.analysis import BidScore
from app.models.user import User
from app.services.bid_views import (
    CLOSING_SOON_DAYS,
    is_bid_closed,
    serialise_bid,
)

router = APIRouter()


def _band_expression(score_column) -> Any:
    """Build the SQL CASE expression that mirrors ``classify_score``.

    Honours the configured ``MATCHING_RELEVANCE_THRESHOLD`` when set, falling
    back to the engine's four-band rule (0.70 / 0.45 / 0.25).
    """
    threshold = getattr(settings, "MATCHING_RELEVANCE_THRESHOLD", None)
    if threshold is not None:
        return case(
            (score_column >= threshold, "MATCH"),
            else_="NO_MATCH",
        )
    return case(
        (score_column >= 0.70, "MATCH"),
        (score_column >= 0.45, "POSSIBLE_MATCH"),
        (score_column >= 0.25, "NEEDS_REVIEW"),
        else_="NO_MATCH",
    )


@router.get("/summary")
def get_dashboard_summary(
    closing_soon_days: int = CLOSING_SOON_DAYS,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(require_viewer),
):
    """
    Aggregate command-strip metrics and work queues for the main dashboard.

    Read-only: this endpoint never triggers analysis, never writes, and never
    fabricates a score. Use `POST /api/v1/bids/{id}/analyze` or the ingestion
    batch pipeline to produce analysis.
    """
    now = datetime.now(timezone.utc)
    closing_soon_cutoff = now + timedelta(days=closing_soon_days)

    open_cond = or_(
        Bid.closing_date.is_(None), Bid.closing_date >= now
    )
    closed_cond = and_(
        Bid.closing_date.is_not(None), Bid.closing_date < now
    )

    # ------------------------------------------------------------------
    # Latest score per bid: one BidScore row per bid (the most recent).
    # Restricted to open bids only so the subquery scans ~2.8K bids'
    # scores instead of all 43K+ score rows. Built once and reused by the
    # counts and the opportunity lists so the CASE band expression is
    # evaluated once per bid instead of once per persisted score row.
    # Index-backed join on bid_scores(bid_id, created_at) (migration 0008).
    # ------------------------------------------------------------------
    open_bid_ids = [
        str(bid_id)
        for (bid_id,) in db.query(Bid.id).filter(open_cond).all()
    ]
    if open_bid_ids:
        latest_subq = (
            db.query(
                BidScore.bid_id,
                func.max(BidScore.created_at).label("max_created"),
            )
            .filter(BidScore.bid_id.in_(open_bid_ids))
            .group_by(BidScore.bid_id)
            .subquery("latest_score")
        )
        latest_scores_q = (
            db.query(BidScore)
            .join(
                latest_subq,
                and_(
                    BidScore.bid_id == latest_subq.c.bid_id,
                    BidScore.created_at == latest_subq.c.max_created,
                ),
            )
            .subquery("ls")
        )
        ls = aliased(BidScore, latest_scores_q)
        band_expr = _band_expression(ls.relevance_score)
    else:
        ls = None
        band_expr = None

    # ------------------------------------------------------------------
    # Metrics: all computed in SQL via conditional aggregation.
    # ------------------------------------------------------------------
    counts_query = (
        db.query(
            func.count(Bid.id).label("total_bids"),
            func.count(Bid.id).filter(open_cond).label("open_bids"),
            func.count(Bid.id).filter(closed_cond).label("closed_bids"),
        )
    )
    if ls is not None:
        counts_query = counts_query.add_columns(
            func.count(Bid.id).filter(
                and_(open_cond, ls.bid_id.is_not(None))
            ).label("analyzed_bids"),
            func.count(Bid.id).filter(
                and_(
                    open_cond,
                    ls.bid_id.is_not(None),
                    band_expr == "MATCH",
                )
            ).label("relevant_bids"),
            func.count(Bid.id).filter(
                and_(
                    open_cond,
                    ls.bid_id.is_not(None),
                    band_expr == "POSSIBLE_MATCH",
                )
            ).label("possible_match_bids"),
            func.count(Bid.id).filter(
                and_(
                    open_cond,
                    ls.bid_id.is_not(None),
                    band_expr == "NEEDS_REVIEW",
                )
            ).label("needs_review_bids"),
        )
    counts_query = counts_query.add_columns(
        func.count(Bid.id).filter(
            and_(
                open_cond,
                Bid.closing_date.is_not(None),
                Bid.closing_date >= now,
                Bid.closing_date <= closing_soon_cutoff,
            )
        ).label("closing_soon_bids"),
    )
    if ls is not None:
        counts_query = counts_query.outerjoin(ls, ls.bid_id == Bid.id)
    counts = counts_query.first()

    notification_total = db.query(func.count(Notification.id)).scalar()

    total_bids = counts.total_bids or 0
    open_bids = counts.open_bids or 0
    closed_bids = counts.closed_bids or 0
    if ls is not None:
        analyzed_bids = counts.analyzed_bids or 0
        relevant_bids = counts.relevant_bids or 0
        possible_match_bids = counts.possible_match_bids or 0
        needs_review_bids = counts.needs_review_bids or 0
    else:
        analyzed_bids = 0
        relevant_bids = 0
        possible_match_bids = 0
        needs_review_bids = 0
    closing_soon_bids = counts.closing_soon_bids or 0

    # ------------------------------------------------------------------
    # Lists: bounded queries, only required rows fetched.
    # ------------------------------------------------------------------

    # priority_opportunities: open, analyzed, MATCH bids.
    if ls is not None:
        opp_rows = (
            db.query(Bid, ls)
            .join(ls, ls.bid_id == Bid.id)
            .filter(
                open_cond,
                band_expr == "MATCH",
            )
            .order_by(
                desc(ls.relevance_score),
                desc(ls.opportunity_score),
                asc(Bid.closing_date).nullslast(),
            )
            .limit(100)
            .all()
        )
        priority_opportunities = [serialise_bid(b, s) for b, s in opp_rows]
    else:
        priority_opportunities = []

    # possible_matches: open, analyzed, POSSIBLE_MATCH bids.
    if ls is not None:
        possible_rows = (
            db.query(Bid, ls)
            .join(ls, ls.bid_id == Bid.id)
            .filter(
                open_cond,
                band_expr == "POSSIBLE_MATCH",
            )
            .order_by(
                desc(ls.relevance_score),
                desc(ls.opportunity_score),
                asc(Bid.closing_date).nullslast(),
            )
            .limit(100)
            .all()
        )
        possible_matches = [serialise_bid(b, s) for b, s in possible_rows]
    else:
        possible_matches = []

    # recent_bids: ALL bids (open and closed), top 8 by published_date desc.
    recent_bid_rows = (
        db.query(Bid)
        .order_by(
            desc(Bid.published_date).nullslast(),
            desc(Bid.last_updated_at).nullslast(),
        )
        .limit(8)
        .all()
    )
    recent_bid_ids = [str(b.id) for b in recent_bid_rows]
    recent_scores_map: Dict[str, Any] = {}
    if recent_bid_ids:
        for score in (
            db.query(BidScore)
            .filter(BidScore.bid_id.in_(recent_bid_ids))
            .order_by(BidScore.bid_id, BidScore.created_at.desc())
            .all()
        ):
            key = str(score.bid_id)
            if key not in recent_scores_map:
                recent_scores_map[key] = score
    recent_bids = [
        serialise_bid(b, recent_scores_map.get(str(b.id)))
        for b in recent_bid_rows
    ]

    # action_required: open bids closing soon, top 6 by days_remaining asc.
    # Sorting by closing_date ascending is equivalent to sorting by
    # days_remaining ascending (earlier deadline = fewer days remaining).
    if ls is not None:
        action_rows = (
            db.query(Bid, ls)
            .outerjoin(ls, ls.bid_id == Bid.id)
            .filter(
                open_cond,
                Bid.closing_date.is_not(None),
                Bid.closing_date >= now,
                Bid.closing_date <= closing_soon_cutoff,
            )
            .order_by(asc(Bid.closing_date).nullslast())
            .limit(6)
            .all()
        )
        action_required = [serialise_bid(b, s) for b, s in action_rows]
    else:
        action_required = []

    # recent_activity: top 8 notifications for open bids, by id desc.
    recent_notifs = (
        db.query(Notification)
        .order_by(Notification.id.desc())
        .limit(8)
        .all()
    )
    notif_bid_ids = {
        str(n.bid_id) for n in recent_notifs if n.bid_id
    }
    bid_map: Dict[str, Any] = {}
    if notif_bid_ids:
        bid_map = {
            str(b.id): b
            for b in db.query(Bid).filter(Bid.id.in_(notif_bid_ids)).all()
        }

    recent_activity: List[Dict[str, Any]] = []
    for notif in recent_notifs:
        bid = bid_map.get(str(notif.bid_id)) if notif.bid_id else None
        if bid is None or is_bid_closed(bid):
            continue
        recent_activity.append(
            {
                "id": str(notif.id),
                "bid_id": str(notif.bid_id) if notif.bid_id else None,
                "bid_title": bid.title if bid else None,
                "notification_type": notif.notification_type,
                "channel": notif.channel,
                "status": notif.status,
                "recipient": notif.recipient,
            }
        )

    return {
        "metrics": {
            "total_bids": total_bids,
            "open_bids": open_bids,
            "closed_bids": closed_bids,
            "analyzed_bids": analyzed_bids,
            "pending_analysis": open_bids - analyzed_bids,
            "relevant_bids": relevant_bids,
            "possible_match_bids": possible_match_bids,
            "needs_review_bids": needs_review_bids,
            "closing_soon_bids": closing_soon_bids,
            "closing_soon_window_days": closing_soon_days,
            "notifications": notification_total,
        },
        "priority_opportunities": priority_opportunities,
        "possible_matches": possible_matches,
        "recent_bids": recent_bids,
        "action_required": action_required,
        "recent_activity": recent_activity,
    }
