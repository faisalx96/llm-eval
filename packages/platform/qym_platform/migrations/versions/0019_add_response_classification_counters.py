"""Add qym.response.classification counters to run_trace_aggregates.

Revision ID: 0019_add_response_classification_counters
Revises: 0018_add_run_lifecycle_fields
Create Date: 2026-04-17
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0019_response_classification"
down_revision = "0018_add_run_lifecycle_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "run_trace_aggregates",
        sa.Column("malformed_tool_calls", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "run_trace_aggregates",
        sa.Column("noisy_reasoning", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "run_trace_aggregates",
        sa.Column("provider_errors", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("run_trace_aggregates", "provider_errors")
    op.drop_column("run_trace_aggregates", "noisy_reasoning")
    op.drop_column("run_trace_aggregates", "malformed_tool_calls")
