"""
Organization membership router: add and list organization members.
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.core.auth import get_current_membership, require_role
from app.core.rate_limit import rate_limit_org_write
from app.db.session import get_db
from app.models.membership import Membership, MembershipRole
from app.models.user import User
from app.schemas.member import AddMemberRequest, MemberResponse
from app.services import audit_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/orgs", tags=["Organization Members"])


@router.post(
    "/{org_id}/members",
    response_model=MemberResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add a member to an organization",
)
def add_member(
    org_id: uuid.UUID,
    payload: AddMemberRequest,
    request: Request,
    current_membership: Membership = Depends(require_role(MembershipRole.OWNER)),
    _: Membership = Depends(rate_limit_org_write),
    db: Session = Depends(get_db),
) -> MemberResponse:
    """
    Add an existing user to the organization with a specified role.
    Only organization owners may add members.

    Returns:
        HTTP 201: Member created successfully.
        HTTP 401: Unauthenticated request.
        HTTP 403: Requester lacks the owner role.
        HTTP 404: Requester not a member of the organization, or target user not found.
        HTTP 409: Target user is already a member of the organization.
        HTTP 422: Invalid role or malformed email.
    """
    target_user = db.scalar(
        select(User).where(User.email == payload.email.strip().lower())
    )
    if target_user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found.",
        )

    # Check for existing membership in this organization
    existing_membership = db.scalar(
        select(Membership).where(
            Membership.organization_id == org_id,
            Membership.user_id == target_user.id,
        )
    )
    if existing_membership is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="User is already a member of this organization.",
        )

    new_membership = Membership(
        organization_id=org_id,
        user_id=target_user.id,
        role=payload.role,
    )
    db.add(new_membership)
    audit_service.record_audit_event(
        db,
        organization_id=org_id,
        user_id=current_membership.user_id,
        action="member.added",
        resource_type="membership",
        resource_id=str(target_user.id),
        details={"target_email": target_user.email, "role": payload.role},
        ip_address=request.client.host if request and request.client else None,
    )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="User is already a member of this organization.",
        )

    db.refresh(new_membership)
    new_membership.user = target_user

    return MemberResponse.model_validate(new_membership)


@router.get(
    "/{org_id}/members",
    response_model=list[MemberResponse],
    summary="List organization members",
)
def list_members(
    org_id: uuid.UUID,
    current_membership: Membership = Depends(get_current_membership),
    db: Session = Depends(get_db),
) -> list[MemberResponse]:
    """
    List all members in the organization.
    Any active member of the organization (owner, member, viewer) may list members.

    Returns:
        HTTP 200: List of members with user profiles and roles.
        HTTP 401: Unauthenticated request.
        HTTP 404: Requester is not a member of the organization.
    """
    memberships = db.scalars(
        select(Membership)
        .where(Membership.organization_id == org_id)
        .options(joinedload(Membership.user))
        .order_by(Membership.created_at.asc())
    ).all()

    return [MemberResponse.model_validate(m) for m in memberships]
