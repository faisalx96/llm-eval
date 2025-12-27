"""Add org units, org unit closure, platform settings, user.team_unit_id, and ADMIN role.

Revision ID: 0002_org_units
Revises: 0001_initial
Create Date: 2025-12-27
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0002_org_units"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add ADMIN to userrole enum (Postgres-specific; SQLite will auto-handle)
    # For SQLite, the enum is stored as VARCHAR and doesn't need explicit alteration.
    # For Postgres, we need to add the new value to the enum type.
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("ALTER TYPE userrole ADD VALUE IF NOT EXISTS 'ADMIN'")

    # Create org_units table
    op.create_table(
        "org_units",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column(
            "type",
            sa.Enum("TEAM", "DEPARTMENT", "SECTOR", name="orgunittype"),
            nullable=False,
        ),
        sa.Column("parent_id", sa.String(length=36), sa.ForeignKey("org_units.id"), nullable=True),
        sa.Column("manager_user_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("name", "type", "parent_id", name="uq_org_unit_name_type_parent"),
    )
    op.create_index("ix_org_units_type", "org_units", ["type"])
    op.create_index("ix_org_units_parent_id", "org_units", ["parent_id"])
    op.create_index("ix_org_units_manager_user_id", "org_units", ["manager_user_id"])

    # Create org_unit_closure table
    op.create_table(
        "org_unit_closure",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("ancestor_id", sa.String(length=36), sa.ForeignKey("org_units.id"), nullable=False),
        sa.Column("descendant_id", sa.String(length=36), sa.ForeignKey("org_units.id"), nullable=False),
        sa.Column("depth", sa.Integer(), nullable=False),
        sa.UniqueConstraint("ancestor_id", "descendant_id", name="uq_org_unit_closure"),
    )
    op.create_index("ix_org_unit_closure_ancestor_id", "org_unit_closure", ["ancestor_id"])
    op.create_index("ix_org_unit_closure_descendant_id", "org_unit_closure", ["descendant_id"])

    # Create platform_settings table
    op.create_table(
        "platform_settings",
        sa.Column("key", sa.String(length=100), primary_key=True),
        sa.Column("value", sa.Text(), nullable=False, server_default=""),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )

    # Add team_unit_id to users table
    op.add_column(
        "users",
        sa.Column("team_unit_id", sa.String(length=36), sa.ForeignKey("org_units.id"), nullable=True),
    )
    op.create_index("ix_users_team_unit_id", "users", ["team_unit_id"])

    # Insert default platform settings
    op.execute(
        "INSERT INTO platform_settings (key, value) VALUES ('gm_vp_approved_only', 'true')"
    )
    op.execute(
        "INSERT INTO platform_settings (key, value) VALUES ('manager_visibility_scope', 'team_only')"
    )


def downgrade() -> None:
    # Remove default settings
    op.execute("DELETE FROM platform_settings WHERE key IN ('gm_vp_approved_only', 'manager_visibility_scope')")

    # Drop team_unit_id from users
    op.drop_index("ix_users_team_unit_id", table_name="users")
    op.drop_column("users", "team_unit_id")

    # Drop platform_settings
    op.drop_table("platform_settings")

    # Drop org_unit_closure
    op.drop_index("ix_org_unit_closure_descendant_id", table_name="org_unit_closure")
    op.drop_index("ix_org_unit_closure_ancestor_id", table_name="org_unit_closure")
    op.drop_table("org_unit_closure")

    # Drop org_units
    op.drop_index("ix_org_units_manager_user_id", table_name="org_units")
    op.drop_index("ix_org_units_parent_id", table_name="org_units")
    op.drop_index("ix_org_units_type", table_name="org_units")
    op.drop_table("org_units")

    # Note: Removing ADMIN from userrole enum is complex in Postgres and typically not done.
    # The enum value will remain but be unused after downgrade.

