"""Configuration for LLM-as-judge metrics."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class JudgeConfig:
    """Connection and model settings for LLM judge calls.

    All values must be provided via environment variables or programmatically.
    There are no defaults — you must configure your own LLM provider.

    Environment variables:
        * ``QYM_JUDGE_MODEL``    — Model name (e.g. "gpt-4o-mini", "llama-3.1-8b")
        * ``QYM_JUDGE_API_KEY``  — API key (falls back to ``OPENAI_API_KEY``)
        * ``QYM_JUDGE_BASE_URL`` — Base URL (falls back to ``OPENAI_BASE_URL``)
    """

    model: str = ""
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    temperature: float = 0.0
    max_tokens: int = 1024
    timeout: float = 60.0

    def __post_init__(self) -> None:
        if not self.model:
            self.model = os.environ.get("QYM_JUDGE_MODEL", "")
        if self.base_url is None:
            self.base_url = os.environ.get(
                "QYM_JUDGE_BASE_URL", os.environ.get("OPENAI_BASE_URL")
            )
        if self.api_key is None:
            self.api_key = os.environ.get(
                "QYM_JUDGE_API_KEY", os.environ.get("OPENAI_API_KEY")
            )

    def validate(self) -> None:
        """Raise a clear error if required configuration is missing."""
        missing = []
        if not self.model:
            missing.append("QYM_JUDGE_MODEL")
        if not self.api_key:
            missing.append("QYM_JUDGE_API_KEY (or OPENAI_API_KEY)")
        if missing:
            raise RuntimeError(
                f"LLM judge metrics require configuration. "
                f"Missing: {', '.join(missing)}\n\n"
                f"Set these environment variables:\n"
                f"  export QYM_JUDGE_MODEL=<your-model>       # e.g. gpt-4o-mini, llama-3.1-8b\n"
                f"  export QYM_JUDGE_API_KEY=<your-api-key>   # Your LLM provider API key\n"
                f"  export QYM_JUDGE_BASE_URL=<your-url>      # Optional: for vLLM, Ollama, etc.\n\n"
                f"Or configure programmatically:\n"
                f"  from qym.metrics import JudgeConfig, set_default_judge_config\n"
                f"  set_default_judge_config(JudgeConfig(model='...', api_key='...'))"
            )

    def __repr__(self) -> str:
        masked_key = "***" if self.api_key else "None"
        return (
            f"JudgeConfig(model={self.model!r}, base_url={self.base_url!r}, "
            f"api_key={masked_key}, temperature={self.temperature}, "
            f"max_tokens={self.max_tokens}, timeout={self.timeout})"
        )


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
