"""Defaults and runtime resolution for project-scoped analysis prompts."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from qym_platform.datetime_utils import to_api_timestamp
from qym_platform.db.models import ProjectAnalysisPromptSettings
from qym_platform.services.analysis_aggregation import AGGREGATION_SYSTEM_PROMPT
from qym_platform.services.llm_analyzer import (
    DEFAULT_SYSTEM_PROMPT,
    RULE_WRITER_SYSTEM_PROMPT,
)


PROMPT_MAX_CHARS = 100_000

DEFAULT_ANALYSIS_PROMPTS: dict[str, str] = {
    "llm_analyzer": DEFAULT_SYSTEM_PROMPT,
    "aggregator": AGGREGATION_SYSTEM_PROMPT,
    "rules_writer": RULE_WRITER_SYSTEM_PROMPT,
}


def get_effective_analysis_prompts(
    db: Session, project_id: str
) -> dict[str, str]:
    """Return saved prompts, falling back to the built-in defaults per field."""
    row = db.get(ProjectAnalysisPromptSettings, project_id)
    if row is None:
        return dict(DEFAULT_ANALYSIS_PROMPTS)
    return {
        "llm_analyzer": row.llm_analyzer_system_prompt
        or DEFAULT_ANALYSIS_PROMPTS["llm_analyzer"],
        "aggregator": row.aggregator_system_prompt
        or DEFAULT_ANALYSIS_PROMPTS["aggregator"],
        "rules_writer": row.rules_writer_system_prompt
        or DEFAULT_ANALYSIS_PROMPTS["rules_writer"],
    }


def serialize_analysis_prompt_settings(
    db: Session, project_id: str
) -> dict[str, Any]:
    """Build the settings payload without exposing persistence details."""
    row = db.get(ProjectAnalysisPromptSettings, project_id)
    prompts = get_effective_analysis_prompts(db, project_id)
    return {
        "project_id": project_id,
        "prompts": prompts,
        "defaults": dict(DEFAULT_ANALYSIS_PROMPTS),
        "customized": {
            key: prompts[key] != DEFAULT_ANALYSIS_PROMPTS[key]
            for key in DEFAULT_ANALYSIS_PROMPTS
        },
        "updated_at": to_api_timestamp(row.updated_at) if row else None,
    }
