"""
Tests covering missing roadmap milestones implemented during reconciliation:
- S27: SSE endpoint with Redis Pub/Sub and cross-tenant isolation
- S28: Tenant-scoped CSV export endpoint with formula-injection sanitization
- S31: AuditLog model, attribution, and owner-only audit retrieval
- S34: DeepSeek streaming responses and Redis response caching + invalidation
- S36: Prometheus /metrics exposition and /readiness (PostgreSQL + Redis)
- S37: Redis-backed rate limiting (HTTP 429 + Retry-After, tenant/user isolation)
- S38: Synthetic demo seeder, read-only demo viewer account, and 5/day Copilot limit
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import threading
import time
import uuid

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.deepseek_client import DeepSeekClient, DeepSeekError
from app.config import settings
from app.core.auth import create_access_token, get_password_hash
from app.core.rate_limit import get_redis_client
from app.core.security import generate_encryption_key
from app.db.session import get_db
from app.main import app
from app.models.audit_log import AuditLog
from app.models.membership import Membership, MembershipRole
from app.models.organization import Organization
from app.models.user import User
from app.schemas.event import NormalizedEvent
from app.services import copilot_service, demo_service, event_service

TEST_JWT_SECRET = "unit-test-only"


@pytest.fixture(autouse=True)
def patch_secrets(monkeypatch):
    monkeypatch.setattr(settings, "jwt_secret_key", TEST_JWT_SECRET)
    monkeypatch.setattr(
        settings, "integration_encryption_key", generate_encryption_key()
    )
    monkeypatch.setattr(settings, "deepseek_api_key", None)


@pytest.fixture()
def gap_env(test_engine):
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

        def make_org_user(self, role: str = MembershipRole.OWNER.value, email: str | None = None):
            org = Organization(name=f"GapOrg-{uuid.uuid4().hex[:8]}")
            user = User(
                email=email or f"gap_{role}_{uuid.uuid4().hex[:8]}@example.com",
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
                email=f"gap_{role}_{uuid.uuid4().hex[:8]}@example.com",
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
# S27 — SSE Real-time Updates & Tenant Isolation
# ---------------------------------------------------------------------------


def test_sse_stream_requires_auth_and_enforces_tenant_isolation(gap_env):
    org_a, _, tok_a = gap_env.make_org_user(MembershipRole.OWNER.value)
    org_b, _, tok_b = gap_env.make_org_user(MembershipRole.OWNER.value)

    # Unauthenticated rejected with 401
    assert gap_env.client.get(f"/orgs/{org_a.id}/events/stream").status_code == 401

    # Non-member rejected with 404
    assert (
        gap_env.client.get(
            f"/orgs/{org_a.id}/events/stream",
            headers={"Authorization": f"Bearer {tok_b}"},
        ).status_code
        == 404
    )

    # Trigger events for Org B first, then Org A from a background thread while
    # Org A streams max_events=1 over real Redis Pub/Sub.
    def _publish_after_subscribe():
        time.sleep(0.35)
        from app.services.realtime_service import publish_org_events

        evt_b = NormalizedEvent(
            source="razorpay",
            external_id=f"sse_b_{uuid.uuid4().hex[:6]}",
            event_type="subscription.charged",
            occurred_at=datetime.now(timezone.utc),
            amount_cents=9900,
            currency="USD",
        )
        publish_org_events(organization_id=org_b.id, events=[evt_b], inserted_count=1)
        time.sleep(0.1)
        evt_a = NormalizedEvent(
            source="github",
            external_id=f"sse_a_{uuid.uuid4().hex[:6]}",
            event_type="pr.merged",
            occurred_at=datetime.now(timezone.utc),
            actor="alice",
        )
        publish_org_events(organization_id=org_a.id, events=[evt_a], inserted_count=1)

    thread = threading.Thread(target=_publish_after_subscribe, daemon=True)
    thread.start()

    frames: list[str] = []
    with gap_env.client.stream(
        "GET",
        f"/orgs/{org_a.id}/events/stream?max_events=1&idle_timeout=5.0",
        headers={"Authorization": f"Bearer {tok_a}"},
    ) as resp:
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers.get("content-type", "")
        for line in resp.iter_lines():
            if line:
                frames.append(line)

    thread.join(timeout=5.0)
    joined = "\n".join(frames)
    assert str(org_a.id) in joined
    assert str(org_b.id) not in joined
    assert "events.ingested" in joined
    assert "pr.merged" in joined


# ---------------------------------------------------------------------------
# S28 — CSV Export
# ---------------------------------------------------------------------------


def test_csv_export_enforces_membership_tenant_scope_and_sanitization(gap_env):
    org_a, _, tok_a = gap_env.make_org_user(MembershipRole.OWNER.value)
    _, tok_a_viewer = gap_env.add_member(org_a, MembershipRole.VIEWER.value)
    org_b, _, tok_b = gap_env.make_org_user(MembershipRole.OWNER.value)

    now = datetime.now(timezone.utc)
    event_service.ingest_events(
        gap_env.session,
        organization_id=org_a.id,
        events=[
            NormalizedEvent(
                source="csv",
                external_id="exp_a_1",
                event_type="subscription.charged",
                occurred_at=now,
                amount_cents=15000,
                currency="USD",
                actor="=CMD('calc')",
            )
        ],
    )
    event_service.ingest_events(
        gap_env.session,
        organization_id=org_b.id,
        events=[
            NormalizedEvent(
                source="razorpay",
                external_id="exp_b_secret",
                event_type="subscription.charged",
                occurred_at=now,
                amount_cents=55000,
                currency="USD",
                actor="org_b_customer",
            )
        ],
    )
    gap_env.session.flush()

    # Cross-tenant denied with 404
    assert (
        gap_env.client.get(
            f"/orgs/{org_a.id}/events/export",
            headers={"Authorization": f"Bearer {tok_b}"},
        ).status_code
        == 404
    )

    # Viewer and Owner can export Org A events cleanly
    for tok in (tok_a, tok_a_viewer):
        resp = gap_env.client.get(
            f"/orgs/{org_a.id}/events/export",
            headers={"Authorization": f"Bearer {tok}"},
        )
        assert resp.status_code == 200
        assert "text/csv" in resp.headers["content-type"]
        assert "attachment" in resp.headers.get("content-disposition", "")
        assert "exp_a_1" in resp.text
        assert "'=CMD('calc')" in resp.text
        assert "exp_b_secret" not in resp.text
        assert "org_b_customer" not in resp.text

    # Source filter excludes non-matching rows
    filtered = gap_env.client.get(
        f"/orgs/{org_a.id}/events/export?source=github",
        headers={"Authorization": f"Bearer {tok_a}"},
    )
    assert filtered.status_code == 200
    assert "exp_a_1" not in filtered.text


# ---------------------------------------------------------------------------
# S31 — Audit Logging
# ---------------------------------------------------------------------------


def test_audit_logging_records_mutations_and_restricts_retrieval_to_owners(gap_env):
    suffix = uuid.uuid4().hex[:8]
    reg_a = gap_env.client.post(
        "/auth/register",
        json={
            "email": f"audit_owner_{suffix}@example.com",
            "password": "StrongPassword123!",
            "organization_name": f"AuditOrgA-{suffix}",
        },
    )
    assert reg_a.status_code == 201
    org_a_id = reg_a.json()["organization_id"]

    tok_a = gap_env.client.post(
        "/auth/login",
        json={
            "email": f"audit_owner_{suffix}@example.com",
            "password": "StrongPassword123!",
        },
    ).json()["access_token"]
    h_a = {"Authorization": f"Bearer {tok_a}"}

    # Register a second user (for member/viewer addition & cross-tenant Org B)
    reg_b = gap_env.client.post(
        "/auth/register",
        json={
            "email": f"audit_member_{suffix}@example.com",
            "password": "StrongPassword123!",
            "organization_name": f"AuditOrgB-{suffix}",
        },
    )
    assert reg_b.status_code == 201
    tok_b = gap_env.client.post(
        "/auth/login",
        json={
            "email": f"audit_member_{suffix}@example.com",
            "password": "StrongPassword123!",
        },
    ).json()["access_token"]
    h_b = {"Authorization": f"Bearer {tok_b}"}

    # Add User B as member in Org A
    add_res = gap_env.client.post(
        f"/orgs/{org_a_id}/members",
        json={"email": f"audit_member_{suffix}@example.com", "role": "member"},
        headers=h_a,
    )
    assert add_res.status_code == 201

    # Connect & sync fake integration + CSV import + copilot proposal + decision
    integ = gap_env.client.post(
        f"/orgs/{org_a_id}/integrations",
        json={"provider": "fake", "credentials": {"api_key": "secret-should-not-leak"}},
        headers=h_a,
    )
    assert integ.status_code == 201
    integ_id = integ.json()["id"]

    assert (
        gap_env.client.post(
            f"/orgs/{org_a_id}/integrations/{integ_id}/sync", headers=h_a
        ).status_code
        == 200
    )

    chat_resp = gap_env.client.post(
        f"/orgs/{org_a_id}/copilot/chat",
        json={"message": "Please sync my fake integration"},
        headers=h_a,
    )
    assert chat_resp.status_code == 200
    prop_id = chat_resp.json()["pending_proposals"][0]["id"]

    dec_resp = gap_env.client.post(
        f"/orgs/{org_a_id}/copilot/proposals/{prop_id}/decision",
        json={"decision": "reject"},
        headers=h_a,
    )
    assert dec_resp.status_code == 200

    assert (
        gap_env.client.delete(
            f"/orgs/{org_a_id}/integrations/{integ_id}", headers=h_a
        ).status_code
        == 204
    )

    # Owner gets 200 with full audit trail and zero secret leakage
    logs_resp = gap_env.client.get(f"/orgs/{org_a_id}/audit-logs", headers=h_a)
    assert logs_resp.status_code == 200
    actions = {entry["action"] for entry in logs_resp.json()}
    assert {
        "auth.register",
        "member.added",
        "integration.created",
        "integration.synced",
        "copilot.proposal_created",
        "copilot.proposal_rejected",
        "integration.deleted",
    }.issubset(actions)
    assert "secret-should-not-leak" not in logs_resp.text

    # Member role denied with 403
    assert (
        gap_env.client.get(f"/orgs/{org_a_id}/audit-logs", headers=h_b).status_code
        == 403
    )

    # Unrelated user in Org C receives 404
    _, _, tok_c = gap_env.make_org_user(MembershipRole.OWNER.value)
    assert (
        gap_env.client.get(
            f"/orgs/{org_a_id}/audit-logs",
            headers={"Authorization": f"Bearer {tok_c}"},
        ).status_code
        == 404
    )


# ---------------------------------------------------------------------------
# S34 — DeepSeek Caching & Streaming
# ---------------------------------------------------------------------------


def test_copilot_response_caching_and_invalidation(gap_env):
    org, user, _ = gap_env.make_org_user(MembershipRole.OWNER.value)
    calls = {"count": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"role": "assistant", "content": "Cached MRR summary."}}
                ]
            },
        )

    mock_client = DeepSeekClient(
        api_key="test-deepseek-key",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    # 1st call executes DeepSeek
    r1 = copilot_service.run_copilot_chat(
        gap_env.session,
        organization_id=org.id,
        user_id=user.id,
        message="What is our MRR?",
        deepseek_client=mock_client,
    )
    assert r1.cached is False
    assert r1.reply == "Cached MRR summary."
    assert calls["count"] == 1

    # 2nd call hits Redis cache without external API call
    r2 = copilot_service.run_copilot_chat(
        gap_env.session,
        organization_id=org.id,
        user_id=user.id,
        message="What is our MRR?",
        deepseek_client=mock_client,
    )
    assert r2.cached is True
    assert r2.reply == "Cached MRR summary."
    assert calls["count"] == 1

    # New event ingestion invalidates cache version cleanly
    event_service.ingest_events(
        gap_env.session,
        organization_id=org.id,
        events=[
            NormalizedEvent(
                source="csv",
                external_id=f"cache_inv_{uuid.uuid4().hex[:6]}",
                event_type="subscription.charged",
                occurred_at=datetime.now(timezone.utc),
                amount_cents=5000,
                currency="USD",
            )
        ],
    )
    r3 = copilot_service.run_copilot_chat(
        gap_env.session,
        organization_id=org.id,
        user_id=user.id,
        message="What is our MRR?",
        deepseek_client=mock_client,
    )
    assert r3.cached is False
    assert calls["count"] == 2


def test_copilot_streaming_sse_and_deepseek_client_stream(gap_env):
    org, _, tok = gap_env.make_org_user(MembershipRole.OWNER.value)

    # Endpoint streaming without API key -> deterministic fallback SSE chunks
    with gap_env.client.stream(
        "POST",
        f"/orgs/{org.id}/copilot/chat",
        json={"message": "Summarize MRR and open issues", "stream": True},
        headers={"Authorization": f"Bearer {tok}"},
    ) as resp:
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers.get("content-type", "")
        body = "".join(resp.iter_text())

    assert '"type": "token"' in body
    assert '"type": "done"' in body
    assert "PulseOps Operational Briefing" in body

    # Unconfigured DeepSeekClient must fail closed without external calls
    with pytest.raises(DeepSeekError):
        list(DeepSeekClient(api_key="").stream_chat_completions(messages=[]))

    # Configured DeepSeekClient streams OpenAI-compatible SSE deltas
    sse_payload = (
        'data: {"choices":[{"delta":{"content":"Net "}}]}\n\n'
        'data: {"choices":[{"delta":{"content":"MRR OK"}}]}\n\n'
        "data: [DONE]\n\n"
    )

    def stream_handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=sse_payload.encode("utf-8"))

    ds = DeepSeekClient(
        api_key="test-key",
        http_client=httpx.Client(transport=httpx.MockTransport(stream_handler)),
    )
    tokens = list(ds.stream_chat_completions(messages=[{"role": "user", "content": "hi"}]))
    assert tokens == ["Net ", "MRR OK"]


# ---------------------------------------------------------------------------
# S36 — Monitoring (/readiness & /metrics)
# ---------------------------------------------------------------------------


def test_readiness_and_prometheus_metrics_endpoints(gap_env, monkeypatch):
    r_ready = gap_env.client.get("/readiness")
    assert r_ready.status_code == 200
    assert r_ready.json() == {
        "status": "ready",
        "checks": {"database": "ok", "redis": "ok"},
    }

    # Hit root once so HTTP request counter records a sample
    assert gap_env.client.get("/").status_code == 200

    r_metrics = gap_env.client.get("/metrics")
    assert r_metrics.status_code == 200
    assert "pulseops_http_requests_total" in r_metrics.text
    assert "pulseops_http_request_duration_seconds" in r_metrics.text

    # Simulated Redis unavailability flips /readiness to 503
    monkeypatch.setattr(
        "app.main.check_readiness",
        lambda: (False, {"database": "ok", "redis": "unavailable"}),
    )
    r_unready = gap_env.client.get("/readiness")
    assert r_unready.status_code == 503
    assert r_unready.json()["status"] == "not_ready"


# ---------------------------------------------------------------------------
# S37 — Redis Rate Limiting (429 + Retry-After + Tenant/User Isolation)
# ---------------------------------------------------------------------------


def test_redis_rate_limiting_auth_and_tenant_user_copilot(gap_env, monkeypatch):
    redis_client = get_redis_client()
    for key in redis_client.keys("pulseops:ratelimit:*"):
        redis_client.delete(key)

    monkeypatch.setattr(settings, "rate_limit_auth_max_requests", 2)
    monkeypatch.setattr(settings, "rate_limit_copilot_max_requests", 2)
    monkeypatch.setattr(settings, "rate_limit_window_seconds", 60)

    # 1. Auth endpoint rate limited after 2 requests -> 429 + Retry-After
    for _ in range(2):
        r = gap_env.client.post(
            "/auth/login",
            json={"email": "nobody@example.com", "password": "wrongpassword"},
        )
        assert r.status_code == 401

    r_limited = gap_env.client.post(
        "/auth/login",
        json={"email": "nobody@example.com", "password": "wrongpassword"},
    )
    assert r_limited.status_code == 429
    assert int(r_limited.headers["Retry-After"]) >= 1

    # 2. Copilot rate limiting is scoped per (org_id, user_id)
    org_a, _, tok_a1 = gap_env.make_org_user(MembershipRole.OWNER.value)
    _, tok_a2 = gap_env.add_member(org_a, MembershipRole.MEMBER.value)
    org_b, _, tok_b = gap_env.make_org_user(MembershipRole.OWNER.value)

    for _ in range(2):
        ok = gap_env.client.post(
            f"/orgs/{org_a.id}/copilot/chat",
            json={"message": "Summarize metrics"},
            headers={"Authorization": f"Bearer {tok_a1}"},
        )
        assert ok.status_code == 200

    throttled = gap_env.client.post(
        f"/orgs/{org_a.id}/copilot/chat",
        json={"message": "Summarize metrics"},
        headers={"Authorization": f"Bearer {tok_a1}"},
    )
    assert throttled.status_code == 429
    assert int(throttled.headers["Retry-After"]) >= 1

    # Second user in same org AND user in Org B remain unaffected
    assert (
        gap_env.client.post(
            f"/orgs/{org_a.id}/copilot/chat",
            json={"message": "Summarize metrics"},
            headers={"Authorization": f"Bearer {tok_a2}"},
        ).status_code
        == 200
    )
    assert (
        gap_env.client.post(
            f"/orgs/{org_b.id}/copilot/chat",
            json={"message": "Summarize metrics"},
            headers={"Authorization": f"Bearer {tok_b}"},
        ).status_code
        == 200
    )


# ---------------------------------------------------------------------------
# S38 — Synthetic Demo Environment
# ---------------------------------------------------------------------------


def test_demo_environment_seeder_readonly_role_and_daily_copilot_limit(
    gap_env, monkeypatch
):
    demo_email = f"demo_viewer_{uuid.uuid4().hex[:8]}@pulseops.example.com"
    monkeypatch.setattr(settings, "demo_account_email", demo_email)
    monkeypatch.setattr(settings, "demo_copilot_daily_limit", 5)

    redis_client = get_redis_client()
    for key in redis_client.keys("pulseops:ratelimit:demo_copilot_daily:*"):
        redis_client.delete(key)

    first = demo_service.seed_synthetic_demo(
        gap_env.session,
        demo_password="DemoViewerPass123!",
    )
    assert first["demo_user_email"] == demo_email
    assert first["demo_role"] == MembershipRole.VIEWER.value
    assert first["events_inserted"] > 0

    # Re-running seeder is idempotent
    second = demo_service.seed_synthetic_demo(
        gap_env.session,
        demo_password="DemoViewerPass123!",
    )
    assert second["events_inserted"] == 0

    demo_token = gap_env.client.post(
        "/auth/login",
        json={"email": demo_email, "password": "DemoViewerPass123!"},
    ).json()["access_token"]
    h_demo = {"Authorization": f"Bearer {demo_token}"}
    demo_org_id = first["organization_id"]

    # Read-only metrics work
    metrics_resp = gap_env.client.get(
        f"/orgs/{demo_org_id}/metrics/summary", headers=h_demo
    )
    assert metrics_resp.status_code == 200
    assert metrics_resp.json()["total_events_in_window"] > 0

    # Mutating actions forbidden for read-only viewer demo account (403)
    assert (
        gap_env.client.post(
            f"/orgs/{demo_org_id}/integrations",
            json={"provider": "fake", "credentials": {}},
            headers=h_demo,
        ).status_code
        == 403
    )

    # Copilot limited to 5 requests/day for demo account
    for i in range(5):
        r = gap_env.client.post(
            f"/orgs/{demo_org_id}/copilot/chat",
            json={"message": f"Briefing #{i}"},
            headers=h_demo,
        )
        assert r.status_code == 200

    sixth = gap_env.client.post(
        f"/orgs/{demo_org_id}/copilot/chat",
        json={"message": "Briefing #6"},
        headers=h_demo,
    )
    assert sixth.status_code == 429
    assert "5 requests per day" in sixth.json()["detail"]
    assert int(sixth.headers["Retry-After"]) >= 60
