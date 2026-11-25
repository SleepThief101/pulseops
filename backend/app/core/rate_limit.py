from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging
import uuid

from fastapi import Depends, HTTPException, Request, status
import redis
from sqlalchemy.orm import Session

from app.config import settings
from app.core.auth import get_current_membership
from app.core.monitoring import RATE_LIMIT_HITS_TOTAL
from app.db.session import get_db
from app.models.membership import Membership
from app.models.user import User

logger = logging.getLogger("app.rate_limit")

_REDIS_CLIENTS: dict[str, redis.Redis] = {}


def get_redis_client() -> redis.Redis:
    """Return a pooled synchronous Redis client for the configured REDIS_URL."""
    url = settings.redis_url
    client = _REDIS_CLIENTS.get(url)
    if client is None:
        client = redis.Redis.from_url(
            url,
            decode_responses=True,
            socket_connect_timeout=2.0,
            socket_timeout=2.0,
        )
        _REDIS_CLIENTS[url] = client
    return client


def check_fixed_window_rate_limit(
    *,
    scope: str,
    identifier: str,
    limit: int,
    window_seconds: int,
) -> tuple[bool, int, int]:
    """
    Atomically increment a Redis fixed-window counter and evaluate quota.

    Returns ``(allowed, remaining, retry_after_seconds)``.
    """
    if not settings.rate_limit_enabled or limit <= 0:
        return True, max(0, limit), 0

    key = f"pulseops:ratelimit:{scope}:{identifier}"
    try:
        client = get_redis_client()
        pipe = client.pipeline()
        pipe.incr(key)
        pipe.ttl(key)
        count, ttl = pipe.execute()

        if int(count) == 1 or int(ttl) < 0:
            client.expire(key, window_seconds)
            ttl = window_seconds

        retry_after = max(1, int(ttl) if int(ttl) > 0 else window_seconds)
        remaining = max(0, limit - int(count))
        if int(count) > limit:
            RATE_LIMIT_HITS_TOTAL.labels(scope=scope).inc()
            return False, 0, retry_after
        return True, remaining, 0
    except Exception as exc:
        logger.warning("Rate-limit Redis check bypassed due to error: %s", exc)
        return True, max(0, limit), 0


def _raise_429(*, detail: str, retry_after: int, limit: int) -> None:
    raise HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail=detail,
        headers={
            "Retry-After": str(max(1, retry_after)),
            "X-RateLimit-Limit": str(limit),
            "X-RateLimit-Remaining": "0",
        },
    )


def _client_ip(request: Request) -> str:
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def rate_limit_auth(request: Request) -> None:
    """Rate-limit unauthenticated /auth endpoints by client IP."""
    limit = settings.rate_limit_auth_max_requests
    window = settings.rate_limit_window_seconds
    allowed, _, retry_after = check_fixed_window_rate_limit(
        scope="auth",
        identifier=f"{request.url.path}:{_client_ip(request)}",
        limit=limit,
        window_seconds=window,
    )
    if not allowed:
        _raise_429(
            detail="Too many authentication requests. Please retry later.",
            retry_after=retry_after,
            limit=limit,
        )


def rate_limit_copilot(
    org_id: uuid.UUID,
    membership: Membership = Depends(get_current_membership),
    db: Session = Depends(get_db),
) -> Membership:
    """
    Enforce tenant-aware and user-aware Redis rate limiting on Copilot chat,
    plus the S38 daily request quota for the read-only synthetic demo account.
    """
    limit = settings.rate_limit_copilot_max_requests
    window = settings.rate_limit_window_seconds
    allowed, _, retry_after = check_fixed_window_rate_limit(
        scope="copilot",
        identifier=f"{org_id}:{membership.user_id}",
        limit=limit,
        window_seconds=window,
    )
    if not allowed:
        _raise_429(
            detail="Copilot rate limit exceeded for this user and organization.",
            retry_after=retry_after,
            limit=limit,
        )

    user = db.get(User, membership.user_id)
    if user is not None:
        enforce_demo_copilot_daily_limit(user_email=user.email, user_id=user.id)

    return membership


def rate_limit_org_write(
    org_id: uuid.UUID,
    membership: Membership = Depends(get_current_membership),
) -> Membership:
    """Enforce tenant-aware and user-aware rate limiting on org write/sync endpoints."""
    limit = settings.rate_limit_org_write_max_requests
    window = settings.rate_limit_window_seconds
    allowed, _, retry_after = check_fixed_window_rate_limit(
        scope="org_write",
        identifier=f"{org_id}:{membership.user_id}",
        limit=limit,
        window_seconds=window,
    )
    if not allowed:
        _raise_429(
            detail="Organization rate limit exceeded. Please retry later.",
            retry_after=retry_after,
            limit=limit,
        )
    return membership


def enforce_demo_copilot_daily_limit(
    *,
    user_email: str,
    user_id: uuid.UUID,
) -> None:
    """
    S38: Restrict the synthetic read-only demo account to
    ``settings.demo_copilot_daily_limit`` (default 5) Copilot requests per UTC day.
    """
    demo_email = (settings.demo_account_email or "").strip().lower()
    if not demo_email or user_email.strip().lower() != demo_email:
        return

    daily_limit = max(0, int(settings.demo_copilot_daily_limit))
    now = datetime.now(timezone.utc)
    tomorrow = (now + timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    seconds_until_reset = max(60, int((tomorrow - now).total_seconds()))

    if daily_limit == 0:
        _raise_429(
            detail="Copilot is disabled for the demo account.",
            retry_after=seconds_until_reset,
            limit=0,
        )

    day_str = now.strftime("%Y-%m-%d")
    allowed, _, retry_after = check_fixed_window_rate_limit(
        scope="demo_copilot_daily",
        identifier=f"{user_id}:{day_str}",
        limit=daily_limit,
        window_seconds=seconds_until_reset,
    )
    if not allowed:
        _raise_429(
            detail=(
                f"Demo account Copilot limit of {daily_limit} requests per day reached."
            ),
            retry_after=retry_after,
            limit=daily_limit,
        )
