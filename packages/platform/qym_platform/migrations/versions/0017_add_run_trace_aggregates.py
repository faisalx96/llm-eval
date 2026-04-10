"""Add live run trace aggregate table.

Revision ID: 0017_add_run_trace_aggregates
Revises: 0016_add_local_auth_credentials
Create Date: 2026-04-10
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0017_add_run_trace_aggregates"
down_revision = "0016_add_local_auth_credentials"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "run_trace_aggregates",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("run_id", sa.String(length=36), sa.ForeignKey("runs.id"), nullable=False),
        sa.Column("trace_id", sa.String(length=64), nullable=False),
        sa.Column("span_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cost", sa.Float(), nullable=False, server_default="0"),
        sa.Column("llm_calls", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tool_calls", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tool_errors", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("has_reasoning", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("has_reasoning_tokens", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("reasoning_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.UniqueConstraint("run_id", "trace_id", name="uq_run_trace_aggregate"),
    )
    op.create_index("ix_run_trace_aggregates_run_id", "run_trace_aggregates", ["run_id"])
    op.create_index(
        "ix_run_trace_aggregate_run_trace",
        "run_trace_aggregates",
        ["run_id", "trace_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_run_trace_aggregate_run_trace", table_name="run_trace_aggregates")
    op.drop_index("ix_run_trace_aggregates_run_id", table_name="run_trace_aggregates")
    op.drop_table("run_trace_aggregates")
