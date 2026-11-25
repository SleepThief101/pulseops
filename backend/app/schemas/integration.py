from __future__ import annotations

from datetime import datetime
from typing import Any
import uuid

from pydantic import BaseModel, ConfigDict, Field, field_validator


class IntegrationCreateRequest(BaseModel):
    """Request payload for connecting a new integration to an organization."""

    provider: str = Field(..., min_length=1, max_length=50)
    credentials: dict[str, Any] = Field(default_factory=dict)

    @field_validator("provider")
    @classmethod
    def _normalize_provider(cls, value: str) -> str:
        cleaned = value.strip().lower()
        if not cleaned:
            raise ValueError("Provider cannot be empty.")
        return cleaned


class IntegrationResponse(BaseModel):
    """
    Public representation of a tenant Integration.

    Never exposes encrypted ciphertext or decrypted credentials.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    provider: str
    status: str
    last_synced_at: datetime | None
    created_at: datetime


class IntegrationSyncResponse(BaseModel):
    """Result summary returned after syncing an integration."""

    integration_id: uuid.UUID
    provider: str
    status: str
    total_received: int
    inserted_count: int
    skipped_count: int
    sync_run_id: uuid.UUID | None = None
    queued: bool = False


class GitHubOAuthUrlResponse(BaseModel):
    """Authorization URL and signed state token for connecting GitHub OAuth."""

    authorization_url: str
    state: str


class GitHubOAuthCallbackRequest(BaseModel):
    """OAuth callback payload completing a GitHub App/OAuth connection."""

    code: str = Field(..., min_length=1)
    state: str = Field(..., min_length=1)
    repo: str = Field(..., min_length=3, max_length=255)
