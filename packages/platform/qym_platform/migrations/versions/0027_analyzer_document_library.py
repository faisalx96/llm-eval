"""Persist a project analyzer-document library with per-run selection.

Revision ID: 0027_analyzer_document_library
Revises: 0026_expand_correction_details
Create Date: 2026-07-20
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0027_analyzer_document_library"
down_revision = "0026_expand_correction_details"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "analyzer_documents",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("uploaded_by_user_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("characters", sa.Integer(), nullable=False),
        sa.Column("truncated", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["uploaded_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_analyzer_documents_project_id", "analyzer_documents", ["project_id"])
    op.create_index(
        "ix_analyzer_documents_uploaded_by_user_id",
        "analyzer_documents",
        ["uploaded_by_user_id"],
    )
    op.create_index(
        "ix_analyzer_documents_project_created",
        "analyzer_documents",
        ["project_id", "created_at"],
    )
    op.create_table(
        "analyzer_run_documents",
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("document_id", sa.String(length=36), nullable=False),
        sa.Column("selected", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["analyzer_documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("run_id", "document_id"),
    )


def downgrade() -> None:
    op.drop_table("analyzer_run_documents")
    op.drop_index("ix_analyzer_documents_project_created", table_name="analyzer_documents")
    op.drop_index("ix_analyzer_documents_uploaded_by_user_id", table_name="analyzer_documents")
    op.drop_index("ix_analyzer_documents_project_id", table_name="analyzer_documents")
    op.drop_table("analyzer_documents")
