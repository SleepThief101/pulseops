from __future__ import annotations

import os
from typing import Any
import uuid

from mcp.server.mcpserver import MCPServer
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.ai.tool_registry import ai_tool_registry, execute_tool_safely
from app.core.auth import ROLE_HIERARCHY
from app.db.session import SessionLocal
from app.models.membership import Membership
from app.services.api_key_service import (
    MCPAuthError,
    MCPAuthorizationError,
    authenticate_api_key,
)

# Transport stays strictly local stdio; network transports (SSE / Streamable HTTP)
# are intentionally not mounted without transport-layer bearer auth middleware.
mcp = MCPServer("PulseOps")

# Overridable session factory for isolated test fixtures
_session_factory = SessionLocal


def _resolve_api_key(api_key: str | None) -> str:
    resolved = (api_key or os.environ.get("PULSEOPS_MCP_API_KEY") or "").strip()
    if not resolved:
        raise MCPAuthError(
            "MCP authentication required: provide an active per-user API key "
            "(argument 'api_key' or PULSEOPS_MCP_API_KEY)."
        )
    return resolved


def _authorize_org_tool(
    db: Session,
    *,
    api_key: str | None,
    organization_id: str,
    tool_name: str,
) -> tuple[uuid.UUID, Membership]:
    """
    Authenticate the caller via hashed per-user API key, resolve their
    Membership in ``organization_id``, and enforce tool-level RBAC.
    """
    raw_key = _resolve_api_key(api_key)
    user, _ = authenticate_api_key(db, raw_key=raw_key)

    try:
        org_uuid = uuid.UUID(str(organization_id))
    except (ValueError, TypeError) as exc:
        raise MCPAuthorizationError("Invalid organization_id UUID.") from exc

    membership = db.scalar(
        select(Membership).where(
            Membership.user_id == user.id,
            Membership.organization_id == org_uuid,
        )
    )
    if membership is None:
        raise MCPAuthorizationError("Organization not found or access denied.")

    tool = ai_tool_registry.get(tool_name)
    if tool.requires_approval:
        raise MCPAuthorizationError(
            "Mutating tools require human-in-the-loop approval and cannot be executed via MCP."
        )

    if ROLE_HIERARCHY.get(membership.role, 0) < ROLE_HIERARCHY.get(tool.min_role, 99):
        raise MCPAuthorizationError(
            f"Insufficient organization role '{membership.role}' for tool '{tool.name}'."
        )

    return org_uuid, membership


@mcp.tool()
def pulseops_list_my_organizations(api_key: str | None = None) -> dict[str, Any]:
    """List only organizations and roles belonging to the authenticated MCP user."""
    raw_key = _resolve_api_key(api_key)
    with _session_factory() as db:
        user, _ = authenticate_api_key(db, raw_key=raw_key)
        memberships = list(
            db.scalars(
                select(Membership)
                .options(joinedload(Membership.organization))
                .where(Membership.user_id == user.id)
                .order_by(Membership.created_at.asc())
            ).all()
        )
        return {
            "user_id": str(user.id),
            "organizations": [
                {
                    "organization_id": str(m.organization_id),
                    "organization_name": m.organization.name,
                    "role": m.role,
                }
                for m in memberships
            ],
        }


@mcp.tool()
def pulseops_metrics_summary(
    organization_id: str,
    days: int = 30,
    api_key: str | None = None,
) -> dict[str, Any]:
    """Read aggregated MRR, churn, GitHub PRs, open issues, and cycle time for an authorized org."""
    with _session_factory() as db:
        org_uuid, membership = _authorize_org_tool(
            db,
            api_key=api_key,
            organization_id=organization_id,
            tool_name="get_metrics_summary",
        )
        tool = ai_tool_registry.get("get_metrics_summary")
        return execute_tool_safely(
            db,
            tool=tool,
            organization_id=org_uuid,
            caller_role=membership.role,
            raw_args={"days": days},
            allow_mutating_execution=False,
        )


@mcp.tool()
def pulseops_recent_events(
    organization_id: str,
    source: str | None = None,
    event_type: str | None = None,
    limit: int = 20,
    api_key: str | None = None,
) -> dict[str, Any]:
    """List recent normalized operational events for an authorized organization."""
    with _session_factory() as db:
        org_uuid, membership = _authorize_org_tool(
            db,
            api_key=api_key,
            organization_id=organization_id,
            tool_name="list_recent_events",
        )
        tool = ai_tool_registry.get("list_recent_events")
        raw_args: dict[str, Any] = {"limit": limit}
        if source is not None:
            raw_args["source"] = source
        if event_type is not None:
            raw_args["event_type"] = event_type
        return execute_tool_safely(
            db,
            tool=tool,
            organization_id=org_uuid,
            caller_role=membership.role,
            raw_args=raw_args,
            allow_mutating_execution=False,
        )


@mcp.tool()
def pulseops_list_integrations(
    organization_id: str,
    api_key: str | None = None,
) -> dict[str, Any]:
    """List integration statuses for an authorized organization without exposing credentials."""
    with _session_factory() as db:
        org_uuid, membership = _authorize_org_tool(
            db,
            api_key=api_key,
            organization_id=organization_id,
            tool_name="list_integrations_status",
        )
        tool = ai_tool_registry.get("list_integrations_status")
        return execute_tool_safely(
            db,
            tool=tool,
            organization_id=org_uuid,
            caller_role=membership.role,
            raw_args={},
            allow_mutating_execution=False,
        )


if __name__ == "__main__":
    mcp.run(transport="stdio")
