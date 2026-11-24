"""
Authentication utilities for PulseOps.

Provides:
- Argon2id password hashing via pwdlib
- JWT creation and verification via PyJWT (HS256, 1-hour expiry)
- FastAPI dependency for extracting the authenticated user
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pwdlib import PasswordHash
from pwdlib.hashers.argon2 import Argon2Hasher
from sqlalchemy.orm import Session

from app.db.session import get_db

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Password hashing
# ---------------------------------------------------------------------------

_password_hash = PasswordHash((Argon2Hasher(),))

JWT_ALGORITHM = "HS256"
JWT_EXPIRY_SECONDS = 3600  # 1 hour


class _BearerScheme(HTTPBearer):
    """HTTPBearer that returns 401 (not 403) when Authorization header is absent."""

    async def __call__(self, request: Request) -> HTTPAuthorizationCredentials | None:
        try:
            return await super().__call__(request)
        except HTTPException as exc:
            if exc.status_code == status.HTTP_403_FORBIDDEN:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Authentication required.",
                    headers={"WWW-Authenticate": "Bearer"},
                ) from exc
            raise


_bearer_scheme = _BearerScheme(auto_error=True)


def get_jwt_secret() -> str:
    """
    Return the JWT secret key from application settings.

    Fails closed: raises RuntimeError if the key is missing or empty.
    Never falls back to any default value.
    """
    # Import here to avoid circular imports during module initialisation.
    from app.config import settings  # noqa: PLC0415

    key = settings.jwt_secret_key
    if not key or not key.strip():
        raise RuntimeError(
            "JWT_SECRET_KEY is not configured. "
            "Set a strong random secret in the JWT_SECRET_KEY environment variable."
        )
    return key.strip()


def get_password_hash(password: str) -> str:
    """Hash a plain-text password using Argon2id."""
    return _password_hash.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plain-text password against an Argon2id hash."""
    try:
        return _password_hash.verify(plain_password, hashed_password)
    except Exception:
        # Any error from the hasher means verification failed.
        return False


# ---------------------------------------------------------------------------
# JWT
# ---------------------------------------------------------------------------


def create_access_token(user_id: uuid.UUID) -> str:
    """
    Create a signed HS256 JWT for the given user.

    Claims:
        sub  — user UUID (string)
        iat  — issued-at (UTC)
        exp  — expiry (iat + 1 hour)
    """
    now = datetime.now(tz=timezone.utc)
    payload = {
        "sub": str(user_id),
        "iat": now,
        "exp": now + timedelta(seconds=JWT_EXPIRY_SECONDS),
    }
    return jwt.encode(payload, get_jwt_secret(), algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> uuid.UUID:
    """
    Decode and validate a JWT, returning the user UUID from the ``sub`` claim.

    Raises:
        HTTPException 401 — on any validation failure.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired authentication token.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, get_jwt_secret(), algorithms=[JWT_ALGORITHM])
        sub: str | None = payload.get("sub")
        if not sub:
            raise credentials_exception
        return uuid.UUID(sub)
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError, ValueError):
        raise credentials_exception


# ---------------------------------------------------------------------------
# FastAPI dependency
# ---------------------------------------------------------------------------


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer_scheme),
    db: Session = Depends(get_db),
) -> "User":  # type: ignore[name-defined]  # noqa: F821
    """
    FastAPI dependency: extract bearer token, validate it, and return the User.

    Raises 401 for invalid/expired tokens; 404 if the user no longer exists.
    """
    from app.models.user import User  # noqa: PLC0415

    user_id = decode_access_token(credentials.credentials)
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found.",
        )
    return user
