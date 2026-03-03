"""Add solution fields to review_corrections table.

Revision ID: 0004_add_solution_fields
Revises: 0003_review_corrections
Create Date: 2026-03-02
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0004_add_solution_fields"
down_revision = "0003_review_corrections"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "review_corrections",
        sa.Column("ai_solution", sa.String(length=200), nullable=False, server_default=""),
    )
    op.add_column(
        "review_corrections",
        sa.Column("ai_solution_note", sa.Text(), nullable=False, server_default=""),
    )
    op.add_column(
        "review_corrections",
        sa.Column("human_solution", sa.String(length=200), nullable=False, server_default=""),
    )
    op.add_column(
        "review_corrections",
        sa.Column("human_solution_note", sa.Text(), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("review_corrections", "human_solution_note")
    op.drop_column("review_corrections", "human_solution")
    op.drop_column("review_corrections", "ai_solution_note")
    op.drop_column("review_corrections", "ai_solution")
