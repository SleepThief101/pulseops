from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

from app.core.auth import get_current_membership
from app.models.membership import Membership
from app.services.realtime_service import subscribe_org_events

router = APIRouter(prefix="/orgs", tags=["Real-time Updates"])


@router.get(
    "/{org_id}/events/stream",
    summary="Stream real-time operational event notifications via SSE",
)
async def stream_org_events(
    org_id: uuid.UUID,
    max_events: int | None = Query(default=None, ge=1, le=100),
    idle_timeout: float | None = Query(default=None, gt=0, le=300),
    _: Membership = Depends(get_current_membership),
) -> StreamingResponse:
    """
    Subscribe to Server-Sent Events (SSE) backed by Redis Pub/Sub for ``org_id``.
    Strictly requires organization membership (HTTP 401 unauthenticated, HTTP 404 non-member).
    """
    return StreamingResponse(
        subscribe_org_events(
            org_id,
            max_events=max_events,
            idle_timeout_seconds=idle_timeout,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
