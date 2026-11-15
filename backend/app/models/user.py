import uuid
from datetime import datetime, timedelta, timezone
from sqlalchemy import Column, String, Boolean, DateTime, Integer
from app.core.database import Base
from app.models.base_mixins import GUID, TimestampMixin


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    email = Column(String(255), unique=True, index=True, nullable=False)
    name = Column(String(255), nullable=False)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(50), default="reviewer", nullable=False)  # admin, operator, viewer
    active = Column(Boolean(), default=True, nullable=False)
    # Brute-force protection: consecutive failed login attempts and lockout.
    failed_login_attempts = Column(Integer, default=0, nullable=False)
    locked_until = Column(DateTime(timezone=True), nullable=True)

    def is_locked(self) -> bool:
        """True when the account is currently locked due to failed logins."""
        if self.locked_until is None:
            return False
        locked = self.locked_until
        # SQLite may return offset-naive datetimes; normalize to aware.
        if locked.tzinfo is None:
            locked = locked.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) < locked

    def record_failed_attempt(
        self, max_attempts: int, lockout_minutes: int
    ) -> bool:
        """Increment failed-attempt counter; lock if threshold reached.

        Returns True when the account was just locked.
        """
        self.failed_login_attempts += 1
        just_locked = False
        if self.failed_login_attempts >= max_attempts:
            self.locked_until = datetime.now(timezone.utc) + timedelta(minutes=lockout_minutes)
            just_locked = True
        return just_locked

    def record_success(self) -> None:
        """Reset failed-attempt counter and clear lockout on successful login."""
        self.failed_login_attempts = 0
        self.locked_until = None
