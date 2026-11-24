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
    """Verify test transaction rollback ensures no persistent rows leak into test DB."""
    with test_engine.connect() as conn:
        count = conn.execute(select(func.count(Organization.id))).scalar()
        # All tests execute within rolled-back transactions
        assert count == 0
