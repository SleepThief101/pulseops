"""
S40–S47 End-to-End SaaS Control Tower Journey & Regression Verification.

Exercises the complete lifecycle inside an isolated rolled-back transaction:
1. Register Tenant A & Tenant B -> Login -> /me/organizations.
2. Connect Razorpay (mock fallback) & GitHub (mock) -> Sync integrations.
3. Import historical revenue CSV rows.
4. Query /metrics/summary, /metrics/timeseries, /events, and /sync-runs.
5. Query Copilot Chat briefing & propose sync -> Human-in-the-loop Approval -> Executed.
6. Verify Tenant B remains 100% isolated (0 metrics, 404 on every Tenant A ID).
"""

from __future__ import annotations

from datetime import datetime, timezone
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import generate_encryption_key
from app.db.session import get_db
from app.main import app

TEST_JWT_SECRET = "test-jwt-secret-key-for-s40-s47-e2e-suite"


@pytest.fixture(autouse=True)
def patch_secrets(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "jwt_secret_key", TEST_JWT_SECRET)
    monkeypatch.setattr(
        settings, "integration_encryption_key", generate_encryption_key()
    )
    monkeypatch.setattr(settings, "deepseek_api_key", None)


@pytest.fixture()
def e2e_client(test_engine):
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
    try:
        with TestClient(app, raise_server_exceptions=True) as client:
            yield client
    finally:
        app.dependency_overrides.clear()
        if transaction.is_active:
            transaction.rollback()
        connection.close()


def test_full_end_to_end_control_tower_journey_and_isolation(e2e_client: TestClient):
    suffix = uuid.uuid4().hex[:8]
    email_a = f"founder_a_{suffix}@example.com"
    email_b = f"founder_b_{suffix}@example.com"
    password = "E2EStrongPassword123!"

    # 1. Register Tenant A and Tenant B
    reg_a = e2e_client.post(
        "/auth/register",
        json={
            "email": email_a,
            "password": password,
            "organization_name": f"Acme Control {suffix}",
        },
    )
    assert reg_a.status_code == 201
    org_a_id = reg_a.json()["organization_id"]

    reg_b = e2e_client.post(
        "/auth/register",
        json={
            "email": email_b,
            "password": password,
            "organization_name": f"Beta Control {suffix}",
        },
    )
    assert reg_b.status_code == 201
    org_b_id = reg_b.json()["organization_id"]

    # 2. Login and resolve /me/organizations
    tok_a = e2e_client.post(
        "/auth/login", json={"email": email_a, "password": password}
    ).json()["access_token"]
    tok_b = e2e_client.post(
        "/auth/login", json={"email": email_b, "password": password}
    ).json()["access_token"]

    h_a = {"Authorization": f"Bearer {tok_a}"}
    h_b = {"Authorization": f"Bearer {tok_b}"}

    orgs_a = e2e_client.get("/me/organizations", headers=h_a)
    assert orgs_a.status_code == 200
    assert orgs_a.json()[0]["organization_id"] == org_a_id

    # 3. Connect & sync Razorpay (mock fallback) and GitHub (mock)
    rzp = e2e_client.post(
        f"/orgs/{org_a_id}/integrations",
        json={"provider": "razorpay", "credentials": {"mode": "mock"}},
        headers=h_a,
    )
    assert rzp.status_code == 201
    rzp_id = rzp.json()["id"]

    gh = e2e_client.post(
        f"/orgs/{org_a_id}/integrations",
        json={"provider": "github", "credentials": {"mode": "mock", "repo": "acme/tower"}},
        headers=h_a,
    )
    assert gh.status_code == 201
    gh_id = gh.json()["id"]

    assert (
        e2e_client.post(
            f"/orgs/{org_a_id}/integrations/{rzp_id}/sync", headers=h_a
        ).status_code
        == 200
    )
    assert (
        e2e_client.post(
            f"/orgs/{org_a_id}/integrations/{gh_id}/sync", headers=h_a
        ).status_code
        == 200
    )

    # 4. CSV import adds supplemental MRR event
    now_iso = datetime.now(timezone.utc).isoformat()
    csv_resp = e2e_client.post(
        f"/orgs/{org_a_id}/imports/csv",
        json={
            "csv_text": (
                "event_type,occurred_at,amount_cents,currency,actor\n"
                f"subscription.charged,{now_iso},10000,USD,cust_csv_e2e\n"
            )
        },
        headers=h_a,
    )
    assert csv_resp.status_code == 201
    assert csv_resp.json()["inserted_count"] == 1

    # 5. Metrics summary & timeseries reflect Razorpay + GitHub + CSV data
    summary = e2e_client.get(
        f"/orgs/{org_a_id}/metrics/summary?days=30", headers=h_a
    )
    assert summary.status_code == 200
    s_data = summary.json()
    assert s_data["mrr_cents"] > 0
    assert s_data["prs_merged"] >= 1
    assert s_data["open_issues_count"] >= 0
    assert s_data["avg_issue_cycle_time_hours"] == 14.0

    ts = e2e_client.get(
        f"/orgs/{org_a_id}/metrics/timeseries?days=30", headers=h_a
    )
    assert ts.status_code == 200
    assert len(ts.json()["points"]) == 30

    events_list = e2e_client.get(f"/orgs/{org_a_id}/events", headers=h_a)
    assert events_list.status_code == 200
    assert len(events_list.json()) == 10

    runs_list = e2e_client.get(f"/orgs/{org_a_id}/sync-runs", headers=h_a)
    assert runs_list.status_code == 200
    assert len(runs_list.json()) == 2

    # 6. Copilot chat briefing + proposal approval workflow
    briefing = e2e_client.post(
        f"/orgs/{org_a_id}/copilot/chat",
        json={"message": "Give me an executive overview"},
        headers=h_a,
    )
    assert briefing.status_code == 200
    assert "Net MRR:" in briefing.json()["reply"]

    propose = e2e_client.post(
        f"/orgs/{org_a_id}/copilot/chat",
        json={"message": "Sync my github integration"},
        headers=h_a,
    )
    assert propose.status_code == 200
    proposal_id = propose.json()["pending_proposals"][0]["id"]

    decision = e2e_client.post(
        f"/orgs/{org_a_id}/copilot/proposals/{proposal_id}/decision",
        json={"decision": "approve"},
        headers=h_a,
    )
    assert decision.status_code == 200
    assert decision.json()["status"] == "executed"

    # 7. Tenant B cannot see or touch any Tenant A resource
    assert e2e_client.get(f"/orgs/{org_b_id}/metrics/summary", headers=h_b).json()["mrr_cents"] == 0
    for cross_path in (
        f"/orgs/{org_a_id}/metrics/summary",
        f"/orgs/{org_a_id}/events",
        f"/orgs/{org_a_id}/integrations",
        f"/orgs/{org_a_id}/sync-runs",
        f"/orgs/{org_a_id}/copilot/proposals",
    ):
        assert e2e_client.get(cross_path, headers=h_b).status_code == 404
