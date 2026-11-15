"""
Authentication endpoints.

POST   /api/v1/auth/login        -> access + refresh token pair
POST   /api/v1/auth/logout       -> revoke access + refresh tokens
GET    /api/v1/auth/me           -> current user profile
POST   /api/v1/auth/refresh      -> new access token from refresh token

All responses follow a consistent error format:
  401  {"detail": "Authentication required.", ...}
  403  {"detail": "Administrator role required.", ...}
  422  validation error (Pydantic)

No passwords are ever returned or logged. Login failures are tracked for
brute-force protection and account lockout.
"""

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from app.core.auth import (
    authenticate_user,
    decode_token,
    hash_password_wrapper,
    is_token_revoked,
    revoke_token,
)
from app.core.config import settings
from app.core.database import execute_with_retry, get_db
from app.api.v1.dependencies import (
    get_current_user_optional,
    issue_tokens,
    require_admin,
    require_auth,
)
from app.models.token import LoginAttempt, RevokedToken
from app.models.user import User

router = APIRouter(prefix="/auth", tags=["Authentication"])


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8)


class LoginResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    user: dict


class LogoutRequest(BaseModel):
    refresh_token: Optional[str] = None


class LogoutResponse(BaseModel):
    detail: str


class RefreshRequest(BaseModel):
    refresh_token: str


class RefreshResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class UserResponse(BaseModel):
    id: str
    email: str
    name: str
    role: str
    active: bool


class UserCreateRequest(BaseModel):
    email: EmailStr
    name: str = Field(..., min_length=1, max_length=255)
    password: str = Field(..., min_length=8)
    role: str = Field(default="viewer", pattern="^(admin|operator|viewer)$")
    active: bool = True


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _client_ip(request: Request) -> Optional[str]:
    """Best-effort client IP from the request."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


def _record_attempt(
    db: Session,
    email: str,
    request: Request,
    success: bool,
    user: Optional[User] = None,
) -> None:
    """Persist a login attempt for brute-force auditing.

    The commit is retried via ``execute_with_retry`` so that transient SQLite
    write-lock contention (e.g. from a concurrent scheduled collection) does
    not cause the login request to block for the full busy timeout.
    """
    db.add(
        LoginAttempt(
            email=email,
            ip_address=_client_ip(request),
            user_agent=request.headers.get("user-agent"),
            success=success,
        )
    )
    execute_with_retry(db.commit)


def _get_token_expiry(token: str) -> Optional[datetime]:
    """Extract the expiry from a token without full validation (best effort)."""
    try:
        from app.core.auth import decode_token

        payload = decode_token(token)
        exp = payload.get("exp")
        if exp:
            return datetime.fromtimestamp(exp, tz=timezone.utc)
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/login", response_model=LoginResponse)
def login(
    request: Request,
    credentials: LoginRequest,
    db: Session = Depends(get_db),
):
    """Authenticate with email + password and receive a token pair.

    Brute-force protection:
    - Accounts are locked after ``LOGIN_MAX_ATTEMPTS`` consecutive failures.
    - Failed attempts are recorded per email/IP.
    - The response does not reveal whether the email exists.
    """
    email = credentials.email.lower()

    # Reject locked accounts immediately (constant-ish failure path).
    user = db.query(User).filter(User.email == email).first()
    if user is not None and user.is_locked():
        _record_attempt(db, email, request, False)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Account temporarily locked due to failed login attempts. Try again later.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Authenticate. Always runs verify_password even for unknown users to
    # mitigate user-enumeration timing attacks.
    authenticated = authenticate_user(db, email, credentials.password)

    if authenticated is None:
        _record_attempt(db, email, request, False)
        if user is not None:
            just_locked = user.record_failed_attempt(
                settings.LOGIN_MAX_ATTEMPTS, settings.LOGIN_LOCKOUT_MINUTES
            )
            db.add(user)
            execute_with_retry(db.commit)
            if just_locked:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Account locked due to repeated failed login attempts.",
                    headers={"WWW-Authenticate": "Bearer"},
                )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Successful login: reset failure counter and issue tokens.
    authenticated.record_success()
    db.add(authenticated)
    execute_with_retry(db.commit)
    _record_attempt(db, email, request, True, user=authenticated)

    tokens = issue_tokens(authenticated)
    return LoginResponse(**tokens)


@router.post("/logout", response_model=LogoutResponse)
def logout(
    request: Request,
    logout_request: LogoutRequest,
    current_user: Optional[User] = Depends(get_current_user_optional),
    db: Session = Depends(get_db),
):
    """Revoke the current access token and an optional refresh token.

    The access token's JTI is extracted from the ``Authorization: Bearer``
    header and added to the revoked_tokens table. If a refresh token is
    supplied in the body it is revoked as well. Access tokens are short-lived
    (default 30 minutes) so they self-expire quickly, but revocation makes
    logout effective immediately.
    """
    from app.core.auth import decode_token

    # Revoke the access token from the Authorization header.
    auth_header = request.headers.get("authorization", "")
    if auth_header.lower().startswith("bearer "):
        access_token = auth_header[7:].strip()
        try:
            payload = decode_token(access_token)
            if payload.get("type") == "access":
                jti = payload.get("jti")
                exp = payload.get("exp")
                if jti and exp:
                    revoke_token(
                        db,
                        jti,
                        str(current_user.id)
                        if current_user
                        else str(payload.get("sub", "")),
                        datetime.fromtimestamp(exp, tz=timezone.utc),
                    )
        except Exception:
            # Malformed or expired access token: nothing to revoke.
            pass

    # Revoke the refresh token if explicitly supplied.
    if logout_request.refresh_token:
        try:
            payload = decode_token(logout_request.refresh_token)
            if payload.get("type") == "refresh":
                jti = payload.get("jti")
                exp = payload.get("exp")
                if jti and exp:
                    revoke_token(
                        db,
                        jti,
                        str(current_user.id)
                        if current_user
                        else str(payload.get("sub", "")),
                        datetime.fromtimestamp(exp, tz=timezone.utc),
                    )
        except Exception:
            # Invalid refresh token: nothing to revoke.
            pass

    return LogoutResponse(detail="Logged out successfully.")


@router.get("/me", response_model=UserResponse)
def get_current_user(
    current_user: Optional[User] = Depends(get_current_user_optional),
):
    """Return the profile of the currently authenticated user.

    Returns 401 when no valid token is presented and AUTH_REQUIRED is True.
    """
    if current_user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return UserResponse(
        id=str(current_user.id),
        email=current_user.email,
        name=current_user.name,
        role=current_user.role,
        active=current_user.active,
    )


@router.post("/refresh", response_model=RefreshResponse)
def refresh_token(
    request: RefreshRequest,
    db: Session = Depends(get_db),
):
    """Exchange a valid refresh token for a new access token.

    The refresh token is validated for signature, expiry, type and
    revocation. On success a new access token is issued. The old refresh
    token is NOT automatically revoked (rotation can be enabled later).
    """
    try:
        payload = decode_token(request.refresh_token)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if payload.get("type") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token type.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    jti = payload.get("jti")
    if jti and is_token_revoked(db, jti):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token has been revoked.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = payload.get("sub")
    user = db.query(User).filter(User.id == user_id).first()
    if user is None or not user.active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or disabled.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    tokens = issue_tokens(user)
    return RefreshResponse(
        access_token=tokens["access_token"],
        expires_in=tokens["expires_in"],
    )


# ---------------------------------------------------------------------------
# User management (ADMIN only)
# ---------------------------------------------------------------------------


@router.post("/users", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def create_user(
    user_in: UserCreateRequest,
    admin_user: Optional[User] = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Create a new user account. Requires ADMIN role.

    Passwords are hashed with PBKDF2-HMAC-SHA256 before storage. No default
    or hardcoded credentials are ever created.
    """
    email = user_in.email.lower()
    existing = db.query(User).filter(User.email == email).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A user with this email already exists.",
        )

    user = User(
        email=email,
        name=user_in.name,
        password_hash=hash_password_wrapper(user_in.password),
        role=user_in.role,
        active=user_in.active,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return UserResponse(
        id=str(user.id),
        email=user.email,
        name=user.name,
        role=user.role,
        active=user.active,
    )


@router.get("/users", response_model=list[UserResponse])
def list_users(
    admin_user: Optional[User] = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """List all user accounts. Requires ADMIN role."""
    users = db.query(User).order_by(User.created_at.desc()).all()
    return [
        UserResponse(
            id=str(u.id),
            email=u.email,
            name=u.name,
            role=u.role,
            active=u.active,
        )
        for u in users
    ]


@router.get("/users/{user_id}", response_model=UserResponse)
def get_user(
    user_id: str,
    admin_user: Optional[User] = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Get a single user by ID. Requires ADMIN role."""
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found.",
        )
    return UserResponse(
        id=str(user.id),
        email=user.email,
        name=user.name,
        role=user.role,
        active=user.active,
    )


@router.patch("/users/{user_id}", response_model=UserResponse)
def update_user(
    user_id: str,
    user_in: UserCreateRequest,
    admin_user: Optional[User] = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Update a user's role/name/active status. Requires ADMIN role.

    Password changes are not supported here; use a dedicated password-change
    endpoint (future work).
    """
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found.",
        )
    user.name = user_in.name
    user.role = user_in.role
    user.active = user_in.active
    db.add(user)
    db.commit()
    db.refresh(user)
    return UserResponse(
        id=str(user.id),
        email=user.email,
        name=user.name,
        role=user.role,
        active=user.active,
    )


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(
    user_id: str,
    admin_user: Optional[User] = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Deactivate a user (soft delete via active flag). Requires ADMIN role.

    The account is marked inactive rather than hard-deleted so that audit
    records referencing it are preserved.
    """
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found.",
        )
    user.active = False
    # Revoke all known tokens so the user's sessions end immediately.
    from app.core.auth import revoke_all_user_tokens

    revoke_all_user_tokens(db, str(user.id))
    db.commit()
    return None
