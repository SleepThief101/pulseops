"""
Pydantic request and response schemas for organization membership endpoints.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, computed_field, field_validator

from app.models.membership import MembershipRole


class AddMemberRequest(BaseModel):
    email: EmailStr
    role: str = MembershipRole.MEMBER.value

    @field_validator("role")
    @classmethod
    def validate_role(cls, v: str) -> str:
        v_clean = v.strip().lower()
        valid_roles = {r.value for r in MembershipRole}
        if v_clean not in valid_roles:
            raise ValueError(
                f"Invalid role: {v!r}. Must be one of: {', '.join(sorted(valid_roles))}"
            )
        return v_clean


class MemberUserResponse(BaseModel):
    id: uuid.UUID
    email: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class MemberResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    organization_id: uuid.UUID
    role: str
    created_at: datetime
    user: MemberUserResponse

    @computed_field
    @property
    def email(self) -> str:
        return self.user.email

    model_config = ConfigDict(from_attributes=True)
