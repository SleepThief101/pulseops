from __future__ import annotations

import csv
from datetime import datetime, timezone
import hashlib
import io
import json
from typing import Any

from app.connectors.base import BaseConnector, ConnectorAuthError, ConnectorError
from app.schemas.event import NormalizedEvent

MAX_CSV_BYTES = 2 * 1024 * 1024  # 2 MB
MAX_CSV_ROWS = 10_000


def _sanitize_cell(value: str | None) -> str | None:
    """Strip leading formula-injection triggers if present in spreadsheet exports."""
    if value is None:
        return None
    if value.startswith(("\t", "\r")):
        return "'" + value
    cleaned = value.strip()
    if cleaned.startswith(("=", "+", "-", "@")) and not cleaned[1:].replace(".", "", 1).isdigit():
        return "'" + cleaned
    return cleaned


class CsvConnector(BaseConnector):
    """
    CSV import connector supporting billing and engineering operational CSV exports.
    Produces deterministic external IDs when none are supplied so re-imports are idempotent.
    """

    provider = "csv"

    def validate_credentials(self, credentials: dict[str, Any]) -> bool:
        if not isinstance(credentials, dict):
            raise ConnectorAuthError("CSV configuration must be a JSON object.")
        return True

    def fetch_events(
        self,
        credentials: dict[str, Any],
        since: datetime | None = None,
    ) -> list[NormalizedEvent]:
        self.validate_credentials(credentials)
        csv_text = credentials.get("csv_text")
        if not csv_text or not isinstance(csv_text, str):
            return []
        return self.parse_csv_text(csv_text, since=since)

    def parse_csv_text(
        self,
        csv_text: str,
        *,
        since: datetime | None = None,
    ) -> list[NormalizedEvent]:
        csv_text = csv_text.lstrip("\ufeff")
        if len(csv_text.encode("utf-8")) > MAX_CSV_BYTES:
            raise ConnectorError(f"CSV file exceeds maximum allowed size ({MAX_CSV_BYTES} bytes).")

        since_utc: datetime | None = None
        if since is not None:
            since_utc = (
                since.replace(tzinfo=timezone.utc)
                if since.tzinfo is None
                else since.astimezone(timezone.utc)
            )

        reader = csv.DictReader(io.StringIO(csv_text))
        if not reader.fieldnames:
            raise ConnectorError("CSV header row is missing or empty.")

        required_cols = {"event_type", "occurred_at"}
        header_set = {col.strip().lower() for col in reader.fieldnames if col}
        missing = required_cols - header_set
        if missing:
            raise ConnectorError(
                f"CSV is missing required columns: {', '.join(sorted(missing))}."
            )

        events: list[NormalizedEvent] = []
        for idx, row in enumerate(reader, start=1):
            if idx > MAX_CSV_ROWS:
                raise ConnectorError(f"CSV exceeds maximum row limit ({MAX_CSV_ROWS}).")

            if not any(v is not None and str(v).strip() for v in row.values()):
                continue

            normalized_row = {
                (k.strip().lower() if k else ""): (v.strip() if isinstance(v, str) else v)
                for k, v in row.items()
            }
            evt = self.normalize(normalized_row)
            if since_utc is None or evt.occurred_at >= since_utc:
                events.append(evt)

        return events

    def normalize(self, raw_event: dict[str, Any]) -> NormalizedEvent:
        event_type = str(raw_event.get("event_type") or "").strip()
        occurred_raw = str(raw_event.get("occurred_at") or "").strip()

        if not event_type or not occurred_raw:
            raise ConnectorError("CSV row must include non-empty 'event_type' and 'occurred_at'.")

        if occurred_raw.endswith("Z"):
            occurred_raw = occurred_raw[:-1] + "+00:00"
        try:
            occurred_at = datetime.fromisoformat(occurred_raw)
        except ValueError as exc:
            raise ConnectorError(f"Invalid ISO timestamp in CSV: {occurred_raw!r}") from exc

        amount_raw = raw_event.get("amount_cents")
        amount_cents: int | None = None
        if amount_raw not in (None, ""):
            try:
                amount_cents = int(amount_raw)
            except ValueError as exc:
                raise ConnectorError(f"Invalid integer amount_cents: {amount_raw!r}") from exc

        currency = _sanitize_cell(raw_event.get("currency"))
        actor = _sanitize_cell(raw_event.get("actor"))

        ext_id = str(raw_event.get("external_id") or "").strip()
        if not ext_id:
            canonical = json.dumps(
                {
                    "event_type": event_type,
                    "occurred_at": occurred_at.isoformat(),
                    "amount_cents": amount_cents,
                    "currency": currency,
                    "actor": actor,
                },
                sort_keys=True,
            )
            ext_id = "csv_" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:24]

        known_keys = {"external_id", "event_type", "occurred_at", "amount_cents", "currency", "actor"}
        extra_payload = {
            k: _sanitize_cell(str(v))
            for k, v in raw_event.items()
            if k and k not in known_keys and v not in (None, "")
        }

        return NormalizedEvent(
            source=self.provider,
            external_id=ext_id,
            event_type=event_type,
            occurred_at=occurred_at,
            amount_cents=amount_cents,
            currency=currency.upper() if currency else None,
            actor=actor,
            payload=extra_payload,
        )
