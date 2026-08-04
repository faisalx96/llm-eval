"""Merge analyzer lifecycle and run metric analysis migration branches.

Revision ID: 0033_merge_migration_heads
Revises: 0032_rule_release_lifecycle, 0026_run_metric_analyses
Create Date: 2026-07-25
"""

from __future__ import annotations


revision = "0033_merge_migration_heads"
down_revision = (
    "0032_rule_release_lifecycle",
    "0026_run_metric_analyses",
)
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Join the two existing migration branches without changing schema."""


def downgrade() -> None:
    """Split back to the two parent revisions without changing schema."""
