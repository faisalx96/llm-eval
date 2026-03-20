"""Add label and explanation columns to run_item_scores.

Revision ID: 0010_metric_result_fields
Revises: 0009_add_stopped_pending_status
Create Date: 2026-03-20
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0010_metric_result_fields"
down_revision = "0009_add_stopped_pending_status"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("run_item_scores", sa.Column("label", sa.String(200), nullable=True))
    op.add_column("run_item_scores", sa.Column("explanation", sa.Text, nullable=True))


def downgrade() -> None:
    op.drop_column("run_item_scores", "explanation")
    op.drop_column("run_item_scores", "label")
