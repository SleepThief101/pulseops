from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timezone
import hashlib
import json
import logging
from typing import Any
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.deepseek_client import DeepSeekClient, DeepSeekError
from app.ai.tool_registry import (
    ToolArgumentValidationError,
    ToolDefinition,
    ToolSecurityError,
    ai_tool_registry,
    execute_tool_safely,
)
from app.config import settings
from app.core.auth import ROLE_HIERARCHY
from app.core.rate_limit import get_redis_client
from app.models.action_proposal import ActionProposal, ProposalStatus
from app.models.membership import Membership
from app.schemas.copilot import (
    CopilotChatResponse,
    CopilotProposalResponse,
    CopilotToolExecutionRecord,
)
from app.services import audit_service, integration_service

logger = logging.getLogger("app.copilot")


class ProposalNotFoundError(Exception):
    """Raised when an ActionProposal does not exist in the tenant organization."""


class ProposalConflictError(Exception):
    """Raised when attempting to decide a non-pending ActionProposal."""


class ProposalPermissionError(Exception):
    """Raised when reviewer lacks the minimum role required by the proposed tool."""


def _create_proposal(
    db: Session,
    *,
    organization_id: uuid.UUID,
    user_id: uuid.UUID,
    tool: ToolDefinition,
    arguments: dict[str, Any],
    title: str,
    description: str,
) -> ActionProposal:
    proposal = ActionProposal(
        organization_id=organization_id,
        proposed_by_user_id=user_id,
        tool_name=tool.name,
        title=title,
        description=description,
        arguments=arguments,
        status=ProposalStatus.PENDING.value,
    )
    db.add(proposal)
    db.flush()
    audit_service.record_audit_event(
        db,
        organization_id=organization_id,
        user_id=user_id,
        action="copilot.proposal_created",
        resource_type="action_proposal",
        resource_id=str(proposal.id),
        details={"tool_name": tool.name, "title": title},
    )
    return proposal


def _copilot_cache_key(
    *,
    organization_id: uuid.UUID,
    model_key: str,
    message: str,
) -> str:
    version = "0"
    try:
        raw_v = get_redis_client().get(f"pulseops:copilot:version:{organization_id}")
        if raw_v is not None:
            version = str(raw_v)
    except Exception:
        pass
    digest = hashlib.sha256(
        f"{model_key}|{message.strip().lower()}".encode("utf-8")
    ).hexdigest()
    return f"pulseops:copilot:resp:{organization_id}:v{version}:{digest}"


def _get_cached_copilot_response(
    *,
    organization_id: uuid.UUID,
    model_key: str,
    message: str,
) -> CopilotChatResponse | None:
    ttl = int(settings.copilot_cache_ttl_seconds)
    if ttl <= 0:
        return None
    try:
        key = _copilot_cache_key(
            organization_id=organization_id,
            model_key=model_key,
            message=message,
        )
        raw = get_redis_client().get(key)
        if not raw:
            return None
        parsed = CopilotChatResponse.model_validate_json(raw)
        return parsed.model_copy(update={"cached": True})
    except Exception:
        return None


def _store_cached_copilot_response(
    *,
    organization_id: uuid.UUID,
    model_key: str,
    message: str,
    response: CopilotChatResponse,
) -> None:
    ttl = int(settings.copilot_cache_ttl_seconds)
    if ttl <= 0 or response.pending_proposals:
        return
    try:
        key = _copilot_cache_key(
            organization_id=organization_id,
            model_key=model_key,
            message=message,
        )
        get_redis_client().setex(key, ttl, response.model_dump_json())
    except Exception:
        pass


def _resolve_caller_role(
    db: Session,
    *,
    organization_id: uuid.UUID,
    user_id: uuid.UUID,
    caller_role: str | None = None,
) -> str:
    """Resolve and verify active organization membership role from PostgreSQL."""
    membership = db.scalar(
        select(Membership).where(
            Membership.organization_id == organization_id,
            Membership.user_id == user_id,
        )
    )
    if membership is None:
        raise ProposalPermissionError(
            "User is not an active member of this organization."
        )
    if caller_role is not None and caller_role != membership.role:
        raise ProposalPermissionError("Membership role mismatch.")
    return membership.role


def run_copilot_chat(
    db: Session,
    *,
    organization_id: uuid.UUID,
    user_id: uuid.UUID,
    message: str,
    caller_role: str | None = None,
    deepseek_client: DeepSeekClient | None = None,
) -> CopilotChatResponse:
    """
    Process a user prompt using DeepSeek (with safe read-only tool calls,
    response caching, and pending proposals for authorized mutating tools) or
    deterministic local fallback when DEEPSEEK_API_KEY is absent.
    """
    resolved_role = _resolve_caller_role(
        db,
        organization_id=organization_id,
        user_id=user_id,
        caller_role=caller_role,
    )
    client = deepseek_client or DeepSeekClient()
    executed_tools: list[CopilotToolExecutionRecord] = []
    created_proposals: list[ActionProposal] = []
    base_model_key = client.model if client.is_configured else "pulseops-deterministic-fallback"
    cache_model_key = f"{base_model_key}:{resolved_role}"

    cached = _get_cached_copilot_response(
        organization_id=organization_id,
        model_key=cache_model_key,
        message=message,
    )
    if cached is not None:
        return cached

    if client.is_configured:
        try:
            reply = _run_deepseek_tool_loop(
                db=db,
                client=client,
                organization_id=organization_id,
                user_id=user_id,
                caller_role=resolved_role,
                message=message,
                executed_tools=executed_tools,
                created_proposals=created_proposals,
            )
            db.commit()
            for p in created_proposals:
                db.refresh(p)
            response = CopilotChatResponse(
                reply=reply,
                model_used=client.model,
                fallback_mode=False,
                cached=False,
                tool_calls_executed=executed_tools,
                pending_proposals=[
                    CopilotProposalResponse.model_validate(p) for p in created_proposals
                ],
            )
            _store_cached_copilot_response(
                organization_id=organization_id,
                model_key=cache_model_key,
                message=message,
                response=response,
            )
            return response
        except DeepSeekError:
            # Fall back transparently to local deterministic mode
            pass

    reply = _run_deterministic_fallback(
        db=db,
        organization_id=organization_id,
        user_id=user_id,
        caller_role=resolved_role,
        message=message,
        executed_tools=executed_tools,
        created_proposals=created_proposals,
    )
    db.commit()
    for p in created_proposals:
        db.refresh(p)

    response = CopilotChatResponse(
        reply=reply,
        model_used="pulseops-deterministic-fallback",
        fallback_mode=True,
        cached=False,
        tool_calls_executed=executed_tools,
        pending_proposals=[
            CopilotProposalResponse.model_validate(p) for p in created_proposals
        ],
    )
    _store_cached_copilot_response(
        organization_id=organization_id,
        model_key=f"pulseops-deterministic-fallback:{resolved_role}",
        message=message,
        response=response,
    )
    return response


def prepare_copilot_stream(
    db: Session,
    *,
    organization_id: uuid.UUID,
    user_id: uuid.UUID,
    message: str,
    caller_role: str | None = None,
    deepseek_client: DeepSeekClient | None = None,
) -> Iterator[str]:
    """
    Execute all DB-backed tool calls and proposal writes synchronously while the
    request DB session is open, then return an SSE token iterator for streaming.
    Uses DeepSeek streaming when DEEPSEEK_API_KEY is configured and falls back
    cleanly to deterministic local output when unconfigured.
    """
    resolved_role = _resolve_caller_role(
        db,
        organization_id=organization_id,
        user_id=user_id,
        caller_role=caller_role,
    )
    client = deepseek_client or DeepSeekClient()
    base_model_key = (
        client.model if client.is_configured else "pulseops-deterministic-fallback"
    )
    cache_model_key = f"{base_model_key}:{resolved_role}"
    cached = _get_cached_copilot_response(
        organization_id=organization_id,
        model_key=cache_model_key,
        message=message,
    )
    if cached is not None:
        return _yield_chunked_sse(cached)

    executed_tools: list[CopilotToolExecutionRecord] = []
    created_proposals: list[ActionProposal] = []

    if client.is_configured:
        try:
            messages, executed_all = _execute_deepseek_tool_rounds(
                db=db,
                client=client,
                organization_id=organization_id,
                user_id=user_id,
                caller_role=resolved_role,
                message=message,
                executed_tools=executed_tools,
                created_proposals=created_proposals,
            )
            if executed_all is not None:
                db.commit()
                for p in created_proposals:
                    db.refresh(p)
                resp = CopilotChatResponse(
                    reply=executed_all,
                    model_used=client.model,
                    fallback_mode=False,
                    cached=False,
                    tool_calls_executed=executed_tools,
                    pending_proposals=[
                        CopilotProposalResponse.model_validate(p)
                        for p in created_proposals
                    ],
                )
                _store_cached_copilot_response(
                    organization_id=organization_id,
                    model_key=cache_model_key,
                    message=message,
                    response=resp,
                )
                return _yield_chunked_sse(resp)

            db.commit()
            for p in created_proposals:
                db.refresh(p)
            proposals_snapshot = [
                CopilotProposalResponse.model_validate(p) for p in created_proposals
            ]
            tools_snapshot = list(executed_tools)

            def _stream_live() -> Iterator[str]:
                chunks: list[str] = []
                try:
                    for token in client.stream_chat_completions(messages=messages):
                        chunks.append(token)
                        yield f"data: {json.dumps({'type': 'token', 'content': token})}\n\n"
                except DeepSeekError as exc:
                    err_text = f"Streaming interrupted: {exc}"
                    chunks.append(err_text)
                    yield f"data: {json.dumps({'type': 'token', 'content': err_text})}\n\n"

                full_reply = "".join(chunks) or "Completed analysis."
                resp = CopilotChatResponse(
                    reply=full_reply,
                    model_used=client.model,
                    fallback_mode=False,
                    cached=False,
                    tool_calls_executed=tools_snapshot,
                    pending_proposals=proposals_snapshot,
                )
                _store_cached_copilot_response(
                    organization_id=organization_id,
                    model_key=cache_model_key,
                    message=message,
                    response=resp,
                )
                yield f"data: {json.dumps({'type': 'done', 'response': resp.model_dump(mode='json')})}\n\n"

            return _stream_live()
        except DeepSeekError:
            pass

    resp = run_copilot_chat(
        db,
        organization_id=organization_id,
        user_id=user_id,
        message=message,
        caller_role=resolved_role,
        deepseek_client=DeepSeekClient(api_key=""),
    )
    return _yield_chunked_sse(resp)


def _yield_chunked_sse(resp: CopilotChatResponse) -> Iterator[str]:
    lines = resp.reply.splitlines(keepends=True) or [resp.reply]
    for chunk in lines:
        yield f"data: {json.dumps({'type': 'token', 'content': chunk})}\n\n"
    yield f"data: {json.dumps({'type': 'done', 'response': resp.model_dump(mode='json')})}\n\n"


def _execute_deepseek_tool_rounds(
    *,
    db: Session,
    client: DeepSeekClient,
    organization_id: uuid.UUID,
    user_id: uuid.UUID,
    caller_role: str,
    message: str,
    executed_tools: list[CopilotToolExecutionRecord],
    created_proposals: list[ActionProposal],
) -> tuple[list[dict[str, Any]], str | None]:
    messages: list[dict[str, Any]] = [
        {
            "role": "system",
            "content": (
                "You are PulseOps Copilot, an AI operations assistant for SaaS teams. "
                "Use tools strictly for factual metrics and integrations. "
                "Mutating actions always require human approval."
            ),
        },
        {"role": "user", "content": message},
    ]
    tools_schema = ai_tool_registry.openai_tools_schema()
    max_rounds = max(1, int(settings.deepseek_max_tool_rounds))

    for _ in range(max_rounds):
        raw_resp = client.chat_completions(messages=messages, tools=tools_schema)
        choice = (raw_resp.get("choices") or [{}])[0]
        assistant_msg = choice.get("message") or {}
        tool_calls = assistant_msg.get("tool_calls") or []

        if not tool_calls:
            return messages, str(
                assistant_msg.get("content") or "No response generated."
            )

        messages.append(assistant_msg)
        for tc in tool_calls:
            fn = tc.get("function") or {}
            tool_name = str(fn.get("name") or "")
            raw_args = fn.get("arguments") or "{}"
            try:
                args = (
                    json.loads(raw_args)
                    if isinstance(raw_args, str)
                    else dict(raw_args)
                )
            except (json.JSONDecodeError, TypeError, ValueError):
                tool_result = {"error": f"Malformed JSON arguments for tool: {tool_name}"}
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.get("id"),
                        "content": json.dumps(tool_result),
                    }
                )
                continue

            try:
                tool = ai_tool_registry.get(tool_name)
            except KeyError:
                tool_result = {"error": f"Unknown tool: {tool_name}"}
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.get("id"),
                        "content": json.dumps(tool_result),
                    }
                )
                continue

            # Enforce tool-level role requirement BEFORE argument execution or proposal persistence
            if ROLE_HIERARCHY.get(caller_role, 0) < ROLE_HIERARCHY.get(tool.min_role, 99):
                logger.warning(
                    "Blocked AI tool call due to insufficient role",
                    extra={
                        "org_id": str(organization_id),
                        "user_id": str(user_id),
                        "tool_name": tool.name,
                        "caller_role": caller_role,
                        "min_role": tool.min_role,
                    },
                )
                tool_result = {
                    "error": (
                        f"Permission denied: role '{caller_role}' cannot invoke or propose "
                        f"'{tool.name}' (requires '{tool.min_role}')."
                    )
                }
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.get("id"),
                        "content": json.dumps(tool_result),
                    }
                )
                continue

            # Strictly validate arguments and reject reserved context/unexpected keys
            try:
                validated_args = tool.validate_arguments(args)
            except ToolArgumentValidationError as exc:
                logger.warning(
                    "Rejected suspicious or invalid AI tool arguments",
                    extra={
                        "org_id": str(organization_id),
                        "user_id": str(user_id),
                        "tool_name": tool.name,
                        "reason": str(exc),
                    },
                )
                tool_result = {"error": f"Rejected invalid tool arguments: {exc}"}
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.get("id"),
                        "content": json.dumps(tool_result),
                    }
                )
                continue

            if tool.requires_approval:
                proposal = _create_proposal(
                    db,
                    organization_id=organization_id,
                    user_id=user_id,
                    tool=tool,
                    arguments=validated_args,
                    title=f"Execute {tool.name}",
                    description=(
                        f"AI Copilot proposed executing `{tool.name}` "
                        f"with validated arguments {validated_args}."
                    ),
                )
                created_proposals.append(proposal)
                tool_result = {
                    "status": "pending_approval",
                    "proposal_id": str(proposal.id),
                    "message": "Created pending proposal awaiting human approval.",
                }
            else:
                tool_result = execute_tool_safely(
                    db,
                    tool=tool,
                    organization_id=organization_id,
                    caller_role=caller_role,
                    raw_args=validated_args,
                    allow_mutating_execution=False,
                )
                executed_tools.append(
                    CopilotToolExecutionRecord(tool_name=tool.name, result=tool_result)
                )

            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.get("id"),
                    "content": json.dumps(tool_result),
                }
            )

    return messages, None


def _run_deepseek_tool_loop(
    *,
    db: Session,
    client: DeepSeekClient,
    organization_id: uuid.UUID,
    user_id: uuid.UUID,
    caller_role: str,
    message: str,
    executed_tools: list[CopilotToolExecutionRecord],
    created_proposals: list[ActionProposal],
) -> str:
    messages, direct_reply = _execute_deepseek_tool_rounds(
        db=db,
        client=client,
        organization_id=organization_id,
        user_id=user_id,
        caller_role=caller_role,
        message=message,
        executed_tools=executed_tools,
        created_proposals=created_proposals,
    )
    if direct_reply is not None:
        return direct_reply

    final_resp = client.chat_completions(messages=messages)
    final_msg = ((final_resp.get("choices") or [{}])[0]).get("message") or {}
    return str(final_msg.get("content") or "Completed analysis.")


def _run_deterministic_fallback(
    *,
    db: Session,
    organization_id: uuid.UUID,
    user_id: uuid.UUID,
    caller_role: str,
    message: str,
    executed_tools: list[CopilotToolExecutionRecord],
    created_proposals: list[ActionProposal],
) -> str:
    lower = message.lower()

    summary_tool = ai_tool_registry.get("get_metrics_summary")
    summary = execute_tool_safely(
        db,
        tool=summary_tool,
        organization_id=organization_id,
        caller_role=caller_role,
        raw_args={"days": 30},
        allow_mutating_execution=False,
    )
    executed_tools.append(
        CopilotToolExecutionRecord(tool_name=summary_tool.name, result=summary)
    )

    integ_tool = ai_tool_registry.get("list_integrations_status")
    integ_status = execute_tool_safely(
        db,
        tool=integ_tool,
        organization_id=organization_id,
        caller_role=caller_role,
        raw_args={},
        allow_mutating_execution=False,
    )
    executed_tools.append(
        CopilotToolExecutionRecord(tool_name=integ_tool.name, result=integ_status)
    )

    # Detect mutating intent ("sync" or "disconnect") -> NEVER auto-execute; propose only for authorized roles!
    if any(kw in lower for kw in ("sync", "refresh", "pull latest")):
        sync_tool = ai_tool_registry.get("sync_organization_integration")
        if ROLE_HIERARCHY.get(caller_role, 0) < ROLE_HIERARCHY.get(
            sync_tool.min_role, 99
        ):
            return (
                f"Permission denied: role '{caller_role}' is read-only and cannot "
                "create integration sync proposals (member or owner role required)."
            )

        integrations = integration_service.list_integrations(
            db, organization_id=organization_id
        )
        if integrations:
            target = integrations[0]
            for integ in integrations:
                if integ.provider in lower:
                    target = integ
                    break
            validated_args = sync_tool.validate_arguments(
                {"integration_id": str(target.id), "full_sync": False}
            )
            proposal = _create_proposal(
                db,
                organization_id=organization_id,
                user_id=user_id,
                tool=sync_tool,
                arguments=validated_args,
                title=f"Sync {target.provider} integration",
                description=(
                    f"Proposed syncing `{target.provider}` ({target.id}) to ingest recent events."
                ),
            )
            created_proposals.append(proposal)
            return (
                f"Created pending approval proposal to sync your `{target.provider}` integration "
                f"(Proposal ID: {proposal.id}). Review and approve it in Action Approvals."
            )
        return (
            "No integrations are currently connected to this organization. "
            "Connect Razorpay, GitHub, or Fake connector in Integrations first."
        )

    mrr_dollars = summary["mrr_cents"] / 100.0
    arr_dollars = summary["arr_cents"] / 100.0
    cycle = summary["avg_issue_cycle_time_hours"]
    cycle_str = f"{cycle}h" if cycle is not None else "N/A"
    providers = [i["provider"] for i in integ_status["integrations"]]
    providers_str = ", ".join(providers) if providers else "none"

    return (
        f"PulseOps Operational Briefing (Last 30 days):\n"
        f"- Net MRR: ${mrr_dollars:,.2f} (ARR: ${arr_dollars:,.2f})\n"
        f"- Churn Rate: {summary['churn_rate_pct']}% ({summary['churned_subscriptions_count']} churned)\n"
        f"- GitHub PRs: {summary['prs_merged']} merged / {summary['prs_opened']} opened\n"
        f"- Open Issues: {summary['open_issues_count']} open ({summary['issues_closed_count']} closed, avg cycle time: {cycle_str})\n"
        f"- Connected Integrations: {providers_str}"
    )


def list_proposals(
    db: Session,
    *,
    organization_id: uuid.UUID,
    limit: int = 50,
) -> list[ActionProposal]:
    """List ActionProposals strictly scoped to ``organization_id``."""
    return list(
        db.scalars(
            select(ActionProposal)
            .where(ActionProposal.organization_id == organization_id)
            .order_by(ActionProposal.created_at.desc())
            .limit(limit)
        ).all()
    )


def decide_proposal(
    db: Session,
    *,
    organization_id: uuid.UUID,
    proposal_id: uuid.UUID,
    reviewer_user_id: uuid.UUID,
    reviewer_role: str,
    decision: str,
) -> ActionProposal:
    """
    Approve or reject a pending ActionProposal strictly within ``organization_id``.
    Executing an approved proposal invokes the registered tool with verified org scope.
    """
    proposal = db.scalar(
        select(ActionProposal).where(
            ActionProposal.id == proposal_id,
            ActionProposal.organization_id == organization_id,
        )
    )
    if proposal is None:
        raise ProposalNotFoundError("Action proposal not found.")

    if proposal.status != ProposalStatus.PENDING.value:
        raise ProposalConflictError(
            f"Proposal is already resolved with status {proposal.status!r}."
        )

    verified_role = _resolve_caller_role(
        db,
        organization_id=organization_id,
        user_id=reviewer_user_id,
        caller_role=reviewer_role,
    )

    tool = ai_tool_registry.get(proposal.tool_name)
    if ROLE_HIERARCHY.get(verified_role, 0) < ROLE_HIERARCHY.get(tool.min_role, 99):
        raise ProposalPermissionError(
            f"Role {tool.min_role!r} or higher is required to resolve {tool.name!r}."
        )

    now = datetime.now(timezone.utc)
    proposal.reviewed_by_user_id = reviewer_user_id
    proposal.reviewed_at = now

    if decision == "reject":
        proposal.status = ProposalStatus.REJECTED.value
        audit_service.record_audit_event(
            db,
            organization_id=organization_id,
            user_id=reviewer_user_id,
            action="copilot.proposal_rejected",
            resource_type="action_proposal",
            resource_id=str(proposal.id),
            details={"tool_name": proposal.tool_name},
        )
        db.commit()
        db.refresh(proposal)
        return proposal

    try:
        result = execute_tool_safely(
            db,
            tool=tool,
            organization_id=organization_id,
            caller_role=verified_role,
            raw_args=dict(proposal.arguments or {}),
            allow_mutating_execution=True,
        )
        proposal.status = ProposalStatus.EXECUTED.value
        proposal.execution_result = result
    except (ToolSecurityError, Exception) as exc:
        proposal.status = ProposalStatus.FAILED.value
        proposal.execution_result = {"error": str(exc)}

    audit_service.record_audit_event(
        db,
        organization_id=organization_id,
        user_id=reviewer_user_id,
        action="copilot.proposal_approved",
        resource_type="action_proposal",
        resource_id=str(proposal.id),
        details={"tool_name": proposal.tool_name, "status": proposal.status},
    )
    db.commit()
    db.refresh(proposal)
    return proposal
