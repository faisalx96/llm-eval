"""Add root_cause_detail fields to review_corrections table.

Revision ID: 0005_add_rc_detail
Revises: 0004_add_solution_fields
Create Date: 2026-03-03
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0005_add_rc_detail"
down_revision = "0004_add_solution_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "review_corrections",
        sa.Column("ai_root_cause_detail", sa.String(length=200), nullable=False, server_default=""),
    )
    op.add_column(
        "review_corrections",
        sa.Column("human_root_cause_detail", sa.String(length=200), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("review_corrections", "human_root_cause_detail")
    op.drop_column("review_corrections", "ai_root_cause_detail")
