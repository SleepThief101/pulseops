from __future__ import annotations

import logging
import time
from typing import Any

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
import redis
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.config import settings
from app.db.session import engine

logger = logging.getLogger("app.monitoring")

HTTP_REQUESTS_TOTAL = Counter(
    "pulseops_http_requests_total",
    "Total HTTP requests handled by PulseOps API",
    ["method", "route", "status_code"],
)

HTTP_REQUEST_DURATION_SECONDS = Histogram(
    "pulseops_http_request_duration_seconds",
    "HTTP request duration in seconds",
    ["method", "route"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)

EVENTS_INGESTED_TOTAL = Counter(
    "pulseops_events_ingested_total",
    "Total operational events persisted by source",
    ["source"],
)

RATE_LIMIT_HITS_TOTAL = Counter(
    "pulseops_rate_limit_hits_total",
    "Total requests rejected with HTTP 429 by rate-limit scope",
    ["scope"],
)


class MonitoringMiddleware(BaseHTTPMiddleware):
    """Collect Prometheus HTTP request counters and latency histograms."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        start = time.perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        finally:
            duration = max(0.0, time.perf_counter() - start)
            route = request.scope.get("route")
            route_path = getattr(route, "path", None) or "unmatched"
            if route_path != "/metrics":
                HTTP_REQUESTS_TOTAL.labels(
                    method=request.method,
                    route=route_path,
                    status_code=str(status_code),
                ).inc()
                HTTP_REQUEST_DURATION_SECONDS.labels(
                    method=request.method,
                    route=route_path,
                ).observe(duration)


def render_prometheus_metrics() -> tuple[bytes, str]:
    """Render Prometheus text exposition payload and content-type."""
    return generate_latest(), CONTENT_TYPE_LATEST


def check_readiness() -> tuple[bool, dict[str, Any]]:
    """Verify PostgreSQL and Redis connectivity for service readiness."""
    checks: dict[str, str] = {}
    ready = True

    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except SQLAlchemyError as exc:
        logger.warning("Readiness database check failed: %s", exc)
        checks["database"] = "unavailable"
        ready = False

    client: redis.Redis | None = None
    try:
        client = redis.Redis.from_url(
            settings.redis_url,
            socket_connect_timeout=2.0,
            socket_timeout=2.0,
        )
        if client.ping():
            checks["redis"] = "ok"
        else:
            checks["redis"] = "unavailable"
            ready = False
    except Exception as exc:
        logger.warning("Readiness Redis check failed: %s", exc)
        checks["redis"] = "unavailable"
        ready = False
    finally:
        if client is not None:
            try:
                client.close()
            except Exception:
                pass

    return ready, checks
