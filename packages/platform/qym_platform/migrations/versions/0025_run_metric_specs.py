"""Add immutable per-run metric specifications.

Revision ID: 0025_run_metric_specs
Revises: 0024_trace_aggregate_raw_bucket
Create Date: 2026-07-11
"""

from alembic import op
import sqlalchemy as sa


revision = "0025_run_metric_specs"
down_revision = "0024_trace_aggregate_raw_bucket"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "run_metric_specs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("metric_name", sa.String(length=200), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("schema_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("score_type", sa.String(length=30), nullable=False),
        sa.Column(
            "direction", sa.String(length=20), nullable=False, server_default="maximize"
        ),
        sa.Column("pass_threshold", sa.Float(), nullable=True),
        sa.Column(
            "sample_reducer",
            sa.String(length=20),
            nullable=False,
            server_default="mean",
        ),
        sa.Column(
            "run_reducer", sa.String(length=20), nullable=False, server_default="mean"
        ),
        sa.Column("unit", sa.String(length=80), nullable=True),
        sa.Column("precision", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "metric_name", name="uq_run_metric_spec"),
    )
    op.create_index("ix_run_metric_specs_run_id", "run_metric_specs", ["run_id"])
    op.create_index(
        "ix_run_metric_specs_run_position", "run_metric_specs", ["run_id", "position"]
    )


def downgrade() -> None:
    op.drop_index("ix_run_metric_specs_run_position", table_name="run_metric_specs")
    op.drop_index("ix_run_metric_specs_run_id", table_name="run_metric_specs")
    op.drop_table("run_metric_specs")
