"""Add versioned subcategory taxonomy definitions.

Revision ID: 0045
Revises: 0044
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0045"
down_revision = "0044"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("project_analysis_category_catalog_versions") as batch:
        batch.add_column(
            sa.Column(
                "subcategory_taxonomy",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'{}'"),
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("project_analysis_category_catalog_versions") as batch:
        batch.drop_column("subcategory_taxonomy")
