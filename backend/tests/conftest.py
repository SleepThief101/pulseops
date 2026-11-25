from collections.abc import Generator
import os
import socket
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings
from app.core.security import generate_encryption_key
from app.main import app


def get_test_database_url() -> str:
    """
    Retrieve the dedicated test database URL.
    Strictly requires TEST_DATABASE_URL and explicitly rejects:
    - Missing or empty TEST_DATABASE_URL (never falls back to DATABASE_URL)
    - TEST_DATABASE_URL matching DATABASE_URL (prevents modifying development data)
    """
    test_url = os.environ.get("TEST_DATABASE_URL")
    if not test_url or not test_url.strip():
        test_url = settings.test_database_url

    if not test_url or not test_url.strip():
        raise RuntimeError(
            "TEST_DATABASE_URL is not configured. "
            "A dedicated test database URL must be explicitly provided via the "
            "TEST_DATABASE_URL environment variable to run database tests. "
            "Never silently fall back to the development database."
        )

    clean_url = test_url.strip()

    # Guard against accidental collision with the development database
    if clean_url == settings.database_url.strip():
        raise RuntimeError(
            "TEST_DATABASE_URL matches DATABASE_URL! "
            "A separate, dedicated test database must be used to ensure test isolation "
            "and protect the development database from test side-effects."
        )

    # Dynamic host adaptation if running on host machine outside Docker network
    if "@db:" in clean_url:
        try:
            socket.gethostbyname("db")
        except (socket.gaierror, OSError):
            clean_url = clean_url.replace("@db:", "@127.0.0.1:")

    return clean_url


@pytest.fixture(scope="session")
def test_engine():
    """
    Session-scoped test database engine.
    Bound strictly to TEST_DATABASE_URL, completely isolated from
    the runtime application engine (app.db.session.engine).
    """
    url = get_test_database_url()
    engine = create_engine(url, pool_pre_ping=True)
    yield engine
    engine.dispose()


@pytest.fixture(scope="session")
def TestSessionLocal(test_engine):
    """Session factory bound strictly to the dedicated test database."""
    return sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


@pytest.fixture
def client() -> TestClient:
    """FastAPI TestClient fixture."""
    return TestClient(app)


@pytest.fixture
def db_session(test_engine) -> Generator[Session, None, None]:
    """
    Provide an isolated transactional database session against the test database.
    Every test executes inside an uncommitted transaction that is explicitly
    rolled back upon test completion (even on test failure) to guarantee isolation.
    """
    connection = test_engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, expire_on_commit=False)

    try:
        yield session
    finally:
        session.close()
        if transaction.is_active:
            transaction.rollback()
        connection.close()


@pytest.fixture(autouse=True)
def default_test_rate_limits(monkeypatch):
    """
    Keep Redis rate limiting enabled with high thresholds during unrelated unit tests
    so shared TestClient IP fixtures do not hit 429s; rate-limit tests override
    these thresholds explicitly via monkeypatch.
    """
    monkeypatch.setattr(settings, "rate_limit_auth_max_requests", 10000)
    monkeypatch.setattr(settings, "rate_limit_copilot_max_requests", 10000)
    monkeypatch.setattr(settings, "rate_limit_org_write_max_requests", 10000)


@pytest.fixture
def test_encryption_key() -> str:
    """Generate a clean URL-safe base64 Fernet key for testing."""
    return generate_encryption_key()
