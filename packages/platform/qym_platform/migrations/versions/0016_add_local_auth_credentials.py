"""Add local auth credentials table.

Revision ID: 0016_add_local_auth_credentials
Revises: 0015_add_run_item_attempts
Create Date: 2026-04-08
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0016_add_local_auth_credentials"
down_revision = "0015_add_run_item_attempts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "local_auth_credentials",
        sa.Column("user_id", sa.String(length=36), sa.ForeignKey("users.id"), primary_key=True),
        sa.Column("password_hash", sa.LargeBinary(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("last_login_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("local_auth_credentials")
