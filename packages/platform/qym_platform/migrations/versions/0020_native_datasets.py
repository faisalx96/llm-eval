"""Add native datasets.

Revision ID: 0020_native_datasets
Revises: 0019_response_classification
Create Date: 2026-05-19
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0020_native_datasets"
down_revision = "0019_response_classification"
branch_labels = None
depends_on = None


dataset_status = sa.Enum("draft", "published", "archived", name="datasetversionstatus")


def upgrade() -> None:
    dataset_status.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "datasets",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("slug", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("tags", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("created_by_user_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "slug", name="uq_dataset_project_slug"),
    )
    op.create_index("ix_datasets_project_id", "datasets", ["project_id"])
    op.create_index("ix_datasets_slug", "datasets", ["slug"])
    op.create_index("ix_datasets_deleted_at", "datasets", ["deleted_at"])
    op.create_index("ix_datasets_project_deleted", "datasets", ["project_id", "deleted_at"])

    op.create_table(
        "dataset_versions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("dataset_id", sa.String(length=36), nullable=False),
        sa.Column("version", sa.String(length=100), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", dataset_status, nullable=False),
        sa.Column("source_type", sa.String(length=50), nullable=False, server_default="api"),
        sa.Column("source_uri", sa.Text(), nullable=False, server_default=""),
        sa.Column("parent_version_id", sa.String(length=36), nullable=True),
        sa.Column("base_version_id", sa.String(length=36), nullable=True),
        sa.Column("schema", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("labels", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("item_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("content_hash", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("created_by_user_id", sa.String(length=36), nullable=False),
        sa.Column("published_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("published_at", sa.DateTime(), nullable=True),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.ForeignKeyConstraint(["base_version_id"], ["dataset_versions.id"]),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["dataset_id"], ["datasets.id"]),
        sa.ForeignKeyConstraint(["parent_version_id"], ["dataset_versions.id"]),
        sa.ForeignKeyConstraint(["published_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("dataset_id", "version", name="uq_dataset_version"),
    )
    op.create_index("ix_dataset_versions_dataset_id", "dataset_versions", ["dataset_id"])
    op.create_index("ix_dataset_versions_status", "dataset_versions", ["status"])
    op.create_index("ix_dataset_versions_parent_version_id", "dataset_versions", ["parent_version_id"])
    op.create_index("ix_dataset_versions_base_version_id", "dataset_versions", ["base_version_id"])
    op.create_index("ix_dataset_versions_created_by_user_id", "dataset_versions", ["created_by_user_id"])
    op.create_index("ix_dataset_versions_dataset_status", "dataset_versions", ["dataset_id", "status"])

    op.create_table(
        "dataset_aliases",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("dataset_id", sa.String(length=36), nullable=False),
        sa.Column("alias", sa.String(length=100), nullable=False),
        sa.Column("dataset_version_id", sa.String(length=36), nullable=False),
        sa.Column("updated_by_user_id", sa.String(length=36), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["dataset_id"], ["datasets.id"]),
        sa.ForeignKeyConstraint(["dataset_version_id"], ["dataset_versions.id"]),
        sa.ForeignKeyConstraint(["updated_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("dataset_id", "alias", name="uq_dataset_alias"),
    )
    op.create_index("ix_dataset_aliases_dataset_id", "dataset_aliases", ["dataset_id"])
    op.create_index("ix_dataset_aliases_dataset_version_id", "dataset_aliases", ["dataset_version_id"])

    op.create_table(
        "dataset_items",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("dataset_version_id", sa.String(length=36), nullable=False),
        sa.Column("item_id", sa.String(length=200), nullable=False),
        sa.Column("index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("input", sa.JSON(), nullable=False),
        sa.Column("expected_output", sa.JSON(), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("labels", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["dataset_version_id"], ["dataset_versions.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("dataset_version_id", "item_id", name="uq_dataset_item_id"),
    )
    op.create_index("ix_dataset_items_dataset_version_id", "dataset_items", ["dataset_version_id"])
    op.create_index("ix_dataset_items_fingerprint", "dataset_items", ["fingerprint"])
    op.create_index("ix_dataset_item_version_fingerprint", "dataset_items", ["dataset_version_id", "fingerprint"])

    op.create_table(
        "dataset_item_revisions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("dataset_item_id", sa.Integer(), nullable=True),
        sa.Column("dataset_version_id", sa.String(length=36), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("change_type", sa.String(length=30), nullable=False),
        sa.Column("before", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("after", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("actor_user_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["dataset_item_id"], ["dataset_items.id"]),
        sa.ForeignKeyConstraint(["dataset_version_id"], ["dataset_versions.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_dataset_item_revisions_dataset_item_id", "dataset_item_revisions", ["dataset_item_id"])
    op.create_index("ix_dataset_item_revisions_dataset_version_id", "dataset_item_revisions", ["dataset_version_id"])
    op.create_index("ix_dataset_item_revisions_actor_user_id", "dataset_item_revisions", ["actor_user_id"])
    op.create_index("ix_dataset_item_revisions_version_item", "dataset_item_revisions", ["dataset_version_id", "dataset_item_id"])

    op.create_table(
        "dataset_version_changes",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("dataset_version_id", sa.String(length=36), nullable=False),
        sa.Column("parent_version_id", sa.String(length=36), nullable=True),
        sa.Column("change_summary", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["dataset_version_id"], ["dataset_versions.id"]),
        sa.ForeignKeyConstraint(["parent_version_id"], ["dataset_versions.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_dataset_version_changes_dataset_version_id", "dataset_version_changes", ["dataset_version_id"])
    op.create_index("ix_dataset_version_changes_parent_version_id", "dataset_version_changes", ["parent_version_id"])

    op.add_column("runs", sa.Column("dataset_id", sa.String(length=36), nullable=True))
    op.add_column("runs", sa.Column("dataset_version_id", sa.String(length=36), nullable=True))
    op.create_index("ix_runs_dataset_id", "runs", ["dataset_id"])
    op.create_index("ix_runs_dataset_version_id", "runs", ["dataset_version_id"])
    op.create_foreign_key("fk_runs_dataset_id", "runs", "datasets", ["dataset_id"], ["id"])
    op.create_foreign_key("fk_runs_dataset_version_id", "runs", "dataset_versions", ["dataset_version_id"], ["id"])

    op.add_column("run_items", sa.Column("dataset_item_pk", sa.Integer(), nullable=True))
    op.create_index("ix_run_items_dataset_item_pk", "run_items", ["dataset_item_pk"])
    op.create_foreign_key("fk_run_items_dataset_item_pk", "run_items", "dataset_items", ["dataset_item_pk"], ["id"])


def downgrade() -> None:
    op.drop_constraint("fk_run_items_dataset_item_pk", "run_items", type_="foreignkey")
    op.drop_index("ix_run_items_dataset_item_pk", table_name="run_items")
    op.drop_column("run_items", "dataset_item_pk")

    op.drop_constraint("fk_runs_dataset_version_id", "runs", type_="foreignkey")
    op.drop_constraint("fk_runs_dataset_id", "runs", type_="foreignkey")
    op.drop_index("ix_runs_dataset_version_id", table_name="runs")
    op.drop_index("ix_runs_dataset_id", table_name="runs")
    op.drop_column("runs", "dataset_version_id")
    op.drop_column("runs", "dataset_id")

    op.drop_table("dataset_version_changes")
    op.drop_table("dataset_item_revisions")
    op.drop_table("dataset_items")
    op.drop_table("dataset_aliases")
    op.drop_table("dataset_versions")
    op.drop_table("datasets")
    dataset_status.drop(op.get_bind(), checkfirst=True)
