"""Durable dashboard outbox, numeric state, summaries and rollups."""

import sqlalchemy as sa
from alembic import op

revision = "0048"
down_revision = "0047"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "dashboard_change_events",
        sa.Column(
            "source_version",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            nullable=False,
            autoincrement=True,
        ),
        sa.Column("event_id", sa.String(length=36), nullable=False),
        sa.Column("project_key", sa.String(length=36), nullable=False),
        sa.Column("partition_key", sa.String(length=36), nullable=False),
        sa.Column("record_key", sa.String(length=260), nullable=False),
        sa.Column("metric_key", sa.String(length=240), nullable=False),
        sa.Column("record_kind", sa.String(length=20), nullable=False),
        sa.Column("pass_number", sa.Integer(), nullable=False),
        sa.Column("operation", sa.String(length=10), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("published_at", sa.DateTime(), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("observed", sa.Integer(), nullable=False),
        sa.Column("terminal", sa.Integer(), nullable=False),
        sa.Column("success", sa.Integer(), nullable=False),
        sa.Column("error", sa.Integer(), nullable=False),
        sa.Column("retry_count", sa.Integer(), nullable=False),
        sa.Column("latency_ms", sa.Float(), nullable=True),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("started_at_ms", sa.Float(), nullable=True),
        sa.Column("is_last", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("source_version"),
        sa.UniqueConstraint("event_id"),
        sqlite_autoincrement=True,
    )
    op.create_index(
        "ix_dashboard_change_events_partition_key",
        "dashboard_change_events",
        ["partition_key"],
        unique=False,
    )
    op.create_index(
        "ix_dashboard_change_events_project_key",
        "dashboard_change_events",
        ["project_key"],
        unique=False,
    )
    op.create_index(
        "ix_dashboard_event_pending_partition",
        "dashboard_change_events",
        ["partition_key", "published_at", "source_version"],
        unique=False,
    )
    op.create_index(
        "ix_dashboard_event_retention",
        "dashboard_change_events",
        ["created_at", "published_at", "source_version"],
        unique=False,
    )
    op.create_table(
        "dashboard_event_causes",
        sa.Column(
            "source_version",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            nullable=False,
        ),
        sa.Column("cause_key", sa.String(length=64), nullable=False),
        sa.PrimaryKeyConstraint("source_version", "cause_key"),
    )
    op.create_table(
        "dashboard_record_state",
        sa.Column("id", sa.Integer(), nullable=False, autoincrement=True),
        sa.Column("project_key", sa.String(length=36), nullable=False),
        sa.Column("run_key", sa.String(length=36), nullable=False),
        sa.Column("record_key", sa.String(length=260), nullable=False),
        sa.Column("metric_key", sa.String(length=240), nullable=False),
        sa.Column("record_kind", sa.String(length=20), nullable=False),
        sa.Column("pass_number", sa.Integer(), nullable=False),
        sa.Column("bucket_key", sa.Integer(), nullable=False),
        sa.Column(
            "applied_source_version",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            nullable=False,
        ),
        sa.Column("present", sa.Boolean(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("observed", sa.Integer(), nullable=False),
        sa.Column("terminal", sa.Integer(), nullable=False),
        sa.Column("success", sa.Integer(), nullable=False),
        sa.Column("error", sa.Integer(), nullable=False),
        sa.Column("retry_count", sa.Integer(), nullable=False),
        sa.Column("latency_ms", sa.Float(), nullable=True),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("started_at_ms", sa.Float(), nullable=True),
        sa.Column("is_last", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_key",
            "record_key",
            "metric_key",
            "record_kind",
            "pass_number",
            name="uq_dashboard_record_identity",
        ),
    )
    op.create_index(
        "ix_dashboard_record_retention",
        "dashboard_record_state",
        ["present", "updated_at", "id"],
        unique=False,
    )
    op.create_index(
        "ix_dashboard_record_bucket",
        "dashboard_record_state",
        ["project_key", "bucket_key", "present", "latency_ms"],
        unique=False,
    )
    op.create_index(
        "ix_dashboard_record_bucket_score",
        "dashboard_record_state",
        ["project_key", "bucket_key", "present", "score"],
        unique=False,
    )
    op.create_index(
        "ix_dashboard_record_latency",
        "dashboard_record_state",
        ["run_key", "record_kind", "present", "latency_ms"],
        unique=False,
    )
    op.create_index(
        "ix_dashboard_record_score",
        "dashboard_record_state",
        ["run_key", "record_kind", "present", "metric_key", "score"],
        unique=False,
    )
    op.create_index(
        "ix_dashboard_record_state_run_key",
        "dashboard_record_state",
        ["run_key"],
        unique=False,
    )
    op.create_table(
        "dashboard_record_causes",
        sa.Column("record_state_id", sa.Integer(), nullable=False),
        sa.Column("cause_key", sa.String(length=64), nullable=False),
        sa.Column("run_key", sa.String(length=36), nullable=False),
        sa.Column("pass_number", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("record_state_id", "cause_key"),
    )
    op.create_index(
        "ix_dashboard_record_causes_run_key",
        "dashboard_record_causes",
        ["run_key"],
        unique=False,
    )
    op.create_table(
        "dashboard_run_dimensions",
        sa.Column("run_key", sa.String(length=36), nullable=False),
        sa.Column("project_key", sa.String(length=36), nullable=False),
        sa.Column("task", sa.String(length=200), nullable=False),
        sa.Column("model", sa.String(length=240), nullable=False),
        sa.Column("dataset", sa.String(length=400), nullable=False),
        sa.Column("version", sa.String(length=400), nullable=False),
        sa.Column("owner", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("timestamp", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("present", sa.Boolean(), nullable=False),
        sa.Column("descriptor", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("run_key"),
    )
    op.create_index(
        "ix_dashboard_run_dimensions_created_at",
        "dashboard_run_dimensions",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        "ix_dashboard_run_dimensions_dataset",
        "dashboard_run_dimensions",
        ["dataset"],
        unique=False,
    )
    op.create_index(
        "ix_dashboard_run_dimensions_model",
        "dashboard_run_dimensions",
        ["model"],
        unique=False,
    )
    op.create_index(
        "ix_dashboard_run_dimensions_owner",
        "dashboard_run_dimensions",
        ["owner"],
        unique=False,
    )
    op.create_index(
        "ix_dashboard_run_dimensions_present",
        "dashboard_run_dimensions",
        ["present"],
        unique=False,
    )
    op.create_index(
        "ix_dashboard_run_dimensions_project_key",
        "dashboard_run_dimensions",
        ["project_key"],
        unique=False,
    )
    op.create_index(
        "ix_dashboard_run_dimensions_status",
        "dashboard_run_dimensions",
        ["status"],
        unique=False,
    )
    op.create_index(
        "ix_dashboard_run_dimensions_task",
        "dashboard_run_dimensions",
        ["task"],
        unique=False,
    )
    op.create_index(
        "ix_dashboard_run_dimensions_timestamp",
        "dashboard_run_dimensions",
        ["timestamp"],
        unique=False,
    )
    op.create_index(
        "ix_dashboard_run_dimensions_version",
        "dashboard_run_dimensions",
        ["version"],
        unique=False,
    )
    op.create_table(
        "dashboard_run_summaries",
        sa.Column(
            "projection_revision",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            nullable=False,
        ),
        sa.Column("run_key", sa.String(length=36), nullable=False),
        sa.Column("project_key", sa.String(length=36), nullable=False),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.Column("median_latency_ms", sa.Float(), nullable=False),
        sa.Column("avg_latency_ms", sa.Float(), nullable=False),
        sa.Column("success_rate", sa.Float(), nullable=False),
        sa.Column("completed_success_rate", sa.Float(), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.Column("terminal_count", sa.Integer(), nullable=False),
        sa.Column("success_count", sa.Integer(), nullable=False),
        sa.Column("error_count", sa.Integer(), nullable=False),
        sa.Column("retry_sum", sa.Integer(), nullable=False),
        sa.Column("latency_count", sa.Integer(), nullable=False),
        sa.Column("latency_sum", sa.Float(), nullable=False),
        sa.Column("latency_sum_squares", sa.Float(), nullable=False),
        sa.Column("score_count", sa.Integer(), nullable=False),
        sa.Column("score_sum", sa.Float(), nullable=False),
        sa.Column("score_sum_squares", sa.Float(), nullable=False),
        sa.Column("latency_min", sa.Float(), nullable=True),
        sa.Column("latency_max", sa.Float(), nullable=True),
        sa.Column("score_min", sa.Float(), nullable=True),
        sa.Column("score_max", sa.Float(), nullable=True),
        sa.Column("extrema_state", sa.String(length=20), nullable=False),
        sa.Column(
            "extrema_verified_version",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            nullable=False,
        ),
        sa.Column(
            "dirty_since_version",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            nullable=True,
        ),
        sa.Column(
            "applied_source_version",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("run_key"),
    )
    op.create_index(
        "ix_dashboard_run_summaries_project_key",
        "dashboard_run_summaries",
        ["project_key"],
        unique=False,
    )
    op.create_table(
        "dashboard_bucket_rollups",
        sa.Column("project_key", sa.String(length=36), nullable=False),
        sa.Column("slice_key", sa.String(length=260), nullable=False),
        sa.Column("bucket_key", sa.Integer(), nullable=False),
        sa.Column("granularity", sa.String(length=8), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.Column("terminal_count", sa.Integer(), nullable=False),
        sa.Column("success_count", sa.Integer(), nullable=False),
        sa.Column("error_count", sa.Integer(), nullable=False),
        sa.Column("retry_sum", sa.Integer(), nullable=False),
        sa.Column("latency_count", sa.Integer(), nullable=False),
        sa.Column("latency_sum", sa.Float(), nullable=False),
        sa.Column("latency_sum_squares", sa.Float(), nullable=False),
        sa.Column("score_count", sa.Integer(), nullable=False),
        sa.Column("score_sum", sa.Float(), nullable=False),
        sa.Column("score_sum_squares", sa.Float(), nullable=False),
        sa.Column("latency_min", sa.Float(), nullable=True),
        sa.Column("latency_max", sa.Float(), nullable=True),
        sa.Column("score_min", sa.Float(), nullable=True),
        sa.Column("score_max", sa.Float(), nullable=True),
        sa.Column("extrema_state", sa.String(length=20), nullable=False),
        sa.Column(
            "extrema_verified_version",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            nullable=False,
        ),
        sa.Column(
            "dirty_since_version",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            nullable=True,
        ),
        sa.Column(
            "applied_source_version",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint(
            "project_key", "slice_key", "bucket_key", "granularity"
        ),
    )
    op.create_table(
        "dashboard_histograms",
        sa.Column("project_key", sa.String(length=36), nullable=False),
        sa.Column("slice_key", sa.String(length=260), nullable=False),
        sa.Column("bucket_key", sa.Integer(), nullable=False),
        sa.Column("granularity", sa.String(length=8), nullable=False),
        sa.Column("definition_version", sa.Integer(), nullable=False),
        sa.Column("value_kind", sa.String(length=12), nullable=False),
        sa.Column("bucket_index", sa.Integer(), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint(
            "project_key",
            "slice_key",
            "bucket_key",
            "granularity",
            "definition_version",
            "value_kind",
            "bucket_index",
        ),
    )
    op.create_table(
        "dashboard_partition_state",
        sa.Column(
            "backfill_source_version",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            nullable=False,
        ),
        sa.Column("partition_key", sa.String(length=36), nullable=False),
        sa.Column("project_key", sa.String(length=36), nullable=False),
        sa.Column(
            "last_enqueued_version",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            nullable=False,
        ),
        sa.Column(
            "last_applied_version",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            nullable=False,
        ),
        sa.Column("oldest_pending_event", sa.DateTime(), nullable=True),
        sa.Column("queue_state", sa.String(length=20), nullable=False),
        sa.Column("lease_owner", sa.String(length=36), nullable=True),
        sa.Column("lease_until", sa.DateTime(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False),
        sa.Column("backfill_kind", sa.String(length=20), nullable=False),
        sa.Column("backfill_cursor", sa.Integer(), nullable=False),
        sa.Column("backfill_complete", sa.Boolean(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("partition_key"),
    )
    op.create_index(
        "ix_dashboard_partition_state_project_key",
        "dashboard_partition_state",
        ["project_key"],
        unique=False,
    )
    op.create_index(
        "ix_dashboard_partition_state_queue_state",
        "dashboard_partition_state",
        ["queue_state"],
        unique=False,
    )
    op.create_table(
        "dashboard_dead_letters",
        sa.Column("id", sa.Integer(), nullable=False, autoincrement=True),
        sa.Column("event_id", sa.String(length=36), nullable=False),
        sa.Column("project_key", sa.String(length=36), nullable=False),
        sa.Column("partition_key", sa.String(length=36), nullable=False),
        sa.Column(
            "source_version",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            nullable=False,
        ),
        sa.Column("error", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_id"),
    )
    op.create_index(
        "ix_dashboard_dead_letters_partition_key",
        "dashboard_dead_letters",
        ["partition_key"],
        unique=False,
    )
    op.create_index(
        "ix_dashboard_dead_letters_project_key",
        "dashboard_dead_letters",
        ["project_key"],
        unique=False,
    )

    # Seed only stable source identifiers. Numerical source history is handled
    # by the resumable worker after the migration transaction commits.
    source = sa.table("runs", sa.column("id"), sa.column("project_id"))
    fields = [
        "partition_key",
        "project_key",
        "last_enqueued_version",
        "last_applied_version",
        "oldest_pending_event",
        "queue_state",
        "retry_count",
        "backfill_kind",
        "backfill_cursor",
        "backfill_complete",
        "updated_at",
        "backfill_source_version",
    ]
    target = sa.table(
        "dashboard_partition_state", *(sa.column(name) for name in fields)
    )
    op.execute(
        target.insert().from_select(
            fields,
            sa.select(
                source.c.id,
                source.c.project_id,
                sa.literal(0),
                sa.literal(0),
                sa.func.current_timestamp(),
                sa.literal("backfill"),
                sa.literal(0),
                sa.literal("item"),
                sa.literal(0),
                sa.false(),
                sa.func.current_timestamp(),
                sa.literal(0),
            ),
        )
    )


def downgrade():
    op.drop_table("dashboard_dead_letters")
    op.drop_table("dashboard_partition_state")
    op.drop_table("dashboard_histograms")
    op.drop_table("dashboard_bucket_rollups")
    op.drop_table("dashboard_run_summaries")
    op.drop_table("dashboard_run_dimensions")
    op.drop_table("dashboard_record_causes")
    op.drop_table("dashboard_record_state")
    op.drop_table("dashboard_event_causes")
    op.drop_table("dashboard_change_events")
