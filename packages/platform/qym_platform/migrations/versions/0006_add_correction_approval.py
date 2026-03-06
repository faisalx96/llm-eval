"""Add approval workflow fields to review_corrections table.

Revision ID: 0006_correction_approval
Revises: 0005_add_rc_detail
Create Date: 2026-03-03
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0006_correction_approval"
down_revision = "0005_add_rc_detail"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create the PG enum type first, then reference it in the column
    correctionstatus = sa.Enum("pending", "approved", "rejected", name="correctionstatus")
    correctionstatus.create(op.get_bind(), checkfirst=True)

    op.add_column(
        "review_corrections",
        sa.Column(
            "status",
            correctionstatus,
            nullable=False,
            server_default="pending",
        ),
    )
    op.add_column(
        "review_corrections",
        sa.Column("reviewed_by_user_id", sa.String(length=36), nullable=True),
    )
    op.add_column(
        "review_corrections",
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
    )
    op.add_column(
        "review_corrections",
        sa.Column("review_comment", sa.Text(), nullable=False, server_default=""),
    )
    op.create_index(
        "ix_review_corrections_status", "review_corrections", ["status"]
    )
    op.create_foreign_key(
        "fk_review_corrections_reviewer",
        "review_corrections",
        "users",
        ["reviewed_by_user_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_review_corrections_reviewer", "review_corrections", type_="foreignkey")
    op.drop_index("ix_review_corrections_status", table_name="review_corrections")
    op.drop_column("review_corrections", "review_comment")
    op.drop_column("review_corrections", "reviewed_at")
    op.drop_column("review_corrections", "reviewed_by_user_id")
    op.drop_column("review_corrections", "status")
    # Drop the PG enum type
    sa.Enum(name="correctionstatus").drop(op.get_bind(), checkfirst=True)
