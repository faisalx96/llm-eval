"""Backfill one active analysis category catalog per legacy project.

Revision ID: 0043
Revises: 0042_merge_analysis_pass_scores
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from alembic import op
import sqlalchemy as sa


revision = "0043"
down_revision = "0042_merge_analysis_pass_scores"
branch_labels = None
depends_on = None


DEFAULT_TAXONOMY = {
    "Hallucination": {
        "description": "The response asserts facts, entities, values, or behavior that are not supported by the available evidence.",
        "when_to_use": "Use when the output contains fabricated or unsupported information and the primary failure is not simply missing content or incorrect formatting.",
    },
    "Incomplete Answer": {
        "description": "The response omits a required part of the requested answer or fails to complete the requested task.",
        "when_to_use": "Use when the response is materially incomplete even though the omitted information was available or the task was otherwise understood.",
    },
    "Wrong Format": {
        "description": "The response does not follow the required output structure, syntax, schema, or formatting contract.",
        "when_to_use": "Use when formatting or schema non-compliance is the main reason the selected metric failed.",
    },
    "Context Missing": {
        "description": "The model lacked, failed to retrieve, or failed to use context needed to produce the correct answer.",
        "when_to_use": "Use when the evidence shows that missing or unused input, retrieval, memory, or tool context caused the failure.",
    },
    "Reasoning Error": {
        "description": "The response uses an invalid inference, calculation, transformation, or logical step despite having sufficient relevant information.",
        "when_to_use": "Use when the model had the necessary facts but reached the wrong result because its reasoning or computation was incorrect.",
    },
    "Tool Use Error": {
        "description": "A tool was selected, invoked, parameterized, interpreted, or sequenced incorrectly.",
        "when_to_use": "Use when an incorrect tool action or tool-result handling is the direct cause of the failed metric.",
    },
    "Instruction Following": {
        "description": "The response violates an explicit instruction, constraint, policy, or requested behavior.",
        "when_to_use": "Use when the model understood or had access to the requirement but did not follow it, and the failure is not better explained by format alone.",
    },
    "Knowledge Gap": {
        "description": "The model cannot provide a correct answer because it lacks knowledge that was not supplied in the evaluation context.",
        "when_to_use": "Use when the failure depends on information absent from the model's available knowledge and context, without evidence of fabrication or reasoning error.",
    },
    "Dataset Issue": {
        "description": "The evaluation input, expected answer, metadata, or other dataset record is incorrect, ambiguous, or internally inconsistent.",
        "when_to_use": "Use when the record itself makes a correct evaluation or answer impossible, ambiguous, or misleading.",
    },
}


def _text(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()[:200]


def _json(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (TypeError, ValueError):
            return value
    return None


def _merge_taxonomy(target: dict[str, dict[str, str]], value: Any) -> None:
    raw = _json(value)
    if not isinstance(raw, dict):
        return
    for raw_label, raw_entry in raw.items():
        label = _text(raw_label)
        if not label:
            continue
        canonical = next(
            (existing for existing in target if existing.casefold() == label.casefold()),
            label,
        )
        entry = raw_entry if isinstance(raw_entry, dict) else {}
        current = target.setdefault(canonical, {})
        for field in ("description", "when_to_use"):
            text = _text(entry.get(field))
            if text:
                current[field] = text


def _add_categories(
    categories: list[str], details: dict[str, list[str]], value: Any
) -> None:
    raw = _json(value)
    if isinstance(raw, dict):
        for raw_label, raw_details in raw.items():
            label = _text(raw_label)
            if not label:
                continue
            canonical = next(
                (existing for existing in categories if existing.casefold() == label.casefold()),
                label,
            )
            if canonical not in categories:
                categories.append(canonical)
            if isinstance(raw_details, (list, tuple, set)):
                existing_details = details.setdefault(canonical, [])
                for raw_detail in raw_details:
                    detail = _text(raw_detail)
                    if detail and detail.casefold() not in {
                        item.casefold() for item in existing_details
                    }:
                        existing_details.append(detail)
        return
    values = raw if isinstance(raw, list) else [raw]
    for raw_label in values:
        label = _text(raw_label)
        if label and label.casefold() not in {item.casefold() for item in categories}:
            categories.append(label)


def _add_detail(details: dict[str, list[str]], label: Any, raw_detail: Any) -> None:
    category = _text(label)
    detail = _text(raw_detail)
    if not category or not detail:
        return
    canonical = next(
        (existing for existing in details if existing.casefold() == category.casefold()),
        category,
    )
    values = details.setdefault(canonical, [])
    if detail.casefold() not in {item.casefold() for item in values}:
        values.append(detail)


def _catalog_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
            "utf-8"
        )
    ).hexdigest()


def _legacy_project_catalog(
    bind: sa.Connection,
    project_id: str,
    prior_catalog: dict[str, Any] | None = None,
) -> dict[str, Any]:
    categories = list(DEFAULT_TAXONOMY)
    details: dict[str, list[str]] = {}
    taxonomy = {label: dict(entry) for label, entry in DEFAULT_TAXONOMY.items()}
    prior_entries = []
    if prior_catalog:
        _add_categories(categories, details, prior_catalog.get("categories"))
        _add_categories(categories, details, prior_catalog.get("category_details_map"))
        _merge_taxonomy(taxonomy, prior_catalog.get("category_taxonomy"))
        prior_entries = prior_catalog.get("category_entries") or []

    # Review candidates can contain human labels that were not copied back to
    # item metadata in older releases. Only active approved candidates are
    # allowed to seed the project vocabulary; pending AI labels are not
    # reviewer-approved diagnosis categories.
    correction_query = sa.text(
        """
        SELECT rc.human_root_cause, rc.human_root_causes,
               rc.human_category_taxonomy, rc.human_root_cause_detail,
               rc.ai_root_cause, rc.ai_root_causes,
               rc.ai_category_taxonomy, rc.ai_root_cause_detail
        FROM review_corrections rc
        JOIN runs r ON r.id = rc.run_id
        WHERE r.project_id = :project_id
          AND rc.status = 'approved'
          AND rc.is_active = TRUE
        """
    )
    result = bind.execute(
        correction_query,
        {"project_id": project_id},
        execution_options={"stream_results": True},
    )
    while True:
        rows = result.fetchmany(500)
        if not rows:
            break
        for row in rows:
            human_categories = row[1] or row[0]
            ai_categories = row[5] or row[4]
            raw_categories = human_categories or ai_categories
            _add_categories(categories, details, raw_categories)
            _merge_taxonomy(taxonomy, row[2] or row[6])
            detail = row[3] or row[7]
            parsed_categories = _json(raw_categories)
            if isinstance(parsed_categories, list):
                for category in parsed_categories:
                    _add_detail(details, category, detail)
            else:
                _add_detail(details, parsed_categories, detail)
    result.close()

    prior_by_fold = {
        _text(entry.get("label")).casefold(): entry
        for entry in prior_entries
        if isinstance(entry, dict) and _text(entry.get("label"))
    }
    entries = []
    active_folds = {label.casefold() for label in categories}
    for label in categories:
        prior = prior_by_fold.get(label.casefold()) or {}
        entries.append(
            {
                "id": _text(prior.get("id"))
                or str(uuid5(NAMESPACE_URL, f"qym-category:{project_id}:{label.casefold()}")),
                "label": label,
                "status": "active",
            }
        )
    for entry in prior_entries:
        if not isinstance(entry, dict):
            continue
        label = _text(entry.get("label"))
        if label and label.casefold() not in active_folds:
            entries.append(
                {
                    "id": _text(entry.get("id"))
                    or str(uuid5(NAMESPACE_URL, f"qym-category:{project_id}:{label.casefold()}")),
                    "label": label,
                    "status": "archived",
                }
            )
    payload = {
        "categories": categories,
        "category_entries": entries,
        "category_details_map": details,
        "category_taxonomy": taxonomy,
        "max_root_cause_categories": 3,
    }
    payload["content_hash"] = _catalog_hash(payload)
    return payload


def upgrade() -> None:
    bind = op.get_bind()
    projects = sa.Table("projects", sa.MetaData(), autoload_with=bind)
    catalogs = sa.Table(
        "project_analysis_category_catalog_versions",
        sa.MetaData(),
        autoload_with=bind,
    )
    # Keep the small project-id result buffered so per-project batch queries
    # can reuse the same connection on PostgreSQL.
    project_rows = bind.execute(sa.select(projects.c.id))
    while True:
        rows = project_rows.fetchmany(100)
        if not rows:
            break
        for (project_id,) in rows:
            active = bind.execute(
                sa.select(catalogs.c.id)
                .where(
                    catalogs.c.project_id == project_id,
                    catalogs.c.is_active.is_(True),
                )
                .limit(1)
            ).first()
            if active:
                continue
            latest = bind.execute(
                sa.select(
                    catalogs.c.version,
                    catalogs.c.categories,
                    catalogs.c.category_entries,
                    catalogs.c.category_details_map,
                    catalogs.c.category_taxonomy,
                )
                .where(catalogs.c.project_id == project_id)
                .order_by(catalogs.c.version.desc())
                .limit(1)
            ).first()
            prior_catalog = (
                {
                    "categories": latest.categories,
                    "category_entries": latest.category_entries,
                    "category_details_map": latest.category_details_map,
                    "category_taxonomy": latest.category_taxonomy,
                }
                if latest is not None
                else None
            )
            catalog = _legacy_project_catalog(bind, str(project_id), prior_catalog)
            bind.execute(
                catalogs.insert().values(
                    id=str(uuid5(NAMESPACE_URL, f"qym-catalog:{project_id}:0043")),
                    project_id=project_id,
                    version=int(latest.version if latest is not None else 0) + 1,
                    categories=catalog["categories"],
                    category_entries=catalog["category_entries"],
                    category_details_map=catalog["category_details_map"],
                    category_taxonomy=catalog["category_taxonomy"],
                    max_root_cause_categories=catalog["max_root_cause_categories"],
                    content_hash=catalog["content_hash"],
                    source="migration",
                    is_active=True,
                    created_at=datetime.utcnow(),
                )
            )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "DELETE FROM project_analysis_category_catalog_versions "
            "WHERE source = 'migration'"
        )
    )
