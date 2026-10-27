import uuid
from sqlalchemy import Column, String, Boolean
from app.core.database import Base
from app.models.base_mixins import GUID, TimestampMixin


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    email = Column(String(255), unique=True, index=True, nullable=False)
    name = Column(String(255), nullable=False)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(50), default="reviewer", nullable=False)  # admin, reviewer, viewer
    active = Column(Boolean(), default=True, nullable=False)
