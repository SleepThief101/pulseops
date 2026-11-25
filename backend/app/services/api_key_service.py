from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import secrets
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.models.api_key import ApiKey
from app.models.user import User
from app.services import audit_service

API_KEY_PREFIX = "pmcp_"


class MCPAuthError(Exception):
    """Raised when an MCP API key is missing, invalid, expired, or revoked."""


class MCPAuthorizationError(Exception):
    """Raised when an authenticated MCP caller lacks org membership or role."""


def hash_api_key(raw_key: str) -> str:
    """Compute SHA-256 hex digest for storage and constant-time comparison."""
    return hashlib.sha256(raw_key.strip().encode("utf-8")).hexdigest()


def create_api_key(
    db: Session,
    *,
    user_id: uuid.UUID,
    name: str,
    expires_in_days: int | None = None,
    ip_address: str | None = None,
) -> tuple[ApiKey, str]:
    """
    Generate a cryptographically random per-user API key, persist only its
    SHA-256 hash and display prefix, and return ``(ApiKey, plaintext_key)``.
    """
    raw_key = f"{API_KEY_PREFIX}{secrets.token_urlsafe(32)}"
    key_prefix = raw_key[:13]
    key_hash = hash_api_key(raw_key)

    expires_at = (
        datetime.now(timezone.utc) + timedelta(days=expires_in_days)
        if expires_in_days is not None
        else None
    )

    record = ApiKey(
        user_id=user_id,
        name=name,
        key_prefix=key_prefix,
        key_hash=key_hash,
        expires_at=expires_at,
    )
    db.add(record)
    db.flush()

    audit_service.record_audit_event(
        db,
        organization_id=None,
        user_id=user_id,
        action="api_key.created",
        resource_type="api_key",
        resource_id=str(record.id),
        details={"name": name, "key_prefix": key_prefix},
        ip_address=ip_address,
    )
    db.commit()
    db.refresh(record)
    return record, raw_key


def list_api_keys(
    db: Session,
    *,
    user_id: uuid.UUID,
) -> list[ApiKey]:
    """List API keys belonging strictly to ``user_id``."""
    return list(
        db.scalars(
            select(ApiKey)
            .where(ApiKey.user_id == user_id)
            .order_by(ApiKey.created_at.desc())
        ).all()
    )


def revoke_api_key(
    db: Session,
    *,
    user_id: uuid.UUID,
    key_id: uuid.UUID,
    ip_address: str | None = None,
) -> ApiKey | None:
    """
    Revoke an API key belonging to ``user_id``. Returns None if not found or
    owned by a different user (enforces 404 ownership isolation).
    """
    record = db.scalar(
        select(ApiKey).where(
            ApiKey.id == key_id,
            ApiKey.user_id == user_id,
        )
    )
    if record is None:
        return None

    if record.revoked_at is None:
        record.revoked_at = datetime.now(timezone.utc)
        audit_service.record_audit_event(
            db,
            organization_id=None,
            user_id=user_id,
            action="api_key.revoked",
            resource_type="api_key",
            resource_id=str(record.id),
            details={"name": record.name, "key_prefix": record.key_prefix},
            ip_address=ip_address,
        )
        db.commit()
        db.refresh(record)

    return record


def authenticate_api_key(
    db: Session,
    *,
    raw_key: str | None,
) -> tuple[User, ApiKey]:
    """
    Authenticate a caller from a per-user MCP API key.
    Rejects missing, malformed, unknown, expired, and revoked keys.
    """
    cleaned = (raw_key or "").strip()
    if not cleaned or not cleaned.startswith(API_KEY_PREFIX):
        raise MCPAuthError("Invalid or missing MCP API key.")

    digest = hash_api_key(cleaned)
    record = db.scalar(
        select(ApiKey)
        .options(joinedload(ApiKey.user))
        .where(ApiKey.key_hash == digest)
    )
    if record is None or not hmac.compare_digest(record.key_hash, digest):
        raise MCPAuthError("Invalid or missing MCP API key.")

    if record.revoked_at is not None:
        raise MCPAuthError("MCP API key has been revoked.")

    now = datetime.now(timezone.utc)
    if record.expires_at is not None and record.expires_at <= now:
        raise MCPAuthError("MCP API key has expired.")

    if record.user is None:
        raise MCPAuthError("MCP API key user not found.")

    record.last_used_at = now
    db.commit()
    return record.user, record
