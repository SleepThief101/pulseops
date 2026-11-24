"""
S07 Organization Membership and Role-Based Authorization Tests.

Verifies:
- get_current_membership authorization dependency (404 for non-members).
- require_role authorization dependency (403 for insufficient roles).
- POST /orgs/{org_id}/members (owner only, existing user lookup, duplicate check, 404/409/422 handling).
- GET /orgs/{org_id}/members (all active members, no password hash exposure).
- Transactional rollback and dedicated test database isolation.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.auth import (
    create_access_token,
    get_password_hash,
    require_role,
)
from app.db.session import get_db
from app.main import app
from app.models.membership import Membership, MembershipRole
from app.models.organization import Organization
from app.models.user import User

TEST_JWT_SECRET = "test-jwt-secret-key-for-s07-tests-only"


@pytest.fixture(autouse=True)
def patch_jwt_secret(monkeypatch):
    """Inject a stable test JWT secret for every test in this module."""
    from app.config import settings

    monkeypatch.setattr(settings, "jwt_secret_key", TEST_JWT_SECRET)


@pytest.fixture()
def member_env(test_engine):
    """
    Provide an isolated test client and database session factory bound to
    the dedicated test database via an outer rolled-back transaction.
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

    # Setup session for fixture data creation
    setup_session = Session(
        bind=connection,
        join_transaction_mode="create_savepoint",
        expire_on_commit=False,
    )

    class TestEnvironment:
        def __init__(self, client: TestClient, session: Session):
            self.client = client
            self.session = session

        def create_user(self, email_prefix: str) -> tuple[User, str]:
            """Create a test user and return (User, bearer_token)."""
            u_email = f"s07_{email_prefix}_{uuid.uuid4().hex[:8]}@example.com"
            user = User(
                email=u_email,
                password_hash=get_password_hash("SecretPass123!"),
            )
            self.session.add(user)
            self.session.flush()
            token = create_access_token(user.id)
            return user, token

        def create_org(self, name_prefix: str) -> Organization:
            """Create a test organization."""
            org = Organization(name=f"S07 Org {name_prefix} {uuid.uuid4().hex[:8]}")
            self.session.add(org)
            self.session.flush()
            return org

        def add_membership(
            self, user: User, org: Organization, role: str
        ) -> Membership:
            """Create a membership directly in the database."""
            membership = Membership(
                user_id=user.id,
                organization_id=org.id,
                role=role,
            )
            self.session.add(membership)
            self.session.flush()
            return membership

        def auth_headers(self, token: str) -> dict[str, str]:
            return {"Authorization": f"Bearer {token}"}

    try:
        with TestClient(app, raise_server_exceptions=True) as client:
            env = TestEnvironment(client, setup_session)
            yield env
    finally:
        setup_session.close()
        app.dependency_overrides.clear()
        if transaction.is_active:
            transaction.rollback()
        connection.close()


# ---------------------------------------------------------------------------
# Unit tests for require_role
# ---------------------------------------------------------------------------


def test_require_role_invalid_role_raises_value_error():
    """Verify require_role fails fast when configured with an unrecognized role."""
    with pytest.raises(ValueError, match="Invalid role"):
        require_role("superadmin")


# ---------------------------------------------------------------------------
# POST /orgs/{org_id}/members tests
# ---------------------------------------------------------------------------


class TestAddMember:
    def test_owner_successfully_adds_existing_user_as_member(self, member_env):
        owner, owner_token = member_env.create_user("owner")
        org = member_env.create_org("Main")
        member_env.add_membership(owner, org, MembershipRole.OWNER.value)

        target_user, _ = member_env.create_user("target")

        resp = member_env.client.post(
            f"/orgs/{org.id}/members",
            headers=member_env.auth_headers(owner_token),
            json={"email": target_user.email, "role": "member"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["organization_id"] == str(org.id)
        assert data["user_id"] == str(target_user.id)
        assert data["role"] == "member"
        assert data["email"] == target_user.email
        assert "user" in data
        assert data["user"]["id"] == str(target_user.id)
        assert data["user"]["email"] == target_user.email
        # Ensure password_hash is never exposed
        assert "password_hash" not in resp.text

    def test_owner_can_add_user_as_viewer(self, member_env):
        owner, owner_token = member_env.create_user("owner")
        org = member_env.create_org("Main")
        member_env.add_membership(owner, org, MembershipRole.OWNER.value)

        target_user, _ = member_env.create_user("target_viewer")

        resp = member_env.client.post(
            f"/orgs/{org.id}/members",
            headers=member_env.auth_headers(owner_token),
            json={"email": target_user.email, "role": "viewer"},
        )
        assert resp.status_code == 201
        assert resp.json()["role"] == "viewer"

    def test_owner_can_add_user_as_owner(self, member_env):
        owner, owner_token = member_env.create_user("owner")
        org = member_env.create_org("Main")
        member_env.add_membership(owner, org, MembershipRole.OWNER.value)

        target_user, _ = member_env.create_user("target_owner")

        resp = member_env.client.post(
            f"/orgs/{org.id}/members",
            headers=member_env.auth_headers(owner_token),
            json={"email": target_user.email, "role": "owner"},
        )
        assert resp.status_code == 201
        assert resp.json()["role"] == "owner"

    def test_default_role_is_member(self, member_env):
        owner, owner_token = member_env.create_user("owner")
        org = member_env.create_org("Main")
        member_env.add_membership(owner, org, MembershipRole.OWNER.value)

        target_user, _ = member_env.create_user("target_default")

        # Omit role in payload; default must be member
        resp = member_env.client.post(
            f"/orgs/{org.id}/members",
            headers=member_env.auth_headers(owner_token),
            json={"email": target_user.email},
        )
        assert resp.status_code == 201
        assert resp.json()["role"] == "member"

    def test_member_cannot_add_members_returns_403(self, member_env):
        member_user, member_token = member_env.create_user("member")
        org = member_env.create_org("Main")
        member_env.add_membership(member_user, org, MembershipRole.MEMBER.value)

        target_user, _ = member_env.create_user("target")

        resp = member_env.client.post(
            f"/orgs/{org.id}/members",
            headers=member_env.auth_headers(member_token),
            json={"email": target_user.email, "role": "member"},
        )
        assert resp.status_code == 403
        assert "Insufficient permissions" in resp.json()["detail"]

    def test_viewer_cannot_add_members_returns_403(self, member_env):
        viewer_user, viewer_token = member_env.create_user("viewer")
        org = member_env.create_org("Main")
        member_env.add_membership(viewer_user, org, MembershipRole.VIEWER.value)

        target_user, _ = member_env.create_user("target")

        resp = member_env.client.post(
            f"/orgs/{org.id}/members",
            headers=member_env.auth_headers(viewer_token),
            json={"email": target_user.email, "role": "viewer"},
        )
        assert resp.status_code == 403
        assert "Insufficient permissions" in resp.json()["detail"]

    def test_user_from_another_org_cannot_add_member_returns_404(self, member_env):
        foreign_owner, foreign_token = member_env.create_user("foreign")
        foreign_org = member_env.create_org("Foreign")
        member_env.add_membership(foreign_owner, foreign_org, MembershipRole.OWNER.value)

        target_org = member_env.create_org("TargetOrg")
        target_user, _ = member_env.create_user("target")

        # foreign_owner attempts to add someone to target_org
        resp = member_env.client.post(
            f"/orgs/{target_org.id}/members",
            headers=member_env.auth_headers(foreign_token),
            json={"email": target_user.email, "role": "member"},
        )
        # Must return 404 to avoid revealing whether target_org exists
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Organization not found."

    def test_add_member_nonexistent_org_returns_404(self, member_env):
        owner, owner_token = member_env.create_user("owner")
        target_user, _ = member_env.create_user("target")
        random_org_id = uuid.uuid4()

        resp = member_env.client.post(
            f"/orgs/{random_org_id}/members",
            headers=member_env.auth_headers(owner_token),
            json={"email": target_user.email, "role": "member"},
        )
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Organization not found."

    def test_add_nonexistent_user_returns_404(self, member_env):
        owner, owner_token = member_env.create_user("owner")
        org = member_env.create_org("Main")
        member_env.add_membership(owner, org, MembershipRole.OWNER.value)

        resp = member_env.client.post(
            f"/orgs/{org.id}/members",
            headers=member_env.auth_headers(owner_token),
            json={"email": "nonexistent_person_12345@example.com", "role": "member"},
        )
        assert resp.status_code == 404
        assert resp.json()["detail"] == "User not found."

    def test_add_duplicate_member_returns_409(self, member_env):
        owner, owner_token = member_env.create_user("owner")
        org = member_env.create_org("Main")
        member_env.add_membership(owner, org, MembershipRole.OWNER.value)

        target_user, _ = member_env.create_user("target")
        # Add target user once
        member_env.add_membership(target_user, org, MembershipRole.MEMBER.value)

        # Attempt to add same user again
        resp = member_env.client.post(
            f"/orgs/{org.id}/members",
            headers=member_env.auth_headers(owner_token),
            json={"email": target_user.email, "role": "member"},
        )
        assert resp.status_code == 409
        assert "already a member" in resp.json()["detail"]

    def test_add_member_invalid_role_returns_422(self, member_env):
        owner, owner_token = member_env.create_user("owner")
        org = member_env.create_org("Main")
        member_env.add_membership(owner, org, MembershipRole.OWNER.value)

        target_user, _ = member_env.create_user("target")

        resp = member_env.client.post(
            f"/orgs/{org.id}/members",
            headers=member_env.auth_headers(owner_token),
            json={"email": target_user.email, "role": "superadmin"},
        )
        assert resp.status_code == 422

    def test_add_member_unauthenticated_returns_401(self, member_env):
        org_id = uuid.uuid4()
        resp = member_env.client.post(
            f"/orgs/{org_id}/members",
            json={"email": "anyone@example.com", "role": "member"},
        )
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# GET /orgs/{org_id}/members tests
# ---------------------------------------------------------------------------


class TestListMembers:
    def test_owner_can_list_members(self, member_env):
        owner, owner_token = member_env.create_user("owner")
        org = member_env.create_org("Main")
        member_env.add_membership(owner, org, MembershipRole.OWNER.value)

        m1, _ = member_env.create_user("m1")
        member_env.add_membership(m1, org, MembershipRole.MEMBER.value)

        resp = member_env.client.get(
            f"/orgs/{org.id}/members",
            headers=member_env.auth_headers(owner_token),
        )
        assert resp.status_code == 200
        members = resp.json()
        assert len(members) == 2
        emails = {m["email"] for m in members}
        assert owner.email in emails
        assert m1.email in emails
        # Ensure password_hash is never exposed
        assert "password_hash" not in resp.text

    def test_member_can_list_members(self, member_env):
        owner, _ = member_env.create_user("owner")
        org = member_env.create_org("Main")
        member_env.add_membership(owner, org, MembershipRole.OWNER.value)

        member_user, member_token = member_env.create_user("regular_member")
        member_env.add_membership(member_user, org, MembershipRole.MEMBER.value)

        resp = member_env.client.get(
            f"/orgs/{org.id}/members",
            headers=member_env.auth_headers(member_token),
        )
        assert resp.status_code == 200
        members = resp.json()
        assert len(members) == 2

    def test_viewer_can_list_members(self, member_env):
        owner, _ = member_env.create_user("owner")
        org = member_env.create_org("Main")
        member_env.add_membership(owner, org, MembershipRole.OWNER.value)

        viewer_user, viewer_token = member_env.create_user("viewer_user")
        member_env.add_membership(viewer_user, org, MembershipRole.VIEWER.value)

        resp = member_env.client.get(
            f"/orgs/{org.id}/members",
            headers=member_env.auth_headers(viewer_token),
        )
        assert resp.status_code == 200
        members = resp.json()
        assert len(members) == 2

    def test_user_from_another_org_cannot_list_members_returns_404(self, member_env):
        user_a, token_a = member_env.create_user("user_a")
        org_a = member_env.create_org("OrgA")
        member_env.add_membership(user_a, org_a, MembershipRole.OWNER.value)

        org_b = member_env.create_org("OrgB")

        # user_a tries to list members of org_b
        resp = member_env.client.get(
            f"/orgs/{org_b.id}/members",
            headers=member_env.auth_headers(token_a),
        )
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Organization not found."

    def test_list_members_nonexistent_org_returns_404(self, member_env):
        user, token = member_env.create_user("user")
        random_org_id = uuid.uuid4()

        resp = member_env.client.get(
            f"/orgs/{random_org_id}/members",
            headers=member_env.auth_headers(token),
        )
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Organization not found."

    def test_list_members_unauthenticated_returns_401(self, member_env):
        org_id = uuid.uuid4()
        resp = member_env.client.get(f"/orgs/{org_id}/members")
        assert resp.status_code == 401
