from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from app.config import settings
from app.connectors.base import BaseConnector, ConnectorAuthError, ConnectorError
from app.schemas.event import NormalizedEvent

def _mock_base_time() -> datetime:
    return datetime.now(timezone.utc).replace(
        hour=9, minute=0, second=0, microsecond=0
    ) - timedelta(days=4)

_MOCK_RAZORPAY_EVENTS: list[dict[str, Any]] = [
    {
        "external_id": "rzp_mock_sub_001",
        "event_type": "subscription.charged",
        "offset_hours": 0,
        "amount_cents": 9900,
        "currency": "USD",
        "actor": "cust_mock_alpha",
        "payload": {"plan_id": "plan_growth", "subscription_id": "sub_mock_001"},
    },
    {
        "external_id": "rzp_mock_sub_002",
        "event_type": "subscription.charged",
        "offset_hours": 12,
        "amount_cents": 29900,
        "currency": "USD",
        "actor": "cust_mock_beta",
        "payload": {"plan_id": "plan_scale", "subscription_id": "sub_mock_002"},
    },
    {
        "external_id": "rzp_mock_pay_003",
        "event_type": "payment.captured",
        "offset_hours": 36,
        "amount_cents": 4900,
        "currency": "USD",
        "actor": "cust_mock_gamma",
        "payload": {"method": "card", "order_id": "order_mock_003"},
    },
    {
        "external_id": "rzp_mock_ref_004",
        "event_type": "payment.refunded",
        "offset_hours": 60,
        "amount_cents": 4900,
        "currency": "USD",
        "actor": "cust_mock_gamma",
        "payload": {"reason": "requested_by_customer", "payment_id": "rzp_mock_pay_003"},
    },
    {
        "external_id": "rzp_mock_sub_cancel_005",
        "event_type": "subscription.cancelled",
        "offset_hours": 72,
        "amount_cents": 9900,
        "currency": "USD",
        "actor": "cust_mock_delta",
        "payload": {"subscription_id": "sub_mock_004", "cancelled_at_cycle_end": False},
    },
]


class RazorpayConnector(BaseConnector):
    """
    Razorpay connector supporting Test Mode API syncs and deterministic
    conditional mock-billing fallback when Test Mode credentials are unavailable.

    Live Razorpay keys (``rzp_live_...``) are strictly rejected.
    """

    provider = "razorpay"
    base_url = "https://api.razorpay.com/v1"

    def __init__(self, http_client: httpx.Client | None = None) -> None:
        self._http_client = http_client

    def validate_credentials(self, credentials: dict[str, Any]) -> bool:
        """
        Validate Razorpay credentials.
        - Rejects any live key (`rzp_live_...`).
        - Accepts `{"mode": "mock"}` for synthetic billing mode.
        - Accepts `{"key_id": "rzp_test_...", "key_secret": "..."}` for Test Mode.
        """
        if not isinstance(credentials, dict):
            raise ConnectorAuthError("Razorpay credentials must be a JSON object.")

        key_id = str(credentials.get("key_id") or "").strip()
        key_secret = str(credentials.get("key_secret") or "").strip()
        mode = str(credentials.get("mode") or "").strip().lower()

        if key_id.startswith("rzp_live_"):
            raise ConnectorAuthError(
                "Live Razorpay keys are strictly forbidden. Use Test Mode (rzp_test_*) or mock mode."
            )

        if mode == "mock":
            return True

        if key_id and key_secret:
            if not key_id.startswith("rzp_test_"):
                raise ConnectorAuthError(
                    "Razorpay key_id must start with 'rzp_test_' in Test Mode."
                )
            return True

        if settings.razorpay_mock_fallback and not key_id and not key_secret:
            return True

        raise ConnectorAuthError(
            "Provide Razorpay Test Mode credentials (key_id starting with 'rzp_test_' "
            "and key_secret) or set mode='mock'."
        )

    def fetch_events(
        self,
        credentials: dict[str, Any],
        since: datetime | None = None,
    ) -> list[NormalizedEvent]:
        """
        Fetch payments from Razorpay Test Mode API, or emit deterministic
        mock-billing events when running in mock mode or conditional fallback.
        """
        self.validate_credentials(credentials)

        mode = str(credentials.get("mode") or "").strip().lower()
        key_id = str(credentials.get("key_id") or "").strip()
        key_secret = str(credentials.get("key_secret") or "").strip()

        since_utc: datetime | None = None
        if since is not None:
            since_utc = (
                since.replace(tzinfo=timezone.utc)
                if since.tzinfo is None
                else since.astimezone(timezone.utc)
            )

        if mode == "mock" or (not key_id and settings.razorpay_mock_fallback):
            return self._fetch_mock_events(credentials, since_utc)

        try:
            raw_payments = self._fetch_razorpay_payments(
                key_id=key_id,
                key_secret=key_secret,
                since=since_utc,
            )
            events = [self.normalize(item) for item in raw_payments]
            if since_utc is not None:
                events = [e for e in events if e.occurred_at >= since_utc]
            return events
        except (httpx.HTTPError, ConnectorError) as exc:
            if settings.razorpay_mock_fallback and credentials.get(
                "allow_mock_fallback", False
            ):
                return self._fetch_mock_events(credentials, since_utc)
            raise ConnectorError(f"Razorpay API sync failed: {exc}") from exc

    def _fetch_mock_events(
        self,
        credentials: dict[str, Any],
        since_utc: datetime | None,
    ) -> list[NormalizedEvent]:
        raw_items = credentials.get("mock_events", _MOCK_RAZORPAY_EVENTS)
        results: list[NormalizedEvent] = []
        for item in raw_items:
            if "occurred_at" in item and item["occurred_at"] is not None:
                raw_dt = item["occurred_at"]
                dt = (
                    datetime.fromisoformat(raw_dt)
                    if isinstance(raw_dt, str)
                    else raw_dt
                )
            else:
                dt = _mock_base_time() + timedelta(hours=item.get("offset_hours", 0))

            evt = NormalizedEvent(
                source=self.provider,
                external_id=str(item["external_id"]),
                event_type=str(item["event_type"]),
                occurred_at=dt,
                amount_cents=item.get("amount_cents"),
                currency=item.get("currency", "USD"),
                actor=item.get("actor"),
                payload={
                    **dict(item.get("payload") or {}),
                    "billing_mode": "mock_fallback",
                },
            )
            if since_utc is None or evt.occurred_at >= since_utc:
                results.append(evt)
        return results

    def _fetch_razorpay_payments(
        self,
        *,
        key_id: str,
        key_secret: str,
        since: datetime | None,
        page_size: int = 50,
        max_pages: int = 10,
    ) -> list[dict[str, Any]]:
        collected: list[dict[str, Any]] = []
        for page_idx in range(max_pages):
            params: dict[str, Any] = {"count": page_size, "skip": page_idx * page_size}
            if since is not None:
                params["from"] = int(since.timestamp())

            if self._http_client is not None:
                resp = self._http_client.get(
                    f"{self.base_url}/payments",
                    auth=(key_id, key_secret),
                    params=params,
                )
            else:
                with httpx.Client(timeout=10.0) as client:
                    resp = client.get(
                        f"{self.base_url}/payments",
                        auth=(key_id, key_secret),
                        params=params,
                    )

            if resp.status_code == 401:
                raise ConnectorAuthError("Razorpay API rejected Test Mode credentials.")
            resp.raise_for_status()
            data = resp.json()
            items = list(data.get("items") or [])
            collected.extend(items)
            if len(items) < page_size:
                break
        return collected

    def normalize(self, raw_event: dict[str, Any]) -> NormalizedEvent:
        """
        Normalize a Razorpay API object or webhook envelope into a NormalizedEvent.
        """
        # Handle Razorpay webhook envelope {"event": "payment.captured", "payload": {"payment": {"entity": ...}}}
        if "event" in raw_event and isinstance(raw_event.get("payload"), dict):
            event_name = str(raw_event["event"])
            payload_obj = raw_event["payload"]
            entity: dict[str, Any] = {}
            for key in ("subscription", "payment", "refund"):
                if key in payload_obj and isinstance(payload_obj[key], dict):
                    entity = payload_obj[key].get("entity") or payload_obj[key]
                    break

            external_id = str(
                raw_event.get("id")
                or entity.get("id")
                or f"rzp_wh_{event_name}_{raw_event.get('created_at', 0)}"
            )
            created_epoch = entity.get("created_at") or raw_event.get("created_at")
            occurred_at = (
                datetime.fromtimestamp(int(created_epoch), tz=timezone.utc)
                if created_epoch is not None
                else datetime.now(timezone.utc)
            )
            amount_raw = entity.get("amount")
            amount_cents = int(amount_raw) if amount_raw is not None else None
            currency = entity.get("currency")
            actor = entity.get("email") or entity.get("customer_id") or entity.get("contact")

            return NormalizedEvent(
                source=self.provider,
                external_id=external_id,
                event_type=event_name,
                occurred_at=occurred_at,
                amount_cents=amount_cents,
                currency=str(currency).upper() if currency else None,
                actor=str(actor) if actor else None,
                payload={
                    "entity": entity.get("entity"),
                    "status": entity.get("status"),
                    "method": entity.get("method"),
                    "order_id": entity.get("order_id"),
                },
            )

        # Handle direct Razorpay API payment/subscription entity
        entity_id = str(raw_event["id"])
        entity_kind = str(raw_event.get("entity") or "payment")
        status = str(raw_event.get("status") or "captured")

        if entity_kind == "subscription":
            event_type = (
                "subscription.cancelled"
                if status in {"cancelled", "halted", "expired"}
                else "subscription.charged"
            )
        elif entity_kind == "refund":
            event_type = "payment.refunded"
        else:
            event_type = (
                "payment.refunded"
                if status == "refunded"
                else (
                    "payment.failed"
                    if status == "failed"
                    else "payment.captured"
                )
            )

        created_epoch = raw_event.get("created_at")
        occurred_at = (
            datetime.fromtimestamp(int(created_epoch), tz=timezone.utc)
            if created_epoch is not None
            else datetime.now(timezone.utc)
        )
        amount_raw = raw_event.get("amount")
        currency = raw_event.get("currency")
        actor = raw_event.get("email") or raw_event.get("customer_id")

        return NormalizedEvent(
            source=self.provider,
            external_id=entity_id,
            event_type=event_type,
            occurred_at=occurred_at,
            amount_cents=int(amount_raw) if amount_raw is not None else None,
            currency=str(currency).upper() if currency else None,
            actor=str(actor) if actor else None,
            payload={
                "entity": entity_kind,
                "status": status,
                "method": raw_event.get("method"),
                "order_id": raw_event.get("order_id"),
            },
        )
