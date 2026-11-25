from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
from typing import Any, Callable
import uuid

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy.orm import Session

from app.core.auth import ROLE_HIERARCHY
from app.core.currency import (
    InvalidCurrencyError,
    format_minor_amount,
    get_minor_unit_exponent,
    get_minor_unit_name,
    minor_to_major_decimal,
    normalize_currency,
)
from app.core.security import decrypt_credentials
from app.models.membership import MembershipRole
from app.services import event_service, integration_service, metrics_service

RESERVED_TOOL_CONTEXT_KEYS = frozenset(
    {"db", "organization_id", "user_id", "membership", "role", "caller_role"}
)

_SAFE_CORRELATION_KEYS = (
    "order_id",
    "invoice_id",
    "subscription_id",
    "payment_id",
    "entity",
    "status",
    "method",
    "billing_mode",
    "error_code",
    "error_reason",
    "synthetic",
    "repo",
    "number",
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
    include_synthetic: bool = False


class GetMetricsTimeseriesArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    days: int = Field(default=14, ge=1, le=90)
    include_synthetic: bool = False


class ListRecentEventsArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: str | None = Field(default=None, min_length=1, max_length=50)
    event_type: str | None = Field(default=None, min_length=1, max_length=100)
    actor: str | None = Field(default=None, min_length=1, max_length=255)
    currency: str | None = Field(default=None, min_length=3, max_length=10)
    include_synthetic: bool = True
    since_days: int | None = Field(default=None, ge=1, le=365)
    limit: int = Field(default=20, ge=1, le=50)
    offset: int = Field(default=0, ge=0, le=5000)


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


def _sanitize_untrusted_text(value: Any, *, max_len: int = 120) -> str | None:
    """Strip control characters and bound untrusted external text returned to LLM."""
    if value is None:
        return None
    cleaned = "".join(ch if ch >= " " else " " for ch in str(value)).strip()
    if not cleaned:
        return None
    return cleaned[:max_len]


def _extract_safe_correlation(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    out: dict[str, Any] = {}
    for key in _SAFE_CORRELATION_KEYS:
        if key not in payload or payload[key] is None:
            continue
        val = payload[key]
        if isinstance(val, (bool, int, float)):
            out[key] = val
        else:
            clean = _sanitize_untrusted_text(val, max_len=120)
            if clean is not None:
                out[key] = clean
    return out


# ---------------------------------------------------------------------------
# Tenant-scoped Tool Handlers
# ---------------------------------------------------------------------------


def _tool_get_metrics_summary(
    db: Session,
    *,
    organization_id: uuid.UUID,
    days: int = 30,
    include_synthetic: bool = False,
) -> dict[str, Any]:
    days_clamped = max(1, min(int(days), 365))
    summary = metrics_service.compute_metrics_summary(
        db,
        organization_id=organization_id,
        window_days=days_clamped,
        include_synthetic=bool(include_synthetic),
    )
    data = summary.model_dump(mode="json")
    data["timezone"] = "UTC"
    return data


def _tool_get_metrics_timeseries(
    db: Session,
    *,
    organization_id: uuid.UUID,
    days: int = 14,
    include_synthetic: bool = False,
) -> dict[str, Any]:
    days_clamped = max(1, min(int(days), 90))
    ts = metrics_service.compute_metrics_timeseries(
        db,
        organization_id=organization_id,
        window_days=days_clamped,
        include_synthetic=bool(include_synthetic),
    )
    data = ts.model_dump(mode="json")
    data["timezone"] = "UTC"
    return data


def _tool_list_recent_events(
    db: Session,
    *,
    organization_id: uuid.UUID,
    source: str | None = None,
    event_type: str | None = None,
    actor: str | None = None,
    currency: str | None = None,
    include_synthetic: bool = True,
    since_days: int | None = None,
    limit: int = 20,
    offset: int = 0,
) -> dict[str, Any]:
    limit_clamped = max(1, min(int(limit), 50))
    offset_clamped = max(0, int(offset))

    curr_norm: str | None = None
    if currency is not None:
        try:
            curr_norm = normalize_currency(currency, allow_none=True)
        except InvalidCurrencyError:
            curr_norm = currency.strip().upper()

    since_dt: datetime | None = None
    if since_days is not None:
        since_dt = datetime.now(timezone.utc) - timedelta(days=max(1, min(int(since_days), 365)))

    events = event_service.list_events(
        db,
        organization_id=organization_id,
        source=source,
        event_type=event_type,
        actor=actor,
        currency=curr_norm,
        include_synthetic=bool(include_synthetic),
        since=since_dt,
        limit=limit_clamped,
        offset=offset_clamped,
    )
    total_matching = event_service.count_events(
        db,
        organization_id=organization_id,
        source=source,
        event_type=event_type,
        actor=actor,
        currency=curr_norm,
        include_synthetic=bool(include_synthetic),
        since=since_dt,
    )

    serialized_events: list[dict[str, Any]] = []
    for e in events:
        exp = e.minor_unit_exponent
        if exp is None and e.currency:
            try:
                exp = get_minor_unit_exponent(e.currency)
            except InvalidCurrencyError:
                exp = None

        amount_major: str | None = None
        formatted_amount: str | None = None
        if e.amount_cents is not None:
            formatted_amount = format_minor_amount(
                e.amount_cents,
                e.currency,
                exponent=exp,
            )
            if e.currency:
                try:
                    amount_major = str(
                        minor_to_major_decimal(e.amount_cents, e.currency, exponent=exp)
                    )
                except InvalidCurrencyError:
                    amount_major = None

        serialized_events.append(
            {
                "id": str(e.id),
                "external_id": e.external_id,
                "source": e.source,
                "event_type": e.event_type,
                "occurred_at": e.occurred_at.astimezone(timezone.utc).isoformat(),
                "amount_minor": e.amount_cents,
                "currency": e.currency,
                "minor_unit_exponent": exp,
                "minor_unit_name": get_minor_unit_name(e.currency)
                if e.amount_cents is not None
                else None,
                "amount_major": amount_major,
                "formatted_amount": formatted_amount,
                "actor": _sanitize_untrusted_text(e.actor, max_len=120),
                "is_synthetic": bool(e.is_synthetic),
                "correlation": _extract_safe_correlation(e.payload),
            }
        )

    return {
        "count": len(serialized_events),
        "total_matching": total_matching,
        "limit": limit_clamped,
        "offset": offset_clamped,
        "truncated": (offset_clamped + len(serialized_events)) < total_matching,
        "timezone": "UTC",
        "filters": {
            "source": source,
            "event_type": event_type,
            "actor": actor,
            "currency": curr_norm,
            "include_synthetic": bool(include_synthetic),
            "since_days": since_days,
        },
        "events": serialized_events,
    }


def _safe_integration_mode(credentials_encrypted: str, provider: str) -> tuple[str, bool]:
    """Infer non-secret operational mode ('mock', 'test_credentials', 'synthetic') cleanly."""
    if provider == "fake":
        return "synthetic", True
    try:
        creds = json.loads(decrypt_credentials(credentials_encrypted))
        if isinstance(creds, dict):
            mode = str(creds.get("mode") or "").strip().lower()
            if mode == "mock":
                return "mock", True
            if creds.get("key_id") or creds.get("access_token"):
                return "test_credentials", False
    except Exception:
        return "unknown", False
    return "mock_fallback", True


def _tool_list_integrations_status(
    db: Session,
    *,
    organization_id: uuid.UUID,
) -> dict[str, Any]:
    integrations = integration_service.list_integrations(
        db, organization_id=organization_id
    )
    items: list[dict[str, Any]] = []
    for i in integrations:
        mode, is_mock_or_synth = _safe_integration_mode(i.credentials_encrypted, i.provider)
        items.append(
            {
                "id": str(i.id),
                "provider": i.provider,
                "status": i.status,
                "mode": mode,
                "is_mock_or_synthetic": is_mock_or_synth,
                "last_synced_at": i.last_synced_at.astimezone(timezone.utc).isoformat()
                if i.last_synced_at
                else None,
            }
        )
    return {
        "count": len(items),
        "timezone": "UTC",
        "integrations": items,
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
        description=(
            "Read tenant-scoped multi-currency SaaS KPIs (recurring MRR/ARR, one-time payment volume, "
            "failed payments, churn rate, PRs, open issues, cycle time). Currencies are separated under by_currency."
        ),
        parameters_schema={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "days": {
                    "type": "integer",
                    "description": "Lookback window in days (1-365).",
                    "default": 30,
                },
                "include_synthetic": {
                    "type": "boolean",
                    "description": "Include synthetic/mock events (default false for production accuracy).",
                    "default": False,
                },
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
        description="Read daily UTC time-series breakdown per currency of revenue, churn, PRs, and issues.",
        parameters_schema={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "days": {
                    "type": "integer",
                    "description": "Lookback window in days (1-90).",
                    "default": 14,
                },
                "include_synthetic": {
                    "type": "boolean",
                    "description": "Include synthetic/mock events (default false).",
                    "default": False,
                },
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
        description=(
            "List normalized operational events with minor & formatted major amounts, currency unit metadata, "
            "external_id, correlation fields (order_id/subscription_id/invoice_id), is_synthetic, and truncation info."
        ),
        parameters_schema={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "source": {
                    "type": "string",
                    "description": "Optional source filter (razorpay, github, csv, fake).",
                },
                "event_type": {
                    "type": "string",
                    "description": "Optional event_type filter (e.g. payment.failed, payment.captured, pr.merged).",
                },
                "actor": {
                    "type": "string",
                    "description": "Optional customer/user actor identifier.",
                },
                "currency": {
                    "type": "string",
                    "description": "Optional 3-letter ISO-4217 currency filter (e.g. INR, USD, JPY, KWD).",
                },
                "include_synthetic": {
                    "type": "boolean",
                    "description": "Whether to include synthetic/mock events.",
                    "default": True,
                },
                "since_days": {
                    "type": "integer",
                    "description": "Optional lookback filter in UTC days (1-365).",
                },
                "limit": {"type": "integer", "default": 20},
                "offset": {"type": "integer", "default": 0},
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
        description="List connected integrations, operational mode (mock vs test_credentials), and last sync timestamps.",
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
