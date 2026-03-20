"""Configuration for LLM-as-judge metrics."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class JudgeConfig:
    """Connection and model settings for LLM judge calls.

    Values default to environment variables when not passed programmatically:

    * ``model``:    ``QYM_JUDGE_MODEL``    -> ``"gpt-4o-mini"``
    * ``base_url``: ``QYM_JUDGE_BASE_URL`` -> ``OPENAI_BASE_URL`` -> *None*
    * ``api_key``:  ``QYM_JUDGE_API_KEY``  -> ``OPENAI_API_KEY``  -> *None*
    """

    model: str = ""
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    temperature: float = 0.0
    max_tokens: int = 1024
    timeout: float = 60.0

    def __post_init__(self) -> None:
        if not self.model:
            self.model = os.environ.get("QYM_JUDGE_MODEL", "gpt-4o-mini")
        if self.base_url is None:
            self.base_url = os.environ.get(
                "QYM_JUDGE_BASE_URL", os.environ.get("OPENAI_BASE_URL")
            )
        if self.api_key is None:
            self.api_key = os.environ.get(
                "QYM_JUDGE_API_KEY", os.environ.get("OPENAI_API_KEY")
            )


# ---------------------------------------------------------------------------
# Module-level default singleton
# ---------------------------------------------------------------------------

_default_config: Optional[JudgeConfig] = None


def get_default_judge_config() -> JudgeConfig:
    """Return the current default JudgeConfig (lazily created)."""
    global _default_config
    if _default_config is None:
        _default_config = JudgeConfig()
    return _default_config


def set_default_judge_config(config: JudgeConfig) -> None:
    """Override the global default JudgeConfig."""
    global _default_config
    _default_config = config
