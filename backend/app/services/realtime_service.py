from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, Sequence
from datetime import datetime, timezone
import json
import logging
from typing import Any
import uuid

import redis.asyncio as aioredis

from app.config import settings
from app.core.rate_limit import get_redis_client
from app.schemas.event import NormalizedEvent

logger = logging.getLogger("app.realtime")


def get_org_events_channel(organization_id: uuid.UUID) -> str:
    """Return the strictly tenant-scoped Redis Pub/Sub channel name."""
    return f"pulseops:org:{organization_id}:events"


def publish_org_events(
    *,
    organization_id: uuid.UUID,
    events: Sequence[NormalizedEvent],
    inserted_count: int,
) -> int:
    """
    Publish an event-ingested notification to the organization's Redis Pub/Sub
    channel. Fail-soft on Redis issues so ingestion remains reliable.
    """
    if inserted_count <= 0:
        return 0

    channel = get_org_events_channel(organization_id)
    sources = sorted({evt.source for evt in events})
    event_types = sorted({evt.event_type for evt in events})
    payload: dict[str, Any] = {
        "type": "events.ingested",
        "organization_id": str(organization_id),
        "inserted_count": inserted_count,
        "sources": sources,
        "event_types": event_types,
        "published_at": datetime.now(timezone.utc).isoformat(),
    }

    try:
        client = get_redis_client()
        return int(client.publish(channel, json.dumps(payload)))
    except Exception as exc:
        logger.warning(
            "Failed to publish org events to Redis Pub/Sub: %s",
            exc,
            extra={"org_id": str(organization_id)},
        )
        return 0


def format_sse_frame(*, event: str, data: dict[str, Any], event_id: str | None = None) -> str:
    """Encode a single Server-Sent Events frame."""
    lines: list[str] = []
    if event_id:
        lines.append(f"id: {event_id}")
    lines.append(f"event: {event}")
    lines.append(f"data: {json.dumps(data)}")
    return "\n".join(lines) + "\n\n"


async def subscribe_org_events(
    organization_id: uuid.UUID,
    *,
    max_events: int | None = None,
    heartbeat_seconds: float = 15.0,
    idle_timeout_seconds: float | None = None,
) -> AsyncGenerator[str, None]:
    """
    Subscribe to Redis Pub/Sub for ``organization_id`` only and yield SSE frames.

    Cross-tenant isolation is enforced both by endpoint membership dependency and
    by subscribing strictly to ``pulseops:org:{organization_id}:events``.
    """
    channel = get_org_events_channel(organization_id)
    client = aioredis.from_url(settings.redis_url, decode_responses=True)
    pubsub = client.pubsub()
    await pubsub.subscribe(channel)

    delivered = 0
    started_at = asyncio.get_running_loop().time()
    last_heartbeat = started_at

    try:
        yield format_sse_frame(
            event="connected",
            data={
                "organization_id": str(organization_id),
                "channel": channel,
            },
        )

        while True:
            if max_events is not None and delivered >= max_events:
                break

            now = asyncio.get_running_loop().time()
            if idle_timeout_seconds is not None and (now - started_at) >= idle_timeout_seconds:
                break

            message = await pubsub.get_message(
                ignore_subscribe_messages=True,
                timeout=0.25,
            )
            if message is not None and message.get("type") == "message":
                raw_data = message.get("data")
                try:
                    parsed = json.loads(raw_data) if isinstance(raw_data, str) else raw_data
                except json.JSONDecodeError:
                    parsed = {"raw": str(raw_data)}

                # Defense-in-depth: never forward a payload carrying a different org_id
                if (
                    isinstance(parsed, dict)
                    and parsed.get("organization_id") == str(organization_id)
                ):
                    delivered += 1
                    yield format_sse_frame(
                        event="events.ingested",
                        data=parsed,
                        event_id=str(delivered),
                    )
                    last_heartbeat = asyncio.get_running_loop().time()
                continue

            now = asyncio.get_running_loop().time()
            if (now - last_heartbeat) >= heartbeat_seconds:
                yield ": keepalive\n\n"
                last_heartbeat = now

            await asyncio.sleep(0.05)
    finally:
        try:
            await pubsub.unsubscribe(channel)
            await pubsub.aclose()
        finally:
            await client.aclose()
