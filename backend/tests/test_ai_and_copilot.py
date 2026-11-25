"""
S30–S39 tests covering:
- AI Tool Registry & RBAC/approval metadata (S30)
- MCP Python SDK server tool registration & tenant scoping (S31–S32)
- DeepSeek REST client tool calling & deterministic local fallback (S33–S35)
- Copilot chat endpoint, ActionProposal creation, human-in-the-loop approval/rejection,
  RBAC enforcement, and cross-tenant isolation (S36–S39)
- GET /me/organizations endpoint (S23 bridge)
"""

from __future__ import annotations

import json
import uuid

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.ai import DeepSeekClient, DeepSeekError, ai_tool_registry
from app.core.auth import create_access_token, get_password_hash
from app.core.security import generate_encryption_key
from app.db.session import get_db
from app.main import app
from app.mcp_server import mcp as pulseops_mcp
from app.models.action_proposal import ProposalStatus
from app.models.membership import Membership, MembershipRole
from app.models.organization import Organization
from app.models.user import User

TEST_JWT_SECRET = "unit-test-only-jwt-secret-key-minimum-32-bytes"


@pytest.fixture(autouse=True)
def patch_secrets(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "jwt_secret_key", TEST_JWT_SECRET)
    monkeypatch.setattr(
        settings, "integration_encryption_key", generate_encryption_key()
    )
    monkeypatch.setattr(settings, "deepseek_api_key", None)


@pytest.fixture()
def ai_env(test_engine):
    connection = test_engine.connect()
    transaction = connection.begin()

    def override_get_db():
        session = Session(
            bind=connection,
            join_transaction_mode="create_savepoint",
            expire_on_commit=False,
        )
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    setup_session = Session(
        bind=connection,
        join_transaction_mode="create_savepoint",
        expire_on_commit=False,
    )

    class Env:
        def __init__(self, client: TestClient, session: Session):
            self.client = client
            self.session = session

        def make_org_user(self, role: str = MembershipRole.OWNER.value):
            org = Organization(name=f"AIOrg-{uuid.uuid4().hex[:8]}")
            user = User(
                email=f"ai_{role}_{uuid.uuid4().hex[:8]}@example.com",
                password_hash=get_password_hash("StrongPassword123!"),
            )
            self.session.add_all([org, user])
            self.session.flush()
            self.session.add(
                Membership(
                    user_id=user.id,
                    organization_id=org.id,
                    role=role,
                )
            )
            self.session.flush()
            return org, user, create_access_token(user.id)

        def add_member(self, org: Organization, role: str):
            user = User(
                email=f"ai_{role}_{uuid.uuid4().hex[:8]}@example.com",
                password_hash=get_password_hash("StrongPassword123!"),
            )
            self.session.add(user)
            self.session.flush()
            self.session.add(
                Membership(
                    user_id=user.id,
                    organization_id=org.id,
                    role=role,
                )
            )
            self.session.flush()
            return user, create_access_token(user.id)

    try:
        with TestClient(app, raise_server_exceptions=True) as client:
            yield Env(client, setup_session)
    finally:
        setup_session.close()
        app.dependency_overrides.clear()
        if transaction.is_active:
            transaction.rollback()
        connection.close()


# ---------------------------------------------------------------------------
# S30–S32: Tool Registry & MCP Server
# ---------------------------------------------------------------------------


class TestToolRegistryAndMCP:
    def test_tool_registry_separates_readonly_and_approval_required_tools(self):
        tools = {t.name: t for t in ai_tool_registry.list_tools()}
        assert "get_metrics_summary" in tools
        assert "sync_organization_integration" in tools
        assert "disconnect_integration" in tools

        assert tools["get_metrics_summary"].requires_approval is False
        assert tools["list_integrations_status"].requires_approval is False
        assert tools["sync_organization_integration"].requires_approval is True
        assert tools["disconnect_integration"].requires_approval is True
        assert tools["disconnect_integration"].min_role == MembershipRole.OWNER.value

    @pytest.mark.anyio
    async def test_mcp_server_exposes_pulseops_tools(self):
        mcp_tools = await pulseops_mcp.list_tools()
        names = {t.name for t in mcp_tools}
        assert {
            "pulseops_metrics_summary",
            "pulseops_recent_events",
            "pulseops_list_integrations",
        }.issubset(names)


# ---------------------------------------------------------------------------
# S33–S35: DeepSeek Client & Deterministic Fallback
# ---------------------------------------------------------------------------


class TestDeepSeekAndFallback:
    def test_deepseek_client_fails_safely_when_unconfigured(self):
        client = DeepSeekClient(api_key="")
        assert client.is_configured is False
        with pytest.raises(DeepSeekError, match="DEEPSEEK_API_KEY"):
            client.chat_completions(messages=[{"role": "user", "content": "hi"}])

    def test_deepseek_client_enforces_max_tokens_budget(self):
        captured_payload: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal captured_payload
            captured_payload = json.loads(request.content.decode("utf-8"))
            return httpx.Response(
                200,
                json={"choices": [{"message": {"role": "assistant", "content": "ok"}}]},
            )

        client = DeepSeekClient(
            api_key="sk-test-budget",
            max_tokens=256,
            http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        )
        res = client.chat_completions(messages=[{"role": "user", "content": "hi"}])
        assert res["choices"][0]["message"]["content"] == "ok"
        assert captured_payload["max_tokens"] == 256

    def test_deepseek_tool_loop_intercepts_mutating_tool_as_proposal(
        self, ai_env, monkeypatch
    ):
        from app.services import copilot_service

        org, user, owner_tok = ai_env.make_org_user()
        integ = ai_env.client.post(
            f"/orgs/{org.id}/integrations",
            json={"provider": "fake", "credentials": {}},
            headers={"Authorization": f"Bearer {owner_tok}"},
        ).json()

        call_count = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return httpx.Response(
                    200,
                    json={
                        "choices": [
                            {
                                "message": {
                                    "role": "assistant",
                                    "content": None,
                                    "tool_calls": [
                                        {
                                            "id": "call_1",
                                            "type": "function",
                                            "function": {
                                                "name": "sync_organization_integration",
                                                "arguments": json.dumps(
                                                    {
                                                        "integration_id": integ["id"],
                                                        "full_sync": True,
                                                    }
                                                ),
                                            },
                                        }
                                    ],
                                }
                            }
                        ]
                    },
                )
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "role": "assistant",
                                "content": "I created a pending sync proposal for your review.",
                            }
                        }
                    ]
                },
            )

        ds_client = DeepSeekClient(
            api_key="sk-test-deepseek-mock",
            http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        )
        res = copilot_service.run_copilot_chat(
            ai_env.session,
            organization_id=org.id,
            user_id=user.id,
            message="Please sync my fake connector",
            deepseek_client=ds_client,
        )
        assert res.fallback_mode is False
        assert len(res.pending_proposals) == 1
        assert res.pending_proposals[0].status == ProposalStatus.PENDING.value
        assert res.pending_proposals[0].tool_name == "sync_organization_integration"


# ---------------------------------------------------------------------------
# S36–S39: Copilot Chat, Approval Workflow, RBAC & Tenant Isolation
# ---------------------------------------------------------------------------


class TestCopilotChatAndApprovals:
    def test_me_organizations_and_fallback_copilot_briefing(self, ai_env):
        org, _, owner_tok = ai_env.make_org_user()
        headers = {"Authorization": f"Bearer {owner_tok}"}

        orgs_resp = ai_env.client.get("/me/organizations", headers=headers)
        assert orgs_resp.status_code == 200
        assert len(orgs_resp.json()) == 1
        assert orgs_resp.json()[0]["organization_id"] == str(org.id)
        assert orgs_resp.json()[0]["role"] == "owner"

        # Connect & sync razorpay mock
        integ = ai_env.client.post(
            f"/orgs/{org.id}/integrations",
            json={"provider": "razorpay", "credentials": {"mode": "mock"}},
            headers=headers,
        ).json()
        ai_env.client.post(
            f"/orgs/{org.id}/integrations/{integ['id']}/sync",
            headers=headers,
        )

        # Ask Copilot for KPI summary (uses deterministic fallback when key unset)
        chat_resp = ai_env.client.post(
            f"/orgs/{org.id}/copilot/chat",
            json={"message": "Summarize our MRR and churn"},
            headers=headers,
        )
        assert chat_resp.status_code == 200
        body = chat_resp.json()
        assert body["fallback_mode"] is True
        assert "Net MRR:" in body["reply"]
        assert body["pending_proposals"] == []

    def test_propose_sync_and_approve_executes_tool(self, ai_env):
        org, _, owner_tok = ai_env.make_org_user()
        headers = {"Authorization": f"Bearer {owner_tok}"}

        ai_env.client.post(
            f"/orgs/{org.id}/integrations",
            json={"provider": "razorpay", "credentials": {"mode": "mock"}},
            headers=headers,
        )

        chat_resp = ai_env.client.post(
            f"/orgs/{org.id}/copilot/chat",
            json={"message": "Please sync my razorpay integration"},
            headers=headers,
        )
        assert chat_resp.status_code == 200
        proposals = chat_resp.json()["pending_proposals"]
        assert len(proposals) == 1
        proposal_id = proposals[0]["id"]
        assert proposals[0]["status"] == "pending"

        # Approve & execute
        approve_resp = ai_env.client.post(
            f"/orgs/{org.id}/copilot/proposals/{proposal_id}/decision",
            json={"decision": "approve"},
            headers=headers,
        )
        assert approve_resp.status_code == 200
        resolved = approve_resp.json()
        assert resolved["status"] == "executed"
        assert resolved["execution_result"]["inserted_count"] == 5

        # Deciding again must fail with 409 Conflict
        dup_resp = ai_env.client.post(
            f"/orgs/{org.id}/copilot/proposals/{proposal_id}/decision",
            json={"decision": "reject"},
            headers=headers,
        )
        assert dup_resp.status_code == 409

    def test_proposal_rejection_rbac_and_cross_tenant_isolation(self, ai_env):
        org_a, _, owner_a = ai_env.make_org_user()
        _, viewer_a = ai_env.add_member(org_a, MembershipRole.VIEWER.value)
        _, _, owner_b = ai_env.make_org_user()

        h_a = {"Authorization": f"Bearer {owner_a}"}
        ai_env.client.post(
            f"/orgs/{org_a.id}/integrations",
            json={"provider": "fake", "credentials": {}},
            headers=h_a,
        )

        chat_resp = ai_env.client.post(
            f"/orgs/{org_a.id}/copilot/chat",
            json={"message": "Sync fake connector"},
            headers=h_a,
        )
        proposal_id = chat_resp.json()["pending_proposals"][0]["id"]

        # Viewer cannot approve/reject -> 403
        assert (
            ai_env.client.post(
                f"/orgs/{org_a.id}/copilot/proposals/{proposal_id}/decision",
                json={"decision": "approve"},
                headers={"Authorization": f"Bearer {viewer_a}"},
            ).status_code
            == 403
        )

        # Cross-tenant Org B owner gets 404
        h_b = {"Authorization": f"Bearer {owner_b}"}
        assert (
            ai_env.client.get(
                f"/orgs/{org_a.id}/copilot/proposals", headers=h_b
            ).status_code
            == 404
        )
        assert (
            ai_env.client.post(
                f"/orgs/{org_a.id}/copilot/proposals/{proposal_id}/decision",
                json={"decision": "approve"},
                headers=h_b,
            ).status_code
            == 404
        )

        # Owner A rejects cleanly
        rej_resp = ai_env.client.post(
            f"/orgs/{org_a.id}/copilot/proposals/{proposal_id}/decision",
            json={"decision": "reject"},
            headers=h_a,
        )
        assert rej_resp.status_code == 200
        assert rej_resp.json()["status"] == "rejected"

    def test_fallback_disconnect_proposal_enforces_owner_role(self, ai_env):
        org, _, owner_tok = ai_env.make_org_user(MembershipRole.OWNER.value)
        _, member_tok = ai_env.add_member(org, MembershipRole.MEMBER.value)
        h_owner = {"Authorization": f"Bearer {owner_tok}"}
        h_member = {"Authorization": f"Bearer {member_tok}"}

        ai_env.client.post(
            f"/orgs/{org.id}/integrations",
            json={"provider": "fake", "credentials": {}},
            headers=h_owner,
        )

        member_resp = ai_env.client.post(
            f"/orgs/{org.id}/copilot/chat",
            json={"message": "Disconnect fake integration"},
            headers=h_member,
        )
        assert member_resp.status_code == 200
        assert member_resp.json()["pending_proposals"] == []
        assert "Permission denied" in member_resp.json()["reply"]

        owner_resp = ai_env.client.post(
            f"/orgs/{org.id}/copilot/chat",
            json={"message": "Disconnect fake integration"},
            headers=h_owner,
        )
        assert owner_resp.status_code == 200
        proposals = owner_resp.json()["pending_proposals"]
        assert len(proposals) == 1
        assert proposals[0]["tool_name"] == "disconnect_integration"
        assert proposals[0]["status"] == ProposalStatus.PENDING.value
