"""Add durable incremental trace contributions and numeric summaries.

Revision ID: 0047
Revises: 0046
"""

from alembic import op
import sqlalchemy as sa

revision = "0047"
down_revision = "0046"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "run_trace_summaries",
        sa.Column(
            "run_id",
            sa.String(36),
            sa.ForeignKey("runs.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("totals", sa.JSON(), nullable=False),
    )
    op.create_table(
        "run_trace_contributions",
        sa.Column(
            "run_id",
            sa.String(36),
            sa.ForeignKey("runs.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("item_id", sa.String(200), primary_key=True),
        sa.Column("item_order", sa.BigInteger(), nullable=False),
        sa.Column("trace_id", sa.String(200), nullable=True),
        sa.Column("included", sa.Boolean(), nullable=False),
        sa.Column("bucket", sa.JSON(), nullable=False),
    )
    op.create_index(
        "ix_trace_contribution_run_trace",
        "run_trace_contributions",
        ["run_id", "trace_id"],
    )
    op.create_table(
        "run_trace_named_contributions",
        sa.Column(
            "run_id",
            sa.String(36),
            sa.ForeignKey("runs.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("item_id", sa.String(200), primary_key=True),
        sa.Column("name", sa.String(500), primary_key=True),
        sa.Column("item_order", sa.BigInteger(), nullable=False),
        sa.Column("name_position", sa.Integer(), nullable=False),
    )
    op.create_index(
        "ix_trace_named_first",
        "run_trace_named_contributions",
        ["run_id", "name", "item_order", "name_position"],
    )
    # The normal refresh locates only items pointing at changed traces.
    op.create_index("ix_run_item_run_trace", "run_items", ["run_id", "trace_id"])


def downgrade():
    op.drop_index("ix_run_item_run_trace", table_name="run_items")
    op.drop_table("run_trace_named_contributions")
    op.drop_table("run_trace_contributions")
    op.drop_table("run_trace_summaries")
