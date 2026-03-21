"""Add spans table for native OTEL trace storage.

Revision ID: 0011_add_spans_table
Revises: 0010_metric_result_fields
Create Date: 2026-03-20
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0011_add_spans_table"
down_revision = "0010_metric_result_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "spans",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("run_id", sa.String(36), sa.ForeignKey("runs.id"), nullable=False),
        sa.Column("trace_id", sa.String(64), nullable=False),
        sa.Column("span_id", sa.String(32), nullable=False),
        sa.Column("parent_span_id", sa.String(32), nullable=True),
        sa.Column("name", sa.String(500), nullable=False),
        sa.Column("kind", sa.String(20), server_default="INTERNAL"),
        sa.Column("start_time_ns", sa.BigInteger(), nullable=True),
        sa.Column("end_time_ns", sa.BigInteger(), nullable=True),
        sa.Column("duration_ms", sa.Float(), nullable=True),
        sa.Column("status", sa.String(20), server_default="UNSET"),
        sa.Column("attributes", sa.JSON(), server_default="{}"),
        sa.Column("events", sa.JSON(), server_default="[]"),
    )
    op.create_index("ix_span_run_id", "spans", ["run_id"])
    op.create_index("ix_span_run_trace", "spans", ["run_id", "trace_id"])
    op.create_unique_constraint("uq_span", "spans", ["run_id", "span_id"])


def downgrade() -> None:
    op.drop_table("spans")
