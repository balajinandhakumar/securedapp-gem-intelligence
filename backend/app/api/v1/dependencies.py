"""
Authentication and authorization dependencies for FastAPI.

Provides:
- ``get_current_user_optional``: resolves a user from a bearer token, or
  returns None when no token is supplied (used by endpoints that work with
  or without auth).
- ``require_auth``: requires a valid, non-revoked token (401 otherwise).
- ``require_admin`` / ``require_operator`` / ``require_viewer``: role-based
  authorization (403 when the caller's role is insufficient).

Role hierarchy (ADMIN > OPERATOR > VIEWER):
- ADMIN: user management, configuration, source management, all operations.
- OPERATOR: collection, matching, product/source writes, read everything.
- VIEWER: read-only access to dashboard, bids, products.

Consistent error responses:
- 401: missing, expired, revoked or malformed token (when AUTH_REQUIRED).
- 403: authenticated but insufficient role for the requested action.

Backward compatibility: when ``settings.AUTH_REQUIRED`` is False (the
development default), ``require_auth`` is a pass-through so existing
unauthenticated callers keep working. Production deployments MUST set
AUTH_REQUIRED=True.
"""

from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.core.auth import (
    decode_token,
    is_token_revoked,
)
from app.core.config import settings
from app.core.database import get_db
from app.models.user import User

# Bearer token scheme. Clients send ``Authorization: Bearer <access_token>``.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)


def get_current_user_optional(
    token: Optional[str] = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> Optional[User]:
    """Resolve the current user from a bearer token without requiring one.

    Returns the ``User`` when a valid, non-revoked access token is presented,
    otherwise ``None``. Never raises; callers that need authentication should
    use ``require_auth`` instead.

    The database session is injected by FastAPI (via ``Depends(get_db)``),
    which means test overrides of ``get_db`` are respected.
    """
    if token is None:
        return None
    try:
        payload = decode_token(token)
    except Exception:
        return None

    # Enforce token type and reject revoked tokens.
    if payload.get("type") != "access":
        return None
    jti = payload.get("jti")
    if jti is None:
        return None

    if is_token_revoked(db, jti):
        return None
    user_id = payload.get("sub")
    user = db.query(User).filter(User.id == user_id).first()
    if user is None or not user.active:
        return None
    return user


def require_auth(
    current_user: Optional[User] = Depends(get_current_user_optional),
) -> Optional[User]:
    """Require an authenticated user.

    When ``settings.AUTH_REQUIRED`` is False (development default), this is a
    pass-through that allows unauthenticated callers so existing integrations
    keep working. Production deployments MUST set AUTH_REQUIRED=True, at which
    point unauthenticated requests receive 401.
    """
    if settings.AUTH_REQUIRED and current_user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return current_user  # may be None in dev mode


def require_admin(
    current_user: Optional[User] = Depends(require_auth),
) -> Optional[User]:
    """Require the ADMIN role (403 for OPERATOR/VIEWER when auth enforced).

    In dev mode (AUTH_REQUIRED=False) this is a pass-through.
    """
    if settings.AUTH_REQUIRED:
        if current_user is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        if current_user.role != "admin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Administrator role required.",
            )
    return current_user


def require_operator(
    current_user: Optional[User] = Depends(require_auth),
) -> Optional[User]:
    """Require OPERATOR or ADMIN (403 for VIEWER when auth enforced).

    In dev mode (AUTH_REQUIRED=False) this is a pass-through.
    """
    if settings.AUTH_REQUIRED:
        if current_user is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        if current_user.role not in ("admin", "operator"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Operator or administrator role required.",
            )
    return current_user


def require_viewer(
    current_user: Optional[User] = Depends(require_auth),
) -> Optional[User]:
    """Require any authenticated role when auth enforced.

    In dev mode (AUTH_REQUIRED=False) this is a pass-through.
    """
    if settings.AUTH_REQUIRED and current_user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return current_user


# ---------------------------------------------------------------------------
# Token creation helpers (used by auth endpoints)
# ---------------------------------------------------------------------------

from app.core.auth import create_access_token, create_refresh_token  # noqa: E402


def issue_tokens(user: User) -> dict:
    """Issue a fresh access + refresh token pair for a user.

    Revocation is handled lazily via the revoked_tokens table at validation
    time; nothing is written to the database here.
    """
    access_token = create_access_token(
        user_id=str(user.id),
        email=user.email,
        role=user.role,
    )
    refresh_token = create_refresh_token(
        user_id=str(user.id),
        email=user.email,
    )
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "expires_in": settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        "user": {
            "id": str(user.id),
            "email": user.email,
            "name": user.name,
            "role": user.role,
            "active": user.active,
        },
    }
