"""Store root-cause category taxonomy alongside review candidates.

Revision ID: 0039_category_taxonomy
Revises: 0038_multi_root_cause_categories
Create Date: 2026-08-05
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0039_category_taxonomy"
down_revision = "0038_multi_root_cause_categories"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("review_corrections") as batch:
        batch.add_column(sa.Column("ai_category_taxonomy", sa.JSON(), nullable=True))
        batch.add_column(
            sa.Column("human_category_taxonomy", sa.JSON(), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table("review_corrections") as batch:
        batch.drop_column("human_category_taxonomy")
        batch.drop_column("ai_category_taxonomy")
