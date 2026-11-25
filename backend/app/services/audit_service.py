from __future__ import annotations

from typing import Any
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog

_SENSITIVE_DETAIL_KEYS = frozenset(
    {
        "password",
        "password_hash",
        "secret",
        "api_key",
        "key_hash",
        "key_secret",
        "access_token",
        "refresh_token",
        "webhook_secret",
        "credentials",
        "credentials_encrypted",
        "encryption_key",
        "jwt_secret_key",
        "authorization",
    }
)


def _sanitize_audit_details(value: Any) -> Any:
    """Recursively redact sensitive keys before writing AuditLog records."""
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, item in value.items():
            key_lower = str(key).strip().lower()
            if key_lower in _SENSITIVE_DETAIL_KEYS or any(
                s in key_lower for s in ("password", "secret", "token", "api_key")
            ):
                sanitized[str(key)] = "[REDACTED]"
            else:
                sanitized[str(key)] = _sanitize_audit_details(item)
        return sanitized
    if isinstance(value, list):
        return [_sanitize_audit_details(item) for item in value]
    return value


def record_audit_event(
    db: Session,
    *,
    action: str,
    resource_type: str,
    organization_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
    resource_id: str | None = None,
    details: dict[str, Any] | None = None,
    ip_address: str | None = None,
    commit: bool = False,
) -> AuditLog:
    """
    Persist a structured AuditLog entry with actor and tenant attribution.
    Automatically scrubs credentials, tokens, and passwords from ``details``.
    """
    entry = AuditLog(
        organization_id=organization_id,
        user_id=user_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        details=_sanitize_audit_details(details or {}),
        ip_address=ip_address,
    )
    db.add(entry)
    if commit:
        db.commit()
        db.refresh(entry)
    else:
        db.flush()
    return entry


def list_audit_logs(
    db: Session,
    *,
    organization_id: uuid.UUID,
    action: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[AuditLog]:
    """List AuditLog entries strictly scoped to ``organization_id`` newest first."""
    stmt = select(AuditLog).where(AuditLog.organization_id == organization_id)
    if action is not None:
        stmt = stmt.where(AuditLog.action == action)
    stmt = stmt.order_by(AuditLog.created_at.desc()).limit(limit).offset(offset)
    return list(db.scalars(stmt).all())
