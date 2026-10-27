"""
Configurable multi-source registry for the bid intelligence platform.

``DataSource`` is one configured, enabled/disabled collection source (an
RSS/Atom feed, a JSON API, or a public HTML listing). ``SourceRun`` records
every manual or scheduled collection attempt against that source, with
per-stage counters (discovered / validated / rejected / inserted / updated /
duplicated) and *safe* error details.

Secrets are never stored here: any credential a source needs is referenced by
environment-variable name inside ``DataSource.config["auth"]["env_ref"]`` and
resolved from the backend environment at request time.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Text, Integer, DateTime, JSON, Boolean, ForeignKey
from sqlalchemy.orm import relationship

from app.core.database import Base
from app.models.base_mixins import GUID, TimestampMixin


class DataSource(Base, TimestampMixin):
    __tablename__ = "data_sources"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    source_id = Column(String(100), unique=True, index=True, nullable=False)
    name = Column(String(255), nullable=False)
    base_url = Column(Text(), nullable=True)
    # rss | json_api | html_listing | playwright_html
    source_type = Column(String(50), nullable=False)
    adapter_key = Column(String(100), nullable=False)
    enabled = Column(Boolean, default=True, nullable=False)
    # Per-source collection interval (minutes). Clamped to safe limits by the
    # service layer before scheduling (min 5, max 10080).
    collection_interval_minutes = Column(Integer, default=60, nullable=False)
    # Adapter-specific configuration (JSON). May reference credentials by
    # environment-variable name only; never contains secret values.
    config = Column(JSON, nullable=True)
    notes = Column(Text(), nullable=True)

    # Live run state ------------------------------------------------
    # IDLE | RUNNING | SUCCESS | ERROR | CONFIG_ERROR | NEEDS_ATTENTION
    status = Column(String(50), default="IDLE", nullable=False)
    last_attempt_at = Column(DateTime(timezone=True), nullable=True)
    last_success_at = Column(DateTime(timezone=True), nullable=True)
    # Safe last-error detail (trimmed, secrets masked, no raw payloads).
    last_error = Column(Text(), nullable=True)

    # Last-run counters ----------------------------------------------
    last_discovered = Column(Integer, default=0, nullable=False)
    last_validated = Column(Integer, default=0, nullable=False)
    last_rejected = Column(Integer, default=0, nullable=False)
    last_inserted = Column(Integer, default=0, nullable=False)
    last_updated = Column(Integer, default=0, nullable=False)
    last_duplicates = Column(Integer, default=0, nullable=False)

    # Lifetime counters -----------------------------------------------
    total_runs = Column(Integer, default=0, nullable=False)
    total_inserted = Column(Integer, default=0, nullable=False)
    total_updated = Column(Integer, default=0, nullable=False)
    total_duplicates = Column(Integer, default=0, nullable=False)
    total_rejected = Column(Integer, default=0, nullable=False)

    runs = relationship(
        "SourceRun",
        back_populates="source",
        cascade="all, delete-orphan",
        order_by="SourceRun.started_at",
    )

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"<DataSource {self.source_id} enabled={self.enabled} status={self.status}>"


class SourceRun(Base):
    __tablename__ = "source_runs"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    source_id = Column(GUID(), ForeignKey("data_sources.id", ondelete="CASCADE"), nullable=False)
    trigger = Column(String(20), default="manual", nullable=False)  # manual | scheduler
    started_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    finished_at = Column(DateTime(timezone=True), nullable=True)
    # RUNNING | SUCCESS | PARTIAL | FAILED | SKIPPED | BUSY | BLOCKED | NO_RECORDS | ERROR
    status = Column(String(50), default="RUNNING", nullable=False)
    pages_visited = Column(Integer, default=0, nullable=False)
    records_discovered = Column(Integer, default=0, nullable=False)
    validated = Column(Integer, default=0, nullable=False)
    rejected = Column(Integer, default=0, nullable=False)
    inserted = Column(Integer, default=0, nullable=False)
    updated = Column(Integer, default=0, nullable=False)
    duplicates = Column(Integer, default=0, nullable=False)
    # Safe per-run detail errors (cap of {field, message}, trimmed + masked).
    errors = Column(JSON, nullable=True)
    notes = Column(Text(), nullable=True)

    source = relationship("DataSource", back_populates="runs")