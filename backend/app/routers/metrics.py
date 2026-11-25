from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session
import uuid

from app.core.auth import get_current_membership
from app.db.session import get_db
from app.models.membership import Membership
from app.schemas.event import EventResponse
from app.schemas.metrics import (
    MetricsSummaryResponse,
    MetricsTimeseriesResponse,
    SyncRunResponse,
)
from app.services import event_service, integration_service, metrics_service

router = APIRouter(prefix="/orgs", tags=["Metrics, Events & Sync Runs"])


@router.get(
    "/{org_id}/metrics/summary",
    response_model=MetricsSummaryResponse,
    summary="Get aggregated MRR, churn, PR, and issue metrics",
)
def get_metrics_summary(
    org_id: uuid.UUID,
    days: int = Query(default=30, ge=1, le=365),
    _: Membership = Depends(get_current_membership),
    db: Session = Depends(get_db),
) -> MetricsSummaryResponse:
    """Return organization-scoped SaaS and engineering KPIs."""
    return metrics_service.compute_metrics_summary(
        db,
        organization_id=org_id,
        window_days=days,
    )


@router.get(
    "/{org_id}/metrics/timeseries",
    response_model=MetricsTimeseriesResponse,
    summary="Get daily revenue and engineering time-series metrics",
)
def get_metrics_timeseries(
    org_id: uuid.UUID,
    days: int = Query(default=30, ge=1, le=365),
    _: Membership = Depends(get_current_membership),
    db: Session = Depends(get_db),
) -> MetricsTimeseriesResponse:
    """Return daily metric buckets for chart visualization."""
    return metrics_service.compute_metrics_timeseries(
        db,
        organization_id=org_id,
        window_days=days,
    )


@router.get(
    "/{org_id}/events",
    response_model=list[EventResponse],
    summary="List normalized operational events for an organization",
)
def list_org_events(
    org_id: uuid.UUID,
    source: str | None = Query(default=None),
    event_type: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    _: Membership = Depends(get_current_membership),
    db: Session = Depends(get_db),
) -> list[EventResponse]:
    """List tenant-scoped normalized events newest first."""
    events = event_service.list_events(
        db,
        organization_id=org_id,
        source=source,
        event_type=event_type,
        limit=limit,
        offset=offset,
    )
    return [EventResponse.model_validate(evt) for evt in events]


@router.get(
    "/{org_id}/events/export",
    summary="Export tenant-scoped operational events as CSV",
)
def export_org_events_csv(
    org_id: uuid.UUID,
    source: str | None = Query(default=None),
    event_type: str | None = Query(default=None),
    days: int = Query(default=30, ge=1, le=365),
    limit: int = Query(default=1000, ge=1, le=5000),
    _: Membership = Depends(get_current_membership),
    db: Session = Depends(get_db),
) -> Response:
    """
    Download normalized events strictly scoped to ``org_id`` as RFC 4180 CSV.
    Requires active organization membership (viewer, member, or owner).
    """
    csv_body = event_service.export_events_csv(
        db,
        organization_id=org_id,
        source=source,
        event_type=event_type,
        days=days,
        limit=limit,
    )
    return Response(
        content=csv_body,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="pulseops-events-{org_id}.csv"',
            "Cache-Control": "no-store",
        },
    )


@router.get(
    "/{org_id}/sync-runs",
    response_model=list[SyncRunResponse],
    summary="List connector sync run history for an organization",
)
def list_org_sync_runs(
    org_id: uuid.UUID,
    limit: int = Query(default=50, ge=1, le=200),
    _: Membership = Depends(get_current_membership),
    db: Session = Depends(get_db),
) -> list[SyncRunResponse]:
    """List SyncRun audit records strictly scoped to ``org_id``."""
    runs = integration_service.list_sync_runs(
        db,
        organization_id=org_id,
        limit=limit,
    )
    return [SyncRunResponse.model_validate(run) for run in runs]
