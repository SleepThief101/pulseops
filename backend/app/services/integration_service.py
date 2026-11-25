from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from typing import Any
from urllib.parse import urlencode
import uuid

import httpx
import jwt
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.connectors import (
    ConnectorAuthError,
    ConnectorError,
    ConnectorNotFoundError,
    connector_registry,
)
from app.core.auth import JWT_ALGORITHM, get_jwt_secret
from app.core.security import decrypt_credentials, encrypt_credentials
from app.models.integration import Integration, IntegrationStatus
from app.models.sync_run import SyncRun, SyncRunStatus
from app.schemas.integration import IntegrationSyncResponse
from app.services.event_service import sync_connector_events


def create_integration(
    db: Session,
    *,
    organization_id: uuid.UUID,
    provider: str,
    credentials: dict[str, Any],
) -> Integration:
    """
    Validate provider & credentials, encrypt credentials via Fernet, and
    persist a tenant-scoped Integration record.
    """
    connector = connector_registry.get(provider)
    connector.validate_credentials(credentials)

    encrypted = encrypt_credentials(json.dumps(credentials))
    integration = Integration(
        organization_id=organization_id,
        provider=connector.provider,
        status=IntegrationStatus.ACTIVE.value,
        credentials_encrypted=encrypted,
    )
    db.add(integration)
    db.commit()
    db.refresh(integration)
    return integration


def list_integrations(
    db: Session,
    *,
    organization_id: uuid.UUID,
) -> list[Integration]:
    """List integrations strictly scoped to ``organization_id``."""
    return list(
        db.scalars(
            select(Integration)
            .where(Integration.organization_id == organization_id)
            .order_by(Integration.created_at.desc())
        ).all()
    )


def get_integration(
    db: Session,
    *,
    organization_id: uuid.UUID,
    integration_id: uuid.UUID,
) -> Integration | None:
    """Retrieve a single integration only if it belongs to ``organization_id``."""
    return db.scalar(
        select(Integration).where(
            Integration.id == integration_id,
            Integration.organization_id == organization_id,
        )
    )


def delete_integration(
    db: Session,
    *,
    organization_id: uuid.UUID,
    integration_id: uuid.UUID,
) -> bool:
    """Delete an integration only if it belongs to ``organization_id``."""
    integration = get_integration(
        db,
        organization_id=organization_id,
        integration_id=integration_id,
    )
    if integration is None:
        return False
    db.delete(integration)
    db.commit()
    return True


def create_pending_sync_run(
    db: Session,
    *,
    organization_id: uuid.UUID,
    integration_id: uuid.UUID,
) -> SyncRun:
    """Create a pending SyncRun record scoped to ``organization_id``."""
    integration = get_integration(
        db,
        organization_id=organization_id,
        integration_id=integration_id,
    )
    if integration is None:
        raise ConnectorNotFoundError("Integration not found.")

    run = SyncRun(
        organization_id=organization_id,
        integration_id=integration_id,
        status=SyncRunStatus.PENDING.value,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def list_sync_runs(
    db: Session,
    *,
    organization_id: uuid.UUID,
    limit: int = 50,
) -> list[SyncRun]:
    """List SyncRun audit records strictly scoped to ``organization_id``."""
    return list(
        db.scalars(
            select(SyncRun)
            .where(SyncRun.organization_id == organization_id)
            .order_by(SyncRun.started_at.desc())
            .limit(limit)
        ).all()
    )


def sync_integration(
    db: Session,
    *,
    organization_id: uuid.UUID,
    integration_id: uuid.UUID,
    since: datetime | None = None,
    full_sync: bool = False,
    sync_run_id: uuid.UUID | None = None,
) -> IntegrationSyncResponse:
    """
    Decrypt stored credentials for ``integration_id`` (scoped to ``organization_id``),
    fetch and normalize events from its connector, persist them idempotently, and
    record a SyncRun audit entry.
    """
    integration = get_integration(
        db,
        organization_id=organization_id,
        integration_id=integration_id,
    )
    if integration is None:
        raise ConnectorNotFoundError("Integration not found.")

    sync_run: SyncRun | None = None
    if sync_run_id is not None:
        sync_run = db.scalar(
            select(SyncRun).where(
                SyncRun.id == sync_run_id,
                SyncRun.organization_id == organization_id,
            )
        )
    if sync_run is None:
        sync_run = SyncRun(
            organization_id=organization_id,
            integration_id=integration.id,
            status=SyncRunStatus.RUNNING.value,
        )
        db.add(sync_run)
        db.flush()
    else:
        sync_run.status = SyncRunStatus.RUNNING.value
        db.flush()

    raw_json = decrypt_credentials(integration.credentials_encrypted)
    credentials = json.loads(raw_json)

    effective_since = (
        None if full_sync else (since if since is not None else integration.last_synced_at)
    )

    try:
        result = sync_connector_events(
            db,
            organization_id=organization_id,
            provider=integration.provider,
            credentials=credentials,
            since=effective_since,
            integration_id=integration.id,
        )
        now = datetime.now(timezone.utc)
        integration.last_synced_at = now
        integration.status = IntegrationStatus.ACTIVE.value
        sync_run.status = SyncRunStatus.COMPLETED.value
        sync_run.events_received = result.total_received
        sync_run.events_inserted = result.inserted_count
        sync_run.events_skipped = result.skipped_count
        sync_run.finished_at = now
        db.commit()
    except (ConnectorError, ConnectorAuthError) as exc:
        now = datetime.now(timezone.utc)
        integration.status = IntegrationStatus.ERROR.value
        sync_run.status = SyncRunStatus.FAILED.value
        sync_run.error_message = str(exc)
        sync_run.finished_at = now
        db.commit()
        raise

    return IntegrationSyncResponse(
        integration_id=integration.id,
        provider=integration.provider,
        status=integration.status,
        total_received=result.total_received,
        inserted_count=result.inserted_count,
        skipped_count=result.skipped_count,
        sync_run_id=sync_run.id,
        queued=False,
    )


# ---------------------------------------------------------------------------
# GitHub OAuth helpers
# ---------------------------------------------------------------------------


def create_github_oauth_state(
    *,
    organization_id: uuid.UUID,
    user_id: uuid.UUID,
) -> str:
    """Sign a short-lived OAuth state JWT binding org_id and user_id."""
    now = datetime.now(tz=timezone.utc)
    payload = {
        "purpose": "github_oauth",
        "org_id": str(organization_id),
        "user_id": str(user_id),
        "nonce": uuid.uuid4().hex,
        "iat": now,
        "exp": now + timedelta(minutes=10),
    }
    return jwt.encode(payload, get_jwt_secret(), algorithm=JWT_ALGORITHM)


def build_github_oauth_url(
    *,
    organization_id: uuid.UUID,
    user_id: uuid.UUID,
) -> tuple[str, str]:
    """Build a GitHub OAuth authorization URL and signed state token."""
    state = create_github_oauth_state(
        organization_id=organization_id,
        user_id=user_id,
    )
    client_id = (settings.github_client_id or "pulseops_github_oauth_unconfigured").strip()
    params: dict[str, str] = {
        "client_id": client_id,
        "scope": "repo read:org",
        "state": state,
    }
    if settings.github_oauth_redirect_uri:
        params["redirect_uri"] = settings.github_oauth_redirect_uri
    url = f"https://github.com/login/oauth/authorize?{urlencode(params)}"
    return url, state


def verify_github_oauth_state(
    *,
    state: str,
    organization_id: uuid.UUID,
    user_id: uuid.UUID,
) -> None:
    """Verify signed OAuth state belongs to the active org_id and user_id."""
    try:
        payload = jwt.decode(state, get_jwt_secret(), algorithms=[JWT_ALGORITHM])
    except jwt.InvalidTokenError as exc:
        raise ConnectorAuthError("Invalid or expired GitHub OAuth state.") from exc

    if (
        payload.get("purpose") != "github_oauth"
        or payload.get("org_id") != str(organization_id)
        or payload.get("user_id") != str(user_id)
    ):
        raise ConnectorAuthError("OAuth state does not match organization or user.")


def exchange_github_oauth_code(
    *,
    code: str,
    http_client: httpx.Client | None = None,
) -> str:
    """
    Exchange an OAuth authorization code for a GitHub access token.
    Requires GITHUB_CLIENT_ID and GITHUB_CLIENT_SECRET.
    """
    if not settings.github_client_id or not settings.github_client_secret:
        raise ConnectorAuthError(
            "GitHub OAuth is not configured (missing GITHUB_CLIENT_ID / GITHUB_CLIENT_SECRET)."
        )

    payload = {
        "client_id": settings.github_client_id,
        "client_secret": settings.github_client_secret,
        "code": code,
    }
    headers = {"Accept": "application/json"}

    try:
        if http_client is not None:
            resp = http_client.post(
                "https://github.com/login/oauth/access_token",
                json=payload,
                headers=headers,
            )
        else:
            with httpx.Client(timeout=10.0) as client:
                resp = client.post(
                    "https://github.com/login/oauth/access_token",
                    json=payload,
                    headers=headers,
                )
        resp.raise_for_status()
        data = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise ConnectorAuthError("GitHub OAuth code exchange failed.") from exc

    if not isinstance(data, dict):
        raise ConnectorAuthError("GitHub OAuth code exchange returned malformed data.")
    access_token = data.get("access_token")
    if not access_token:
        raise ConnectorAuthError(
            data.get("error_description") or "GitHub OAuth code exchange failed."
        )
    return str(access_token)
