"""Add soft-delete columns to runs table.

Revision ID: 0013_run_soft_delete
Revises: 0012_add_span_links
Create Date: 2026-04-03
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0013_run_soft_delete"
down_revision = "0012_add_span_links"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("runs", sa.Column("deleted_at", sa.DateTime(), nullable=True))
    op.add_column(
        "runs",
        sa.Column(
            "deleted_by_user_id",
            sa.String(36),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
    )
    op.create_index("ix_runs_deleted_at", "runs", ["deleted_at"])


def downgrade() -> None:
    op.drop_index("ix_runs_deleted_at", table_name="runs")
    op.drop_column("runs", "deleted_by_user_id")
    op.drop_column("runs", "deleted_at")
