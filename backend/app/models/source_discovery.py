"""
Source Discovery Ledger.

Tracks every GeM bid identifier observed during collection, regardless of
whether it was classified as relevant enough to persist as a business bid.

This lets the system distinguish:

* A bid that was genuinely never seen on GeM (never discovered).
* A bid that was discovered but classified NO_MATCH and therefore not stored
  as a business bid (discovered, not persisted).
* A bid that was discovered and persisted as a business bid (discovered +
  persisted).

A NO_MATCH bid must never be incorrectly reported as an unobserved source bid.

This table is additive: it never modifies existing bids, analysis, or
notification records. It is safe to add to an existing database with
historical data.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Column, String, DateTime, Integer, ForeignKey, Index, Text, Boolean, Float
from sqlalchemy.orm import relationship

from app.core.database import Base
from app.models.base_mixins import GUID


class SourceDiscovery(Base):
    """
    One row per unique GeM bid identifier observed during collection.

    ``gem_bid_id`` is the primary identity from GeM. ``bid_number`` is kept
    separately because some GeM pages print one but not the other.
    """

    __tablename__ = "source_discoveries"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)

    # --- GeM source identity ------------------------------------------------
    gem_bid_id = Column(String(100), nullable=True)
    bid_number = Column(String(100), nullable=True)

    # Canonical composite identity when GeM does not print a stable ID.
    # Derived from stable fields (title + organisation + closing_date), so
    # a corrigendum that only moves dates keeps the same composite ID.
    composite_identity = Column(String(64), nullable=True)

    # --- Collection context -------------------------------------------------
    source_url = Column(Text(), nullable=True)
    listing_page = Column(Integer, nullable=True)
    collection_run_id = Column(
        GUID(), ForeignKey("collection_runs.id", ondelete="SET NULL"), nullable=True
    )

    # --- Timestamps ---------------------------------------------------------
    first_discovered_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    last_observed_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # --- Status -------------------------------------------------------------
    # "discovered" | "updated" | "duplicate"
    discovery_status = Column(String(20), nullable=False, default="discovered")

    # Was this bid persisted as a business bid (relevance >= 0.25)?
    persisted_as_business_bid = Column(Boolean, nullable=False, default=False)

    # Relevance score if the bid was analyzed (NULL when NO_MATCH / not analyzed).
    relevance_score = Column(Float(), nullable=True)

    # --- Optional metadata --------------------------------------------------
    title = Column(Text(), nullable=True)
    organisation = Column(String(255), nullable=True)
    category = Column(String(255), nullable=True)

    collection_run = relationship("CollectionRun", back_populates="source_discoveries")

    __table_args__ = (
        Index("ix_source_discoveries_gem_bid_id", "gem_bid_id"),
        Index("ix_source_discoveries_composite", "composite_identity"),
        Index("ix_source_discoveries_last_observed", "last_observed_at"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return (
            f"<SourceDiscovery gem_bid_id={self.gem_bid_id!r} "
            f"page={self.listing_page} persisted={self.persisted_as_business_bid}>"
        )


# Backwards-compatible alias for code that imports the old name.
GemSourceDiscovery = SourceDiscovery
