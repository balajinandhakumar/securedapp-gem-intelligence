"""
API endpoints for Bid Intelligence Analysis, Opportunity Analysis, Human Review, and Notifications.
"""
from typing import Any, Dict, List, Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.analysis import BidAnalysis, BidScore, BidProductMatch
from app.models.bid import Bid
from app.models.notification import Notification
from app.models.review import HumanReview
from app.schemas.notification import NotificationResponse
from app.services.bid_views import is_bid_closed
from app.services.intelligence import (
    DeterministicLLMProvider,
    OpportunityAnalyzer,
    match_bid_against_products,
)

router = APIRouter()

# Accepted label sets. Anything else is rejected at the API boundary so no
# malformed value can reach the evaluation set as a silent non-participant.
RELEVANCE_DECISIONS = ("RELEVANT", "NOT_RELEVANT", "MAYBE")
PURSUE_DECISIONS = ("PURSUE", "DONT_PURSUE", "PENDING")


class HumanReviewCreate(BaseModel):
    """One human label for a bid: relevant, irrelevant, or uncertain (MAYBE).

    Values are accepted case-insensitively and normalized to upper-case so the
    stored label always matches the evaluation's accepted set.
    """

    relevance_decision: str  # RELEVANT, NOT_RELEVANT, MAYBE
    pursue_decision: str = "PENDING"  # PURSUE, DONT_PURSUE, PENDING
    comments: Optional[str] = None

    @field_validator("relevance_decision")
    @classmethod
    def _validate_relevance(cls, value: str) -> str:
        normalized = (value or "").strip().upper()
        if normalized not in RELEVANCE_DECISIONS:
            raise ValueError(
                f"must be one of: {', '.join(RELEVANCE_DECISIONS)}"
            )
        return normalized

    @field_validator("pursue_decision")
    @classmethod
    def _validate_pursue(cls, value: str) -> str:
        normalized = (value or "PENDING").strip().upper() or "PENDING"
        if normalized not in PURSUE_DECISIONS:
            raise ValueError(
                f"must be one of: {', '.join(PURSUE_DECISIONS)}"
            )
        return normalized


@router.post("/bids/{bid_id}/analyze", status_code=status.HTTP_200_OK)
def analyze_bid_full(bid_id: UUID, db: Session = Depends(get_db)):
    """
    Run full Phase 4 Bid Intelligence & Opportunity Analysis pipeline for a bid.
    """
    bid = db.get(Bid, bid_id)
    if not bid:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Bid not found")

    # 1. Product Matching
    match_results = match_bid_against_products(db, bid)

    # 2. Bid Intelligence Analysis
    llm_provider = DeterministicLLMProvider()
    intelligence_res = llm_provider.analyze_bid(bid, match_results)

    # 3. Opportunity Analysis
    opp_analyzer = OpportunityAnalyzer()
    opp_res = opp_analyzer.analyze_opportunity(bid, intelligence_res)

    # Persist BidScore
    highest_rel = opp_res.relevance_score
    highest_label = "UNMATCHED"
    if match_results:
        highest_label = match_results[0].match_state

    # Remove existing score/analysis for clean re-run
    db.query(BidScore).filter(BidScore.bid_id == bid.id).delete()
    db.query(BidAnalysis).filter(BidAnalysis.bid_id == bid.id).delete()
    db.flush()

    analysis = BidAnalysis(
        bid_id=bid.id,
        engine_version="Phase4-Full-Intelligence",
        model_used="Deterministic-LLM-Engine",
        product_matches=[r.to_dict() for r in match_results],
        eligibility_analysis=[e.model_dump(mode="json") for e in intelligence_res.eligibility_assessments],
        concerns=[r.model_dump(mode="json") for r in intelligence_res.risk_indicators],
        evidence=[req.model_dump(mode="json") for req in intelligence_res.requirements],
        llm_output=intelligence_res.model_dump(mode="json"),
    )
    db.add(analysis)
    db.flush()

    score_rec = BidScore(
        bid_id=bid.id,
        analysis_id=analysis.id,
        relevance_score=highest_rel,
        opportunity_score=opp_res.opportunity_score,
        relevance_label=highest_label,
        urgency=intelligence_res.deadline_intelligence.status,
        score_breakdown={
            "opportunity_analysis": opp_res.model_dump(mode="json"),
            "highest_product_match": match_results[0].to_dict() if match_results else None,
        },
    )

    db.add(score_rec)

    # Create Notification if High Relevance / High Opportunity
    # Closed bids never generate new actionable notifications.
    created_notif: Optional[Notification] = None
    if not is_bid_closed(bid) and (highest_rel >= 0.70 or opp_res.opportunity_score >= 0.70):
        existing_notif = db.query(Notification).filter(
            Notification.bid_id == bid.id,
            Notification.notification_type == "NEW_HIGH_RELEVANCE",
        ).first()
        if not existing_notif:
            created_notif = Notification(
                bid_id=bid.id,
                channel="EMAIL",
                recipient="security-team@securedapp.com",
                notification_type="NEW_HIGH_RELEVANCE",
                deduplication_key=f"notif_{bid.id}_high_relevance",
                status="PENDING",
            )
            db.add(created_notif)

    db.commit()

    # Real dispatch when SMTP is configured; a no-op (row stays queued) when
    # it is not, which is the default deployment.
    if created_notif is not None:
        from app.services.notification_delivery import try_dispatch

        try_dispatch(db, created_notif)

    return {
        "bid_id": str(bid.id),
        "bid_title": bid.title,
        "intelligence": intelligence_res.model_dump(),
        "opportunity": opp_res.model_dump(),
    }


@router.get("/bids/{bid_id}/analysis", status_code=status.HTTP_200_OK)
def get_bid_analysis(bid_id: UUID, db: Session = Depends(get_db)):
    """Retrieve existing analysis and scores for a bid."""
    bid = db.get(Bid, bid_id)
    if not bid:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Bid not found")
    analysis = db.query(BidAnalysis).filter(BidAnalysis.bid_id == bid.id).order_by(BidAnalysis.analyzed_at.desc()).first()
    score = db.query(BidScore).filter(BidScore.bid_id == bid.id).first()
    return {
        "bid_id": str(bid.id),
        "analysis": analysis,
        "score": score,
    }


@router.post("/bids/{bid_id}/review", status_code=status.HTTP_201_CREATED)
def submit_human_review(bid_id: UUID, review_in: HumanReviewCreate, db: Session = Depends(get_db)):
    """Submit a human review decision (relevant / irrelevant / uncertain).

    Validation happens in :class:`HumanReviewCreate`. An identical
    resubmission (double-click, retry) is idempotent: it returns the existing
    latest row instead of adding another, so duplicate labels can never
    inflate evaluation counts. A *changed* decision still appends history.
    """
    bid = db.get(Bid, bid_id)
    if not bid:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Bid not found")

    latest = (
        db.query(HumanReview)
        .filter(HumanReview.bid_id == bid.id)
        .order_by(HumanReview.reviewed_at.desc(), HumanReview.id.desc())
        .first()
    )
    if (
        latest is not None
        and latest.relevance_decision == review_in.relevance_decision
        and latest.pursue_decision == review_in.pursue_decision
        and (latest.comments or None) == (review_in.comments or None)
    ):
        return latest

    review = HumanReview(
        bid_id=bid.id,
        relevance_decision=review_in.relevance_decision,
        pursue_decision=review_in.pursue_decision,
        comments=review_in.comments,
    )
    db.add(review)
    db.commit()
    db.refresh(review)
    return review


@router.get("/bids/{bid_id}/reviews", status_code=status.HTTP_200_OK)
def get_human_reviews(bid_id: UUID, db: Session = Depends(get_db)):
    """Get audit history of human reviews for a bid."""
    reviews = db.query(HumanReview).filter(HumanReview.bid_id == bid_id).order_by(HumanReview.reviewed_at.desc()).all()
    return reviews


@router.get("/notifications", response_model=List[NotificationResponse], status_code=status.HTTP_200_OK)
def list_notifications(db: Session = Depends(get_db)):
    """
    List notification logs with an explicit delivery status.

    Each row keeps its raw ``status``/``sent_at`` for existing consumers and adds
    a derived ``delivery_state`` (QUEUED / DELIVERED / FAILED), a
    ``delivery_configured`` flag and a human-readable ``delivery_note``.
    ``delivery_configured`` is true only when SMTP credentials are present;
    without them alerts are reported as QUEUED -- never as delivered. SMTP
    settings themselves are never part of this response.
    """
    from app.services.notification_delivery import describe_delivery

    rows = db.query(Notification).order_by(Notification.id.desc()).limit(100).all()
    return [
        {
            "id": n.id,
            "bid_id": n.bid_id,
            "channel": n.channel,
            "recipient": n.recipient,
            "notification_type": n.notification_type,
            "deduplication_key": n.deduplication_key,
            "status": n.status,
            "sent_at": n.sent_at,
            **describe_delivery(n),
        }
        for n in rows
    ]


@router.post("/notifications/dispatch", status_code=status.HTTP_200_OK)
def dispatch_queued_notifications(
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    """
    Attempt delivery of up to ``limit`` queued EMAIL notifications.

    Idempotent and bounded. Without SMTP configuration this reports
    ``configured: false`` and dispatches nothing; rows already SENT are never
    re-sent.
    """
    from app.services.notification_delivery import dispatch_pending

    return dispatch_pending(db, limit=limit)


@router.post("/notifications/{notification_id}/deliver", status_code=status.HTTP_200_OK)
def deliver_notification(notification_id: UUID, db: Session = Depends(get_db)):
    """
    Send or retry one notification through the configured provider.

    Marks the row SENT only after the provider accepts the message; a row that
    is already SENT short-circuits (duplicate-send prevention) and an
    unconfigured deployment returns the explicit not-configured state without
    opening a connection.
    """
    from app.services.notification_delivery import attempt_delivery

    row = db.get(Notification, notification_id)
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found")
    outcome = attempt_delivery(db, row)
    outcome["status"] = row.status  # raw stored state after the attempt
    return outcome


@router.get("/analytics/evaluation", status_code=status.HTTP_200_OK)
def get_evaluation_metrics(db: Session = Depends(get_db)):
    """
    Compare the matching engine's relevance predictions against validated human
    review labels.

    Only ``RELEVANT`` / ``NOT_RELEVANT`` reviews count as ground truth (``MAYBE``
    is excluded), reviews are de-duplicated to the latest per bid, and a review
    is only evaluated when its bid has a persisted score. Precision, recall,
    agreement and F1 are returned together with the sample size, an explicit
    ``accuracy_measured`` flag, and the limitations of the measurement -- so a
    small sample is never mistaken for a measured accuracy.
    """
    from app.services.matching_evaluation import evaluate_matching

    return evaluate_matching(db)
