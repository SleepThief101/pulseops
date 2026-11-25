"""
Phase 3 Security Hardening & Adversarial Tests:
- Per-user hashed MCP API keys: issuance, listing, revocation, expiry, and tenant isolation
- AI tool strict argument validation, reserved context key injection blocking,
  viewer/member RBAC on proposals, and approval-bypass prevention
- Webhook replay timestamps, delivery ID deduplication, signature-before-dedup invariant
- Rate-limit bypass resistance (X-Forwarded-For & email case normalization)
- Credential & token sanitization in structured JSON logs and AuditLog details
- JWT required claims enforcement (sub, exp, iat)
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import logging
import uuid

import httpx
import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.deepseek_client import DeepSeekClient
from app.ai.tool_registry import (
    ToolApprovalRequiredError,
    ToolArgumentValidationError,
    ai_tool_registry,
    execute_tool_safely,
)
from app.config import settings
from app.core.auth import JWT_ALGORITHM, create_access_token, get_password_hash
from app.core.logging import StructuredJsonFormatter, sanitize_log_message
from app.core.rate_limit import get_redis_client
from app.core.security import generate_encryption_key
from app.db.session import get_db
from app.main import app
from app.models.action_proposal import ActionProposal, ProposalStatus
from app.models.api_key import ApiKey
from app.models.audit_log import AuditLog
from app.models.membership import Membership, MembershipRole
from app.models.organization import Organization
from app.models.user import User
from app.services import api_key_service, audit_service, copilot_service
from app.services.api_key_service import MCPAuthError, MCPAuthorizationError

TEST_JWT_SECRET = "test-jwt-secret-key-for-phase3-security-hardening-tests"


@pytest.fixture(autouse=True)
def patch_secrets(monkeypatch):
    monkeypatch.setattr(settings, "jwt_secret_key", TEST_JWT_SECRET)
    monkeypatch.setattr(
        settings, "integration_encryption_key", generate_encryption_key()
    )
    monkeypatch.setattr(settings, "deepseek_api_key", None)


@pytest.fixture()
def sec_env(test_engine):
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

        @contextmanager
        def mcp_session_factory(self):
            s = Session(
                bind=connection,
                join_transaction_mode="create_savepoint",
                expire_on_commit=False,
            )
            try:
                yield s
            finally:
                s.close()

        def make_org_user(self, role: str = MembershipRole.OWNER.value):
            org = Organization(name=f"SecOrg-{uuid.uuid4().hex[:8]}")
            user = User(
                email=f"sec_{role}_{uuid.uuid4().hex[:8]}@example.com",
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
                email=f"sec_{role}_{uuid.uuid4().hex[:8]}@example.com",
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
# 1. MCP API Key Lifecycle, Auth, Revocation & Tenant Isolation
# ---------------------------------------------------------------------------


class TestMCPAuthAndIsolation:
    def test_api_key_lifecycle_hashed_storage_and_cross_user_isolation(self, sec_env):
        _, user_a, tok_a = sec_env.make_org_user()
        _, _, tok_b = sec_env.make_org_user()
        h_a = {"Authorization": f"Bearer {tok_a}"}
        h_b = {"Authorization": f"Bearer {tok_b}"}

        # Unauthenticated -> 401
        assert sec_env.client.get("/me/api-keys").status_code == 401
        assert (
            sec_env.client.post("/me/api-keys", json={"name": "unauth"}).status_code
            == 401
        )

        # Create key returns plaintext ONCE
        create_resp = sec_env.client.post(
            "/me/api-keys",
            json={"name": "Local Claude Stdio", "expires_in_days": 30},
            headers=h_a,
        )
        assert create_resp.status_code == 201
        created = create_resp.json()
        raw_key = created["api_key"]
        assert raw_key.startswith("pmcp_")
        assert created["key_prefix"] == raw_key[:13]

        # DB stores SHA-256 hash only, never plaintext
        db_row = sec_env.session.get(ApiKey, uuid.UUID(created["id"]))
        assert db_row is not None
        assert db_row.key_hash != raw_key
        assert db_row.key_hash == hashlib.sha256(raw_key.encode("utf-8")).hexdigest()

        # Listing keys NEVER exposes plaintext or key_hash
        list_resp = sec_env.client.get("/me/api-keys", headers=h_a)
        assert list_resp.status_code == 200
        assert len(list_resp.json()) == 1
        assert raw_key not in list_resp.text
        assert "key_hash" not in list_resp.text

        # User B cannot see or revoke User A's API key (404)
        assert sec_env.client.get("/me/api-keys", headers=h_b).json() == []
        assert (
            sec_env.client.delete(
                f"/me/api-keys/{created['id']}", headers=h_b
            ).status_code
            == 404
        )

        # User A revokes own key cleanly
        rev_resp = sec_env.client.delete(
            f"/me/api-keys/{created['id']}", headers=h_a
        )
        assert rev_resp.status_code == 200
        assert rev_resp.json()["revoked_at"] is not None

    def test_mcp_server_enforces_api_key_auth_revocation_and_tenant_isolation(
        self, sec_env, monkeypatch
    ):
        from app import mcp_server

        monkeypatch.setattr(mcp_server, "_session_factory", sec_env.mcp_session_factory)
        monkeypatch.delenv("PULSEOPS_MCP_API_KEY", raising=False)

        org_a, user_a, tok_a = sec_env.make_org_user()
        org_b, _, _ = sec_env.make_org_user()

        issued = sec_env.client.post(
            "/me/api-keys",
            json={"name": "MCP Auth Key"},
            headers={"Authorization": f"Bearer {tok_a}"},
        ).json()
        key_id = uuid.UUID(issued["id"])
        raw_key = issued["api_key"]

        # 1. Missing or invalid key rejected
        with pytest.raises(MCPAuthError):
            mcp_server.pulseops_metrics_summary(str(org_a.id))
        with pytest.raises(MCPAuthError):
            mcp_server.pulseops_metrics_summary(str(org_a.id), api_key="pmcp_bogus_key")

        # 2. Valid key resolves only User A's orgs
        my_orgs = mcp_server.pulseops_list_my_organizations(api_key=raw_key)
        assert [o["organization_id"] for o in my_orgs["organizations"]] == [str(org_a.id)]

        # 3. Valid key accesses Org A cleanly
        metrics_a = mcp_server.pulseops_metrics_summary(str(org_a.id), api_key=raw_key)
        assert metrics_a["organization_id"] == str(org_a.id)
        events_a = mcp_server.pulseops_recent_events(str(org_a.id), api_key=raw_key)
        assert events_a["count"] == 0
        integ_a = mcp_server.pulseops_list_integrations(str(org_a.id), api_key=raw_key)
        assert integ_a["count"] == 0

        # 4. Supplying Org B's UUID with User A's valid key is strictly rejected
        with pytest.raises(MCPAuthorizationError):
            mcp_server.pulseops_metrics_summary(str(org_b.id), api_key=raw_key)
        with pytest.raises(MCPAuthorizationError):
            mcp_server.pulseops_recent_events(str(org_b.id), api_key=raw_key)
        with pytest.raises(MCPAuthorizationError):
            mcp_server.pulseops_list_integrations(str(org_b.id), api_key=raw_key)

        # 5. Mutating tool cannot be authorized via MCP
        with pytest.raises(MCPAuthorizationError):
            mcp_server._authorize_org_tool(
                sec_env.session,
                api_key=raw_key,
                organization_id=str(org_a.id),
                tool_name="sync_organization_integration",
            )

        # 6. Revoked key is immediately rejected
        assert (
            sec_env.client.delete(
                f"/me/api-keys/{key_id}",
                headers={"Authorization": f"Bearer {tok_a}"},
            ).status_code
            == 200
        )
        with pytest.raises(MCPAuthError, match="revoked"):
            mcp_server.pulseops_metrics_summary(str(org_a.id), api_key=raw_key)

        # 7. Expired key is rejected
        expired_rec, expired_raw = api_key_service.create_api_key(
            sec_env.session, user_id=user_a.id, name="Expired Key"
        )
        expired_rec.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        sec_env.session.flush()
        with pytest.raises(MCPAuthError, match="expired"):
            mcp_server.pulseops_metrics_summary(str(org_a.id), api_key=expired_raw)


# ---------------------------------------------------------------------------
# 2. AI Tool Execution Security & Approval Bypass Prevention
# ---------------------------------------------------------------------------


class TestAIToolExecutionSecurity:
    def test_llm_reserved_and_unexpected_argument_injection_blocked(self, sec_env):
        org_a, user_a, _ = sec_env.make_org_user()
        org_b, _, _ = sec_env.make_org_user()

        step = {"idx": 0}
        tool_responses: list[dict] = []

        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content.decode("utf-8"))
            for msg in body["messages"]:
                if msg.get("role") == "tool":
                    tool_responses.append(json.loads(msg["content"]))

            step["idx"] += 1
            if step["idx"] == 1:
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
                                            "id": "inj_org",
                                            "type": "function",
                                            "function": {
                                                "name": "get_metrics_summary",
                                                "arguments": json.dumps(
                                                    {"days": 30, "organization_id": str(org_b.id)}
                                                ),
                                            },
                                        },
                                        {
                                            "id": "inj_db",
                                            "type": "function",
                                            "function": {
                                                "name": "get_metrics_summary",
                                                "arguments": json.dumps(
                                                    {"days": 30, "db": "evil"}
                                                ),
                                            },
                                        },
                                        {
                                            "id": "inj_extra",
                                            "type": "function",
                                            "function": {
                                                "name": "list_recent_events",
                                                "arguments": json.dumps(
                                                    {"limit": 10, "sql_override": "1=1"}
                                                ),
                                            },
                                        },
                                    ],
                                }
                            }
                        ]
                    },
                )
            return httpx.Response(
                200,
                json={"choices": [{"message": {"role": "assistant", "content": "Rejected invalid tool calls."}}]},
            )

        ds = DeepSeekClient(
            api_key="sk-test-injection",
            http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        )
        res = copilot_service.run_copilot_chat(
            sec_env.session,
            organization_id=org_a.id,
            user_id=user_a.id,
            message="Run injected tools",
            caller_role=MembershipRole.OWNER.value,
            deepseek_client=ds,
        )
        assert res.tool_calls_executed == []
        assert len(tool_responses) == 3
        for tr in tool_responses:
            assert "error" in tr
            assert "Rejected invalid tool arguments" in tr["error"]

    def test_viewer_cannot_create_proposals_and_member_cannot_propose_owner_tools(
        self, sec_env
    ):
        org_a, _, tok_owner = sec_env.make_org_user(MembershipRole.OWNER.value)
        member_a, tok_member = sec_env.add_member(org_a, MembershipRole.MEMBER.value)
        viewer_a, tok_viewer = sec_env.add_member(org_a, MembershipRole.VIEWER.value)

        integ = sec_env.client.post(
            f"/orgs/{org_a.id}/integrations",
            json={"provider": "fake", "credentials": {}},
            headers={"Authorization": f"Bearer {tok_owner}"},
        ).json()

        # 1. Viewer deterministic fallback sync request must NOT create proposal
        v_resp = sec_env.client.post(
            f"/orgs/{org_a.id}/copilot/chat",
            json={"message": "Please sync my fake integration"},
            headers={"Authorization": f"Bearer {tok_viewer}"},
        )
        assert v_resp.status_code == 200
        assert v_resp.json()["pending_proposals"] == []
        assert "Permission denied" in v_resp.json()["reply"]
        assert (
            sec_env.client.get(
                f"/orgs/{org_a.id}/copilot/proposals",
                headers={"Authorization": f"Bearer {tok_owner}"},
            ).json()
            == []
        )

        # 2. DeepSeek tool-call attempt for viewer (sync) & member (disconnect) must NOT persist ActionProposal
        for uid, role, tool_name in (
            (viewer_a.id, MembershipRole.VIEWER.value, "sync_organization_integration"),
            (member_a.id, MembershipRole.MEMBER.value, "disconnect_integration"),
        ):
            step = {"idx": 0}

            def handler(_req: httpx.Request, _t=tool_name) -> httpx.Response:
                step["idx"] += 1
                if step["idx"] == 1:
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
                                                "id": "c1",
                                                "type": "function",
                                                "function": {
                                                    "name": _t,
                                                    "arguments": json.dumps({"integration_id": integ["id"]}),
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
                    json={"choices": [{"message": {"role": "assistant", "content": "Denied."}}]},
                )

            ds = DeepSeekClient(
                api_key="sk-test-rbac",
                http_client=httpx.Client(transport=httpx.MockTransport(handler)),
            )
            out = copilot_service.run_copilot_chat(
                sec_env.session,
                organization_id=org_a.id,
                user_id=uid,
                message=f"Run {tool_name}",
                caller_role=role,
                deepseek_client=ds,
            )
            assert out.pending_proposals == []

        assert (
            sec_env.session.scalars(
                select(ActionProposal).where(ActionProposal.organization_id == org_a.id)
            ).all()
            == []
        )

    def test_mutating_tool_execution_requires_approval_and_rejects_tampered_db_args(
        self, sec_env
    ):
        org_a, owner_a, tok_owner = sec_env.make_org_user(MembershipRole.OWNER.value)
        org_b, _, _ = sec_env.make_org_user(MembershipRole.OWNER.value)
        _, tok_member = sec_env.add_member(org_a, MembershipRole.MEMBER.value)

        integ = sec_env.client.post(
            f"/orgs/{org_a.id}/integrations",
            json={"provider": "fake", "credentials": {}},
            headers={"Authorization": f"Bearer {tok_owner}"},
        ).json()

        # Direct execution of mutating tool without approval flag must raise
        sync_tool = ai_tool_registry.get("sync_organization_integration")
        with pytest.raises(ToolApprovalRequiredError):
            execute_tool_safely(
                sec_env.session,
                tool=sync_tool,
                organization_id=org_a.id,
                caller_role=MembershipRole.OWNER.value,
                raw_args={"integration_id": integ["id"]},
                allow_mutating_execution=False,
            )

        # Member cannot approve owner-only disconnect proposal
        disconnect_prop = ActionProposal(
            organization_id=org_a.id,
            proposed_by_user_id=owner_a.id,
            tool_name="disconnect_integration",
            title="Disconnect",
            description="Owner-only disconnect",
            arguments={"integration_id": integ["id"]},
            status=ProposalStatus.PENDING.value,
        )
        sec_env.session.add(disconnect_prop)
        sec_env.session.flush()
        assert (
            sec_env.client.post(
                f"/orgs/{org_a.id}/copilot/proposals/{disconnect_prop.id}/decision",
                json={"decision": "approve"},
                headers={"Authorization": f"Bearer {tok_member}"},
            ).status_code
            == 403
        )

        # Tampered reserved key inside persisted proposal arguments fails cleanly at decision time
        tampered_prop = ActionProposal(
            organization_id=org_a.id,
            proposed_by_user_id=owner_a.id,
            tool_name="sync_organization_integration",
            title="Tampered",
            description="Injected org_id",
            arguments={"integration_id": integ["id"], "organization_id": str(org_b.id)},
            status=ProposalStatus.PENDING.value,
        )
        sec_env.session.add(tampered_prop)
        sec_env.session.flush()
        dec = sec_env.client.post(
            f"/orgs/{org_a.id}/copilot/proposals/{tampered_prop.id}/decision",
            json={"decision": "approve"},
            headers={"Authorization": f"Bearer {tok_owner}"},
        )
        assert dec.status_code == 200
        assert dec.json()["status"] == "failed"
        assert "Reserved execution context keys" in dec.json()["execution_result"]["error"]


# ---------------------------------------------------------------------------
# 3. Webhook Replay, Expired Timestamp, Invalid & Duplicate Delivery Tests
# ---------------------------------------------------------------------------


class TestWebhookSecurityHardening:
    def test_razorpay_and_github_replay_expired_invalid_and_duplicate_deliveries(
        self, sec_env
    ):
        org, _, tok = sec_env.make_org_user()
        h = {"Authorization": f"Bearer {tok}"}
        rzp_secret = "test"
        gh_secret = "test"

        sec_env.client.post(
            f"/orgs/{org.id}/integrations",
            json={
                "provider": "razorpay",
                "credentials": {"mode": "mock", "webhook_secret": rzp_secret},
            },
            headers=h,
        )
        sec_env.client.post(
            f"/orgs/{org.id}/integrations",
            json={
                "provider": "github",
                "credentials": {
                    "mode": "mock",
                    "repo": "acme/sec",
                    "webhook_secret": gh_secret,
                },
            },
            headers=h,
        )

        # 1. Expired Razorpay timestamp (15 min old) with valid HMAC -> 401
        stale_ts = int((datetime.now(timezone.utc) - timedelta(minutes=15)).timestamp())
        stale_body = json.dumps(
            {
                "event": "payment.captured",
                "created_at": stale_ts,
                "payload": {
                    "payment": {
                        "entity": {
                            "id": "pay_stale_1",
                            "entity": "payment",
                            "amount": 5000,
                            "currency": "USD",
                            "status": "captured",
                            "created_at": stale_ts,
                        }
                    }
                },
            }
        ).encode("utf-8")
        stale_sig = hmac.new(rzp_secret.encode("utf-8"), stale_body, hashlib.sha256).hexdigest()
        assert (
            sec_env.client.post(
                f"/webhooks/razorpay/{org.id}",
                content=stale_body,
                headers={
                    "X-Razorpay-Signature": stale_sig,
                    "X-Razorpay-Event-Id": "evt_stale_1",
                },
            ).status_code
            == 401
        )

        # 2. Fresh Razorpay webhook: invalid signature does NOT poison delivery_id;
        # valid delivery succeeds (200); duplicate delivery_id rejected (409)
        now_ts = int(datetime.now(timezone.utc).timestamp())
        fresh_body = json.dumps(
            {
                "event": "payment.captured",
                "created_at": now_ts,
                "payload": {
                    "payment": {
                        "entity": {
                            "id": "pay_fresh_1",
                            "entity": "payment",
                            "amount": 7500,
                            "currency": "USD",
                            "status": "captured",
                            "created_at": now_ts,
                        }
                    }
                },
            }
        ).encode("utf-8")
        fresh_sig = hmac.new(rzp_secret.encode("utf-8"), fresh_body, hashlib.sha256).hexdigest()

        assert (
            sec_env.client.post(
                f"/webhooks/razorpay/{org.id}",
                content=fresh_body,
                headers={
                    "X-Razorpay-Signature": "forged",
                    "X-Razorpay-Event-Id": "evt_fresh_1",
                },
            ).status_code
            == 401
        )
        assert (
            sec_env.client.post(
                f"/webhooks/razorpay/{org.id}",
                content=fresh_body,
                headers={
                    "X-Razorpay-Signature": fresh_sig,
                    "X-Razorpay-Event-Id": "evt_fresh_1",
                },
            ).status_code
            == 200
        )
        assert (
            sec_env.client.post(
                f"/webhooks/razorpay/{org.id}",
                content=fresh_body,
                headers={
                    "X-Razorpay-Signature": fresh_sig,
                    "X-Razorpay-Event-Id": "evt_fresh_1",
                },
            ).status_code
            == 409
        )

        # 3. GitHub expired X-Webhook-Timestamp -> 401; duplicate X-GitHub-Delivery -> 409
        gh_body = json.dumps(
            {
                "action": "opened",
                "repository": {"full_name": "acme/sec"},
                "issue": {
                    "number": 7,
                    "title": "Harden webhook",
                    "state": "open",
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "user": {"login": "alice"},
                },
            }
        ).encode("utf-8")
        gh_sig = "sha256=" + hmac.new(gh_secret.encode("utf-8"), gh_body, hashlib.sha256).hexdigest()

        assert (
            sec_env.client.post(
                f"/webhooks/github/{org.id}",
                content=gh_body,
                headers={
                    "X-Hub-Signature-256": gh_sig,
                    "X-GitHub-Delivery": "gh-deliv-1",
                    "X-Webhook-Timestamp": str(stale_ts),
                },
            ).status_code
            == 401
        )
        assert (
            sec_env.client.post(
                f"/webhooks/github/{org.id}",
                content=gh_body,
                headers={
                    "X-Hub-Signature-256": gh_sig,
                    "X-GitHub-Delivery": "gh-deliv-1",
                    "X-Webhook-Timestamp": str(now_ts),
                },
            ).status_code
            == 200
        )
        assert (
            sec_env.client.post(
                f"/webhooks/github/{org.id}",
                content=gh_body,
                headers={
                    "X-Hub-Signature-256": gh_sig,
                    "X-GitHub-Delivery": "gh-deliv-1",
                    "X-Webhook-Timestamp": str(now_ts),
                },
            ).status_code
            == 409
        )


# ---------------------------------------------------------------------------
# 4. Rate-Limit Bypass, Log Sanitization, AuditLog Redaction & JWT Claims
# ---------------------------------------------------------------------------


class TestAuthLoggingAndRateLimitHardening:
    def test_auth_rate_limit_resists_forwarded_for_and_email_casing_bypass(
        self, sec_env, monkeypatch
    ):
        redis_client = get_redis_client()
        for key in redis_client.keys("pulseops:ratelimit:*"):
            redis_client.delete(key)

        monkeypatch.setattr(settings, "rate_limit_auth_max_requests", 2)
        monkeypatch.setattr(settings, "rate_limit_window_seconds", 60)

        target_email = f"brute_{uuid.uuid4().hex[:6]}@example.com"
        for i, email_variant in enumerate((target_email, target_email.upper())):
            r = sec_env.client.post(
                "/auth/login",
                json={"email": email_variant, "password": "WrongPassword!"},
                headers={"X-Forwarded-For": f"10.0.0.{i + 1}"},
            )
            assert r.status_code == 401

        blocked = sec_env.client.post(
            "/auth/login",
            json={"email": target_email.lower(), "password": "WrongPassword!"},
            headers={"X-Forwarded-For": "10.0.0.99"},
        )
        assert blocked.status_code == 429
        assert int(blocked.headers["Retry-After"]) >= 1

    def test_log_formatter_and_audit_service_redact_credentials_and_tokens(self, sec_env):
        formatter = StructuredJsonFormatter()
        record = logging.LogRecord(
            name="app.security_test",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="key=pmcp_SuperSecretMcpToken12345 rzp=rzp_test_ABC12345 ghp=ghp_SecretToken123 sk=sk-LiveStyleKey12345",
            args=(),
            exc_info=None,
        )
        record.details = {
            "api_key": "pmcp_NestedSecret12345",
            "password": "MyPassword123!",
            "nested": {"webhook_secret": "whsec_nested"},
        }
        formatted = formatter.format(record)
        assert "pmcp_SuperSecretMcpToken12345" not in formatted
        assert "rzp_test_ABC12345" not in formatted
        assert "ghp_SecretToken123" not in formatted
        assert "sk-LiveStyleKey12345" not in formatted
        assert "pmcp_NestedSecret12345" not in formatted
        assert "MyPassword123!" not in formatted
        assert "whsec_nested" not in formatted

        org, user, _ = sec_env.make_org_user()
        entry = audit_service.record_audit_event(
            sec_env.session,
            organization_id=org.id,
            user_id=user.id,
            action="security.test",
            resource_type="test",
            details={
                "api_key": "pmcp_ShouldNotPersist",
                "nested": {"key_secret": "raw_secret", "safe": "ok"},
            },
        )
        assert entry.details["api_key"] == "[REDACTED]"
        assert entry.details["nested"]["key_secret"] == "[REDACTED]"
        assert entry.details["nested"]["safe"] == "ok"

    def test_jwt_missing_exp_or_iat_claims_rejected_with_401(self, sec_env):
        _, user, _ = sec_env.make_org_user()
        token_no_exp = jwt.encode(
            {"sub": str(user.id), "iat": datetime.now(timezone.utc)},
            TEST_JWT_SECRET,
            algorithm=JWT_ALGORITHM,
        )
        token_no_iat = jwt.encode(
            {"sub": str(user.id), "exp": datetime.now(timezone.utc) + timedelta(minutes=10)},
            TEST_JWT_SECRET,
            algorithm=JWT_ALGORITHM,
        )
        for bad_tok in (token_no_exp, token_no_iat):
            resp = sec_env.client.get(
                "/me", headers={"Authorization": f"Bearer {bad_tok}"}
            )
            assert resp.status_code == 401
