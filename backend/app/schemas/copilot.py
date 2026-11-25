from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
import uuid

from pydantic import BaseModel, ConfigDict, Field, field_validator


class CopilotChatRequest(BaseModel):
    """User prompt submitted to the PulseOps AI Copilot."""

    message: str = Field(..., min_length=1, max_length=4000)
    stream: bool = False

    @field_validator("message")
    @classmethod
    def _strip_msg(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Message cannot be empty.")
        return cleaned


class CopilotProposalResponse(BaseModel):
    """Serialized ActionProposal for human-in-the-loop review."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    proposed_by_user_id: uuid.UUID
    tool_name: str
    title: str
    description: str
    arguments: dict[str, Any]
    status: str
    reviewed_by_user_id: uuid.UUID | None
    reviewed_at: datetime | None
    execution_result: dict[str, Any] | None
    created_at: datetime


class CopilotToolExecutionRecord(BaseModel):
    """Summary of a read-only tool call executed during chat."""

    tool_name: str
    result: dict[str, Any]


class CopilotChatResponse(BaseModel):
    """Response from the AI Copilot including any generated action proposals."""

    reply: str
    model_used: str
    fallback_mode: bool
    cached: bool = False
    tool_calls_executed: list[CopilotToolExecutionRecord] = Field(default_factory=list)
    pending_proposals: list[CopilotProposalResponse] = Field(default_factory=list)


class ProposalDecisionRequest(BaseModel):
    """Approve or reject a pending ActionProposal."""

    decision: Literal["approve", "reject"]
