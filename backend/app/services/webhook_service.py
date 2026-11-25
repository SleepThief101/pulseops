from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import hmac
import json
from typing import Any
import uuid

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.config import settings
from app.connectors import GitHubConnector, RazorpayConnector
from app.core.security import decrypt_credentials
from app.models.integration import Integration, IntegrationStatus
from app.models.webhook_delivery import WebhookDelivery
from app.schemas.event import EventIngestResult
from app.services.event_service import ingest_events


class WebhookNotConfiguredError(Exception):
    """Raised when an organization has no matching active webhook integration."""


class WebhookSignatureError(Exception):
    """Raised when the webhook HMAC signature header is missing or invalid."""


class WebhookReplayError(Exception):
    """Raised when a webhook timestamp is missing, expired, or outside replay window."""


class WebhookDuplicateDeliveryError(Exception):
    """Raised when a webhook delivery ID has already been processed."""


def _find_webhook_integration(
    db: Session,
    *,
    organization_id: uuid.UUID,
    provider: str,
) -> tuple[Integration, str]:
    """
    Find an active integration for ``organization_id`` and ``provider`` that has
    a non-empty ``webhook_secret`` in its encrypted credentials.
    """
    integrations = list(
        db.scalars(
            select(Integration).where(
                Integration.organization_id == organization_id,
                Integration.provider == provider,
                Integration.status == IntegrationStatus.ACTIVE.value,
            )
        ).all()
    )

    for integ in integrations:
        creds = json.loads(decrypt_credentials(integ.credentials_encrypted))
        secret = str(creds.get("webhook_secret") or "").strip()
        if secret:
            return integ, secret

    raise WebhookNotConfiguredError(
        f"No active {provider} webhook configuration found for organization."
    )


def verify_razorpay_signature(
    *,
    raw_body: bytes,
    signature: str | None,
    secret: str,
) -> None:
    """Verify Razorpay X-Razorpay-Signature (HMAC-SHA256 hex digest)."""
    if not signature or not signature.strip():
        raise WebhookSignatureError("Missing X-Razorpay-Signature header.")
    expected = hmac.new(
        secret.encode("utf-8"),
        raw_body,
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(expected, signature.strip()):
        raise WebhookSignatureError("Invalid Razorpay webhook signature.")


def verify_github_signature(
    *,
    raw_body: bytes,
    signature: str | None,
    secret: str,
) -> None:
    """Verify GitHub X-Hub-Signature-256 ('sha256=' + HMAC-SHA256 hex digest)."""
    if not signature or not signature.strip():
        raise WebhookSignatureError("Missing X-Hub-Signature-256 header.")
    expected = (
        "sha256="
        + hmac.new(
            secret.encode("utf-8"),
            raw_body,
            hashlib.sha256,
        ).hexdigest()
    )
    if not hmac.compare_digest(expected, signature.strip()):
        raise WebhookSignatureError("Invalid GitHub webhook signature.")


def verify_webhook_timestamp(
    *,
    raw_timestamp: int | float | str | None,
    required: bool = False,
) -> None:
    """
    Enforce anti-replay timestamp tolerance on webhook payloads/headers.
    Rejects stale timestamps older than ``webhook_replay_tolerance_seconds``
    and future timestamps beyond ``webhook_future_skew_seconds``.
    """
    if raw_timestamp is None or str(raw_timestamp).strip() == "":
        if required:
            raise WebhookReplayError("Webhook timestamp is required.")
        return

    try:
        if isinstance(raw_timestamp, (int, float)) or str(raw_timestamp).strip().isdigit():
            ts_epoch = float(raw_timestamp)
        else:
            iso_str = str(raw_timestamp).strip()
            if iso_str.endswith("Z"):
                iso_str = iso_str[:-1] + "+00:00"
            dt = datetime.fromisoformat(iso_str)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            ts_epoch = dt.timestamp()
    except (ValueError, TypeError) as exc:
        raise WebhookReplayError("Malformed webhook timestamp.") from exc

    now_epoch = datetime.now(timezone.utc).timestamp()
    age_seconds = now_epoch - ts_epoch
    if age_seconds > settings.webhook_replay_tolerance_seconds:
        raise WebhookReplayError("Webhook timestamp expired outside replay window.")
    if (-age_seconds) > settings.webhook_future_skew_seconds:
        raise WebhookReplayError("Webhook timestamp is too far in the future.")


def record_unique_webhook_delivery(
    db: Session,
    *,
    organization_id: uuid.UUID,
    provider: str,
    delivery_id: str | None,
    raw_body: bytes,
) -> None:
    """
    Atomically record ``delivery_id`` for ``(organization_id, provider)``.
    Raises ``WebhookDuplicateDeliveryError`` if the delivery ID was already seen.
    Must only be invoked AFTER HMAC signature verification succeeds.
    """
    cleaned_id = (delivery_id or "").strip()
    if not cleaned_id:
        return

    payload_digest = hashlib.sha256(raw_body).hexdigest()
    stmt = (
        pg_insert(WebhookDelivery)
        .values(
            id=uuid.uuid4(),
            organization_id=organization_id,
            provider=provider,
            delivery_id=cleaned_id,
            payload_sha256=payload_digest,
        )
        .on_conflict_do_nothing(
            constraint="uq_webhook_deliveries_org_provider_delivery"
        )
        .returning(WebhookDelivery.id)
    )
    inserted = db.scalar(stmt)
    if inserted is None:
        raise WebhookDuplicateDeliveryError(
            f"Duplicate {provider} webhook delivery '{cleaned_id}' rejected."
        )


def process_razorpay_webhook(
    db: Session,
    *,
    organization_id: uuid.UUID,
    raw_body: bytes,
    signature: str | None,
    delivery_id: str | None = None,
    header_timestamp: str | None = None,
) -> EventIngestResult:
    """
    Verify signature, enforce replay window & delivery ID deduplication,
    normalize Razorpay webhook event, and persist idempotently.
    """
    integration, secret = _find_webhook_integration(
        db, organization_id=organization_id, provider="razorpay"
    )
    verify_razorpay_signature(raw_body=raw_body, signature=signature, secret=secret)

    payload: dict[str, Any] = json.loads(raw_body.decode("utf-8"))
    if header_timestamp is not None:
        verify_webhook_timestamp(raw_timestamp=header_timestamp, required=True)
    else:
        envelope_ts = payload.get("created_at")
        verify_webhook_timestamp(raw_timestamp=envelope_ts, required=True)

    record_unique_webhook_delivery(
        db,
        organization_id=organization_id,
        provider="razorpay",
        delivery_id=delivery_id,
        raw_body=raw_body,
    )

    normalized = RazorpayConnector().normalize(payload)
    result = ingest_events(
        db,
        organization_id=organization_id,
        events=[normalized],
        integration_id=integration.id,
    )
    db.commit()
    return result


def process_github_webhook(
    db: Session,
    *,
    organization_id: uuid.UUID,
    raw_body: bytes,
    signature: str | None,
    delivery_id: str | None = None,
    header_timestamp: str | None = None,
) -> EventIngestResult:
    """
    Verify signature, enforce optional timestamp window & X-GitHub-Delivery
    deduplication, normalize GitHub webhook event, and persist idempotently.
    """
    integration, secret = _find_webhook_integration(
        db, organization_id=organization_id, provider="github"
    )
    verify_github_signature(raw_body=raw_body, signature=signature, secret=secret)

    if header_timestamp is not None:
        verify_webhook_timestamp(raw_timestamp=header_timestamp, required=True)

    payload: dict[str, Any] = json.loads(raw_body.decode("utf-8"))
    record_unique_webhook_delivery(
        db,
        organization_id=organization_id,
        provider="github",
        delivery_id=delivery_id,
        raw_body=raw_body,
    )

    normalized = GitHubConnector().normalize(payload)
    result = ingest_events(
        db,
        organization_id=organization_id,
        events=[normalized],
        integration_id=integration.id,
    )
    db.commit()
    return result
