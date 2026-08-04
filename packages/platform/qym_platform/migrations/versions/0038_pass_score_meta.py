"""Add per-pass metric meta to repeat runs.

The judge writes one explanation per execution, but run_item_pass_scores
only stored the number and a label — so the UI could not show why pass 2
scored 0.60 next to why pass 4 scored 1.00. Mirrors RunItemScore's
meta/explanation columns at pass granularity.

Revision ID: 0038_pass_score_meta
Revises: 0037_remove_project_desc
Create Date: 2026-07-29
"""

from alembic import op
import sqlalchemy as sa


revision = "0038_pass_score_meta"
down_revision = "0037_remove_project_desc"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Databases migrated before the analyzer-branch merge already ran this
    # change under the retired revision id 0027_pass_score_meta, so both
    # columns may exist.
    inspector = sa.inspect(op.get_bind())
    existing = {c["name"] for c in inspector.get_columns("run_item_pass_scores")}
    if "meta" not in existing:
        op.add_column(
            "run_item_pass_scores",
            sa.Column("meta", sa.JSON(), nullable=True),
        )
    if "explanation" not in existing:
        op.add_column(
            "run_item_pass_scores",
            sa.Column("explanation", sa.Text(), nullable=True),
        )


def downgrade() -> None:
    op.drop_column("run_item_pass_scores", "explanation")
    op.drop_column("run_item_pass_scores", "meta")
