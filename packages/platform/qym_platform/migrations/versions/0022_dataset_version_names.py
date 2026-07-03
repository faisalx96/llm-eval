"""Dataset version names: vN identifiers stay immutable, names are free text.

Adds ``dataset_versions.name`` for the optional human-friendly label. Version
identifiers are now always sequential ``vN`` strings, so existing rows whose
``version`` is free text (e.g. "test") move that text into ``name`` and get
the next available ``vN`` for their dataset.

Revision ID: 0022_dataset_version_names
Revises: 0021_project_llm_connections
Create Date: 2026-07-03
"""

from __future__ import annotations

import re

from alembic import op
import sqlalchemy as sa


revision = "0022_dataset_version_names"
down_revision = "0021_project_llm_connections"
branch_labels = None
depends_on = None

_VN = re.compile(r"v(\d+)\Z")


def upgrade() -> None:
    op.add_column(
        "dataset_versions",
        sa.Column("name", sa.String(length=200), nullable=False, server_default=""),
    )

    conn = op.get_bind()
    rows = conn.execute(
        sa.text(
            "SELECT id, dataset_id, version FROM dataset_versions ORDER BY dataset_id, created_at, id"
        )
    ).fetchall()

    highest: dict[str, int] = {}
    for _, dataset_id, version in rows:
        match = _VN.fullmatch(str(version or ""))
        if match:
            highest[dataset_id] = max(highest.get(dataset_id, 0), int(match.group(1)))

    for row_id, dataset_id, version in rows:
        if _VN.fullmatch(str(version or "")):
            continue
        next_num = highest.get(dataset_id, 0) + 1
        highest[dataset_id] = next_num
        conn.execute(
            sa.text(
                "UPDATE dataset_versions SET name = :name, version = :version WHERE id = :id"
            ),
            {"name": str(version or ""), "version": f"v{next_num}", "id": row_id},
        )


def downgrade() -> None:
    # Rows renamed to vN keep that identifier; the free-text label is dropped.
    with op.batch_alter_table("dataset_versions") as batch:
        batch.drop_column("name")
