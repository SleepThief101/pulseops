from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from app.connectors.base import BaseConnector, ConnectorAuthError
from app.core.currency import get_minor_unit_exponent, normalize_currency
from app.schemas.event import NormalizedEvent

_BASE_TIMESTAMP = datetime(2026, 11, 1, 12, 0, 0, tzinfo=timezone.utc)

_DEFAULT_SYNTHETIC_EVENTS: list[dict[str, Any]] = [
    {
        "external_id": "fake_evt_sub_001",
        "event_type": "subscription.charged",
        "offset_hours": 0,
        "amount_minor": 4900,
        "currency": "USD",
        "actor": "cust_acme_01",
        "payload": {"plan": "pro_monthly", "customer": "Acme Corp", "synthetic": True},
    },
    {
        "external_id": "fake_evt_sub_002",
        "event_type": "subscription.charged",
        "offset_hours": 24,
        "amount_minor": 19900,
        "currency": "USD",
        "actor": "cust_globex_02",
        "payload": {"plan": "team_monthly", "customer": "Globex", "synthetic": True},
    },
    {
        "external_id": "fake_evt_pr_001",
        "event_type": "pr.merged",
        "offset_hours": 36,
        "amount_minor": None,
        "currency": None,
        "actor": "dev_alice",
        "payload": {
            "repo": "pulseops/app",
            "pr_number": 42,
            "cycle_time_hours": 4.5,
            "synthetic": True,
        },
    },
    {
        "external_id": "fake_evt_issue_001",
        "event_type": "issue.closed",
        "offset_hours": 48,
        "amount_minor": None,
        "currency": None,
        "actor": "dev_bob",
        "payload": {
            "repo": "pulseops/app",
            "issue_number": 108,
            "cycle_time_hours": 12.0,
            "synthetic": True,
        },
    },
]


class FakeConnector(BaseConnector):
    """
    Deterministic synthetic connector used for testing, local development,
    and demonstrations without external API credentials.
    """

    provider = "fake"

    def validate_credentials(self, credentials: dict[str, Any]) -> bool:
        """
        Validate synthetic connector configuration.
        Rejects non-dict credentials or explicit ``{"fail_auth": True}``.
        """
        if not isinstance(credentials, dict):
            raise ConnectorAuthError("Credentials must be a JSON object.")
        if credentials.get("fail_auth") is True:
            raise ConnectorAuthError("Fake connector credentials rejected.")
        return True

    def fetch_events(
        self,
        credentials: dict[str, Any],
        since: datetime | None = None,
    ) -> list[NormalizedEvent]:
        """Return deterministic synthetic events filtered by optional ``since``."""
        self.validate_credentials(credentials)

        since_utc: datetime | None = None
        if since is not None:
            since_utc = (
                since.replace(tzinfo=timezone.utc)
                if since.tzinfo is None
                else since.astimezone(timezone.utc)
            )

        raw_items = credentials.get("events", _DEFAULT_SYNTHETIC_EVENTS)
        normalized: list[NormalizedEvent] = []

        for item in raw_items:
            event = self.normalize(item)
            if since_utc is None or event.occurred_at >= since_utc:
                normalized.append(event)

        return normalized

    def normalize(self, raw_event: dict[str, Any]) -> NormalizedEvent:
        """Normalize a synthetic event dictionary into a NormalizedEvent."""
        if "occurred_at" in raw_event and raw_event["occurred_at"] is not None:
            raw_dt = raw_event["occurred_at"]
            occurred_at = (
                datetime.fromisoformat(raw_dt)
                if isinstance(raw_dt, str)
                else raw_dt
            )
        else:
            offset_hours = raw_event.get("offset_hours", 0)
            occurred_at = _BASE_TIMESTAMP + timedelta(hours=offset_hours)

        currency = normalize_currency(raw_event.get("currency"), allow_none=True)
        amount_raw = raw_event.get("amount_minor")
        if amount_raw is None:
            amount_raw = raw_event.get("amount_cents")
        amount_minor = int(amount_raw) if amount_raw is not None else None
        exponent = (
            get_minor_unit_exponent(currency)
            if amount_minor is not None and currency is not None
            else None
        )

        return NormalizedEvent(
            source=self.provider,
            external_id=str(raw_event["external_id"]),
            event_type=str(raw_event["event_type"]),
            occurred_at=occurred_at,
            amount_minor=amount_minor,
            minor_unit_exponent=exponent,
            currency=currency,
            actor=raw_event.get("actor"),
            is_synthetic=True,
            payload=dict(raw_event.get("payload") or {}),
        )
