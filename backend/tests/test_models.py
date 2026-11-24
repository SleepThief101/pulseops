import uuid
import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.db.base import Base
from app.models import (
    Integration,
    IntegrationStatus,
    Membership,
    MembershipRole,
    Organization,
    User,
)


def test_all_models_registered_in_metadata():
    """Verify all four models are registered in Base.metadata."""
    table_names = set(Base.metadata.tables.keys())
    expected = {"organizations", "users", "memberships", "integrations"}
    assert expected.issubset(table_names)


def test_organization_creation_and_defaults(db_session):
    """Verify Organization model creation and default values."""
    org = Organization(name="Acme Corp")
    db_session.add(org)
    db_session.flush()

    assert org.id is not None
    assert isinstance(org.id, uuid.UUID)
    assert org.name == "Acme Corp"
    assert org.created_at is not None


def test_user_creation_and_email_normalization(db_session):
    """Verify User model creation and automatic lowercase email normalization."""
    user = User(
        email="User.One@EXAMPLE.COM",
        password_hash="hashed_pw_test",
    )
    db_session.add(user)
    db_session.flush()

    assert user.id is not None
    assert isinstance(user.id, uuid.UUID)
    # Email must be normalized to lowercase
    assert user.email == "user.one@example.com"
    assert user.password_hash == "hashed_pw_test"
    assert user.created_at is not None


def test_user_email_uniqueness_enforced(db_session):
    """Verify duplicate emails are rejected by the database."""
    user1 = User(email="test.dup@example.com", password_hash="hash1")
    db_session.add(user1)
    db_session.flush()

    user2 = User(email="test.dup@example.com", password_hash="hash2")
    db_session.add(user2)
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_user_email_case_insensitive_uniqueness(db_session):
    """Verify casing differences in email are rejected as duplicate accounts."""
    user1 = User(email="unique.founder@saas.com", password_hash="hash1")
    db_session.add(user1)
    db_session.flush()

    # Even if bypassing the Python validator, database-level index prevents it
    user2 = User(password_hash="hash2")
    # Directly set column value to bypass validator for raw database test
    user2.__dict__["email"] = "UNIQUE.FOUNDER@saas.com"
    db_session.add(user2)
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_membership_creation_and_roles(db_session):
    """Verify Membership creation with valid roles."""
    org = Organization(name="Beta Org")
    user = User(email="beta.member@example.com", password_hash="hash")
    db_session.add_all([org, user])
    db_session.flush()

    membership = Membership(
        user_id=user.id,
        organization_id=org.id,
        role=MembershipRole.OWNER.value,
    )
    db_session.add(membership)
    db_session.flush()

    assert membership.id is not None
    assert isinstance(membership.id, uuid.UUID)
    assert membership.role == "owner"
    assert membership.created_at is not None


def test_membership_invalid_role_rejected_by_database(db_session):
    """Verify database-level check constraint rejects invalid membership roles."""
    org = Organization(name="Role Org")
    user = User(email="role.user@example.com", password_hash="hash")
    db_session.add_all([org, user])
    db_session.flush()

    invalid_membership = Membership(
        user_id=user.id,
        organization_id=org.id,
        role="superadmin",  # Invalid role not in ('owner', 'member', 'viewer')
    )
    db_session.add(invalid_membership)
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_membership_duplicate_user_org_rejected(db_session):
    """Verify unique constraint on (user_id, organization_id) prevents duplicate memberships."""
    org = Organization(name="Single Membership Org")
    user = User(email="single.member@example.com", password_hash="hash")
    db_session.add_all([org, user])
    db_session.flush()

    mem1 = Membership(
        user_id=user.id,
        organization_id=org.id,
        role=MembershipRole.MEMBER.value,
    )
    db_session.add(mem1)
    db_session.flush()

    mem2 = Membership(
        user_id=user.id,
        organization_id=org.id,
        role=MembershipRole.VIEWER.value,
    )
    db_session.add(mem2)
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_user_can_belong_to_multiple_organizations(db_session):
    """Verify a user can belong to multiple distinct organizations."""
    org1 = Organization(name="Org One")
    org2 = Organization(name="Org Two")
    user = User(email="multi.org.user@example.com", password_hash="hash")
    db_session.add_all([org1, org2, user])
    db_session.flush()

    mem1 = Membership(user_id=user.id, organization_id=org1.id, role=MembershipRole.OWNER.value)
    mem2 = Membership(user_id=user.id, organization_id=org2.id, role=MembershipRole.MEMBER.value)
    db_session.add_all([mem1, mem2])
    db_session.flush()

    assert mem1.id != mem2.id


def test_integration_creation_and_defaults(db_session):
    """Verify Integration creation with valid provider and encrypted credentials."""
    org = Organization(name="Integration Org")
    db_session.add(org)
    db_session.flush()

    integration = Integration(
        organization_id=org.id,
        provider="github",
        status=IntegrationStatus.ACTIVE.value,
        credentials_encrypted="encrypted_ciphertext_blob_placeholder",
    )
    db_session.add(integration)
    db_session.flush()

    assert integration.id is not None
    assert isinstance(integration.id, uuid.UUID)
    assert integration.provider == "github"
    assert integration.status == "active"
    assert integration.last_synced_at is None
    assert integration.created_at is not None


def test_integration_invalid_status_rejected_by_database(db_session):
    """Verify database-level check constraint rejects invalid integration statuses."""
    org = Organization(name="Status Org")
    db_session.add(org)
    db_session.flush()

    invalid_integration = Integration(
        organization_id=org.id,
        provider="razorpay",
        status="bogus_status",
        credentials_encrypted="ciphertext",
    )
    db_session.add(invalid_integration)
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_cascade_delete_organization_deletes_memberships_and_integrations(db_session):
    """Verify deleting an Organization cascades to delete its memberships and integrations."""
    org = Organization(name="Cascade Org")
    user = User(email="cascade.user@example.com", password_hash="hash")
    db_session.add_all([org, user])
    db_session.flush()

    mem = Membership(user_id=user.id, organization_id=org.id, role=MembershipRole.OWNER.value)
    integ = Integration(
        organization_id=org.id,
        provider="github",
        status=IntegrationStatus.ACTIVE.value,
        credentials_encrypted="encrypted_data",
    )
    db_session.add_all([mem, integ])
    db_session.flush()

    org_id = org.id
    mem_id = mem.id
    integ_id = integ.id

    # Delete organization
    db_session.delete(org)
    db_session.flush()
    # Expire identity map so session queries the database to observe DB-level ON DELETE CASCADE
    db_session.expire_all()

    # Memberships and Integrations must be deleted in the database
    assert db_session.get(Membership, mem_id) is None
    assert db_session.get(Integration, integ_id) is None
    # User remains intact
    assert db_session.get(User, user.id) is not None


def test_cascade_delete_user_deletes_memberships(db_session):
    """Verify deleting a User cascades to delete their memberships."""
    org = Organization(name="Cascade User Org")
    user = User(email="cascade.user2@example.com", password_hash="hash")
    db_session.add_all([org, user])
    db_session.flush()

    mem = Membership(user_id=user.id, organization_id=org.id, role=MembershipRole.MEMBER.value)
    db_session.add(mem)
    db_session.flush()

    mem_id = mem.id

    db_session.delete(user)
    db_session.flush()
    # Expire identity map so session queries the database to observe DB-level ON DELETE CASCADE
    db_session.expire_all()

    assert db_session.get(Membership, mem_id) is None
    assert db_session.get(Organization, org.id) is not None
