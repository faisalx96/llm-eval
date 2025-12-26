from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class PlatformSettings(BaseSettings):
    """Runtime configuration for the deployed llm-eval platform."""

    model_config = SettingsConfigDict(env_prefix="LLM_EVAL_", extra="ignore")

    # Core
    environment: str = Field(default="dev")
    base_url: str = Field(default="http://localhost:8000")

    # Auth
    auth_mode: str = Field(default="none")  # none|proxy_headers|oidc|saml (SSO later)
    admin_bootstrap_token: str = Field(default="")

    # Database
    database_url: str = Field(default="sqlite:///./llm_eval_platform.db")

    # Storage (raw artifacts)
    artifact_store_path: str = Field(default="./artifacts")


