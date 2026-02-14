"""Initial platform schema.

Revision ID: 0001_initial
Revises:
Create Date: 2025-12-26
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("title", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("role", sa.Enum("EMPLOYEE", "MANAGER", "GM", "VP", name="userrole"), nullable=False, server_default="EMPLOYEE"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )
    op.create_index("ix_users_email", "users", ["email"])

    op.create_table(
        "user_identities",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("subject", sa.String(length=512), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=True),
        sa.Column("raw_claims", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.UniqueConstraint("provider", "subject", name="uq_identity_provider_subject"),
    )
    op.create_index("ix_user_identities_user_id", "user_identities", ["user_id"])

    op.create_table(
        "org_edges",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("manager_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("employee_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("effective_from", sa.DateTime(), nullable=False),
        sa.Column("effective_to", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("manager_id", "employee_id", "effective_from", name="uq_org_edge"),
    )
    op.create_index("ix_org_edges_manager_id", "org_edges", ["manager_id"])
    op.create_index("ix_org_edges_employee_id", "org_edges", ["employee_id"])

    op.create_table(
        "org_closure",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("ancestor_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("descendant_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("depth", sa.Integer(), nullable=False),
        sa.UniqueConstraint("ancestor_id", "descendant_id", name="uq_org_closure"),
    )
    op.create_index("ix_org_closure_ancestor_id", "org_closure", ["ancestor_id"])
    op.create_index("ix_org_closure_descendant_id", "org_closure", ["descendant_id"])

    op.create_table(
        "api_keys",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("user_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("prefix", sa.String(length=16), nullable=False),
        sa.Column("key_hash", sa.LargeBinary(), nullable=False),
        sa.Column("scopes", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_api_keys_user_id", "api_keys", ["user_id"])
    op.create_index("ix_api_keys_prefix", "api_keys", ["prefix"])
    op.create_index("ix_api_key_prefix_active", "api_keys", ["prefix", "revoked_at"])

    op.create_table(
        "runs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("external_run_id", sa.String(length=200), nullable=True),
        sa.Column("created_by_user_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("owner_user_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("task", sa.String(length=200), nullable=False),
        sa.Column("dataset", sa.String(length=200), nullable=False),
        sa.Column("model", sa.String(length=200), nullable=True),
        sa.Column("metrics", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("run_metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("run_config", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column(
            "status",
            sa.Enum(
                "DRAFT",
                "SUBMITTED",
                "APPROVED",
                "REJECTED",
                "RUNNING",
                "COMPLETED",
                "FAILED",
                name="runworkflowstatus",
            ),
            nullable=False,
            server_default="DRAFT",
        ),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("ended_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_runs_external_run_id", "runs", ["external_run_id"])
    op.create_index("ix_runs_created_by_user_id", "runs", ["created_by_user_id"])
    op.create_index("ix_runs_owner_user_id", "runs", ["owner_user_id"])
    op.create_index("ix_runs_task", "runs", ["task"])
    op.create_index("ix_runs_dataset", "runs", ["dataset"])
    op.create_index("ix_runs_model", "runs", ["model"])
    op.create_index("ix_runs_status", "runs", ["status"])

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
        sa.Column("item_metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
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
        sa.Column("meta", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
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
        sa.Column("submitted_at", sa.DateTime(), nullable=False),
        sa.Column("decision_by_user_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("decision_at", sa.DateTime(), nullable=True),
        sa.Column("decision", sa.Enum("APPROVED", "REJECTED", name="approvaldecision"), nullable=True),
        sa.Column("comment", sa.Text(), nullable=False, server_default=""),
        sa.UniqueConstraint("run_id", name="uq_approvals_run_id"),
    )
    op.create_index("ix_approvals_run_id", "approvals", ["run_id"])

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("actor_user_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("action", sa.String(length=200), nullable=False),
        sa.Column("entity_type", sa.String(length=200), nullable=False),
        sa.Column("entity_id", sa.String(length=200), nullable=False),
        sa.Column("before", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("after", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_audit_logs_actor_user_id", "audit_logs", ["actor_user_id"])
    op.create_index("ix_audit_logs_action", "audit_logs", ["action"])
    op.create_index("ix_audit_logs_entity_type", "audit_logs", ["entity_type"])
    op.create_index("ix_audit_logs_entity_id", "audit_logs", ["entity_id"])

    op.create_table(
        "run_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("run_id", sa.String(length=36), sa.ForeignKey("runs.id"), nullable=False),
        sa.Column("event_id", sa.String(length=36), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("type", sa.String(length=50), nullable=False),
        sa.Column("sent_at", sa.DateTime(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.UniqueConstraint("run_id", "event_id", name="uq_run_event_event_id"),
        sa.UniqueConstraint("run_id", "sequence", name="uq_run_event_sequence"),
    )
    op.create_index("ix_run_events_run_id", "run_events", ["run_id"])
    op.create_index("ix_run_events_event_id", "run_events", ["event_id"])


def downgrade() -> None:
    op.drop_index("ix_run_events_event_id", table_name="run_events")
    op.drop_index("ix_run_events_run_id", table_name="run_events")
    op.drop_table("run_events")

    op.drop_index("ix_audit_logs_entity_id", table_name="audit_logs")
    op.drop_index("ix_audit_logs_entity_type", table_name="audit_logs")
    op.drop_index("ix_audit_logs_action", table_name="audit_logs")
    op.drop_index("ix_audit_logs_actor_user_id", table_name="audit_logs")
    op.drop_table("audit_logs")

    op.drop_index("ix_approvals_run_id", table_name="approvals")
    op.drop_table("approvals")

    op.drop_index("ix_run_item_scores_metric_name", table_name="run_item_scores")
    op.drop_index("ix_run_item_scores_item_id", table_name="run_item_scores")
    op.drop_index("ix_run_item_scores_run_id", table_name="run_item_scores")
    op.drop_table("run_item_scores")

    op.drop_index("ix_run_item_run_index", table_name="run_items")
    op.drop_index("ix_run_items_run_id", table_name="run_items")
    op.drop_table("run_items")

    op.drop_index("ix_runs_status", table_name="runs")
    op.drop_index("ix_runs_model", table_name="runs")
    op.drop_index("ix_runs_dataset", table_name="runs")
    op.drop_index("ix_runs_task", table_name="runs")
    op.drop_index("ix_runs_owner_user_id", table_name="runs")
    op.drop_index("ix_runs_created_by_user_id", table_name="runs")
    op.drop_index("ix_runs_external_run_id", table_name="runs")
    op.drop_table("runs")

    op.drop_index("ix_api_key_prefix_active", table_name="api_keys")
    op.drop_index("ix_api_keys_prefix", table_name="api_keys")
    op.drop_index("ix_api_keys_user_id", table_name="api_keys")
    op.drop_table("api_keys")

    op.drop_index("ix_org_closure_descendant_id", table_name="org_closure")
    op.drop_index("ix_org_closure_ancestor_id", table_name="org_closure")
    op.drop_table("org_closure")

    op.drop_index("ix_org_edges_employee_id", table_name="org_edges")
    op.drop_index("ix_org_edges_manager_id", table_name="org_edges")
    op.drop_table("org_edges")

    op.drop_index("ix_user_identities_user_id", table_name="user_identities")
    op.drop_table("user_identities")

    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")

    # Enums may need explicit drop in Postgres; Alembic will generally handle on drop_table order.


