import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Text, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from app.core.database import Base
from app.models.base_mixins import GUID


class HumanReview(Base):
    __tablename__ = "human_reviews"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    bid_id = Column(GUID(), ForeignKey("bids.id", ondelete="CASCADE"), nullable=False)
    reviewer_id = Column(GUID(), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    relevance_decision = Column(String(50), nullable=False)  # RELEVANT, NOT_RELEVANT, MAYBE
    pursue_decision = Column(String(50), nullable=False)    # PURSUE, DONT_PURSUE, PENDING
    comments = Column(Text(), nullable=True)
    reviewed_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    bid = relationship("Bid", back_populates="reviews")
    reviewer = relationship("User")
