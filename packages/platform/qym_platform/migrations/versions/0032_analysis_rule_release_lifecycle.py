"""Add dataset-style release lifecycle to analyzer rule versions.

Revision ID: 0032_rule_release_lifecycle
Revises: 0031_repair_rule_activation
Create Date: 2026-07-25
"""

from __future__ import annotations

import hashlib
import json

import sqlalchemy as sa
from alembic import op


revision = "0032_rule_release_lifecycle"
down_revision = "0031_repair_rule_activation"
branch_labels = None
depends_on = None


def _content_hash(rules: object) -> str:
    payload = json.dumps(
        rules if isinstance(rules, list) else [],
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def upgrade() -> None:
    with op.batch_alter_table("project_analysis_rule_versions") as batch:
        batch.add_column(
            sa.Column("name", sa.String(length=200), nullable=False, server_default="")
        )
        batch.add_column(
            sa.Column("description", sa.Text(), nullable=False, server_default="")
        )
        batch.add_column(
            sa.Column("status", sa.String(length=20), nullable=False, server_default="published")
        )
        batch.add_column(
            sa.Column(
                "parent_version_id",
                sa.String(length=36),
                sa.ForeignKey(
                    "project_analysis_rule_versions.id",
                    name="fk_rule_versions_parent_version_id",
                ),
                nullable=True,
            )
        )
        batch.add_column(
            sa.Column(
                "base_version_id",
                sa.String(length=36),
                sa.ForeignKey(
                    "project_analysis_rule_versions.id",
                    name="fk_rule_versions_base_version_id",
                ),
                nullable=True,
            )
        )
        batch.add_column(
            sa.Column("content_hash", sa.String(length=64), nullable=False, server_default="")
        )
        batch.add_column(sa.Column("updated_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("published_at", sa.DateTime(), nullable=True))
        batch.add_column(
            sa.Column(
                "published_by_user_id",
                sa.String(length=36),
                sa.ForeignKey(
                    "users.id",
                    name="fk_rule_versions_published_by_user_id",
                ),
                nullable=True,
            )
        )
        batch.create_index(
            "ix_project_analysis_rule_versions_status",
            ["project_id", "status"],
        )
        batch.create_index(
            "ix_project_analysis_rule_versions_parent",
            ["parent_version_id"],
        )
        batch.create_index(
            "ix_project_analysis_rule_versions_base",
            ["base_version_id"],
        )

    op.create_table(
        "project_analysis_rule_aliases",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "project_id",
            sa.String(length=36),
            sa.ForeignKey("projects.id"),
            nullable=False,
        ),
        sa.Column("alias", sa.String(length=100), nullable=False),
        sa.Column(
            "rule_version_id",
            sa.String(length=36),
            sa.ForeignKey("project_analysis_rule_versions.id"),
            nullable=False,
        ),
        sa.Column(
            "updated_by_user_id",
            sa.String(length=36),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint(
            "project_id", "alias", name="uq_project_analysis_rule_alias"
        ),
    )
    op.create_index(
        "ix_project_analysis_rule_aliases_project_id",
        "project_analysis_rule_aliases",
        ["project_id"],
    )
    op.create_index(
        "ix_project_analysis_rule_aliases_rule_version_id",
        "project_analysis_rule_aliases",
        ["rule_version_id"],
    )

    connection = op.get_bind()
    versions = sa.table(
        "project_analysis_rule_versions",
        sa.column("id", sa.String()),
        sa.column("project_id", sa.String()),
        sa.column("version", sa.Integer()),
        sa.column("rules", sa.JSON()),
        sa.column("created_by_user_id", sa.String()),
        sa.column("created_at", sa.DateTime()),
        sa.column("activated_at", sa.DateTime()),
        sa.column("activated_by_user_id", sa.String()),
        sa.column("deleted_at", sa.DateTime()),
        sa.column("status", sa.String()),
        sa.column("parent_version_id", sa.String()),
        sa.column("base_version_id", sa.String()),
        sa.column("content_hash", sa.String()),
        sa.column("updated_at", sa.DateTime()),
        sa.column("published_at", sa.DateTime()),
        sa.column("published_by_user_id", sa.String()),
    )
    aliases = sa.table(
        "project_analysis_rule_aliases",
        sa.column("project_id", sa.String()),
        sa.column("alias", sa.String()),
        sa.column("rule_version_id", sa.String()),
        sa.column("updated_by_user_id", sa.String()),
        sa.column("updated_at", sa.DateTime()),
    )

    project_ids = connection.execute(
        sa.select(versions.c.project_id).distinct()
    ).scalars()
    for project_id in project_ids:
        rows = connection.execute(
            sa.select(versions)
            .where(versions.c.project_id == project_id)
            .order_by(versions.c.version.asc())
        ).mappings().all()
        previous_id = None
        root_id = rows[0]["id"] if rows else None
        for row in rows:
            status = "archived" if row["deleted_at"] is not None else "published"
            timestamp = row["activated_at"] or row["created_at"]
            connection.execute(
                versions.update()
                .where(versions.c.id == row["id"])
                .values(
                    status=status,
                    parent_version_id=previous_id,
                    base_version_id=root_id if previous_id else None,
                    content_hash=_content_hash(row["rules"]),
                    updated_at=timestamp,
                    published_at=timestamp if status == "published" else None,
                    published_by_user_id=(
                        row["activated_by_user_id"]
                        or row["created_by_user_id"]
                        if status == "published"
                        else None
                    ),
                )
            )
            previous_id = row["id"]

        active = next(
            (
                row
                for row in sorted(
                    rows,
                    key=lambda item: (
                        item["activated_at"] or item["created_at"],
                        item["version"],
                    ),
                    reverse=True,
                )
                if row["deleted_at"] is None
            ),
            None,
        )
        if active and (active["activated_by_user_id"] or active["created_by_user_id"]):
            connection.execute(
                aliases.insert().values(
                    project_id=project_id,
                    alias="production",
                    rule_version_id=active["id"],
                    updated_by_user_id=(
                        active["activated_by_user_id"]
                        or active["created_by_user_id"]
                    ),
                    updated_at=active["activated_at"] or active["created_at"],
                )
            )

    with op.batch_alter_table("project_analysis_rule_versions") as batch:
        batch.alter_column("updated_at", existing_type=sa.DateTime(), nullable=False)


def downgrade() -> None:
    op.drop_index(
        "ix_project_analysis_rule_aliases_rule_version_id",
        table_name="project_analysis_rule_aliases",
    )
    op.drop_index(
        "ix_project_analysis_rule_aliases_project_id",
        table_name="project_analysis_rule_aliases",
    )
    op.drop_table("project_analysis_rule_aliases")
    with op.batch_alter_table("project_analysis_rule_versions") as batch:
        batch.drop_index("ix_project_analysis_rule_versions_base")
        batch.drop_index("ix_project_analysis_rule_versions_parent")
        batch.drop_index("ix_project_analysis_rule_versions_status")
        batch.drop_column("published_by_user_id")
        batch.drop_column("published_at")
        batch.drop_column("updated_at")
        batch.drop_column("content_hash")
        batch.drop_column("base_version_id")
        batch.drop_column("parent_version_id")
        batch.drop_column("status")
        batch.drop_column("description")
        batch.drop_column("name")
