"""Allow draft analyzer rule versions without activation timestamps.

Revision ID: 0034_draft_rule_activation
Revises: 0033_merge_migration_heads
Create Date: 2026-07-25
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0034_draft_rule_activation"
down_revision = "0033_merge_migration_heads"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Match the nullable activation fields used by un-published drafts."""
    op.alter_column(
        "project_analysis_rule_versions",
        "activated_at",
        existing_type=sa.DateTime(),
        nullable=True,
    )


def downgrade() -> None:
    """Backfill draft timestamps before restoring the old constraint."""
    connection = op.get_bind()
    connection.execute(
        sa.text(
            "UPDATE project_analysis_rule_versions "
            "SET activated_at = COALESCE(created_at, CURRENT_TIMESTAMP) "
            "WHERE activated_at IS NULL"
        )
    )
    op.alter_column(
        "project_analysis_rule_versions",
        "activated_at",
        existing_type=sa.DateTime(),
        nullable=False,
    )
