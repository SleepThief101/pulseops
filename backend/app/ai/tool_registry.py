from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable
import uuid

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy.orm import Session

from app.core.auth import ROLE_HIERARCHY
from app.models.membership import MembershipRole
from app.services import event_service, integration_service, metrics_service

RESERVED_TOOL_CONTEXT_KEYS = frozenset(
    {"db", "organization_id", "user_id", "membership", "role", "caller_role"}
)


class ToolSecurityError(Exception):
    """Base error raised when AI/MCP tool execution violates security controls."""


class ToolArgumentValidationError(ToolSecurityError):
    """Raised when LLM or caller arguments fail strict schema/context checks."""


class ToolPermissionError(ToolSecurityError):
    """Raised when caller lacks the required organization role for a tool."""


class ToolApprovalRequiredError(ToolSecurityError):
    """Raised when attempting direct execution of a mutating tool without approval."""


# ---------------------------------------------------------------------------
# Strict Pydantic Argument Schemas (extra="forbid" on every tool)
# ---------------------------------------------------------------------------


class GetMetricsSummaryArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    days: int = Field(default=30, ge=1, le=365)


class GetMetricsTimeseriesArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    days: int = Field(default=14, ge=1, le=90)


class ListRecentEventsArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: str | None = Field(default=None, min_length=1, max_length=50)
    limit: int = Field(default=20, ge=1, le=50)


class ListIntegrationsStatusArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SyncIntegrationArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    integration_id: uuid.UUID
    full_sync: bool = False


class DisconnectIntegrationArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    integration_id: uuid.UUID


@dataclass(frozen=True)
class ToolDefinition:
    """
    Registered AI tool with explicit RBAC, strict schema, and approval metadata.
    """

    name: str
    description: str
    parameters_schema: dict[str, Any]
    args_model: type[BaseModel]
    requires_approval: bool
    min_role: str
    handler: Callable[..., dict[str, Any]]

    def to_openai_tool(self) -> dict[str, Any]:
        """Format tool definition for OpenAI/DeepSeek function calling."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters_schema,
            },
        }

    def validate_arguments(self, raw_args: Any) -> dict[str, Any]:
        """
        Reject reserved execution context keys and validate against ``args_model``
        with ``extra='forbid'``. Never accepts arbitrary or unvalidated kwargs.
        """
        if not isinstance(raw_args, dict):
            raise ToolArgumentValidationError(
                f"Tool '{self.name}' arguments must be a JSON object."
            )

        forbidden = RESERVED_TOOL_CONTEXT_KEYS.intersection(raw_args.keys())
        if forbidden:
            raise ToolArgumentValidationError(
                f"Reserved execution context keys are forbidden in tool arguments: {sorted(forbidden)}"
            )

        try:
            validated = self.args_model.model_validate(raw_args)
        except ValidationError as exc:
            raise ToolArgumentValidationError(
                f"Invalid arguments for tool '{self.name}': {exc}"
            ) from exc

        return validated.model_dump(mode="json")


def execute_tool_safely(
    db: Session,
    *,
    tool: ToolDefinition,
    organization_id: uuid.UUID,
    caller_role: str,
    raw_args: Any,
    allow_mutating_execution: bool = False,
) -> dict[str, Any]:
    """
    Central security choke point for invoking any registered AI/MCP tool:
    1. Enforce caller RBAC (``caller_role >= tool.min_role``).
    2. Block mutating tools unless explicitly approved (``allow_mutating_execution``).
    3. Reject reserved context keys & validate parameters via strict Pydantic schema.
    4. Inject trusted ``db`` and ``organization_id`` exclusively from auth context.
    """
    if ROLE_HIERARCHY.get(caller_role, 0) < ROLE_HIERARCHY.get(tool.min_role, 99):
        raise ToolPermissionError(
            f"Role {tool.min_role!r} or higher is required for tool {tool.name!r}."
        )

    if tool.requires_approval and not allow_mutating_execution:
        raise ToolApprovalRequiredError(
            f"Mutating tool {tool.name!r} cannot execute without an approved ActionProposal."
        )

    clean_args = tool.validate_arguments(raw_args)
    return tool.handler(db, organization_id=organization_id, **clean_args)


# ---------------------------------------------------------------------------
# Tenant-scoped Tool Handlers
# ---------------------------------------------------------------------------


def _tool_get_metrics_summary(
    db: Session,
    *,
    organization_id: uuid.UUID,
    days: int = 30,
) -> dict[str, Any]:
    days_clamped = max(1, min(int(days), 365))
    summary = metrics_service.compute_metrics_summary(
        db,
        organization_id=organization_id,
        window_days=days_clamped,
    )
    return summary.model_dump(mode="json")


def _tool_get_metrics_timeseries(
    db: Session,
    *,
    organization_id: uuid.UUID,
    days: int = 14,
) -> dict[str, Any]:
    days_clamped = max(1, min(int(days), 90))
    ts = metrics_service.compute_metrics_timeseries(
        db,
        organization_id=organization_id,
        window_days=days_clamped,
    )
    return ts.model_dump(mode="json")


def _tool_list_recent_events(
    db: Session,
    *,
    organization_id: uuid.UUID,
    source: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    limit_clamped = max(1, min(int(limit), 50))
    events = event_service.list_events(
        db,
        organization_id=organization_id,
        source=source,
        limit=limit_clamped,
    )
    return {
        "count": len(events),
        "events": [
            {
                "id": str(e.id),
                "source": e.source,
                "event_type": e.event_type,
                "occurred_at": e.occurred_at.isoformat(),
                "amount_cents": e.amount_cents,
                "currency": e.currency,
                "actor": e.actor,
            }
            for e in events
        ],
    }


def _tool_list_integrations_status(
    db: Session,
    *,
    organization_id: uuid.UUID,
) -> dict[str, Any]:
    integrations = integration_service.list_integrations(
        db, organization_id=organization_id
    )
    return {
        "count": len(integrations),
        "integrations": [
            {
                "id": str(i.id),
                "provider": i.provider,
                "status": i.status,
                "last_synced_at": i.last_synced_at.isoformat()
                if i.last_synced_at
                else None,
            }
            for i in integrations
        ],
    }


def _tool_sync_integration(
    db: Session,
    *,
    organization_id: uuid.UUID,
    integration_id: str,
    full_sync: bool = False,
) -> dict[str, Any]:
    result = integration_service.sync_integration(
        db,
        organization_id=organization_id,
        integration_id=uuid.UUID(str(integration_id)),
        full_sync=bool(full_sync),
    )
    return result.model_dump(mode="json")


def _tool_disconnect_integration(
    db: Session,
    *,
    organization_id: uuid.UUID,
    integration_id: str,
) -> dict[str, Any]:
    deleted = integration_service.delete_integration(
        db,
        organization_id=organization_id,
        integration_id=uuid.UUID(str(integration_id)),
    )
    return {"deleted": deleted, "integration_id": str(integration_id)}


# ---------------------------------------------------------------------------
# Tool Registry
# ---------------------------------------------------------------------------


class AIToolRegistry:
    """Registry holding all PulseOps AI & Copilot tools."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}

    def register(self, tool: ToolDefinition) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> ToolDefinition:
        if name not in self._tools:
            raise KeyError(f"Unknown AI tool: {name!r}")
        return self._tools[name]

    def list_tools(self) -> list[ToolDefinition]:
        return list(self._tools.values())

    def openai_tools_schema(self) -> list[dict[str, Any]]:
        return [t.to_openai_tool() for t in self._tools.values()]


ai_tool_registry = AIToolRegistry()

ai_tool_registry.register(
    ToolDefinition(
        name="get_metrics_summary",
        description="Read tenant-scoped SaaS KPIs (MRR, ARR, churn rate, PRs, open issues, cycle time).",
        parameters_schema={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "days": {
                    "type": "integer",
                    "description": "Lookback window in days (1-365).",
                    "default": 30,
                }
            },
        },
        args_model=GetMetricsSummaryArgs,
        requires_approval=False,
        min_role=MembershipRole.VIEWER.value,
        handler=_tool_get_metrics_summary,
    )
)

ai_tool_registry.register(
    ToolDefinition(
        name="get_metrics_timeseries",
        description="Read daily time-series breakdown of revenue, churn, PRs, and issues.",
        parameters_schema={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "days": {
                    "type": "integer",
                    "description": "Lookback window in days (1-90).",
                    "default": 14,
                }
            },
        },
        args_model=GetMetricsTimeseriesArgs,
        requires_approval=False,
        min_role=MembershipRole.VIEWER.value,
        handler=_tool_get_metrics_timeseries,
    )
)

ai_tool_registry.register(
    ToolDefinition(
        name="list_recent_events",
        description="List recent normalized operational events for the organization.",
        parameters_schema={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "source": {"type": "string", "description": "Optional source filter."},
                "limit": {"type": "integer", "default": 20},
            },
        },
        args_model=ListRecentEventsArgs,
        requires_approval=False,
        min_role=MembershipRole.VIEWER.value,
        handler=_tool_list_recent_events,
    )
)

ai_tool_registry.register(
    ToolDefinition(
        name="list_integrations_status",
        description="List connected integrations and last sync timestamps (without exposing secrets).",
        parameters_schema={
            "type": "object",
            "additionalProperties": False,
            "properties": {},
        },
        args_model=ListIntegrationsStatusArgs,
        requires_approval=False,
        min_role=MembershipRole.VIEWER.value,
        handler=_tool_list_integrations_status,
    )
)

ai_tool_registry.register(
    ToolDefinition(
        name="sync_organization_integration",
        description="Trigger a connector sync for an organization integration (requires human approval).",
        parameters_schema={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "integration_id": {
                    "type": "string",
                    "description": "UUID of the integration to sync.",
                },
                "full_sync": {"type": "boolean", "default": False},
            },
            "required": ["integration_id"],
        },
        args_model=SyncIntegrationArgs,
        requires_approval=True,
        min_role=MembershipRole.MEMBER.value,
        handler=_tool_sync_integration,
    )
)

ai_tool_registry.register(
    ToolDefinition(
        name="disconnect_integration",
        description="Disconnect and remove an organization integration (requires owner approval).",
        parameters_schema={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "integration_id": {
                    "type": "string",
                    "description": "UUID of the integration to delete.",
                },
            },
            "required": ["integration_id"],
        },
        args_model=DisconnectIntegrationArgs,
        requires_approval=True,
        min_role=MembershipRole.OWNER.value,
        handler=_tool_disconnect_integration,
    )
)
