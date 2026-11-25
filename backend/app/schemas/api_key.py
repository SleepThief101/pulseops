from __future__ import annotations

from datetime import datetime
import uuid

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ApiKeyCreateRequest(BaseModel):
    """Request body for issuing a new per-user MCP API key."""

    name: str = Field(..., min_length=1, max_length=100)
    expires_in_days: int | None = Field(default=None, ge=1, le=365)

    @field_validator("name")
    @classmethod
    def _strip_name(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("API key name cannot be empty.")
        return cleaned


class ApiKeyResponse(BaseModel):
    """Metadata view of a user's API key (never includes secret or hash)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    name: str
    key_prefix: str
    last_used_at: datetime | None
    revoked_at: datetime | None
    expires_at: datetime | None
    created_at: datetime


class ApiKeyCreatedResponse(ApiKeyResponse):
    """
    Returned ONCE at API key creation time. Contains the plaintext key
    so the user can store it; never persisted or returned again.
    """

    api_key: str
