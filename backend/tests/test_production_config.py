"""
Tests for production configuration guards, URL normalization, CORS parsing,
and OpenAPI docs exposure defaults.
"""

from __future__ import annotations

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from app.config import Settings, normalize_database_url
from app.main import app


class TestDatabaseUrlNormalization:
    """Verify PostgreSQL URLs are normalized for Psycopg 3 compatibility."""

    def test_postgres_scheme_normalized_to_psycopg(self):
        url = "postgres://user:pass@ep-cool.neon.tech/neondb?sslmode=require"
        assert (
            normalize_database_url(url)
            == "postgresql+psycopg://user:pass@ep-cool.neon.tech/neondb?sslmode=require"
        )

    def test_postgresql_scheme_normalized_to_psycopg(self):
        url = "postgresql://user:pass@ep-cool.neon.tech/neondb?sslmode=require"
        assert (
            normalize_database_url(url)
            == "postgresql+psycopg://user:pass@ep-cool.neon.tech/neondb?sslmode=require"
        )

    def test_psycopg_scheme_preserved(self):
        url = "postgresql+psycopg://user:pass@ep-cool.neon.tech/neondb?sslmode=require"
        assert normalize_database_url(url) == url


class TestProductionSettingsValidation:
    """Verify fail-closed production validation and helper properties."""

    def _base_kwargs(self) -> dict:
        return {
            "database_url": "postgresql+psycopg://u:p@db:5432/app",
            "redis_url": "rediss://default:p@upstash.io:6379",
            "environment": "production",
            "jwt_secret_key": "a" * 64,
            "integration_encryption_key": Fernet.generate_key().decode("utf-8"),
            "cors_origins": "https://pulseops.vercel.app",
        }

    def test_valid_production_settings_pass(self):
        cfg = Settings(**self._base_kwargs())
        cfg.validate_production_settings()
        assert cfg.is_production is True
        assert cfg.docs_enabled is False
        assert cfg.cors_origins_list == ["https://pulseops.vercel.app"]

    def test_docs_enabled_defaults(self):
        dev = Settings(
            database_url="postgresql+psycopg://u:p@db:5432/app",
            redis_url="redis://redis:6379/0",
            environment="development",
        )
        assert dev.is_production is False
        assert dev.docs_enabled is True

        prod_override = Settings(**{**self._base_kwargs(), "enable_docs": True})
        assert prod_override.docs_enabled is True

    def test_short_or_missing_jwt_secret_fails_in_production(self):
        cfg_missing = Settings(**{**self._base_kwargs(), "jwt_secret_key": None})
        with pytest.raises(RuntimeError, match="JWT_SECRET_KEY"):
            cfg_missing.validate_production_settings()

        cfg_short = Settings(**{**self._base_kwargs(), "jwt_secret_key": "short"})
        with pytest.raises(RuntimeError, match="32 characters"):
            cfg_short.validate_production_settings()

    def test_missing_or_invalid_encryption_key_fails_in_production(self):
        cfg_missing = Settings(
            **{**self._base_kwargs(), "integration_encryption_key": None}
        )
        with pytest.raises(RuntimeError, match="INTEGRATION_ENCRYPTION_KEY"):
            cfg_missing.validate_production_settings()

        cfg_bad = Settings(
            **{**self._base_kwargs(), "integration_encryption_key": "invalid-key"}
        )
        with pytest.raises(RuntimeError, match="valid base64 Fernet"):
            cfg_bad.validate_production_settings()

    def test_identical_jwt_and_encryption_keys_rejected(self):
        fernet_key = Fernet.generate_key().decode("utf-8")
        cfg = Settings(
            **{
                **self._base_kwargs(),
                "jwt_secret_key": fernet_key,
                "integration_encryption_key": fernet_key,
            }
        )
        with pytest.raises(RuntimeError, match="distinct"):
            cfg.validate_production_settings()

    def test_wildcard_cors_rejected_in_production(self):
        cfg = Settings(**{**self._base_kwargs(), "cors_origins": "*"})
        with pytest.raises(RuntimeError, match="wildcard"):
            cfg.validate_production_settings()

    def test_cors_origins_parsing_strips_slashes_and_whitespace(self):
        cfg = Settings(
            **{
                **self._base_kwargs(),
                "cors_origins": " https://a.vercel.app/ , https://b.example.com ",
            }
        )
        assert cfg.cors_origins_list == [
            "https://a.vercel.app",
            "https://b.example.com",
        ]


class TestCorsMiddlewareBehavior:
    """Verify CORS does not open arbitrary origins by default."""

    def test_disallowed_origin_receives_no_allow_origin_header(self):
        with TestClient(app) as client:
            resp = client.get(
                "/health", headers={"Origin": "https://evil.example.com"}
            )
            assert resp.status_code == 200
            assert "access-control-allow-origin" not in resp.headers
