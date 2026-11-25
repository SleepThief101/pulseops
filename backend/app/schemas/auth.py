"""
Pydantic request/response schemas for authentication endpoints.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, field_validator


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    organization_name: str

    @field_validator("password")
    @classmethod
    def password_length(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters.")
        if len(v) > 128:
            raise ValueError("Password must not exceed 128 characters.")
        return v

    @field_validator("organization_name")
    @classmethod
    def org_name_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Organization name must not be empty.")
        if len(v) > 255:
            raise ValueError("Organization name must not exceed 255 characters.")
        return v


class RegisterResponse(BaseModel):
    user_id: uuid.UUID
    email: str
    created_at: datetime
    organization_id: uuid.UUID
    organization_name: str
    role: str

    model_config = ConfigDict(from_attributes=True)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int = 3600


class UserProfile(BaseModel):
    id: uuid.UUID
    email: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class UserOrganizationSummary(BaseModel):
    organization_id: uuid.UUID
    organization_name: str
    role: str
    created_at: datetime
