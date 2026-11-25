"""
GET /me and GET /me/organizations — authenticated user profile endpoints.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.core.auth import get_current_user
from app.db.session import get_db
from app.models.membership import Membership
from app.models.user import User
from app.schemas.api_key import (
    ApiKeyCreateRequest,
    ApiKeyCreatedResponse,
    ApiKeyResponse,
)
from app.schemas.auth import UserOrganizationSummary, UserProfile
from app.services import api_key_service

me_router = APIRouter(tags=["Profile"])


@me_router.get(
    "/me",
    response_model=UserProfile,
    summary="Return the authenticated user's profile",
)
def me(current_user: User = Depends(get_current_user)) -> UserProfile:
    """
    Return the profile of the currently authenticated user.

    Requires a valid Bearer JWT in the Authorization header.
    Password hash is never included in the response.
    """
    return UserProfile.model_validate(current_user)


@me_router.get(
    "/me/organizations",
    response_model=list[UserOrganizationSummary],
    summary="List organizations the authenticated user belongs to",
)
def list_my_organizations(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[UserOrganizationSummary]:
    """Return organizations and roles strictly scoped to ``current_user``."""
    memberships = list(
        db.scalars(
            select(Membership)
            .options(joinedload(Membership.organization))
            .where(Membership.user_id == current_user.id)
            .order_by(Membership.created_at.asc())
        ).all()
    )
    return [
        UserOrganizationSummary(
            organization_id=m.organization_id,
            organization_name=m.organization.name,
            role=m.role,
            created_at=m.organization.created_at,
        )
        for m in memberships
    ]


@me_router.post(
    "/me/api-keys",
    response_model=ApiKeyCreatedResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new per-user MCP API key",
)
def create_my_api_key(
    payload: ApiKeyCreateRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ApiKeyCreatedResponse:
    """
    Issue a new per-user MCP API key. The plaintext key is returned ONCE in
    this response and is never stored or retrievable again.
    """
    record, raw_key = api_key_service.create_api_key(
        db,
        user_id=current_user.id,
        name=payload.name,
        expires_in_days=payload.expires_in_days,
        ip_address=request.client.host if request.client else None,
    )
    return ApiKeyCreatedResponse(
        id=record.id,
        user_id=record.user_id,
        name=record.name,
        key_prefix=record.key_prefix,
        last_used_at=record.last_used_at,
        revoked_at=record.revoked_at,
        expires_at=record.expires_at,
        created_at=record.created_at,
        api_key=raw_key,
    )


@me_router.get(
    "/me/api-keys",
    response_model=list[ApiKeyResponse],
    summary="List the authenticated user's MCP API keys",
)
def list_my_api_keys(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[ApiKeyResponse]:
    """List API key metadata strictly scoped to ``current_user``."""
    keys = api_key_service.list_api_keys(db, user_id=current_user.id)
    return [ApiKeyResponse.model_validate(k) for k in keys]


@me_router.delete(
    "/me/api-keys/{key_id}",
    response_model=ApiKeyResponse,
    summary="Revoke one of the authenticated user's MCP API keys",
)
def revoke_my_api_key(
    key_id: uuid.UUID,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ApiKeyResponse:
    """
    Revoke an API key belonging to ``current_user``. Returns 404 if the key
    does not exist or belongs to another user.
    """
    revoked = api_key_service.revoke_api_key(
        db,
        user_id=current_user.id,
        key_id=key_id,
        ip_address=request.client.host if request.client else None,
    )
    if revoked is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="API key not found.",
        )
    return ApiKeyResponse.model_validate(revoked)
