from __future__ import annotations

import logging
from typing import Any
import uuid

from arq import Retry, create_pool
from arq.connections import RedisSettings

from app.config import settings
from app.db.session import SessionLocal
from app.services import integration_service

logger = logging.getLogger("app.worker")


def get_redis_settings() -> RedisSettings:
    """Parse REDIS_URL (including rediss:// TLS URLs) into ARQ RedisSettings."""
    return RedisSettings.from_dsn(settings.redis_url)


async def sync_integration_job(
    ctx: dict[str, Any],
    org_id: str,
    integration_id: str,
    sync_run_id: str | None = None,
    full_sync: bool = False,
) -> dict[str, Any]:
    """
    ARQ background job executing connector synchronization for a tenant integration.
    Retries transient failures up to ``WorkerSettings.max_tries`` using exponential
    backoff.
    """
    org_uuid = uuid.UUID(org_id)
    integ_uuid = uuid.UUID(integration_id)
    run_uuid = uuid.UUID(sync_run_id) if sync_run_id else None
    job_try = int(ctx.get("job_try", 1))

    db = SessionLocal()
    try:
        result = integration_service.sync_integration(
            db,
            organization_id=org_uuid,
            integration_id=integ_uuid,
            full_sync=full_sync,
            sync_run_id=run_uuid,
        )
        return result.model_dump(mode="json")
    except Exception as exc:
        logger.error(
            "Background integration sync failed",
            extra={
                "org_id": org_id,
                "integration_id": integration_id,
                "job_try": job_try,
                "error": str(exc),
            },
        )
        if job_try < WorkerSettings.max_tries:
            raise Retry(defer=job_try * 5) from exc
        raise
    finally:
        db.close()


async def enqueue_sync_job(
    *,
    organization_id: uuid.UUID,
    integration_id: uuid.UUID,
    sync_run_id: uuid.UUID,
    full_sync: bool = False,
) -> str | None:
    """Enqueue an integration sync job onto Redis/ARQ and return job ID."""
    pool = await create_pool(get_redis_settings())
    try:
        job = await pool.enqueue_job(
            "sync_integration_job",
            str(organization_id),
            str(integration_id),
            str(sync_run_id),
            full_sync,
        )
        return job.job_id if job is not None else None
    finally:
        await pool.aclose()


class WorkerSettings:
    """ARQ worker entrypoint: `arq app.worker.WorkerSettings`."""

    functions = [sync_integration_job]
    redis_settings = get_redis_settings()
    max_tries = 3
    job_timeout = 120
    health_check_interval = 15
