"""
S12–S16 tests covering:
- Integration CRUD, encryption at rest, RBAC, and tenant isolation (S12)
- Razorpay Test Mode & conditional mock-billing fallback (S13)
- GitHub REST sync, cycle time calculation, & OAuth state verification (S14)
- CSV import connector & idempotent upload endpoint (S15)
- Razorpay & GitHub HMAC-SHA256 webhook verification (S16)
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import hmac
import json
import uuid

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.connectors import (
    ConnectorAuthError,
    GitHubConnector,
    RazorpayConnector,
)
from app.core.auth import create_access_token, get_password_hash
from app.core.security import generate_encryption_key
from app.db.session import get_db
from app.main import app
from app.models.event import Event
from app.models.integration import Integration
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


@pytest.fixture()
def int_env(test_engine):
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
            org = Organization(name=f"IntOrg-{uuid.uuid4().hex[:8]}")
            user = User(
                email=f"int_{role}_{uuid.uuid4().hex[:8]}@example.com",
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
                email=f"int_{role}_{uuid.uuid4().hex[:8]}@example.com",
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
# S12: Integrations CRUD, RBAC & Sync
# ---------------------------------------------------------------------------


class TestIntegrationManagement:
    def test_owner_connect_list_sync_delete_integration_without_leaking_secrets(
        self, int_env
    ):
        org, _, owner_tok = int_env.make_org_user()
        headers = {"Authorization": f"Bearer {owner_tok}"}

        create_resp = int_env.client.post(
            f"/orgs/{org.id}/integrations",
            json={"provider": "razorpay", "credentials": {"mode": "mock"}},
            headers=headers,
        )
        assert create_resp.status_code == 201
        created = create_resp.json()
        assert created["provider"] == "razorpay"
        assert created["status"] == "active"
        assert "credentials_encrypted" not in created
        assert "credentials" not in created

        # Verify encrypted at rest in DB
        db_integ = int_env.session.get(Integration, uuid.UUID(created["id"]))
        assert db_integ is not None
        assert "mock" not in db_integ.credentials_encrypted

        # List integrations
        list_resp = int_env.client.get(f"/orgs/{org.id}/integrations", headers=headers)
        assert list_resp.status_code == 200
        assert len(list_resp.json()) == 1

        # Trigger sync (idempotent across two calls)
        sync1 = int_env.client.post(
            f"/orgs/{org.id}/integrations/{created['id']}/sync",
            headers=headers,
        )
        assert sync1.status_code == 200
        assert sync1.json()["inserted_count"] == 5
        assert sync1.json()["skipped_count"] == 0

        sync2 = int_env.client.post(
            f"/orgs/{org.id}/integrations/{created['id']}/sync?full_sync=true",
            headers=headers,
        )
        assert sync2.status_code == 200
        assert sync2.json()["inserted_count"] == 0
        assert sync2.json()["skipped_count"] == 5

        # Delete integration
        del_resp = int_env.client.delete(
            f"/orgs/{org.id}/integrations/{created['id']}",
            headers=headers,
        )
        assert del_resp.status_code == 204
        assert int_env.client.get(
            f"/orgs/{org.id}/integrations", headers=headers
        ).json() == []

    def test_integration_rbac_and_cross_tenant_isolation(self, int_env):
        org_a, _, owner_a = int_env.make_org_user()
        _, member_a = int_env.add_member(org_a, MembershipRole.MEMBER.value)
        _, viewer_a = int_env.add_member(org_a, MembershipRole.VIEWER.value)
        _, _, owner_b = int_env.make_org_user()

        created = int_env.client.post(
            f"/orgs/{org_a.id}/integrations",
            json={"provider": "fake", "credentials": {}},
            headers={"Authorization": f"Bearer {owner_a}"},
        ).json()
        integ_id = created["id"]

        # Member & viewer cannot create or delete (403)
        for tok in (member_a, viewer_a):
            r_post = int_env.client.post(
                f"/orgs/{org_a.id}/integrations",
                json={"provider": "fake", "credentials": {}},
                headers={"Authorization": f"Bearer {tok}"},
            )
            assert r_post.status_code == 403
            r_del = int_env.client.delete(
                f"/orgs/{org_a.id}/integrations/{integ_id}",
                headers={"Authorization": f"Bearer {tok}"},
            )
            assert r_del.status_code == 403

        # Viewer can list (200) but cannot sync (403); Member can sync (200)
        assert (
            int_env.client.get(
                f"/orgs/{org_a.id}/integrations",
                headers={"Authorization": f"Bearer {viewer_a}"},
            ).status_code
            == 200
        )
        assert (
            int_env.client.post(
                f"/orgs/{org_a.id}/integrations/{integ_id}/sync",
                headers={"Authorization": f"Bearer {viewer_a}"},
            ).status_code
            == 403
        )
        assert (
            int_env.client.post(
                f"/orgs/{org_a.id}/integrations/{integ_id}/sync",
                headers={"Authorization": f"Bearer {member_a}"},
            ).status_code
            == 200
        )

        # Cross-tenant Org B owner gets 404 on every endpoint targeting Org A
        h_b = {"Authorization": f"Bearer {owner_b}"}
        assert int_env.client.get(f"/orgs/{org_a.id}/integrations", headers=h_b).status_code == 404
        assert (
            int_env.client.post(
                f"/orgs/{org_a.id}/integrations/{integ_id}/sync", headers=h_b
            ).status_code
            == 404
        )
        assert (
            int_env.client.delete(
                f"/orgs/{org_a.id}/integrations/{integ_id}", headers=h_b
            ).status_code
            == 404
        )


# ---------------------------------------------------------------------------
# S13: Razorpay Connector (Test Mode & Mock Fallback)
# ---------------------------------------------------------------------------


class TestRazorpayConnector:
    def test_rejects_live_razorpay_keys(self):
        conn = RazorpayConnector()
        with pytest.raises(ConnectorAuthError, match="Live Razorpay keys"):
            conn.validate_credentials(
                {"key_id": "rzp_live_123456", "key_secret": "secret"}
            )

    def test_razorpay_test_mode_api_normalization(self):
        created_ts = int(datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc).timestamp())

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/v1/payments"
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": "pay_test_999",
                            "entity": "payment",
                            "amount": 14900,
                            "currency": "INR",
                            "status": "captured",
                            "email": "founder@startup.io",
                            "method": "upi",
                            "created_at": created_ts,
                        }
                    ]
                },
            )

        client = httpx.Client(transport=httpx.MockTransport(handler))
        conn = RazorpayConnector(http_client=client)
        events = conn.fetch_events(
            {"key_id": "rzp_test_abc", "key_secret": "secret_xyz"}
        )

        assert len(events) == 1
        assert events[0].external_id == "pay_test_999"
        assert events[0].event_type == "payment.captured"
        assert events[0].amount_cents == 14900
        assert events[0].currency == "INR"
        assert events[0].actor == "founder@startup.io"

    def test_razorpay_test_mode_pagination(self):
        created_ts = int(datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc).timestamp())

        def handler(request: httpx.Request) -> httpx.Response:
            skip = int(request.url.params.get("skip", "0"))
            if skip == 0:
                items = [
                    {
                        "id": f"pay_p1_{i}",
                        "entity": "payment",
                        "amount": 1000,
                        "currency": "USD",
                        "status": "captured",
                        "created_at": created_ts,
                    }
                    for i in range(2)
                ]
            else:
                items = [
                    {
                        "id": "pay_p2_0",
                        "entity": "payment",
                        "amount": 2000,
                        "currency": "USD",
                        "status": "captured",
                        "created_at": created_ts,
                    }
                ]
            return httpx.Response(200, json={"items": items})

        client = httpx.Client(transport=httpx.MockTransport(handler))
        conn = RazorpayConnector(http_client=client)
        raw = conn._fetch_razorpay_payments(
            key_id="rzp_test_abc", key_secret="sec", since=None, page_size=2
        )
        assert [r["id"] for r in raw] == ["pay_p1_0", "pay_p1_1", "pay_p2_0"]

    def test_razorpay_failed_payment_refund_envelope_and_error_handling(self):
        created_ts = int(datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc).timestamp())

        def failed_payment_handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": "pay_fail_01",
                            "entity": "payment",
                            "amount": 19900,
                            "currency": "INR",
                            "status": "failed",
                            "email": "failed@startup.io",
                            "created_at": created_ts,
                        }
                    ]
                },
            )

        conn_ok = RazorpayConnector(
            http_client=httpx.Client(transport=httpx.MockTransport(failed_payment_handler))
        )
        events = conn_ok.fetch_events({"key_id": "rzp_test_abc", "key_secret": "sec"})
        assert len(events) == 1
        assert events[0].event_type == "payment.failed"
        assert events[0].amount_cents == 19900

        # Refund webhook envelope uses refund entity amount (partial refund)
        refund_evt = conn_ok.normalize(
            {
                "event": "payment.refunded",
                "created_at": created_ts,
                "payload": {
                    "payment": {
                        "entity": {
                            "id": "pay_orig_1",
                            "entity": "payment",
                            "amount": 10000,
                            "currency": "USD",
                            "status": "refunded",
                        }
                    },
                    "refund": {
                        "entity": {
                            "id": "rfnd_partial_1",
                            "entity": "refund",
                            "amount": 3500,
                            "currency": "USD",
                            "status": "processed",
                            "created_at": created_ts,
                        }
                    },
                },
            }
        )
        assert refund_evt.event_type == "payment.refunded"
        assert refund_evt.amount_cents == 3500

        # Invalid creds (401), rate limit (429), and timeout map cleanly to ConnectorError subclasses
        from app.connectors import ConnectorError

        for status_code in (401, 403):
            bad_conn = RazorpayConnector(
                http_client=httpx.Client(
                    transport=httpx.MockTransport(lambda _r, s=status_code: httpx.Response(s))
                )
            )
            with pytest.raises(ConnectorAuthError):
                bad_conn.fetch_events({"key_id": "rzp_test_bad", "key_secret": "sec"})

        rate_conn = RazorpayConnector(
            http_client=httpx.Client(
                transport=httpx.MockTransport(lambda _r: httpx.Response(429))
            )
        )
        with pytest.raises(ConnectorError, match="rate limit"):
            rate_conn.fetch_events({"key_id": "rzp_test_abc", "key_secret": "sec"})

        def timeout_handler(_r: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("timed out")

        to_conn = RazorpayConnector(
            http_client=httpx.Client(transport=httpx.MockTransport(timeout_handler))
        )
        with pytest.raises(ConnectorError, match="Razorpay API sync failed"):
            to_conn.fetch_events({"key_id": "rzp_test_abc", "key_secret": "sec"})


# ---------------------------------------------------------------------------
# S14: GitHub Connector & OAuth
# ---------------------------------------------------------------------------


class TestGitHubConnectorAndOAuth:
    def test_github_rest_sync_computes_cycle_time_and_excludes_prs_from_issues(self):
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/pulls"):
                return httpx.Response(
                    200,
                    json=[
                        {
                            "number": 7,
                            "title": "Add metrics",
                            "state": "closed",
                            "created_at": "2026-11-10T10:00:00Z",
                            "merged_at": "2026-11-10T15:30:00Z",
                            "user": {"login": "alice"},
                        }
                    ],
                )
            if request.url.path.endswith("/issues"):
                return httpx.Response(
                    200,
                    json=[
                        # PR returned in /issues by GitHub API must be skipped
                        {"number": 7, "pull_request": {"url": "..."}},
                        {
                            "number": 12,
                            "title": "Bug in CSV parser",
                            "state": "closed",
                            "created_at": "2026-11-09T08:00:00Z",
                            "closed_at": "2026-11-10T08:00:00Z",
                            "user": {"login": "bob"},
                        },
                    ],
                )
            return httpx.Response(404)

        client = httpx.Client(transport=httpx.MockTransport(handler))
        conn = GitHubConnector(http_client=client)
        events = conn.fetch_events({"access_token": "ghp_mock", "repo": "acme/api"})

        assert len(events) == 2
        pr_evt = next(e for e in events if e.event_type == "pr.merged")
        issue_evt = next(e for e in events if e.event_type == "issue.closed")
        assert pr_evt.payload["cycle_time_hours"] == 5.5
        assert issue_evt.payload["cycle_time_hours"] == 24.0

    def test_github_rest_pagination(self):
        def handler(request: httpx.Request) -> httpx.Response:
            page = int(request.url.params.get("page", "1"))
            if request.url.path.endswith("/pulls"):
                if page == 1:
                    return httpx.Response(
                        200,
                        json=[
                            {
                                "number": 1,
                                "title": "PR 1",
                                "state": "open",
                                "created_at": "2026-11-10T10:00:00Z",
                                "user": {"login": "alice"},
                            }
                        ],
                    )
                return httpx.Response(200, json=[])
            return httpx.Response(200, json=[])

        client = httpx.Client(transport=httpx.MockTransport(handler))
        conn = GitHubConnector(http_client=client)
        raw = conn._fetch_repo_records(
            repo="acme/api",
            headers={"Authorization": "Bearer ghp_x"},
            since=None,
            per_page=1,
        )
        assert len(raw) == 1
        assert raw[0]["number"] == 1

    def test_github_error_status_mapping_and_oauth_failure_handling(self):
        from app.connectors import ConnectorError
        from app.services import integration_service

        conn_403 = GitHubConnector(
            http_client=httpx.Client(
                transport=httpx.MockTransport(lambda _r: httpx.Response(403))
            )
        )
        with pytest.raises(ConnectorAuthError, match="denied access"):
            conn_403.fetch_events({"access_token": "ghp_bad", "repo": "acme/api"})

        conn_404 = GitHubConnector(
            http_client=httpx.Client(
                transport=httpx.MockTransport(lambda _r: httpx.Response(404))
            )
        )
        with pytest.raises(ConnectorError, match="not found"):
            conn_404.fetch_events({"access_token": "ghp_bad", "repo": "acme/missing"})

        # OAuth code exchange HTTP errors map cleanly to ConnectorAuthError
        from app.config import settings

        old_cid, old_sec = settings.github_client_id, settings.github_client_secret
        try:
            settings.github_client_id = "cid"
            settings.github_client_secret = "csec"
            with pytest.raises(ConnectorAuthError):
                integration_service.exchange_github_oauth_code(
                    code="bad_code",
                    http_client=httpx.Client(
                        transport=httpx.MockTransport(lambda _r: httpx.Response(502))
                    ),
                )
        finally:
            settings.github_client_id = old_cid
            settings.github_client_secret = old_sec

    def test_github_oauth_url_and_state_isolation(self, int_env, monkeypatch):
        from app.services import integration_service

        org_a, _, owner_a = int_env.make_org_user()
        org_b, _, owner_b = int_env.make_org_user()

        url_resp = int_env.client.get(
            f"/orgs/{org_a.id}/integrations/github/oauth/url",
            headers={"Authorization": f"Bearer {owner_a}"},
        )
        assert url_resp.status_code == 200
        state_a = url_resp.json()["state"]
        assert "github.com/login/oauth/authorize" in url_resp.json()["authorization_url"]

        monkeypatch.setattr(
            integration_service,
            "exchange_github_oauth_code",
            lambda code: "gho_exchanged_token",
        )

        # Cross-org state reuse must fail with 400
        bad_cb = int_env.client.post(
            f"/orgs/{org_b.id}/integrations/github/oauth/callback",
            json={"code": "abc", "state": state_a, "repo": "acme/web"},
            headers={"Authorization": f"Bearer {owner_b}"},
        )
        assert bad_cb.status_code == 400

        # Valid Org A callback stores encrypted integration
        ok_cb = int_env.client.post(
            f"/orgs/{org_a.id}/integrations/github/oauth/callback",
            json={"code": "abc", "state": state_a, "repo": "acme/web"},
            headers={"Authorization": f"Bearer {owner_a}"},
        )
        assert ok_cb.status_code == 201
        assert ok_cb.json()["provider"] == "github"


# ---------------------------------------------------------------------------
# S15: CSV Import Endpoint
# ---------------------------------------------------------------------------


class TestCsvImport:
    def test_csv_import_idempotent_for_json_and_raw_csv(self, int_env):
        org, _, owner_tok = int_env.make_org_user()
        headers = {"Authorization": f"Bearer {owner_tok}"}

        csv_body = (
            "event_type,occurred_at,amount_cents,currency,actor,plan\n"
            "subscription.charged,2026-11-15T10:00:00Z,7900,USD,cust_1,pro\n"
            "payment.refunded,2026-11-16T10:00:00Z,2900,USD,cust_2,starter\n"
        )

        # First upload as JSON
        resp1 = int_env.client.post(
            f"/orgs/{org.id}/imports/csv",
            json={"csv_text": csv_body},
            headers=headers,
        )
        assert resp1.status_code == 201
        assert resp1.json() == {
            "total_received": 2,
            "inserted_count": 2,
            "skipped_count": 0,
        }

        # Re-upload identical data as raw text/csv -> deterministic hashes skip duplicates
        resp2 = int_env.client.post(
            f"/orgs/{org.id}/imports/csv",
            content=csv_body.encode("utf-8"),
            headers={**headers, "Content-Type": "text/csv"},
        )
        assert resp2.status_code == 201
        assert resp2.json() == {
            "total_received": 2,
            "inserted_count": 0,
            "skipped_count": 2,
        }

    def test_csv_import_rejects_missing_columns(self, int_env):
        org, _, owner_tok = int_env.make_org_user()
        resp = int_env.client.post(
            f"/orgs/{org.id}/imports/csv",
            json={"csv_text": "foo,bar\n1,2\n"},
            headers={"Authorization": f"Bearer {owner_tok}"},
        )
        assert resp.status_code == 422

    def test_csv_import_handles_utf8_bom_blank_rows_and_viewer_rbac(self, int_env):
        org, _, owner_tok = int_env.make_org_user()
        _, viewer_tok = int_env.add_member(org, MembershipRole.VIEWER.value)

        now_iso = datetime.now(timezone.utc).isoformat()
        bom_csv = (
            "\ufeffevent_type,occurred_at,amount_cents,currency,actor\n"
            f"subscription.charged,{now_iso},9900,USD,cust_bom_01\n"
            "\n"
        )

        # Viewer cannot import CSV -> 403
        viewer_resp = int_env.client.post(
            f"/orgs/{org.id}/imports/csv",
            json={"csv_text": bom_csv},
            headers={"Authorization": f"Bearer {viewer_tok}"},
        )
        assert viewer_resp.status_code == 403

        # Member/Owner UTF-8 BOM CSV with blank trailing row succeeds
        ok_resp = int_env.client.post(
            f"/orgs/{org.id}/imports/csv",
            json={"csv_text": bom_csv},
            headers={"Authorization": f"Bearer {owner_tok}"},
        )
        assert ok_resp.status_code == 201
        assert ok_resp.json() == {
            "total_received": 1,
            "inserted_count": 1,
            "skipped_count": 0,
        }


# ---------------------------------------------------------------------------
# S16: Inbound Webhooks (HMAC-SHA256)
# ---------------------------------------------------------------------------


class TestInboundWebhooks:
    def test_razorpay_webhook_signature_and_idempotency(self, int_env):
        org, _, owner_tok = int_env.make_org_user()
        secret = "rzp_whsec_test_secret_123"

        int_env.client.post(
            f"/orgs/{org.id}/integrations",
            json={
                "provider": "razorpay",
                "credentials": {"mode": "mock", "webhook_secret": secret},
            },
            headers={"Authorization": f"Bearer {owner_tok}"},
        )

        now_ts = int(datetime.now(timezone.utc).timestamp())
        raw_payload = json.dumps(
            {
                "event": "payment.captured",
                "created_at": now_ts,
                "payload": {
                    "payment": {
                        "entity": {
                            "id": "pay_wh_1001",
                            "entity": "payment",
                            "amount": 9900,
                            "currency": "USD",
                            "status": "captured",
                            "email": "buyer@example.com",
                            "created_at": now_ts,
                        }
                    }
                },
            }
        ).encode("utf-8")

        valid_sig = hmac.new(
            secret.encode("utf-8"), raw_payload, hashlib.sha256
        ).hexdigest()

        # Missing or invalid signature -> 401
        assert (
            int_env.client.post(
                f"/webhooks/razorpay/{org.id}",
                content=raw_payload,
            ).status_code
            == 401
        )
        assert (
            int_env.client.post(
                f"/webhooks/razorpay/{org.id}",
                content=raw_payload,
                headers={"X-Razorpay-Signature": "bad_sig"},
            ).status_code
            == 401
        )

        # Valid signature -> 200 & inserts 1
        ok1 = int_env.client.post(
            f"/webhooks/razorpay/{org.id}",
            content=raw_payload,
            headers={"X-Razorpay-Signature": valid_sig},
        )
        assert ok1.status_code == 200
        assert ok1.json()["inserted_count"] == 1

        # Webhook update reflects immediately in metrics summary (one-time payment.captured -> volume, not MRR)
        metrics = int_env.client.get(
            f"/orgs/{org.id}/metrics/summary?days=30",
            headers={"Authorization": f"Bearer {owner_tok}"},
        )
        assert metrics.status_code == 200
        m_json = metrics.json()
        assert m_json["gross_revenue_cents"] == 9900
        assert m_json["by_currency"]["USD"]["one_time_payment_volume_minor"] == 9900
        assert m_json["mrr_cents"] == 0

        # Replay -> idempotent skip
        ok2 = int_env.client.post(
            f"/webhooks/razorpay/{org.id}",
            content=raw_payload,
            headers={"X-Razorpay-Signature": valid_sig},
        )
        assert ok2.status_code == 200
        assert ok2.json()["inserted_count"] == 0
        assert ok2.json()["skipped_count"] == 1

    def test_github_webhook_signature_and_unknown_org_404(self, int_env):
        org, _, owner_tok = int_env.make_org_user()
        secret = "gh_whsec_test_secret_456"

        int_env.client.post(
            f"/orgs/{org.id}/integrations",
            json={
                "provider": "github",
                "credentials": {
                    "mode": "mock",
                    "repo": "acme/app",
                    "webhook_secret": secret,
                },
            },
            headers={"Authorization": f"Bearer {owner_tok}"},
        )

        raw_payload = json.dumps(
            {
                "action": "closed",
                "repository": {"full_name": "acme/app"},
                "pull_request": {
                    "number": 55,
                    "title": "Ship S16 webhook",
                    "state": "closed",
                    "merged": True,
                    "created_at": "2026-11-10T10:00:00Z",
                    "merged_at": "2026-11-10T12:00:00Z",
                    "user": {"login": "dev_alice"},
                },
            }
        ).encode("utf-8")

        sig = "sha256=" + hmac.new(
            secret.encode("utf-8"), raw_payload, hashlib.sha256
        ).hexdigest()

        # Unknown org returns 404
        assert (
            int_env.client.post(
                f"/webhooks/github/{uuid.uuid4()}",
                content=raw_payload,
                headers={"X-Hub-Signature-256": sig},
            ).status_code
            == 404
        )

        # Invalid signature returns 401
        assert (
            int_env.client.post(
                f"/webhooks/github/{org.id}",
                content=raw_payload,
                headers={"X-Hub-Signature-256": "sha256=deadbeef"},
            ).status_code
            == 401
        )

        # Valid signature persists normalized PR merged event
        ok = int_env.client.post(
            f"/webhooks/github/{org.id}",
            content=raw_payload,
            headers={"X-Hub-Signature-256": sig},
        )
        assert ok.status_code == 200
        assert ok.json()["inserted_count"] == 1

        stored = int_env.session.scalars(
            select(Event).where(Event.organization_id == org.id)
        ).all()
        assert len(stored) == 1
        assert stored[0].event_type == "pr.merged"
        assert stored[0].payload["cycle_time_hours"] == 2.0
