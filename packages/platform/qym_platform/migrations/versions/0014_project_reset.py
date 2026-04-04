"""Reset platform authorization model to projects.

Revision ID: 0014_project_reset
Revises: 0013_run_soft_delete
Create Date: 2026-04-03
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "0014_project_reset"
down_revision = "0013_run_soft_delete"
branch_labels = None
depends_on = None


def _drop_if_exists(name: str) -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if name in insp.get_table_names():
        op.drop_table(name)


def _drop_column_if_exists(table_name: str, column_name: str, index_name: str | None = None) -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = {col["name"] for col in insp.get_columns(table_name)}
    if column_name not in cols:
        return
    if index_name:
        try:
            op.drop_index(index_name, table_name=table_name)
        except Exception:
            pass
    op.drop_column(table_name, column_name)


def _reset_user_role_enum(bind: sa.engine.Connection) -> None:
    dialect = bind.dialect.name
    if dialect == "postgresql":
        op.execute("ALTER TABLE users ALTER COLUMN role DROP DEFAULT")
        op.execute("ALTER TYPE userrole RENAME TO userrole_old")
        op.execute("CREATE TYPE userrole AS ENUM ('MEMBER', 'ADMIN')")
        op.execute(
            """
            ALTER TABLE users
            ALTER COLUMN role TYPE userrole
            USING (
                CASE
                    WHEN role::text = 'ADMIN' THEN 'ADMIN'
                    ELSE 'MEMBER'
                END
            )::userrole
            """
        )
        op.execute("DROP TYPE userrole_old")
        op.execute("ALTER TABLE users ALTER COLUMN role SET DEFAULT 'MEMBER'")
        return

    op.execute("UPDATE users SET role = 'MEMBER' WHERE role <> 'ADMIN'")


def _ensure_postgres_enums(bind: sa.engine.Connection) -> dict[str, sa.Enum]:
    if bind.dialect.name != "postgresql":
        return {
            "projectrole": sa.Enum("MEMBER", "MANAGER", name="projectrole"),
            "runworkflowstatus": sa.Enum(
                "DRAFT",
                "SUBMITTED",
                "APPROVED",
                "REJECTED",
                "RUNNING",
                "COMPLETED",
                "FAILED",
                "STOPPED",
                "PENDING",
                name="runworkflowstatus",
            ),
            "approvaldecision": sa.Enum("APPROVED", "REJECTED", name="approvaldecision"),
            "correctionstatus": sa.Enum(
                "pending",
                "approved",
                "rejected",
                "superseded",
                "withdrawn",
                name="correctionstatus",
            ),
        }

    op.execute("CREATE TYPE projectrole AS ENUM ('MEMBER', 'MANAGER')")
    op.execute("ALTER TYPE runworkflowstatus ADD VALUE IF NOT EXISTS 'STOPPED'")
    op.execute("ALTER TYPE runworkflowstatus ADD VALUE IF NOT EXISTS 'PENDING'")

    return {
        "projectrole": postgresql.ENUM("MEMBER", "MANAGER", name="projectrole", create_type=False),
        "runworkflowstatus": postgresql.ENUM(
            "DRAFT",
            "SUBMITTED",
            "APPROVED",
            "REJECTED",
            "RUNNING",
            "COMPLETED",
            "FAILED",
            "STOPPED",
            "PENDING",
            name="runworkflowstatus",
            create_type=False,
        ),
        "approvaldecision": postgresql.ENUM(
            "APPROVED",
            "REJECTED",
            name="approvaldecision",
            create_type=False,
        ),
        "correctionstatus": postgresql.ENUM(
            "pending",
            "approved",
            "rejected",
            "superseded",
            "withdrawn",
            name="correctionstatus",
            create_type=False,
        ),
    }


def upgrade() -> None:
    bind = op.get_bind()
    _reset_user_role_enum(bind)
    enums = _ensure_postgres_enums(bind)
    _drop_column_if_exists("users", "team_unit_id", index_name="ix_users_team_unit_id")

    # Destroy project-unsafe runtime data and recreate the affected tables.
    for table_name in [
        "review_corrections",
        "root_cause_revisions",
        "spans",
        "run_events",
        "approvals",
        "run_item_scores",
        "run_items",
        "runs",
        "api_keys",
        "org_unit_closure",
        "org_units",
        "org_closure",
        "org_edges",
    ]:
        _drop_if_exists(table_name)

    op.create_table(
        "projects",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("slug", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by_user_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("slug", name="uq_projects_slug"),
    )
    op.create_index("ix_projects_slug", "projects", ["slug"])
    op.create_index("ix_projects_is_active", "projects", ["is_active"])
    op.create_index("ix_projects_created_by_user_id", "projects", ["created_by_user_id"])

    op.create_table(
        "project_memberships",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("project_id", sa.String(length=36), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("user_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column(
            "role",
            enums["projectrole"],
            nullable=False,
            server_default="MEMBER",
        ),
        sa.Column("added_by_user_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("project_id", "user_id", name="uq_project_membership_project_user"),
    )
    op.create_index("ix_project_memberships_project_id", "project_memberships", ["project_id"])
    op.create_index("ix_project_memberships_user_id", "project_memberships", ["user_id"])
    op.create_index("ix_project_memberships_role", "project_memberships", ["role"])
    op.create_index("ix_project_memberships_project_role", "project_memberships", ["project_id", "role"])

    op.create_table(
        "api_keys",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("user_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("project_id", sa.String(length=36), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("prefix", sa.String(length=16), nullable=False),
        sa.Column("key_hash", sa.LargeBinary(), nullable=False),
        sa.Column("scopes", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_api_keys_user_id", "api_keys", ["user_id"])
    op.create_index("ix_api_keys_project_id", "api_keys", ["project_id"])
    op.create_index("ix_api_keys_prefix", "api_keys", ["prefix"])
    op.create_index("ix_api_key_prefix_active", "api_keys", ["prefix", "revoked_at"])

    op.create_table(
        "runs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("project_id", sa.String(length=36), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("external_run_id", sa.String(length=200), nullable=True),
        sa.Column("created_by_user_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("owner_user_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("task", sa.String(length=200), nullable=False),
        sa.Column("dataset", sa.String(length=200), nullable=False),
        sa.Column("model", sa.String(length=200), nullable=True),
        sa.Column("metrics", sa.JSON(), nullable=False),
        sa.Column("run_metadata", sa.JSON(), nullable=False),
        sa.Column("run_config", sa.JSON(), nullable=False),
        sa.Column(
            "status",
            enums["runworkflowstatus"],
            nullable=False,
            server_default="DRAFT",
        ),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("ended_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.Column("deleted_by_user_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=True),
    )
    op.create_index("ix_runs_project_id", "runs", ["project_id"])
    op.create_index("ix_runs_external_run_id", "runs", ["external_run_id"])
    op.create_index("ix_runs_created_by_user_id", "runs", ["created_by_user_id"])
    op.create_index("ix_runs_owner_user_id", "runs", ["owner_user_id"])
    op.create_index("ix_runs_task", "runs", ["task"])
    op.create_index("ix_runs_dataset", "runs", ["dataset"])
    op.create_index("ix_runs_model", "runs", ["model"])
    op.create_index("ix_runs_status", "runs", ["status"])
    op.create_index("ix_runs_created_at", "runs", ["created_at"])
    op.create_index("ix_runs_deleted_at", "runs", ["deleted_at"])

    op.create_table(
        "run_items",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("run_id", sa.String(length=36), sa.ForeignKey("runs.id"), nullable=False),
        sa.Column("item_id", sa.String(length=200), nullable=False),
        sa.Column("index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("input", sa.JSON(), nullable=False),
        sa.Column("expected", sa.JSON(), nullable=True),
        sa.Column("output", sa.JSON(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("item_metadata", sa.JSON(), nullable=False),
        sa.Column("latency_ms", sa.Float(), nullable=True),
        sa.Column("trace_id", sa.String(length=200), nullable=True),
        sa.Column("trace_url", sa.String(length=2000), nullable=True),
        sa.UniqueConstraint("run_id", "item_id", name="uq_run_item"),
    )
    op.create_index("ix_run_items_run_id", "run_items", ["run_id"])
    op.create_index("ix_run_item_run_index", "run_items", ["run_id", "index"])

    op.create_table(
        "run_item_scores",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("run_id", sa.String(length=36), sa.ForeignKey("runs.id"), nullable=False),
        sa.Column("item_id", sa.String(length=200), nullable=False),
        sa.Column("metric_name", sa.String(length=200), nullable=False),
        sa.Column("score_numeric", sa.Float(), nullable=True),
        sa.Column("score_raw", sa.JSON(), nullable=True),
        sa.Column("meta", sa.JSON(), nullable=False),
        sa.Column("label", sa.String(length=200), nullable=True),
        sa.Column("explanation", sa.Text(), nullable=True),
        sa.UniqueConstraint("run_id", "item_id", "metric_name", name="uq_run_item_metric"),
    )
    op.create_index("ix_run_item_scores_run_id", "run_item_scores", ["run_id"])
    op.create_index("ix_run_item_scores_item_id", "run_item_scores", ["item_id"])
    op.create_index("ix_run_item_scores_metric_name", "run_item_scores", ["metric_name"])

    op.create_table(
        "approvals",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("run_id", sa.String(length=36), sa.ForeignKey("runs.id"), nullable=False),
        sa.Column("submitted_by_user_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("submitted_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("decision_by_user_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("decision_at", sa.DateTime(), nullable=True),
        sa.Column(
            "decision",
            enums["approvaldecision"],
            nullable=True,
        ),
        sa.Column("comment", sa.Text(), nullable=False, server_default=""),
        sa.UniqueConstraint("run_id", name="uq_approvals_run_id"),
    )
    op.create_index("ix_approvals_run_id", "approvals", ["run_id"])

    op.create_table(
        "run_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("run_id", sa.String(length=36), sa.ForeignKey("runs.id"), nullable=False),
        sa.Column("event_id", sa.String(length=36), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("type", sa.String(length=50), nullable=False),
        sa.Column("sent_at", sa.DateTime(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.UniqueConstraint("run_id", "event_id", name="uq_run_event_event_id"),
        sa.UniqueConstraint("run_id", "sequence", name="uq_run_event_sequence"),
    )
    op.create_index("ix_run_events_run_id", "run_events", ["run_id"])

    op.create_table(
        "spans",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("run_id", sa.String(length=36), sa.ForeignKey("runs.id"), nullable=False),
        sa.Column("trace_id", sa.String(length=64), nullable=False),
        sa.Column("span_id", sa.String(length=32), nullable=False),
        sa.Column("parent_span_id", sa.String(length=32), nullable=True),
        sa.Column("name", sa.String(length=500), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False, server_default="INTERNAL"),
        sa.Column("start_time_ns", sa.BigInteger(), nullable=True),
        sa.Column("end_time_ns", sa.BigInteger(), nullable=True),
        sa.Column("duration_ms", sa.Float(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="UNSET"),
        sa.Column("attributes", sa.JSON(), nullable=False),
        sa.Column("events", sa.JSON(), nullable=False),
        sa.Column("links", sa.JSON(), nullable=False),
        sa.UniqueConstraint("run_id", "span_id", name="uq_span"),
    )
    op.create_index("ix_span_run_trace", "spans", ["run_id", "trace_id"])

    op.create_table(
        "root_cause_revisions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("run_id", sa.String(length=36), sa.ForeignKey("runs.id"), nullable=False),
        sa.Column("item_id", sa.String(length=200), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("actor_user_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("actor_source", sa.String(length=20), nullable=False, server_default="human"),
        sa.Column("before_state", sa.JSON(), nullable=False),
        sa.Column("after_state", sa.JSON(), nullable=False),
        sa.Column("backfilled_from_legacy", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("run_id", "item_id", "revision_number", name="uq_root_cause_revision_number"),
    )
    op.create_index("ix_root_cause_revisions_run_item_created", "root_cause_revisions", ["run_id", "item_id", "created_at"])

    op.create_table(
        "review_corrections",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("run_id", sa.String(length=36), sa.ForeignKey("runs.id"), nullable=False),
        sa.Column("item_id", sa.String(length=200), nullable=False),
        sa.Column("task", sa.String(length=200), nullable=False),
        sa.Column("input_snapshot", sa.JSON(), nullable=True),
        sa.Column("expected_snapshot", sa.JSON(), nullable=True),
        sa.Column("output_snapshot", sa.JSON(), nullable=True),
        sa.Column("scores_snapshot", sa.JSON(), nullable=False),
        sa.Column("ai_root_cause", sa.String(length=200), nullable=False),
        sa.Column("ai_root_cause_detail", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("ai_root_cause_note", sa.Text(), nullable=False, server_default=""),
        sa.Column("ai_confidence", sa.Float(), nullable=True),
        sa.Column("ai_solution", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("ai_solution_note", sa.Text(), nullable=False, server_default=""),
        sa.Column("human_root_cause", sa.String(length=200), nullable=False),
        sa.Column("human_root_cause_detail", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("human_root_cause_note", sa.Text(), nullable=False, server_default=""),
        sa.Column("human_solution", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("human_solution_note", sa.Text(), nullable=False, server_default=""),
        sa.Column("corrected_by_user_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("revision_id", sa.Integer(), sa.ForeignKey("root_cause_revisions.id"), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column(
            "status",
            enums["correctionstatus"],
            nullable=False,
            server_default="pending",
        ),
        sa.Column("reviewed_by_user_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        sa.Column("review_comment", sa.Text(), nullable=False, server_default=""),
    )
    op.create_index("ix_review_corrections_task_created", "review_corrections", ["task", "created_at"])
    op.create_index("ix_review_corrections_run_item_active", "review_corrections", ["run_id", "item_id", "is_active"])


def downgrade() -> None:
    raise RuntimeError("0014_project_reset is destructive and cannot be downgraded safely")
