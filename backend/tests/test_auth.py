"""
S06 authentication tests.

All tests run against the dedicated test database via dependency override.
Transactional isolation uses an outer transaction with savepoints (join_transaction_mode="create_savepoint")
so that route handler commits are rolled back after each test and cannot persist.
JWT_SECRET_KEY is provided as a fixed test value via monkeypatching.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.auth import (
    JWT_ALGORITHM,
    create_access_token,
    decode_access_token,
    get_password_hash,
    verify_password,
)
from app.db.session import get_db
from app.main import app

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

TEST_JWT_SECRET = "test-jwt-secret-key-for-s06-tests-only"


@pytest.fixture(autouse=True)
def patch_jwt_secret(monkeypatch):
    """Inject a stable test JWT secret for every test in this module."""
    from app.config import settings

    monkeypatch.setattr(settings, "jwt_secret_key", TEST_JWT_SECRET)


@pytest.fixture()
def auth_client(test_engine):
    """
    TestClient with strict transactional isolation against TEST_DATABASE_URL.

    Each test runs inside an outer transaction on a dedicated connection.
    Route handlers use savepoints (join_transaction_mode='create_savepoint'),
    so handler commits are rolled back at the end of each test.
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
    try:
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c
    finally:
        app.dependency_overrides.clear()
        if transaction.is_active:
            transaction.rollback()
        connection.close()


@pytest.fixture()
def registered_user(auth_client):
    """Register a user and return (response_json, password)."""
    password = "ValidPassword1!"
    resp = auth_client.post(
        "/auth/register",
        json={
            "email": "auth_fixture_user@example.com",
            "password": password,
            "organization_name": "Auth Fixture Org",
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json(), password


# ---------------------------------------------------------------------------
# Registration tests (10)
# ---------------------------------------------------------------------------


class TestRegistration:
    def test_register_success_returns_201(self, auth_client):
        resp = auth_client.post(
            "/auth/register",
            json={
                "email": "auth_test_alice@example.com",
                "password": "StrongPass1!",
                "organization_name": "Auth Alice Org",
            },
        )
        assert resp.status_code == 201

    def test_register_response_shape(self, auth_client):
        resp = auth_client.post(
            "/auth/register",
            json={
                "email": "auth_test_shape@example.com",
                "password": "StrongPass1!",
                "organization_name": "Auth Shape Org",
            },
        )
        data = resp.json()
        assert "user_id" in data
        assert "email" in data
        assert "created_at" in data
        assert "organization_id" in data
        assert "organization_name" in data
        assert "role" in data

    def test_register_role_is_owner(self, auth_client):
        resp = auth_client.post(
            "/auth/register",
            json={
                "email": "auth_test_owner@example.com",
                "password": "StrongPass1!",
                "organization_name": "Auth Owner Org",
            },
        )
        assert resp.json()["role"] == "owner"

    def test_register_email_normalized_to_lowercase(self, auth_client):
        resp = auth_client.post(
            "/auth/register",
            json={
                "email": "AUTH_UPPER@Example.COM",
                "password": "StrongPass1!",
                "organization_name": "Auth Upper Org",
            },
        )
        assert resp.status_code == 201
        assert resp.json()["email"] == "auth_upper@example.com"

    def test_register_duplicate_email_returns_409(self, auth_client):
        payload = {
            "email": "auth_test_dup@example.com",
            "password": "StrongPass1!",
            "organization_name": "Auth Dup Org",
        }
        resp1 = auth_client.post("/auth/register", json=payload)
        assert resp1.status_code == 201
        resp2 = auth_client.post("/auth/register", json=payload)
        assert resp2.status_code == 409

    def test_register_password_too_short_returns_422(self, auth_client):
        resp = auth_client.post(
            "/auth/register",
            json={
                "email": "auth_short@example.com",
                "password": "abc",
                "organization_name": "Auth Short Pass Org",
            },
        )
        assert resp.status_code == 422

    def test_register_missing_email_returns_422(self, auth_client):
        resp = auth_client.post(
            "/auth/register",
            json={"password": "StrongPass1!", "organization_name": "Auth No Email Org"},
        )
        assert resp.status_code == 422

    def test_register_invalid_email_returns_422(self, auth_client):
        resp = auth_client.post(
            "/auth/register",
            json={
                "email": "not-an-email",
                "password": "StrongPass1!",
                "organization_name": "Auth Bad Email Org",
            },
        )
        assert resp.status_code == 422

    def test_register_empty_org_name_returns_422(self, auth_client):
        resp = auth_client.post(
            "/auth/register",
            json={
                "email": "auth_emptyorg@example.com",
                "password": "StrongPass1!",
                "organization_name": "   ",
            },
        )
        assert resp.status_code == 422

    def test_register_password_not_in_response(self, auth_client):
        resp = auth_client.post(
            "/auth/register",
            json={
                "email": "auth_nopw@example.com",
                "password": "StrongPass1!",
                "organization_name": "Auth No PW Org",
            },
        )
        body = resp.text
        assert "StrongPass1!" not in body
        assert "password_hash" not in body


# ---------------------------------------------------------------------------
# Login tests (8)
# ---------------------------------------------------------------------------


class TestLogin:
    def test_login_success_returns_200(self, auth_client, registered_user):
        data, password = registered_user
        resp = auth_client.post(
            "/auth/login",
            json={"email": data["email"], "password": password},
        )
        assert resp.status_code == 200

    def test_login_response_contains_access_token(self, auth_client, registered_user):
        data, password = registered_user
        resp = auth_client.post(
            "/auth/login",
            json={"email": data["email"], "password": password},
        )
        body = resp.json()
        assert "access_token" in body
        assert body["token_type"] == "bearer"
        assert body["expires_in"] == 3600

    def test_login_wrong_password_returns_401(self, auth_client, registered_user):
        data, _ = registered_user
        resp = auth_client.post(
            "/auth/login",
            json={"email": data["email"], "password": "WrongPassword!"},
        )
        assert resp.status_code == 401

    def test_login_nonexistent_email_returns_401(self, auth_client):
        resp = auth_client.post(
            "/auth/login",
            json={"email": "auth_ghost@example.com", "password": "SomePass1!"},
        )
        assert resp.status_code == 401

    def test_login_case_insensitive_email(self, auth_client, registered_user):
        data, password = registered_user
        # Login with uppercase version of registered lowercase email
        resp = auth_client.post(
            "/auth/login",
            json={"email": data["email"].upper(), "password": password},
        )
        assert resp.status_code == 200

    def test_login_missing_password_returns_422(self, auth_client, registered_user):
        data, _ = registered_user
        resp = auth_client.post(
            "/auth/login",
            json={"email": data["email"]},
        )
        assert resp.status_code == 422

    def test_login_jwt_contains_correct_sub(self, auth_client, registered_user):
        import jwt as pyjwt

        data, password = registered_user
        resp = auth_client.post(
            "/auth/login",
            json={"email": data["email"], "password": password},
        )
        token = resp.json()["access_token"]
        payload = pyjwt.decode(token, TEST_JWT_SECRET, algorithms=[JWT_ALGORITHM])
        assert payload["sub"] == str(data["user_id"])

    def test_login_does_not_return_password_hash(self, auth_client, registered_user):
        data, password = registered_user
        resp = auth_client.post(
            "/auth/login",
            json={"email": data["email"], "password": password},
        )
        assert "password_hash" not in resp.text
        assert password not in resp.text


# ---------------------------------------------------------------------------
# GET /me tests (8)
# ---------------------------------------------------------------------------


class TestMe:
    def _get_token(self, auth_client, registered_user) -> str:
        data, password = registered_user
        resp = auth_client.post(
            "/auth/login",
            json={"email": data["email"], "password": password},
        )
        return resp.json()["access_token"]

    def test_me_authenticated_returns_200(self, auth_client, registered_user):
        token = self._get_token(auth_client, registered_user)
        resp = auth_client.get("/me", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200

    def test_me_response_shape(self, auth_client, registered_user):
        token = self._get_token(auth_client, registered_user)
        resp = auth_client.get("/me", headers={"Authorization": f"Bearer {token}"})
        body = resp.json()
        assert "id" in body
        assert "email" in body
        assert "created_at" in body

    def test_me_no_password_hash_in_response(self, auth_client, registered_user):
        token = self._get_token(auth_client, registered_user)
        resp = auth_client.get("/me", headers={"Authorization": f"Bearer {token}"})
        assert "password_hash" not in resp.text

    def test_me_no_bearer_returns_401(self, auth_client):
        resp = auth_client.get("/me")
        assert resp.status_code == 401

    def test_me_invalid_token_returns_401(self, auth_client):
        resp = auth_client.get(
            "/me", headers={"Authorization": "Bearer this.is.invalid"}
        )
        assert resp.status_code == 401

    def test_me_expired_token_returns_401(self, auth_client, registered_user):
        import jwt as pyjwt
        from datetime import datetime, timedelta, timezone

        data, _ = registered_user
        # Forge an already-expired token.
        past = datetime.now(tz=timezone.utc) - timedelta(hours=2)
        expired_token = pyjwt.encode(
            {"sub": str(data["user_id"]), "iat": past, "exp": past + timedelta(seconds=1)},
            TEST_JWT_SECRET,
            algorithm=JWT_ALGORITHM,
        )
        resp = auth_client.get(
            "/me", headers={"Authorization": f"Bearer {expired_token}"}
        )
        assert resp.status_code == 401

    def test_me_email_matches_registered_email(self, auth_client, registered_user):
        data, password = registered_user
        token = self._get_token(auth_client, registered_user)
        resp = auth_client.get("/me", headers={"Authorization": f"Bearer {token}"})
        assert resp.json()["email"] == data["email"]

    def test_me_user_id_matches_registered_id(self, auth_client, registered_user):
        data, _ = registered_user
        token = self._get_token(auth_client, registered_user)
        resp = auth_client.get("/me", headers={"Authorization": f"Bearer {token}"})
        assert resp.json()["id"] == str(data["user_id"])


# ---------------------------------------------------------------------------
# Config / security unit tests (4)
# ---------------------------------------------------------------------------


class TestAuthSecurity:
    def test_password_hash_is_not_plaintext(self):
        hashed = get_password_hash("MySecret123!")
        assert "MySecret123!" not in hashed

    def test_verify_password_correct(self):
        hashed = get_password_hash("CorrectHorse!")
        assert verify_password("CorrectHorse!", hashed) is True

    def test_verify_password_wrong(self):
        hashed = get_password_hash("CorrectHorse!")
        assert verify_password("WrongHorse!", hashed) is False

    def test_missing_jwt_secret_raises(self, monkeypatch):
        from app.config import settings
        from app.core.auth import get_jwt_secret

        monkeypatch.setattr(settings, "jwt_secret_key", None)
        with pytest.raises(RuntimeError, match="JWT_SECRET_KEY"):
            get_jwt_secret()
