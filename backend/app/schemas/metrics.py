from __future__ import annotations

from datetime import datetime
import uuid

from pydantic import BaseModel, ConfigDict, Field


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


class CurrencyMetricsSummary(BaseModel):
    """Monetary KPIs isolated strictly to a single currency."""

    currency: str
    minor_unit_exponent: int | None
    minor_unit_name: str
    recurring_mrr_minor: int
    recurring_arr_minor: int
    subscription_revenue_minor: int
    one_time_payment_volume_minor: int
    gross_volume_minor: int
    refunded_minor: int
    net_revenue_minor: int
    churned_mrr_minor: int
    failed_payments_count: int
    failed_payments_minor: int
    active_subscribers_count: int
    churned_subscriptions_count: int
    formatted_recurring_mrr: str
    formatted_recurring_arr: str
    formatted_subscription_revenue: str
    formatted_one_time_volume: str
    formatted_gross_volume: str
    formatted_refunded: str
    formatted_net_revenue: str
    formatted_churned_mrr: str
    formatted_failed_payments: str
    mrr_reliable: bool = True
    mrr_note: str | None = None


class MetricsSummaryResponse(BaseModel):
    """
    Aggregated SaaS revenue & engineering metrics for an organization.

    Multi-currency metrics are always isolated under ``by_currency``.
    Legacy scalar ``*_cents`` fields are populated ONLY for single-currency
    (or empty) windows and set to ``None`` when multiple currencies exist so
    distinct currencies are never added together.
    """

    organization_id: uuid.UUID
    window_days: int
    currencies: list[str] = Field(default_factory=list)
    primary_currency: str | None = None
    multi_currency: bool = False
    by_currency: dict[str, CurrencyMetricsSummary] = Field(default_factory=dict)
    contains_synthetic_data: bool = False
    synthetic_events_in_window: int = 0
    synthetic_events_excluded: bool = False
    include_synthetic: bool = False
    fx_conversion_applied: bool = False
    methodology_notes: list[str] = Field(default_factory=list)

    # Single-currency compatibility scalars (None when multi_currency is True)
    gross_revenue_cents: int | None = 0
    refunded_cents: int | None = 0
    churned_mrr_cents: int | None = 0
    mrr_cents: int | None = 0
    arr_cents: int | None = 0

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


class CurrencyTimeseriesPoint(BaseModel):
    """Daily monetary figures for a single currency in minor units."""

    currency: str
    subscription_revenue_minor: int = 0
    one_time_volume_minor: int = 0
    gross_volume_minor: int = 0
    refunded_minor: int = 0
    churned_mrr_minor: int = 0
    failed_payments_minor: int = 0


class MetricsTimeseriesPoint(BaseModel):
    """Single day metric bucket suitable for Recharts visualization."""

    date: str
    revenue_cents: int | None = 0
    churn_cents: int | None = 0
    by_currency: dict[str, CurrencyTimeseriesPoint] = Field(default_factory=dict)
    prs_opened: int
    prs_merged: int
    issues_opened: int
    issues_closed: int


class MetricsTimeseriesResponse(BaseModel):
    """Daily time-series response for an organization."""

    organization_id: uuid.UUID
    window_days: int
    currencies: list[str] = Field(default_factory=list)
    primary_currency: str | None = None
    multi_currency: bool = False
    contains_synthetic_data: bool = False
    synthetic_events_in_window: int = 0
    synthetic_events_excluded: bool = False
    include_synthetic: bool = False
    points: list[MetricsTimeseriesPoint]
