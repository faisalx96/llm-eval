"""Merge analysis prompts and repeat pass score metadata branches.

Revision ID: 0042_merge_analysis_pass_scores
Revises: 0041_analysis_prompts, 0038_pass_score_meta
Create Date: 2026-08-11
"""

from __future__ import annotations


revision = "0042_merge_analysis_pass_scores"
down_revision = (
    "0041_analysis_prompts",
    "0038_pass_score_meta",
)
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Join both migration branches without changing schema."""


def downgrade() -> None:
    """Split back to both parent revisions without changing schema."""
