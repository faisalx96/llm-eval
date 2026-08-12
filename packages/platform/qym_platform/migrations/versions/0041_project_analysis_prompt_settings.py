"""Add editable project-scoped analysis system prompts.

Revision ID: 0041_analysis_prompts
Revises: 0040_category_catalog
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0041_analysis_prompts"
down_revision = "0040_category_catalog"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "project_analysis_prompt_settings",
        sa.Column(
            "project_id",
            sa.String(length=36),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("llm_analyzer_system_prompt", sa.Text(), nullable=False),
        sa.Column("aggregator_system_prompt", sa.Text(), nullable=False),
        sa.Column("rules_writer_system_prompt", sa.Text(), nullable=False),
        sa.Column(
            "updated_by_user_id",
            sa.String(length=36),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("project_analysis_prompt_settings")
