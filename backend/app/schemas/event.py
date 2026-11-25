from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
import uuid

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.currency import (
    InvalidCurrencyError,
    format_minor_amount,
    get_minor_unit_exponent,
    get_minor_unit_name,
    minor_to_major_decimal,
    normalize_currency,
)


class NormalizedEvent(BaseModel):
    """Canonical normalized event emitted by connectors prior to persistence."""

    source: str = Field(..., min_length=1, max_length=50)
    external_id: str = Field(..., min_length=1, max_length=255)
    event_type: str = Field(..., min_length=1, max_length=100)
    occurred_at: datetime
    amount_minor: int | None = None
    amount_cents: int | None = None
    minor_unit_exponent: int | None = Field(default=None, ge=0, le=4)
    currency: str | None = Field(default=None, max_length=10)
    actor: str | None = Field(default=None, max_length=255)
    is_synthetic: bool = False
    payload: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _sync_minor_and_cents(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        copied = dict(data)
        minor = copied.get("amount_minor")
        cents = copied.get("amount_cents")
        if minor is None and cents is not None:
            copied["amount_minor"] = cents
        elif cents is None and minor is not None:
            copied["amount_cents"] = minor
        elif minor is not None and cents is not None and int(minor) != int(cents):
            raise ValueError("Conflicting 'amount_minor' and 'amount_cents' values supplied.")
        return copied

    @field_validator("source", "external_id", "event_type")
    @classmethod
    def _strip_required_strings(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Field cannot be empty or whitespace.")
        return cleaned

    @field_validator("currency")
    @classmethod
    def _validate_currency(cls, value: str | None) -> str | None:
        return normalize_currency(value, allow_none=True)

    @field_validator("occurred_at")
    @classmethod
    def _ensure_utc_datetime(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def _populate_precision_and_synthetic(self) -> "NormalizedEvent":
        if self.amount_minor is not None and self.currency is not None and self.minor_unit_exponent is None:
            self.minor_unit_exponent = get_minor_unit_exponent(self.currency)
        if (
            self.source == "fake"
            or bool(self.payload.get("synthetic"))
            or self.payload.get("billing_mode") == "mock_fallback"
        ):
            self.is_synthetic = True
        return self


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
    amount_minor: int | None = None
    amount_cents: int | None = None
    minor_unit_exponent: int | None = None
    minor_unit_name: str | None = None
    amount_major: str | None = None
    formatted_amount: str | None = None
    currency: str | None
    actor: str | None
    is_synthetic: bool = False
    payload: dict[str, Any]
    created_at: datetime

    @model_validator(mode="after")
    def _enrich_monetary_fields(self) -> "EventResponse":
        raw_minor = self.amount_minor if self.amount_minor is not None else self.amount_cents
        self.amount_minor = raw_minor
        self.amount_cents = raw_minor

        if self.currency is not None:
            cleaned = self.currency.strip().upper()
            self.currency = cleaned or None

        if raw_minor is not None:
            exp = self.minor_unit_exponent
            if exp is None and self.currency is not None:
                try:
                    exp = get_minor_unit_exponent(self.currency)
                except InvalidCurrencyError:
                    exp = None
            self.minor_unit_exponent = exp
            self.minor_unit_name = get_minor_unit_name(self.currency)
            if exp is not None and self.currency is not None:
                try:
                    self.amount_major = str(
                        minor_to_major_decimal(raw_minor, self.currency, exponent=exp)
                    )
                except InvalidCurrencyError:
                    self.amount_major = None
            self.formatted_amount = format_minor_amount(
                raw_minor,
                self.currency,
                exponent=exp,
            )

        return self
