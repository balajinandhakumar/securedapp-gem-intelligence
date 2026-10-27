import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Text, Integer, DateTime, ForeignKey, JSON
from sqlalchemy.orm import relationship
from app.core.database import Base
from app.models.base_mixins import GUID


class CollectionRun(Base):
    __tablename__ = "collection_runs"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    source_adapter = Column(String(100), nullable=False)  # e.g., ManualFileAdapter, GeMAdapter
    started_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    finished_at = Column(DateTime(timezone=True), nullable=True)
    status = Column(String(50), default="RUNNING", nullable=False)  # RUNNING, SUCCESS, FAILED, PARTIAL
    records_found = Column(Integer(), default=0, nullable=False)
    records_new = Column(Integer(), default=0, nullable=False)
    records_duplicate = Column(Integer(), default=0, nullable=False)
    error_count = Column(Integer(), default=0, nullable=False)
    notes = Column(Text(), nullable=True)

    raw_payloads = relationship("RawBidPayload", back_populates="collection_run", cascade="all, delete-orphan")


class RawBidPayload(Base):
    __tablename__ = "raw_bid_payloads"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    collection_run_id = Column(GUID(), ForeignKey("collection_runs.id", ondelete="SET NULL"), nullable=True)
    raw_content = Column(JSON, nullable=False)
    source_reference = Column(String(255), nullable=True)
    checksum = Column(String(64), nullable=True)
    ingested_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    collection_run = relationship("CollectionRun", back_populates="raw_payloads")
