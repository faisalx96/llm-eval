from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class PlatformSettings(BaseSettings):
    """Runtime configuration for the deployed qym platform."""

    model_config = SettingsConfigDict(
        env_prefix="QYM_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Core
    environment: str = Field(default="dev")
    base_url: str = Field(default="http://localhost:8000")
    root_path: str = Field(default="", description="URL prefix when served behind a reverse proxy (e.g. /qym)")

    # Auth
    auth_mode: str = Field(default="none")  # none|proxy_headers|oidc|saml (SSO later)
    admin_bootstrap_token: str = Field(default="")
    auto_provision_users: bool = Field(default=True)
    allow_legacy_empty_api_key_scopes: bool = Field(default=True)
    auth_session_secret: str = Field(default="")
    auth_local_enabled: bool = Field(default=False)
    auth_google_client_id: str = Field(default="")
    auth_google_client_secret: str = Field(default="")
    auth_github_client_id: str = Field(default="")
    auth_github_client_secret: str = Field(default="")

    # Database (required - no SQLite fallback)
    database_url: str = Field(description="PostgreSQL connection string (required)")

    # Secrets
    llm_config_encryption_key: str = Field(default="")

    # Visibility
    hidden_tasks: str = Field(default="", description="Comma-separated task names to hide from listings")

    # Storage (raw artifacts)
    artifact_store_path: str = Field(default="./artifacts")

    # Run lifecycle
    run_stale_timeout_seconds: int = Field(default=60, ge=5)

    # Product eval API
    product_eval_max_workers: int = Field(default=3, ge=1)
