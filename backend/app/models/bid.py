import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Text, Numeric, DateTime, JSON, ForeignKey
from sqlalchemy.orm import relationship
from app.core.database import Base
from app.models.base_mixins import GUID, TimestampMixin


class Bid(Base, TimestampMixin):
    __tablename__ = "bids"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    gem_bid_id = Column(String(100), index=True, nullable=True)
    bid_number = Column(String(100), index=True, nullable=True)
    title = Column(Text(), nullable=False)
    organisation = Column(String(255), nullable=True)
    department = Column(String(255), nullable=True)
    ministry = Column(String(255), nullable=True)
    category = Column(String(255), nullable=True)
    bid_type = Column(String(100), nullable=True)
    published_date = Column(DateTime(timezone=True), nullable=True)
    closing_date = Column(DateTime(timezone=True), nullable=True)
    location = Column(String(255), nullable=True)
    estimated_value = Column(Numeric(15, 2), nullable=True)
    currency = Column(String(10), default="INR", nullable=False)
    scope_of_work = Column(Text(), nullable=True)
    technical_requirements = Column(JSON, nullable=True)
    # Authoritative Bill-of-Quantities line items, kept separate from the
    # bid title / scope_of_work (which GeM's public listing truncates to ~99
    # chars in its data-content popover). Shape:
    #   {"items": [{item_number,title,description,quantity,unit,...}],
    #    "item_count": int, "source_url": str, "retrieved_at": iso8601}
    boq_items = Column(JSON, nullable=True)
    # When automatic BoQ enrichment last *attempted* this bid (whether or not a
    # CSV was found), so a bid with no published BoQ is never re-fetched on
    # every collection. NULL = never attempted. Manual CLI runs do not set it.
    boq_checked_at = Column(DateTime(timezone=True), nullable=True)
    eligibility_criteria = Column(JSON, nullable=True)
    qualification_requirements = Column(JSON, nullable=True)
    experience_requirements = Column(JSON, nullable=True)
    certification_requirements = Column(JSON, nullable=True)
    emd_information = Column(JSON, nullable=True)
    tender_fee_information = Column(JSON, nullable=True)
    contact_information = Column(JSON, nullable=True)
    source_url = Column(Text(), nullable=True)
    source_name = Column(String(255), nullable=True)  # ingestion adapter / source feed name
    search_text = Column(Text(), nullable=True)        # pre-computed search index text
    content_hash = Column(String(64), index=True, nullable=True)
    status = Column(String(50), default="NEW", nullable=False)  # NEW, PROCESSED, ARCHIVED, EXPIRED
    first_discovered_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    last_updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    analyses = relationship("BidAnalysis", back_populates="bid", cascade="all, delete-orphan")
    scores = relationship("BidScore", back_populates="bid", cascade="all, delete-orphan")
    product_matches = relationship("BidProductMatch", back_populates="bid", cascade="all, delete-orphan")
    reviews = relationship("HumanReview", back_populates="bid", cascade="all, delete-orphan")
    notifications = relationship("Notification", back_populates="bid", cascade="all, delete-orphan")
    status_history = relationship("BidStatusHistory", back_populates="bid", cascade="all, delete-orphan")


class BidStatusHistory(Base):
    __tablename__ = "bid_status_history"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    bid_id = Column(GUID(), ForeignKey("bids.id", ondelete="CASCADE"), nullable=False)
    old_status = Column(String(50), nullable=True)
    new_status = Column(String(50), nullable=False)
    changed_by = Column(String(255), nullable=True)
    reason = Column(Text(), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    bid = relationship("Bid", back_populates="status_history")
