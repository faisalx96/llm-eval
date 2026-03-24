"""Add links column to spans table for OTEL span links.

Revision ID: 0012_add_span_links
Revises: 0011_add_spans_table
Create Date: 2026-03-22
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0012_add_span_links"
down_revision = "0011_add_spans_table"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("spans", sa.Column("links", sa.JSON(), server_default="[]"))


def downgrade() -> None:
    op.drop_column("spans", "links")
