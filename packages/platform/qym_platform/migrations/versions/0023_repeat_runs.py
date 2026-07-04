"""Repeat runs (samples=k): pass-aware storage.

- ``runs.samples`` — how many passes the run evaluates per item (1 = classic).
- ``run_item_attempts.pass_number`` + ``output`` — attempts now belong to a
  pass; the final attempt of each pass stores that pass's output for the
  per-pass drill-down. Unique key widens to (run, item, pass, attempt).
- New ``run_item_pass_scores`` — one numeric score per
  (run, item, metric, pass). ``run_item_scores`` intentionally keeps its
  one-row-per-(run, item, metric) contract and stores the reduced mean, so
  every existing view and query keeps working.

Revision ID: 0023_repeat_runs
Revises: 0022_dataset_version_names
Create Date: 2026-07-04
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0023_repeat_runs"
down_revision = "0022_dataset_version_names"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "runs",
        sa.Column("samples", sa.Integer(), nullable=False, server_default="1"),
    )

    with op.batch_alter_table("run_item_attempts") as batch:
        batch.add_column(
            sa.Column("pass_number", sa.Integer(), nullable=False, server_default="1")
        )
        batch.add_column(sa.Column("output", sa.JSON(), nullable=True))
        batch.drop_constraint("uq_run_item_attempt", type_="unique")
        batch.create_unique_constraint(
            "uq_run_item_pass_attempt",
            ["run_id", "item_id", "pass_number", "attempt_number"],
        )

    op.create_table(
        "run_item_pass_scores",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "run_id", sa.String(length=36), sa.ForeignKey("runs.id"), nullable=False
        ),
        sa.Column("item_id", sa.String(length=200), nullable=False),
        sa.Column("metric_name", sa.String(length=200), nullable=False),
        sa.Column("pass_number", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("score_numeric", sa.Float(), nullable=True),
        sa.Column("label", sa.String(length=200), nullable=True),
        sa.UniqueConstraint(
            "run_id",
            "item_id",
            "metric_name",
            "pass_number",
            name="uq_run_item_metric_pass",
        ),
    )
    op.create_index(
        "ix_run_item_pass_scores_run_metric",
        "run_item_pass_scores",
        ["run_id", "metric_name"],
    )
    op.create_index(
        "ix_run_item_pass_scores_run", "run_item_pass_scores", ["run_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_run_item_pass_scores_run", table_name="run_item_pass_scores")
    op.drop_index(
        "ix_run_item_pass_scores_run_metric", table_name="run_item_pass_scores"
    )
    op.drop_table("run_item_pass_scores")

    with op.batch_alter_table("run_item_attempts") as batch:
        batch.drop_constraint("uq_run_item_pass_attempt", type_="unique")
        batch.create_unique_constraint(
            "uq_run_item_attempt", ["run_id", "item_id", "attempt_number"]
        )
        batch.drop_column("output")
        batch.drop_column("pass_number")

    op.drop_column("runs", "samples")
