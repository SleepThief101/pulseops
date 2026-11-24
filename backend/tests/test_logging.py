"""
Tests for structured JSON logging and request ID tracking (S10).

Covers:
- Unique UUID request ID generation and X-Request-ID header response.
- Different request IDs across requests.
- Acceptance of valid UUID X-Request-ID and rejection/replacement of arbitrary client values.
- HTTP method, path, response status, duration_ms recorded in structured JSON logs.
- Authenticated user ID and organization ID inclusion when present.
- Resilient logging on unauthenticated requests.
- Security verification: credentials, tokens, and authorization headers are never logged.
- Redaction of database passwords, JWTs, and secrets via sanitize_log_message.
- Safe handling of unhandled exceptions returning HTTP 500 with X-Request-ID header.
"""

from __future__ import annotations

import io
import json
import logging
import uuid
import pytest
from fastapi.testclient import TestClient

from app.core.auth import create_access_token
from app.core.logging import (
    StructuredJsonFormatter,
    sanitize_log_message,
    logger as request_logger,
)
from app.db.session import get_db
from app.main import app
from app.models.membership import Membership, MembershipRole
from app.models.organization import Organization
from app.models.user import User
from sqlalchemy.orm import Session

TEST_JWT_SECRET = "test-jwt-secret-key-for-s10-logging-tests"


@pytest.fixture(autouse=True)
def patch_jwt_secret(monkeypatch):
    """Inject a stable test JWT secret for all tests in this module."""
    from app.config import settings

    monkeypatch.setattr(settings, "jwt_secret_key", TEST_JWT_SECRET)


@pytest.fixture()
def log_env(test_engine):
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

    setup_session = Session(
        bind=connection,
        join_transaction_mode="create_savepoint",
        expire_on_commit=False,
    )

    try:
        with TestClient(app, raise_server_exceptions=True) as client:
            yield client, setup_session
    finally:
        setup_session.close()
        app.dependency_overrides.clear()
        if transaction.is_active:
            transaction.rollback()
        connection.close()


class LogCapture:
    """Helper context manager to capture and parse single-line JSON logs."""

    def __init__(self, target_logger: logging.Logger = request_logger):
        self.target_logger = target_logger
        self.stream = io.StringIO()
        self.handler = logging.StreamHandler(self.stream)
        self.handler.setFormatter(StructuredJsonFormatter())

    def __enter__(self) -> LogCapture:
        self.target_logger.addHandler(self.handler)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.target_logger.removeHandler(self.handler)

    def get_records(self) -> list[dict]:
        """Return parsed JSON objects for each captured log line."""
        self.stream.seek(0)
        lines = [line.strip() for line in self.stream.getvalue().split("\n") if line.strip()]
        records = []
        for line in lines:
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                pass
        return records

    @property
    def raw_output(self) -> str:
        """Return the unparsed raw string output."""
        return self.stream.getvalue()


# ---------------------------------------------------------------------------
# Request ID Tests
# ---------------------------------------------------------------------------


class TestRequestId:
    """Verify request ID generation, validation, and propagation."""

    def test_request_id_generated_and_returned_in_header(self, client: TestClient):
        """Incoming requests receive an X-Request-ID header containing a valid UUID."""
        response = client.get("/health")
        assert response.status_code == 200
        assert "x-request-id" in response.headers or "X-Request-ID" in response.headers

        req_id = response.headers.get("X-Request-ID")
        assert req_id is not None
        # Verify valid UUID format
        parsed = uuid.UUID(req_id)
        assert str(parsed) == req_id

    def test_different_requests_receive_different_ids(self, client: TestClient):
        """Consecutive requests receive distinct, unique UUID request IDs."""
        res1 = client.get("/health")
        res2 = client.get("/health")

        id1 = res1.headers.get("X-Request-ID")
        id2 = res2.headers.get("X-Request-ID")

        assert id1 is not None and id2 is not None
        assert id1 != id2

    def test_valid_client_uuid_is_accepted_and_returned(self, client: TestClient):
        """If a client provides a canonical UUID X-Request-ID, it is validated and preserved."""
        client_uuid = str(uuid.uuid4())
        response = client.get("/health", headers={"X-Request-ID": client_uuid})

        assert response.status_code == 200
        assert response.headers.get("X-Request-ID") == client_uuid

    def test_arbitrary_client_request_id_is_rejected_and_replaced(self, client: TestClient):
        """Arbitrary strings and injection payloads in X-Request-ID are rejected and replaced."""
        dangerous_payloads = [
            "not-a-uuid",
            "<script>alert(1)</script>",
            "12345",
            "'; DROP TABLE users; --",
            "fake_id\nnewline_injection",
        ]

        for payload in dangerous_payloads:
            response = client.get("/health", headers={"X-Request-ID": payload})
            assert response.status_code == 200
            returned_id = response.headers.get("X-Request-ID")
            assert returned_id != payload

            # Returned ID must be a freshly generated valid UUID
            parsed = uuid.UUID(returned_id)
            assert str(parsed) == returned_id


# ---------------------------------------------------------------------------
# Structured JSON Logging Tests
# ---------------------------------------------------------------------------


class TestStructuredLogging:
    """Verify JSON structure, HTTP fields, and metric tracking."""

    def test_request_logging_emits_valid_json_with_standard_fields(self, client: TestClient):
        """Requests emit single-line JSON with timestamp, level, logger, message, request_id."""
        with LogCapture() as capture:
            response = client.get("/health")

        assert response.status_code == 200
        records = capture.get_records()
        assert len(records) >= 1

        rec = records[-1]
        assert "timestamp" in rec
        assert rec["timestamp"].endswith("Z")
        assert rec["level"] == "INFO"
        assert rec["log_level"] == "INFO"
        assert rec["logger"] == "app.request"
        assert rec["request_id"] == response.headers.get("X-Request-ID")
        assert rec["http_method"] == "GET"
        assert rec["path"] == "/health"
        assert rec["status_code"] == 200
        assert isinstance(rec["duration_ms"], (int, float))
        assert rec["duration_ms"] >= 0

    def test_unauthenticated_request_logging_succeeds(self, client: TestClient):
        """Requests without authentication do not break logging and record null user_id."""
        with LogCapture() as capture:
            response = client.get("/me")

        assert response.status_code == 401
        records = capture.get_records()
        assert len(records) >= 1

        rec = records[-1]
        assert rec["status_code"] == 401
        assert rec["path"] == "/me"
        assert rec["http_method"] == "GET"
        assert rec.get("user_id") is None
        assert rec["request_id"] == response.headers.get("X-Request-ID")

    def test_authenticated_user_id_included_in_request_log(self, log_env):
        """Authenticated requests include the user UUID in the structured log entry."""
        client, session = log_env
        user = User(
            email=f"logging_user_{uuid.uuid4().hex[:8]}@example.com",
            password_hash="dummy_hash",
        )
        session.add(user)
        session.flush()

        token = create_access_token(user.id)

        with LogCapture() as capture:
            response = client.get("/me", headers={"Authorization": f"Bearer {token}"})

        assert response.status_code == 200
        records = capture.get_records()
        assert len(records) >= 1

        rec = records[-1]
        assert rec["status_code"] == 200
        assert rec["path"] == "/me"
        assert rec["user_id"] == str(user.id)
        assert rec["request_id"] == response.headers.get("X-Request-ID")

    def test_organization_id_included_in_member_endpoints_log(self, log_env):
        """Member endpoints record the organization ID in the structured log entry."""
        client, session = log_env
        org = Organization(name=f"Logging Org {uuid.uuid4().hex[:8]}")
        user = User(
            email=f"org_logger_{uuid.uuid4().hex[:8]}@example.com",
            password_hash="dummy_hash",
        )
        session.add_all([org, user])
        session.flush()

        membership = Membership(
            user_id=user.id,
            organization_id=org.id,
            role=MembershipRole.OWNER.value,
        )
        session.add(membership)
        session.flush()

        token = create_access_token(user.id)

        with LogCapture() as capture:
            response = client.get(
                f"/orgs/{org.id}/members",
                headers={"Authorization": f"Bearer {token}"},
            )

        assert response.status_code == 200
        records = capture.get_records()
        assert len(records) >= 1

        rec = records[-1]
        assert rec["status_code"] == 200
        assert rec["user_id"] == str(user.id)
        assert rec["org_id"] == str(org.id)
        assert rec["request_id"] == response.headers.get("X-Request-ID")


# ---------------------------------------------------------------------------
# Security & Secret Safety Tests
# ---------------------------------------------------------------------------


class TestLoggingSecurity:
    """Verify passwords, authorization tokens, and credentials are never logged."""

    def test_sensitive_headers_and_passwords_never_appear_in_logs(self, log_env):
        """Passwords and Authorization tokens must never leak into raw log output."""
        client, _ = log_env
        sensitive_password = "SuperSecretPlainTextPassword123!"
        dummy_jwt = (
            "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
            "eyJzdWIiOiIxMjM0NTY3OC0xMjM0LTUyMzQtYTIzNC0xMjM0NTY3ODkwMTIifQ."
            "somesignaturevaluehere1234567890abcdef"
        )

        with LogCapture() as capture:
            # 1. Registration with plaintext password
            client.post(
                "/auth/register",
                json={
                    "email": f"security_test_{uuid.uuid4().hex[:8]}@example.com",
                    "password": sensitive_password,
                    "organization_name": "Security Org",
                },
            )

            # 2. Authenticated request with Bearer token
            client.get(
                "/me",
                headers={"Authorization": f"Bearer {dummy_jwt}"},
            )

        raw = capture.raw_output
        assert sensitive_password not in raw
        assert dummy_jwt not in raw
        assert "Authorization: Bearer" not in raw

    def test_sanitize_log_message_redacts_database_passwords(self):
        """sanitize_log_message replaces database credentials with asterisks."""
        raw_msg = (
            "Connection failed to postgresql+psycopg://pulseops:super_secret_db_pass@db:5432/pulseops"
        )
        sanitized = sanitize_log_message(raw_msg)

        assert "super_secret_db_pass" not in sanitized
        assert "postgresql+psycopg://pulseops:***@db:5432/pulseops" in sanitized

    def test_sanitize_log_message_redacts_bearer_and_jwt_tokens(self):
        """sanitize_log_message redacts Bearer tokens and raw JWTs."""
        token = (
            "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
            "eyJzdWIiOiJkOGVjZjA3MC04NjBkLTRmZjMtODNmMi1mYmM0ZGM2YzI3NGUifQ."
            "PjJ0_xyz_123"
        )
        msg_with_bearer = f"Failed auth with token: Bearer {token}"
        msg_with_raw_jwt = f"Decoded payload from {token}"

        assert token not in sanitize_log_message(msg_with_bearer)
        assert "Bearer [REDACTED]" in sanitize_log_message(msg_with_bearer)
        assert token not in sanitize_log_message(msg_with_raw_jwt)
        assert "[REDACTED_JWT]" in sanitize_log_message(msg_with_raw_jwt)

    def test_sanitize_log_message_redacts_json_secret_fields(self):
        """sanitize_log_message redacts password and secret fields in JSON fragments."""
        msg = '{"password": "secret_user_password", "email": "alice@example.com"}'
        sanitized = sanitize_log_message(msg)

        assert "secret_user_password" not in sanitized
        assert '"password": "[REDACTED]"' in sanitized
        assert "alice@example.com" in sanitized


# ---------------------------------------------------------------------------
# Resilience & Exception Handling Tests
# ---------------------------------------------------------------------------


class TestLoggingResilience:
    """Verify unhandled exceptions are caught gracefully with X-Request-ID header."""

    def test_unhandled_exception_returns_500_with_request_id_and_logs_error(
        self, client: TestClient
    ):
        """Unhandled exceptions return a safe HTTP 500 JSON response with X-Request-ID."""
        # Dynamically mount a crash endpoint to verify unhandled error safety
        @app.get("/_test_unhandled_crash_route")
        def crash_route():
            raise RuntimeError("Database connection string error: postgresql://admin:secret123@host/db")

        with LogCapture() as capture:
            response = client.get("/_test_unhandled_crash_route")

        assert response.status_code == 500
        assert response.json() == {"detail": "Internal server error"}
        req_id = response.headers.get("X-Request-ID")
        assert req_id is not None
        # Verify it's a valid UUID
        assert str(uuid.UUID(req_id)) == req_id

        # Verify error log
        records = capture.get_records()
        assert len(records) >= 1
        rec = records[-1]
        assert rec["status_code"] == 500
        assert rec["level"] == "ERROR"
        assert rec["request_id"] == req_id
        # Credentials in the exception message must be redacted
        assert "secret123" not in capture.raw_output
        assert "postgresql://admin:***@host/db" in capture.raw_output
