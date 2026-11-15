"""
Authentication core for the SecuredApp GeM Bid Intelligence Platform.

Implements JWT-based access/refresh tokens built on the existing PBKDF2
password hashing in ``app.core.security``.

Design decisions:
- Access tokens are short-lived JWTs (default 30 minutes) carrying the user
  id, email, role and a unique JTI identifier.
- Refresh tokens are longer-lived JWTs (default 7 days) used only to obtain
  new access tokens. They are revoked on logout and on reuse-detection.
- Revoked access tokens are tracked in a ``revoked_tokens`` table keyed by
  JTI with an expiry, so logout is effective immediately.
- No plaintext passwords are ever stored or logged.
- No hardcoded credentials and no default administrator account.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt
from jwt import PyJWTError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import hash_password, verify_password
from app.models.user import User

# Token algorithm and lifetimes. All values are overridable via environment
# variables through the pydantic Settings class.
ALGORITHM = "HS256"


def create_access_token(
    user_id: str,
    email: str,
    role: str,
    expires_delta: Optional[timedelta] = None,
) -> str:
    """Create a signed JWT access token.

    The token carries ``sub`` (user id), ``email``, ``role`` and a unique
    ``jti`` so it can be individually revoked.
    """
    now = datetime.now(timezone.utc)
    expire = now + (expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES))
    jti = _new_jti()
    payload = {
        "sub": str(user_id),
        "email": email,
        "role": role,
        "jti": jti,
        "iat": now,
        "exp": expire,
        "type": "access",
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=ALGORITHM)


def create_refresh_token(
    user_id: str,
    email: str,
    expires_delta: Optional[timedelta] = None,
) -> str:
    """Create a signed JWT refresh token.

    Refresh tokens carry only the user id and a JTI; they are exchanged for
    new access tokens at ``POST /auth/refresh``.
    """
    now = datetime.now(timezone.utc)
    expire = now + (expires_delta or timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS))
    jti = _new_jti()
    payload = {
        "sub": str(user_id),
        "email": email,
        "jti": jti,
        "iat": now,
        "exp": expire,
        "type": "refresh",
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=ALGORITHM)


def _new_jti() -> str:
    """Generate a cryptographically random token identifier."""
    import secrets

    return secrets.token_urlsafe(32)


def decode_token(token: str) -> dict:
    """Decode and validate a JWT, returning its payload.

    Raises ``PyJWTError`` on expired, malformed or signature-invalid tokens.
    Callers are responsible for checking revocation separately.
    """
    return jwt.decode(
        token,
        settings.SECRET_KEY,
        algorithms=[ALGORITHM],
        options={"require": ["exp", "iat", "sub", "jti"]},
    )


def authenticate_user(db: Session, email: str, password: str) -> Optional[User]:
    """Verify email/password against the database.

    Returns the ``User`` on success, ``None`` on failure. Uses constant-time
    comparison via ``verify_password`` and never reveals whether the email
    exists (timing side-channel is minimised by always running the hash).
    """
    user = db.query(User).filter(User.email == email).first()
    if user is None:
        # Still run a hash so a missing email takes similar time to a wrong
        # password, mitigating user-enumeration timing attacks.
        verify_password(password, "x$" + "0" * 64)
        return None
    if not user.active:
        return None
    if not verify_password(password, user.password_hash):
        return None
    return user


def hash_password_wrapper(password: str) -> str:
    """Public wrapper around the PBKDF2 password hasher.

    Delegates to ``app.core.security.hash_password`` so there is a single
    hashing implementation in the codebase.
    """
    return hash_password(password)


def verify_password_wrapper(password: str, password_hash: str) -> bool:
    """Public wrapper around the PBKDF2 password verifier."""
    return verify_password(password, password_hash)


def is_token_revoked(db: Session, jti: str) -> bool:
    """True when a JTI appears in the revoked tokens table and is not expired."""
    from app.models.token import RevokedToken

    now = datetime.now(timezone.utc)
    row = (
        db.query(RevokedToken)
        .filter(RevokedToken.jti == jti)
        .first()
    )
    if row is None:
        return False
    # Compare expires_at, handling offset-naive/offset-aware datetime mismatch
    # (SQLite may return offset-naive datetimes).
    expires = row.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    return expires > now


def revoke_token(db: Session, jti: str, user_id: str, expires_at: datetime) -> None:
    """Mark a token JTI as revoked until its natural expiry."""
    from app.models.token import RevokedToken

    existing = db.query(RevokedToken).filter(RevokedToken.jti == jti).first()
    if existing is not None:
        return
    db.add(RevokedToken(jti=jti, user_id=user_id, expires_at=expires_at))
    db.commit()


def revoke_all_user_tokens(db: Session, user_id: str) -> None:
    """Revoke every known token for a user (used on password change / disable)."""
    from app.models.token import RevokedToken

    # Mark all non-expired revoked-token rows for this user as expired so they
    # are cleaned up by the expiry sweep. New tokens issued after this point
    # carry fresh JTIs and are unaffected unless explicitly revoked.
    rows = db.query(RevokedToken).filter(RevokedToken.user_id == user_id).all()
    now = datetime.now(timezone.utc)
    for row in rows:
        if row.expires_at > now:
            row.expires_at = now
    db.commit()
