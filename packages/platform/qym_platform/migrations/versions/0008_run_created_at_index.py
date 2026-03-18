"""Add index on runs.created_at for faster ORDER BY.

Revision ID: 0008_run_created_at_index
Revises: 0007_root_cause_revisions
Create Date: 2026-03-18
"""

from __future__ import annotations

from alembic import op

revision = "0008_run_created_at_index"
down_revision = "0007_root_cause_revisions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_runs_created_at", "runs", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_runs_created_at", table_name="runs")
