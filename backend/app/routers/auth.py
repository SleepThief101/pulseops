"""
Authentication router: registration and login.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.auth import (
    create_access_token,
    get_password_hash,
    verify_password,
)
from app.db.session import get_db
from app.models.membership import Membership, MembershipRole
from app.models.organization import Organization
from app.models.user import User
from app.schemas.auth import (
    LoginRequest,
    RegisterRequest,
    RegisterResponse,
    TokenResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post(
    "/register",
    response_model=RegisterResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user and organization",
)
def register(payload: RegisterRequest, db: Session = Depends(get_db)) -> RegisterResponse:
    """
    Create a new User, a new Organization, and an owner Membership in a single
    atomic transaction.

    Returns HTTP 409 if the email address is already registered.
    """
    # Check for existing email before attempting the insert so we can return a
    # clear 409 rather than leaking internal IntegrityError details.
    existing = db.scalar(select(User).where(User.email == payload.email.strip().lower()))
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A user with that email address already exists.",
        )

    hashed = get_password_hash(payload.password)

    org = Organization(name=payload.organization_name.strip())
    user = User(email=payload.email, password_hash=hashed)
    db.add(org)
    db.add(user)
    db.flush()  # populate PKs before creating the Membership FK

    membership = Membership(
        user_id=user.id,
        organization_id=org.id,
        role=MembershipRole.OWNER.value,
    )
    db.add(membership)

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A user with that email address already exists.",
        )

    db.refresh(user)
    db.refresh(org)

    return RegisterResponse(
        user_id=user.id,
        email=user.email,
        created_at=user.created_at,
        organization_id=org.id,
        organization_name=org.name,
        role=MembershipRole.OWNER.value,
    )


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Authenticate and receive a JWT",
)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    """
    Verify credentials and return a signed HS256 JWT (1-hour expiry).

    Returns HTTP 401 for invalid email or incorrect password.
    Uses a constant-time comparison (Argon2id verify) to prevent timing attacks.
    """
    user = db.scalar(select(User).where(User.email == payload.email.strip().lower()))

    # Always run verify_password to prevent user-enumeration via timing.
    _dummy_hash = "$argon2id$v=19$m=65536,t=3,p=4$dummysaltvalue$dummyhashvalue"
    password_ok = verify_password(
        payload.password,
        user.password_hash if user is not None else _dummy_hash,
    )

    if user is None or not password_ok:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email address or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = create_access_token(user.id)
    return TokenResponse(access_token=token)

