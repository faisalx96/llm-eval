"""Add merge-parent edges for analyzer rule-version lineage.

Revision ID: 0035_rule_merge_lineage
Revises: 0034_draft_rule_activation
Create Date: 2026-07-29
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0035_rule_merge_lineage"
down_revision = "0034_draft_rule_activation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "project_analysis_rule_merge_parents",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("version_id", sa.String(length=36), nullable=False),
        sa.Column("parent_version_id", sa.String(length=36), nullable=False),
        sa.Column("merge_base_version_id", sa.String(length=36), nullable=True),
        sa.Column("created_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "version_id <> parent_version_id",
            name="ck_project_analysis_rule_merge_parent_distinct",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
        ),
        sa.ForeignKeyConstraint(
            ["merge_base_version_id"],
            ["project_analysis_rule_versions.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["parent_version_id"],
            ["project_analysis_rule_versions.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["version_id"],
            ["project_analysis_rule_versions.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "version_id",
            "parent_version_id",
            name="uq_project_analysis_rule_merge_parent",
        ),
    )
    op.create_index(
        "ix_project_analysis_rule_merge_parents_version_id",
        "project_analysis_rule_merge_parents",
        ["version_id"],
    )
    op.create_index(
        "ix_project_analysis_rule_merge_parents_parent_version_id",
        "project_analysis_rule_merge_parents",
        ["parent_version_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_project_analysis_rule_merge_parents_parent_version_id",
        table_name="project_analysis_rule_merge_parents",
    )
    op.drop_index(
        "ix_project_analysis_rule_merge_parents_version_id",
        table_name="project_analysis_rule_merge_parents",
    )
    op.drop_table("project_analysis_rule_merge_parents")
