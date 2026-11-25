from __future__ import annotations

from collections.abc import Sequence
import csv
from datetime import datetime, timedelta, timezone
import io
from typing import Any
import uuid

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.connectors import ConnectorRegistry, connector_registry
from app.core.currency import format_minor_amount, minor_to_major_decimal
from app.core.monitoring import EVENTS_INGESTED_TOTAL
from app.core.rate_limit import get_redis_client
from app.models.event import Event
from app.models.integration import Integration
from app.schemas.event import EventIngestResult, NormalizedEvent
from app.services.realtime_service import publish_org_events


def ingest_events(
    db: Session,
    *,
    organization_id: uuid.UUID,
    events: Sequence[NormalizedEvent],
    integration_id: uuid.UUID | None = None,
) -> EventIngestResult:
    """
    Idempotently persist normalized events for a single organization.

    Uses PostgreSQL ``ON CONFLICT DO NOTHING`` against
    ``uq_events_org_source_external_id`` so duplicate external IDs within a
    batch or across retries are safely ignored without rolling back the session.
    """
    if integration_id is not None:
        owned_integration = db.scalar(
            select(Integration.id).where(
                Integration.id == integration_id,
                Integration.organization_id == organization_id,
            )
        )
        if owned_integration is None:
            raise ValueError(
                "Integration does not exist or does not belong to this organization."
            )

    total_received = len(events)
    if total_received == 0:
        return EventIngestResult(
            total_received=0,
            inserted_count=0,
            skipped_count=0,
        )

    rows = [
        {
            "id": uuid.uuid4(),
            "organization_id": organization_id,
            "integration_id": integration_id,
            "source": evt.source,
            "external_id": evt.external_id,
            "event_type": evt.event_type,
            "occurred_at": evt.occurred_at,
            "amount_cents": evt.amount_minor,
            "minor_unit_exponent": evt.minor_unit_exponent,
            "currency": evt.currency,
            "actor": evt.actor,
            "is_synthetic": bool(
                evt.is_synthetic
                or evt.source == "fake"
                or evt.payload.get("synthetic") is True
                or evt.payload.get("billing_mode") == "mock_fallback"
            ),
            "payload": evt.payload,
        }
        for evt in events
    ]

    stmt = (
        pg_insert(Event)
        .values(rows)
        .on_conflict_do_nothing(
            constraint="uq_events_org_source_external_id",
        )
        .returning(Event.id)
    )
    inserted_ids = list(db.scalars(stmt).all())
    db.flush()

    inserted_count = len(inserted_ids)
    if inserted_count > 0:
        for src in {evt.source for evt in events}:
            EVENTS_INGESTED_TOTAL.labels(source=src).inc(inserted_count)
        publish_org_events(
            organization_id=organization_id,
            events=events,
            inserted_count=inserted_count,
        )
        try:
            get_redis_client().incr(f"pulseops:copilot:version:{organization_id}")
        except Exception:
            pass

    return EventIngestResult(
        total_received=total_received,
        inserted_count=inserted_count,
        skipped_count=total_received - inserted_count,
    )


def sync_connector_events(
    db: Session,
    *,
    organization_id: uuid.UUID,
    provider: str,
    credentials: dict[str, Any],
    since: datetime | None = None,
    integration_id: uuid.UUID | None = None,
    registry: ConnectorRegistry = connector_registry,
) -> EventIngestResult:
    """
    Fetch events from a registered connector and persist them idempotently
    for the target organization.
    """
    connector = registry.get(provider)
    events = connector.fetch_events(credentials=credentials, since=since)
    return ingest_events(
        db,
        organization_id=organization_id,
        events=events,
        integration_id=integration_id,
    )


def _apply_event_filters(
    stmt: Any,
    *,
    organization_id: uuid.UUID,
    source: str | None = None,
    event_type: str | None = None,
    actor: str | None = None,
    currency: str | None = None,
    include_synthetic: bool = True,
    since: datetime | None = None,
    until: datetime | None = None,
) -> Any:
    stmt = stmt.where(Event.organization_id == organization_id)
    if source is not None:
        stmt = stmt.where(Event.source == source)
    if event_type is not None:
        stmt = stmt.where(Event.event_type == event_type)
    if actor is not None:
        stmt = stmt.where(Event.actor == actor)
    if currency is not None:
        stmt = stmt.where(Event.currency == currency.strip().upper())
    if not include_synthetic:
        stmt = stmt.where(Event.is_synthetic.is_(False))
    if since is not None:
        stmt = stmt.where(Event.occurred_at >= since)
    if until is not None:
        stmt = stmt.where(Event.occurred_at <= until)
    return stmt


def list_events(
    db: Session,
    *,
    organization_id: uuid.UUID,
    source: str | None = None,
    event_type: str | None = None,
    actor: str | None = None,
    currency: str | None = None,
    include_synthetic: bool = True,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[Event]:
    """List events strictly scoped to ``organization_id`` ordered newest first."""
    stmt = _apply_event_filters(
        select(Event),
        organization_id=organization_id,
        source=source,
        event_type=event_type,
        actor=actor,
        currency=currency,
        include_synthetic=include_synthetic,
        since=since,
        until=until,
    )
    stmt = stmt.order_by(Event.occurred_at.desc(), Event.created_at.desc())
    stmt = stmt.limit(limit).offset(offset)
    return list(db.scalars(stmt).all())


def count_events(
    db: Session,
    *,
    organization_id: uuid.UUID,
    source: str | None = None,
    event_type: str | None = None,
    actor: str | None = None,
    currency: str | None = None,
    include_synthetic: bool = True,
    since: datetime | None = None,
    until: datetime | None = None,
) -> int:
    """Count matching tenant-scoped events for accurate truncation reporting."""
    stmt = _apply_event_filters(
        select(func.count(Event.id)),
        organization_id=organization_id,
        source=source,
        event_type=event_type,
        actor=actor,
        currency=currency,
        include_synthetic=include_synthetic,
        since=since,
        until=until,
    )
    return int(db.scalar(stmt) or 0)


def get_event_by_id(
    db: Session,
    *,
    organization_id: uuid.UUID,
    event_id: uuid.UUID,
) -> Event | None:
    """Fetch a single event only if it belongs to ``organization_id``."""
    return db.scalar(
        select(Event).where(
            Event.id == event_id,
            Event.organization_id == organization_id,
        )
    )


def _sanitize_csv_cell(value: str | None) -> str:
    """Neutralize spreadsheet formula prefixes (=, +, -, @, tab, CR)."""
    if value is None:
        return ""
    text = str(value)
    if text and text[0] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + text
    return text


def export_events_csv(
    db: Session,
    *,
    organization_id: uuid.UUID,
    source: str | None = None,
    event_type: str | None = None,
    days: int = 30,
    limit: int = 1000,
) -> str:
    """
    Export tenant-scoped operational events to RFC 4180 CSV format with
    formula-injection sanitization and explicit minor/major monetary precision.
    """
    since = datetime.now(timezone.utc) - timedelta(days=days)
    stmt = (
        select(Event)
        .where(
            Event.organization_id == organization_id,
            Event.occurred_at >= since,
        )
        .order_by(Event.occurred_at.desc(), Event.created_at.desc())
        .limit(limit)
    )
    if source is not None:
        stmt = stmt.where(Event.source == source)
    if event_type is not None:
        stmt = stmt.where(Event.event_type == event_type)

    rows = list(db.scalars(stmt).all())

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        [
            "id",
            "organization_id",
            "source",
            "external_id",
            "event_type",
            "occurred_at",
            "amount_minor",
            "amount_cents",
            "minor_unit_exponent",
            "amount_major",
            "formatted_amount",
            "currency",
            "actor",
            "is_synthetic",
        ]
    )
    for evt in rows:
        amt_major = ""
        amt_formatted = ""
        if evt.amount_cents is not None:
            amt_formatted = format_minor_amount(
                evt.amount_cents,
                evt.currency,
                exponent=evt.minor_unit_exponent,
            )
            if evt.currency:
                try:
                    amt_major = str(
                        minor_to_major_decimal(
                            evt.amount_cents,
                            evt.currency,
                            exponent=evt.minor_unit_exponent,
                        )
                    )
                except ValueError:
                    amt_major = ""

        writer.writerow(
            [
                str(evt.id),
                str(evt.organization_id),
                _sanitize_csv_cell(evt.source),
                _sanitize_csv_cell(evt.external_id),
                _sanitize_csv_cell(evt.event_type),
                evt.occurred_at.isoformat(),
                "" if evt.amount_cents is None else str(evt.amount_cents),
                "" if evt.amount_cents is None else str(evt.amount_cents),
                "" if evt.minor_unit_exponent is None else str(evt.minor_unit_exponent),
                _sanitize_csv_cell(amt_major),
                _sanitize_csv_cell(amt_formatted),
                _sanitize_csv_cell(evt.currency),
                _sanitize_csv_cell(evt.actor),
                "true" if evt.is_synthetic else "false",
            ]
        )
    return buf.getvalue()
