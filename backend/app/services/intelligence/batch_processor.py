"""
Batch Intelligence Pipeline Processor.

Orchestrates full Stage 2 batch processing:
Ingestion → Validation → Normalization → Deduplication / Update → DB Persistence
→ 11-Product Matching & Differentiation → Requirement / Eligibility Analysis
→ Opportunity Analysis → Notification Generation → Audit / Metrics.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, BinaryIO, Dict, List, Optional, Union
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.analysis import BidAnalysis, BidProductMatch, BidScore
from app.models.bid import Bid
from app.models.collection import CollectionRun
from app.models.notification import Notification
from app.services.ingestion.pipeline import run_ingestion_pipeline
from app.services.ingestion.schemas import ImportResult
from app.services.bid_views import is_bid_closed
from app.services.intelligence.matching_engine import match_bid_against_products
from app.services.intelligence.opportunity_analyzer import OpportunityAnalyzer
from app.services.intelligence.providers import DeterministicLLMProvider

logger = logging.getLogger(__name__)

# A stored product match must rest on real bidding evidence. Only candidates the
# engine positively classified (at least NEEDS_REVIEW, i.e. score >= 0.25) with a
# genuine positive/regular signal may be persisted. A NO_MATCH candidate -- or a
# candidate whose only signals are exclusions -- carries no evidence of relevance
# and must never be stored as if it matched.
_PERSISTABLE_STATES = frozenset({"MATCH", "POSSIBLE_MATCH", "NEEDS_REVIEW"})


@dataclass
class BatchIntelligenceSummary:
    run_id: UUID
    total_input_bids: int
    successfully_processed: int
    rejected: int
    duplicates: int
    updated_records: int
    relevant_matches: int
    possible_matches: int
    needs_review_records: int
    no_match_records: int
    notifications_generated: int
    processing_time_seconds: float
    avg_time_per_bid_ms: float
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_id": str(self.run_id),
            "total_input_bids": self.total_input_bids,
            "successfully_processed": self.successfully_processed,
            "rejected": self.rejected,
            "duplicates": self.duplicates,
            "updated_records": self.updated_records,
            "relevant_matches": self.relevant_matches,
            "possible_matches": self.possible_matches,
            "needs_review_records": self.needs_review_records,
            "no_match_records": self.no_match_records,
            "notifications_generated": self.notifications_generated,
            "processing_time_seconds": round(self.processing_time_seconds, 3),
            "avg_time_per_bid_ms": round(self.avg_time_per_bid_ms, 2),
            "details": self.details,
        }


def process_bid_intelligence(
    db: Session,
    bid: Bid,
    llm_provider: Optional[DeterministicLLMProvider] = None,
    opp_analyzer: Optional[OpportunityAnalyzer] = None,
    auto_notify: bool = True,
    commit: bool = True,
) -> Dict[str, Any]:
    """
    Executes full intelligence matching, requirement extraction,
    opportunity scoring, and notification generation for a single bid.
    """
    if llm_provider is None:
        llm_provider = DeterministicLLMProvider()
    if opp_analyzer is None:
        opp_analyzer = OpportunityAnalyzer()

    # 1. Product Matching against 11 SecuredApp products + differentiation
    match_results = match_bid_against_products(db, bid)

    # 2. Structured Requirement Extraction & Eligibility Analysis
    intelligence_res = llm_provider.analyze_bid(bid, match_results)

    # 3. Opportunity Analysis
    opp_res = opp_analyzer.analyze_opportunity(bid, intelligence_res)

    # Determine highest relevance and match state
    highest_rel = opp_res.relevance_score
    highest_label = "UNMATCHED"
    if match_results:
        highest_label = match_results[0].match_state

    # Remove existing score/analysis for clean re-run
    db.query(BidScore).filter(BidScore.bid_id == bid.id).delete()
    db.query(BidAnalysis).filter(BidAnalysis.bid_id == bid.id).delete()
    db.flush()

    # Persist BidAnalysis
    analysis = BidAnalysis(
        bid_id=bid.id,
        engine_version="Stage2-Batch-Intelligence",
        model_used="Deterministic-LLM-Engine",
        product_matches=[r.to_dict() for r in match_results],
        eligibility_analysis=[e.model_dump(mode="json") for e in intelligence_res.eligibility_assessments],
        concerns=[r.model_dump(mode="json") for r in intelligence_res.risk_indicators],
        evidence=[req.model_dump(mode="json") for req in intelligence_res.requirements],
        llm_output=intelligence_res.model_dump(mode="json"),
    )
    db.add(analysis)
    db.flush()

    # Persist BidScore
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

    # Persist product matches for queryable audit and dashboard use.
    # Only persist candidates the engine positively classified with genuine
    # positive evidence (same bar as the /api/v1/bids/{id}/match-products endpoint).
    db.query(BidProductMatch).filter(BidProductMatch.bid_id == bid.id).delete()
    for res in match_results:
        if res.match_state not in _PERSISTABLE_STATES or res.relevance_score < 0.25:
            continue
        if not any(s.get("strength") != "EXCLUSION" for s in res.signals):
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

    # Notification Handling (Relevance >= 0.70 or Opportunity >= 0.70)
    # Closed bids never generate new actionable notifications.
    notification_created = False
    created_notif = None
    if auto_notify and not is_bid_closed(bid) and (highest_rel >= 0.70 or opp_res.opportunity_score >= 0.70):
        notif_key = f"notif_{bid.id}_high_relevance"
        existing_notif = db.query(Notification).filter(
            Notification.bid_id == bid.id,
            Notification.notification_type == "NEW_HIGH_RELEVANCE",
        ).first()

        if not existing_notif:
            matched_product_name = match_results[0].product_name if match_results else "SecuredApp Product"
            created_notif = Notification(
                bid_id=bid.id,
                channel="EMAIL",
                recipient="security-team@securedapp.com",
                notification_type="NEW_HIGH_RELEVANCE",
                deduplication_key=notif_key,
                status="PENDING",
            )
            db.add(created_notif)
            notification_created = True

    if commit:
        db.commit()
        # Real dispatch only when SMTP is configured (no-op otherwise) and only
        # when this call owns the commit; with commit=False the caller owns the
        # transaction and may still roll back.
        if created_notif is not None:
            from app.services.notification_delivery import try_dispatch

            try_dispatch(db, created_notif)

    return {
        "bid_id": str(bid.id),
        "relevance_score": highest_rel,
        "match_state": highest_label,
        "opportunity_score": opp_res.opportunity_score,
        "opportunity_label": opp_res.opportunity_label,
        "notification_created": notification_created,
        "primary_product": match_results[0].product_name if match_results else None,
    }


def run_batch_intelligence_pipeline(
    db: Session,
    file_content: Union[bytes, str, BinaryIO],
    file_type: str = "json",
    source_name: str = "synthetic_gem_dev_dataset",
    allow_update_duplicates: bool = True,
    auto_notify: bool = True,
) -> BatchIntelligenceSummary:
    """
    Executes the end-to-end Stage 2 batch pipeline:
    1. Ingestion, validation, normalization, deduplication & persistence
    2. 11-product matching, differentiation, requirement extraction, opportunity analysis
    3. Notification triggering and comprehensive metric calculation
    """
    start_time = time.perf_counter()

    # Step 1: Ingestion Pipeline
    import_res = run_ingestion_pipeline(
        db=db,
        file_content=file_content,
        file_type=file_type,
        source_name=source_name,
        allow_update_duplicates=allow_update_duplicates,
    )

    # Step 2: Fetch all bids to evaluate intelligence
    # Retrieve bids that belong to the current database or were just ingested
    all_bids = db.query(Bid).all()

    llm_provider = DeterministicLLMProvider()
    opp_analyzer = OpportunityAnalyzer()

    relevant_count = 0
    possible_count = 0
    needs_review_count = 0
    no_match_count = 0
    notifs_count = 0

    # Step 3: Run Intelligence & Opportunity Evaluation on each bid
    for bid in all_bids:
        res = process_bid_intelligence(
            db=db,
            bid=bid,
            llm_provider=llm_provider,
            opp_analyzer=opp_analyzer,
            auto_notify=auto_notify,
            commit=False,
        )

        state = res["match_state"]
        if state == "MATCH":
            relevant_count += 1
        elif state == "POSSIBLE_MATCH":
            possible_count += 1
        elif state == "NEEDS_REVIEW":
            needs_review_count += 1
        else:
            no_match_count += 1

        if res["notification_created"]:
            notifs_count += 1

    db.commit()

    total_time = time.perf_counter() - start_time
    total_processed = len(all_bids)
    avg_time_ms = (total_time / total_processed * 1000.0) if total_processed > 0 else 0.0

    return BatchIntelligenceSummary(
        run_id=import_res.run_id,
        total_input_bids=import_res.total_records,
        successfully_processed=import_res.created + import_res.updated,
        rejected=import_res.failed,
        duplicates=import_res.duplicates,
        updated_records=import_res.updated,
        relevant_matches=relevant_count,
        possible_matches=possible_count,
        needs_review_records=needs_review_count,
        no_match_records=no_match_count,
        notifications_generated=notifs_count,
        processing_time_seconds=total_time,
        avg_time_per_bid_ms=avg_time_ms,
        details={
            "status": import_res.status,
            "created": import_res.created,
            "updated": import_res.updated,
            "duplicates": import_res.duplicates,
            "errors": [err.model_dump() if hasattr(err, "model_dump") else str(err) for err in import_res.errors],
        },
    )
