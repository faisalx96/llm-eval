"""Repair activation fields on early analysis-rule version tables.

Revision ID: 0031_repair_rule_activation
Revises: 0030_analysis_rule_versions
Create Date: 2026-07-23
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0031_repair_rule_activation"
down_revision = "0030_analysis_rule_versions"
branch_labels = None
depends_on = None


TABLE = "project_analysis_rule_versions"
ACTIVE_INDEX = "ix_project_analysis_rule_versions_active"


def upgrade() -> None:
    """Bring databases created by the early 0030 draft up to the final schema."""
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    column_names = {
        column["name"] for column in inspector.get_columns(TABLE)
    }

    if "activated_at" not in column_names:
        op.add_column(
            TABLE,
            sa.Column("activated_at", sa.DateTime(), nullable=True),
        )
        connection.execute(
            sa.text(
                f"UPDATE {TABLE} "
                "SET activated_at = COALESCE(created_at, CURRENT_TIMESTAMP) "
                "WHERE activated_at IS NULL"
            )
        )
        op.alter_column(TABLE, "activated_at", nullable=False)

    if "activated_by_user_id" not in column_names:
        op.add_column(
            TABLE,
            sa.Column("activated_by_user_id", sa.String(length=36), nullable=True),
        )
        connection.execute(
            sa.text(
                f"UPDATE {TABLE} "
                "SET activated_by_user_id = created_by_user_id "
                "WHERE activated_by_user_id IS NULL"
            )
        )
        op.create_foreign_key(
            "fk_project_analysis_rule_versions_activated_by_user_id",
            TABLE,
            "users",
            ["activated_by_user_id"],
            ["id"],
        )

    indexes = {
        index["name"]: index
        for index in sa.inspect(connection).get_indexes(TABLE)
    }
    active_index = indexes.get(ACTIVE_INDEX)
    expected_columns = ["project_id", "deleted_at", "activated_at"]
    if active_index and active_index.get("column_names") != expected_columns:
        op.drop_index(ACTIVE_INDEX, table_name=TABLE)
        active_index = None
    if active_index is None:
        op.create_index(ACTIVE_INDEX, TABLE, expected_columns)


def downgrade() -> None:
    """Keep the compatible fields; only restore the earlier active index."""
    indexes = {
        index["name"]: index
        for index in sa.inspect(op.get_bind()).get_indexes(TABLE)
    }
    if ACTIVE_INDEX in indexes:
        op.drop_index(ACTIVE_INDEX, table_name=TABLE)
    op.create_index(
        ACTIVE_INDEX,
        TABLE,
        ["project_id", "deleted_at", "version"],
    )
