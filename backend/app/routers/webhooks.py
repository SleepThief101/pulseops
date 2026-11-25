from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.connectors import ConnectorError
from app.db.session import get_db
from app.schemas.event import EventIngestResult
from app.services.webhook_service import (
    WebhookDuplicateDeliveryError,
    WebhookNotConfiguredError,
    WebhookReplayError,
    WebhookSignatureError,
    process_github_webhook,
    process_razorpay_webhook,
)

router = APIRouter(prefix="/webhooks", tags=["Webhooks"])


@router.post(
    "/razorpay/{org_id}",
    response_model=EventIngestResult,
    summary="Receive signed Razorpay webhook events",
)
async def razorpay_webhook(
    org_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db),
) -> EventIngestResult:
    """
    Verify X-Razorpay-Signature, enforce timestamp replay window and
    X-Razorpay-Event-Id deduplication, and idempotently ingest events.
    """
    raw_body = await request.body()
    signature = request.headers.get("X-Razorpay-Signature")
    delivery_id = request.headers.get("X-Razorpay-Event-Id")
    header_ts = request.headers.get("X-Webhook-Timestamp")

    try:
        return process_razorpay_webhook(
            db,
            organization_id=org_id,
            raw_body=raw_body,
            signature=signature,
            delivery_id=delivery_id,
            header_timestamp=header_ts,
        )
    except WebhookNotConfiguredError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Webhook endpoint not found.",
        ) from exc
    except (WebhookSignatureError, WebhookReplayError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        ) from exc
    except WebhookDuplicateDeliveryError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except (json.JSONDecodeError, ConnectorError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Invalid webhook payload: {exc}",
        ) from exc


@router.post(
    "/github/{org_id}",
    response_model=EventIngestResult,
    summary="Receive signed GitHub webhook events",
)
async def github_webhook(
    org_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db),
) -> EventIngestResult:
    """
    Verify X-Hub-Signature-256, enforce X-GitHub-Delivery deduplication and
    optional X-Webhook-Timestamp replay protection, and ingest GitHub events.
    """
    raw_body = await request.body()
    signature = request.headers.get("X-Hub-Signature-256")
    delivery_id = request.headers.get("X-GitHub-Delivery")
    header_ts = request.headers.get("X-Webhook-Timestamp")

    try:
        return process_github_webhook(
            db,
            organization_id=org_id,
            raw_body=raw_body,
            signature=signature,
            delivery_id=delivery_id,
            header_timestamp=header_ts,
        )
    except WebhookNotConfiguredError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Webhook endpoint not found.",
        ) from exc
    except (WebhookSignatureError, WebhookReplayError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        ) from exc
    except WebhookDuplicateDeliveryError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except (json.JSONDecodeError, ConnectorError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Invalid webhook payload: {exc}",
        ) from exc
