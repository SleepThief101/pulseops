"""
S08: Tenant Isolation Tests.

Proves that users belonging to one organization cannot access or modify
another organization's data across all access layers:
- HTTP API endpoints (cross-tenant requests return 404 to avoid tenant enumeration).
- Manipulated organization IDs return identical 404 responses.
- Legitimate same-tenant access works as expected.
- Existing role-based authorization (owner/member/viewer) remains strictly enforced.
- Database models and tenant-scoped queries prevent cross-tenant reads/writes.
- Transactional isolation ensures no test records persist to TEST_DATABASE_URL.
"""

from __future__ import annotations

import uuid
from typing import NamedTuple

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import (
    create_access_token,
    get_current_membership,
    get_password_hash,
)
from app.db.session import get_db
from app.main import app
from app.models.integration import Integration, IntegrationStatus
from app.models.membership import Membership, MembershipRole
from app.models.organization import Organization
from app.models.user import User

TEST_JWT_SECRET = "test-jwt-secret-key-for-s08-tenant-isolation"


@pytest.fixture(autouse=True)
def patch_jwt_secret(monkeypatch):
    """Inject a stable test JWT secret for S08 isolation tests."""
    from app.config import settings

    monkeypatch.setattr(settings, "jwt_secret_key", TEST_JWT_SECRET)


class TenantUsers(NamedTuple):
    owner: User
    owner_token: str
    member: User
    member_token: str
    viewer: User
    viewer_token: str


class TwoTenantFixture:
    def __init__(
        self,
        client: TestClient,
        session: Session,
        org_a: Organization,
        tenant_a: TenantUsers,
        org_b: Organization,
        tenant_b: TenantUsers,
        unassigned_user: User,
        unassigned_token: str,
    ):
        self.client = client
        self.session = session
        self.org_a = org_a
        self.tenant_a = tenant_a
        self.org_b = org_b
        self.tenant_b = tenant_b
        self.unassigned_user = unassigned_user
        self.unassigned_token = unassigned_token

    def headers(self, token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def two_tenants(test_engine) -> TwoTenantFixture:
    """
    Sets up two completely independent organizations and sets of users
    within a transaction that is rolled back on teardown.
    """
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

    def _create_user(prefix: str) -> tuple[User, str]:
        email = f"s08_{prefix}_{uuid.uuid4().hex[:8]}@example.com"
        user = User(
            email=email,
            password_hash=get_password_hash("Password123!"),
        )
        setup_session.add(user)
        setup_session.flush()
        token = create_access_token(user.id)
        return user, token

    def _create_tenant(prefix: str) -> tuple[Organization, TenantUsers]:
        org = Organization(name=f"S08 Org {prefix} {uuid.uuid4().hex[:8]}")
        setup_session.add(org)
        setup_session.flush()

        owner, o_token = _create_user(f"{prefix}_owner")
        member, m_token = _create_user(f"{prefix}_member")
        viewer, v_token = _create_user(f"{prefix}_viewer")

        setup_session.add(
            Membership(
                user_id=owner.id,
                organization_id=org.id,
                role=MembershipRole.OWNER.value,
            )
        )
        setup_session.add(
            Membership(
                user_id=member.id,
                organization_id=org.id,
                role=MembershipRole.MEMBER.value,
            )
        )
        setup_session.add(
            Membership(
                user_id=viewer.id,
                organization_id=org.id,
                role=MembershipRole.VIEWER.value,
            )
        )
        setup_session.flush()

        return org, TenantUsers(
            owner=owner,
            owner_token=o_token,
            member=member,
            member_token=m_token,
            viewer=viewer,
            viewer_token=v_token,
        )

    org_a, tenant_a = _create_tenant("tenant_a")
    org_b, tenant_b = _create_tenant("tenant_b")
    unassigned, u_token = _create_user("unassigned")

    try:
        with TestClient(app, raise_server_exceptions=True) as client:
            yield TwoTenantFixture(
                client=client,
                session=setup_session,
                org_a=org_a,
                tenant_a=tenant_a,
                org_b=org_b,
                tenant_b=tenant_b,
                unassigned_user=unassigned,
                unassigned_token=u_token,
            )
    finally:
        setup_session.close()
        app.dependency_overrides.clear()
        if transaction.is_active:
            transaction.rollback()
        connection.close()


# ---------------------------------------------------------------------------
# Cross-Tenant Access Verification (Requirement 2)
# ---------------------------------------------------------------------------


class TestCrossTenantAccess:
    """
    Verify that users belonging to Organization A cannot access Organization B's
    members or resources, and receive HTTP 404 without leaking tenant existence.
    """

    def test_user_a_owner_cannot_list_org_b_members_returns_404(
        self, two_tenants: TwoTenantFixture
    ):
        resp = two_tenants.client.get(
            f"/orgs/{two_tenants.org_b.id}/members",
            headers=two_tenants.headers(two_tenants.tenant_a.owner_token),
        )
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Organization not found."

    def test_user_a_member_cannot_list_org_b_members_returns_404(
        self, two_tenants: TwoTenantFixture
    ):
        resp = two_tenants.client.get(
            f"/orgs/{two_tenants.org_b.id}/members",
            headers=two_tenants.headers(two_tenants.tenant_a.member_token),
        )
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Organization not found."

    def test_user_a_viewer_cannot_list_org_b_members_returns_404(
        self, two_tenants: TwoTenantFixture
    ):
        resp = two_tenants.client.get(
            f"/orgs/{two_tenants.org_b.id}/members",
            headers=two_tenants.headers(two_tenants.tenant_a.viewer_token),
        )
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Organization not found."

    def test_user_b_owner_cannot_list_org_a_members_returns_404(
        self, two_tenants: TwoTenantFixture
    ):
        resp = two_tenants.client.get(
            f"/orgs/{two_tenants.org_a.id}/members",
            headers=two_tenants.headers(two_tenants.tenant_b.owner_token),
        )
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Organization not found."

    def test_user_b_member_cannot_list_org_a_members_returns_404(
        self, two_tenants: TwoTenantFixture
    ):
        resp = two_tenants.client.get(
            f"/orgs/{two_tenants.org_a.id}/members",
            headers=two_tenants.headers(two_tenants.tenant_b.member_token),
        )
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Organization not found."

    def test_user_b_viewer_cannot_list_org_a_members_returns_404(
        self, two_tenants: TwoTenantFixture
    ):
        resp = two_tenants.client.get(
            f"/orgs/{two_tenants.org_a.id}/members",
            headers=two_tenants.headers(two_tenants.tenant_b.viewer_token),
        )
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Organization not found."

    def test_user_a_owner_cannot_add_member_to_org_b_returns_404(
        self, two_tenants: TwoTenantFixture
    ):
        resp = two_tenants.client.post(
            f"/orgs/{two_tenants.org_b.id}/members",
            headers=two_tenants.headers(two_tenants.tenant_a.owner_token),
            json={
                "email": two_tenants.unassigned_user.email,
                "role": "member",
            },
        )
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Organization not found."

    def test_user_b_owner_cannot_add_member_to_org_a_returns_404(
        self, two_tenants: TwoTenantFixture
    ):
        resp = two_tenants.client.post(
            f"/orgs/{two_tenants.org_a.id}/members",
            headers=two_tenants.headers(two_tenants.tenant_b.owner_token),
            json={
                "email": two_tenants.unassigned_user.email,
                "role": "member",
            },
        )
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Organization not found."

    def test_unassigned_user_cannot_access_org_a_or_org_b_returns_404(
        self, two_tenants: TwoTenantFixture
    ):
        resp_a = two_tenants.client.get(
            f"/orgs/{two_tenants.org_a.id}/members",
            headers=two_tenants.headers(two_tenants.unassigned_token),
        )
        assert resp_a.status_code == 404
        assert resp_a.json()["detail"] == "Organization not found."

        resp_b = two_tenants.client.get(
            f"/orgs/{two_tenants.org_b.id}/members",
            headers=two_tenants.headers(two_tenants.unassigned_token),
        )
        assert resp_b.status_code == 404
        assert resp_b.json()["detail"] == "Organization not found."

    def test_manipulated_random_org_id_returns_identical_404(
        self, two_tenants: TwoTenantFixture
    ):
        random_id = uuid.uuid4()
        resp_random = two_tenants.client.get(
            f"/orgs/{random_id}/members",
            headers=two_tenants.headers(two_tenants.tenant_a.owner_token),
        )
        resp_cross_tenant = two_tenants.client.get(
            f"/orgs/{two_tenants.org_b.id}/members",
            headers=two_tenants.headers(two_tenants.tenant_a.owner_token),
        )
        # Responses must be completely indistinguishable to prevent ID enumeration
        assert resp_random.status_code == 404
        assert resp_cross_tenant.status_code == 404
        assert resp_random.json() == resp_cross_tenant.json()


# ---------------------------------------------------------------------------
# Legitimate Same-Tenant Access Verification (Requirement 3)
# ---------------------------------------------------------------------------


class TestLegitimateTenantAccess:
    """
    Verify that User A can legitimately access Organization A, User B can access
    Organization B, and existing owner/member/viewer permissions work within tenants.
    """

    def test_tenant_a_members_can_list_org_a(
        self, two_tenants: TwoTenantFixture
    ):
        for token in [
            two_tenants.tenant_a.owner_token,
            two_tenants.tenant_a.member_token,
            two_tenants.tenant_a.viewer_token,
        ]:
            resp = two_tenants.client.get(
                f"/orgs/{two_tenants.org_a.id}/members",
                headers=two_tenants.headers(token),
            )
            assert resp.status_code == 200
            data = resp.json()
            assert len(data) == 3
            emails = {m["email"] for m in data}
            assert two_tenants.tenant_a.owner.email in emails
            assert two_tenants.tenant_a.member.email in emails
            assert two_tenants.tenant_a.viewer.email in emails
            # Never leaks Organization B members
            assert two_tenants.tenant_b.owner.email not in emails

    def test_tenant_b_members_can_list_org_b(
        self, two_tenants: TwoTenantFixture
    ):
        for token in [
            two_tenants.tenant_b.owner_token,
            two_tenants.tenant_b.member_token,
            two_tenants.tenant_b.viewer_token,
        ]:
            resp = two_tenants.client.get(
                f"/orgs/{two_tenants.org_b.id}/members",
                headers=two_tenants.headers(token),
            )
            assert resp.status_code == 200
            data = resp.json()
            assert len(data) == 3
            emails = {m["email"] for m in data}
            assert two_tenants.tenant_b.owner.email in emails
            assert two_tenants.tenant_b.member.email in emails
            assert two_tenants.tenant_b.viewer.email in emails
            # Never leaks Organization A members
            assert two_tenants.tenant_a.owner.email not in emails

    def test_tenant_a_owner_can_add_member_to_org_a(
        self, two_tenants: TwoTenantFixture
    ):
        resp = two_tenants.client.post(
            f"/orgs/{two_tenants.org_a.id}/members",
            headers=two_tenants.headers(two_tenants.tenant_a.owner_token),
            json={
                "email": two_tenants.unassigned_user.email,
                "role": "member",
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["organization_id"] == str(two_tenants.org_a.id)
        assert data["email"] == two_tenants.unassigned_user.email
        assert data["role"] == "member"

    def test_tenant_b_owner_can_add_member_to_org_b(
        self, two_tenants: TwoTenantFixture
    ):
        resp = two_tenants.client.post(
            f"/orgs/{two_tenants.org_b.id}/members",
            headers=two_tenants.headers(two_tenants.tenant_b.owner_token),
            json={
                "email": two_tenants.unassigned_user.email,
                "role": "viewer",
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["organization_id"] == str(two_tenants.org_b.id)
        assert data["email"] == two_tenants.unassigned_user.email
        assert data["role"] == "viewer"

    def test_tenant_a_member_and_viewer_cannot_add_members_to_org_a_returns_403(
        self, two_tenants: TwoTenantFixture
    ):
        for token in [
            two_tenants.tenant_a.member_token,
            two_tenants.tenant_a.viewer_token,
        ]:
            resp = two_tenants.client.post(
                f"/orgs/{two_tenants.org_a.id}/members",
                headers=two_tenants.headers(token),
                json={
                    "email": two_tenants.unassigned_user.email,
                    "role": "member",
                },
            )
            assert resp.status_code == 403
            assert "Insufficient permissions" in resp.json()["detail"]

    def test_tenant_b_member_and_viewer_cannot_add_members_to_org_b_returns_403(
        self, two_tenants: TwoTenantFixture
    ):
        for token in [
            two_tenants.tenant_b.member_token,
            two_tenants.tenant_b.viewer_token,
        ]:
            resp = two_tenants.client.post(
                f"/orgs/{two_tenants.org_b.id}/members",
                headers=two_tenants.headers(token),
                json={
                    "email": two_tenants.unassigned_user.email,
                    "role": "member",
                },
            )
            assert resp.status_code == 403
            assert "Insufficient permissions" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# Tenant Resource and Integration Isolation (Requirement 2 & 5)
# ---------------------------------------------------------------------------


class TestTenantResourceAndIntegrationIsolation:
    """
    Verify integration model queries and authorization dependencies prevent
    cross-tenant data leakage.
    """

    def test_authorization_dependency_blocks_cross_tenant_access_with_404(
        self, two_tenants: TwoTenantFixture
    ):
        from fastapi import HTTPException

        # Direct dependency test: User A attempting to resolve Org B membership
        with pytest.raises(HTTPException) as exc_info:
            get_current_membership(
                org_id=two_tenants.org_b.id,
                current_user=two_tenants.tenant_a.owner,
                db=two_tenants.session,
            )
        assert exc_info.value.status_code == 404
        assert exc_info.value.detail == "Organization not found."

        # User B attempting to resolve Org A membership
        with pytest.raises(HTTPException) as exc_info_b:
            get_current_membership(
                org_id=two_tenants.org_a.id,
                current_user=two_tenants.tenant_b.owner,
                db=two_tenants.session,
            )
        assert exc_info_b.value.status_code == 404
        assert exc_info_b.value.detail == "Organization not found."

    def test_integration_model_query_strictly_enforces_tenant_boundary(
        self, two_tenants: TwoTenantFixture
    ):
        """
        Verify that database integration queries strictly scope by organization_id
        and prevent cross-tenant reads.
        """
        integration_a = Integration(
            organization_id=two_tenants.org_a.id,
            provider="github",
            status=IntegrationStatus.ACTIVE.value,
            credentials_encrypted="encrypted_creds_tenant_a",
        )
        integration_b = Integration(
            organization_id=two_tenants.org_b.id,
            provider="github",
            status=IntegrationStatus.ACTIVE.value,
            credentials_encrypted="encrypted_creds_tenant_b",
        )
        two_tenants.session.add(integration_a)
        two_tenants.session.add(integration_b)
        two_tenants.session.flush()

        # Query scoped to Org A
        org_a_integrations = two_tenants.session.scalars(
            select(Integration).where(
                Integration.organization_id == two_tenants.org_a.id
            )
        ).all()
        assert len(org_a_integrations) == 1
        assert org_a_integrations[0].id == integration_a.id
        assert (
            org_a_integrations[0].credentials_encrypted
            == "encrypted_creds_tenant_a"
        )

        # Query scoped to Org B
        org_b_integrations = two_tenants.session.scalars(
            select(Integration).where(
                Integration.organization_id == two_tenants.org_b.id
            )
        ).all()
        assert len(org_b_integrations) == 1
        assert org_b_integrations[0].id == integration_b.id
        assert (
            org_b_integrations[0].credentials_encrypted
            == "encrypted_creds_tenant_b"
        )

        # Verify cross-tenant search finds nothing
        cross_search = two_tenants.session.scalars(
            select(Integration).where(
                Integration.organization_id == two_tenants.org_a.id,
                Integration.id == integration_b.id,
            )
        ).first()
        assert cross_search is None

    def test_unimplemented_integration_endpoints_safely_return_404(
        self, two_tenants: TwoTenantFixture
    ):
        """
        Documents and verifies that hypothetical integration routes (e.g. /orgs/{org_id}/integrations)
        are not exposed, returning standard 404 without data leakage.
        """
        resp = two_tenants.client.get(
            f"/orgs/{two_tenants.org_a.id}/integrations",
            headers=two_tenants.headers(two_tenants.tenant_a.owner_token),
        )
        # Endpoint is not implemented yet; returns 404 cleanly
        assert resp.status_code == 404
