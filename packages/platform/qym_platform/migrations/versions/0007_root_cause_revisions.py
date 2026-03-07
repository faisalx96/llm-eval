"""Add root-cause revisions and active review candidate lifecycle.

Revision ID: 0007_root_cause_revisions
Revises: 0006_correction_approval
Create Date: 2026-03-06
"""

from __future__ import annotations

from collections import defaultdict

from alembic import op
import sqlalchemy as sa


revision = "0007_root_cause_revisions"
down_revision = "0006_correction_approval"
branch_labels = None
depends_on = None


def _upgrade_correction_status_enum() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.execute(
        """
        ALTER TABLE review_corrections
        ALTER COLUMN status DROP DEFAULT
        """
    )
    op.execute(
        "ALTER TYPE correctionstatus RENAME TO correctionstatus_old"
    )
    new_enum = sa.Enum(
        "pending",
        "approved",
        "rejected",
        "superseded",
        "withdrawn",
        name="correctionstatus",
    )
    new_enum.create(bind, checkfirst=True)
    op.execute(
        """
        ALTER TABLE review_corrections
        ALTER COLUMN status TYPE correctionstatus
        USING status::text::correctionstatus
        """
    )
    op.execute(
        """
        ALTER TABLE review_corrections
        ALTER COLUMN status SET DEFAULT 'pending'::correctionstatus
        """
    )
    sa.Enum(name="correctionstatus_old").drop(bind, checkfirst=True)


def _downgrade_correction_status_enum() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.execute(
        """
        ALTER TABLE review_corrections
        ALTER COLUMN status DROP DEFAULT
        """
    )
    op.execute(
        "ALTER TYPE correctionstatus RENAME TO correctionstatus_new"
    )
    old_enum = sa.Enum(
        "pending",
        "approved",
        "rejected",
        name="correctionstatus",
    )
    old_enum.create(bind, checkfirst=True)
    op.execute(
        """
        ALTER TABLE review_corrections
        ALTER COLUMN status TYPE correctionstatus
        USING (
          CASE
            WHEN status::text IN ('superseded', 'withdrawn') THEN 'rejected'
            ELSE status::text
          END
        )::correctionstatus
        """
    )
    op.execute(
        """
        ALTER TABLE review_corrections
        ALTER COLUMN status SET DEFAULT 'pending'::correctionstatus
        """
    )
    sa.Enum(name="correctionstatus_new").drop(bind, checkfirst=True)


def upgrade() -> None:
    _upgrade_correction_status_enum()

    op.create_table(
        "root_cause_revisions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("item_id", sa.String(length=200), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("actor_user_id", sa.String(length=36), nullable=True),
        sa.Column("actor_source", sa.String(length=20), nullable=False, server_default="human"),
        sa.Column("before_state", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("after_state", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("backfilled_from_legacy", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "item_id", "revision_number", name="uq_root_cause_revision_number"),
    )
    op.create_index(
        "ix_root_cause_revisions_run_item_created",
        "root_cause_revisions",
        ["run_id", "item_id", "created_at"],
    )

    op.add_column(
        "review_corrections",
        sa.Column("revision_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "review_corrections",
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.create_index("ix_review_corrections_is_active", "review_corrections", ["is_active"])
    op.create_index(
        "ix_review_corrections_run_item_active",
        "review_corrections",
        ["run_id", "item_id", "is_active"],
    )
    op.create_foreign_key(
        "fk_review_corrections_revision",
        "review_corrections",
        "root_cause_revisions",
        ["revision_id"],
        ["id"],
    )

    bind = op.get_bind()
    meta = sa.MetaData()
    review_corrections = sa.Table("review_corrections", meta, autoload_with=bind)
    root_cause_revisions = sa.Table("root_cause_revisions", meta, autoload_with=bind)

    rows = list(
        bind.execute(
            sa.select(
                review_corrections.c.id,
                review_corrections.c.run_id,
                review_corrections.c.item_id,
                review_corrections.c.corrected_by_user_id,
                review_corrections.c.ai_root_cause,
                review_corrections.c.ai_root_cause_detail,
                review_corrections.c.ai_root_cause_note,
                review_corrections.c.ai_confidence,
                review_corrections.c.ai_solution,
                review_corrections.c.ai_solution_note,
                review_corrections.c.human_root_cause,
                review_corrections.c.human_root_cause_detail,
                review_corrections.c.human_root_cause_note,
                review_corrections.c.human_solution,
                review_corrections.c.human_solution_note,
                review_corrections.c.status,
                review_corrections.c.created_at,
            )
            .order_by(
                review_corrections.c.run_id.asc(),
                review_corrections.c.item_id.asc(),
                review_corrections.c.created_at.asc(),
                review_corrections.c.id.asc(),
            )
        ).mappings()
    )

    latest_id_by_pair: dict[tuple[str, str], int] = {}
    for row in rows:
        latest_id_by_pair[(row["run_id"], row["item_id"])] = row["id"]

    revision_counts: dict[tuple[str, str], int] = defaultdict(int)
    for row in rows:
        pair = (row["run_id"], row["item_id"])
        revision_counts[pair] += 1

        ai_root_cause = (row["ai_root_cause"] or "").strip()
        ai_is_unanalyzed = ai_root_cause.lower() == "unanalyzed"
        before_state = {
            "root_cause": "" if ai_is_unanalyzed else ai_root_cause,
            "root_cause_detail": "" if ai_is_unanalyzed else (row["ai_root_cause_detail"] or ""),
            "root_cause_note": "" if ai_is_unanalyzed else (row["ai_root_cause_note"] or ""),
            "root_cause_source": "ai" if (ai_root_cause and not ai_is_unanalyzed) else "",
            "root_cause_confidence": None if ai_is_unanalyzed else row["ai_confidence"],
            "solution": "" if ai_is_unanalyzed else (row["ai_solution"] or ""),
            "solution_note": "" if ai_is_unanalyzed else (row["ai_solution_note"] or ""),
            "solution_source": "ai" if (row["ai_solution"] or "") and not ai_is_unanalyzed else "",
        }
        after_state = {
            "root_cause": row["human_root_cause"] or "",
            "root_cause_detail": row["human_root_cause_detail"] or "",
            "root_cause_note": row["human_root_cause_note"] or "",
            "root_cause_source": "human" if (row["human_root_cause"] or "") else "",
            "root_cause_confidence": None,
            "solution": row["human_solution"] or "",
            "solution_note": row["human_solution_note"] or "",
            "solution_source": "human" if (row["human_solution"] or "") else "",
        }

        insert_result = bind.execute(
            root_cause_revisions.insert().values(
                run_id=row["run_id"],
                item_id=row["item_id"],
                revision_number=revision_counts[pair],
                actor_user_id=row["corrected_by_user_id"],
                actor_source="human",
                before_state=before_state,
                after_state=after_state,
                backfilled_from_legacy=True,
                created_at=row["created_at"],
            )
        )
        revision_id = insert_result.inserted_primary_key[0]

        bind.execute(
            review_corrections.update()
            .where(review_corrections.c.id == row["id"])
            .values(
                revision_id=revision_id,
                is_active=(row["id"] == latest_id_by_pair[pair]),
            )
        )


def downgrade() -> None:
    op.drop_constraint("fk_review_corrections_revision", "review_corrections", type_="foreignkey")
    op.drop_index("ix_review_corrections_run_item_active", table_name="review_corrections")
    op.drop_index("ix_review_corrections_is_active", table_name="review_corrections")
    op.drop_column("review_corrections", "is_active")
    op.drop_column("review_corrections", "revision_id")

    op.drop_index("ix_root_cause_revisions_run_item_created", table_name="root_cause_revisions")
    op.drop_table("root_cause_revisions")

    _downgrade_correction_status_enum()
