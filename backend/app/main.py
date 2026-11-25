from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.config import settings
from app.core.logging import RequestLoggingMiddleware, setup_logging
from app.core.monitoring import (
    MonitoringMiddleware,
    check_readiness,
    render_prometheus_metrics,
)
from app.db.session import engine
from app.routers import auth as auth_router
from app.routers.audit import router as audit_router
from app.routers.copilot import router as copilot_router
from app.routers.integrations import router as integrations_router
from app.routers.me import me_router
from app.routers.members import router as members_router
from app.routers.metrics import router as metrics_router
from app.routers.sse import router as sse_router
from app.routers.webhooks import router as webhooks_router

# Configure structured JSON logging
setup_logging(level=settings.log_level)
logger = logging.getLogger("app.startup")


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Validate production readiness on startup and dispose DB pool on shutdown."""
    if settings.is_production:
        settings.validate_production_settings()

        db_lower = settings.database_url.lower()
        is_local_db = any(h in db_lower for h in ("@localhost", "@127.0.0.1", "@db:"))
        if not is_local_db and "sslmode=" not in db_lower:
            logger.warning(
                "Production DATABASE_URL does not specify sslmode (Neon requires sslmode=require)."
            )

        redis_lower = settings.redis_url.lower()
        is_local_redis = any(
            h in redis_lower for h in ("localhost", "127.0.0.1", "//redis:")
        )
        if not is_local_redis and not redis_lower.startswith("rediss://"):
            logger.warning(
                "Production REDIS_URL does not use TLS (Upstash requires rediss://)."
            )

        logger.info("PulseOps API started in production mode.")

    try:
        yield
    finally:
        engine.dispose()


# FastAPI application
app = FastAPI(
    title="PulseOps API",
    description="AI-native control tower for small SaaS teams.",
    version="0.1.0",
    docs_url="/docs" if settings.docs_enabled else None,
    redoc_url="/redoc" if settings.docs_enabled else None,
    openapi_url="/openapi.json" if settings.docs_enabled else None,
    lifespan=lifespan,
)

# Middleware (registered inner-to-outer: CORSMiddleware wraps MonitoringMiddleware wrapping RequestLoggingMiddleware)
app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(MonitoringMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
    expose_headers=["X-Request-ID"],
)

# Routers
app.include_router(auth_router.router)
app.include_router(me_router)
app.include_router(members_router)
app.include_router(integrations_router)
app.include_router(metrics_router)
app.include_router(sse_router)
app.include_router(audit_router)
app.include_router(copilot_router)
app.include_router(webhooks_router)


@app.get("/", tags=["General"])
def root():
    return {
        "message": "PulseOps API is running",
        "version": "0.1.0",
    }


@app.get("/health", tags=["Health"])
def health_check():
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))

        return {"status": "ok"}

    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=503,
            detail="Database unavailable",
        ) from exc


@app.get("/readiness", tags=["Health"])
def readiness_check():
    """Verify PostgreSQL and Redis readiness before serving traffic."""
    ready, checks = check_readiness()
    payload = {
        "status": "ready" if ready else "not_ready",
        "checks": checks,
    }
    return JSONResponse(status_code=200 if ready else 503, content=payload)


@app.get("/metrics", tags=["Monitoring"])
def prometheus_metrics():
    """Expose Prometheus text-format operational metrics."""
    payload, content_type = render_prometheus_metrics()
    return Response(content=payload, media_type=content_type)
