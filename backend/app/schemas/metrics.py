from __future__ import annotations

from datetime import datetime
import uuid

from pydantic import BaseModel, ConfigDict


class SyncRunResponse(BaseModel):
    """Serialized SyncRun status entry scoped to an organization."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    integration_id: uuid.UUID
    status: str
    events_received: int
    events_inserted: int
    events_skipped: int
    error_message: str | None
    started_at: datetime
    finished_at: datetime | None


class MetricsSummaryResponse(BaseModel):
    """Aggregated SaaS revenue & engineering metrics for an organization."""

    organization_id: uuid.UUID
    window_days: int
    gross_revenue_cents: int
    refunded_cents: int
    churned_mrr_cents: int
    mrr_cents: int
    arr_cents: int
    active_subscribers_count: int
    churned_subscriptions_count: int
    churn_rate_pct: float
    prs_opened: int
    prs_merged: int
    open_issues_count: int
    issues_closed_count: int
    avg_issue_cycle_time_hours: float | None
    avg_pr_cycle_time_hours: float | None
    total_events_in_window: int


class MetricsTimeseriesPoint(BaseModel):
    """Single day metric bucket suitable for Recharts visualization."""

    date: str
    revenue_cents: int
    churn_cents: int
    prs_opened: int
    prs_merged: int
    issues_opened: int
    issues_closed: int


class MetricsTimeseriesResponse(BaseModel):
    """Daily time-series response for an organization."""

    organization_id: uuid.UUID
    window_days: int
    points: list[MetricsTimeseriesPoint]
