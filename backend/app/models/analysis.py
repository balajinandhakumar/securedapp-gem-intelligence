import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Float, DateTime, JSON, ForeignKey
from sqlalchemy.orm import relationship
from app.core.database import Base
from app.models.base_mixins import GUID


class BidAnalysis(Base):
    __tablename__ = "bid_analysis"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    bid_id = Column(GUID(), ForeignKey("bids.id", ondelete="CASCADE"), nullable=False)
    engine_version = Column(String(50), nullable=False)
    model_used = Column(String(100), nullable=True)
    keyword_results = Column(JSON, nullable=True)
    semantic_results = Column(JSON, nullable=True)
    product_matches = Column(JSON, nullable=True)
    eligibility_analysis = Column(JSON, nullable=True)
    concerns = Column(JSON, nullable=True)
    evidence = Column(JSON, nullable=True)
    llm_output = Column(JSON, nullable=True)
    analyzed_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    bid = relationship("Bid", back_populates="analyses")
    scores = relationship("BidScore", back_populates="analysis", cascade="all, delete-orphan")


class BidScore(Base):
    __tablename__ = "bid_scores"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    bid_id = Column(GUID(), ForeignKey("bids.id", ondelete="CASCADE"), nullable=False)
    analysis_id = Column(GUID(), ForeignKey("bid_analysis.id", ondelete="CASCADE"), nullable=False)
    relevance_score = Column(Float(), nullable=False)
    opportunity_score = Column(Float(), nullable=False)
    relevance_label = Column(String(50), nullable=False)  # HIGH, MEDIUM, LOW, UNMATCHED
    urgency = Column(String(50), nullable=False)  # CRITICAL, HIGH, MEDIUM, NORMAL
    score_breakdown = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    bid = relationship("Bid", back_populates="scores")
    analysis = relationship("BidAnalysis", back_populates="scores")


class BidProductMatch(Base):
    __tablename__ = "bid_product_matches"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    bid_id = Column(GUID(), ForeignKey("bids.id", ondelete="CASCADE"), nullable=False)
    product_id = Column(GUID(), ForeignKey("products.id", ondelete="CASCADE"), nullable=False)
    match_score = Column(Float(), nullable=False)
    match_type = Column(String(50), nullable=False)  # KEYWORD, SEMANTIC, LLM, COMBINED
    evidence = Column(JSON, nullable=True)
    confidence = Column(Float(), default=1.0, nullable=False)

    bid = relationship("Bid", back_populates="product_matches")
    product = relationship("Product")
