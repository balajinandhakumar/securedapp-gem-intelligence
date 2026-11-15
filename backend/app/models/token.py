"""
Token revocation and login-attempt tracking models.

These tables support secure logout (token revocation) and brute-force
protection (failed login attempt tracking with account lockout).
"""

import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, DateTime, ForeignKey, Integer, Index, Boolean, Text
from sqlalchemy.orm import relationship

from app.core.database import Base
from app.models.base_mixins import GUID, TimestampMixin


class RevokedToken(Base, TimestampMixin):
    """A JWT JTI that has been revoked before its natural expiry.

    Access and refresh tokens are identified by their ``jti`` claim. On
    logout the JTI is inserted here with the token's original expiry so it
    can no longer be used. Rows are considered inactive once ``expires_at``
    has passed and can be swept by a maintenance job.
    """

    __tablename__ = "revoked_tokens"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    jti = Column(String(255), unique=True, index=True, nullable=False)
    user_id = Column(GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    revoked_at = Column(DateTime(timezone=True), default=datetime.now(timezone.utc), nullable=False)

    user = relationship("User", backref="revoked_tokens")

    __table_args__ = (
        Index("ix_revoked_tokens_user_expires", "user_id", "expires_at"),
    )


class LoginAttempt(Base, TimestampMixin):
    """Record of a login attempt for brute-force detection.

    One row per attempt (successful or failed), keyed by email and IP.
    Used to lock accounts after ``LOGIN_MAX_ATTEMPTS`` consecutive failures
    within ``LOGIN_LOCKOUT_MINUTES``.
    """

    __tablename__ = "login_attempts"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    email = Column(String(255), index=True, nullable=False)
    ip_address = Column(String(64), nullable=True)
    user_agent = Column(Text, nullable=True)
    success = Column(Boolean(), default=False, nullable=False)
    attempted_at = Column(DateTime(timezone=True), default=datetime.now(timezone.utc), nullable=False)

    __table_args__ = (
        Index("ix_login_attempts_email_attempted", "email", "attempted_at"),
        Index("ix_login_attempts_ip_attempted", "ip_address", "attempted_at"),
    )
