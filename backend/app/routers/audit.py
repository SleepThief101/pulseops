from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.auth import require_role
from app.db.session import get_db
from app.models.membership import Membership, MembershipRole
from app.schemas.audit import AuditLogResponse
from app.services import audit_service

router = APIRouter(prefix="/orgs", tags=["Audit Logs"])


@router.get(
    "/{org_id}/audit-logs",
    response_model=list[AuditLogResponse],
    summary="List security and mutation audit logs for an organization",
)
def list_org_audit_logs(
    org_id: uuid.UUID,
    action: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    _: Membership = Depends(require_role(MembershipRole.OWNER)),
    db: Session = Depends(get_db),
) -> list[AuditLogResponse]:
    """
    List immutable AuditLog entries scoped to ``org_id``.
    Strictly requires the ``owner`` role (member and viewer receive HTTP 403;
    non-members receive HTTP 404).
    """
    entries = audit_service.list_audit_logs(
        db,
        organization_id=org_id,
        action=action,
        limit=limit,
        offset=offset,
    )
    return [AuditLogResponse.model_validate(entry) for entry in entries]
