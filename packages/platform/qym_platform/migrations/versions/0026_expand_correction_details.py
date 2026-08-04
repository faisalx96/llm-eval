"""Store review-correction detail fields as unbounded text.

Revision ID: 0026_expand_correction_details
Revises: 0025_run_metric_specs
Create Date: 2026-07-20
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0026_expand_correction_details"
down_revision = "0025_run_metric_specs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("review_corrections") as batch:
        batch.alter_column(
            "ai_root_cause_detail",
            existing_type=sa.String(length=200),
            type_=sa.Text(),
            existing_nullable=False,
        )
        batch.alter_column(
            "human_root_cause_detail",
            existing_type=sa.String(length=200),
            type_=sa.Text(),
            existing_nullable=False,
        )


def downgrade() -> None:
    # Values introduced after this migration may not fit the legacy columns.
    # Truncate them explicitly so the downgrade is deterministic on PostgreSQL.
    op.execute(
        sa.text(
            "UPDATE review_corrections "
            "SET ai_root_cause_detail = substr(ai_root_cause_detail, 1, 200), "
            "human_root_cause_detail = substr(human_root_cause_detail, 1, 200)"
        )
    )
    with op.batch_alter_table("review_corrections") as batch:
        batch.alter_column(
            "ai_root_cause_detail",
            existing_type=sa.Text(),
            type_=sa.String(length=200),
            existing_nullable=False,
        )
        batch.alter_column(
            "human_root_cause_detail",
            existing_type=sa.Text(),
            type_=sa.String(length=200),
            existing_nullable=False,
        )
