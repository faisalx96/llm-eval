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

    # Auth
    auth_mode: str = Field(default="none")  # none|proxy_headers|oidc|saml (SSO later)
    admin_bootstrap_token: str = Field(default="")

    # Database (required - no SQLite fallback)
    database_url: str = Field(description="PostgreSQL connection string (required)")

    # Storage (raw artifacts)
    artifact_store_path: str = Field(default="./artifacts")


