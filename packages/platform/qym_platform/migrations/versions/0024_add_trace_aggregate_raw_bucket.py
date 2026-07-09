"""Add raw_bucket JSON to run_trace_aggregates.

Stores the full span-derived trace bucket (including latency totals/counts
and named outer-scope parent buckets) so live trace stats can be rebuilt
incrementally without reloading every span of the run.

Revision ID: 0024_trace_aggregate_raw_bucket
Revises: 0023_repeat_runs
Create Date: 2026-07-07
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0024_trace_aggregate_raw_bucket"
down_revision = "0023_repeat_runs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "run_trace_aggregates",
        sa.Column("raw_bucket", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("run_trace_aggregates", "raw_bucket")
