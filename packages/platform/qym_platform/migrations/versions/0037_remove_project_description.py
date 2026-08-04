"""Remove the obsolete project description.

Revision ID: 0037_remove_project_desc
Revises: 0036_document_enabled
Create Date: 2026-07-30
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0037_remove_project_desc"
down_revision = "0036_document_enabled"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("projects") as batch_op:
        batch_op.drop_column("description")


def downgrade() -> None:
    with op.batch_alter_table("projects") as batch_op:
        batch_op.add_column(
            sa.Column(
                "description",
                sa.Text(),
                nullable=False,
                server_default="",
            )
        )
