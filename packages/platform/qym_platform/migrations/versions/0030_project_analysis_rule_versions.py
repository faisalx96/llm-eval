"""Replace analyzer roles with versioned project analysis rules.

Revision ID: 0030_analysis_rule_versions
Revises: 0029_metric_scoped_corrections
Create Date: 2026-07-23
"""

from __future__ import annotations

import json
from uuid import uuid4

import sqlalchemy as sa
from alembic import op


revision = "0030_analysis_rule_versions"
down_revision = "0029_metric_scoped_corrections"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "project_analysis_rule_versions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "project_id",
            sa.String(length=36),
            sa.ForeignKey("projects.id"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("rules", sa.JSON(), nullable=False),
        sa.Column(
            "source",
            sa.String(length=30),
            nullable=False,
            server_default="manual",
        ),
        sa.Column(
            "created_by_user_id",
            sa.String(length=36),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("activated_at", sa.DateTime(), nullable=False),
        sa.Column(
            "activated_by_user_id",
            sa.String(length=36),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.Column(
            "deleted_by_user_id",
            sa.String(length=36),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
        sa.Column("restored_at", sa.DateTime(), nullable=True),
        sa.Column(
            "restored_by_user_id",
            sa.String(length=36),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
        sa.UniqueConstraint(
            "project_id",
            "version",
            name="uq_project_analysis_rule_version",
        ),
    )
    op.create_index(
        "ix_project_analysis_rule_versions_project_id",
        "project_analysis_rule_versions",
        ["project_id"],
    )
    op.create_index(
        "ix_project_analysis_rule_versions_active",
        "project_analysis_rule_versions",
        ["project_id", "deleted_at", "activated_at"],
    )

    connection = op.get_bind()
    projects = sa.table(
        "projects",
        sa.column("id", sa.String()),
        sa.column("analyzer_roles", sa.JSON()),
        sa.column("updated_at", sa.DateTime()),
        sa.column("created_by_user_id", sa.String()),
    )
    versions = sa.table(
        "project_analysis_rule_versions",
        sa.column("id", sa.String()),
        sa.column("project_id", sa.String()),
        sa.column("version", sa.Integer()),
        sa.column("rules", sa.JSON()),
        sa.column("source", sa.String()),
        sa.column("created_by_user_id", sa.String()),
        sa.column("created_at", sa.DateTime()),
        sa.column("activated_at", sa.DateTime()),
        sa.column("activated_by_user_id", sa.String()),
    )
    for project in connection.execute(
        sa.select(
            projects.c.id,
            projects.c.analyzer_roles,
            projects.c.updated_at,
            projects.c.created_by_user_id,
        )
    ).mappings():
        legacy_rules = project["analyzer_roles"]
        if isinstance(legacy_rules, str):
            try:
                legacy_rules = json.loads(legacy_rules)
            except (TypeError, json.JSONDecodeError):
                legacy_rules = []
        if not isinstance(legacy_rules, list) or not legacy_rules:
            continue
        normalized = [
            {
                "title": str(rule.get("name") or rule.get("title") or "").strip(),
                "instruction": str(
                    rule.get("description") or rule.get("instruction") or ""
                ).strip(),
            }
            for rule in legacy_rules
            if isinstance(rule, dict)
            and str(rule.get("name") or rule.get("title") or "").strip()
            and str(
                rule.get("description") or rule.get("instruction") or ""
            ).strip()
        ]
        if normalized:
            connection.execute(
                versions.insert().values(
                    id=str(uuid4()),
                    project_id=project["id"],
                    version=1,
                    rules=normalized,
                    source="migration",
                    created_by_user_id=project["created_by_user_id"],
                    created_at=project["updated_at"],
                    activated_at=project["updated_at"],
                    activated_by_user_id=project["created_by_user_id"],
                )
            )

    with op.batch_alter_table("projects") as batch:
        batch.drop_column("analyzer_roles")


def downgrade() -> None:
    with op.batch_alter_table("projects") as batch:
        batch.add_column(
            sa.Column(
                "analyzer_roles",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'[]'"),
            )
        )

    connection = op.get_bind()
    projects = sa.table(
        "projects",
        sa.column("id", sa.String()),
        sa.column("analyzer_roles", sa.JSON()),
    )
    versions = sa.table(
        "project_analysis_rule_versions",
        sa.column("project_id", sa.String()),
        sa.column("version", sa.Integer()),
        sa.column("rules", sa.JSON()),
        sa.column("deleted_at", sa.DateTime()),
    )
    project_ids = connection.execute(sa.select(projects.c.id)).scalars()
    for project_id in project_ids:
        latest = connection.execute(
            sa.select(versions.c.rules)
            .where(
                versions.c.project_id == project_id,
                versions.c.deleted_at.is_(None),
            )
            .order_by(versions.c.version.desc())
            .limit(1)
        ).scalar_one_or_none()
        legacy_roles = [
            {
                "name": rule.get("title", ""),
                "description": rule.get("instruction", ""),
            }
            for rule in (latest or [])
            if isinstance(rule, dict)
        ]
        connection.execute(
            projects.update()
            .where(projects.c.id == project_id)
            .values(analyzer_roles=legacy_roles)
        )

    op.drop_index(
        "ix_project_analysis_rule_versions_active",
        table_name="project_analysis_rule_versions",
    )
    op.drop_index(
        "ix_project_analysis_rule_versions_project_id",
        table_name="project_analysis_rule_versions",
    )
    op.drop_table("project_analysis_rule_versions")
