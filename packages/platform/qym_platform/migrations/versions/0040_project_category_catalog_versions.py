"""Add immutable project category catalog versions.

Revision ID: 0040_category_catalog
Revises: 0039_category_taxonomy
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0040_category_catalog"
down_revision = "0039_category_taxonomy"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "project_analysis_category_catalog_versions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("project_id", sa.String(length=36), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("categories", sa.JSON(), nullable=False),
        sa.Column("category_entries", sa.JSON(), nullable=False),
        sa.Column("category_details_map", sa.JSON(), nullable=False),
        sa.Column("category_taxonomy", sa.JSON(), nullable=False),
        sa.Column("max_root_cause_categories", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("source", sa.String(length=30), nullable=False, server_default="manual"),
        sa.Column(
            "restored_from_version_id",
            sa.String(length=36),
            sa.ForeignKey("project_analysis_category_catalog_versions.id"),
            nullable=True,
        ),
        sa.Column(
            "parent_version_id",
            sa.String(length=36),
            sa.ForeignKey("project_analysis_category_catalog_versions.id"),
            nullable=True,
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by_user_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("project_id", "version", name="uq_project_analysis_category_catalog_version"),
    )
    op.create_index(
        "ix_project_analysis_category_catalog_versions_project_id",
        "project_analysis_category_catalog_versions",
        ["project_id"],
    )
    op.create_index(
        "ix_project_analysis_category_catalog_versions_active",
        "project_analysis_category_catalog_versions",
        ["project_id", "is_active"],
    )
    op.create_index(
        "ix_project_analysis_category_catalog_versions_project_version",
        "project_analysis_category_catalog_versions",
        ["project_id", "version"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_project_analysis_category_catalog_versions_active",
        table_name="project_analysis_category_catalog_versions",
    )
    op.drop_index(
        "ix_project_analysis_category_catalog_versions_project_version",
        table_name="project_analysis_category_catalog_versions",
    )
    op.drop_index(
        "ix_project_analysis_category_catalog_versions_project_id",
        table_name="project_analysis_category_catalog_versions",
    )
    op.drop_table("project_analysis_category_catalog_versions")
