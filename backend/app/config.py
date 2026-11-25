from __future__ import annotations

from cryptography.fernet import Fernet
from pydantic_settings import BaseSettings, SettingsConfigDict


def normalize_database_url(url: str) -> str:
    """
    Ensure PostgreSQL URLs use the Psycopg 3 SQLAlchemy dialect.

    Managed providers such as Neon and Render often provide URLs starting with
    ``postgresql://`` or ``postgres://``, which default to ``psycopg2`` in
    SQLAlchemy unless ``+psycopg`` is specified.
    """
    clean = url.strip()
    if clean.startswith("postgres://"):
        return "postgresql+psycopg://" + clean[len("postgres://") :]
    if clean.startswith("postgresql://"):
        return "postgresql+psycopg://" + clean[len("postgresql://") :]
    return clean


class Settings(BaseSettings):
    database_url: str
    redis_url: str
    integration_encryption_key: str | None = None
    test_database_url: str | None = None
    jwt_secret_key: str | None = None

    environment: str = "development"
    log_level: str = "INFO"
    cors_origins: str = ""
    enable_docs: bool | None = None

    # External Integration Settings (Optional; fallback/mock modes apply when unset)
    razorpay_mock_fallback: bool = True
    github_client_id: str | None = None
    github_client_secret: str | None = None
    github_oauth_redirect_uri: str | None = None
    deepseek_api_key: str | None = None
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"
    deepseek_max_tokens: int = 800
    deepseek_max_tool_rounds: int = 3
    copilot_cache_ttl_seconds: int = 120

    # Rate Limiting, Webhooks & Demo Controls
    rate_limit_enabled: bool = True
    rate_limit_window_seconds: int = 60
    rate_limit_auth_max_requests: int = 20
    rate_limit_copilot_max_requests: int = 20
    rate_limit_org_write_max_requests: int = 60
    webhook_replay_tolerance_seconds: int = 300
    webhook_future_skew_seconds: int = 60
    demo_account_email: str = "demo@pulseops.example.com"
    demo_copilot_daily_limit: int = 5

    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def is_production(self) -> bool:
        """Return True when running in the production environment."""
        return self.environment.strip().lower() == "production"

    @property
    def docs_enabled(self) -> bool:
        """
        Control OpenAPI/Swagger UI exposure.

        Disabled by default in production unless explicitly overridden via
        ENABLE_DOCS=true.
        """
        if self.enable_docs is not None:
            return self.enable_docs
        return not self.is_production

    @property
    def cors_origins_list(self) -> list[str]:
        """Parse comma-separated CORS_ORIGINS into a clean list of origins."""
        if not self.cors_origins or not self.cors_origins.strip():
            return []
        return [
            origin.strip().rstrip("/")
            for origin in self.cors_origins.split(",")
            if origin.strip()
        ]

    @property
    def sqlalchemy_database_url(self) -> str:
        """Return database_url normalized for SQLAlchemy + Psycopg 3."""
        return normalize_database_url(self.database_url)

    def validate_production_settings(self) -> None:
        """
        Fail closed if critical production security requirements are unmet.

        Called during application startup when ENVIRONMENT=production.
        """
        jwt_key = (self.jwt_secret_key or "").strip()
        if len(jwt_key) < 32:
            raise RuntimeError(
                "JWT_SECRET_KEY must be set to at least 32 characters in production."
            )

        enc_key = (self.integration_encryption_key or "").strip()
        if not enc_key:
            raise RuntimeError(
                "INTEGRATION_ENCRYPTION_KEY must be configured in production."
            )

        try:
            Fernet(enc_key.encode("utf-8"))
        except Exception as exc:
            raise RuntimeError(
                "INTEGRATION_ENCRYPTION_KEY is not a valid base64 Fernet key."
            ) from exc

        if jwt_key == enc_key:
            raise RuntimeError(
                "JWT_SECRET_KEY and INTEGRATION_ENCRYPTION_KEY must be distinct keys."
            )

        if "*" in self.cors_origins_list:
            raise RuntimeError(
                "CORS_ORIGINS cannot contain wildcard '*' in production when credentials are enabled."
            )


settings = Settings()
