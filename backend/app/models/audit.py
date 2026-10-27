import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, DateTime, JSON
from app.core.database import Base
from app.models.base_mixins import GUID


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    entity_type = Column(String(100), nullable=False)
    entity_id = Column(GUID(), nullable=True)
    action = Column(String(100), nullable=False)
    actor = Column(String(255), nullable=False)
    metadata_info = Column("metadata", JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
