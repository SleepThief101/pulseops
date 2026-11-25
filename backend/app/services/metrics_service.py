from __future__ import annotations

from datetime import datetime, timedelta, timezone
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.event import Event
from app.schemas.metrics import (
    MetricsSummaryResponse,
    MetricsTimeseriesPoint,
    MetricsTimeseriesResponse,
)

_REVENUE_EVENT_TYPES = {"subscription.charged", "payment.captured"}
_REFUND_EVENT_TYPES = {"payment.refunded"}
_CHURN_EVENT_TYPES = {"subscription.cancelled"}


def compute_metrics_summary(
    db: Session,
    *,
    organization_id: uuid.UUID,
    window_days: int = 30,
    as_of: datetime | None = None,
) -> MetricsSummaryResponse:
    """
    Compute tenant-scoped SaaS revenue (MRR, ARR, churn) and engineering
    metrics (PRs opened/merged, open issues, issue & PR cycle time) strictly
    from Event records belonging to ``organization_id``.
    """
    now = as_of or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    since = now - timedelta(days=window_days)

    events = list(
        db.scalars(
            select(Event).where(
                Event.organization_id == organization_id,
                Event.occurred_at >= since,
                Event.occurred_at <= now,
            )
        ).all()
    )

    gross_revenue_cents = 0
    refunded_cents = 0
    churned_mrr_cents = 0

    paying_actors: set[str] = set()
    churned_actors: set[str] = set()
    churn_events_count = 0

    prs_opened = 0
    prs_merged = 0
    issues_opened_in_window = 0
    issues_closed_count = 0

    issue_cycle_times: list[float] = []
    pr_cycle_times: list[float] = []

    for evt in events:
        etype = evt.event_type
        amount = int(evt.amount_cents or 0)
        payload = evt.payload if isinstance(evt.payload, dict) else {}

        if etype in _REVENUE_EVENT_TYPES:
            gross_revenue_cents += amount
            if evt.actor:
                paying_actors.add(evt.actor)
        elif etype in _REFUND_EVENT_TYPES:
            refunded_cents += amount
        elif etype in _CHURN_EVENT_TYPES:
            churned_mrr_cents += amount
            churn_events_count += 1
            if evt.actor:
                churned_actors.add(evt.actor)
        elif etype == "pr.opened":
            prs_opened += 1
        elif etype == "pr.merged":
            prs_merged += 1
            if isinstance(payload.get("cycle_time_hours"), (int, float)):
                pr_cycle_times.append(float(payload["cycle_time_hours"]))
        elif etype == "issue.opened":
            issues_opened_in_window += 1
        elif etype == "issue.closed":
            issues_closed_count += 1
            if isinstance(payload.get("cycle_time_hours"), (int, float)):
                issue_cycle_times.append(float(payload["cycle_time_hours"]))

    # Compute current open issues across all org events by tracking repo+number state
    all_issue_events = list(
        db.scalars(
            select(Event)
            .where(
                Event.organization_id == organization_id,
                Event.event_type.in_(["issue.opened", "issue.closed"]),
            )
            .order_by(Event.occurred_at.asc())
        ).all()
    )
    open_issue_keys: set[str] = set()
    unkeyed_open_balance = 0
    for ievt in all_issue_events:
        p = ievt.payload if isinstance(ievt.payload, dict) else {}
        num = p.get("number")
        repo = p.get("repo") or ievt.source
        if num is not None:
            key = f"{repo}#{num}"
            if ievt.event_type == "issue.opened":
                open_issue_keys.add(key)
            else:
                open_issue_keys.discard(key)
        else:
            if ievt.event_type == "issue.opened":
                unkeyed_open_balance += 1
            else:
                unkeyed_open_balance = max(unkeyed_open_balance - 1, 0)

    open_issues_count = len(open_issue_keys) + unkeyed_open_balance

    mrr_cents = max(gross_revenue_cents - refunded_cents - churned_mrr_cents, 0)
    arr_cents = mrr_cents * 12

    churned_subscriptions_count = (
        len(churned_actors) if churned_actors else churn_events_count
    )
    active_subscribers_count = len(paying_actors - churned_actors)
    total_sub_base = len(paying_actors | churned_actors)
    if total_sub_base > 0:
        churn_rate_pct = round((churned_subscriptions_count / total_sub_base) * 100.0, 2)
    else:
        churn_rate_pct = 0.0

    avg_issue_cycle = (
        round(sum(issue_cycle_times) / len(issue_cycle_times), 2)
        if issue_cycle_times
        else None
    )
    avg_pr_cycle = (
        round(sum(pr_cycle_times) / len(pr_cycle_times), 2)
        if pr_cycle_times
        else None
    )

    return MetricsSummaryResponse(
        organization_id=organization_id,
        window_days=window_days,
        gross_revenue_cents=gross_revenue_cents,
        refunded_cents=refunded_cents,
        churned_mrr_cents=churned_mrr_cents,
        mrr_cents=mrr_cents,
        arr_cents=arr_cents,
        active_subscribers_count=active_subscribers_count,
        churned_subscriptions_count=churned_subscriptions_count,
        churn_rate_pct=churn_rate_pct,
        prs_opened=prs_opened,
        prs_merged=prs_merged,
        open_issues_count=open_issues_count,
        issues_closed_count=issues_closed_count,
        avg_issue_cycle_time_hours=avg_issue_cycle,
        avg_pr_cycle_time_hours=avg_pr_cycle,
        total_events_in_window=len(events),
    )


def compute_metrics_timeseries(
    db: Session,
    *,
    organization_id: uuid.UUID,
    window_days: int = 30,
    as_of: datetime | None = None,
) -> MetricsTimeseriesResponse:
    """
    Build daily aggregated time-series points strictly scoped to ``organization_id``.
    """
    now = as_of or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    end_date = now.date()
    start_date = end_date - timedelta(days=window_days - 1)

    since_dt = datetime.combine(start_date, datetime.min.time(), tzinfo=timezone.utc)
    events = list(
        db.scalars(
            select(Event).where(
                Event.organization_id == organization_id,
                Event.occurred_at >= since_dt,
                Event.occurred_at <= now,
            )
        ).all()
    )

    buckets: dict[str, dict[str, int]] = {}
    for day_offset in range(window_days):
        day_str = (start_date + timedelta(days=day_offset)).isoformat()
        buckets[day_str] = {
            "revenue_cents": 0,
            "churn_cents": 0,
            "prs_opened": 0,
            "prs_merged": 0,
            "issues_opened": 0,
            "issues_closed": 0,
        }

    for evt in events:
        day_str = evt.occurred_at.astimezone(timezone.utc).date().isoformat()
        bucket = buckets.get(day_str)
        if bucket is None:
            continue
        etype = evt.event_type
        amount = int(evt.amount_cents or 0)
        if etype in _REVENUE_EVENT_TYPES:
            bucket["revenue_cents"] += amount
        elif etype in (_REFUND_EVENT_TYPES | _CHURN_EVENT_TYPES):
            bucket["churn_cents"] += amount
        elif etype == "pr.opened":
            bucket["prs_opened"] += 1
        elif etype == "pr.merged":
            bucket["prs_merged"] += 1
        elif etype == "issue.opened":
            bucket["issues_opened"] += 1
        elif etype == "issue.closed":
            bucket["issues_closed"] += 1

    points = [
        MetricsTimeseriesPoint(date=day_str, **vals)
        for day_str, vals in buckets.items()
    ]
    return MetricsTimeseriesResponse(
        organization_id=organization_id,
        window_days=window_days,
        points=points,
    )
