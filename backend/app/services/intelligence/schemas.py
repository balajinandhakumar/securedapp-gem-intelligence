"""
Pydantic schemas for Bid Intelligence, Structured Requirement Extraction,
Eligibility Analysis, and AI Provider Abstraction.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class EvidenceItem(BaseModel):
    finding: str = Field(..., description="Key intelligence finding or requirement")
    evidence: str = Field(..., description="Exact snippet or source text excerpt")
    field: Optional[str] = Field(None, description="Source field in the bid")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    status: str = Field(
        default="CONFIRMED",
        description="CONFIRMED, UNKNOWN, POTENTIAL_CONFLICT, REQUIRES_HUMAN_VERIFICATION",
    )
    reason: Optional[str] = Field(None, description="Contextual explanation")


class BidRequirement(BaseModel):
    category: str = Field(
        ...,
        description=(
            "technical_requirements, functional_requirements, security_requirements, "
            "identity_requirements, blockchain_requirements, cryptography_requirements, "
            "smart_contract_requirements, compliance_requirements, experience_requirements, "
            "qualification_requirements, certifications, geographical_requirements, "
            "organizational_requirements, financial_requirements, mandatory_conditions"
        ),
    )
    requirement_text: str = Field(..., description="Requirement description")
    evidence: Optional[EvidenceItem] = None
    is_mandatory: bool = True


class EligibilityAssessment(BaseModel):
    requirement_name: str
    status: str = Field(
        default="UNKNOWN",
        description="CONFIRMED, UNKNOWN, POTENTIAL_CONFLICT, REQUIRES_HUMAN_VERIFICATION",
    )
    evidence_snippet: Optional[str] = None
    reason: str
    requires_human: bool = True


class RiskIndicator(BaseModel):
    risk_type: str  # e.g., DEADLINE_URGENT, MISSING_BUDGET, COMPLEX_COMPLIANCE
    severity: str  # HIGH, MEDIUM, LOW
    description: str
    evidence_snippet: Optional[str] = None


class DeadlineIntelligence(BaseModel):
    published_date: Optional[datetime] = None
    closing_date: Optional[datetime] = None
    days_remaining: Optional[float] = None
    status: str = Field(
        default="UNKNOWN",
        description="NORMAL, UPCOMING, URGENT, CLOSING_SOON, CLOSED, UNKNOWN",
    )


class ProductReasoning(BaseModel):
    product_name: str
    matched: bool
    confidence: float
    relevance_score: float
    match_state: str  # MATCH, POSSIBLE_MATCH, NEEDS_REVIEW, NO_MATCH
    signals: List[Dict[str, Any]] = []
    reason: str


class BidIntelligenceResult(BaseModel):
    bid_id: str
    bid_title: str
    analysis_version: str = "Phase4-Structured-v1"
    analyzed_at: datetime
    deadline_intelligence: DeadlineIntelligence
    requirements: List[BidRequirement] = []
    eligibility_assessments: List[EligibilityAssessment] = []
    risk_indicators: List[RiskIndicator] = []
    product_reasoning: List[ProductReasoning] = []
    missing_information: List[str] = []
    human_verification_needed: bool = True
