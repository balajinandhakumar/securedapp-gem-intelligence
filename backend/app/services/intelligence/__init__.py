"""
Intelligence service package for SecuredApp GeM Bid Intelligence Platform.

Contains the deterministic bid-to-product matching engine, requirement extraction,
eligibility analysis, deadline intelligence, AI/LLM & embedding abstractions,
and opportunity scoring.
"""
from app.services.intelligence.matching_engine import (
    BidMatcherEngine,
    ProductMatchResult,
    classify_score,
    match_bid_against_products,
)
from app.services.intelligence.opportunity_analyzer import (
    OpportunityAnalysisResult,
    OpportunityAnalyzer,
)
from app.services.intelligence.providers import (
    DeterministicLLMProvider,
    EmbeddingProvider,
    LLMProvider,
    MockEmbeddingProvider,
    OpenAILLMProvider,
)
from app.services.intelligence.schemas import (
    BidIntelligenceResult,
    BidRequirement,
    DeadlineIntelligence,
    EligibilityAssessment,
    EvidenceItem,
    ProductReasoning,
    RiskIndicator,
)
from app.services.intelligence.batch_processor import (
    BatchIntelligenceSummary,
    process_bid_intelligence,
    run_batch_intelligence_pipeline,
)

__all__ = [
    "BidMatcherEngine",
    "ProductMatchResult",
    "classify_score",
    "match_bid_against_products",
    "OpportunityAnalysisResult",
    "OpportunityAnalyzer",
    "LLMProvider",
    "DeterministicLLMProvider",
    "OpenAILLMProvider",
    "EmbeddingProvider",
    "MockEmbeddingProvider",
    "BidIntelligenceResult",
    "BidRequirement",
    "DeadlineIntelligence",
    "EligibilityAssessment",
    "EvidenceItem",
    "ProductReasoning",
    "RiskIndicator",
    "run_batch_intelligence_pipeline",
    "process_bid_intelligence",
    "BatchIntelligenceSummary",
]
