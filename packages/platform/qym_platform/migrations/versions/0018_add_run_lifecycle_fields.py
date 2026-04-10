"""Add run lifecycle fields for liveness reconciliation.

Revision ID: 0018_add_run_lifecycle_fields
Revises: 0017_add_run_trace_aggregates
Create Date: 2026-04-10
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0018_add_run_lifecycle_fields"
down_revision = "0017_add_run_trace_aggregates"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("runs", sa.Column("last_event_at", sa.DateTime(), nullable=True))
    op.add_column("runs", sa.Column("status_reason", sa.String(length=50), nullable=True))
    op.create_index("ix_runs_last_event_at", "runs", ["last_event_at"])


def downgrade() -> None:
    op.drop_index("ix_runs_last_event_at", table_name="runs")
    op.drop_column("runs", "status_reason")
    op.drop_column("runs", "last_event_at")
