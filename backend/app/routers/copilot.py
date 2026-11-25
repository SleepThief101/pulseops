from __future__ import annotations

from typing import Any
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.auth import get_current_membership, require_role
from app.core.rate_limit import rate_limit_copilot
from app.db.session import get_db
from app.models.membership import Membership, MembershipRole
from app.schemas.copilot import (
    CopilotChatRequest,
    CopilotChatResponse,
    CopilotProposalResponse,
    ProposalDecisionRequest,
)
from app.services import copilot_service

router = APIRouter(prefix="/orgs", tags=["AI Copilot & Approvals"])


@router.post(
    "/{org_id}/copilot/chat",
    response_model=None,
    responses={200: {"model": CopilotChatResponse}},
    summary="Chat with the PulseOps AI Copilot",
)
def copilot_chat(
    org_id: uuid.UUID,
    payload: CopilotChatRequest,
    membership: Membership = Depends(rate_limit_copilot),
    db: Session = Depends(get_db),
) -> Any:
    """
    Answer operational questions using tenant-scoped read-only tools and create
    pending ActionProposals for mutating requests. Supports ``stream=true`` for
    Server-Sent Events token streaming.
    """
    if payload.stream:
        stream_iter = copilot_service.prepare_copilot_stream(
            db,
            organization_id=org_id,
            user_id=membership.user_id,
            message=payload.message,
            caller_role=membership.role,
        )
        return StreamingResponse(
            stream_iter,
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    return copilot_service.run_copilot_chat(
        db,
        organization_id=org_id,
        user_id=membership.user_id,
        message=payload.message,
        caller_role=membership.role,
    )


@router.get(
    "/{org_id}/copilot/proposals",
    response_model=list[CopilotProposalResponse],
    summary="List AI action proposals for an organization",
)
def list_copilot_proposals(
    org_id: uuid.UUID,
    limit: int = Query(default=50, ge=1, le=200),
    _: Membership = Depends(get_current_membership),
    db: Session = Depends(get_db),
) -> list[CopilotProposalResponse]:
    """List pending and resolved ActionProposals scoped to ``org_id``."""
    proposals = copilot_service.list_proposals(
        db,
        organization_id=org_id,
        limit=limit,
    )
    return [CopilotProposalResponse.model_validate(p) for p in proposals]


@router.post(
    "/{org_id}/copilot/proposals/{proposal_id}/decision",
    response_model=CopilotProposalResponse,
    summary="Approve or reject a pending AI action proposal",
)
def decide_copilot_proposal(
    org_id: uuid.UUID,
    proposal_id: uuid.UUID,
    payload: ProposalDecisionRequest,
    membership: Membership = Depends(require_role(MembershipRole.MEMBER)),
    db: Session = Depends(get_db),
) -> CopilotProposalResponse:
    """
    Approve (and execute) or reject a pending ActionProposal.
    Member or Owner role required (plus any tool-specific min_role).
    """
    try:
        proposal = copilot_service.decide_proposal(
            db,
            organization_id=org_id,
            proposal_id=proposal_id,
            reviewer_user_id=membership.user_id,
            reviewer_role=membership.role,
            decision=payload.decision,
        )
    except copilot_service.ProposalNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except copilot_service.ProposalConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except copilot_service.ProposalPermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        ) from exc

    return CopilotProposalResponse.model_validate(proposal)
