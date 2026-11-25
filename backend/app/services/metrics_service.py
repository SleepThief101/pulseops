from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.currency import (
    InvalidCurrencyError,
    UNKNOWN_CURRENCY,
    format_minor_amount,
    get_minor_unit_exponent,
    get_minor_unit_name,
    normalize_currency,
)
from app.models.event import Event
from app.schemas.metrics import (
    CurrencyMetricsSummary,
    CurrencyTimeseriesPoint,
    MetricsSummaryResponse,
    MetricsTimeseriesPoint,
    MetricsTimeseriesResponse,
)

_SUBSCRIPTION_CHARGE_TYPES = {"subscription.charged"}
_ONE_TIME_PAYMENT_TYPES = {"payment.captured"}
_REFUND_EVENT_TYPES = {"payment.refunded"}
_FAILED_PAYMENT_TYPES = {"payment.failed"}
_CHURN_EVENT_TYPES = {"subscription.cancelled"}
_MONETARY_EVENT_TYPES = (
    _SUBSCRIPTION_CHARGE_TYPES
    | _ONE_TIME_PAYMENT_TYPES
    | _REFUND_EVENT_TYPES
    | _FAILED_PAYMENT_TYPES
    | _CHURN_EVENT_TYPES
)


@dataclass
class _ActiveSubscriptionEntry:
    occurred_at: datetime
    monthly_minor: int
    actor: str | None
    payment_external_id: str


@dataclass
class _CurrencyAccumulator:
    currency: str
    exponent: int | None
    subscription_revenue_minor: int = 0
    one_time_payment_volume_minor: int = 0
    refunded_minor: int = 0
    churned_mrr_minor: int = 0
    failed_payments_count: int = 0
    failed_payments_minor: int = 0
    paying_actors: set[str] = field(default_factory=set)
    one_time_actors: set[str] = field(default_factory=set)
    churned_actors: set[str] = field(default_factory=set)
    churn_events_count: int = 0
    active_subscriptions: dict[str, _ActiveSubscriptionEntry] = field(default_factory=dict)
    refunds_to_apply: list[tuple[str | None, str | None, str | None, int]] = field(
        default_factory=list
    )


def _canonical_event_currency(evt: Event) -> str:
    raw = (evt.currency or "").strip().upper()
    if not raw:
        return UNKNOWN_CURRENCY
    try:
        normalized = normalize_currency(raw, allow_none=False)
        return normalized or UNKNOWN_CURRENCY
    except InvalidCurrencyError:
        return raw


def _subscription_key(evt: Event, payload: dict[str, object]) -> str:
    sub_id = str(payload.get("subscription_id") or "").strip()
    if sub_id:
        return f"sub:{sub_id}"
    if evt.actor:
        return f"actor:{evt.actor}"
    return f"evt:{evt.external_id}"


def _monthly_equivalent_minor(amount_minor: int, payload: dict[str, object]) -> int:
    interval = str(
        payload.get("billing_interval") or payload.get("interval") or ""
    ).strip().lower()
    if interval in {"year", "yearly", "annual", "annually"}:
        monthly = (Decimal(amount_minor) / Decimal(12)).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
        return int(monthly)
    return amount_minor


def compute_metrics_summary(
    db: Session,
    *,
    organization_id: uuid.UUID,
    window_days: int = 30,
    as_of: datetime | None = None,
    include_synthetic: bool = False,
) -> MetricsSummaryResponse:
    """
    Compute tenant-scoped multi-currency SaaS revenue and engineering metrics
    strictly from Event records belonging to ``organization_id``.

    - Currencies are never aggregated together.
    - Recurring MRR/ARR uses latest active ``subscription.charged`` per subscriber
      (never one-time ``payment.captured`` and never multiplying 90-day sums by 12).
    - Failed payments (``payment.failed``) are tracked separately and excluded from revenue.
    - Synthetic/mock events are excluded unless ``include_synthetic=True``.
    """
    now = as_of or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    since = now - timedelta(days=window_days)

    synthetic_events_in_window = int(
        db.scalar(
            select(func.count(Event.id)).where(
                Event.organization_id == organization_id,
                Event.occurred_at >= since,
                Event.occurred_at <= now,
                Event.is_synthetic.is_(True),
            )
        )
        or 0
    )

    stmt = (
        select(Event)
        .where(
            Event.organization_id == organization_id,
            Event.occurred_at >= since,
            Event.occurred_at <= now,
        )
        .order_by(Event.occurred_at.asc(), Event.created_at.asc())
    )
    if not include_synthetic:
        stmt = stmt.where(Event.is_synthetic.is_(False))

    events = list(db.scalars(stmt).all())

    by_currency_acc: dict[str, _CurrencyAccumulator] = {}

    def _get_acc(evt: Event) -> _CurrencyAccumulator:
        code = _canonical_event_currency(evt)
        acc = by_currency_acc.get(code)
        if acc is None:
            exp = evt.minor_unit_exponent
            if exp is None and code != UNKNOWN_CURRENCY:
                try:
                    exp = get_minor_unit_exponent(code)
                except InvalidCurrencyError:
                    exp = None
            acc = _CurrencyAccumulator(currency=code, exponent=exp)
            by_currency_acc[code] = acc
        return acc

    all_paying_actors: set[str] = set()
    all_churned_actors: set[str] = set()
    total_churn_events = 0

    prs_opened = 0
    prs_merged = 0
    issues_closed_count = 0

    issue_cycle_times: list[float] = []
    pr_cycle_times: list[float] = []

    for evt in events:
        etype = evt.event_type
        payload = evt.payload if isinstance(evt.payload, dict) else {}

        if etype in _MONETARY_EVENT_TYPES or evt.amount_cents is not None:
            amount = int(evt.amount_cents or 0)
            acc = _get_acc(evt)

            if etype in _SUBSCRIPTION_CHARGE_TYPES:
                acc.subscription_revenue_minor += amount
                if evt.actor:
                    acc.paying_actors.add(evt.actor)
                    all_paying_actors.add(evt.actor)

                sub_key = _subscription_key(evt, payload)
                monthly_minor = _monthly_equivalent_minor(amount, payload)
                prev = acc.active_subscriptions.get(sub_key)
                if prev is None or evt.occurred_at >= prev.occurred_at:
                    acc.active_subscriptions[sub_key] = _ActiveSubscriptionEntry(
                        occurred_at=evt.occurred_at,
                        monthly_minor=monthly_minor,
                        actor=evt.actor,
                        payment_external_id=evt.external_id,
                    )
            elif etype in _ONE_TIME_PAYMENT_TYPES:
                acc.one_time_payment_volume_minor += amount
                if evt.actor:
                    acc.one_time_actors.add(evt.actor)
            elif etype in _FAILED_PAYMENT_TYPES:
                acc.failed_payments_count += 1
                acc.failed_payments_minor += amount
            elif etype in _REFUND_EVENT_TYPES:
                acc.refunded_minor += amount
                ref_sub_id = str(payload.get("subscription_id") or "").strip() or None
                ref_pay_id = str(payload.get("payment_id") or "").strip() or None
                acc.refunds_to_apply.append((ref_sub_id, ref_pay_id, evt.actor, amount))
            elif etype in _CHURN_EVENT_TYPES:
                acc.churned_mrr_minor += amount
                acc.churn_events_count += 1
                total_churn_events += 1
                if evt.actor:
                    acc.churned_actors.add(evt.actor)
                    all_churned_actors.add(evt.actor)
                sub_key = _subscription_key(evt, payload)
                active_entry = acc.active_subscriptions.get(sub_key)
                if active_entry is not None and evt.occurred_at >= active_entry.occurred_at:
                    acc.active_subscriptions.pop(sub_key, None)

        if etype == "pr.opened":
            prs_opened += 1
        elif etype == "pr.merged":
            prs_merged += 1
            if isinstance(payload.get("cycle_time_hours"), (int, float)):
                pr_cycle_times.append(float(payload["cycle_time_hours"]))
        elif etype == "issue.closed":
            issues_closed_count += 1
            if isinstance(payload.get("cycle_time_hours"), (int, float)):
                issue_cycle_times.append(float(payload["cycle_time_hours"]))

    # Compute current open issues across org events by tracking repo+number state
    issue_stmt = (
        select(Event.event_type, Event.source, Event.payload)
        .where(
            Event.organization_id == organization_id,
            Event.event_type.in_(["issue.opened", "issue.closed"]),
        )
        .order_by(Event.occurred_at.asc())
    )
    if not include_synthetic:
        issue_stmt = issue_stmt.where(Event.is_synthetic.is_(False))
    all_issue_events = db.execute(issue_stmt).all()

    open_issue_keys: set[str] = set()
    unkeyed_open_balance = 0
    for evt_type, evt_source, raw_payload in all_issue_events:
        p = raw_payload if isinstance(raw_payload, dict) else {}
        num = p.get("number")
        repo = p.get("repo") or evt_source
        if num is not None:
            key = f"{repo}#{num}"
            if evt_type == "issue.opened":
                open_issue_keys.add(key)
            else:
                open_issue_keys.discard(key)
        else:
            if evt_type == "issue.opened":
                unkeyed_open_balance += 1
            else:
                unkeyed_open_balance = max(unkeyed_open_balance - 1, 0)

    open_issues_count = len(open_issue_keys) + unkeyed_open_balance

    # Build per-currency summaries (never merging currencies)
    currencies = sorted(by_currency_acc.keys(), key=lambda c: (c == UNKNOWN_CURRENCY, c))
    by_currency: dict[str, CurrencyMetricsSummary] = {}
    methodology_notes: list[str] = []

    for code in currencies:
        acc = by_currency_acc[code]

        # Apply refunds tied directly to active subscriptions (or subscription-only actors)
        sub_refund_deduction = 0
        sub_by_actor: dict[str, list[str]] = defaultdict(list)
        sub_by_payment: dict[str, str] = {}
        for skey, entry in acc.active_subscriptions.items():
            if entry.actor:
                sub_by_actor[entry.actor].append(skey)
            sub_by_payment[entry.payment_external_id] = skey

        for ref_sub_id, ref_pay_id, ref_actor, ref_amt in acc.refunds_to_apply:
            target_key: str | None = None
            if ref_sub_id and f"sub:{ref_sub_id}" in acc.active_subscriptions:
                target_key = f"sub:{ref_sub_id}"
            elif ref_pay_id and ref_pay_id in sub_by_payment:
                target_key = sub_by_payment[ref_pay_id]
            elif (
                ref_actor
                and ref_actor in sub_by_actor
                and ref_actor not in acc.one_time_actors
            ):
                target_key = sub_by_actor[ref_actor][-1]

            if target_key is not None and target_key in acc.active_subscriptions:
                entry = acc.active_subscriptions[target_key]
                deduction = min(max(ref_amt, 0), max(entry.monthly_minor, 0))
                entry.monthly_minor -= deduction
                sub_refund_deduction += deduction

        recurring_mrr_minor = max(
            sum(entry.monthly_minor for entry in acc.active_subscriptions.values()),
            0,
        )
        recurring_arr_minor = recurring_mrr_minor * 12
        gross_volume_minor = acc.subscription_revenue_minor + acc.one_time_payment_volume_minor
        net_revenue_minor = gross_volume_minor - acc.refunded_minor

        curr_churned_count = (
            len(acc.churned_actors) if acc.churned_actors else acc.churn_events_count
        )
        curr_active_count = len(acc.paying_actors - acc.churned_actors)

        mrr_reliable = True
        mrr_note: str | None = None
        if code == UNKNOWN_CURRENCY:
            mrr_reliable = False
            mrr_note = (
                "Events lack an ISO-4217 currency code; amounts cannot be formatted "
                "or converted reliably."
            )
        elif acc.subscription_revenue_minor == 0 and acc.one_time_payment_volume_minor > 0:
            mrr_reliable = False
            mrr_note = (
                "Only one-time payment.captured events exist in this window; "
                "one-time payments are excluded from recurring MRR and ARR."
            )
        elif window_days > 31 and acc.active_subscriptions:
            mrr_note = (
                f"Active recurring MRR deduplicated across {window_days}d using each "
                "subscriber's latest charge rather than summing multi-month renewals."
            )

        by_currency[code] = CurrencyMetricsSummary(
            currency=code,
            minor_unit_exponent=acc.exponent,
            minor_unit_name=get_minor_unit_name(code),
            recurring_mrr_minor=recurring_mrr_minor,
            recurring_arr_minor=recurring_arr_minor,
            subscription_revenue_minor=acc.subscription_revenue_minor,
            one_time_payment_volume_minor=acc.one_time_payment_volume_minor,
            gross_volume_minor=gross_volume_minor,
            refunded_minor=acc.refunded_minor,
            net_revenue_minor=net_revenue_minor,
            churned_mrr_minor=acc.churned_mrr_minor,
            failed_payments_count=acc.failed_payments_count,
            failed_payments_minor=acc.failed_payments_minor,
            active_subscribers_count=curr_active_count,
            churned_subscriptions_count=curr_churned_count,
            formatted_recurring_mrr=format_minor_amount(
                recurring_mrr_minor, code, exponent=acc.exponent
            ),
            formatted_recurring_arr=format_minor_amount(
                recurring_arr_minor, code, exponent=acc.exponent
            ),
            formatted_subscription_revenue=format_minor_amount(
                acc.subscription_revenue_minor, code, exponent=acc.exponent
            ),
            formatted_one_time_volume=format_minor_amount(
                acc.one_time_payment_volume_minor, code, exponent=acc.exponent
            ),
            formatted_gross_volume=format_minor_amount(
                gross_volume_minor, code, exponent=acc.exponent
            ),
            formatted_refunded=format_minor_amount(
                acc.refunded_minor, code, exponent=acc.exponent
            ),
            formatted_net_revenue=format_minor_amount(
                net_revenue_minor, code, exponent=acc.exponent
            ),
            formatted_churned_mrr=format_minor_amount(
                acc.churned_mrr_minor, code, exponent=acc.exponent
            ),
            formatted_failed_payments=format_minor_amount(
                acc.failed_payments_minor, code, exponent=acc.exponent
            ),
            mrr_reliable=mrr_reliable,
            mrr_note=mrr_note,
        )

    multi_currency = len(currencies) > 1
    primary_currency = currencies[0] if len(currencies) == 1 else None

    if multi_currency:
        methodology_notes.append(
            f"Multiple currencies present ({', '.join(currencies)}); figures are aggregated "
            "per currency with no FX conversion applied."
        )
    if any(not s.mrr_reliable and s.mrr_note for s in by_currency.values()):
        methodology_notes.append(
            "One-time payment.captured events are excluded from recurring MRR/ARR."
        )
    synthetic_excluded = (not include_synthetic) and (synthetic_events_in_window > 0)
    contains_synthetic = include_synthetic and (synthetic_events_in_window > 0)
    if synthetic_excluded:
        methodology_notes.append(
            f"Excluded {synthetic_events_in_window} synthetic/mock event(s) from financial metrics."
        )
    elif contains_synthetic:
        methodology_notes.append(
            f"Includes {synthetic_events_in_window} synthetic/mock demo event(s)."
        )

    if len(currencies) == 1:
        single = by_currency[currencies[0]]
        gross_revenue_cents: int | None = single.gross_volume_minor
        refunded_cents: int | None = single.refunded_minor
        churned_mrr_cents: int | None = single.churned_mrr_minor
        mrr_cents: int | None = single.recurring_mrr_minor
        arr_cents: int | None = single.recurring_arr_minor
    elif len(currencies) == 0:
        gross_revenue_cents = 0
        refunded_cents = 0
        churned_mrr_cents = 0
        mrr_cents = 0
        arr_cents = 0
    else:
        # Never combine distinct currencies into scalar totals
        gross_revenue_cents = None
        refunded_cents = None
        churned_mrr_cents = None
        mrr_cents = None
        arr_cents = None

    churned_subscriptions_count = (
        len(all_churned_actors) if all_churned_actors else total_churn_events
    )
    active_subscribers_count = len(all_paying_actors - all_churned_actors)
    total_sub_base = len(all_paying_actors | all_churned_actors)
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
        currencies=currencies,
        primary_currency=primary_currency,
        multi_currency=multi_currency,
        by_currency=by_currency,
        contains_synthetic_data=contains_synthetic,
        synthetic_events_in_window=synthetic_events_in_window,
        synthetic_events_excluded=synthetic_excluded,
        include_synthetic=include_synthetic,
        fx_conversion_applied=False,
        methodology_notes=methodology_notes,
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
    include_synthetic: bool = False,
) -> MetricsTimeseriesResponse:
    """
    Build daily aggregated time-series points strictly scoped to ``organization_id``
    and isolated per currency.
    """
    now = as_of or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    end_date = now.date()
    start_date = end_date - timedelta(days=window_days - 1)
    since_dt = datetime.combine(start_date, datetime.min.time(), tzinfo=timezone.utc)

    synthetic_events_in_window = int(
        db.scalar(
            select(func.count(Event.id)).where(
                Event.organization_id == organization_id,
                Event.occurred_at >= since_dt,
                Event.occurred_at <= now,
                Event.is_synthetic.is_(True),
            )
        )
        or 0
    )

    stmt = select(Event).where(
        Event.organization_id == organization_id,
        Event.occurred_at >= since_dt,
        Event.occurred_at <= now,
    )
    if not include_synthetic:
        stmt = stmt.where(Event.is_synthetic.is_(False))

    events = list(db.scalars(stmt).all())

    day_eng: dict[str, dict[str, int]] = {}
    day_currencies: dict[str, dict[str, CurrencyTimeseriesPoint]] = {}
    seen_currencies: set[str] = set()

    for day_offset in range(window_days):
        day_str = (start_date + timedelta(days=day_offset)).isoformat()
        day_eng[day_str] = {
            "prs_opened": 0,
            "prs_merged": 0,
            "issues_opened": 0,
            "issues_closed": 0,
        }
        day_currencies[day_str] = {}

    for evt in events:
        day_str = evt.occurred_at.astimezone(timezone.utc).date().isoformat()
        eng_bucket = day_eng.get(day_str)
        curr_map = day_currencies.get(day_str)
        if eng_bucket is None or curr_map is None:
            continue

        etype = evt.event_type
        if etype in _MONETARY_EVENT_TYPES or evt.amount_cents is not None:
            code = _canonical_event_currency(evt)
            seen_currencies.add(code)
            pt = curr_map.get(code)
            if pt is None:
                pt = CurrencyTimeseriesPoint(currency=code)
                curr_map[code] = pt

            amount = int(evt.amount_cents or 0)
            if etype in _SUBSCRIPTION_CHARGE_TYPES:
                pt.subscription_revenue_minor += amount
                pt.gross_volume_minor += amount
            elif etype in _ONE_TIME_PAYMENT_TYPES:
                pt.one_time_volume_minor += amount
                pt.gross_volume_minor += amount
            elif etype in _REFUND_EVENT_TYPES:
                pt.refunded_minor += amount
            elif etype in _CHURN_EVENT_TYPES:
                pt.churned_mrr_minor += amount
            elif etype in _FAILED_PAYMENT_TYPES:
                pt.failed_payments_minor += amount

        if etype == "pr.opened":
            eng_bucket["prs_opened"] += 1
        elif etype == "pr.merged":
            eng_bucket["prs_merged"] += 1
        elif etype == "issue.opened":
            eng_bucket["issues_opened"] += 1
        elif etype == "issue.closed":
            eng_bucket["issues_closed"] += 1

    currencies = sorted(seen_currencies, key=lambda c: (c == UNKNOWN_CURRENCY, c))
    multi_currency = len(currencies) > 1
    primary_currency = currencies[0] if len(currencies) == 1 else None

    points: list[MetricsTimeseriesPoint] = []
    for day_str, eng in day_eng.items():
        curr_map = day_currencies[day_str]
        if multi_currency:
            rev_cents: int | None = None
            churn_cents: int | None = None
        elif len(currencies) == 1:
            pt = curr_map.get(currencies[0])
            rev_cents = pt.gross_volume_minor if pt else 0
            churn_cents = (pt.refunded_minor + pt.churned_mrr_minor) if pt else 0
        else:
            rev_cents = 0
            churn_cents = 0

        points.append(
            MetricsTimeseriesPoint(
                date=day_str,
                revenue_cents=rev_cents,
                churn_cents=churn_cents,
                by_currency=curr_map,
                **eng,
            )
        )

    return MetricsTimeseriesResponse(
        organization_id=organization_id,
        window_days=window_days,
        currencies=currencies,
        primary_currency=primary_currency,
        multi_currency=multi_currency,
        contains_synthetic_data=include_synthetic and (synthetic_events_in_window > 0),
        synthetic_events_in_window=synthetic_events_in_window,
        synthetic_events_excluded=(not include_synthetic) and (synthetic_events_in_window > 0),
        include_synthetic=include_synthetic,
        points=points,
    )
