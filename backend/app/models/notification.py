import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from app.core.database import Base
from app.models.base_mixins import GUID


class Notification(Base):
    __tablename__ = "notifications"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    bid_id = Column(GUID(), ForeignKey("bids.id", ondelete="CASCADE"), nullable=False)
    channel = Column(String(50), nullable=False)  # EMAIL, WHATSAPP, TEAMS, SLACK
    recipient = Column(String(255), nullable=False)
    notification_type = Column(String(50), nullable=False)  # NEW_HIGH_RELEVANCE, DIGEST, EXPIRING_SOON
    deduplication_key = Column(String(255), index=True, nullable=True)
    status = Column(String(50), default="PENDING", nullable=False)  # PENDING, SENT, FAILED
    sent_at = Column(DateTime(timezone=True), nullable=True)

    bid = relationship("Bid", back_populates="notifications")
