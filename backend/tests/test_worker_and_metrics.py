"""
S17–S21 tests covering:
- Redis / ARQ worker settings, TLS DSN parsing, job enqueueing, and execution (S17)
- SyncRun model audit tracking, failure logging, and tenant isolation (S18)
- Metrics Engine calculations (MRR, ARR, churn, PRs, open issues, cycle time) (S19)
- Metrics & Events REST endpoints, RBAC, and cross-tenant isolation (S20–S21)
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app import worker
from app.core.auth import create_access_token, get_password_hash
from app.core.security import generate_encryption_key
from app.db.session import get_db
from app.main import app
from app.models.event import Event
from app.models.membership import Membership, MembershipRole
from app.models.organization import Organization
from app.models.sync_run import SyncRunStatus
from app.models.user import User

TEST_JWT_SECRET = "test-jwt-secret-key-for-s17-s21-metrics-tests"


@pytest.fixture(autouse=True)
def patch_secrets(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "jwt_secret_key", TEST_JWT_SECRET)
    monkeypatch.setattr(
        settings, "integration_encryption_key", generate_encryption_key()
    )


@pytest.fixture()
def wm_env(test_engine):
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

        def make_org_owner(self):
            org = Organization(name=f"MetricsOrg-{uuid.uuid4().hex[:8]}")
            user = User(
                email=f"wm_owner_{uuid.uuid4().hex[:8]}@example.com",
                password_hash=get_password_hash("StrongPassword123!"),
            )
            self.session.add_all([org, user])
            self.session.flush()
            self.session.add(
                Membership(
                    user_id=user.id,
                    organization_id=org.id,
                    role=MembershipRole.OWNER.value,
                )
            )
            self.session.flush()
            return org, user, create_access_token(user.id)

        def add_event(
            self,
            *,
            org: Organization,
            source: str,
            external_id: str,
            event_type: str,
            days_ago: int = 1,
            amount_cents: int | None = None,
            currency: str | None = None,
            actor: str | None = None,
            payload: dict | None = None,
        ):
            evt = Event(
                organization_id=org.id,
                source=source,
                external_id=external_id,
                event_type=event_type,
                occurred_at=datetime.now(timezone.utc) - timedelta(days=days_ago),
                amount_cents=amount_cents,
                currency=currency,
                actor=actor,
                payload=payload or {},
            )
            self.session.add(evt)
            self.session.flush()
            return evt

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
# S17 & S18: ARQ Worker & SyncRun Audit Tests
# ---------------------------------------------------------------------------


class TestWorkerAndSyncRuns:
    def test_redis_settings_supports_tls_rediss_dsn(self, monkeypatch):
        from app.config import settings

        monkeypatch.setattr(
            settings, "redis_url", "rediss://default:secret@upstash.io:6379"
        )
        redis_cfg = worker.get_redis_settings()
        assert redis_cfg.host == "upstash.io"
        assert redis_cfg.port == 6379
        assert redis_cfg.ssl is True

    def test_background_sync_enqueues_job_and_creates_pending_sync_run(
        self, wm_env, monkeypatch
    ):
        org, _, owner_tok = wm_env.make_org_owner()
        headers = {"Authorization": f"Bearer {owner_tok}"}

        integ = wm_env.client.post(
            f"/orgs/{org.id}/integrations",
            json={"provider": "fake", "credentials": {}},
            headers=headers,
        ).json()

        enqueued: list[dict] = []

        async def mock_enqueue(**kwargs):
            enqueued.append(kwargs)
            return "arq_job_123"

        monkeypatch.setattr("app.routers.integrations.enqueue_sync_job", mock_enqueue)

        sync_resp = wm_env.client.post(
            f"/orgs/{org.id}/integrations/{integ['id']}/sync?background=true",
            headers=headers,
        )
        assert sync_resp.status_code == 200
        data = sync_resp.json()
        assert data["queued"] is True
        assert data["status"] == SyncRunStatus.PENDING.value
        assert data["sync_run_id"] is not None
        assert len(enqueued) == 1
        assert str(enqueued[0]["sync_run_id"]) == data["sync_run_id"]

        runs_resp = wm_env.client.get(f"/orgs/{org.id}/sync-runs", headers=headers)
        assert runs_resp.status_code == 200
        runs = runs_resp.json()
        assert len(runs) == 1
        assert runs[0]["status"] == SyncRunStatus.PENDING.value

    def test_background_sync_queue_failure_marks_run_failed_and_returns_503(
        self, wm_env, monkeypatch
    ):
        org, _, owner_tok = wm_env.make_org_owner()
        headers = {"Authorization": f"Bearer {owner_tok}"}
        integ = wm_env.client.post(
            f"/orgs/{org.id}/integrations",
            json={"provider": "fake", "credentials": {}},
            headers=headers,
        ).json()

        async def broken_enqueue(**_kwargs):
            raise RuntimeError("Redis queue unavailable")

        monkeypatch.setattr("app.routers.integrations.enqueue_sync_job", broken_enqueue)

        resp = wm_env.client.post(
            f"/orgs/{org.id}/integrations/{integ['id']}/sync?background=true",
            headers=headers,
        )
        assert resp.status_code == 503
        assert "Background worker queue unavailable" in resp.json()["detail"]

        runs = wm_env.client.get(f"/orgs/{org.id}/sync-runs", headers=headers).json()
        assert len(runs) == 1
        assert runs[0]["status"] == SyncRunStatus.FAILED.value
        assert "Failed to enqueue" in (runs[0]["error_message"] or "")

    @pytest.mark.anyio
    async def test_sync_integration_job_executes_and_completes_run(
        self, wm_env, monkeypatch
    ):
        org, _, owner_tok = wm_env.make_org_owner()
        headers = {"Authorization": f"Bearer {owner_tok}"}
        integ = wm_env.client.post(
            f"/orgs/{org.id}/integrations",
            json={"provider": "razorpay", "credentials": {"mode": "mock"}},
            headers=headers,
        ).json()

        # Bind worker's SessionLocal to the isolated test session without closing outer conn
        class NonClosingSessionProxy:
            def __init__(self, inner: Session):
                self._inner = inner

            def __getattr__(self, name):
                return getattr(self._inner, name)

            def close(self):
                pass

        monkeypatch.setattr(
            worker, "SessionLocal", lambda: NonClosingSessionProxy(wm_env.session)
        )

        result = await worker.sync_integration_job(
            {},
            str(org.id),
            integ["id"],
        )
        assert result["status"] == "active"
        assert result["inserted_count"] == 5

        runs = wm_env.client.get(f"/orgs/{org.id}/sync-runs", headers=headers).json()
        assert len(runs) == 1
        assert runs[0]["status"] == SyncRunStatus.COMPLETED.value
        assert runs[0]["events_inserted"] == 5

    def test_sync_failure_records_failed_sync_run(self, wm_env):
        org, _, owner_tok = wm_env.make_org_owner()
        headers = {"Authorization": f"Bearer {owner_tok}"}

        # Connect fake integration then force failure via custom credentials stored directly
        integ = wm_env.client.post(
            f"/orgs/{org.id}/integrations",
            json={"provider": "fake", "credentials": {}},
            headers=headers,
        ).json()

        from app.core.security import encrypt_credentials
        from app.models.integration import Integration

        db_integ = wm_env.session.get(Integration, uuid.UUID(integ["id"]))
        db_integ.credentials_encrypted = encrypt_credentials('{"fail_auth": true}')
        wm_env.session.flush()

        resp = wm_env.client.post(
            f"/orgs/{org.id}/integrations/{integ['id']}/sync",
            headers=headers,
        )
        assert resp.status_code == 502

        runs = wm_env.client.get(f"/orgs/{org.id}/sync-runs", headers=headers).json()
        assert len(runs) == 1
        assert runs[0]["status"] == SyncRunStatus.FAILED.value
        assert "rejected" in (runs[0]["error_message"] or "")

    @pytest.mark.anyio
    async def test_worker_retry_on_transient_failure(self, monkeypatch):
        from arq import Retry

        assert worker.WorkerSettings.max_tries == 3
        assert worker.WorkerSettings.health_check_interval == 15

        def boom(*args, **kwargs):
            raise RuntimeError("transient network blip")

        monkeypatch.setattr(
            "app.services.integration_service.sync_integration", boom
        )
        with pytest.raises(Retry):
            await worker.sync_integration_job(
                {"job_try": 1},
                str(uuid.uuid4()),
                str(uuid.uuid4()),
            )

    @pytest.mark.anyio
    async def test_worker_final_retry_marks_sync_run_failed(
        self, wm_env, monkeypatch
    ):
        org, _, owner_tok = wm_env.make_org_owner()
        headers = {"Authorization": f"Bearer {owner_tok}"}
        integ = wm_env.client.post(
            f"/orgs/{org.id}/integrations",
            json={"provider": "fake", "credentials": {}},
            headers=headers,
        ).json()

        class NonClosingSessionProxy:
            def __init__(self, inner: Session):
                self._inner = inner

            def __getattr__(self, name):
                return getattr(self._inner, name)

            def close(self):
                pass

        from app.services import integration_service

        run = integration_service.create_pending_sync_run(
            wm_env.session,
            organization_id=org.id,
            integration_id=uuid.UUID(integ["id"]),
        )
        monkeypatch.setattr(
            worker, "SessionLocal", lambda: NonClosingSessionProxy(wm_env.session)
        )
        monkeypatch.setattr(
            "app.services.integration_service.sync_integration",
            lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("fatal sync crash")),
        )

        with pytest.raises(RuntimeError, match="fatal sync crash"):
            await worker.sync_integration_job(
                {"job_try": worker.WorkerSettings.max_tries},
                str(org.id),
                integ["id"],
                str(run.id),
            )

        runs = wm_env.client.get(f"/orgs/{org.id}/sync-runs", headers=headers).json()
        assert len(runs) == 1
        assert runs[0]["status"] == SyncRunStatus.FAILED.value
        assert "fatal sync crash" in (runs[0]["error_message"] or "")


# ---------------------------------------------------------------------------
# S19–S21: Metrics Engine, Events API & Multi-Tenant Isolation
# ---------------------------------------------------------------------------


class TestMetricsEngineAndEndpoints:
    def test_metrics_summary_and_timeseries_calculations(self, wm_env):
        org, _, owner_tok = wm_env.make_org_owner()
        headers = {"Authorization": f"Bearer {owner_tok}"}

        # Revenue & churn events
        wm_env.add_event(
            org=org,
            source="razorpay",
            external_id="sub_1",
            event_type="subscription.charged",
            days_ago=2,
            amount_cents=10000,
            currency="USD",
            actor="cust_1",
        )
        wm_env.add_event(
            org=org,
            source="razorpay",
            external_id="sub_2",
            event_type="subscription.charged",
            days_ago=2,
            amount_cents=20000,
            currency="USD",
            actor="cust_2",
        )
        wm_env.add_event(
            org=org,
            source="razorpay",
            external_id="ref_1",
            event_type="payment.refunded",
            days_ago=1,
            amount_cents=2000,
            currency="USD",
            actor="cust_1",
        )
        wm_env.add_event(
            org=org,
            source="razorpay",
            external_id="cancel_1",
            event_type="subscription.cancelled",
            days_ago=1,
            amount_cents=5000,
            currency="USD",
            actor="cust_3",
        )

        # Engineering events (2 opened, 1 closed -> 1 open issue)
        wm_env.add_event(
            org=org,
            source="github",
            external_id="pr_1",
            event_type="pr.opened",
            days_ago=3,
            actor="alice",
        )
        wm_env.add_event(
            org=org,
            source="github",
            external_id="pr_2",
            event_type="pr.merged",
            days_ago=2,
            actor="bob",
            payload={"number": 2, "cycle_time_hours": 6.0},
        )
        wm_env.add_event(
            org=org,
            source="github",
            external_id="iss_1_open",
            event_type="issue.opened",
            days_ago=4,
            actor="alice",
            payload={"repo": "acme/app", "number": 10},
        )
        wm_env.add_event(
            org=org,
            source="github",
            external_id="iss_2_open",
            event_type="issue.opened",
            days_ago=3,
            actor="alice",
            payload={"repo": "acme/app", "number": 11},
        )
        wm_env.add_event(
            org=org,
            source="github",
            external_id="iss_1_close",
            event_type="issue.closed",
            days_ago=1,
            actor="bob",
            payload={"repo": "acme/app", "number": 10, "cycle_time_hours": 18.0},
        )

        summary_resp = wm_env.client.get(
            f"/orgs/{org.id}/metrics/summary?days=30", headers=headers
        )
        assert summary_resp.status_code == 200
        s = summary_resp.json()
        assert s["gross_revenue_cents"] == 30000
        assert s["refunded_cents"] == 2000
        assert s["churned_mrr_cents"] == 5000
        # cust_1 (10000 - 2000 refund = 8000) + cust_2 (20000) = 28000; cust_3 wasn't active in window
        assert s["mrr_cents"] == 28000
        assert s["arr_cents"] == 28000 * 12
        assert s["by_currency"]["USD"]["recurring_mrr_minor"] == 28000
        assert s["by_currency"]["USD"]["subscription_revenue_minor"] == 30000
        assert s["by_currency"]["USD"]["one_time_payment_volume_minor"] == 0
        assert s["active_subscribers_count"] == 2
        assert s["churned_subscriptions_count"] == 1
        assert s["churn_rate_pct"] == 33.33
        assert s["prs_opened"] == 1
        assert s["prs_merged"] == 1
        assert s["open_issues_count"] == 1
        assert s["issues_closed_count"] == 1
        assert s["avg_issue_cycle_time_hours"] == 18.0
        assert s["avg_pr_cycle_time_hours"] == 6.0
        assert s["total_events_in_window"] == 9

        ts_resp = wm_env.client.get(
            f"/orgs/{org.id}/metrics/timeseries?days=7", headers=headers
        )
        assert ts_resp.status_code == 200
        ts = ts_resp.json()
        assert len(ts["points"]) == 7
        assert sum(p["revenue_cents"] for p in ts["points"]) == 30000
        assert sum(p["prs_merged"] for p in ts["points"]) == 1

        ev_resp = wm_env.client.get(
            f"/orgs/{org.id}/events?source=github", headers=headers
        )
        assert ev_resp.status_code == 200
        assert len(ev_resp.json()) == 5

    def test_metrics_and_events_enforce_strict_tenant_isolation(self, wm_env):
        org_a, _, owner_a = wm_env.make_org_owner()
        org_b, _, owner_b = wm_env.make_org_owner()

        wm_env.add_event(
            org=org_a,
            source="razorpay",
            external_id="secret_a",
            event_type="subscription.charged",
            amount_cents=99900,
        )

        # Org B has 0 MRR
        b_summary = wm_env.client.get(
            f"/orgs/{org_b.id}/metrics/summary",
            headers={"Authorization": f"Bearer {owner_b}"},
        ).json()
        assert b_summary["mrr_cents"] == 0
        assert b_summary["total_events_in_window"] == 0

        # Org B owner cannot query Org A metrics, events, or sync-runs -> 404
        h_b = {"Authorization": f"Bearer {owner_b}"}
        assert wm_env.client.get(f"/orgs/{org_a.id}/metrics/summary", headers=h_b).status_code == 404
        assert wm_env.client.get(f"/orgs/{org_a.id}/metrics/timeseries", headers=h_b).status_code == 404
        assert wm_env.client.get(f"/orgs/{org_a.id}/events", headers=h_b).status_code == 404
        assert wm_env.client.get(f"/orgs/{org_a.id}/sync-runs", headers=h_b).status_code == 404
