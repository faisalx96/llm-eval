"""Regression checks for the project prompt defaults."""

from qym_platform.services.analysis_aggregation import AGGREGATION_SYSTEM_PROMPT
from qym_platform.services.analysis_prompts import (
    DEFAULT_ANALYSIS_PROMPTS,
    PROMPT_MAX_CHARS,
)
from qym_platform.services.llm_analyzer import (
    DEFAULT_SYSTEM_PROMPT,
    MAX_ANALYSIS_PROMPT_CHARS,
    RULE_WRITER_SYSTEM_PROMPT,
)


def test_settings_defaults_track_runtime_prompt_constants() -> None:
    """The settings payload must use the prompts that analysis actually ships."""
    assert DEFAULT_ANALYSIS_PROMPTS == {
        "llm_analyzer": DEFAULT_SYSTEM_PROMPT,
        "aggregator": AGGREGATION_SYSTEM_PROMPT,
        "rules_writer": RULE_WRITER_SYSTEM_PROMPT,
    }


def test_editable_prompt_limit_matches_analyzer_budget() -> None:
    """Saved analysis prompts must accept the full root-cause prompt budget."""
    assert PROMPT_MAX_CHARS == MAX_ANALYSIS_PROMPT_CHARS == 640_000
