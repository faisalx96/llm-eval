"""Remove unapproved diagnosis labels from migration-created catalogs.

Revision ID: 0044
Revises: 0043
"""

from __future__ import annotations

import hashlib
import json
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from alembic import op
import sqlalchemy as sa

revision = "0044"
down_revision = "0043"
branch_labels = None
depends_on = None


DEFAULT_CATEGORIES = (
    "Hallucination",
    "Incomplete Answer",
    "Wrong Format",
    "Context Missing",
    "Reasoning Error",
    "Tool Use Error",
    "Instruction Following",
    "Knowledge Gap",
    "Dataset Issue",
)


def _json(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (TypeError, ValueError):
            return value
    return None


def _label(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()[:200]


def _labels(value: Any) -> list[str]:
    raw = _json(value)
    if isinstance(raw, dict):
        raw = list(raw)
    if not isinstance(raw, (list, tuple, set)):
        raw = [raw]
    result: list[str] = []
    seen: set[str] = set()
    for entry in raw:
        label = _label(entry)
        key = label.casefold()
        if label and key not in seen:
            seen.add(key)
            result.append(label)
    return result


def _hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
    ).hexdigest()


def _approved_labels(bind: sa.Connection, project_id: str) -> list[str]:
    rows = bind.execute(
        sa.text("""
            SELECT rc.human_root_cause, rc.human_root_causes,
                   rc.ai_root_cause, rc.ai_root_causes
            FROM review_corrections rc
            JOIN runs r ON r.id = rc.run_id
            WHERE r.project_id = :project_id
              AND rc.status = 'approved'
              AND rc.is_active = TRUE
            ORDER BY rc.created_at ASC, rc.id ASC
            """),
        {"project_id": project_id},
    )
    labels: list[str] = []
    seen: set[str] = set()
    for human_singular, human_plural, ai_singular, ai_plural in rows:
        values = (human_plural or human_singular) or (ai_plural or ai_singular)
        for label in _labels(values):
            if label.casefold() in seen:
                continue
            seen.add(label.casefold())
            labels.append(label)
    return labels


def _filter_map(value: Any, active_by_fold: dict[str, str]) -> dict[str, Any]:
    raw = _json(value)
    if not isinstance(raw, dict):
        return {}
    result: dict[str, Any] = {}
    for raw_label, raw_value in raw.items():
        canonical = active_by_fold.get(_label(raw_label).casefold())
        if canonical is not None:
            result[canonical] = raw_value
    return result


def upgrade() -> None:
    bind = op.get_bind()
    catalogs = sa.Table(
        "project_analysis_category_catalog_versions",
        sa.MetaData(),
        autoload_with=bind,
    )
    rows = bind.execute(
        sa.select(
            catalogs.c.id,
            catalogs.c.project_id,
            catalogs.c.categories,
            catalogs.c.category_entries,
            catalogs.c.category_details_map,
            catalogs.c.category_taxonomy,
            catalogs.c.max_root_cause_categories,
        ).where(
            catalogs.c.is_active.is_(True),
            catalogs.c.source == "migration",
        )
    ).mappings()

    for row in rows:
        approved = _approved_labels(bind, str(row["project_id"]))
        allowed_by_fold = {label.casefold(): label for label in DEFAULT_CATEGORIES}
        for label in approved:
            allowed_by_fold.setdefault(label.casefold(), label)

        categories: list[str] = []
        seen: set[str] = set()
        for label in [*_labels(row["categories"]), *approved]:
            canonical = allowed_by_fold.get(label.casefold())
            if canonical is None:
                continue
            if canonical.casefold() not in seen:
                seen.add(canonical.casefold())
                categories.append(canonical)

        active_by_fold = {label.casefold(): label for label in categories}
        details = _filter_map(row["category_details_map"], active_by_fold)
        taxonomy = _filter_map(row["category_taxonomy"], active_by_fold)

        entries: list[dict[str, Any]] = []
        entry_by_fold: dict[str, dict[str, Any]] = {}
        for raw_entry in _json(row["category_entries"]) or []:
            if not isinstance(raw_entry, dict):
                continue
            label = _label(raw_entry.get("label"))
            if not label:
                continue
            canonical = active_by_fold.get(label.casefold())
            entry = {
                "id": _label(raw_entry.get("id")),
                "label": canonical or label,
                "status": "active" if canonical else "archived",
            }
            entries.append(entry)
            entry_by_fold[label.casefold()] = entry
        for label in categories:
            if label.casefold() in entry_by_fold:
                continue
            entries.append(
                {
                    "id": str(
                        uuid5(
                            NAMESPACE_URL,
                            f"qym-category:{row['project_id']}:{label.casefold()}",
                        )
                    ),
                    "label": label,
                    "status": "active",
                }
            )

        payload = {
            "categories": categories,
            "category_entries": entries,
            "category_details_map": details,
            "category_taxonomy": taxonomy,
            "max_root_cause_categories": int(row["max_root_cause_categories"] or 3),
        }
        bind.execute(
            catalogs.update()
            .where(catalogs.c.id == row["id"])
            .values(
                categories=categories,
                category_entries=entries,
                category_details_map=details,
                category_taxonomy=taxonomy,
                content_hash=_hash(payload),
            )
        )


def downgrade() -> None:
    """The removed labels cannot be reconstructed safely."""
