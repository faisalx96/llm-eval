"""Store project-scoped analyzer roles.

Revision ID: 0028_project_analyzer_roles
Revises: 0027_analyzer_document_library
Create Date: 2026-07-21
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0028_project_analyzer_roles"
down_revision = "0027_analyzer_document_library"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("projects") as batch:
        batch.add_column(
            sa.Column(
                "analyzer_roles",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'[]'"),
            )
        ) 


def downgrade() -> None:
    with op.batch_alter_table("projects") as batch:
        batch.drop_column("analyzer_roles")
