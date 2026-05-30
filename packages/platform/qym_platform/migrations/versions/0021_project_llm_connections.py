"""Project-scoped LLM connections; drop per-user llm_config.

Moves AI-analysis LLM configuration from a single per-user setting
(``users.llm_config``) to multiple named, project-owned connections. Per the
"start fresh" decision, existing per-user configs are discarded.

Revision ID: 0021_project_llm_connections
Revises: 0020_native_datasets
Create Date: 2026-05-30
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0021_project_llm_connections"
down_revision = "0020_native_datasets"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "project_llm_connections",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("llm_base_url", sa.String(length=500), nullable=False, server_default=""),
        sa.Column("llm_model", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("llm_api_key_encrypted", sa.Text(), nullable=False, server_default=""),
        sa.Column("llm_api_key_last4", sa.String(length=8), nullable=False, server_default=""),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "name", name="uq_project_llm_connection_name"),
    )
    op.create_index(
        "ix_project_llm_connections_project_id",
        "project_llm_connections",
        ["project_id"],
    )
    op.create_index(
        "ix_project_llm_connections_project_default",
        "project_llm_connections",
        ["project_id", "is_default"],
    )

    # Start fresh: per-user LLM config is discarded.
    with op.batch_alter_table("users") as batch:
        batch.drop_column("llm_config")


def downgrade() -> None:
    # Re-adds the column (empty) — previously stored keys are not recoverable.
    op.add_column(
        "users",
        sa.Column("llm_config", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
    )
    op.drop_index("ix_project_llm_connections_project_default", table_name="project_llm_connections")
    op.drop_index("ix_project_llm_connections_project_id", table_name="project_llm_connections")
    op.drop_table("project_llm_connections")
