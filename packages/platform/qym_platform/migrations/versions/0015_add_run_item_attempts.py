"""Add per-attempt records and retry count on run items.

Revision ID: 0015_add_run_item_attempts
Revises: 0014_project_reset
Create Date: 2026-04-06
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0015_add_run_item_attempts"
down_revision = "0014_project_reset"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("run_items", sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"))

    op.create_table(
        "run_item_attempts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("run_id", sa.String(length=36), sa.ForeignKey("runs.id"), nullable=False),
        sa.Column("item_id", sa.String(length=200), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="FAILED"),
        sa.Column("latency_ms", sa.Float(), nullable=True),
        sa.Column("task_started_at_ms", sa.BigInteger(), nullable=True),
        sa.Column("trace_id", sa.String(length=200), nullable=True),
        sa.Column("trace_url", sa.String(length=2000), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("is_last_attempt", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.UniqueConstraint("run_id", "item_id", "attempt_number", name="uq_run_item_attempt"),
    )
    op.create_index("ix_run_item_attempts_run_id", "run_item_attempts", ["run_id"])
    op.create_index("ix_run_item_attempts_item_id", "run_item_attempts", ["item_id"])
    op.create_index("ix_run_item_attempt_run_item", "run_item_attempts", ["run_id", "item_id"])


def downgrade() -> None:
    op.drop_index("ix_run_item_attempt_run_item", table_name="run_item_attempts")
    op.drop_index("ix_run_item_attempts_item_id", table_name="run_item_attempts")
    op.drop_index("ix_run_item_attempts_run_id", table_name="run_item_attempts")
    op.drop_table("run_item_attempts")
    op.drop_column("run_items", "retry_count")
