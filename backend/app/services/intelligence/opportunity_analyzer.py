"""
Opportunity Intelligence Analyzer.

Separates Relevance Score from Opportunity Score with a transparent, configurable formula.
Evaluates deal size, deadline feasibility, eligibility confidence, and risk factors.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from app.models.bid import Bid
from app.services.intelligence.schemas import BidIntelligenceResult


class ComponentScore(BaseModel):
    name: str
    weight: float
    raw_value: float
    weighted_score: float
    description: str


class OpportunityAnalysisResult(BaseModel):
    bid_id: str
    bid_title: str
    relevance_score: float = Field(..., description="Highest product relevance score")
    opportunity_score: float = Field(..., ge=0.0, le=1.0, description="Overall opportunity rating score")
    opportunity_label: str = Field(..., description="HIGH_OPPORTUNITY, MEDIUM_OPPORTUNITY, LOW_OPPORTUNITY, UNMATCHED")
    urgency_label: str = Field(..., description="NORMAL, UPCOMING, URGENT, CLOSING_SOON, CLOSED, UNKNOWN")
    score_breakdown: List[ComponentScore] = []
    missing_information: List[str] = []
    reason: str


class OpportunityAnalyzer:
    def __init__(
        self,
        weights: Optional[Dict[str, float]] = None,
    ):
        self.weights = weights or {
            "relevance": 0.50,
            "estimated_value": 0.20,
            "eligibility": 0.15,
            "urgency": 0.15,
        }

    def analyze_opportunity(
        self,
        bid: Bid,
        intelligence: BidIntelligenceResult,
    ) -> OpportunityAnalysisResult:
        missing_info: List[str] = list(intelligence.missing_information)

        # 1. Relevance Component
        max_rel = 0.0
        if intelligence.product_reasoning:
            max_rel = max((p.relevance_score for p in intelligence.product_reasoning), default=0.0)
        rel_weighted = max_rel * self.weights["relevance"]

        comp_rel = ComponentScore(
            name="Product Relevance",
            weight=self.weights["relevance"],
            raw_value=round(max_rel, 3),
            weighted_score=round(rel_weighted, 3),
            description="Max product capability relevance score",
        )

        # 2. Estimated Value Component
        val_score = 0.5  # default if unstated
        if bid.estimated_value and float(bid.estimated_value) > 0:
            val_flt = float(bid.estimated_value)
            # Log scale: 10 Lakhs = 0.5, 1 Cr = 0.7, 10 Cr+ = 1.0
            val_score = min(1.0, max(0.2, (math.log10(val_flt) - 4.0) / 4.0))
        else:
            missing_info.append("Unstated contract value; defaulted to neutral factor (0.5).")

        val_weighted = val_score * self.weights["estimated_value"]
        comp_val = ComponentScore(
            name="Contract Value Alignment",
            weight=self.weights["estimated_value"],
            raw_value=round(val_score, 3),
            weighted_score=round(val_weighted, 3),
            description=f"Estimated value factor (₹{bid.estimated_value or 'Unstated'})",
        )

        # 3. Eligibility Confidence Component
        elig_score = 0.5
        if intelligence.eligibility_assessments:
            confirmed_cnt = sum(1 for e in intelligence.eligibility_assessments if e.status == "CONFIRMED")
            total_cnt = len(intelligence.eligibility_assessments)
            elig_score = confirmed_cnt / float(total_cnt) if total_cnt > 0 else 0.5
        elig_weighted = elig_score * self.weights["eligibility"]
        comp_elig = ComponentScore(
            name="Eligibility Confidence",
            weight=self.weights["eligibility"],
            raw_value=round(elig_score, 3),
            weighted_score=round(elig_weighted, 3),
            description="Proportion of confirmed eligibility requirements",
        )

        # 4. Deadline Urgency Component
        urg_status = intelligence.deadline_intelligence.status
        urg_map = {
            "NORMAL": 1.0,
            "UPCOMING": 0.8,
            "URGENT": 0.6,
            "CLOSING_SOON": 0.3,
            "CLOSED": 0.0,
            "UNKNOWN": 0.5,
        }
        urg_score = urg_map.get(urg_status, 0.5)
        urg_weighted = urg_score * self.weights["urgency"]
        comp_urg = ComponentScore(
            name="Deadline Feasibility",
            weight=self.weights["urgency"],
            raw_value=round(urg_score, 3),
            weighted_score=round(urg_weighted, 3),
            description=f"Deadline feasibility ({urg_status})",
        )

        # Total Opportunity Score
        total_opp = rel_weighted + val_weighted + elig_weighted + urg_weighted
        total_opp = max(0.0, min(1.0, total_opp))

        # Classification
        if total_opp >= 0.70:
            opp_label = "HIGH_OPPORTUNITY"
        elif total_opp >= 0.45:
            opp_label = "MEDIUM_OPPORTUNITY"
        elif total_opp >= 0.25:
            opp_label = "LOW_OPPORTUNITY"
        else:
            opp_label = "UNMATCHED"

        reason = (
            f"Opportunity score of {round(total_opp, 2)} ({opp_label}) computed from "
            f"Relevance ({round(max_rel, 2)}), Value ({round(val_score, 2)}), "
            f"Eligibility ({round(elig_score, 2)}), and Deadline ({urg_status})."
        )

        return OpportunityAnalysisResult(
            bid_id=str(bid.id),
            bid_title=bid.title or "Untitled Bid",
            relevance_score=round(max_rel, 3),
            opportunity_score=round(total_opp, 3),
            opportunity_label=opp_label,
            urgency_label=urg_status,
            score_breakdown=[comp_rel, comp_val, comp_elig, comp_urg],
            missing_information=missing_info,
            reason=reason,
        )
