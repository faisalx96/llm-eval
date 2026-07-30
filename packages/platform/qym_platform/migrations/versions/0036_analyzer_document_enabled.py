"""Add project-level analyzer document inclusion.

Revision ID: 0036_document_enabled
Revises: 0035_rule_merge_lineage
Create Date: 2026-07-29
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0036_document_enabled"
down_revision = "0035_rule_merge_lineage"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "analyzer_documents",
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
    )


def downgrade() -> None:
    op.drop_column("analyzer_documents", "enabled")
