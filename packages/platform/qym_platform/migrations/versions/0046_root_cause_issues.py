"""Store structured root-cause issues on review corrections.

Revision ID: 0046
Revises: 0045
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0046"
down_revision = "0045"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("review_corrections") as batch:
        batch.add_column(sa.Column("ai_root_cause_issues", sa.JSON(), nullable=True))
        batch.add_column(
            sa.Column("human_root_cause_issues", sa.JSON(), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table("review_corrections") as batch:
        batch.drop_column("human_root_cause_issues")
        batch.drop_column("ai_root_cause_issues")
