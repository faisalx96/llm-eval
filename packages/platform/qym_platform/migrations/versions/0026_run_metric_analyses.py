"""Add cached repeat-analysis curves.

Revision ID: 0026_run_metric_analyses
Revises: 0025_run_metric_specs
Create Date: 2026-07-15
"""

from alembic import op
import sqlalchemy as sa


revision = "0026_run_metric_analyses"
down_revision = "0025_run_metric_specs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "run_metric_analyses",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("metric_name", sa.String(length=200), nullable=False),
        sa.Column("threshold_micros", sa.Integer(), nullable=False),
        sa.Column("method_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("source_signature", sa.String(length=64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "run_id",
            "metric_name",
            "threshold_micros",
            "method_version",
            name="uq_run_metric_analysis_cache",
        ),
    )
    op.create_index("ix_run_metric_analyses_run_id", "run_metric_analyses", ["run_id"])
    op.create_index(
        "ix_run_metric_analyses_lookup",
        "run_metric_analyses",
        ["run_id", "metric_name", "threshold_micros"],
    )


def downgrade() -> None:
    op.drop_index("ix_run_metric_analyses_lookup", table_name="run_metric_analyses")
    op.drop_index("ix_run_metric_analyses_run_id", table_name="run_metric_analyses")
    op.drop_table("run_metric_analyses")
