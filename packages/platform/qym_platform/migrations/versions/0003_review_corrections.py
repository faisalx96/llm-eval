"""Add review_corrections table and users.llm_config column.

Revision ID: 0003_review_corrections
Revises: 0002_org_units
Create Date: 2026-02-28
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0003_review_corrections"
down_revision = "0002_org_units"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add llm_config JSON column to users table
    op.add_column(
        "users",
        sa.Column("llm_config", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
    )

    # Create review_corrections table
    op.create_table(
        "review_corrections",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("run_id", sa.String(length=36), sa.ForeignKey("runs.id"), nullable=False),
        sa.Column("item_id", sa.String(length=200), nullable=False),
        sa.Column("task", sa.String(length=200), nullable=False),
        sa.Column("input_snapshot", sa.JSON(), nullable=True),
        sa.Column("expected_snapshot", sa.JSON(), nullable=True),
        sa.Column("output_snapshot", sa.JSON(), nullable=True),
        sa.Column("scores_snapshot", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("ai_root_cause", sa.String(length=200), nullable=False),
        sa.Column("ai_root_cause_note", sa.Text(), nullable=False, server_default=""),
        sa.Column("ai_confidence", sa.Float(), nullable=True),
        sa.Column("human_root_cause", sa.String(length=200), nullable=False),
        sa.Column("human_root_cause_note", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "corrected_by_user_id",
            sa.String(length=36),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_review_corrections_run_id", "review_corrections", ["run_id"])
    op.create_index("ix_review_corrections_item_id", "review_corrections", ["item_id"])
    op.create_index("ix_review_corrections_task", "review_corrections", ["task"])
    op.create_index(
        "ix_review_corrections_task_created", "review_corrections", ["task", "created_at"]
    )
    op.create_index(
        "ix_review_corrections_corrected_by", "review_corrections", ["corrected_by_user_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_review_corrections_corrected_by", table_name="review_corrections")
    op.drop_index("ix_review_corrections_task_created", table_name="review_corrections")
    op.drop_index("ix_review_corrections_task", table_name="review_corrections")
    op.drop_index("ix_review_corrections_item_id", table_name="review_corrections")
    op.drop_index("ix_review_corrections_run_id", table_name="review_corrections")
    op.drop_table("review_corrections")
    op.drop_column("users", "llm_config")
