from __future__ import annotations

from typing import Any
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from app.connectors import (
    ConnectorAuthError,
    ConnectorError,
    ConnectorNotFoundError,
    CsvConnector,
)
from app.core.auth import get_current_membership, require_role
from app.core.rate_limit import rate_limit_org_write
from app.db.session import get_db
from app.models.membership import Membership, MembershipRole
from app.schemas.event import EventIngestResult
from app.schemas.integration import (
    GitHubOAuthCallbackRequest,
    GitHubOAuthUrlResponse,
    IntegrationCreateRequest,
    IntegrationResponse,
    IntegrationSyncResponse,
)
from app.services import audit_service, integration_service
from app.services.event_service import ingest_events
from app.worker import enqueue_sync_job

router = APIRouter(prefix="/orgs", tags=["Integrations & Imports"])


@router.post(
    "/{org_id}/integrations",
    response_model=IntegrationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Connect an external integration",
)
def connect_integration(
    org_id: uuid.UUID,
    payload: IntegrationCreateRequest,
    request: Request,
    membership: Membership = Depends(require_role(MembershipRole.OWNER)),
    _: Membership = Depends(rate_limit_org_write),
    db: Session = Depends(get_db),
) -> IntegrationResponse:
    """
    Validate and store encrypted integration credentials for an organization.
    Owner role required.
    """
    try:
        integration = integration_service.create_integration(
            db,
            organization_id=org_id,
            provider=payload.provider,
            credentials=payload.credentials,
        )
    except ConnectorNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except ConnectorAuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    audit_service.record_audit_event(
        db,
        organization_id=org_id,
        user_id=membership.user_id,
        action="integration.created",
        resource_type="integration",
        resource_id=str(integration.id),
        details={"provider": integration.provider},
        ip_address=request.client.host if request and request.client else None,
        commit=True,
    )
    return IntegrationResponse.model_validate(integration)


@router.get(
    "/{org_id}/integrations",
    response_model=list[IntegrationResponse],
    summary="List organization integrations",
)
def list_org_integrations(
    org_id: uuid.UUID,
    _: Membership = Depends(get_current_membership),
    db: Session = Depends(get_db),
) -> list[IntegrationResponse]:
    """List integrations for an organization without exposing secrets."""
    items = integration_service.list_integrations(db, organization_id=org_id)
    return [IntegrationResponse.model_validate(item) for item in items]


@router.delete(
    "/{org_id}/integrations/{integration_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Disconnect and delete an organization integration",
)
def remove_integration(
    org_id: uuid.UUID,
    integration_id: uuid.UUID,
    request: Request,
    membership: Membership = Depends(require_role(MembershipRole.OWNER)),
    _: Membership = Depends(rate_limit_org_write),
    db: Session = Depends(get_db),
) -> Response:
    """Delete a tenant integration. Owner role required."""
    deleted = integration_service.delete_integration(
        db,
        organization_id=org_id,
        integration_id=integration_id,
    )
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Integration not found.",
        )
    audit_service.record_audit_event(
        db,
        organization_id=org_id,
        user_id=membership.user_id,
        action="integration.deleted",
        resource_type="integration",
        resource_id=str(integration_id),
        details={},
        ip_address=request.client.host if request and request.client else None,
        commit=True,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{org_id}/integrations/{integration_id}/sync",
    response_model=IntegrationSyncResponse,
    summary="Trigger connector sync for an integration",
)
async def trigger_integration_sync(
    org_id: uuid.UUID,
    integration_id: uuid.UUID,
    request: Request,
    full_sync: bool = False,
    background: bool = False,
    membership: Membership = Depends(require_role(MembershipRole.MEMBER)),
    _: Membership = Depends(rate_limit_org_write),
    db: Session = Depends(get_db),
) -> IntegrationSyncResponse:
    """
    Fetch and idempotently ingest events from a connected integration.
    Supports synchronous execution or background ARQ queuing via ``background=true``.
    Member or Owner role required.
    """
    if background:
        try:
            run = integration_service.create_pending_sync_run(
                db,
                organization_id=org_id,
                integration_id=integration_id,
            )
            await enqueue_sync_job(
                organization_id=org_id,
                integration_id=integration_id,
                sync_run_id=run.id,
                full_sync=full_sync,
            )
            integ = integration_service.get_integration(
                db, organization_id=org_id, integration_id=integration_id
            )
            audit_service.record_audit_event(
                db,
                organization_id=org_id,
                user_id=membership.user_id,
                action="integration.synced",
                resource_type="integration",
                resource_id=str(integration_id),
                details={"queued": True, "full_sync": full_sync},
                ip_address=request.client.host if request and request.client else None,
                commit=True,
            )
            return IntegrationSyncResponse(
                integration_id=integration_id,
                provider=integ.provider if integ else "unknown",
                status=run.status,
                total_received=0,
                inserted_count=0,
                skipped_count=0,
                sync_run_id=run.id,
                queued=True,
            )
        except ConnectorNotFoundError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=str(exc),
            ) from exc

    try:
        result = integration_service.sync_integration(
            db,
            organization_id=org_id,
            integration_id=integration_id,
            full_sync=full_sync,
        )
        audit_service.record_audit_event(
            db,
            organization_id=org_id,
            user_id=membership.user_id,
            action="integration.synced",
            resource_type="integration",
            resource_id=str(integration_id),
            details={
                "queued": False,
                "full_sync": full_sync,
                "inserted_count": result.inserted_count,
            },
            ip_address=request.client.host if request and request.client else None,
            commit=True,
        )
        return result
    except ConnectorNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except (ConnectorAuthError, ConnectorError) as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc


@router.get(
    "/{org_id}/integrations/github/oauth/url",
    response_model=GitHubOAuthUrlResponse,
    summary="Generate GitHub OAuth authorization URL",
)
def github_oauth_url(
    org_id: uuid.UUID,
    membership: Membership = Depends(require_role(MembershipRole.OWNER)),
) -> GitHubOAuthUrlResponse:
    """Generate a signed state token and GitHub OAuth URL. Owner role required."""
    url, state = integration_service.build_github_oauth_url(
        organization_id=org_id,
        user_id=membership.user_id,
    )
    return GitHubOAuthUrlResponse(authorization_url=url, state=state)


@router.post(
    "/{org_id}/integrations/github/oauth/callback",
    response_model=IntegrationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Complete GitHub OAuth callback and store integration",
)
def github_oauth_callback(
    org_id: uuid.UUID,
    payload: GitHubOAuthCallbackRequest,
    membership: Membership = Depends(require_role(MembershipRole.OWNER)),
    db: Session = Depends(get_db),
) -> IntegrationResponse:
    """
    Verify OAuth state, exchange the code for a GitHub token, and persist the
    encrypted GitHub integration. Owner role required.
    """
    try:
        integration_service.verify_github_oauth_state(
            state=payload.state,
            organization_id=org_id,
            user_id=membership.user_id,
        )
        access_token = integration_service.exchange_github_oauth_code(code=payload.code)
        integration = integration_service.create_integration(
            db,
            organization_id=org_id,
            provider="github",
            credentials={"access_token": access_token, "repo": payload.repo},
        )
    except ConnectorAuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    return IntegrationResponse.model_validate(integration)


@router.post(
    "/{org_id}/imports/csv",
    response_model=EventIngestResult,
    status_code=status.HTTP_201_CREATED,
    summary="Import normalized operational events from CSV",
)
async def import_csv_events(
    org_id: uuid.UUID,
    request: Request,
    membership: Membership = Depends(require_role(MembershipRole.MEMBER)),
    _: Membership = Depends(rate_limit_org_write),
    db: Session = Depends(get_db),
) -> EventIngestResult:
    """
    Ingest CSV event data sent either as JSON ``{"csv_text": "..."}`` or raw
    ``text/csv`` request body. Member or Owner role required.
    """
    content_type = (request.headers.get("content-type") or "").lower()
    raw_bytes = await request.body()

    if "application/json" in content_type:
        try:
            body_json: Any = await request.json()
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Malformed JSON body.",
            ) from exc
        if not isinstance(body_json, dict) or not isinstance(
            body_json.get("csv_text"), str
        ):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="JSON body must contain string field 'csv_text'.",
            )
        csv_text = body_json["csv_text"]
    else:
        try:
            csv_text = raw_bytes.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="CSV payload must be UTF-8 encoded.",
            ) from exc

    try:
        events = CsvConnector().parse_csv_text(csv_text)
    except ConnectorError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    result = ingest_events(db, organization_id=org_id, events=events)
    audit_service.record_audit_event(
        db,
        organization_id=org_id,
        user_id=membership.user_id,
        action="csv.imported",
        resource_type="event_batch",
        details={
            "total_received": result.total_received,
            "inserted_count": result.inserted_count,
            "skipped_count": result.skipped_count,
        },
        ip_address=request.client.host if request and request.client else None,
    )
    db.commit()
    return result
