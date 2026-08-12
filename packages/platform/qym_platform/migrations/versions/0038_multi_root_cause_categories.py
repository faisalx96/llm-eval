"""Store multiple root-cause categories on review candidates.

Revision ID: 0038_multi_root_cause_categories
Revises: 0037_remove_project_desc
Create Date: 2026-08-05
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0038_multi_root_cause_categories"
down_revision = "0037_remove_project_desc"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("review_corrections") as batch:
        batch.add_column(sa.Column("ai_root_causes", sa.JSON(), nullable=True))
        batch.add_column(sa.Column("human_root_causes", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("review_corrections") as batch:
        batch.drop_column("human_root_causes")
        batch.drop_column("ai_root_causes")
