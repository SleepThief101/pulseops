import pytest
from sqlalchemy import func, select

from app.config import settings
from app.models import Organization
from tests.conftest import get_test_database_url


def test_missing_test_database_url_raises_error(monkeypatch):
    """Verify missing TEST_DATABASE_URL fails safely with explicit RuntimeError."""
    monkeypatch.delenv("TEST_DATABASE_URL", raising=False)
    monkeypatch.setattr(settings, "test_database_url", None)

    with pytest.raises(RuntimeError) as exc_info:
        get_test_database_url()

    assert "TEST_DATABASE_URL is not configured" in str(exc_info.value)
    assert "Never silently fall back" in str(exc_info.value)


def test_matching_database_url_raises_error(monkeypatch):
    """Verify TEST_DATABASE_URL matching DATABASE_URL raises RuntimeError to protect dev DB."""
    monkeypatch.setenv("TEST_DATABASE_URL", settings.database_url)
    monkeypatch.setattr(settings, "test_database_url", settings.database_url)

    with pytest.raises(RuntimeError) as exc_info:
        get_test_database_url()

    assert "TEST_DATABASE_URL matches DATABASE_URL" in str(exc_info.value)


def test_test_engine_points_to_test_database(test_engine):
    """Verify test engine connects specifically to the test database and not dev DB."""
    assert "pulseops_test" in str(test_engine.url)
    assert test_engine.url.database == "pulseops_test"


def test_transaction_rollback_leaves_test_db_clean(test_engine):
    """
    Verify transaction rollback ensures uniquely identifiable rows created within
    a transaction do not persist in the test database after rollback.
    """
    import uuid
    from sqlalchemy.orm import Session

    unique_org_name = f"Temporary-Rollback-Org-{uuid.uuid4()}"

    # Create and flush the temporary organization within an explicit transaction
    connection = test_engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, expire_on_commit=False)

    try:
        temp_org = Organization(name=unique_org_name)
        session.add(temp_org)
        session.flush()

        # Confirm the row is visible within the uncommitted transaction
        found_inside = session.scalar(
            select(Organization).where(Organization.name == unique_org_name)
        )
        assert found_inside is not None
        assert found_inside.name == unique_org_name
    finally:
        session.close()
        transaction.rollback()
        connection.close()

    # In a separate connection, confirm the temporary organization does not exist
    with test_engine.connect() as verify_conn:
        found_after_rollback = verify_conn.execute(
            select(Organization).where(Organization.name == unique_org_name)
        ).scalar_one_or_none()
        assert found_after_rollback is None
