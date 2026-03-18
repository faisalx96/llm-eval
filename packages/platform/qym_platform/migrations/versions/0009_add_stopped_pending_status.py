"""Add STOPPED and PENDING values to runworkflowstatus enum.

Revision ID: 0009_add_stopped_pending_status
Revises: 0008_run_created_at_index
Create Date: 2026-03-18
"""

from __future__ import annotations

from alembic import op

revision = "0009_add_stopped_pending_status"
down_revision = "0008_run_created_at_index"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE runworkflowstatus ADD VALUE IF NOT EXISTS 'STOPPED'")
    op.execute("ALTER TYPE runworkflowstatus ADD VALUE IF NOT EXISTS 'PENDING'")


def downgrade() -> None:
    # PostgreSQL does not support removing values from an enum type.
    # These values are harmless to leave in place.
    pass
