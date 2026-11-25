"""
Authentication router: registration and login.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.auth import (
    create_access_token,
    get_password_hash,
    verify_password,
)
from app.core.logging import set_org_id, set_user_id
from app.core.rate_limit import (
    _raise_429,
    check_fixed_window_rate_limit,
    rate_limit_auth,
)
from app.config import settings
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
from app.services import audit_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post(
    "/register",
    response_model=RegisterResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit_auth)],
    summary="Register a new user and organization",
)
def register(
    payload: RegisterRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> RegisterResponse:
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
    audit_service.record_audit_event(
        db,
        organization_id=org.id,
        user_id=user.id,
        action="auth.register",
        resource_type="organization",
        resource_id=str(org.id),
        details={"email": user.email, "organization_name": org.name},
        ip_address=request.client.host if request and request.client else None,
    )

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

    if request is not None:
        request.state.user_id = str(user.id)
        request.state.org_id = str(org.id)
    set_user_id(str(user.id))
    set_org_id(str(org.id))

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
    dependencies=[Depends(rate_limit_auth)],
    summary="Authenticate and receive a JWT",
)
def login(
    payload: LoginRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> TokenResponse:
    """
    Verify credentials and return a signed HS256 JWT (1-hour expiry).

    Enforces both IP-level and normalized-email brute-force rate limits,
    uses constant-time Argon2id verification to prevent user enumeration, and
    records login success/failure in AuditLog.
    """
    normalized_email = payload.email.strip().lower()
    email_allowed, _, retry_after = check_fixed_window_rate_limit(
        scope="auth_email",
        identifier=normalized_email,
        limit=settings.rate_limit_auth_max_requests,
        window_seconds=settings.rate_limit_window_seconds,
    )
    if not email_allowed:
        _raise_429(
            detail="Too many authentication attempts for this account. Please retry later.",
            retry_after=retry_after,
            limit=settings.rate_limit_auth_max_requests,
        )

    user = db.scalar(select(User).where(User.email == normalized_email))

    # Always run verify_password to prevent user-enumeration via timing.
    _dummy_hash = "$argon2id$v=19$m=65536,t=3,p=4$dummysaltvalue$dummyhashvalue"
    password_ok = verify_password(
        payload.password,
        user.password_hash if user is not None else _dummy_hash,
    )

    if user is None or not password_ok:
        audit_service.record_audit_event(
            db,
            organization_id=None,
            user_id=user.id if user is not None else None,
            action="auth.login_failed",
            resource_type="user",
            resource_id=str(user.id) if user is not None else None,
            details={"email": normalized_email},
            ip_address=request.client.host if request and request.client else None,
            commit=True,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email address or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = create_access_token(user.id)
    audit_service.record_audit_event(
        db,
        organization_id=None,
        user_id=user.id,
        action="auth.login",
        resource_type="user",
        resource_id=str(user.id),
        details={"email": user.email},
        ip_address=request.client.host if request and request.client else None,
        commit=True,
    )
    if request is not None:
        request.state.user_id = str(user.id)
    set_user_id(str(user.id))
    return TokenResponse(access_token=token)

