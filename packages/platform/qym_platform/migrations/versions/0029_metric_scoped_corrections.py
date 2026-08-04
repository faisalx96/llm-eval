"""Scope review corrections to individual metrics.

Revision ID: 0029_metric_scoped_corrections
Revises: 0028_project_analyzer_roles
Create Date: 2026-07-21
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0029_metric_scoped_corrections"
down_revision = "0028_project_analyzer_roles"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("review_corrections") as batch:
        batch.add_column(sa.Column("metric_name", sa.String(length=200), nullable=True))
        batch.create_index(
            "ix_review_corrections_metric_name",
            ["metric_name"],
            unique=False,
        )
        batch.create_index(
            "ix_review_corrections_run_item_metric_active",
            ["run_id", "item_id", "metric_name", "is_active"],
            unique=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("review_corrections") as batch:
        batch.drop_index("ix_review_corrections_run_item_metric_active")
        batch.drop_index("ix_review_corrections_metric_name")
        batch.drop_column("metric_name")
