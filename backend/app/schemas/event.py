from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
import uuid

from pydantic import BaseModel, ConfigDict, Field, field_validator


class NormalizedEvent(BaseModel):
    """Canonical normalized event emitted by connectors prior to persistence."""

    source: str = Field(..., min_length=1, max_length=50)
    external_id: str = Field(..., min_length=1, max_length=255)
    event_type: str = Field(..., min_length=1, max_length=100)
    occurred_at: datetime
    amount_cents: int | None = None
    currency: str | None = Field(default=None, max_length=10)
    actor: str | None = Field(default=None, max_length=255)
    payload: dict[str, Any] = Field(default_factory=dict)

    @field_validator("source", "external_id", "event_type")
    @classmethod
    def _strip_required_strings(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Field cannot be empty or whitespace.")
        return cleaned

    @field_validator("occurred_at")
    @classmethod
    def _ensure_utc_datetime(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


class EventIngestResult(BaseModel):
    """Summary of an idempotent event ingestion batch."""

    total_received: int
    inserted_count: int
    skipped_count: int


class EventResponse(BaseModel):
    """Serialized normalized Event record scoped to an organization."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    integration_id: uuid.UUID | None
    source: str
    external_id: str
    event_type: str
    occurred_at: datetime
    amount_cents: int | None
    currency: str | None
    actor: str | None
    payload: dict[str, Any]
    created_at: datetime
