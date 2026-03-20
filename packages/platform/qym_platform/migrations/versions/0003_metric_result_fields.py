"""Add label and explanation columns to run_item_scores.

Revision ID: 0003_metric_result_fields
Revises: 0002_org_units
Create Date: 2026-02-26
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0003_metric_result_fields"
down_revision = "0002_org_units"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("run_item_scores", sa.Column("label", sa.String(200), nullable=True))
    op.add_column("run_item_scores", sa.Column("explanation", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("run_item_scores", "explanation")
    op.drop_column("run_item_scores", "label")
