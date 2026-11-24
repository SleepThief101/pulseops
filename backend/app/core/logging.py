"""
Structured JSON logging and request ID tracking for PulseOps.

Provides:
- Context variable management for request IDs, authenticated user IDs, and organization IDs.
- StructuredJsonFormatter producing single-line JSON log events with ISO-8601 timestamps.
- Sensitive data sanitization redacting database passwords, JWT tokens, and credentials.
- RequestLoggingMiddleware managing X-Request-ID propagation, duration metrics, and safe error handling.
- Application-wide setup_logging configuration.
"""

from __future__ import annotations

import contextvars
from datetime import datetime, timezone
import json
import logging
import re
import sys
import time
from typing import Any, Callable
import uuid

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

# ---------------------------------------------------------------------------
# Context variables for asynchronous request context tracking
# ---------------------------------------------------------------------------

_request_id_ctx: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "pulseops_request_id", default=None
)
_user_id_ctx: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "pulseops_user_id", default=None
)
_org_id_ctx: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "pulseops_org_id", default=None
)


def get_request_id() -> str | None:
    """Return the active request ID from the current async context."""
    return _request_id_ctx.get()


def set_request_id(request_id: str | None) -> contextvars.Token:
    """Set the active request ID in the current async context."""
    return _request_id_ctx.set(request_id)


def reset_request_id(token: contextvars.Token) -> None:
    """Reset the request ID context variable to its previous state."""
    _request_id_ctx.reset(token)


def get_user_id() -> str | None:
    """Return the active user ID from the current async context."""
    return _user_id_ctx.get()


def set_user_id(user_id: str | None) -> contextvars.Token:
    """Set the active user ID in the current async context."""
    return _user_id_ctx.set(user_id)


def reset_user_id(token: contextvars.Token) -> None:
    """Reset the user ID context variable to its previous state."""
    _user_id_ctx.reset(token)


def get_org_id() -> str | None:
    """Return the active organization ID from the current async context."""
    return _org_id_ctx.get()


def set_org_id(org_id: str | None) -> contextvars.Token:
    """Set the active organization ID in the current async context."""
    return _org_id_ctx.set(org_id)


def reset_org_id(token: contextvars.Token) -> None:
    """Reset the organization ID context variable to its previous state."""
    _org_id_ctx.reset(token)


# ---------------------------------------------------------------------------
# Sensitive data sanitization
# ---------------------------------------------------------------------------

_SENSITIVE_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # Database connection passwords: postgresql://user:password@host
    (re.compile(r"(://[^:]+:)([^@]+)(@)"), r"\1***\3"),
    # Bearer tokens in headers or logs: Bearer <token>
    (re.compile(r"(Bearer\s+)[A-Za-z0-9\-._~+/]+=*", re.IGNORECASE), r"\1[REDACTED]"),
    # JWT tokens: 3 base64url segments starting with eyJ
    (
        re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]*"),
        "[REDACTED_JWT]",
    ),
    # Sensitive JSON keys: "password": "...", "secret": "..."
    (
        re.compile(
            r'("(?:password|secret|token|api_key|encryption_key|credentials)"\s*:\s*)"[^"]*"',
            re.IGNORECASE,
        ),
        r'\1"[REDACTED]"',
    ),
    # Key-value assignments: password=..., jwt_secret_key=...
    (
        re.compile(
            r"((?:password|jwt_secret_key|encryption_key|secret_key|api_key)\s*=\s*)[^\s,;]+",
            re.IGNORECASE,
        ),
        r"\1[REDACTED]",
    ),
]


def sanitize_log_message(message: Any) -> str:
    """Redact passwords, database credentials, tokens, and secrets from log strings."""
    if not isinstance(message, str):
        message = str(message)
    for pattern, replacement in _SENSITIVE_PATTERNS:
        message = pattern.sub(replacement, message)
    return message


# ---------------------------------------------------------------------------
# Structured JSON Formatter
# ---------------------------------------------------------------------------

_RESERVED_LOG_RECORD_ATTRS: set[str] = {
    "args",
    "asctime",
    "created",
    "exc_info",
    "exc_text",
    "filename",
    "funcName",
    "id",
    "levelname",
    "levelno",
    "lineno",
    "module",
    "msecs",
    "message",
    "msg",
    "name",
    "pathname",
    "process",
    "processName",
    "relativeCreated",
    "stack_info",
    "thread",
    "threadName",
    "taskName",
    "request_id",
    "user_id",
    "org_id",
    "http_method",
    "path",
    "status_code",
    "duration_ms",
}


class StructuredJsonFormatter(logging.Formatter):
    """
    Formats standard Python logging records into structured, single-line JSON.

    Standard keys included in every record:
    - timestamp: ISO-8601 UTC string (e.g. 2026-11-24T15:45:00.123Z)
    - level: standard log level name (INFO, WARNING, ERROR, etc.)
    - log_level: alias for level to support diverse log aggregators
    - logger: name of the logger emitting the record
    - message: sanitized log message
    - request_id: UUID request ID from context or None if outside request scope
    """

    def format(self, record: logging.LogRecord) -> str:
        # Resolve contextual attributes
        request_id = getattr(record, "request_id", None) or get_request_id()
        user_id = getattr(record, "user_id", None) or get_user_id()
        org_id = getattr(record, "org_id", None) or get_org_id()

        now = datetime.now(timezone.utc)
        timestamp = now.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

        log_data: dict[str, Any] = {
            "timestamp": timestamp,
            "level": record.levelname,
            "log_level": record.levelname,
            "logger": record.name,
            "message": sanitize_log_message(record.getMessage()),
            "request_id": request_id,
        }

        # Contextual identifiers
        if user_id is not None:
            log_data["user_id"] = str(user_id)
        if org_id is not None:
            log_data["org_id"] = str(org_id)

        # HTTP request metrics
        for attr in ("http_method", "path", "status_code", "duration_ms"):
            val = getattr(record, attr, None)
            if val is not None:
                log_data[attr] = val

        # Custom extra fields
        for key, value in record.__dict__.items():
            if key not in _RESERVED_LOG_RECORD_ATTRS and not key.startswith("_"):
                if key not in log_data:
                    if isinstance(value, str):
                        log_data[key] = sanitize_log_message(value)
                    else:
                        log_data[key] = value

        # Exception stack trace (sanitized)
        if record.exc_info:
            log_data["exception"] = sanitize_log_message(
                self.formatException(record.exc_info)
            )

        return json.dumps(log_data, default=str)


# ---------------------------------------------------------------------------
# Request ID and Request Logging Middleware
# ---------------------------------------------------------------------------

logger = logging.getLogger("app.request")


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """
    Middleware managing request tracking and HTTP request logging:
    - Generates a unique UUIDv4 request ID for every incoming request.
    - Validates client-supplied X-Request-ID (rejects arbitrary/non-UUID values).
    - Populates request state and async context variables.
    - Emits structured JSON logs recording HTTP method, path, status, and duration.
    - Records user_id and org_id when available.
    - Redacts sensitive credentials, tokens, and passwords.
    - Safely catches unhandled exceptions, logs them with request ID, and returns HTTP 500.
    """

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        # Validate or generate unique request ID
        client_header = request.headers.get("X-Request-ID")
        validated_request_id: str | None = None
        if client_header:
            try:
                parsed_uuid = uuid.UUID(client_header.strip())
                validated_request_id = str(parsed_uuid)
            except (ValueError, TypeError, AttributeError):
                validated_request_id = None

        if not validated_request_id:
            validated_request_id = str(uuid.uuid4())

        request_id = validated_request_id
        request.state.request_id = request_id

        # Bind to async context variables
        req_token = set_request_id(request_id)
        user_token = set_user_id(None)
        org_token = set_org_id(None)

        # Attempt extracting org_id from path if available: /orgs/{org_id}/...
        path_parts = request.url.path.strip("/").split("/")
        if len(path_parts) >= 2 and path_parts[0] == "orgs":
            try:
                path_org_uuid = uuid.UUID(path_parts[1])
                set_org_id(str(path_org_uuid))
                request.state.org_id = str(path_org_uuid)
            except (ValueError, TypeError):
                pass

        start_time = time.perf_counter()

        try:
            response = await call_next(request)
            duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
            response.headers["X-Request-ID"] = request_id

            user_id = getattr(request.state, "user_id", None) or get_user_id()
            org_id = getattr(request.state, "org_id", None) or get_org_id()

            status_code = response.status_code
            if status_code >= 500:
                log_func: Callable[..., None] = logger.error
            elif status_code >= 400:
                log_func = logger.warning
            else:
                log_func = logger.info

            try:
                log_func(
                    f"{request.method} {request.url.path} {status_code} ({duration_ms}ms)",
                    extra={
                        "http_method": request.method,
                        "path": request.url.path,
                        "status_code": status_code,
                        "duration_ms": duration_ms,
                        "user_id": user_id,
                        "org_id": org_id,
                    },
                )
            except Exception:
                pass

            return response

        except Exception as exc:
            duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
            user_id = getattr(request.state, "user_id", None) or get_user_id()
            org_id = getattr(request.state, "org_id", None) or get_org_id()

            try:
                logger.error(
                    f"{request.method} {request.url.path} 500 ({duration_ms}ms)",
                    extra={
                        "http_method": request.method,
                        "path": request.url.path,
                        "status_code": 500,
                        "duration_ms": duration_ms,
                        "user_id": user_id,
                        "org_id": org_id,
                        "error": sanitize_log_message(str(exc)),
                    },
                    exc_info=True,
                )
            except Exception:
                pass

            return JSONResponse(
                status_code=500,
                content={"detail": "Internal server error"},
                headers={"X-Request-ID": request_id},
            )

        finally:
            reset_request_id(req_token)
            reset_user_id(user_token)
            reset_org_id(org_token)


# ---------------------------------------------------------------------------
# Setup logging configuration
# ---------------------------------------------------------------------------


def setup_logging(level: str | int = logging.INFO) -> None:
    """
    Configure application logging to emit single-line structured JSON logs.
    Silences duplicate plaintext access logging from uvicorn.
    """
    if isinstance(level, str):
        level = getattr(logging, level.upper(), logging.INFO)

    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # Avoid duplicate JSON handlers if called multiple times
    for handler in root_logger.handlers:
        if getattr(handler, "_pulseops_json", False):
            return

    json_handler = logging.StreamHandler(sys.stdout)
    json_handler.setFormatter(StructuredJsonFormatter())
    json_handler._pulseops_json = True  # type: ignore[attr-defined]
    root_logger.addHandler(json_handler)

    # Silence uvicorn's plaintext access logger so logs are not duplicated
    logging.getLogger("uvicorn.access").handlers.clear()
    logging.getLogger("uvicorn.access").propagate = False
