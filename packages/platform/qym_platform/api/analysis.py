from __future__ import annotations

import ast
import asyncio
import copy
import hashlib
import inspect
import json
import logging
import math
from functools import partial
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional, Union
from uuid import NAMESPACE_URL, uuid4, uuid5

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from anyio import CapacityLimiter, to_thread
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from qym_platform.auth import Principal, require_ui_principal
from qym_platform.datetime_utils import to_api_timestamp, utc_now_naive
from qym_platform.db.models import (
    AnalyzerDocument,
    AnalysisRuleVersionStatus,
    CorrectionStatus,
    Project,
    ProjectAnalysisCategoryCatalogVersion,
    ProjectAnalysisRuleAlias,
    ProjectAnalysisRuleMergeParent,
    ProjectAnalysisRuleVersion,
    ProjectLlmConnection,
    ReviewCorrection,
    RootCauseRevision,
    Run,
    RunItem,
    RunItemScore,
    RunMetricSpec,
    User,
    UserRole,
)
from qym_platform.db.session import SessionLocal
from qym_platform.deps import get_db
from qym_platform.llm_endpoint_security import (
    LlmEndpointValidationError,
    validate_llm_base_url,
)
from qym_platform.permissions import (
    apply_reviewable_run_filter,
    can_delete_run,
    can_review_run,
    can_view_run,
    has_project_access,
    is_project_manager,
)
from qym_platform.secrets import resolve_llm_api_key
from qym_platform.services.analysis_aggregation import (
    AnalysisAggregationError,
    aggregate_analysis_categories,
)
from qym_platform.services.document_extractor import (
    MAX_REFERENCE_DOCUMENT_CONTENT_CHARS,
    MAX_REFERENCE_DOCUMENT_CHARS,
    MAX_REFERENCE_UPLOAD_BYTES,
    DocumentExtractionError,
    UnsupportedDocumentError,
    extract_document_text,
)
from qym_platform.services.llm_analyzer import (
    DEFAULT_SYSTEM_PROMPT,
    ROOT_CAUSE_CATEGORIES,
    SOLUTION_CATEGORIES,
    AnalysisRule,
    AnalysisResult,
    analyze_items_batch,
    analyze_single_item,
    build_analysis_prompt,
    build_client,
    estimate_rule_writer_example_characters,
    get_all_approved_examples,
    get_selected_approved_examples,
    infer_analysis_rules,
    normalize_analysis_rules,
    prompt_character_count,
    MAX_ANALYSIS_PROMPT_CHARS,
    MAX_RULE_WRITER_DOCUMENT_CHARS,
    MAX_RULE_WRITER_EXAMPLE_CHARS,
    MAX_RULE_WRITER_PROMPT_CHARS,
    MAX_TOTAL_REFERENCE_DOCUMENT_CHARS,
)
from qym_platform.services.root_cause_changes import (
    apply_root_cause_change,
    build_ai_state,
    build_item_metadata,
    extract_analysis_state,
    replace_metric_review_candidate,
)
from qym_platform.services.root_cause_categories import (
    DEFAULT_MAX_ROOT_CAUSE_CATEGORIES,
    DEFAULT_ROOT_CAUSE_TAXONOMY,
    analysis_root_causes,
    merge_category_taxonomies,
    normalize_category_taxonomy,
    normalize_root_causes,
)
from qym_platform.services.analysis_jobs import (
    AnalysisJob,
    analysis_job_manager,
)
from qym_platform.services.analysis_prompts import get_effective_analysis_prompts
from qym_platform.settings import PlatformSettings
from sqlalchemy import String, and_, cast, func, or_, tuple_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, object_session, sessionmaker

logger = logging.getLogger(__name__)
router = APIRouter(tags=["analysis"])

# PDF extraction can wait on a resource-limited child process. Keep that wait
# off the event loop and bound concurrent extraction work per application worker.
_DOCUMENT_EXTRACTION_LIMITER = CapacityLimiter(2)

MappingSource = Union[str, List[str]]

_PROJECT_ANALYSIS_SCOPE_PREFIX = "project:"


@dataclass(frozen=True)
class _ProjectAnalysisScope:
    """Run-shaped project scope used by analyzer context endpoints."""

    id: str
    project_id: str
    task: str | None = None
    owner_user_id: str | None = None
    deleted_at: Any = None


def _can_operate_analyzer(db: Session, principal: Principal, run: Run) -> bool:
    """Allow analyzer spending/mutation to the run owner or project managers."""
    return run.owner_user_id == principal.user.id or is_project_manager(
        db, principal, run.project_id
    )


def _project_analysis_scope_key(project_slug: str) -> str:
    return _PROJECT_ANALYSIS_SCOPE_PREFIX + str(project_slug or "").strip()


def _resolve_analysis_scope(
    db: Session,
    principal: Principal,
    scope_id: str,
    *,
    modify: bool = False,
) -> Run | _ProjectAnalysisScope:
    """Resolve either a run or an explicitly project-scoped analyzer context."""
    if scope_id.startswith(_PROJECT_ANALYSIS_SCOPE_PREFIX):
        project_slug = scope_id[len(_PROJECT_ANALYSIS_SCOPE_PREFIX) :].strip()
        project = (
            db.query(Project)
            .filter(Project.slug == project_slug, Project.is_active.is_(True))
            .first()
        )
        if project is None:
            raise HTTPException(status_code=404, detail="Project not found")
        if not has_project_access(db, principal, project.id):
            raise HTTPException(status_code=403, detail="Access denied")
        if modify and not is_project_manager(db, principal, project.id):
            raise HTTPException(
                status_code=403, detail="Project manager access required"
            )
        return _ProjectAnalysisScope(
            id=scope_id,
            project_id=project.id,
        )

    run = Run.active(db).filter(Run.id == scope_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    if not can_view_run(db, principal, run):
        raise HTTPException(status_code=403, detail="Access denied")
    if modify and not _can_operate_analyzer(db, principal, run):
        raise HTTPException(
            status_code=403, detail="Analyzer owner or manager access required"
        )
    return run


def _active_analysis_rule_version(
    db: Session, project_id: str
) -> ProjectAnalysisRuleVersion | None:
    alias = (
        db.query(ProjectAnalysisRuleAlias)
        .filter(
            ProjectAnalysisRuleAlias.project_id == project_id,
            ProjectAnalysisRuleAlias.alias == "production",
        )
        .first()
    )
    if alias:
        version = db.get(ProjectAnalysisRuleVersion, alias.rule_version_id)
        if (
            version is not None
            and version.deleted_at is None
            and _rule_status(version) == AnalysisRuleVersionStatus.PUBLISHED.value
        ):
            return version
    published = (
        db.query(ProjectAnalysisRuleVersion)
        .filter(
            ProjectAnalysisRuleVersion.project_id == project_id,
            ProjectAnalysisRuleVersion.deleted_at.is_(None),
            ProjectAnalysisRuleVersion.status
            == AnalysisRuleVersionStatus.PUBLISHED,
        )
        .order_by(
            ProjectAnalysisRuleVersion.published_at.desc().nullslast(),
            ProjectAnalysisRuleVersion.version.desc(),
        )
        .first()
    )
    if published:
        return published
    return None


def _latest_analysis_rule_draft(
    db: Session, project_id: str
) -> ProjectAnalysisRuleVersion | None:
    """Return the latest editable draft used when no version was selected."""
    return (
        db.query(ProjectAnalysisRuleVersion)
        .filter(
            ProjectAnalysisRuleVersion.project_id == project_id,
            ProjectAnalysisRuleVersion.deleted_at.is_(None),
            ProjectAnalysisRuleVersion.status == AnalysisRuleVersionStatus.DRAFT,
        )
        .order_by(ProjectAnalysisRuleVersion.version.desc())
        .first()
    )


def _rule_status(version: ProjectAnalysisRuleVersion) -> str:
    return (
        version.status.value
        if hasattr(version.status, "value")
        else str(version.status or "")
    )


def _rule_content_hash(rules: list[dict[str, Any]]) -> str:
    payload = json.dumps(
        rules, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _rules_with_stable_ids(
    value: Any,
    *,
    existing: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    normalized = normalize_analysis_rules(value, preserve_ids=True)
    existing_by_id = {
        str(rule.get("id")): rule
        for rule in (existing or [])
        if isinstance(rule, dict) and rule.get("id")
    }
    existing_by_title = {
        str(rule.get("title") or "").strip().casefold(): rule
        for rule in (existing or [])
        if isinstance(rule, dict)
    }
    result: list[dict[str, Any]] = []
    for rule in normalized:
        requested_id = str(rule.get("id") or "").strip()
        prior = existing_by_id.get(requested_id) or existing_by_title.get(
            rule["title"].casefold()
        )
        result.append({
            "id": requested_id
            or str((prior or {}).get("id") or "")
            or str(uuid4()),
            **{key: value for key, value in rule.items() if key != "id"},
        })
    return result


def _analysis_rule_comparison_text(value: Any) -> str:
    return " ".join(str(value or "").split()).casefold()


def _new_analysis_rules(
    existing_rules: list[dict[str, Any]],
    candidates: Any,
) -> list[dict[str, Any]]:
    """Return only new candidates, preserving existing rule dictionaries verbatim."""
    existing_ids = {
        str(rule.get("id") or "").strip()
        for rule in existing_rules
        if isinstance(rule, dict) and str(rule.get("id") or "").strip()
    }
    existing_titles = {
        _analysis_rule_comparison_text(rule.get("title"))
        for rule in existing_rules
        if isinstance(rule, dict)
        and _analysis_rule_comparison_text(rule.get("title"))
    }
    existing_instructions = {
        _analysis_rule_comparison_text(rule.get("instruction"))
        for rule in existing_rules
        if isinstance(rule, dict)
        and _analysis_rule_comparison_text(rule.get("instruction"))
    }
    result: list[dict[str, Any]] = []
    seen_titles: set[str] = set()
    seen_instructions: set[str] = set()
    for rule in normalize_analysis_rules(candidates, preserve_ids=True):
        rule_id = str(rule.get("id") or "").strip()
        title = _analysis_rule_comparison_text(rule.get("title"))
        instruction = _analysis_rule_comparison_text(rule.get("instruction"))
        if (
            (rule_id and rule_id in existing_ids)
            or (title and title in existing_titles)
            or (instruction and instruction in existing_instructions)
            or (title and title in seen_titles)
            or (instruction and instruction in seen_instructions)
        ):
            continue
        result.append(rule)
        if title:
            seen_titles.add(title)
        if instruction:
            seen_instructions.add(instruction)
    return _rules_with_stable_ids(result, existing=existing_rules)


def _resolve_analysis_rule_version(
    db: Session,
    project_id: str,
    ref: str | int | None = "production",
) -> ProjectAnalysisRuleVersion:
    clean = str(ref or "production").strip() or "production"
    by_id = (
        db.query(ProjectAnalysisRuleVersion)
        .filter(
            ProjectAnalysisRuleVersion.project_id == project_id,
            ProjectAnalysisRuleVersion.id == clean,
            ProjectAnalysisRuleVersion.deleted_at.is_(None),
        )
        .first()
    )
    if by_id:
        return by_id
    number = clean[1:] if clean.lower().startswith("v") else clean
    version = None
    if number.isdigit():
        version = (
            db.query(ProjectAnalysisRuleVersion)
            .filter(
                ProjectAnalysisRuleVersion.project_id == project_id,
                ProjectAnalysisRuleVersion.version == int(number),
                ProjectAnalysisRuleVersion.deleted_at.is_(None),
            )
            .first()
        )
    if version:
        return version
    alias = (
        db.query(ProjectAnalysisRuleAlias)
        .filter(
            ProjectAnalysisRuleAlias.project_id == project_id,
            ProjectAnalysisRuleAlias.alias == clean,
        )
        .first()
    )
    if alias:
        version = db.get(ProjectAnalysisRuleVersion, alias.rule_version_id)
        if version is not None and version.deleted_at is None:
            return version
    if clean == "production":
        version = _active_analysis_rule_version(db, project_id)
        if version:
            return version
    raise HTTPException(
        status_code=404, detail=f"Analysis rule version or alias not found: {clean}"
    )


def _set_analysis_rule_alias(
    db: Session,
    *,
    project_id: str,
    alias_name: str,
    version: ProjectAnalysisRuleVersion,
    actor_user_id: str,
) -> ProjectAnalysisRuleAlias:
    if (
        _rule_status(version) != AnalysisRuleVersionStatus.PUBLISHED.value
        or version.deleted_at is not None
    ):
        raise HTTPException(
            status_code=409,
            detail="Aliases can only point to published analysis rule versions",
        )
    alias = (
        db.query(ProjectAnalysisRuleAlias)
        .filter(
            ProjectAnalysisRuleAlias.project_id == project_id,
            ProjectAnalysisRuleAlias.alias == alias_name,
        )
        .first()
    )
    if alias is None:
        alias = ProjectAnalysisRuleAlias(
            project_id=project_id,
            alias=alias_name,
            rule_version_id=version.id,
            updated_by_user_id=actor_user_id,
            updated_at=utc_now_naive(),
        )
        db.add(alias)
    else:
        alias.rule_version_id = version.id
        alias.updated_by_user_id = actor_user_id
        alias.updated_at = utc_now_naive()
    return alias


def _create_analysis_rule_version(
    db: Session,
    *,
    project_id: str,
    rules: list[dict[str, Any]],
    source: str,
    actor_user_id: str | None,
    force_new: bool = False,
    parent: ProjectAnalysisRuleVersion | None = None,
    description: str = "",
    preserve_rules: bool = False,
) -> ProjectAnalysisRuleVersion:
    """Create a mutable draft derived from another rule version."""
    active = parent or _active_analysis_rule_version(db, project_id)
    normalized = (
        copy.deepcopy(rules)
        if preserve_rules
        else _rules_with_stable_ids(rules, existing=active.rules if active else None)
    )
    if (
        not force_new
        and active is not None
        and _rule_status(active) == AnalysisRuleVersionStatus.DRAFT.value
        and normalize_analysis_rules(active.rules)
        == normalize_analysis_rules(normalized)
    ):
        return active
    for attempt in range(3):
        try:
            with db.begin_nested():
                latest_number = (
                    db.query(func.max(ProjectAnalysisRuleVersion.version))
                    .filter(ProjectAnalysisRuleVersion.project_id == project_id)
                    .scalar()
                    or 0
                )
                version_number = int(latest_number) + 1
                version = ProjectAnalysisRuleVersion(
                    project_id=project_id,
                    version=version_number,
                    name=f"v{version_number}",
                    description=description,
                    status=AnalysisRuleVersionStatus.DRAFT,
                    rules=normalized,
                    source=source,
                    parent_version_id=active.id if active else None,
                    base_version_id=(active.base_version_id or active.id) if active else None,
                    created_by_user_id=actor_user_id,
                    created_at=utc_now_naive(),
                    updated_at=utc_now_naive(),
                )
                db.add(version)
                db.flush()
            return version
        except IntegrityError as exc:
            error_text = str(exc.orig).lower()
            if (
                "uq_project_analysis_rule_version" not in error_text
                and "project_analysis_rule_versions.project_id, "
                "project_analysis_rule_versions.version" not in error_text
            ):
                raise
            if attempt == 2:
                raise HTTPException(
                    status_code=409,
                    detail="Could not allocate a rule version; please retry.",
                ) from exc
    raise AssertionError("Rule version allocation retry loop exited unexpectedly")


def _save_active_analysis_rules(
    db: Session,
    *,
    project_id: str,
    rules: list[dict[str, Any]],
    actor_user_id: str | None,
    version_id: str | None = None,
) -> ProjectAnalysisRuleVersion:
    """Update a draft, creating one from production when necessary."""
    target = db.get(ProjectAnalysisRuleVersion, version_id) if version_id else None
    if version_id and target is None:
        raise HTTPException(status_code=404, detail="Analysis rule version not found")
    if target is not None and target.project_id != project_id:
        raise HTTPException(status_code=404, detail="Analysis rule version not found")
    if target is not None and target.deleted_at is not None:
        raise HTTPException(
            status_code=409,
            detail="Deleted analysis rule versions cannot be edited",
        )
    if target is None:
        drafts = (
            db.query(ProjectAnalysisRuleVersion)
            .filter(
                ProjectAnalysisRuleVersion.project_id == project_id,
                ProjectAnalysisRuleVersion.status == AnalysisRuleVersionStatus.DRAFT,
                ProjectAnalysisRuleVersion.deleted_at.is_(None),
            )
            .order_by(ProjectAnalysisRuleVersion.version.desc())
            .all()
        )
        target = drafts[0] if len(drafts) == 1 else None
    if target is None:
        return _create_analysis_rule_version(
            db,
            project_id=project_id,
            rules=rules,
            source="manual",
            actor_user_id=actor_user_id,
        )
    normalized = _rules_with_stable_ids(rules, existing=target.rules)
    if _rule_status(target) != AnalysisRuleVersionStatus.DRAFT.value:
        if normalize_analysis_rules(target.rules) == normalize_analysis_rules(
            normalized
        ):
            return target
        raise HTTPException(
            status_code=409,
            detail="Published analysis rule versions are immutable; continue as a draft to edit them",
        )
    if target.rules != normalized:
        target.rules = normalized
        target.source = "manual"
        target.updated_at = utc_now_naive()
        db.flush()
    return target


def _analysis_rule_version_payload(
    version: ProjectAnalysisRuleVersion,
    *,
    active_version_id: str | None,
) -> Dict[str, Any]:
    session = object_session(version)
    creator = (
        session.get(User, version.created_by_user_id)
        if session is not None and version.created_by_user_id
        else None
    )
    aliases = [
        row.alias
        for row in session.query(ProjectAnalysisRuleAlias)
        .filter(ProjectAnalysisRuleAlias.rule_version_id == version.id)
        .order_by(ProjectAnalysisRuleAlias.alias)
        .all()
    ] if session is not None else []
    merge_parents = (
        session.query(ProjectAnalysisRuleMergeParent)
        .filter(ProjectAnalysisRuleMergeParent.version_id == version.id)
        .order_by(
            ProjectAnalysisRuleMergeParent.created_at.asc(),
            ProjectAnalysisRuleMergeParent.id.asc(),
        )
        .all()
        if session is not None
        else []
    )
    return {
        "id": version.id,
        "version": version.version,
        "name": version.name or "",
        "description": version.description or "",
        "status": _rule_status(version),
        "rules": version.rules or [],
        "rule_count": len(version.rules or []),
        "source": version.source,
        "parent_version_id": version.parent_version_id,
        "base_version_id": version.base_version_id,
        "merge_parent_ids": [edge.parent_version_id for edge in merge_parents],
        "merge_base_version_ids": [
            edge.merge_base_version_id
            for edge in merge_parents
            if edge.merge_base_version_id
        ],
        "content_hash": version.content_hash or "",
        "aliases": aliases,
        "is_active": version.id == active_version_id,
        "is_deleted": version.deleted_at is not None,
        "created_by_user_id": version.created_by_user_id,
        "created_by": (
            {
                "id": creator.id,
                "display_name": creator.display_name
                or creator.email.split("@")[0],
            }
            if creator is not None
            else None
        ),
        "created_at": to_api_timestamp(version.created_at),
        "updated_at": to_api_timestamp(version.updated_at),
        "published_by_user_id": version.published_by_user_id,
        "published_at": to_api_timestamp(version.published_at),
        "activated_by_user_id": version.activated_by_user_id,
        "activated_at": to_api_timestamp(version.activated_at),
        "deleted_by_user_id": version.deleted_by_user_id,
        "deleted_at": to_api_timestamp(version.deleted_at),
        "restored_by_user_id": version.restored_by_user_id,
        "restored_at": to_api_timestamp(version.restored_at),
    }


def _rule_version_parent_ids(
    db: Session, version: ProjectAnalysisRuleVersion
) -> list[str]:
    parent_ids: list[str] = []
    if version.parent_version_id:
        parent_ids.append(version.parent_version_id)
    for (parent_id,) in (
        db.query(ProjectAnalysisRuleMergeParent.parent_version_id)
        .filter(ProjectAnalysisRuleMergeParent.version_id == version.id)
        .order_by(ProjectAnalysisRuleMergeParent.id.asc())
        .all()
    ):
        if parent_id and parent_id not in parent_ids:
            parent_ids.append(parent_id)
    return parent_ids


def _rule_version_ancestor_depths(
    db: Session, version: ProjectAnalysisRuleVersion
) -> dict[str, int]:
    """Return this version and all ancestors with their shortest graph depth."""
    depths = {version.id: 0}
    queue = [version.id]
    while queue:
        current_id = queue.pop(0)
        current = db.get(ProjectAnalysisRuleVersion, current_id)
        if current is None:
            continue
        next_depth = depths[current_id] + 1
        for parent_id in _rule_version_parent_ids(db, current):
            if parent_id not in depths or next_depth < depths[parent_id]:
                depths[parent_id] = next_depth
                queue.append(parent_id)
    return depths


def _nearest_rule_merge_base(
    db: Session,
    target: ProjectAnalysisRuleVersion,
    source: ProjectAnalysisRuleVersion,
) -> ProjectAnalysisRuleVersion | None:
    target_depths = _rule_version_ancestor_depths(db, target)
    source_depths = _rule_version_ancestor_depths(db, source)
    common = set(target_depths) & set(source_depths)
    if not common:
        return None
    base_id = min(
        common,
        key=lambda version_id: (
            target_depths[version_id] + source_depths[version_id],
            max(target_depths[version_id], source_depths[version_id]),
        ),
    )
    return db.get(ProjectAnalysisRuleVersion, base_id)


def _rule_map(
    rules: list[dict[str, Any]] | None,
) -> tuple[dict[str, dict[str, Any]], list[str]]:
    mapped: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for rule in rules or []:
        if not isinstance(rule, dict):
            continue
        key = str(rule.get("id") or "").strip() or (
            "title:" + str(rule.get("title") or "").strip().casefold()
        )
        if not key or key in mapped:
            continue
        normalized: dict[str, Any] = {
            "id": str(rule.get("id") or "").strip(),
            "title": str(rule.get("title") or "").strip(),
            "instruction": str(rule.get("instruction") or "").strip(),
        }
        for metadata_key in ("inferred_from", "explanation"):
            metadata_value = str(rule.get(metadata_key) or "").strip()
            if metadata_value:
                normalized[metadata_key] = metadata_value
        mapped[key] = normalized
        order.append(key)
    return mapped, order


def _rule_equal(
    left: dict[str, Any] | None, right: dict[str, Any] | None
) -> bool:
    if left is None or right is None:
        return left is right
    return all(
        str(left.get(field) or "").strip()
        == str(right.get(field) or "").strip()
        for field in ("title", "instruction", "inferred_from", "explanation")
    )


def _merge_rule_versions(
    *,
    base: ProjectAnalysisRuleVersion | None,
    target: ProjectAnalysisRuleVersion,
    source: ProjectAnalysisRuleVersion,
    resolutions: Dict[str, Union[str, AnalyzerRuleConfig]],
) -> dict[str, Any]:
    base_map, base_order = _rule_map(base.rules if base else [])
    target_map, target_order = _rule_map(target.rules)
    source_map, source_order = _rule_map(source.rules)
    ordered_keys = list(dict.fromkeys(target_order + source_order + base_order))
    merged: dict[str, dict[str, Any]] = {}
    conflicts: list[dict[str, Any]] = []

    for key in ordered_keys:
        before = base_map.get(key)
        current = target_map.get(key)
        incoming = source_map.get(key)
        if _rule_equal(current, incoming):
            chosen = current
        elif _rule_equal(current, before):
            chosen = incoming
        elif _rule_equal(incoming, before):
            chosen = current
        else:
            resolution = resolutions.get(key)
            if resolution == "target":
                chosen = current
            elif resolution == "source":
                chosen = incoming
            elif isinstance(resolution, AnalyzerRuleConfig):
                chosen = resolution.model_dump(exclude_none=True)
                chosen["id"] = str(chosen.get("id") or "").strip() or str(
                    (current or incoming or before or {}).get("id") or ""
                )
            else:
                conflicts.append(
                    {
                        "key": key,
                        "base": before,
                        "target": current,
                        "source": incoming,
                    }
                )
                continue
        if chosen is not None:
            merged[key] = chosen

    merged_rules = [
        merged[key] for key in ordered_keys if key in merged
    ]
    normalized_rules = _rules_with_stable_ids(
        merged_rules,
        existing=list(target.rules or []) + list(source.rules or []),
    )
    before_keys = set(target_map)
    after_map, _ = _rule_map(normalized_rules)
    after_keys = set(after_map)
    changed = sum(
        not _rule_equal(target_map[key], after_map[key])
        for key in before_keys & after_keys
    )
    return {
        "base_version_id": base.id if base else None,
        "target_version_id": target.id,
        "source_version_id": source.id,
        "rules": normalized_rules,
        "summary": {
            "added": len(after_keys - before_keys),
            "removed": len(before_keys - after_keys),
            "changed": changed,
            "unchanged": len(before_keys & after_keys) - changed,
            "conflicts": len(conflicts),
        },
        "conflicts": conflicts,
    }


class ReferenceDocument(BaseModel):
    """Extracted document content included in each analyzer prompt."""

    name: str = Field(..., min_length=1, max_length=255)
    content: str = Field(..., min_length=1, max_length=MAX_REFERENCE_DOCUMENT_CHARS)


class AnalyzerRuleConfig(AnalysisRule):
    """One project rule applied during root-cause analysis."""


class AnalyzerDocumentSelection(BaseModel):
    """Project-level inclusion state for one analyzer document."""

    selected: bool


class CategoryTaxonomyConfig(BaseModel):
    """Definition and selection criteria for one root-cause category."""

    description: str = Field(default="", max_length=2_000)
    when_to_use: str = Field(default="", max_length=2_000)


class CategoryCatalogEntry(BaseModel):
    """Stable identity and lifecycle state for one project category."""

    id: Optional[str] = Field(default=None, max_length=36)
    label: str = Field(..., min_length=1, max_length=200)
    status: Literal["active", "archived"] = "active"


class PlaygroundConfig(BaseModel):
    """Configuration overrides for the AI evaluator playground."""

    analysis_rules: Optional[List[AnalyzerRuleConfig]] = None
    reference_documents: Optional[List[ReferenceDocument]] = Field(
        default=None, max_length=8
    )
    include_project_rules: Optional[bool] = None
    include_project_documents: Optional[bool] = None
    system_prompt: Optional[str] = Field(default=None, max_length=50_000)
    additional_instructions: Optional[str] = Field(default=None, max_length=20_000)
    custom_variable_mapping: Optional[Dict[str, MappingSource]] = None
    root_cause_categories: Optional[List[str]] = Field(default=None, max_length=100)
    max_root_cause_categories: Optional[int] = Field(
        default=None, ge=1, le=10
    )
    root_cause_details: Optional[List[str]] = Field(default=None, max_length=500)
    category_details_map: Optional[Dict[str, List[str]]] = None
    category_taxonomy: Optional[Dict[str, CategoryTaxonomyConfig]] = None
    # Accept the plural spelling from external clients while emitting the
    # canonical singular map internally.
    category_taxonomies: Optional[Dict[str, CategoryTaxonomyConfig]] = None
    category_catalog_version: Optional[int] = Field(default=None, ge=0)
    category_catalog_version_id: Optional[str] = Field(default=None, max_length=80)
    solution_categories: Optional[List[str]] = Field(default=None, max_length=100)
    include_fields: Optional[Dict[str, bool]] = None
    field_mapping: Optional[Dict[str, MappingSource]] = (
        None  # e.g. {"input": "input.question", "expected": "expected"}
    )
    metadata_fields: Optional[List[str]] = Field(default=None, max_length=100)
    temperature: Optional[float] = Field(default=None, ge=0.0, le=2.0)
    max_tokens: Optional[int] = Field(default=None, ge=1, le=32_768)


class AnalyzeRequest(BaseModel):
    """Filter criteria for which items to analyze.

    ``limit`` is an item limit. When several metrics are selected, every
    matching metric target for each selected item is retained.
    """

    metric: Optional[str] = None
    metrics: Optional[List[str]] = Field(default=None, max_length=100)
    max_score: Optional[float] = None
    item_filter: Literal["all", "failed", "passed", "errors"] = "all"
    threshold: float = 0.8
    only_unanalyzed: bool = True
    allow_human_overwrite: bool = False
    complexity: Optional[List[str]] = None
    domain: Optional[List[str]] = None
    root_cause: Optional[List[str]] = None
    item_ids: Optional[List[str]] = None
    limit: Optional[int] = Field(default=None, ge=1)
    concurrency: int = Field(default=20, ge=1, le=20)
    config: Optional[PlaygroundConfig] = None
    category_catalog_version_id: Optional[str] = Field(default=None, max_length=80)
    connection_id: Optional[str] = (
        None  # which project LLM connection to use; default if omitted
    )


class AggregateAnalysisRequest(BaseModel):
    """Re-run canonicalization over already-saved AI diagnoses."""

    metric: Optional[str] = None
    category_catalog_version_id: Optional[str] = Field(default=None, max_length=80)
    connection_id: Optional[str] = None


class PreviewRequest(BaseModel):
    """Request to preview the LLM messages for an item."""

    item_id: str
    metric: Optional[str] = None
    config: Optional[PlaygroundConfig] = None
    category_catalog_version_id: Optional[str] = Field(default=None, max_length=80)
    connection_id: Optional[str] = None


class TestRequest(BaseModel):
    """Request to test analysis on 1-3 items without saving."""

    item_ids: List[str] = Field(..., min_length=1, max_length=3)
    metric: Optional[str] = None
    config: Optional[PlaygroundConfig] = None
    category_catalog_version_id: Optional[str] = Field(default=None, max_length=80)
    connection_id: Optional[str] = None


class AnalysisContextUpdate(BaseModel):
    """Project-scoped analysis rules edited in the analyzer."""

    analysis_rules: List[AnalyzerRuleConfig] = Field(default_factory=list)
    create_new_version: bool = False
    rule_version_id: Optional[str] = None
    from_version: Optional[str] = None


class CategoryCatalogUpdate(BaseModel):
    """Full project diagnosis catalog snapshot submitted by the editor."""

    categories: List[str] = Field(default_factory=list, max_length=100)
    category_entries: Optional[List[CategoryCatalogEntry]] = Field(
        default=None, max_length=100
    )
    category_details_map: Dict[str, List[str]] = Field(default_factory=dict)
    category_taxonomy: Dict[str, CategoryTaxonomyConfig] = Field(default_factory=dict)
    max_root_cause_categories: int = Field(
        default=DEFAULT_MAX_ROOT_CAUSE_CATEGORIES, ge=1, le=10
    )
    base_revision: Optional[int] = Field(default=None, ge=0)
    # Compatibility with clients that named the optimistic revision explicitly.
    expected_version: Optional[int] = Field(default=None, ge=0)


class CategoryCatalogRestore(BaseModel):
    base_revision: Optional[int] = Field(default=None, ge=0)
    expected_version: Optional[int] = Field(default=None, ge=0)


class AnalysisRuleVersionCreate(BaseModel):
    """Create a draft rule version, optionally deriving from another version."""

    from_version: Optional[str] = None
    description: str = Field(default="", max_length=4000)


class AnalysisRuleVersionPublish(BaseModel):
    """Publish a rule draft and optionally move an alias."""

    set_alias: Optional[str] = Field(default=None, max_length=100)


class AnalysisRuleAliasUpdate(BaseModel):
    """Move a project rule alias to a published version."""

    version: str = Field(..., min_length=1, max_length=100)


class RuleInferenceRequest(BaseModel):
    """Inputs for the append-only project rule-writer agent."""

    include_documents: bool = True
    include_examples: bool = True
    # ``None`` preserves the legacy "all approved examples" behavior for old
    # clients.  The analyzer UI sends an explicit list, including an empty
    # list, so a selection can never silently expand to the whole project.
    approved_example_ids: Optional[List[int]] = Field(default=None, max_length=50_000)
    # Reuse the analyzer's field-selection shape when projecting examples into
    # the rule-writer prompt. Omitted fields keep the legacy payload intact.
    include_fields: Optional[Dict[str, bool]] = None
    # Kept as a compatibility field for older clients. The endpoint always
    # performs append-only generation, regardless of this value.
    mode: Literal["generate", "update"] = "generate"
    rule_version_id: Optional[str] = None
    connection_id: Optional[str] = None


class AnalysisExamplesQuery(BaseModel):
    """Paged picker query kept in the request body for large selections."""

    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)
    task: Optional[List[str]] = None
    dataset: Optional[List[str]] = None
    model: Optional[List[str]] = None
    run_name: Optional[List[str]] = None
    user_id: Optional[List[str]] = None
    source: Optional[str] = None
    conf_min: int = Field(default=0, ge=0, le=100)
    conf_max: int = Field(default=100, ge=0, le=100)
    search: Optional[str] = None
    selected_ids: List[int] = Field(default_factory=list, max_length=50_000)
    selected_only: bool = False


class AnalysisRuleMergeRequest(BaseModel):
    """Preview or apply a three-way merge into a rule version."""

    source_version: str = Field(..., min_length=1, max_length=100)
    apply: bool = False
    resolutions: Dict[str, Union[Literal["target", "source"], AnalyzerRuleConfig]] = (
        Field(default_factory=dict)
    )


def _resolve_connection(
    db: Session, project_id: str, connection_id: Optional[str]
) -> ProjectLlmConnection:
    """Pick the LLM connection for an analysis: explicit id, else the project default."""
    base = db.query(ProjectLlmConnection).filter(
        ProjectLlmConnection.project_id == project_id
    )
    if connection_id:
        conn = base.filter(ProjectLlmConnection.id == connection_id).first()
        if not conn:
            raise HTTPException(status_code=404, detail="LLM connection not found")
        return conn
    conn = base.filter(ProjectLlmConnection.is_default.is_(True)).first()
    if conn:
        return conn
    # No default flagged but connections exist (shouldn't normally happen) — use the first.
    conn = base.order_by(ProjectLlmConnection.created_at).first()
    if not conn:
        raise HTTPException(
            status_code=400,
            detail="No LLM connection configured for this project. Add one in Project Settings → LLM Connections.",
        )
    return conn


def _get_llm_config(
    db: Session, project_id: str, connection_id: Optional[str] = None
) -> dict[str, Any]:
    """Resolve and validate the project LLM connection to use for analysis."""
    conn = _resolve_connection(db, project_id, connection_id)
    if not conn.llm_api_key_encrypted:
        raise HTTPException(
            status_code=400,
            detail=f"LLM connection '{conn.name}' has no API key. Update it in Project Settings → LLM Connections.",
        )
    try:
        api_key = resolve_llm_api_key(
            {"llm_api_key_encrypted": conn.llm_api_key_encrypted}, PlatformSettings()
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    try:
        base_url = validate_llm_base_url(
            conn.llm_base_url or "https://api.openai.com/v1",
            allow_private=PlatformSettings().allow_private_llm_base_urls,
        )
    except LlmEndpointValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "llm_base_url": base_url,
        "llm_model": conn.llm_model or "gpt-4o-mini",
        "llm_api_key": api_key,
        "connection_id": conn.id,
        "connection_name": conn.name,
    }


def _playground_config_to_analyzer(
    pg: PlaygroundConfig | None,
) -> dict[str, Any] | None:
    """Convert PlaygroundConfig to the dict format expected by llm_analyzer."""
    if pg is None:
        return None
    cfg: dict[str, Any] = {}
    if pg.analysis_rules is not None:
        cfg["analysis_rules"] = [rule.model_dump() for rule in pg.analysis_rules]
    if pg.reference_documents is not None:
        cfg["reference_documents"] = [
            document.model_dump() for document in pg.reference_documents
        ]
    if pg.include_project_rules is not None:
        cfg["_include_project_rules"] = pg.include_project_rules
    if pg.include_project_documents is not None:
        cfg["_include_project_documents"] = pg.include_project_documents
    if pg.system_prompt is not None:
        cfg["system_prompt"] = pg.system_prompt
    if pg.root_cause_categories is not None:
        cfg["root_cause_categories"] = pg.root_cause_categories
    if pg.max_root_cause_categories is not None:
        cfg["max_root_cause_categories"] = pg.max_root_cause_categories
    if pg.category_details_map is not None:
        cfg["category_details_map"] = pg.category_details_map
    category_taxonomy = pg.category_taxonomy
    if category_taxonomy is None:
        category_taxonomy = pg.category_taxonomies
    if category_taxonomy is not None:
        cfg["category_taxonomy"] = {
            category: definition.model_dump()
            for category, definition in category_taxonomy.items()
        }
    if pg.category_catalog_version is not None:
        cfg["category_catalog_version"] = pg.category_catalog_version
    if pg.category_catalog_version_id is not None:
        cfg["category_catalog_version_id"] = pg.category_catalog_version_id
    if pg.root_cause_details is not None:
        cfg["root_cause_details"] = pg.root_cause_details
    if pg.solution_categories is not None:
        cfg["solution_categories"] = pg.solution_categories
    if pg.include_fields is not None:
        cfg["include_fields"] = pg.include_fields
    if pg.field_mapping is not None:
        cfg["field_mapping"] = pg.field_mapping
    if pg.metadata_fields is not None:
        cfg["metadata_fields"] = pg.metadata_fields
    if pg.additional_instructions is not None:
        cfg["additional_instructions"] = pg.additional_instructions
    if pg.custom_variable_mapping is not None:
        cfg["custom_variable_mapping"] = pg.custom_variable_mapping
    return cfg if cfg else None


def _supports_metric_name_arg(func: Any) -> bool:
    """Return True when the callable accepts metric_name."""
    try:
        return "metric_name" in inspect.signature(func).parameters
    except (TypeError, ValueError):
        return False


def _rewrite_legacy_metric_metadata_source(source: str) -> str:
    """Map metric_metadata.* sources onto item_metadata.* for legacy analyzers."""
    if source == "metric_metadata":
        return "item_metadata"
    if source.startswith("metric_metadata."):
        return "item_metadata." + source[len("metric_metadata.") :]
    return source


def _rewrite_legacy_mapping_source(source: Any) -> Any:
    if isinstance(source, list):
        return [_rewrite_legacy_metric_metadata_source(str(value)) for value in source]
    return _rewrite_legacy_metric_metadata_source(str(source))


def _adapt_legacy_analyzer_inputs(
    item: RunItem,
    scores: dict[str, RunItemScore],
    analyzer_config: dict[str, Any] | None,
    metric_name: str | None,
) -> tuple[RunItem, dict[str, Any] | None]:
    """Shim metric metadata into item metadata for older analyzer code paths."""
    if not metric_name:
        return item, analyzer_config

    metric_score = scores.get(metric_name)
    metric_meta = (
        metric_score.meta
        if metric_score and isinstance(metric_score.meta, dict)
        else {}
    )

    adapted_item = copy.copy(item)
    adapted_item.item_metadata = metric_meta

    if analyzer_config is None:
        return adapted_item, None

    adapted_config = dict(analyzer_config)

    field_mapping = adapted_config.get("field_mapping")
    if isinstance(field_mapping, dict):
        adapted_config["field_mapping"] = {
            key: _rewrite_legacy_mapping_source(source)
            for key, source in field_mapping.items()
        }

    custom_variable_mapping = adapted_config.get("custom_variable_mapping")
    if isinstance(custom_variable_mapping, dict):
        adapted_config["custom_variable_mapping"] = {
            key: _rewrite_legacy_mapping_source(source)
            for key, source in custom_variable_mapping.items()
        }

    metadata_fields = adapted_config.get("metadata_fields")
    if isinstance(metadata_fields, list):
        adapted_config["metadata_fields"] = [
            _rewrite_legacy_metric_metadata_source(str(source))
            for source in metadata_fields
        ]

    return adapted_item, adapted_config


def _load_run_items_and_scores(
    db: Session, run: Run
) -> tuple[list[RunItem], dict[str, dict[str, RunItemScore]]]:
    """Load all items and scores for a run."""
    all_items: list[RunItem] = (
        db.query(RunItem)
        .filter(RunItem.run_id == run.id)
        .order_by(RunItem.index.asc())
        .all()
    )
    all_scores = db.query(RunItemScore).filter(RunItemScore.run_id == run.id).all()
    scores_by_item: dict[str, dict[str, RunItemScore]] = {}
    for s in all_scores:
        scores_by_item.setdefault(s.item_id, {})[s.metric_name] = s
    return all_items, scores_by_item


def _ordered_unique(values: List[str]) -> List[str]:
    seen: set[str] = set()
    ordered: List[str] = []
    for value in values:
        normalized = str(value or "").strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        ordered.append(normalized)
    return ordered


def _approved_correction_categories(correction: ReviewCorrection) -> list[str]:
    """Return the categories represented by an approved correction example."""
    return normalize_root_causes(
        correction.human_root_causes
        or correction.human_root_cause
        or correction.ai_root_causes
        or correction.ai_root_cause
    )


def _category_example_counts(
    corrections: list[ReviewCorrection],
) -> dict[str, int]:
    """Count approved correction examples once for every category they carry."""
    counts: dict[str, int] = {}
    for correction in corrections:
        for category in _approved_correction_categories(correction):
            counts[category] = counts.get(category, 0) + 1
    return counts


def _approved_category_example_counts(
    db: Session,
    run: Run | _ProjectAnalysisScope,
) -> dict[str, int]:
    """Load the active approved-example counts for a run or project scope."""
    corrections_query = (
        db.query(ReviewCorrection)
        .join(Run, Run.id == ReviewCorrection.run_id)
        .filter(
            Run.project_id == run.project_id,
            Run.deleted_at.is_(None),
            ReviewCorrection.status == CorrectionStatus.APPROVED,
            ReviewCorrection.is_active.is_(True),
        )
    )
    if not isinstance(run, _ProjectAnalysisScope):
        corrections_query = corrections_query.filter(
            ReviewCorrection.task == run.task
        )
    return _category_example_counts(corrections_query.all())


def _collect_task_root_cause_catalog(
    db: Session,
    run: Run | _ProjectAnalysisScope,
    items: List[RunItem],
) -> tuple[List[str], Dict[str, List[str]]]:
    """Collect root-cause categories and a category→details mapping from approved corrections."""
    corrections_query = (
        db.query(ReviewCorrection)
        .join(Run, Run.id == ReviewCorrection.run_id)
        .filter(
            Run.project_id == run.project_id,
            Run.deleted_at.is_(None),
            ReviewCorrection.status == CorrectionStatus.APPROVED,
            ReviewCorrection.is_active.is_(True),
        )
        .order_by(ReviewCorrection.created_at.desc())
    )
    if not isinstance(run, _ProjectAnalysisScope):
        corrections_query = corrections_query.filter(ReviewCorrection.task == run.task)
    task_corrections = corrections_query.all()

    correction_categories: list[str] = []
    # Build category → details mapping from approved corrections
    cat_details_map: Dict[str, List[str]] = {}
    for correction in task_corrections:
        categories = normalize_root_causes(
            correction.human_root_causes
            or correction.human_root_cause
        )
        detail = correction.human_root_cause_detail or ""
        if categories:
            correction_categories.extend(categories)
            if detail:
                for category in categories:
                    cat_details_map.setdefault(category, []).append(detail)

    # Include categories already present on this run even before a review
    # candidate has been approved, so the analyzer can preserve current
    # vocabulary when re-running or aggregating a run.
    for item in items:
        metadata = item.item_metadata if isinstance(item.item_metadata, dict) else {}
        for analysis in [metadata, *(
            value
            for value in (metadata.get("metric_analyses") or {}).values()
            if isinstance(value, dict)
        )]:
            correction_categories.extend(analysis_root_causes(analysis))
            detail = str(analysis.get("root_cause_detail") or "").strip()
            for category in analysis_root_causes(analysis):
                if detail:
                    cat_details_map.setdefault(category, []).append(detail)

    all_categories = _ordered_unique(
        list(ROOT_CAUSE_CATEGORIES) + correction_categories
    )

    # De-duplicate details within each category while preserving order
    for cat in cat_details_map:
        cat_details_map[cat] = _ordered_unique(cat_details_map[cat])

    return all_categories, cat_details_map


def _collect_task_root_cause_taxonomy(
    db: Session,
    run: Run | _ProjectAnalysisScope,
    items: List[RunItem],
) -> Dict[str, Dict[str, str]]:
    """Collect built-in and learned category definitions for analyzer prompts."""
    corrections_query = (
        db.query(ReviewCorrection)
        .join(Run, Run.id == ReviewCorrection.run_id)
        .filter(
            Run.project_id == run.project_id,
            Run.deleted_at.is_(None),
            ReviewCorrection.status == CorrectionStatus.APPROVED,
            ReviewCorrection.is_active.is_(True),
        )
        .order_by(ReviewCorrection.created_at.desc(), ReviewCorrection.id.desc())
    )
    if not isinstance(run, _ProjectAnalysisScope):
        corrections_query = corrections_query.filter(ReviewCorrection.task == run.task)
    task_corrections = corrections_query.all()

    # Older corrections do not have taxonomy columns, so use getattr for
    # compatibility with long-lived workers during a rolling migration.
    learned: list[Any] = []
    for correction in reversed(task_corrections):
        learned.append(
            getattr(correction, "ai_category_taxonomy", None)
        )
        learned.append(
            getattr(correction, "human_category_taxonomy", None)
        )

    for item in items:
        metadata = item.item_metadata if isinstance(item.item_metadata, dict) else {}
        learned.append(metadata.get("category_taxonomy"))
        metric_analyses = metadata.get("metric_analyses")
        if isinstance(metric_analyses, dict):
            learned.extend(
                analysis.get("category_taxonomy")
                for analysis in metric_analyses.values()
                if isinstance(analysis, dict)
            )

    return merge_category_taxonomies(DEFAULT_ROOT_CAUSE_TAXONOMY, *learned)


_CATEGORY_CATALOG_SYNTHETIC_PREFIX = "legacy:"


def _synthetic_category_catalog_id(project_id: str) -> str:
    return _CATEGORY_CATALOG_SYNTHETIC_PREFIX + str(project_id)


def _catalog_label(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()[:200]


def _normalize_category_details_map(
    value: Any,
    categories: list[str],
) -> dict[str, list[str]]:
    """Normalize details onto the canonical category spelling and bound input."""
    raw_map = value if isinstance(value, dict) else {}
    by_fold = {category.casefold(): category for category in categories}
    details: dict[str, list[str]] = {}
    for raw_category, raw_details in raw_map.items():
        category = by_fold.get(_catalog_label(raw_category).casefold())
        if not category or not isinstance(raw_details, (list, tuple, set)):
            continue
        seen: set[str] = set()
        normalized: list[str] = []
        for raw_detail in raw_details:
            detail = _catalog_label(raw_detail)
            key = detail.casefold()
            if not detail or key in seen:
                continue
            seen.add(key)
            normalized.append(detail)
            if len(normalized) >= 500:
                break
        if normalized:
            details[category] = normalized
    return details


def _catalog_entries_for_categories(
    categories: list[str],
    *,
    requested_entries: Any = None,
    prior_entries: Any = None,
    project_id: str,
) -> list[dict[str, str]]:
    """Assign stable IDs while retaining prior labels as archived entries."""
    requested_by_fold: dict[str, dict[str, Any]] = {}
    for raw_entry in requested_entries or []:
        if isinstance(raw_entry, CategoryCatalogEntry):
            entry = raw_entry.model_dump(exclude_none=True)
        elif isinstance(raw_entry, dict):
            entry = raw_entry
        else:
            continue
        label = _catalog_label(entry.get("label"))
        if label:
            requested_by_fold.setdefault(label.casefold(), entry)

    prior_by_fold: dict[str, dict[str, Any]] = {}
    for raw_entry in prior_entries or []:
        if not isinstance(raw_entry, dict):
            continue
        label = _catalog_label(raw_entry.get("label"))
        if label:
            prior_by_fold.setdefault(label.casefold(), raw_entry)

    result: list[dict[str, str]] = []
    active_folds = {category.casefold() for category in categories}
    for category in categories:
        requested = requested_by_fold.get(category.casefold(), {})
        prior = prior_by_fold.get(category.casefold(), {})
        entry_id = _catalog_label(requested.get("id")) or _catalog_label(
            prior.get("id")
        )
        if not entry_id:
            entry_id = str(
                uuid5(NAMESPACE_URL, f"qym-category:{project_id}:{category.casefold()}")
            )
        result.append({"id": entry_id, "label": category, "status": "active"})

    # Keep an audit-friendly record for labels removed from the active catalog.
    # A later re-add reuses the archived ID instead of creating a new identity.
    archived: dict[str, dict[str, str]] = {}
    for raw_entry in list(prior_entries or []) + list(requested_entries or []):
        if isinstance(raw_entry, CategoryCatalogEntry):
            entry = raw_entry.model_dump(exclude_none=True)
        elif isinstance(raw_entry, dict):
            entry = raw_entry
        else:
            continue
        label = _catalog_label(entry.get("label"))
        folded = label.casefold()
        if not label or folded in active_folds or folded in archived:
            continue
        entry_id = _catalog_label(entry.get("id")) or str(
            uuid5(NAMESPACE_URL, f"qym-category:{project_id}:{folded}")
        )
        archived[folded] = {
            "id": entry_id,
            "label": label,
            "status": "archived",
        }
    result.extend(archived.values())
    return result


def _category_catalog_hash(
    *,
    categories: list[str],
    category_entries: list[dict[str, str]],
    category_details_map: dict[str, list[str]],
    category_taxonomy: dict[str, dict[str, str]],
    max_root_cause_categories: int,
) -> str:
    payload = {
        "categories": categories,
        "category_entries": category_entries,
        "category_details_map": category_details_map,
        "category_taxonomy": category_taxonomy,
        "max_root_cause_categories": max_root_cause_categories,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
            "utf-8"
        )
    ).hexdigest()


def _synthetic_category_catalog(
    db: Session,
    project_id: str,
) -> dict[str, Any]:
    """Expose pre-versioning project labels as a stable read-only v0."""
    scope = _ProjectAnalysisScope(
        id=_synthetic_category_catalog_id(project_id), project_id=project_id
    )
    legacy_items = (
        db.query(RunItem)
        .join(Run, Run.id == RunItem.run_id)
        .filter(Run.project_id == project_id, Run.deleted_at.is_(None))
        .all()
    )
    categories, details = _collect_task_root_cause_catalog(
        db, scope, legacy_items
    )
    taxonomy = _collect_task_root_cause_taxonomy(db, scope, legacy_items)
    entries = _catalog_entries_for_categories(
        categories,
        prior_entries=[],
        project_id=project_id,
    )
    return {
        "id": _synthetic_category_catalog_id(project_id),
        "project_id": project_id,
        "version": 0,
        "categories": categories,
        "category_entries": entries,
        "category_details_map": details,
        "category_taxonomy": taxonomy,
        "max_root_cause_categories": DEFAULT_MAX_ROOT_CAUSE_CATEGORIES,
        "content_hash": _category_catalog_hash(
            categories=categories,
            category_entries=entries,
            category_details_map=details,
            category_taxonomy=taxonomy,
            max_root_cause_categories=DEFAULT_MAX_ROOT_CAUSE_CATEGORIES,
        ),
        "source": "legacy",
        "parent_version_id": None,
        "restored_from_version_id": None,
        "is_active": False,
        "is_synthetic": True,
        "is_read_only": True,
        "created_by_user_id": None,
        "created_at": None,
    }


def _active_category_catalog(
    db: Session,
    project_id: str,
) -> ProjectAnalysisCategoryCatalogVersion | None:
    return (
        db.query(ProjectAnalysisCategoryCatalogVersion)
        .filter(
            ProjectAnalysisCategoryCatalogVersion.project_id == project_id,
            ProjectAnalysisCategoryCatalogVersion.is_active.is_(True),
        )
        .order_by(ProjectAnalysisCategoryCatalogVersion.version.desc())
        .first()
    )


def _category_catalog_reference(
    db: Session,
    project_id: str,
    reference: Any = None,
) -> ProjectAnalysisCategoryCatalogVersion | dict[str, Any]:
    """Resolve active, historic, numeric, UUID, or synthetic catalog refs."""
    clean = str(reference or "").strip()
    if not clean or clean in {"0", "v0", "legacy"} or clean == _synthetic_category_catalog_id(
        project_id
    ):
        if clean:
            return _synthetic_category_catalog(db, project_id)
        active = _active_category_catalog(db, project_id)
        return active or _synthetic_category_catalog(db, project_id)

    by_id = (
        db.query(ProjectAnalysisCategoryCatalogVersion)
        .filter(
            ProjectAnalysisCategoryCatalogVersion.project_id == project_id,
            ProjectAnalysisCategoryCatalogVersion.id == clean,
        )
        .first()
    )
    if by_id is not None:
        return by_id

    number = clean[1:] if clean.lower().startswith("v") else clean
    if number.isdigit():
        version = (
            db.query(ProjectAnalysisCategoryCatalogVersion)
            .filter(
                ProjectAnalysisCategoryCatalogVersion.project_id == project_id,
                ProjectAnalysisCategoryCatalogVersion.version == int(number),
            )
            .first()
        )
        if version is not None:
            return version
        if int(number) == 0:
            return _synthetic_category_catalog(db, project_id)
    raise HTTPException(status_code=404, detail="Analysis category catalog version not found")


def _category_catalog_values(
    catalog: ProjectAnalysisCategoryCatalogVersion | dict[str, Any],
) -> dict[str, Any]:
    if isinstance(catalog, dict):
        return {
            "id": catalog.get("id"),
            "version": int(catalog.get("version") or 0),
            "categories": list(catalog.get("categories") or []),
            "category_entries": list(catalog.get("category_entries") or []),
            "category_details_map": dict(catalog.get("category_details_map") or {}),
            "category_taxonomy": dict(catalog.get("category_taxonomy") or {}),
            "max_root_cause_categories": int(
                catalog.get("max_root_cause_categories")
                or DEFAULT_MAX_ROOT_CAUSE_CATEGORIES
            ),
        }
    return {
        "id": catalog.id,
        "version": int(catalog.version),
        "categories": list(catalog.categories or []),
        "category_entries": list(catalog.category_entries or []),
        "category_details_map": dict(catalog.category_details_map or {}),
        "category_taxonomy": dict(catalog.category_taxonomy or {}),
        "max_root_cause_categories": int(
            catalog.max_root_cause_categories or DEFAULT_MAX_ROOT_CAUSE_CATEGORIES
        ),
    }


def _category_catalog_payload(
    catalog: ProjectAnalysisCategoryCatalogVersion | dict[str, Any],
    *,
    can_manage: bool,
) -> dict[str, Any]:
    values = _category_catalog_values(catalog)
    if isinstance(catalog, dict):
        extra = catalog
    else:
        extra = {
            "project_id": catalog.project_id,
            "content_hash": catalog.content_hash,
            "source": catalog.source,
            "parent_version_id": catalog.parent_version_id,
            "restored_from_version_id": catalog.restored_from_version_id,
            "is_active": catalog.is_active,
            "is_synthetic": False,
            "is_read_only": False,
            "created_by_user_id": catalog.created_by_user_id,
            "created_at": to_api_timestamp(catalog.created_at),
        }
    return {
        **values,
        "project_id": extra.get("project_id"),
        "content_hash": extra.get("content_hash", ""),
        "source": extra.get("source", "manual"),
        "parent_version_id": extra.get("parent_version_id"),
        "restored_from_version_id": extra.get("restored_from_version_id"),
        "is_active": bool(extra.get("is_active", False)),
        "is_synthetic": bool(extra.get("is_synthetic", False)),
        "is_read_only": bool(extra.get("is_read_only", False)),
        "created_by_user_id": extra.get("created_by_user_id"),
        "created_at": extra.get("created_at"),
        "can_manage": can_manage,
    }


def _catalog_request_values(
    db: Session,
    project_id: str,
    request: CategoryCatalogUpdate,
    prior: ProjectAnalysisCategoryCatalogVersion | dict[str, Any],
) -> dict[str, Any]:
    categories = normalize_root_causes(request.categories)
    if len(categories) > 100:
        categories = categories[:100]
    prior_values = _category_catalog_values(prior)
    entries = _catalog_entries_for_categories(
        categories,
        requested_entries=request.category_entries,
        prior_entries=prior_values.get("category_entries"),
        project_id=project_id,
    )
    details = _normalize_category_details_map(request.category_details_map, categories)
    taxonomy = normalize_category_taxonomy(
        {
            category: definition.model_dump()
            for category, definition in request.category_taxonomy.items()
        }
    )
    max_categories = max(1, min(int(request.max_root_cause_categories), 10))
    return {
        "categories": categories,
        "category_entries": entries,
        "category_details_map": details,
        "category_taxonomy": taxonomy,
        "max_root_cause_categories": max_categories,
        "content_hash": _category_catalog_hash(
            categories=categories,
            category_entries=entries,
            category_details_map=details,
            category_taxonomy=taxonomy,
            max_root_cause_categories=max_categories,
        ),
    }


def _catalog_conflict(
    db: Session,
    project_id: str,
    principal: Principal,
    current: ProjectAnalysisCategoryCatalogVersion | None,
) -> HTTPException:
    current_catalog = current or _synthetic_category_catalog(db, project_id)
    return HTTPException(
        status_code=409,
        detail={
            "code": "catalog_version_conflict",
            "message": "The diagnosis category catalog changed. Reload it before saving.",
            "current_catalog": _category_catalog_payload(
                current_catalog,
                can_manage=is_project_manager(db, principal, project_id),
            ),
        },
    )


def _create_category_catalog_version(
    db: Session,
    *,
    project_id: str,
    values: dict[str, Any],
    parent: ProjectAnalysisCategoryCatalogVersion | None,
    restored_from: ProjectAnalysisCategoryCatalogVersion | None,
    actor_user_id: str | None,
    source: str = "manual",
) -> ProjectAnalysisCategoryCatalogVersion:
    current = _active_category_catalog(db, project_id)
    if current is not None:
        current.is_active = False
    latest = (
        db.query(func.max(ProjectAnalysisCategoryCatalogVersion.version))
        .filter(ProjectAnalysisCategoryCatalogVersion.project_id == project_id)
        .scalar()
        or 0
    )
    version = ProjectAnalysisCategoryCatalogVersion(
        project_id=project_id,
        version=int(latest) + 1,
        categories=values["categories"],
        category_entries=values["category_entries"],
        category_details_map=values["category_details_map"],
        category_taxonomy=values["category_taxonomy"],
        max_root_cause_categories=values["max_root_cause_categories"],
        content_hash=values["content_hash"],
        source=source,
        parent_version_id=parent.id if parent is not None else None,
        restored_from_version_id=restored_from.id if restored_from is not None else None,
        is_active=True,
        created_by_user_id=actor_user_id,
        created_at=utc_now_naive(),
    )
    db.add(version)
    db.flush()
    return version


def _analysis_config_with_category_catalog(
    db: Session,
    run: Run,
    items: List[RunItem],
    analyzer_config: dict[str, Any] | None,
    catalog_reference: Any = None,
) -> dict[str, Any] | None:
    """Add the active project category catalog without overriding explicit edits."""
    config = dict(analyzer_config or {})
    reference = catalog_reference
    if reference is None:
        reference = config.get("category_catalog_version_id")
    if reference is None:
        reference = config.get("category_catalog_version")
    catalog = _category_catalog_reference(db, run.project_id, reference)
    values = _category_catalog_values(catalog)
    if "root_cause_categories" not in config:
        config["root_cause_categories"] = _ordered_unique(
            list(values["categories"]) + list(values["category_taxonomy"].keys())
        )
    if "category_details_map" not in config:
        config["category_details_map"] = values["category_details_map"]
    config["category_taxonomy"] = merge_category_taxonomies(
        values["category_taxonomy"], config.get("category_taxonomy")
    )
    if "max_root_cause_categories" not in config:
        config["max_root_cause_categories"] = values["max_root_cause_categories"]
    if "category_example_counts" not in config:
        config["category_example_counts"] = _approved_category_example_counts(
            db, run
        )
    config["category_catalog_version"] = values["version"]
    config["category_catalog_version_id"] = values["id"]
    return config or None


def _analysis_result_payload(result: AnalysisResult) -> Dict[str, Any]:
    return {
        "item_id": result.item_id,
        "metric_name": result.metric_name,
        "root_cause": result.root_cause,
        "root_causes": normalize_root_causes(
            getattr(result, "root_causes", None) or result.root_cause
        ),
        "category_taxonomy": normalize_category_taxonomy(
            getattr(result, "category_taxonomy", None)
        ),
        "root_cause_detail": result.root_cause_detail,
        "root_cause_reason": result.root_cause_reason,
        "root_cause_note": result.root_cause_note,
        "confidence": result.confidence,
        "solution": result.solution,
        "solution_note": result.solution_note,
        "warning": result.warning,
        "error": result.error,
        "analyzer_model": result.analyzer_model,
        "prompt_hash": result.prompt_hash,
        "provider_request_id": result.provider_request_id,
        "usage": {
            "prompt_tokens": result.prompt_tokens,
            "completion_tokens": result.completion_tokens,
            "total_tokens": result.total_tokens,
        },
    }


def _category_counts(results: List[AnalysisResult]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for result in results:
        categories = normalize_root_causes(
            getattr(result, "root_causes", None) or result.root_cause
        )
        if result.error or not categories:
            continue
        for category in categories:
            counts[category] = counts.get(category, 0) + 1
    return counts


def _sync_item_analysis_warning(meta: dict[str, Any]) -> dict[str, Any]:
    """Keep the item-level warning aligned with saved metric analyses."""
    warnings: list[str] = []
    metric_analyses = meta.get("metric_analyses")
    if isinstance(metric_analyses, dict):
        for analysis in metric_analyses.values():
            if not isinstance(analysis, dict):
                continue
            warning = str(analysis.get("warning") or "").strip()
            if warning and warning not in warnings:
                warnings.append(warning)
    if warnings:
        meta["analysis_warning"] = "; ".join(warnings)
    else:
        meta.pop("analysis_warning", None)
    return meta


@dataclass
class _PersistedAnalysisBinding:
    item: RunItem
    metric_name: str | None
    result: AnalysisResult
    original_root_cause: str
    original_root_cause_detail: str
    original_solution: str
    original_root_causes: tuple[str, ...] = ()
    original_category_taxonomy: dict[str, dict[str, str]] | None = None


def _persisted_ai_analysis_bindings(
    items: list[RunItem],
    analysis_targets: list[tuple[RunItem, str]],
    overwritten_item_ids: set[str] | None = None,
    metric_scope: set[str] | None = None,
) -> list[_PersistedAnalysisBinding]:
    """Load saved AI labels that should participate in run-wide aggregation."""
    target_keys = {
        (item.item_id, metric_name) for item, metric_name in analysis_targets
    }
    target_item_ids = (
        overwritten_item_ids
        if overwritten_item_ids is not None
        else {item.item_id for item, _ in analysis_targets}
    )
    bindings: list[_PersistedAnalysisBinding] = []

    for item in items:
        meta = item.item_metadata if isinstance(item.item_metadata, dict) else {}
        root_causes = analysis_root_causes(meta)
        root_cause = root_causes[0] if root_causes else ""
        root_cause_detail = str(meta.get("root_cause_detail") or "").strip()
        root_cause_reason = str(meta.get("root_cause_reason") or "").strip()
        category_taxonomy = normalize_category_taxonomy(
            meta.get("category_taxonomy")
        )
        legacy_metric_name = str(meta.get("root_cause_metric_name") or "").strip()
        metric_analyses = meta.get("metric_analyses")
        valid_metric_analyses = (
            {
                metric_name: analysis
                for metric_name, analysis in metric_analyses.items()
                if (metric_scope is None or metric_name in metric_scope)
                if isinstance(analysis, dict)
                and analysis.get("source") == "ai"
                and not analysis.get("error")
                and analysis_root_causes(analysis)
            }
            if isinstance(metric_analyses, dict)
            else {}
        )
        legacy_metric_is_orphaned = bool(
            legacy_metric_name
            and legacy_metric_name not in valid_metric_analyses
        )
        if (
            root_cause
            and meta.get("root_cause_source") == "ai"
            and metric_scope is None
            and item.item_id not in target_item_ids
            and not valid_metric_analyses
            and not legacy_metric_is_orphaned
        ):
            bindings.append(
                _PersistedAnalysisBinding(
                    item=item,
                    metric_name=None,
                    result=AnalysisResult(
                        item_id=item.item_id,
                        root_cause=root_cause,
                        root_causes=root_causes,
                        category_taxonomy=category_taxonomy,
                        root_cause_detail=root_cause_detail,
                        root_cause_reason=root_cause_reason,
                        root_cause_note=str(meta.get("root_cause_note") or ""),
                        confidence=float(meta.get("root_cause_confidence") or 0.0),
                        solution=str(meta.get("solution") or ""),
                        solution_note=str(meta.get("solution_note") or ""),
                    ),
                    original_root_cause=root_cause,
                    original_root_cause_detail=root_cause_detail,
                    original_solution=str(meta.get("solution") or ""),
                    original_root_causes=tuple(root_causes),
                    original_category_taxonomy=category_taxonomy,
                )
            )

        for metric_name, raw_analysis in valid_metric_analyses.items():
            if (item.item_id, metric_name) in target_keys:
                continue
            metric_root_causes = analysis_root_causes(raw_analysis)
            metric_root_cause = metric_root_causes[0] if metric_root_causes else ""
            metric_detail = str(raw_analysis.get("root_cause_detail") or "").strip()
            metric_reason = str(raw_analysis.get("root_cause_reason") or "").strip()
            metric_taxonomy = normalize_category_taxonomy(
                raw_analysis.get("category_taxonomy")
            )
            bindings.append(
                _PersistedAnalysisBinding(
                    item=item,
                    metric_name=metric_name,
                    result=AnalysisResult(
                        item_id=item.item_id,
                        metric_name=metric_name,
                        root_cause=metric_root_cause,
                        root_causes=metric_root_causes,
                        category_taxonomy=metric_taxonomy,
                        root_cause_detail=metric_detail,
                        root_cause_reason=metric_reason,
                        root_cause_note=str(raw_analysis.get("root_cause_note") or ""),
                        confidence=float(raw_analysis.get("confidence") or 0.0),
                        solution=str(raw_analysis.get("solution") or ""),
                        solution_note=str(raw_analysis.get("solution_note") or ""),
                    ),
                    original_root_cause=metric_root_cause,
                    original_root_cause_detail=metric_detail,
                    original_solution=str(raw_analysis.get("solution") or ""),
                    original_root_causes=tuple(metric_root_causes),
                    original_category_taxonomy=metric_taxonomy,
                )
            )

    return bindings


def _persist_aggregated_bindings(
    db: Session,
    run: Run,
    bindings: list[_PersistedAnalysisBinding],
    principal: Principal,
) -> int:
    """Persist canonical labels while leaving feedback and solution notes unchanged."""
    changed = [
        binding
        for binding in bindings
        if (
            tuple(
                normalize_root_causes(
                    getattr(binding.result, "root_causes", None)
                    or binding.result.root_cause
                )
            )
            != binding.original_root_causes
            or binding.result.root_cause != binding.original_root_cause
            or binding.result.root_cause_detail != binding.original_root_cause_detail
            or binding.result.solution != binding.original_solution
            or normalize_category_taxonomy(
                getattr(binding.result, "category_taxonomy", None)
            )
            != (binding.original_category_taxonomy or {})
        )
    ]
    actor_user_id = principal.user.id if principal.auth_type != "none" else None

    for binding in changed:
        if binding.metric_name is not None:
            continue
        state = extract_analysis_state(
            binding.item.item_metadata
            if isinstance(binding.item.item_metadata, dict)
            else {}
        )
        state["root_cause"] = binding.result.root_cause
        state["root_causes"] = normalize_root_causes(
            getattr(binding.result, "root_causes", None)
            or binding.result.root_cause
        )
        state["category_taxonomy"] = normalize_category_taxonomy(
            getattr(binding.result, "category_taxonomy", None)
        )
        state["root_cause_detail"] = binding.result.root_cause_detail
        state["root_cause_reason"] = binding.result.root_cause_reason
        state["solution"] = binding.result.solution
        apply_root_cause_change(
            db,
            run=run,
            item=binding.item,
            actor_user_id=actor_user_id,
            actor_source="ai",
            next_state=state,
        )

    metric_changes_by_item: dict[str, list[_PersistedAnalysisBinding]] = {}
    for binding in changed:
        if binding.metric_name is not None:
            metric_changes_by_item.setdefault(binding.item.item_id, []).append(binding)

    items_by_id = {binding.item.item_id: binding.item for binding in changed}
    for item_id, item_bindings in metric_changes_by_item.items():
        item = items_by_id[item_id]
        meta = dict(item.item_metadata) if isinstance(item.item_metadata, dict) else {}
        metric_analyses = dict(meta.get("metric_analyses") or {})
        for binding in item_bindings:
            analysis = dict(metric_analyses.get(binding.metric_name) or {})
            analysis["root_cause"] = binding.result.root_cause
            analysis["root_causes"] = normalize_root_causes(
                getattr(binding.result, "root_causes", None)
                or binding.result.root_cause
            )
            analysis["category_taxonomy"] = normalize_category_taxonomy(
                getattr(binding.result, "category_taxonomy", None)
            )
            analysis["root_cause_detail"] = binding.result.root_cause_detail
            analysis["root_cause_reason"] = binding.result.root_cause_reason
            analysis["solution"] = binding.result.solution
            metric_analyses[binding.metric_name] = analysis
            if (
                meta.get("root_cause_source") == "ai"
                and meta.get("root_cause_metric_name") == binding.metric_name
            ):
                meta["root_cause"] = binding.result.root_cause
                meta["root_causes"] = analysis["root_causes"]
                meta["category_taxonomy"] = analysis["category_taxonomy"]
                meta["root_cause_detail"] = binding.result.root_cause_detail
                meta["root_cause_reason"] = binding.result.root_cause_reason
                meta["solution"] = binding.result.solution
        meta["metric_analyses"] = metric_analyses
        item.item_metadata = meta
        actor_user_id = principal.user.id if principal.auth_type != "none" else None
        for binding in item_bindings:
            replace_metric_review_candidate(
                db,
                run=run,
                item=item,
                metric_name=binding.metric_name or "",
                analysis=metric_analyses[binding.metric_name],
                actor_user_id=actor_user_id,
                actor_source="ai",
            )

    return len(changed)


async def _aggregate_run_analysis_results(
    *,
    db: Session,
    run: Run,
    all_items: list[RunItem],
    analysis_targets: list[tuple[RunItem, str]],
    new_results: list[AnalysisResult],
    client: Any,
    model: str,
    analyzer_config: dict[str, Any] | None,
    principal: Principal,
    metric_scope: set[str] | None = None,
    force: bool = False,
) -> tuple[dict[str, int], int]:
    """Aggregate new and previously saved AI labels across the entire run."""
    successful_item_ids = {result.item_id for result in new_results if not result.error}
    bindings = _persisted_ai_analysis_bindings(
        all_items,
        analysis_targets,
        overwritten_item_ids=successful_item_ids,
        metric_scope=metric_scope,
    )
    combined_results = [*new_results, *(binding.result for binding in bindings)]
    if not combined_results:
        if force:
            _record_run_aggregation_status(
                run,
                status="succeeded",
                metric_scope=metric_scope,
                aggregated=0,
            )
        return {}, 0
    if not analysis_targets and not new_results and not force:
        return _category_counts(combined_results), 0

    labels_before = [
        (
            tuple(
                normalize_root_causes(
                    getattr(result, "root_causes", None) or result.root_cause
                )
            ),
            result.root_cause_detail,
            result.solution,
            normalize_category_taxonomy(
                getattr(result, "category_taxonomy", None)
            ),
        )
        for result in combined_results
    ]
    try:
        categories = await aggregate_analysis_categories(
            client,
            model,
            combined_results,
            known_categories=(analyzer_config or {}).get("root_cause_categories")
            or ROOT_CAUSE_CATEGORIES,
            known_details=(analyzer_config or {}).get("root_cause_details") or [],
            known_category_details=(analyzer_config or {}).get("category_details_map")
            or {},
            system_prompt=(analyzer_config or {}).get("_aggregator_system_prompt"),
        )
    except AnalysisAggregationError:
        for result, before in zip(combined_results, labels_before):
            categories, detail, solution, category_taxonomy = before
            result.root_causes = list(categories)
            result.root_cause = categories[0] if categories else ""
            result.root_cause_detail = detail
            result.solution = solution
            result.category_taxonomy = category_taxonomy
        raise
    changed_new_results = sum(
        (
            tuple(
                normalize_root_causes(
                    getattr(result, "root_causes", None) or result.root_cause
                )
            ),
            result.root_cause_detail,
            result.solution,
            normalize_category_taxonomy(
                getattr(result, "category_taxonomy", None)
            ),
        )
        != before
        for result, before in zip(new_results, labels_before)
    )
    changed_saved_results = _persist_aggregated_bindings(
        db,
        run,
        bindings,
        principal,
    )
    aggregated = changed_new_results + changed_saved_results
    _record_run_aggregation_status(
        run,
        status="succeeded",
        metric_scope=metric_scope,
        aggregated=aggregated,
    )
    return categories, aggregated


def _record_run_aggregation_status(
    run: Run,
    *,
    status: Literal["succeeded", "failed"],
    metric_scope: set[str] | None,
    aggregated: int = 0,
    error: str | None = None,
) -> dict[str, Any]:
    """Persist the latest aggregation outcome for the run-detail UI."""
    payload: dict[str, Any] = {
        "status": status,
        "metrics": sorted(metric_scope) if metric_scope is not None else None,
        "aggregated": int(aggregated),
        "updated_at": to_api_timestamp(utc_now_naive()),
    }
    if error:
        payload["error"] = str(error)[:2000]
    metadata = dict(run.run_metadata) if isinstance(run.run_metadata, dict) else {}
    metadata["analysis_aggregation"] = payload
    run.run_metadata = metadata
    return payload


def _raw_run_analysis_counts(
    all_items: list[RunItem],
    analysis_targets: list[tuple[RunItem, str]],
    new_results: list[AnalysisResult],
    metric_scope: set[str] | None = None,
) -> Dict[str, int]:
    successful_item_ids = {result.item_id for result in new_results if not result.error}
    bindings = _persisted_ai_analysis_bindings(
        all_items,
        analysis_targets,
        overwritten_item_ids=successful_item_ids,
        metric_scope=metric_scope,
    )
    return _category_counts([*new_results, *(binding.result for binding in bindings)])


def _save_analysis_results(
    db: Session,
    run: Run,
    analysis_targets: list[tuple[RunItem, str]],
    results: list[AnalysisResult],
    principal: Principal,
    analyzer_connection_id: str | None = None,
    analyzer_rule_version_id: str | None = None,
    category_catalog_version: int | None = None,
    category_catalog_version_id: str | None = None,
    allow_human_overwrite: bool = False,
) -> tuple[list[Dict[str, Any]], int]:
    response_results: list[Dict[str, Any]] = []
    error_count = 0

    items_by_id = {item.item_id: item for item, _ in analysis_targets}
    results_by_item: dict[str, list[AnalysisResult]] = {}
    for result in results:
        results_by_item.setdefault(result.item_id, []).append(result)
        response_results.append(_analysis_result_payload(result))

    for item_id, item_results in results_by_item.items():
        item = items_by_id.get(item_id)
        if item is None:
            continue

        # The LLM call can run for a long time. Refresh the row so the guard
        # observes a human edit committed by another request during analysis.
        db.refresh(item)
        original_meta = (
            dict(item.item_metadata) if isinstance(item.item_metadata, dict) else {}
        )
        # Re-check ownership at the persistence boundary. Target selection
        # happens before the LLM call, so a reviewer can add a human label
        # while analysis is running. Never let that late edit be overwritten
        # unless the request explicitly opted into human-label replacement.
        persistable_results = [
            result
            for result in item_results
            if not (
                result.metric_name
                and not allow_human_overwrite
                and _is_human_metric_analysis(original_meta, result.metric_name)
            )
        ]
        successful = [result for result in persistable_results if not result.error]

        # Keep the legacy item-level summary for older consumers, but review
        # candidates are created independently for each metric below.
        primary_overwrites_legacy_human = False
        if successful and allow_human_overwrite:
            legacy_source = str(
                original_meta.get("root_cause_source") or ""
            ).strip().lower()
            legacy_metric = str(
                original_meta.get("root_cause_metric_name") or ""
            ).strip()
            primary_overwrites_legacy_human = (
                legacy_source == "human"
                and (
                    not legacy_metric
                    or legacy_metric == str(successful[0].metric_name or "").strip()
                )
            )
        if successful and (
            original_meta.get("root_cause_source") != "human"
            or primary_overwrites_legacy_human
        ):
            primary = successful[0]
            item.item_metadata = build_item_metadata(
                original_meta,
                build_ai_state(
                    root_cause=primary.root_cause,
                    root_causes=normalize_root_causes(
                        getattr(primary, "root_causes", None) or primary.root_cause
                    ),
                    root_cause_detail=primary.root_cause_detail,
                    root_cause_reason=primary.root_cause_reason,
                    root_cause_note=primary.root_cause_note,
                    confidence=primary.confidence,
                    solution=primary.solution,
                    solution_note=primary.solution_note,
                    category_taxonomy=merge_category_taxonomies(
                        original_meta.get("category_taxonomy"),
                        getattr(primary, "category_taxonomy", None),
                    ),
                ),
            )
            item.item_metadata["root_cause_metric_name"] = primary.metric_name

        meta = (
            dict(item.item_metadata)
            if isinstance(item.item_metadata, dict)
            else original_meta
        )
        metric_analyses = dict(meta.get("metric_analyses") or {})
        item_errors: list[str] = []
        for result in persistable_results:
            metric_name = str(result.metric_name or "").strip()
            if not metric_name:
                continue
            if result.error:
                error_count += 1
                item_errors.append(f"{metric_name}: {result.error}")
                metric_analyses[metric_name] = {
                    "source": "ai",
                    "error": result.error,
                    "analyzer_model": result.analyzer_model,
                    "analyzer_connection_id": analyzer_connection_id,
                    "analyzer_rule_version_id": analyzer_rule_version_id,
                    "category_catalog_version": category_catalog_version,
                    "category_catalog_version_id": category_catalog_version_id,
                    "prompt_hash": result.prompt_hash,
                }
                continue
            previous_metric_analysis = metric_analyses.get(metric_name)
            previous_metric_taxonomy = (
                previous_metric_analysis.get("category_taxonomy")
                if isinstance(previous_metric_analysis, dict)
                else None
            )
            metric_analyses[metric_name] = {
                "source": "ai",
                "root_cause": result.root_cause,
                "root_causes": normalize_root_causes(
                    getattr(result, "root_causes", None) or result.root_cause
                ),
                "root_cause_detail": result.root_cause_detail,
                "root_cause_reason": result.root_cause_reason,
                "root_cause_note": result.root_cause_note,
                "warning": result.warning or "",
                "category_taxonomy": merge_category_taxonomies(
                    previous_metric_taxonomy,
                    getattr(result, "category_taxonomy", None),
                ),
                "confidence": result.confidence,
                "solution": result.solution,
                "solution_note": result.solution_note,
                "analyzer_model": result.analyzer_model,
                "analyzer_connection_id": analyzer_connection_id,
                "analyzer_rule_version_id": analyzer_rule_version_id,
                "category_catalog_version": category_catalog_version,
                "category_catalog_version_id": category_catalog_version_id,
                "prompt_hash": result.prompt_hash,
                "provider_request_id": result.provider_request_id,
                "prompt_tokens": result.prompt_tokens,
                "completion_tokens": result.completion_tokens,
                "total_tokens": result.total_tokens,
                "analyzed_at": to_api_timestamp(utc_now_naive()),
            }
        if successful:
            taxonomy_sources = [meta.get("category_taxonomy")]
            taxonomy_sources.extend(
                getattr(result, "category_taxonomy", None)
                for result in successful
            )
            merged_taxonomy = merge_category_taxonomies(*taxonomy_sources)
            if merged_taxonomy:
                meta["category_taxonomy"] = merged_taxonomy
        meta["metric_analyses"] = metric_analyses
        _sync_item_analysis_warning(meta)
        for result in successful:
            warning = str(result.warning or "").strip()
            if not warning:
                continue
            existing_warning = str(meta.get("analysis_warning") or "").strip()
            if warning not in existing_warning:
                meta["analysis_warning"] = (
                    f"{existing_warning}; {warning}" if existing_warning else warning
                )
        if item_errors:
            meta["analysis_error"] = "; ".join(item_errors)
        else:
            meta.pop("analysis_error", None)
        item.item_metadata = meta
        actor_user_id = principal.user.id if principal.auth_type != "none" else None
        if successful:
            # Metric-scoped candidates supersede the old item-scoped review
            # candidate. Leaving both active makes the review workflow appear
            # to have one shared diagnosis even though every metric now has an
            # independent category, root cause, and feedback.
            legacy_candidates = (
                db.query(ReviewCorrection)
                .filter(
                    ReviewCorrection.run_id == run.id,
                    ReviewCorrection.item_id == item.item_id,
                    ReviewCorrection.metric_name.is_(None),
                    ReviewCorrection.is_active.is_(True),
                )
                .all()
            )
            for candidate in legacy_candidates:
                candidate.is_active = False
                candidate.status = CorrectionStatus.SUPERSEDED
        for result in successful:
            metric_name = str(result.metric_name or "").strip()
            if not metric_name:
                continue
            replace_metric_review_candidate(
                db,
                run=run,
                item=item,
                metric_name=metric_name,
                analysis=metric_analyses[metric_name],
                actor_user_id=actor_user_id,
                actor_source="ai",
            )

    db.commit()
    return response_results, error_count


def _load_metric_specs(db: Session, run: Run) -> dict[str, RunMetricSpec]:
    specs = (
        db.query(RunMetricSpec)
        .filter(RunMetricSpec.run_id == run.id)
        .order_by(RunMetricSpec.position.asc(), RunMetricSpec.id.asc())
        .all()
    )
    return {spec.metric_name: spec for spec in specs}


def _metric_passed(
    score: RunItemScore | None,
    spec: RunMetricSpec | None,
    fallback_threshold: float,
) -> bool:
    if score is None or score.score_numeric is None:
        return False
    threshold = (
        spec.pass_threshold
        if spec is not None and spec.pass_threshold is not None
        else fallback_threshold
    )
    direction = (
        str(spec.direction or "maximize").lower() if spec is not None else "maximize"
    )
    if direction in {"minimize", "lower", "lower_is_better"}:
        return score.score_numeric <= threshold
    return score.score_numeric >= threshold


def _is_human_metric_analysis(
    metadata: dict[str, Any] | None, metric_name: str
) -> bool:
    """Return whether a metric diagnosis is owned by a human reviewer.

    Newer rows store the source inside ``metric_analyses``. Older rows may only
    have the legacy item-level source, optionally tied to a metric by
    ``root_cause_metric_name``. Keep both representations protected while
    making the decision per metric rather than per item.
    """
    md = metadata if isinstance(metadata, dict) else {}
    metric = str(metric_name or "").strip()
    metric_analyses = md.get("metric_analyses")
    if isinstance(metric_analyses, dict):
        analysis = metric_analyses.get(metric)
        if isinstance(analysis, dict):
            source = str(
                analysis.get("source") or analysis.get("root_cause_source") or ""
            ).strip().lower()
            if source == "human":
                return True

    legacy_source = str(md.get("root_cause_source") or "").strip().lower()
    if legacy_source != "human":
        return False
    legacy_metric = str(md.get("root_cause_metric_name") or "").strip()
    return not legacy_metric or legacy_metric == metric


def _analysis_metric_names(
    run: Run,
    scores_by_item: dict[str, dict[str, RunItemScore]],
    requested_metric: str | list[str] | None,
) -> list[str]:
    if isinstance(requested_metric, list):
        return list(dict.fromkeys(requested_metric))
    if requested_metric:
        return [requested_metric]
    names = list(run.metrics or [])
    for item_scores in scores_by_item.values():
        for metric_name in item_scores:
            if metric_name not in names:
                names.append(metric_name)
    return names


def _requested_metric_scope(request: AnalyzeRequest) -> set[str] | None:
    if request.metrics is not None:
        return set(request.metrics)
    if request.metric:
        return {request.metric}
    return None


def _validate_requested_metric(
    run: Run,
    scores_by_item: dict[str, dict[str, RunItemScore]],
    requested_metric: str | list[str] | None,
) -> None:
    if requested_metric is None:
        return
    available = _analysis_metric_names(run, scores_by_item, None)
    requested = (
        list(dict.fromkeys(requested_metric))
        if isinstance(requested_metric, list)
        else [requested_metric]
    )
    unknown = [metric_name for metric_name in requested if metric_name not in available]
    if unknown:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unknown metric '{unknown[0]}'. Available metrics: "
                + (", ".join(available) if available else "none")
            ),
        )


def _filter_analysis_targets(
    run: Run,
    request: AnalyzeRequest,
    all_items: list[RunItem],
    scores_by_item: dict[str, dict[str, RunItemScore]],
    metric_specs: dict[str, RunMetricSpec],
) -> list[tuple[RunItem, str]]:
    requested_metrics: str | list[str] | None = (
        request.metrics if request.metrics is not None else request.metric
    )
    metrics = _analysis_metric_names(run, scores_by_item, requested_metrics)
    targets: list[tuple[RunItem, str]] = []

    for item in all_items:
        md = item.item_metadata if isinstance(item.item_metadata, dict) else {}

        if request.item_ids and item.item_id not in request.item_ids:
            continue

        is_error = bool(item.error)
        if request.item_filter == "errors" and not is_error:
            continue

        if request.complexity is not None:
            item_complexity = str(md.get("complexity", "")).lower()
            if item_complexity not in [c.lower() for c in request.complexity]:
                continue

        if request.domain is not None:
            item_domain = str(md.get("domain", "")).lower()
            if item_domain not in [d.lower() for d in request.domain]:
                continue

        if request.root_cause is not None:
            item_categories = analysis_root_causes(md)
            if "__none__" in request.root_cause and not item_categories:
                pass
            elif not any(category in request.root_cause for category in item_categories):
                continue

        item_scores = scores_by_item.get(item.item_id, {})
        metric_analyses = (
            md.get("metric_analyses")
            if isinstance(md.get("metric_analyses"), dict)
            else {}
        )
        for metric_name in metrics:
            score = item_scores.get(metric_name)
            passed = (
                False
                if is_error
                else _metric_passed(
                    score,
                    metric_specs.get(metric_name),
                    request.threshold,
                )
            )

            if request.item_filter == "failed" and passed:
                continue
            if request.item_filter == "passed" and (is_error or not passed):
                continue
            if request.max_score is not None and score is not None:
                direction = str(
                    getattr(metric_specs.get(metric_name), "direction", "maximize")
                    or "maximize"
                ).lower()
                # The UI's max-score severity filter is meaningful for the
                # normalized, higher-is-better metrics it was designed for.
                # Applying the same upper bound to minimize metrics would drop
                # their failures (which are necessarily the larger values).
                if direction not in {"minimize", "lower", "lower_is_better"}:
                    if (
                        score.score_numeric is not None
                        and score.score_numeric > request.max_score
                    ):
                        continue

            existing_analysis = metric_analyses.get(metric_name)
            is_human_analysis = _is_human_metric_analysis(md, metric_name)
            if is_human_analysis and not request.allow_human_overwrite:
                continue
            if (
                request.only_unanalyzed
                and not is_human_analysis
                and isinstance(existing_analysis, dict)
            ):
                if existing_analysis.get("root_cause"):
                    continue
            targets.append((item, metric_name))

    def severity_key(target: tuple[RunItem, str]) -> tuple[float, int, str]:
        item, metric_name = target
        score = scores_by_item.get(item.item_id, {}).get(metric_name)
        direction = str(
            getattr(metric_specs.get(metric_name), "direction", "maximize")
            or "maximize"
        ).lower()
        if item.error or score is None or score.score_numeric is None:
            severity = float("-inf")
        elif direction in {"minimize", "lower", "lower_is_better"}:
            severity = -float(score.score_numeric)
        else:
            severity = float(score.score_numeric)
        return severity, int(item.index or 0), metric_name

    targets.sort(key=severity_key)
    if request.limit is not None:
        # The UI presents one row per item, while the analyzer executes one
        # request per item/metric pair. Select the most severe items first,
        # then keep every selected metric for those items. Slicing the target
        # list directly makes a limit of one silently drop all but one metric
        # from an item, which makes the visible item limit appear unreliable.
        selected_item_ids: set[str] = set()
        for item, _ in targets:
            if item.item_id in selected_item_ids:
                continue
            if len(selected_item_ids) >= request.limit:
                break
            selected_item_ids.add(item.item_id)
        targets = [
            target for target in targets if target[0].item_id in selected_item_ids
        ]
    return targets


def _analysis_job_payload(job: AnalysisJob | None) -> dict[str, Any] | None:
    """Return a JSON-safe job snapshot for the UI status endpoints."""
    if job is None:
        return None
    payload = job.snapshot()
    for key in ("created_at", "updated_at", "completed_at"):
        payload[key] = to_api_timestamp(payload.get(key))
    return payload


async def _run_analysis_job(
    job: AnalysisJob,
    session_factory: Any = SessionLocal,
) -> dict[str, Any]:
    """Run and persist one analysis independently of the starting request."""
    request = AnalyzeRequest.model_validate(job.request_payload)

    # The request dependency's session is closed as soon as the 202 response is
    # returned. A background job must own a fresh session for its whole run.
    with session_factory() as db:
        run = Run.active(db).filter(Run.id == job.run_id).first()
        user = db.get(User, job.user_id)
        if run is None or user is None:
            raise RuntimeError("The run or analysis user no longer exists.")
        principal = Principal(user=user, auth_type=job.auth_type)
        if not _can_operate_analyzer(db, principal, run):
            raise RuntimeError("Analysis access is no longer available.")

        llm_config = _get_llm_config(db, run.project_id, request.connection_id)
        all_items, scores_by_item = _load_run_items_and_scores(db, run)
        metric_specs = _load_metric_specs(db, run)
        metric_scope = _requested_metric_scope(request)
        _validate_requested_metric(
            run,
            scores_by_item,
            request.metrics if request.metrics is not None else request.metric,
        )
        analysis_targets = _filter_analysis_targets(
            run,
            request,
            all_items,
            scores_by_item,
            metric_specs,
        )

        analyzer_config = _analysis_config_with_project_context(
            db,
            run,
            _playground_config_to_analyzer(request.config),
        )
        analyzer_config = _analysis_config_with_category_catalog(
            db,
            run,
            all_items,
            analyzer_config,
            request.category_catalog_version_id,
        )
        client = build_client(llm_config)
        model = llm_config.get("llm_model", "gpt-4o-mini")
        analysis_job_manager.update_progress(
            job,
            phase="analyzing" if analysis_targets else "aggregating",
            total=len(analysis_targets),
            completed=0,
            errors=0,
        )

        if not analysis_targets:
            try:
                categories, aggregated = await _aggregate_run_analysis_results(
                    db=db,
                    run=run,
                    all_items=all_items,
                    analysis_targets=[],
                    new_results=[],
                    client=client,
                    model=model,
                    analyzer_config=analyzer_config,
                    principal=principal,
                    metric_scope=metric_scope,
                )
                db.commit()
            except AnalysisAggregationError as exc:
                db.rollback()
                raise RuntimeError(str(exc)) from exc
            analysis_job_manager.update_progress(
                job,
                phase="completed",
                completed=0,
                total=0,
            )
            return {
                "total_analyzed": 0,
                "results": [],
                "categories": categories,
                "aggregated": aggregated,
                "errors": 0,
            }

        progress_errors = 0

        async def on_progress(
            result: AnalysisResult, completed: int, total_count: int
        ) -> None:
            nonlocal progress_errors
            if job.cancel_requested:
                raise asyncio.CancelledError()
            if result.error:
                progress_errors += 1
            analysis_job_manager.update_progress(
                job,
                phase="analyzing",
                completed=completed,
                total=total_count,
                errors=progress_errors,
                item_id=result.item_id,
                metric_name=result.metric_name,
            )

        results = await _analyze_targets_batch(
            client=client,
            model=model,
            targets=analysis_targets,
            scores_by_item=scores_by_item,
            corrections=[],
            concurrency=request.concurrency,
            config=analyzer_config,
            temperature=request.config.temperature if request.config else None,
            max_tokens=request.config.max_tokens if request.config else None,
            progress_callback=on_progress,
        )
        if job.cancel_requested:
            raise asyncio.CancelledError()

        analysis_job_manager.update_progress(
            job,
            phase="aggregating",
            completed=len(analysis_targets),
            total=len(analysis_targets),
            errors=progress_errors,
        )
        aggregation_error: str | None = None
        try:
            categories, aggregated = await _aggregate_run_analysis_results(
                db=db,
                run=run,
                all_items=all_items,
                analysis_targets=analysis_targets,
                new_results=results,
                client=client,
                model=model,
                analyzer_config=analyzer_config,
                principal=principal,
                metric_scope=metric_scope,
            )
        except AnalysisAggregationError as exc:
            db.rollback()
            _record_run_aggregation_status(
                run,
                status="failed",
                metric_scope=metric_scope,
                error=str(exc),
            )
            logger.warning("Analysis job aggregation failed for run %s: %s", job.run_id, exc)
            categories = _raw_run_analysis_counts(
                all_items,
                analysis_targets,
                results,
                metric_scope=metric_scope,
            )
            aggregated = 0
            aggregation_error = str(exc)

        response_results, error_count = _save_analysis_results(
            db,
            run,
            analysis_targets,
            results,
            principal,
            analyzer_connection_id=llm_config.get("connection_id"),
            analyzer_rule_version_id=(analyzer_config or {}).get(
                "_analysis_rule_version_id"
            ),
            category_catalog_version=(analyzer_config or {}).get(
                "category_catalog_version"
            ),
            category_catalog_version_id=(analyzer_config or {}).get(
                "category_catalog_version_id"
            ),
            allow_human_overwrite=request.allow_human_overwrite,
        )
        analysis_job_manager.update_progress(
            job,
            phase="completed",
            completed=len(analysis_targets),
            total=len(analysis_targets),
            errors=error_count,
        )
        return {
            "total_analyzed": len(results),
            "results": response_results,
            "categories": categories,
            "aggregated": aggregated,
            "aggregation_error": aggregation_error,
            "errors": error_count,
        }


def _analysis_config_with_project_context(
    db: Session,
    run: Run,
    analyzer_config: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Fill omitted request context from the project's saved analyzer settings."""
    config = dict(analyzer_config or {})
    include_rules = bool(config.pop("_include_project_rules", True))
    include_documents = bool(config.pop("_include_project_documents", True))
    project = db.get(Project, run.project_id)
    if project is not None:
        prompts = get_effective_analysis_prompts(db, project.id)
        # The playground may deliberately provide a one-off analyzer prompt.
        # Project settings remain the default for all other analyzer calls, while
        # the aggregator prompt is always resolved from the persisted project
        # settings for this request.
        if not str(config.get("system_prompt") or "").strip():
            config["system_prompt"] = prompts["llm_analyzer"]
        config["_aggregator_system_prompt"] = prompts["aggregator"]
        active_rules = _active_analysis_rule_version(db, project.id)
        if include_rules and not config.get("analysis_rules"):
            config["analysis_rules"] = (
                active_rules.rules if active_rules else []
            )
        elif not include_rules:
            config["analysis_rules"] = []
        if include_rules and active_rules and normalize_analysis_rules(
            config.get("analysis_rules")
        ) == normalize_analysis_rules(active_rules.rules):
            config["_analysis_rule_version_id"] = active_rules.id
    if not include_documents:
        config["reference_documents"] = []
    elif "reference_documents" not in config:
        project_documents = (
            db.query(AnalyzerDocument)
            .filter(
                AnalyzerDocument.project_id == run.project_id,
                AnalyzerDocument.enabled.is_(True),
            )
            .order_by(AnalyzerDocument.created_at.asc(), AnalyzerDocument.id.asc())
            .all()
        )
        config["reference_documents"] = [
            {"name": document.name, "content": document.content}
            for document in project_documents
        ]
    return config or None


async def _analyze_targets_batch(
    *,
    client: Any,
    model: str,
    targets: list[tuple[RunItem, str]],
    scores_by_item: dict[str, dict[str, RunItemScore]],
    corrections: list[ReviewCorrection],
    concurrency: int,
    config: dict[str, Any] | None,
    temperature: float | None,
    max_tokens: int | None,
    progress_callback: Any = None,
) -> list[AnalysisResult]:
    """Run the existing analyzer once for every item-metric target."""
    if _supports_metric_name_arg(analyze_items_batch):
        return await analyze_items_batch(
            client=client,
            model=model,
            items=[
                (item, scores_by_item.get(item.item_id, {}), metric_name)
                for item, metric_name in targets
            ],
            corrections=corrections,
            concurrency=concurrency,
            config=config,
            temperature=temperature,
            max_tokens=max_tokens,
            progress_callback=progress_callback,
        )

    # Compatibility for deployments that still provide the older analyzer
    # callable: adapt and invoke one target at a time so metric context is not
    # accidentally shared between targets.
    results: list[AnalysisResult] = []
    for completed, (item, metric_name) in enumerate(targets, start=1):
        item_scores = scores_by_item.get(item.item_id, {})
        adapted_item, adapted_config = _adapt_legacy_analyzer_inputs(
            item,
            item_scores,
            config,
            metric_name,
        )
        batch_results = await analyze_items_batch(
            client=client,
            model=model,
            items=[(adapted_item, item_scores)],
            corrections=corrections,
            concurrency=1,
            config=adapted_config,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        for result in batch_results:
            result.item_id = item.item_id
            result.metric_name = metric_name
            results.append(result)
            if progress_callback is not None:
                callback_result = progress_callback(result, completed, len(targets))
                if asyncio.iscoroutine(callback_result):
                    await callback_result
    return results


@router.post("/api/runs/{run_id:path}/aggregate-analysis")
async def aggregate_saved_analysis_results(
    run_id: str,
    request: AggregateAnalysisRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> Dict[str, Any]:
    """Canonicalize saved AI diagnoses without rerunning item analysis."""
    run = Run.active(db).filter(Run.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    if not _can_operate_analyzer(db, principal, run):
        raise HTTPException(status_code=403, detail="Access denied")

    all_items, scores_by_item = _load_run_items_and_scores(db, run)
    _validate_requested_metric(run, scores_by_item, request.metric)
    metric_scope = {request.metric} if request.metric else None
    llm_config = _get_llm_config(db, run.project_id, request.connection_id)
    analyzer_config = _analysis_config_with_project_context(
        db,
        run,
        None,
    )
    analyzer_config = _analysis_config_with_category_catalog(
        db,
        run,
        all_items,
        analyzer_config,
        request.category_catalog_version_id,
    )

    try:
        category_counts, aggregated = await _aggregate_run_analysis_results(
            db=db,
            run=run,
            all_items=all_items,
            analysis_targets=[],
            new_results=[],
            client=build_client(llm_config),
            model=llm_config.get("llm_model", "gpt-4o-mini"),
            analyzer_config=analyzer_config,
            principal=principal,
            metric_scope=metric_scope,
            force=True,
        )
        db.commit()
    except AnalysisAggregationError as exc:
        db.rollback()
        aggregation_status = _record_run_aggregation_status(
            run,
            status="failed",
            metric_scope=metric_scope,
            error=str(exc),
        )
        db.commit()
        logger.warning(
            "Saved analysis aggregation failed for run %s: %s", run_id, exc
        )
        raise HTTPException(
            status_code=502,
            detail=str(exc),
            headers={"X-Qym-Aggregation-Status": aggregation_status["status"]},
        ) from exc

    return {
        "status": "succeeded",
        "categories": category_counts,
        "aggregated": aggregated,
        "metric": request.metric,
    }


@router.post("/api/runs/{run_id:path}/analysis-jobs")
async def start_analysis_job(
    run_id: str,
    request: AnalyzeRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> JSONResponse:
    """Start analysis independently of the browser request lifecycle."""
    run = Run.active(db).filter(Run.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    if not _can_operate_analyzer(db, principal, run):
        raise HTTPException(status_code=403, detail="Access denied")

    # Validate the request before creating a background task so malformed
    # filters and missing connections are reported to the initiating page.
    _get_llm_config(db, run.project_id, request.connection_id)
    all_items, scores_by_item = _load_run_items_and_scores(db, run)
    metric_specs = _load_metric_specs(db, run)
    _validate_requested_metric(
        run,
        scores_by_item,
        request.metrics if request.metrics is not None else request.metric,
    )
    analysis_targets = _filter_analysis_targets(
        run,
        request,
        all_items,
        scores_by_item,
        metric_specs,
    )

    job_session_factory = sessionmaker(
        bind=db.get_bind(),
        autoflush=False,
        autocommit=False,
    )

    async def run_job(job: AnalysisJob) -> dict[str, Any]:
        return await _run_analysis_job(job, session_factory=job_session_factory)

    job, created = await analysis_job_manager.submit(
        run_id=run.id,
        user_id=principal.user.id,
        auth_type=principal.auth_type,
        request_payload=request.model_dump(mode="json", exclude_none=True),
        progress={
            "phase": "queued",
            "completed": 0,
            "total": len(analysis_targets),
            "errors": 0,
        },
        runner=run_job,
    )
    payload = _analysis_job_payload(job) or {}
    payload["created"] = created
    return JSONResponse(status_code=202 if created else 200, content=payload)


@router.get("/api/runs/{run_id:path}/analysis-jobs/active")
def get_active_analysis_job(
    run_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> Dict[str, Any]:
    """Return the active analysis so a newly opened page can resume it."""
    run = Run.active(db).filter(Run.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    if not _can_operate_analyzer(db, principal, run):
        raise HTTPException(status_code=403, detail="Access denied")
    return {"job": _analysis_job_payload(analysis_job_manager.active_for_run(run.id))}


@router.get("/api/runs/{run_id:path}/analysis-jobs/{job_id}")
def get_analysis_job(
    run_id: str,
    job_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> Dict[str, Any]:
    """Return one analysis job snapshot for polling."""
    run = Run.active(db).filter(Run.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    if not _can_operate_analyzer(db, principal, run):
        raise HTTPException(status_code=403, detail="Access denied")
    job = analysis_job_manager.get(job_id)
    if job is None or job.run_id != run.id:
        raise HTTPException(status_code=404, detail="Analysis job not found")
    return _analysis_job_payload(job) or {}


@router.post("/api/runs/{run_id:path}/analysis-jobs/{job_id}/cancel")
def cancel_analysis_job(
    run_id: str,
    job_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> Dict[str, Any]:
    """Request cancellation of a background analysis."""
    run = Run.active(db).filter(Run.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    if not _can_operate_analyzer(db, principal, run):
        raise HTTPException(status_code=403, detail="Access denied")
    job = analysis_job_manager.get(job_id)
    if job is None or job.run_id != run.id:
        raise HTTPException(status_code=404, detail="Analysis job not found")
    cancelled = analysis_job_manager.cancel(job_id)
    return _analysis_job_payload(cancelled) or {}


@router.post("/api/runs/{run_id:path}/analyze")
async def analyze_run_items(
    run_id: str,
    request: AnalyzeRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> Dict[str, Any]:
    """Trigger LLM-powered root cause analysis for selected items in a run."""
    run = Run.active(db).filter(Run.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    if not _can_operate_analyzer(db, principal, run):
        raise HTTPException(status_code=403, detail="Access denied")
    llm_config = _get_llm_config(db, run.project_id, request.connection_id)

    all_items, scores_by_item = _load_run_items_and_scores(db, run)

    metric_specs = _load_metric_specs(db, run)
    metric_scope = _requested_metric_scope(request)
    _validate_requested_metric(
        run,
        scores_by_item,
        request.metrics if request.metrics is not None else request.metric,
    )
    analysis_targets = _filter_analysis_targets(
        run,
        request,
        all_items,
        scores_by_item,
        metric_specs,
    )

    analyzer_config = _analysis_config_with_project_context(
        db,
        run,
        _playground_config_to_analyzer(request.config),
    )
    analyzer_config = _analysis_config_with_category_catalog(
        db,
        run,
        all_items,
        analyzer_config,
        request.category_catalog_version_id,
    )
    client = build_client(llm_config)
    model = llm_config.get("llm_model", "gpt-4o-mini")

    if not analysis_targets:
        try:
            categories, aggregated = await _aggregate_run_analysis_results(
                db=db,
                run=run,
                all_items=all_items,
                analysis_targets=[],
                new_results=[],
                client=client,
                model=model,
                analyzer_config=analyzer_config,
                principal=principal,
                metric_scope=metric_scope,
            )
            db.commit()
        except AnalysisAggregationError as exc:
            db.rollback()
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return {
            "total_analyzed": 0,
            "results": [],
            "categories": categories,
            "aggregated": aggregated,
            "errors": 0,
        }

    # Run async LLM analysis
    results = await _analyze_targets_batch(
        client=client,
        model=model,
        targets=analysis_targets,
        scores_by_item=scores_by_item,
        corrections=[],
        concurrency=request.concurrency,
        config=analyzer_config,
        temperature=request.config.temperature if request.config else None,
        max_tokens=request.config.max_tokens if request.config else None,
    )
    aggregation_error: str | None = None
    try:
        categories, aggregated = await _aggregate_run_analysis_results(
            db=db,
            run=run,
            all_items=all_items,
            analysis_targets=analysis_targets,
            new_results=results,
            client=client,
            model=model,
            analyzer_config=analyzer_config,
            principal=principal,
            metric_scope=metric_scope,
        )
    except AnalysisAggregationError as exc:
        db.rollback()
        _record_run_aggregation_status(
            run,
            status="failed",
            metric_scope=metric_scope,
            error=str(exc),
        )
        logger.warning("Analysis aggregation failed for run %s: %s", run_id, exc)
        categories = _raw_run_analysis_counts(
            all_items,
            analysis_targets,
            results,
            metric_scope=metric_scope,
        )
        aggregated = 0
        aggregation_error = str(exc)

    # Save per-metric results plus one backwards-compatible item summary.
    response_results, error_count = _save_analysis_results(
        db,
        run,
        analysis_targets,
        results,
        principal,
        analyzer_connection_id=llm_config.get("connection_id"),
        analyzer_rule_version_id=(analyzer_config or {}).get(
            "_analysis_rule_version_id"
        ),
        category_catalog_version=(analyzer_config or {}).get(
            "category_catalog_version"
        ),
        category_catalog_version_id=(analyzer_config or {}).get(
            "category_catalog_version_id"
        ),
        allow_human_overwrite=request.allow_human_overwrite,
    )

    return {
        "total_analyzed": len(results),
        "results": response_results,
        "categories": categories,
        "aggregated": aggregated,
        "aggregation_error": aggregation_error,
        "errors": error_count,
    }


@router.post("/api/runs/{run_id:path}/analyze-stream")
async def analyze_run_items_stream(
    run_id: str,
    request: AnalyzeRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> StreamingResponse:
    """Stream LLM-powered root cause analysis progress for selected items."""
    run = Run.active(db).filter(Run.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    if not _can_operate_analyzer(db, principal, run):
        raise HTTPException(status_code=403, detail="Access denied")
    llm_config = _get_llm_config(db, run.project_id, request.connection_id)

    all_items, scores_by_item = _load_run_items_and_scores(db, run)
    metric_specs = _load_metric_specs(db, run)
    metric_scope = _requested_metric_scope(request)
    _validate_requested_metric(
        run,
        scores_by_item,
        request.metrics if request.metrics is not None else request.metric,
    )
    analysis_targets = _filter_analysis_targets(
        run,
        request,
        all_items,
        scores_by_item,
        metric_specs,
    )

    async def stream_events():
        def encode(event: Dict[str, Any]) -> str:
            return json.dumps(event, ensure_ascii=False) + "\n"

        total = len(analysis_targets)
        yield encode(
            {
                "type": "started",
                "total": total,
                "completed": 0,
                "errors": 0,
                "concurrency": request.concurrency,
            }
        )

        analyzer_config = _analysis_config_with_project_context(
            db,
            run,
            _playground_config_to_analyzer(request.config),
        )
        analyzer_config = _analysis_config_with_category_catalog(
            db,
            run,
            all_items,
            analyzer_config,
            request.category_catalog_version_id,
        )
        client = build_client(llm_config)
        model = llm_config.get("llm_model", "gpt-4o-mini")

        if not analysis_targets:
            yield encode(
                {
                    "type": "aggregating",
                    "completed": 0,
                    "total": 0,
                    "errors": 0,
                }
            )
            try:
                categories, aggregated = await _aggregate_run_analysis_results(
                    db=db,
                    run=run,
                    all_items=all_items,
                    analysis_targets=[],
                    new_results=[],
                    client=client,
                    model=model,
                    analyzer_config=analyzer_config,
                    principal=principal,
                    metric_scope=metric_scope,
                )
                db.commit()
            except AnalysisAggregationError as exc:
                db.rollback()
                yield encode({"type": "error", "message": str(exc)})
                return
            yield encode(
                {
                    "type": "done",
                    "total_analyzed": 0,
                    "results": [],
                    "categories": categories,
                    "aggregated": aggregated,
                    "errors": 0,
                }
            )
            return

        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        progress_errors = 0

        async def on_progress(
            result: AnalysisResult, completed: int, total_count: int
        ) -> None:
            nonlocal progress_errors
            if result.error:
                progress_errors += 1
            await queue.put(
                {
                    "type": "progress",
                    "completed": completed,
                    "total": total_count,
                    "errors": progress_errors,
                    "item_id": result.item_id,
                    "metric_name": result.metric_name,
                    "root_cause": result.root_cause,
                    "root_causes": normalize_root_causes(
                        getattr(result, "root_causes", None) or result.root_cause
                    ),
                    "category_taxonomy": normalize_category_taxonomy(
                        getattr(result, "category_taxonomy", None)
                    ),
                    "root_cause_detail": result.root_cause_detail,
                    "root_cause_reason": result.root_cause_reason,
                    "warning": result.warning,
                    "error": result.error,
                }
            )

        async def run_batch() -> None:
            try:
                results = await _analyze_targets_batch(
                    client=client,
                    model=model,
                    targets=analysis_targets,
                    scores_by_item=scores_by_item,
                    corrections=[],
                    concurrency=request.concurrency,
                    config=analyzer_config,
                    temperature=request.config.temperature if request.config else None,
                    max_tokens=request.config.max_tokens if request.config else None,
                    progress_callback=on_progress,
                )
                await queue.put({"type": "_complete", "results": results})
            except Exception as exc:
                logger_msg = f"Analysis stream failed for run {run_id}: {exc}"
                await queue.put({"type": "error", "message": logger_msg})

        batch_task = asyncio.create_task(run_batch())
        try:
            while True:
                event = await queue.get()
                if event.get("type") == "_complete":
                    results = event["results"]
                    yield encode(
                        {
                            "type": "aggregating",
                            "completed": total,
                            "total": total,
                            "errors": progress_errors,
                        }
                    )
                    aggregation_error: str | None = None
                    try:
                        categories, aggregated = await _aggregate_run_analysis_results(
                            db=db,
                            run=run,
                            all_items=all_items,
                            analysis_targets=analysis_targets,
                            new_results=results,
                            client=client,
                            model=model,
                            analyzer_config=analyzer_config,
                            principal=principal,
                            metric_scope=metric_scope,
                        )
                    except AnalysisAggregationError as exc:
                        db.rollback()
                        _record_run_aggregation_status(
                            run,
                            status="failed",
                            metric_scope=metric_scope,
                            error=str(exc),
                        )
                        logger.warning(
                            "Analysis aggregation failed for run %s: %s",
                            run_id,
                            exc,
                        )
                        categories = _raw_run_analysis_counts(
                            all_items,
                            analysis_targets,
                            results,
                            metric_scope=metric_scope,
                        )
                        aggregated = 0
                        aggregation_error = str(exc)
                    try:
                        response_results, error_count = _save_analysis_results(
                            db,
                            run,
                            analysis_targets,
                            results,
                            principal,
                            analyzer_connection_id=llm_config.get("connection_id"),
                            analyzer_rule_version_id=(analyzer_config or {}).get(
                                "_analysis_rule_version_id"
                            ),
                            category_catalog_version=(analyzer_config or {}).get(
                                "category_catalog_version"
                            ),
                            category_catalog_version_id=(analyzer_config or {}).get(
                                "category_catalog_version_id"
                            ),
                            allow_human_overwrite=request.allow_human_overwrite,
                        )
                    except Exception as exc:
                        db.rollback()
                        yield encode(
                            {
                                "type": "error",
                                "message": f"Failed to save analysis results: {exc}",
                            }
                        )
                        break
                    yield encode(
                        {
                            "type": "done",
                            "total_analyzed": len(results),
                            "results": response_results,
                            "categories": categories,
                            "aggregated": aggregated,
                            "aggregation_error": aggregation_error,
                            "errors": error_count,
                        }
                    )
                    break
                yield encode(event)
                if event.get("type") == "error":
                    break
        finally:
            if not batch_task.done():
                batch_task.cancel()

    return StreamingResponse(
        stream_events(),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _analysis_document_payload(
    document: AnalyzerDocument,
    *,
    source_characters: Optional[int] = None,
) -> Dict[str, Any]:
    stored_characters = int(document.characters or len(document.content or ""))
    source_count = int(source_characters or stored_characters)
    return {
        "id": document.id,
        "name": document.name,
        "content": document.content,
        "characters": stored_characters,
        "source_characters": source_count,
        "truncated": document.truncated,
        "prompt_limit": MAX_REFERENCE_DOCUMENT_CHARS,
        "content_limit": MAX_REFERENCE_DOCUMENT_CONTENT_CHARS,
        "prompt_over_limit": stored_characters > MAX_REFERENCE_DOCUMENT_CHARS,
        "content_over_limit": bool(document.truncated and stored_characters >= MAX_REFERENCE_DOCUMENT_CONTENT_CHARS),
        "content_was_cut": bool(document.truncated and stored_characters >= MAX_REFERENCE_DOCUMENT_CONTENT_CHARS),
        "selected": document.enabled,
        "created_at": to_api_timestamp(document.created_at),
    }


def _document_library_run(
    db: Session, principal: Principal, run_id: str, *, modify: bool = False
) -> Run | _ProjectAnalysisScope:
    return _resolve_analysis_scope(db, principal, run_id, modify=modify)


@router.get("/api/runs/{run_id:path}/analysis-documents")
def list_analysis_documents(
    run_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> Dict[str, Any]:
    """List documents owned by the run's project."""
    run = _document_library_run(db, principal, run_id, modify=True)
    documents = (
        db.query(AnalyzerDocument)
        .filter(AnalyzerDocument.project_id == run.project_id)
        .order_by(AnalyzerDocument.created_at.asc(), AnalyzerDocument.id.asc())
        .all()
    )
    return {
        "documents": [
            _analysis_document_payload(document)
            for document in documents
        ]
    }


@router.post("/api/runs/{run_id:path}/analysis-documents")
async def upload_analysis_document(
    run_id: str,
    file: UploadFile = File(...),
    large_document_action: Literal["ask", "truncate", "full"] = Form("ask"),
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> Dict[str, Any]:
    """Extract and save a document to the run's project."""
    run = _document_library_run(db, principal, run_id, modify=True)
    action = large_document_action if isinstance(large_document_action, str) else "ask"

    try:
        raw = await file.read(MAX_REFERENCE_UPLOAD_BYTES + 1)
    finally:
        await file.close()

    if len(raw) > MAX_REFERENCE_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413, detail="The document exceeds the 10 MB upload limit."
        )

    try:
        probe = await to_thread.run_sync(
            partial(
                extract_document_text,
                file.filename or "document",
                raw,
                max_chars=MAX_REFERENCE_DOCUMENT_CONTENT_CHARS,
            ),
            limiter=_DOCUMENT_EXTRACTION_LIMITER,
        )
    except UnsupportedDocumentError as exc:
        raise HTTPException(status_code=415, detail=str(exc)) from exc
    except DocumentExtractionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if probe.source_characters > MAX_REFERENCE_DOCUMENT_CHARS and action == "ask":
        raise HTTPException(
            status_code=409,
            detail={
                "code": "DOCUMENT_CONTENT_LIMIT",
                "message": (
                    f"{probe.name} contains about {probe.source_characters:,} characters, "
                    f"which is above the {MAX_REFERENCE_DOCUMENT_CHARS:,}-character "
                    "prompt-safe limit. Choose the shortened version, or explicitly "
                    "add the larger document and let the rule writer process it in patches."
                ),
                "filename": probe.name,
                "source_characters": probe.source_characters,
                "prompt_limit": MAX_REFERENCE_DOCUMENT_CHARS,
                "content_limit": MAX_REFERENCE_DOCUMENT_CONTENT_CHARS,
                "content_will_be_cut": bool(probe.truncated),
                "actions": ["truncate", "full"],
            },
        )

    document = probe
    if action == "truncate" and probe.source_characters > MAX_REFERENCE_DOCUMENT_CHARS:
        try:
            document = await to_thread.run_sync(
                partial(
                    extract_document_text,
                    file.filename or "document",
                    raw,
                    max_chars=MAX_REFERENCE_DOCUMENT_CHARS,
                ),
                limiter=_DOCUMENT_EXTRACTION_LIMITER,
            )
        except (UnsupportedDocumentError, DocumentExtractionError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    stored = AnalyzerDocument(
        project_id=run.project_id,
        uploaded_by_user_id=principal.user.id,
        name=document.name,
        content=document.content,
        characters=document.characters,
        truncated=document.truncated,
    )
    db.add(stored)
    db.commit()
    db.refresh(stored)
    prompt_limit_hit = probe.source_characters > MAX_REFERENCE_DOCUMENT_CHARS
    content_limit_hit = bool(
        probe.truncated
        and probe.source_characters >= MAX_REFERENCE_DOCUMENT_CONTENT_CHARS
    )
    if action == "truncate" and prompt_limit_hit:
        warning = "The document was intentionally shortened to the prompt-safe limit."
        if content_limit_hit:
            warning += (
                " The source also exceeded the absolute content limit, so the saved "
                f"content is capped at {MAX_REFERENCE_DOCUMENT_CHARS:,} characters."
            )
    elif action == "full" and content_limit_hit:
        warning = (
            "The document exceeded the absolute content limit, so only the first "
            f"{MAX_REFERENCE_DOCUMENT_CONTENT_CHARS:,} extracted characters were "
            "retained even after choosing full content."
        )
    elif document.characters > MAX_REFERENCE_DOCUMENT_CHARS:
        warning = (
            "The document is larger than the prompt-safe limit. The rule writer "
            "will process it in bounded patches."
        )
    else:
        warning = None
    return {
        "document": _analysis_document_payload(
            stored,
            source_characters=probe.source_characters,
        ),
        "content_decision": action,
        "warning": warning,
    }


@router.patch("/api/runs/{run_id:path}/analysis-documents/{document_id}")
def select_analysis_document(
    run_id: str,
    document_id: str,
    request: AnalyzerDocumentSelection,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> Dict[str, Any]:
    """Persist whether a project document is available to analyzer prompts."""
    run = _document_library_run(db, principal, run_id, modify=True)
    document = (
        db.query(AnalyzerDocument)
        .filter(
            AnalyzerDocument.id == document_id,
            AnalyzerDocument.project_id == run.project_id,
        )
        .first()
    )
    if not document:
        raise HTTPException(status_code=404, detail="Analyzer document not found")
    document.enabled = request.selected
    db.commit()
    db.refresh(document)
    return {"document": _analysis_document_payload(document)}


@router.delete("/api/runs/{run_id:path}/analysis-documents/{document_id}")
def delete_analysis_document(
    run_id: str,
    document_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> Dict[str, Any]:
    """Delete one document from the shared project library."""
    run = _document_library_run(db, principal, run_id)
    document = (
        db.query(AnalyzerDocument)
        .filter(
            AnalyzerDocument.id == document_id,
            AnalyzerDocument.project_id == run.project_id,
        )
        .first()
    )
    if not document:
        raise HTTPException(status_code=404, detail="Analyzer document not found")
    if document.uploaded_by_user_id != principal.user.id and not is_project_manager(
        db, principal, run.project_id
    ):
        raise HTTPException(
            status_code=403,
            detail="Only the uploader or a project manager can delete this document",
        )
    db.delete(document)
    db.commit()
    return {"ok": True, "document_id": document_id}


def _analysis_example_query(
    db: Session,
    scope: Run | _ProjectAnalysisScope,
) -> Any:
    """Return the approved, active correction bank visible to the analyzer."""
    query = (
        db.query(ReviewCorrection)
        .join(Run, Run.id == ReviewCorrection.run_id)
        .filter(
            Run.project_id == scope.project_id,
            Run.deleted_at.is_(None),
            ReviewCorrection.status == CorrectionStatus.APPROVED,
            ReviewCorrection.is_active.is_(True),
        )
    )
    if isinstance(scope, Run):
        query = query.filter(ReviewCorrection.task == scope.task)
    return query


def _analysis_example_filter_query(
    query: Any,
    *,
    task: Optional[List[str]],
    dataset: Optional[List[str]],
    model: Optional[List[str]],
    run_name: Optional[List[str]],
    user_id: Optional[List[str]],
    source: Optional[str],
    conf_min: int,
    conf_max: int,
    search: Optional[str],
) -> Any:
    """Apply the same review-bank dimensions used by the Reviews page."""
    run_name_expr = func.coalesce(
        cast(Run.run_config.op("->>")("run_name"), String), ""
    )
    ai_root_cause_expr = func.btrim(func.coalesce(ReviewCorrection.ai_root_cause, ""))
    ai_detail_expr = func.btrim(func.coalesce(ReviewCorrection.ai_root_cause_detail, ""))
    ai_note_expr = func.btrim(func.coalesce(ReviewCorrection.ai_root_cause_note, ""))
    human_root_cause_expr = func.btrim(
        func.coalesce(ReviewCorrection.human_root_cause, "")
    )
    human_detail_expr = func.btrim(
        func.coalesce(ReviewCorrection.human_root_cause_detail, "")
    )
    human_note_expr = func.btrim(func.coalesce(ReviewCorrection.human_root_cause_note, ""))
    ai_solution_expr = func.btrim(func.coalesce(ReviewCorrection.ai_solution, ""))
    ai_solution_note_expr = func.btrim(
        func.coalesce(ReviewCorrection.ai_solution_note, "")
    )
    human_solution_expr = func.btrim(func.coalesce(ReviewCorrection.human_solution, ""))
    human_solution_note_expr = func.btrim(
        func.coalesce(ReviewCorrection.human_solution_note, "")
    )
    has_ai_data = or_(
        and_(ai_root_cause_expr != "", func.lower(ai_root_cause_expr) != "unanalyzed"),
        ai_detail_expr != "",
        ai_note_expr != "",
        ai_solution_expr != "",
        ai_solution_note_expr != "",
    )
    has_human_data = or_(
        human_root_cause_expr != "",
        human_detail_expr != "",
        human_note_expr != "",
        human_solution_expr != "",
        human_solution_note_expr != "",
    )
    is_changed = or_(
        ai_root_cause_expr != human_root_cause_expr,
        ai_detail_expr != human_detail_expr,
        ai_note_expr != human_note_expr,
        ai_solution_expr != human_solution_expr,
        ai_solution_note_expr != human_solution_note_expr,
    )
    if task:
        query = query.filter(ReviewCorrection.task.in_(task))
    if dataset:
        query = query.filter(Run.dataset.in_(dataset))
    if model:
        query = query.filter(
            or_(
                *(
                    [Run.model == value for value in model]
                    + [Run.model.ilike(f"%/{value}") for value in model]
                )
            )
        )
    if run_name:
        query = query.filter(
            or_(
                Run.external_run_id.in_(run_name),
                run_name_expr.in_(run_name),
                Run.id.in_(run_name),
            )
        )
    if user_id:
        query = query.filter(
            or_(
                ReviewCorrection.corrected_by_user_id.in_(user_id),
                ReviewCorrection.reviewed_by_user_id.in_(user_id),
            )
        )
    if source == "ai_only":
        query = query.filter(has_ai_data, or_(~has_human_data, ~is_changed))
    elif source == "human_only":
        query = query.filter(has_human_data, ~has_ai_data)
    elif source == "corrected":
        query = query.filter(has_ai_data, has_human_data, is_changed)
    if conf_min > 0 or conf_max < 100:
        query = query.filter(
            ReviewCorrection.ai_confidence.is_not(None),
            ReviewCorrection.ai_confidence >= conf_min / 100.0,
            ReviewCorrection.ai_confidence <= conf_max / 100.0,
        )
    if search:
        like = f"%{search}%"
        query = query.filter(
            or_(
                ReviewCorrection.task.ilike(like),
                ReviewCorrection.item_id.ilike(like),
                ReviewCorrection.metric_name.ilike(like),
                ReviewCorrection.human_root_cause.ilike(like),
                ReviewCorrection.human_root_cause_detail.ilike(like),
                ReviewCorrection.human_root_cause_note.ilike(like),
                ReviewCorrection.ai_root_cause.ilike(like),
                Run.dataset.ilike(like),
                Run.model.ilike(like),
                Run.external_run_id.ilike(like),
                run_name_expr.ilike(like),
            )
        )
    return query


def _analysis_example_row(
    correction: ReviewCorrection,
    *,
    run: Optional[Run],
    users_by_id: Dict[str, User],
) -> Dict[str, Any]:
    def clean(value: Any) -> str:
        return str(value or "").strip()

    ai_values = [
        clean(correction.ai_root_cause),
        clean(correction.ai_root_cause_detail),
        clean(correction.ai_root_cause_note),
        clean(correction.ai_solution),
        clean(correction.ai_solution_note),
    ]
    human_values = [
        clean(correction.human_root_cause),
        clean(correction.human_root_cause_detail),
        clean(correction.human_root_cause_note),
        clean(correction.human_solution),
        clean(correction.human_solution_note),
    ]
    has_ai_data = bool(
        any(ai_values[1:])
        or (ai_values[0] and ai_values[0].lower() != "unanalyzed")
    )
    has_human_data = any(human_values)
    if has_ai_data and has_human_data and ai_values != human_values:
        source = "Corrected"
    elif has_human_data and not has_ai_data:
        source = "Human"
    elif has_ai_data:
        # The picker uses the same semantics as the AI-only filter: an
        # unchanged human review still belongs to the AI baseline bucket.
        source = "AI"
    else:
        source = "Unknown"
    categories = normalize_root_causes(
        correction.human_root_causes
        or correction.human_root_cause
        or correction.ai_root_causes
        or correction.ai_root_cause
    )
    return {
        "id": correction.id,
        "item_id": correction.item_id,
        "metric_name": correction.metric_name,
        "task": correction.task,
        "dataset": run.dataset if run else "",
        "model": _strip_model_provider(run.model or "") if run else "",
        "run_name": _run_display_name(run),
        "root_causes": categories,
        "detail": correction.human_root_cause_detail
        or correction.ai_root_cause_detail
        or "",
        "note": correction.human_root_cause_note
        or correction.ai_root_cause_note
        or "",
        "confidence": correction.ai_confidence,
        "source": source,
        "corrected_by": _serialize_user(users_by_id.get(correction.corrected_by_user_id)),
        "reviewed_by": _serialize_user(users_by_id.get(correction.reviewed_by_user_id)),
        "status": correction.status.value
        if hasattr(correction.status, "value")
        else correction.status,
        "created_at": to_api_timestamp(correction.created_at),
        "source_characters": estimate_rule_writer_example_characters(correction),
    }


def _analysis_example_facets(
    corrections_by_dimension: Dict[str, List[ReviewCorrection]],
    *,
    runs_by_id: Dict[str, Run],
    users_by_id: Dict[str, User],
) -> Dict[str, Any]:
    def unique(values: Any) -> list[str]:
        return sorted({str(value).strip() for value in values if str(value).strip()})

    def corrections_for(dimension: str) -> List[ReviewCorrection]:
        return corrections_by_dimension.get(dimension, [])

    user_corrections = corrections_for("user_id")
    user_ids = {
        user_id
        for correction in user_corrections
        for user_id in (
            correction.corrected_by_user_id,
            correction.reviewed_by_user_id,
        )
        if user_id
    }
    return {
        "tasks": unique(correction.task for correction in corrections_for("task")),
        "datasets": unique(
            runs_by_id.get(correction.run_id).dataset
            if runs_by_id.get(correction.run_id)
            else ""
            for correction in corrections_for("dataset")
        ),
        "models": unique(
            _strip_model_provider(runs_by_id.get(correction.run_id).model or "")
            if runs_by_id.get(correction.run_id)
            else ""
            for correction in corrections_for("model")
        ),
        "run_names": unique(
            _run_display_name(runs_by_id.get(correction.run_id))
            for correction in corrections_for("run_name")
        ),
        "users": [
            _serialize_user(users_by_id[user_id])
            for user_id in sorted(user_ids)
            if user_id in users_by_id and _serialize_user(users_by_id[user_id])
        ],
    }


def _list_analysis_examples(
    *,
    scope_id: str,
    page: int,
    page_size: int,
    task: Optional[List[str]],
    dataset: Optional[List[str]],
    model: Optional[List[str]],
    run_name: Optional[List[str]],
    user_id: Optional[List[str]],
    source: Optional[str],
    conf_min: int,
    conf_max: int,
    search: Optional[str],
    selected_ids: Optional[List[int]],
    selected_only: bool = False,
    db: Session,
    principal: Principal,
) -> Dict[str, Any]:
    scope = _resolve_analysis_scope(db, principal, scope_id, modify=True)
    if not is_project_manager(db, principal, scope.project_id):
        raise HTTPException(status_code=403, detail="Project manager access required")
    if conf_min > conf_max:
        raise HTTPException(
            status_code=422,
            detail={"code": "INVALID_CONFIDENCE_RANGE", "message": "Minimum confidence must not exceed maximum confidence."},
        )

    selected_values = list(dict.fromkeys(int(value) for value in (selected_ids or [])))
    base_query = _analysis_example_query(db, scope)
    filtered_query = _analysis_example_filter_query(
        base_query,
        task=task,
        dataset=dataset,
        model=model,
        run_name=run_name,
        user_id=user_id,
        source=source,
        conf_min=conf_min,
        conf_max=conf_max,
        search=search,
    )
    # Each dimension is faceted against every other active filter, but not its
    # own selection. This keeps the active value available and lets the other
    # selectors narrow to meaningful options without making a selector filter
    # itself.
    facet_filters = {
        "task": task,
        "dataset": dataset,
        "model": model,
        "run_name": run_name,
        "user_id": user_id,
    }
    facet_corrections_by_dimension: Dict[str, List[ReviewCorrection]] = {}
    for dimension in facet_filters:
        dimension_filters = {
            key: values if key != dimension else None
            for key, values in facet_filters.items()
        }
        facet_query = _analysis_example_filter_query(
            base_query,
            task=dimension_filters["task"],
            dataset=dimension_filters["dataset"],
            model=dimension_filters["model"],
            run_name=dimension_filters["run_name"],
            user_id=dimension_filters["user_id"],
            source=source,
            conf_min=conf_min,
            conf_max=conf_max,
            search=search,
        )
        facet_corrections_by_dimension[dimension] = facet_query.all()

    facet_corrections = [
        correction
        for corrections in facet_corrections_by_dimension.values()
        for correction in corrections
    ]
    if selected_only:
        # SQLAlchemy renders an empty IN list as a false predicate, so an
        # empty selection is a valid, deterministic "View selected" state.
        filtered_query = filtered_query.filter(ReviewCorrection.id.in_(selected_values))
    matching = filtered_query.order_by(
        ReviewCorrection.created_at.desc(), ReviewCorrection.id.desc()
    ).all()
    selected_corrections = (
        _analysis_example_query(db, scope)
        .filter(ReviewCorrection.id.in_(selected_values))
        .all()
        if selected_values
        else []
    )
    run_ids = {
        correction.run_id
        for correction in matching + selected_corrections + facet_corrections
    }
    runs_by_id = _load_runs_map(db, run_ids)
    user_ids = {
        user_id
        for correction in matching + selected_corrections + facet_corrections
        for user_id in (
            correction.corrected_by_user_id,
            correction.reviewed_by_user_id,
        )
        if user_id
    }
    users_by_id = _load_users_map(db, user_ids)
    first = (page - 1) * page_size
    page_rows = matching[first : first + page_size]
    rows = [
        _analysis_example_row(
            correction,
            run=runs_by_id.get(correction.run_id),
            users_by_id=users_by_id,
        )
        for correction in page_rows
    ]
    facets = _analysis_example_facets(
        facet_corrections_by_dimension,
        runs_by_id=runs_by_id,
        users_by_id=users_by_id,
    )
    return {
        "examples": rows,
        "total": len(matching),
        "page": page,
        "page_size": page_size,
        "page_count": math.ceil(len(matching) / page_size) if matching else 0,
        "matching_ids": [correction.id for correction in matching],
        "matching_characters": sum(
            estimate_rule_writer_example_characters(correction)
            for correction in matching
        ),
        "selected_ids": [correction.id for correction in selected_corrections],
        "selected_count": len(selected_corrections),
        "selected_characters": sum(
            estimate_rule_writer_example_characters(correction)
            for correction in selected_corrections
        ),
        "facets": facets,
        "limits": {
            "approved_examples_prompt_characters": MAX_RULE_WRITER_EXAMPLE_CHARS,
            "writer_prompt_characters": MAX_RULE_WRITER_PROMPT_CHARS,
        },
    }


@router.get("/api/runs/{run_id:path}/analysis-examples")
def list_analysis_examples(
    run_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    task: Optional[List[str]] = Query(None),
    dataset: Optional[List[str]] = Query(None),
    model: Optional[List[str]] = Query(None),
    run_name: Optional[List[str]] = Query(None),
    user_id: Optional[List[str]] = Query(None),
    source: Optional[str] = Query(None),
    conf_min: int = Query(0, ge=0, le=100),
    conf_max: int = Query(100, ge=0, le=100),
    search: Optional[str] = Query(None),
    selected_id: Optional[List[int]] = Query(None),
    selected_only: bool = Query(False),
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> Dict[str, Any]:
    """Return a paged, filterable approved-example picker dataset."""
    return _list_analysis_examples(
        scope_id=run_id,
        page=page,
        page_size=page_size,
        task=task,
        dataset=dataset,
        model=model,
        run_name=run_name,
        user_id=user_id,
        source=source,
        conf_min=conf_min,
        conf_max=conf_max,
        search=search,
        selected_ids=selected_id,
        selected_only=selected_only,
        db=db,
        principal=principal,
    )


@router.post("/api/runs/{run_id:path}/analysis-examples")
def query_analysis_examples(
    run_id: str,
    request: AnalysisExamplesQuery,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> Dict[str, Any]:
    """Return picker rows without putting a large selection in the URL."""
    return _list_analysis_examples(
        scope_id=run_id,
        page=request.page,
        page_size=request.page_size,
        task=request.task,
        dataset=request.dataset,
        model=request.model,
        run_name=request.run_name,
        user_id=request.user_id,
        source=request.source,
        conf_min=request.conf_min,
        conf_max=request.conf_max,
        search=request.search,
        selected_ids=request.selected_ids,
        selected_only=request.selected_only,
        db=db,
        principal=principal,
    )


@router.patch("/api/runs/{run_id:path}/analysis-context")
def update_analysis_context(
    run_id: str,
    request: AnalysisContextUpdate,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> Dict[str, Any]:
    """Update the active working rules version."""
    run = _resolve_analysis_scope(db, principal, run_id)
    if not is_project_manager(db, principal, run.project_id):
        raise HTTPException(status_code=403, detail="Project manager access required")
    project = db.get(Project, run.project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    rules = [rule.model_dump(exclude_none=True) for rule in request.analysis_rules]
    if request.create_new_version:
        parent = (
            _resolve_analysis_rule_version(db, project.id, request.from_version)
            if request.from_version
            else _active_analysis_rule_version(db, project.id)
        )
        version = _create_analysis_rule_version(
            db,
            project_id=project.id,
            rules=rules,
            source="manual",
            actor_user_id=principal.user.id,
            force_new=True,
            parent=parent,
        )
    else:
        version = _save_active_analysis_rules(
            db,
            project_id=project.id,
            rules=rules,
            actor_user_id=principal.user.id,
            version_id=request.rule_version_id,
        )
    db.commit()
    production = _active_analysis_rule_version(db, project.id)
    return {
        "analysis_rules": version.rules or [],
        "rule_version": _analysis_rule_version_payload(
            version, active_version_id=production.id if production else None
        ),
    }


@router.post("/api/runs/{run_id:path}/analysis-rules/infer")
async def infer_project_analysis_rules(
    run_id: str,
    request: RuleInferenceRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> Dict[str, Any]:
    """Run the rule-writer agent over selected documents and approved examples."""
    run = _resolve_analysis_scope(db, principal, run_id)
    if not is_project_manager(db, principal, run.project_id):
        raise HTTPException(
            status_code=403, detail="Project manager access required"
        )
    project = db.get(Project, run.project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    if not (request.include_documents or request.include_examples):
        raise HTTPException(
            status_code=422,
            detail={
                "code": "NO_INFERENCE_SOURCES_SELECTED",
                "message": (
                    "Choose at least one source before generating rules: turn on "
                    "Project documents or Approved examples."
                ),
                "documents_selected": False,
                "approved_examples_selected": False,
            },
        )

    enabled_documents = (
        db.query(AnalyzerDocument)
        .filter(
            AnalyzerDocument.project_id == run.project_id,
            AnalyzerDocument.enabled.is_(True),
        )
        .order_by(AnalyzerDocument.created_at.asc(), AnalyzerDocument.id.asc())
        .all()
    )
    usable_documents = [
        document
        for document in enabled_documents
        if str(document.content or "").strip()
    ]
    selected_documents = usable_documents if request.include_documents else []
    available_approved_examples = get_all_approved_examples(
        db,
        task=run.task,
        project_id=run.project_id,
    )
    approved_examples = available_approved_examples
    if request.include_examples and request.approved_example_ids is not None:
        approved_examples, missing_example_ids = get_selected_approved_examples(
            db,
            task=run.task,
            project_id=run.project_id,
            correction_ids=request.approved_example_ids,
        )
        if missing_example_ids:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "APPROVED_EXAMPLES_CHANGED",
                    "message": (
                        "One or more selected approved examples are no longer "
                        "available for this project/task. Refresh the picker and "
                        "confirm the selection again."
                    ),
                    "missing_ids": missing_example_ids,
                    "available_count": len(available_approved_examples),
                },
            )
    corrections = approved_examples if request.include_examples else []
    if not selected_documents and not corrections:
        action = "generated"
        if not usable_documents and not approved_examples:
            message = (
                f"Rules cannot be {action} yet. This project has neither an "
                "enabled project document nor an approved example. Add and "
                "enable a project document, or approve an example, then try again."
            )
        elif request.include_documents and not usable_documents:
            message = (
                f"Rules cannot be {action} yet. No enabled project documents are "
                "available, and Approved examples are turned off. Turn on "
                "Approved examples or add and enable a project document, then "
                "try again."
            )
        else:
            message = (
                f"Rules cannot be {action} yet. No approved examples are "
                "available, and Project documents are turned off. Turn on "
                "Project documents or approve an example, then try again."
            )
        raise HTTPException(
            status_code=422,
            detail={
                "code": "NO_INFERENCE_SOURCES",
                "message": message,
                "documents_available": len(usable_documents),
                "approved_examples_available": len(available_approved_examples),
                "approved_examples_selected_count": len(corrections),
                "documents_selected": request.include_documents,
                "approved_examples_selected": request.include_examples and bool(corrections),
            },
        )
    llm_config = _get_llm_config(db, run.project_id, request.connection_id)
    target_version = (
        _resolve_analysis_rule_version(
            db, project.id, request.rule_version_id
        )
        if request.rule_version_id
        else _latest_analysis_rule_draft(db, project.id)
        or _active_analysis_rule_version(db, project.id)
    )
    existing_rules = (
        copy.deepcopy(list(target_version.rules or [])) if target_version else []
    )

    try:
        analysis_prompts = get_effective_analysis_prompts(db, run.project_id)
        inference_stats: dict[str, Any] = {}
        inference_args = {
            "client": build_client(llm_config),
            "model": llm_config.get("llm_model", "gpt-4o-mini"),
            "reference_documents": [
                {"name": document.name, "content": document.content}
                for document in selected_documents
            ],
            "corrections": corrections,
            "existing_rules": existing_rules,
            "system_prompt": analysis_prompts["rules_writer"],
            "stats": inference_stats,
            "include_fields": request.include_fields,
        }
        # ``mode=update`` is accepted for old clients, but generation is now
        # the only operation: it can append rules and can never revise the
        # existing ruleset.
        generated_rules = await infer_analysis_rules(**inference_args)
    except asyncio.TimeoutError as exc:
        logger.warning(
            "Rule inference timed out for run=%s project=%s model=%s",
            run.id,
            run.project_id,
            llm_config.get("llm_model", "unknown"),
        )
        raise HTTPException(
            status_code=504,
            detail="Rule inference timed out while waiting for the LLM provider. Try again or use a faster model.",
        ) from exc
    except ValueError as exc:
        logger.warning(
            "Rule inference returned no usable rules for run=%s project=%s model=%s: %s",
            run.id,
            run.project_id,
            llm_config.get("llm_model", "unknown"),
            exc,
        )
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception(
            "Rule inference provider failure for run=%s project=%s model=%s",
            run.id,
            run.project_id,
            llm_config.get("llm_model", "unknown"),
        )
        raise HTTPException(
            status_code=502, detail=f"Rule inference failed: {exc}"
        ) from exc

    new_rules = _new_analysis_rules(existing_rules, generated_rules)
    if not new_rules and target_version is None:
        raise HTTPException(
            status_code=502,
            detail="The rule writer did not produce any new analysis rules.",
        )

    created_new_version = False
    if not new_rules:
        # A duplicate-only generation is a successful no-op. In particular,
        # do not create a new draft merely because the provider repeated the
        # current rules.
        version = target_version
    elif (
        target_version is not None
        and _rule_status(target_version) == AnalysisRuleVersionStatus.DRAFT.value
    ):
        version = target_version
        version.rules = copy.deepcopy(existing_rules) + copy.deepcopy(new_rules)
        version.source = "inferred"
        version.updated_at = utc_now_naive()
    else:
        full_rules = copy.deepcopy(existing_rules) + copy.deepcopy(new_rules)
        version = _create_analysis_rule_version(
            db,
            project_id=project.id,
            rules=full_rules,
            source="inferred",
            actor_user_id=principal.user.id,
            force_new=True,
            parent=target_version,
            preserve_rules=True,
        )
        created_new_version = True
    db.commit()
    production = _active_analysis_rule_version(db, project.id)
    before_map, _ = _rule_map(existing_rules)
    after_map, _ = _rule_map(version.rules)
    common_keys = set(before_map) & set(after_map)
    changed_count = sum(
        not _rule_equal(before_map[key], after_map[key])
        for key in common_keys
    )
    return {
        "analysis_rules": version.rules or [],
        "rule_version": _analysis_rule_version_payload(
            version, active_version_id=production.id if production else None
        ),
        "mode": "generate",
        "created_new_version": created_new_version,
        "generated_rule_count": len(new_rules),
        "inference_stats": inference_stats,
        "changes": {
            "added": len(set(after_map) - set(before_map)),
            "removed": len(set(before_map) - set(after_map)),
            "changed": changed_count,
            "unchanged": len(common_keys) - changed_count,
        },
        "documents_used": len(selected_documents),
        "examples_used": len(corrections),
        "sources_used": {
            "documents": request.include_documents,
            "approved_examples": request.include_examples,
        },
    }


@router.get("/api/runs/{run_id:path}/analysis-rule-versions")
def list_project_analysis_rule_versions(
    run_id: str,
    include_deleted: bool = Query(default=False),
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> Dict[str, Any]:
    """List immutable rule history for the run's project."""
    run = _resolve_analysis_scope(db, principal, run_id)
    is_admin = principal.user.role == UserRole.ADMIN
    query = db.query(ProjectAnalysisRuleVersion).filter(
        ProjectAnalysisRuleVersion.project_id == run.project_id
    )
    if not (include_deleted and is_admin):
        query = query.filter(ProjectAnalysisRuleVersion.deleted_at.is_(None))
    versions = query.order_by(ProjectAnalysisRuleVersion.version.desc()).all()
    active = _active_analysis_rule_version(db, run.project_id)
    return {
        "versions": [
            _analysis_rule_version_payload(
                version,
                active_version_id=active.id if active else None,
            )
            for version in versions
        ],
        "can_delete": can_delete_run(db, principal, run),
        "can_activate": is_project_manager(db, principal, run.project_id),
        "can_restore": is_admin,
        "production_version_id": active.id if active else None,
    }


@router.get("/api/runs/{run_id:path}/analysis-rule-lineage")
def get_project_analysis_rule_lineage(
    run_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> Dict[str, Any]:
    """Return the parent-linked rule-version history for the run's project."""
    payload = list_project_analysis_rule_versions(
        run_id=run_id,
        include_deleted=False,
        db=db,
        principal=principal,
    )
    return {
        "versions": payload["versions"],
        "production_version_id": payload["production_version_id"],
    }


@router.post("/api/runs/{run_id:path}/analysis-rule-versions")
def create_project_analysis_rule_version(
    run_id: str,
    request: AnalysisRuleVersionCreate,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> Dict[str, Any]:
    """Create a mutable draft, optionally cloning a version or alias."""
    run = _resolve_analysis_scope(db, principal, run_id)
    if not is_project_manager(db, principal, run.project_id):
        raise HTTPException(
            status_code=403, detail="Project manager access required"
        )
    parent = None
    if request.from_version:
        parent = _resolve_analysis_rule_version(
            db, run.project_id, request.from_version
        )
    else:
        parent = _active_analysis_rule_version(db, run.project_id)
    version = _create_analysis_rule_version(
        db,
        project_id=run.project_id,
        rules=list(parent.rules or []) if parent else [],
        source="derived" if parent else "manual",
        actor_user_id=principal.user.id,
        force_new=True,
        parent=parent,
        description=request.description,
    )
    db.commit()
    production = _active_analysis_rule_version(db, run.project_id)
    return {
        "version": _analysis_rule_version_payload(
            version, active_version_id=production.id if production else None
        )
    }


@router.post(
    "/api/runs/{run_id:path}/analysis-rule-versions/{version_ref}:publish"
)
def publish_project_analysis_rule_version(
    run_id: str,
    version_ref: str,
    request: AnalysisRuleVersionPublish,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> Dict[str, Any]:
    """Publish and lock a draft, optionally moving an alias to it."""
    run = _resolve_analysis_scope(db, principal, run_id)
    if not is_project_manager(db, principal, run.project_id):
        raise HTTPException(
            status_code=403, detail="Project manager access required"
        )
    version = _resolve_analysis_rule_version(db, run.project_id, version_ref)
    if _rule_status(version) != AnalysisRuleVersionStatus.DRAFT.value:
        raise HTTPException(
            status_code=409,
            detail="Only draft analysis rule versions can be published",
        )
    rules = _rules_with_stable_ids(version.rules)
    if not rules:
        raise HTTPException(
            status_code=400,
            detail="Cannot publish an empty analysis rule version",
        )
    now = utc_now_naive()
    version.rules = rules
    version.status = AnalysisRuleVersionStatus.PUBLISHED
    version.content_hash = _rule_content_hash(rules)
    version.published_at = now
    version.published_by_user_id = principal.user.id
    version.updated_at = now
    if request.set_alias:
        _set_analysis_rule_alias(
            db,
            project_id=run.project_id,
            alias_name=request.set_alias,
            version=version,
            actor_user_id=principal.user.id,
        )
    db.commit()
    production = _active_analysis_rule_version(db, run.project_id)
    return {
        "version": _analysis_rule_version_payload(
            version, active_version_id=production.id if production else None
        )
    }


@router.post("/api/runs/{run_id:path}/analysis-rule-aliases/{alias_name}")
def set_project_analysis_rule_alias(
    run_id: str,
    alias_name: str,
    request: AnalysisRuleAliasUpdate,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> Dict[str, Any]:
    """Point an alias at a published project rule version."""
    run = _resolve_analysis_scope(db, principal, run_id)
    if not is_project_manager(db, principal, run.project_id):
        raise HTTPException(
            status_code=403, detail="Project manager access required"
        )
    version = _resolve_analysis_rule_version(db, run.project_id, request.version)
    alias = _set_analysis_rule_alias(
        db,
        project_id=run.project_id,
        alias_name=alias_name,
        version=version,
        actor_user_id=principal.user.id,
    )
    db.commit()
    return {
        "alias": alias.alias,
        "version": _analysis_rule_version_payload(
            version, active_version_id=version.id if alias_name == "production" else None
        ),
    }


@router.get(
    "/api/runs/{run_id:path}/analysis-rule-versions/{version_ref}:compare"
)
def compare_project_analysis_rule_versions(
    run_id: str,
    version_ref: str,
    base: str = Query(...),
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> Dict[str, Any]:
    """Compare rule identities and content between two versions."""
    run = _resolve_analysis_scope(db, principal, run_id)
    target = _resolve_analysis_rule_version(db, run.project_id, version_ref)
    base_version = _resolve_analysis_rule_version(db, run.project_id, base)

    def keyed(version: ProjectAnalysisRuleVersion) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for rule in version.rules or []:
            if not isinstance(rule, dict):
                continue
            key = str(rule.get("id") or "").strip() or (
                "title:" + str(rule.get("title") or "").strip().casefold()
            )
            result[key] = rule
        return result

    before = keyed(base_version)
    after = keyed(target)
    added = [after[key] for key in after.keys() - before.keys()]
    removed = [before[key] for key in before.keys() - after.keys()]
    changed = [
        {"id": key, "before": before[key], "after": after[key]}
        for key in before.keys() & after.keys()
        if normalize_analysis_rules([before[key]])
        != normalize_analysis_rules([after[key]])
    ]
    unchanged = len(before.keys() & after.keys()) - len(changed)
    production = _active_analysis_rule_version(db, run.project_id)
    return {
        "base": _analysis_rule_version_payload(
            base_version, active_version_id=production.id if production else None
        ),
        "target": _analysis_rule_version_payload(
            target, active_version_id=production.id if production else None
        ),
        "summary": {
            "added": len(added),
            "removed": len(removed),
            "changed": len(changed),
            "unchanged": unchanged,
        },
        "added_rules": added,
        "removed_rules": removed,
        "changed_rules": changed,
    }


@router.post(
    "/api/runs/{run_id:path}/analysis-rule-versions/{target_ref}:merge"
)
def merge_project_analysis_rule_versions(
    run_id: str,
    target_ref: str,
    request: AnalysisRuleMergeRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> Dict[str, Any]:
    """Preview or apply a three-way merge between two rule-version branches."""
    run = _resolve_analysis_scope(db, principal, run_id)
    if not is_project_manager(db, principal, run.project_id):
        raise HTTPException(
            status_code=403, detail="Project manager access required"
        )
    target = _resolve_analysis_rule_version(db, run.project_id, target_ref)
    source = _resolve_analysis_rule_version(
        db, run.project_id, request.source_version
    )
    if target.id == source.id:
        raise HTTPException(
            status_code=409, detail="A rule version cannot be merged with itself"
        )
    base = _nearest_rule_merge_base(db, target, source)
    merge = _merge_rule_versions(
        base=base,
        target=target,
        source=source,
        resolutions=request.resolutions,
    )
    if not request.apply:
        return {"preview": merge}
    if merge["conflicts"]:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Resolve every rule conflict before applying the merge",
                "preview": merge,
            },
        )

    source_ancestors = _rule_version_ancestor_depths(db, source)
    update_in_place = (
        _rule_status(target) == AnalysisRuleVersionStatus.DRAFT.value
        and target.id not in source_ancestors
    )
    if update_in_place:
        result = target
        result.rules = merge["rules"]
        result.source = "merged"
        result.updated_at = utc_now_naive()
    else:
        result = _create_analysis_rule_version(
            db,
            project_id=run.project_id,
            rules=merge["rules"],
            source="merged",
            actor_user_id=principal.user.id,
            force_new=True,
            parent=target,
            description=f"Merged {source.name or 'v' + str(source.version)}",
        )
    merge["created_new_draft"] = result.id != target.id
    edge = (
        db.query(ProjectAnalysisRuleMergeParent)
        .filter(
            ProjectAnalysisRuleMergeParent.version_id == result.id,
            ProjectAnalysisRuleMergeParent.parent_version_id == source.id,
        )
        .first()
    )
    if edge is None:
        db.add(
            ProjectAnalysisRuleMergeParent(
                version_id=result.id,
                parent_version_id=source.id,
                merge_base_version_id=base.id if base else None,
                created_by_user_id=principal.user.id,
                created_at=utc_now_naive(),
            )
        )
    db.commit()
    production = _active_analysis_rule_version(db, run.project_id)
    return {
        "version": _analysis_rule_version_payload(
            result, active_version_id=production.id if production else None
        ),
        "merge": merge,
    }


@router.post(
    "/api/runs/{run_id:path}/analysis-rule-versions/{version_id}/activate"
)
def activate_project_analysis_rule_version(
    run_id: str,
    version_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> Dict[str, Any]:
    """Make an available historical rules version active for the project."""
    run = _resolve_analysis_scope(db, principal, run_id)
    if not is_project_manager(db, principal, run.project_id):
        raise HTTPException(
            status_code=403, detail="Project manager access required"
        )
    version = (
        db.query(ProjectAnalysisRuleVersion)
        .filter(
            ProjectAnalysisRuleVersion.id == version_id,
            ProjectAnalysisRuleVersion.project_id == run.project_id,
        )
        .first()
    )
    if not version:
        raise HTTPException(status_code=404, detail="Rule version not found")
    if version.deleted_at is not None or _rule_status(version) == "archived":
        raise HTTPException(
            status_code=409, detail="Archived rule versions cannot be promoted"
        )
    _set_analysis_rule_alias(
        db,
        project_id=run.project_id,
        alias_name="production",
        version=version,
        actor_user_id=principal.user.id,
    )
    version.activated_at = utc_now_naive()
    version.activated_by_user_id = principal.user.id
    db.commit()
    return {
        "active_version": _analysis_rule_version_payload(
            version, active_version_id=version.id
        )
    }


@router.delete(
    "/api/runs/{run_id:path}/analysis-rule-versions/{version_id}"
)
def delete_project_analysis_rule_version(
    run_id: str,
    version_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> Dict[str, Any]:
    """Permanently delete a project rules version."""
    run = _resolve_analysis_scope(db, principal, run_id)
    if not can_delete_run(db, principal, run):
        raise HTTPException(
            status_code=403,
            detail="Run owner or project manager access required",
        )
    version = (
        db.query(ProjectAnalysisRuleVersion)
        .filter(
            ProjectAnalysisRuleVersion.id == version_id,
            ProjectAnalysisRuleVersion.project_id == run.project_id,
        )
        .first()
    )
    if not version:
        raise HTTPException(status_code=404, detail="Rule version not found")
    remaining_live_versions = (
        db.query(ProjectAnalysisRuleVersion.id)
        .filter(
            ProjectAnalysisRuleVersion.project_id == run.project_id,
            ProjectAnalysisRuleVersion.id != version.id,
            ProjectAnalysisRuleVersion.deleted_at.is_(None),
        )
        .count()
    )
    if remaining_live_versions < 1:
        raise HTTPException(
            status_code=409,
            detail="At least one rule version must remain",
        )
    deleted_version_id = version.id
    descendants = (
        db.query(ProjectAnalysisRuleVersion)
        .filter(
            ProjectAnalysisRuleVersion.project_id == run.project_id,
            or_(
                ProjectAnalysisRuleVersion.parent_version_id == version.id,
                ProjectAnalysisRuleVersion.base_version_id == version.id,
            ),
        )
        .all()
    )
    for descendant in descendants:
        if descendant.parent_version_id == version.id:
            descendant.parent_version_id = None
        if descendant.base_version_id == version.id:
            descendant.base_version_id = None
    db.query(ProjectAnalysisRuleMergeParent).filter(
        ProjectAnalysisRuleMergeParent.version_id == version.id
    ).delete(synchronize_session=False)
    merge_descendants = (
        db.query(ProjectAnalysisRuleMergeParent)
        .filter(
            ProjectAnalysisRuleMergeParent.parent_version_id == version.id
        )
        .all()
    )
    for edge in merge_descendants:
        db.delete(edge)
    db.query(ProjectAnalysisRuleMergeParent).filter(
        ProjectAnalysisRuleMergeParent.merge_base_version_id == version.id
    ).update(
        {ProjectAnalysisRuleMergeParent.merge_base_version_id: None},
        synchronize_session=False,
    )
    db.query(ProjectAnalysisRuleAlias).filter(
        ProjectAnalysisRuleAlias.project_id == run.project_id,
        ProjectAnalysisRuleAlias.rule_version_id == version.id,
    ).delete(synchronize_session=False)
    try:
        db.flush()
        db.delete(version)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Rule version cannot be deleted while referenced",
        ) from exc
    active = _active_analysis_rule_version(db, run.project_id)
    return {
        "deleted_version_id": deleted_version_id,
        "active_version": (
            _analysis_rule_version_payload(active, active_version_id=active.id)
            if active
            else None
        ),
    }


@router.post(
    "/api/runs/{run_id:path}/analysis-rule-versions/{version_id}/restore"
)
def restore_project_analysis_rule_version(
    run_id: str,
    version_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> Dict[str, Any]:
    """Restore a soft-deleted rules version. Platform admins only."""
    run = _resolve_analysis_scope(db, principal, run_id)
    if principal.user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Admin only")
    version = (
        db.query(ProjectAnalysisRuleVersion)
        .filter(
            ProjectAnalysisRuleVersion.id == version_id,
            ProjectAnalysisRuleVersion.project_id == run.project_id,
        )
        .first()
    )
    if not version:
        raise HTTPException(status_code=404, detail="Rule version not found")
    if version.deleted_at is None:
        raise HTTPException(status_code=409, detail="Rule version is not deleted")
    version.deleted_at = None
    version.deleted_by_user_id = None
    version.restored_at = utc_now_naive()
    version.restored_by_user_id = principal.user.id
    db.commit()
    active = _active_analysis_rule_version(db, run.project_id)
    return {
        "restored_version": _analysis_rule_version_payload(
            version,
            active_version_id=active.id if active else None,
        )
    }


@router.delete(
    "/api/runs/{run_id:path}/analysis-rule-versions/{version_id}/permanent"
)
def permanently_delete_project_analysis_rule_version(
    run_id: str,
    version_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> Dict[str, Any]:
    """Permanently remove a soft-deleted rules version. Platform admins only."""
    run = _resolve_analysis_scope(db, principal, run_id)
    if principal.user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Admin only")
    version = (
        db.query(ProjectAnalysisRuleVersion)
        .filter(
            ProjectAnalysisRuleVersion.id == version_id,
            ProjectAnalysisRuleVersion.project_id == run.project_id,
        )
        .first()
    )
    if not version:
        raise HTTPException(status_code=404, detail="Rule version not found")
    if version.deleted_at is None:
        raise HTTPException(
            status_code=409,
            detail="Rule version must be deleted before it can be permanently removed",
        )
    has_aliases = (
        db.query(ProjectAnalysisRuleAlias.id)
        .filter(ProjectAnalysisRuleAlias.rule_version_id == version.id)
        .first()
        is not None
    )
    has_descendants = (
        db.query(ProjectAnalysisRuleVersion.id)
        .filter(
            or_(
                ProjectAnalysisRuleVersion.parent_version_id == version.id,
                ProjectAnalysisRuleVersion.base_version_id == version.id,
            )
        )
        .first()
        is not None
    )
    has_merge_references = (
        db.query(ProjectAnalysisRuleMergeParent.id)
        .filter(
            or_(
                ProjectAnalysisRuleMergeParent.parent_version_id == version.id,
                ProjectAnalysisRuleMergeParent.merge_base_version_id == version.id,
            )
        )
        .first()
        is not None
    )
    if has_aliases or has_descendants or has_merge_references:
        references = []
        if has_aliases:
            references.append("aliases")
        if has_descendants:
            references.append("descendant versions")
        if has_merge_references:
            references.append("merge lineage")
        raise HTTPException(
            status_code=409,
            detail=(
                "Rule version cannot be permanently removed while referenced by "
                + " and ".join(references)
            ),
        )
    try:
        db.delete(version)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Rule version cannot be permanently removed while referenced",
        )
    return {"permanently_deleted_version_id": version_id}


@router.post("/api/runs/{run_id:path}/analyze-preview")
def analyze_preview(
    run_id: str,
    request: PreviewRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> Dict[str, Any]:
    """Return the exact LLM messages for an item with custom config (no LLM call)."""
    run = Run.active(db).filter(Run.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    if not can_view_run(db, principal, run):
        raise HTTPException(status_code=403, detail="Access denied")

    item = (
        db.query(RunItem)
        .filter(RunItem.run_id == run.id, RunItem.item_id == request.item_id)
        .first()
    )
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    scores_list = (
        db.query(RunItemScore)
        .filter(RunItemScore.run_id == run.id, RunItemScore.item_id == request.item_id)
        .all()
    )
    scores = {s.metric_name: s for s in scores_list}
    _validate_requested_metric(run, {item.item_id: scores}, request.metric)

    preview_metric = request.metric
    if not preview_metric:
        specs = _load_metric_specs(db, run)
        preview_request = AnalyzeRequest(
            item_filter="failed",
            only_unanalyzed=False,
            allow_human_overwrite=True,
            item_ids=[item.item_id],
        )
        preview_targets = _filter_analysis_targets(
            run,
            preview_request,
            [item],
            {item.item_id: scores},
            specs,
        )
        preview_metric = (
            preview_targets[0][1]
            if preview_targets
            else next(iter(scores), (run.metrics or [None])[0])
        )

    analyzer_config = _analysis_config_with_project_context(
        db,
        run,
        _playground_config_to_analyzer(request.config),
    )
    analyzer_config = _analysis_config_with_category_catalog(
        db,
        run,
        [item],
        analyzer_config,
        request.category_catalog_version_id,
    )
    prompt_item = item
    prompt_config = analyzer_config
    prompt_kwargs = dict(config=prompt_config)
    if _supports_metric_name_arg(build_analysis_prompt):
        prompt_kwargs["metric_name"] = preview_metric
    else:
        prompt_item, prompt_config = _adapt_legacy_analyzer_inputs(
            item, scores, analyzer_config, preview_metric
        )
        prompt_kwargs["config"] = prompt_config
    messages = build_analysis_prompt(prompt_item, scores, [], **prompt_kwargs)

    prompt_characters = prompt_character_count(messages)
    return {
        "messages": messages,
        "metric_name": preview_metric,
        "prompt_characters": prompt_characters,
        "prompt_limit": MAX_ANALYSIS_PROMPT_CHARS,
        "prompt_at_limit": prompt_characters >= MAX_ANALYSIS_PROMPT_CHARS,
    }


@router.post("/api/runs/{run_id:path}/analyze-test")
async def analyze_test(
    run_id: str,
    request: TestRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> Dict[str, Any]:
    """Run analysis on 1-3 items with custom config. Does NOT save to DB."""
    run = Run.active(db).filter(Run.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    if not _can_operate_analyzer(db, principal, run):
        raise HTTPException(status_code=403, detail="Access denied")
    llm_config = _get_llm_config(db, run.project_id, request.connection_id)

    items = (
        db.query(RunItem)
        .filter(RunItem.run_id == run.id, RunItem.item_id.in_(request.item_ids))
        .all()
    )
    if not items:
        raise HTTPException(status_code=404, detail="No matching items found")

    all_scores = (
        db.query(RunItemScore)
        .filter(
            RunItemScore.run_id == run.id,
            RunItemScore.item_id.in_(request.item_ids),
        )
        .all()
    )
    scores_by_item: dict[str, dict[str, RunItemScore]] = {}
    for s in all_scores:
        scores_by_item.setdefault(s.item_id, {})[s.metric_name] = s

    analyzer_config = _analysis_config_with_project_context(
        db,
        run,
        _playground_config_to_analyzer(request.config),
    )
    analyzer_config = _analysis_config_with_category_catalog(
        db,
        run,
        items,
        analyzer_config,
        request.category_catalog_version_id,
    )
    client = build_client(llm_config)
    model = llm_config.get("llm_model", "gpt-4o-mini")

    metric_specs = _load_metric_specs(db, run)
    _validate_requested_metric(run, scores_by_item, request.metric)
    target_request = AnalyzeRequest(
        metric=request.metric,
        item_filter="failed" if request.metric is None else "all",
        only_unanalyzed=False,
        allow_human_overwrite=True,
        item_ids=request.item_ids,
    )
    targets = _filter_analysis_targets(
        run,
        target_request,
        items,
        scores_by_item,
        metric_specs,
    )

    analyzed_results: list[AnalysisResult] = []
    messages_by_result: list[list[dict[str, Any]]] = []
    for item, metric_name in targets:
        item_scores = scores_by_item.get(item.item_id, {})

        # Build prompt messages so we can return the inputs alongside the result
        prompt_item = item
        prompt_config = analyzer_config
        prompt_kwargs = dict(config=prompt_config)
        if _supports_metric_name_arg(build_analysis_prompt):
            prompt_kwargs["metric_name"] = metric_name
        else:
            prompt_item, prompt_config = _adapt_legacy_analyzer_inputs(
                item, item_scores, analyzer_config, metric_name
            )
            prompt_kwargs["config"] = prompt_config
        messages = build_analysis_prompt(
            prompt_item, item_scores, [], **prompt_kwargs
        )

        single_kwargs = dict(
            client=client,
            model=model,
            item=item,
            scores=item_scores,
            corrections=[],
            config=analyzer_config,
            temperature=request.config.temperature if request.config else None,
            max_tokens=request.config.max_tokens if request.config else None,
        )
        if _supports_metric_name_arg(analyze_single_item):
            single_kwargs["metric_name"] = metric_name
        else:
            legacy_item, legacy_config = _adapt_legacy_analyzer_inputs(
                item, item_scores, analyzer_config, metric_name
            )
            single_kwargs["item"] = legacy_item
            single_kwargs["config"] = legacy_config
        result = await analyze_single_item(**single_kwargs)
        result.metric_name = metric_name
        analyzed_results.append(result)
        messages_by_result.append(messages)

    aggregation_error: str | None = None
    raw_labels = [
        (
            tuple(
                normalize_root_causes(
                    getattr(result, "root_causes", None) or result.root_cause
                )
            ),
            result.root_cause_detail,
            result.solution,
            normalize_category_taxonomy(
                getattr(result, "category_taxonomy", None)
            ),
        )
        for result in analyzed_results
    ]
    try:
        categories = await aggregate_analysis_categories(
            client,
            model,
            analyzed_results,
            known_categories=(analyzer_config or {}).get("root_cause_categories")
            or ROOT_CAUSE_CATEGORIES,
            known_details=(analyzer_config or {}).get("root_cause_details") or [],
            known_category_details=(analyzer_config or {}).get("category_details_map")
            or {},
            system_prompt=(analyzer_config or {}).get("_aggregator_system_prompt"),
        )
    except AnalysisAggregationError as exc:
        for result, labels in zip(analyzed_results, raw_labels):
            categories, detail, solution, category_taxonomy = labels
            result.root_causes = list(categories)
            result.root_cause = categories[0] if categories else ""
            result.root_cause_detail = detail
            result.solution = solution
            result.category_taxonomy = category_taxonomy
        categories = _category_counts(analyzed_results)
        aggregation_error = str(exc)
    results = [
        {
            "item_id": result.item_id,
            "metric_name": result.metric_name,
            "root_cause": result.root_cause,
            "root_causes": normalize_root_causes(
                getattr(result, "root_causes", None) or result.root_cause
            ),
            "category_taxonomy": normalize_category_taxonomy(
                getattr(result, "category_taxonomy", None)
            ),
            "root_cause_detail": result.root_cause_detail,
            "root_cause_reason": result.root_cause_reason,
            "root_cause_note": result.root_cause_note,
            "warning": result.warning,
            "confidence": result.confidence,
            "solution": result.solution,
            "solution_note": result.solution_note,
            "error": result.error,
            "messages": messages,
        }
        for result, messages in zip(analyzed_results, messages_by_result)
    ]

    return {
        "results": results,
        "categories": categories,
        "aggregation_error": aggregation_error,
    }


@router.get("/api/runs/{run_id:path}/corrections")
def get_corrections(
    run_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> Dict[str, Any]:
    """Return approved correction bank entries for the run's task."""
    run = Run.active(db).filter(Run.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    if not can_view_run(db, principal, run):
        raise HTTPException(status_code=403, detail="Access denied")

    corrections = (
        db.query(ReviewCorrection)
        .join(Run, Run.id == ReviewCorrection.run_id)
        .filter(
            ReviewCorrection.task == run.task,
            Run.project_id == run.project_id,
            Run.deleted_at.is_(None),
            ReviewCorrection.status == CorrectionStatus.APPROVED,
            ReviewCorrection.is_active.is_(True),
        )
        .order_by(ReviewCorrection.created_at.desc())
        .limit(20)
        .all()
    )

    return {
        "corrections": [
            {
                "id": c.id,
                "item_id": c.item_id,
                "human_root_cause": c.human_root_cause,
                "human_root_causes": normalize_root_causes(
                    c.human_root_causes or c.human_root_cause
                ),
                "human_category_taxonomy": normalize_category_taxonomy(
                    getattr(c, "human_category_taxonomy", None)
                ),
                "human_root_cause_detail": c.human_root_cause_detail,
                "human_root_cause_note": c.human_root_cause_note,
                "ai_root_cause": c.ai_root_cause,
                "ai_root_causes": normalize_root_causes(
                    c.ai_root_causes or c.ai_root_cause
                ),
                "ai_category_taxonomy": normalize_category_taxonomy(
                    getattr(c, "ai_category_taxonomy", None)
                ),
                "ai_root_cause_detail": c.ai_root_cause_detail,
                "ai_root_cause_note": c.ai_root_cause_note,
                "ai_confidence": c.ai_confidence,
                "ai_solution": c.ai_solution,
                "human_solution": c.human_solution,
                "human_solution_note": c.human_solution_note,
                "input_snapshot": c.input_snapshot,
                "expected_snapshot": c.expected_snapshot,
                "output_snapshot": c.output_snapshot,
                "status": (
                    c.status.value
                    if hasattr(c.status, "value")
                    else (c.status or "pending")
                ),
                "created_at": to_api_timestamp(c.created_at),
            }
            for c in corrections
        ]
    }


@router.get("/api/runs/{run_id:path}/analysis-config")
def get_analysis_config(
    run_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> Dict[str, Any]:
    """Return analysis configuration for the frontend."""
    run = _resolve_analysis_scope(db, principal, run_id)
    project = db.get(Project, run.project_id)

    connections = (
        db.query(ProjectLlmConnection)
        .filter(ProjectLlmConnection.project_id == run.project_id)
        .order_by(
            ProjectLlmConnection.is_default.desc(), ProjectLlmConnection.created_at
        )
        .all()
    )
    connection_payloads = [
        {
            "id": c.id,
            "name": c.name,
            "llm_model": c.llm_model,
            "is_default": c.is_default,
            "llm_api_key_set": bool(c.llm_api_key_encrypted),
        }
        for c in connections
    ]
    usable = [c for c in connections if c.llm_api_key_encrypted]
    default_conn = next(
        (c for c in usable if c.is_default), usable[0] if usable else None
    )

    items = (
        []
        if isinstance(run, _ProjectAnalysisScope)
        else db.query(RunItem).filter(RunItem.run_id == run.id).all()
    )
    total = len(items)
    with_rc = sum(
        1
        for i in items
        if isinstance(i.item_metadata, dict) and i.item_metadata.get("root_cause")
    )
    ai_assigned = sum(
        1
        for i in items
        if isinstance(i.item_metadata, dict)
        and i.item_metadata.get("root_cause_source") == "ai"
    )

    corrections_query = (
        db.query(ReviewCorrection)
        .join(Run, Run.id == ReviewCorrection.run_id)
        .filter(
            Run.project_id == run.project_id,
            Run.deleted_at.is_(None),
            ReviewCorrection.status == CorrectionStatus.APPROVED,
            ReviewCorrection.is_active.is_(True),
        )
        .order_by(ReviewCorrection.created_at.desc(), ReviewCorrection.id.desc())
    )
    if not isinstance(run, _ProjectAnalysisScope):
        corrections_query = corrections_query.filter(ReviewCorrection.task == run.task)
    approved_corrections = corrections_query.all()
    category_example_counts = _category_example_counts(approved_corrections)
    correction_count = len(approved_corrections)
    enabled_document_count = (
        db.query(AnalyzerDocument)
        .filter(
            AnalyzerDocument.project_id == run.project_id,
            AnalyzerDocument.enabled.is_(True),
        )
        .count()
    )

    category_catalog = _category_catalog_reference(db, run.project_id)
    category_catalog_values = _category_catalog_values(category_catalog)
    all_categories = list(category_catalog_values["categories"])
    category_details_map = dict(category_catalog_values["category_details_map"])
    category_taxonomy = dict(category_catalog_values["category_taxonomy"])
    correction_runs = _load_runs_map(
        db, {correction.run_id for correction in approved_corrections}
    )
    category_examples: Dict[str, List[Dict[str, Any]]] = {
        category: [] for category in all_categories
    }
    for correction in approved_corrections:
        categories = _approved_correction_categories(correction)
        if not categories:
            continue
        example_run = correction_runs.get(correction.run_id)
        example = {
                "id": correction.id,
                "item_id": correction.item_id,
                "metric_name": correction.metric_name,
                "run_name": _run_display_name(example_run),
                "dataset": example_run.dataset if example_run else "",
                "model": (
                    _strip_model_provider(example_run.model or "")
                    if example_run
                    else ""
                ),
                "detail": correction.human_root_cause_detail
                or correction.ai_root_cause_detail,
                "note": correction.human_root_cause_note
                or correction.ai_root_cause_note,
                "solution": correction.human_solution or correction.ai_solution,
                "solution_note": correction.human_solution_note
                or correction.ai_solution_note,
                "input": _normalize_snapshot_value(correction.input_snapshot),
                "expected": _normalize_snapshot_value(correction.expected_snapshot),
                "output": _normalize_snapshot_value(correction.output_snapshot),
                "created_at": to_api_timestamp(correction.created_at),
            }
        for category in categories:
            category_examples.setdefault(category, []).append(example)
    active_rule_version = (
        _active_analysis_rule_version(db, project.id) if project else None
    )

    return {
        "llm_configured": default_conn is not None,
        "model": default_conn.llm_model if default_conn else None,
        "llm_connections": connection_payloads,
        "default_connection_id": default_conn.id if default_conn else None,
        "analysis_rules": (
            normalize_analysis_rules(active_rule_version.rules)
            if active_rule_version
            else []
        ),
        "analysis_rule_version": (
            _analysis_rule_version_payload(
                active_rule_version,
                active_version_id=active_rule_version.id,
            )
            if active_rule_version
            else None
        ),
        "can_manage_analysis_rules": is_project_manager(
            db, principal, run.project_id
        ),
        "can_manage_category_catalog": is_project_manager(
            db, principal, run.project_id
        ),
        "can_restore_analysis_rules": principal.user.role == UserRole.ADMIN,
        "total_items": total,
        "items_with_root_cause": with_rc,
        "items_ai_assigned": ai_assigned,
        "items_without_root_cause": total - with_rc,
        "correction_bank_size": correction_count,
        "approved_example_count": correction_count,
        "enabled_document_count": enabled_document_count,
        "analysis_limits": {
            "document_upload_bytes": MAX_REFERENCE_UPLOAD_BYTES,
            "document_prompt_characters": MAX_REFERENCE_DOCUMENT_CHARS,
            "document_content_characters": MAX_REFERENCE_DOCUMENT_CONTENT_CHARS,
            "documents_prompt_characters": MAX_TOTAL_REFERENCE_DOCUMENT_CHARS,
            "max_reference_documents": 8,
            "rule_writer_document_characters": MAX_RULE_WRITER_DOCUMENT_CHARS,
            "rule_writer_example_characters": MAX_RULE_WRITER_EXAMPLE_CHARS,
            "rule_writer_prompt_characters": MAX_RULE_WRITER_PROMPT_CHARS,
            "final_prompt_characters": MAX_ANALYSIS_PROMPT_CHARS,
        },
        "default_system_prompt": DEFAULT_SYSTEM_PROMPT,
        "default_categories": all_categories,
        "max_root_cause_categories": category_catalog_values[
            "max_root_cause_categories"
        ],
        "default_solution_categories": SOLUTION_CATEGORIES,
        "category_details_map": category_details_map,
        "category_taxonomy": category_taxonomy,
        "category_example_counts": {
            category: category_example_counts.get(category, 0)
            for category, examples in category_examples.items()
        },
        "category_examples": category_examples,
        # Keep flat list for backwards compatibility
        "existing_details": _ordered_unique(
            [d for dets in category_details_map.values() for d in dets]
        ),
        "category_catalog_version": category_catalog_values["version"],
        "category_catalog_version_id": category_catalog_values["id"],
        "category_catalog": _category_catalog_payload(
            category_catalog,
            can_manage=is_project_manager(db, principal, run.project_id),
        ),
    }


# ── Project-scoped analyzer context endpoints ───────────────────────


@router.get("/api/projects/{project_slug}/analysis-config")
def get_project_analysis_config(
    project_slug: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> Dict[str, Any]:
    """Return analyzer configuration without requiring a project run."""
    return get_analysis_config(
        run_id=_project_analysis_scope_key(project_slug),
        db=db,
        principal=principal,
    )


def _project_category_catalog_scope(
    db: Session,
    principal: Principal,
    project_slug: str,
    *,
    modify: bool = False,
) -> tuple[str, bool]:
    scope = _resolve_analysis_scope(
        db,
        principal,
        _project_analysis_scope_key(project_slug),
        modify=modify,
    )
    return scope.project_id, is_project_manager(db, principal, scope.project_id)


@router.get("/api/projects/{project_slug}/analysis-category-catalog")
def get_project_category_catalog(
    project_slug: str,
    version: Optional[int] = Query(default=None, ge=0),
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> Dict[str, Any]:
    project_id, can_manage = _project_category_catalog_scope(
        db, principal, project_slug
    )
    catalog = _category_catalog_reference(db, project_id, version)
    payload = _category_catalog_payload(catalog, can_manage=can_manage)
    # Keep the snapshot top-level for simple clients and nested for the write
    # response shape used by the project workspace.
    return {**payload, "catalog": payload}


def _list_project_category_catalog_versions(
    db: Session,
    principal: Principal,
    project_id: str,
) -> Dict[str, Any]:
    can_manage = is_project_manager(db, principal, project_id)
    versions = (
        db.query(ProjectAnalysisCategoryCatalogVersion)
        .filter(ProjectAnalysisCategoryCatalogVersion.project_id == project_id)
        .order_by(ProjectAnalysisCategoryCatalogVersion.version.desc())
        .all()
    )
    versions_payload = [
        _category_catalog_payload(version, can_manage=can_manage)
        for version in versions
    ]
    versions_payload.append(
        _category_catalog_payload(
            _synthetic_category_catalog(db, project_id), can_manage=can_manage
        )
    )
    return {"versions": versions_payload, "can_manage": can_manage}


@router.get("/api/projects/{project_slug}/analysis-category-catalog/versions")
def list_project_category_catalog_versions(
    project_slug: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> Dict[str, Any]:
    project_id, _ = _project_category_catalog_scope(db, principal, project_slug)
    return _list_project_category_catalog_versions(db, principal, project_id)


@router.get("/api/projects/{project_slug}/analysis-category-catalog/history")
def list_project_category_catalog_history(
    project_slug: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> Dict[str, Any]:
    project_id, _ = _project_category_catalog_scope(db, principal, project_slug)
    return _list_project_category_catalog_versions(db, principal, project_id)


@router.put("/api/projects/{project_slug}/analysis-category-catalog")
def update_project_category_catalog(
    project_slug: str,
    request: CategoryCatalogUpdate,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> Dict[str, Any]:
    project_id, _ = _project_category_catalog_scope(
        db, principal, project_slug, modify=True
    )
    current = _active_category_catalog(db, project_id)
    current_version = int(current.version) if current is not None else 0
    expected = (
        request.base_revision
        if request.base_revision is not None
        else request.expected_version
    )
    if expected is not None and expected != current_version:
        raise _catalog_conflict(db, project_id, principal, current)

    prior = current or _synthetic_category_catalog(db, project_id)
    values = _catalog_request_values(db, project_id, request, prior)
    if current is not None and values["content_hash"] == current.content_hash:
        return {
            "catalog": _category_catalog_payload(
                current, can_manage=is_project_manager(db, principal, project_id)
            ),
            "created": False,
        }

    version = _create_category_catalog_version(
        db,
        project_id=project_id,
        values=values,
        parent=current,
        restored_from=None,
        actor_user_id=(principal.user.id if principal.auth_type != "none" else None),
    )
    db.commit()
    db.refresh(version)
    return {
        "catalog": _category_catalog_payload(
            version, can_manage=is_project_manager(db, principal, project_id)
        ),
        "created": True,
    }


def _restore_project_category_catalog(
    *,
    project_slug: str,
    version_ref: str,
    request: CategoryCatalogRestore,
    db: Session,
    principal: Principal,
) -> Dict[str, Any]:
    project_id, _ = _project_category_catalog_scope(
        db, principal, project_slug, modify=True
    )
    current = _active_category_catalog(db, project_id)
    current_version = int(current.version) if current is not None else 0
    expected = (
        request.base_revision
        if request.base_revision is not None
        else request.expected_version
    )
    if expected is not None and expected != current_version:
        raise _catalog_conflict(db, project_id, principal, current)

    source = _category_catalog_reference(db, project_id, version_ref)
    source_values = _category_catalog_values(source)
    values = {
        **source_values,
        "category_entries": _catalog_entries_for_categories(
            source_values["categories"],
            requested_entries=source_values["category_entries"],
            prior_entries=source_values["category_entries"],
            project_id=project_id,
        ),
    }
    values["content_hash"] = _category_catalog_hash(
        categories=values["categories"],
        category_entries=values["category_entries"],
        category_details_map=values["category_details_map"],
        category_taxonomy=values["category_taxonomy"],
        max_root_cause_categories=values["max_root_cause_categories"],
    )
    version = _create_category_catalog_version(
        db,
        project_id=project_id,
        values=values,
        parent=current,
        restored_from=source if isinstance(source, ProjectAnalysisCategoryCatalogVersion) else None,
        actor_user_id=(principal.user.id if principal.auth_type != "none" else None),
        source="restore",
    )
    db.commit()
    db.refresh(version)
    return {
        "catalog": _category_catalog_payload(
            version, can_manage=is_project_manager(db, principal, project_id)
        ),
        "created": True,
    }


@router.post(
    "/api/projects/{project_slug}/analysis-category-catalog/versions/{version_id}:restore"
)
def restore_project_category_catalog(
    project_slug: str,
    version_id: str,
    request: CategoryCatalogRestore = CategoryCatalogRestore(),
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> Dict[str, Any]:
    return _restore_project_category_catalog(
        project_slug=project_slug,
        version_ref=version_id,
        request=request,
        db=db,
        principal=principal,
    )


@router.post(
    "/api/projects/{project_slug}/analysis-category-catalog/{version_ref}/restore"
)
def restore_project_category_catalog_legacy(
    project_slug: str,
    version_ref: str,
    request: CategoryCatalogRestore = CategoryCatalogRestore(),
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> Dict[str, Any]:
    return _restore_project_category_catalog(
        project_slug=project_slug,
        version_ref=version_ref,
        request=request,
        db=db,
        principal=principal,
    )


@router.get("/api/projects/{project_slug}/analysis-documents")
def list_project_analysis_documents(
    project_slug: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> Dict[str, Any]:
    return list_analysis_documents(
        run_id=_project_analysis_scope_key(project_slug),
        db=db,
        principal=principal,
    )


@router.get("/api/projects/{project_slug}/analysis-examples")
def list_project_analysis_examples(
    project_slug: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    task: Optional[List[str]] = Query(None),
    dataset: Optional[List[str]] = Query(None),
    model: Optional[List[str]] = Query(None),
    run_name: Optional[List[str]] = Query(None),
    user_id: Optional[List[str]] = Query(None),
    source: Optional[str] = Query(None),
    conf_min: int = Query(0, ge=0, le=100),
    conf_max: int = Query(100, ge=0, le=100),
    search: Optional[str] = Query(None),
    selected_id: Optional[List[int]] = Query(None),
    selected_only: bool = Query(False),
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> Dict[str, Any]:
    return list_analysis_examples(
        run_id=_project_analysis_scope_key(project_slug),
        page=page,
        page_size=page_size,
        task=task,
        dataset=dataset,
        model=model,
        run_name=run_name,
        user_id=user_id,
        source=source,
        conf_min=conf_min,
        conf_max=conf_max,
        search=search,
        selected_id=selected_id,
        selected_only=selected_only,
        db=db,
        principal=principal,
    )


@router.post("/api/projects/{project_slug}/analysis-examples")
def query_project_analysis_examples(
    project_slug: str,
    request: AnalysisExamplesQuery,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> Dict[str, Any]:
    return query_analysis_examples(
        run_id=_project_analysis_scope_key(project_slug),
        request=request,
        db=db,
        principal=principal,
    )


@router.post("/api/projects/{project_slug}/analysis-documents")
async def upload_project_analysis_document(
    project_slug: str,
    file: UploadFile = File(...),
    large_document_action: Literal["ask", "truncate", "full"] = Form("ask"),
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> Dict[str, Any]:
    return await upload_analysis_document(
        run_id=_project_analysis_scope_key(project_slug),
        file=file,
        large_document_action=large_document_action,
        db=db,
        principal=principal,
    )


@router.patch("/api/projects/{project_slug}/analysis-documents/{document_id}")
def select_project_analysis_document(
    project_slug: str,
    document_id: str,
    request: AnalyzerDocumentSelection,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> Dict[str, Any]:
    return select_analysis_document(
        run_id=_project_analysis_scope_key(project_slug),
        document_id=document_id,
        request=request,
        db=db,
        principal=principal,
    )


@router.delete("/api/projects/{project_slug}/analysis-documents/{document_id}")
def delete_project_analysis_document(
    project_slug: str,
    document_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> Dict[str, Any]:
    return delete_analysis_document(
        run_id=_project_analysis_scope_key(project_slug),
        document_id=document_id,
        db=db,
        principal=principal,
    )


@router.patch("/api/projects/{project_slug}/analysis-context")
def update_project_analysis_context(
    project_slug: str,
    request: AnalysisContextUpdate,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> Dict[str, Any]:
    return update_analysis_context(
        run_id=_project_analysis_scope_key(project_slug),
        request=request,
        db=db,
        principal=principal,
    )


@router.post("/api/projects/{project_slug}/analysis-rules/infer")
async def infer_project_scoped_analysis_rules(
    project_slug: str,
    request: RuleInferenceRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> Dict[str, Any]:
    return await infer_project_analysis_rules(
        run_id=_project_analysis_scope_key(project_slug),
        request=request,
        db=db,
        principal=principal,
    )


@router.get("/api/projects/{project_slug}/analysis-rule-versions")
def list_project_scoped_analysis_rule_versions(
    project_slug: str,
    include_deleted: bool = Query(default=False),
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> Dict[str, Any]:
    return list_project_analysis_rule_versions(
        run_id=_project_analysis_scope_key(project_slug),
        include_deleted=include_deleted,
        db=db,
        principal=principal,
    )


@router.get("/api/projects/{project_slug}/analysis-rule-lineage")
def get_project_scoped_analysis_rule_lineage(
    project_slug: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> Dict[str, Any]:
    return get_project_analysis_rule_lineage(
        run_id=_project_analysis_scope_key(project_slug),
        db=db,
        principal=principal,
    )


@router.post("/api/projects/{project_slug}/analysis-rule-versions")
def create_project_scoped_analysis_rule_version(
    project_slug: str,
    request: AnalysisRuleVersionCreate,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> Dict[str, Any]:
    return create_project_analysis_rule_version(
        run_id=_project_analysis_scope_key(project_slug),
        request=request,
        db=db,
        principal=principal,
    )


@router.post(
    "/api/projects/{project_slug}/analysis-rule-versions/{version_ref}:publish"
)
def publish_project_scoped_analysis_rule_version(
    project_slug: str,
    version_ref: str,
    request: AnalysisRuleVersionPublish,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> Dict[str, Any]:
    return publish_project_analysis_rule_version(
        run_id=_project_analysis_scope_key(project_slug),
        version_ref=version_ref,
        request=request,
        db=db,
        principal=principal,
    )


@router.post("/api/projects/{project_slug}/analysis-rule-aliases/{alias_name}")
def set_project_scoped_analysis_rule_alias(
    project_slug: str,
    alias_name: str,
    request: AnalysisRuleAliasUpdate,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> Dict[str, Any]:
    return set_project_analysis_rule_alias(
        run_id=_project_analysis_scope_key(project_slug),
        alias_name=alias_name,
        request=request,
        db=db,
        principal=principal,
    )


@router.get(
    "/api/projects/{project_slug}/analysis-rule-versions/{version_ref}:compare"
)
def compare_project_scoped_analysis_rule_versions(
    project_slug: str,
    version_ref: str,
    base: str = Query(...),
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> Dict[str, Any]:
    return compare_project_analysis_rule_versions(
        run_id=_project_analysis_scope_key(project_slug),
        version_ref=version_ref,
        base=base,
        db=db,
        principal=principal,
    )


@router.post(
    "/api/projects/{project_slug}/analysis-rule-versions/{target_ref}:merge"
)
def merge_project_scoped_analysis_rule_versions(
    project_slug: str,
    target_ref: str,
    request: AnalysisRuleMergeRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> Dict[str, Any]:
    return merge_project_analysis_rule_versions(
        run_id=_project_analysis_scope_key(project_slug),
        target_ref=target_ref,
        request=request,
        db=db,
        principal=principal,
    )


@router.post(
    "/api/projects/{project_slug}/analysis-rule-versions/{version_id}/activate"
)
def activate_project_scoped_analysis_rule_version(
    project_slug: str,
    version_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> Dict[str, Any]:
    return activate_project_analysis_rule_version(
        run_id=_project_analysis_scope_key(project_slug),
        version_id=version_id,
        db=db,
        principal=principal,
    )


@router.delete(
    "/api/projects/{project_slug}/analysis-rule-versions/{version_id}"
)
def delete_project_scoped_analysis_rule_version(
    project_slug: str,
    version_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> Dict[str, Any]:
    return delete_project_analysis_rule_version(
        run_id=_project_analysis_scope_key(project_slug),
        version_id=version_id,
        db=db,
        principal=principal,
    )


@router.post(
    "/api/projects/{project_slug}/analysis-rule-versions/{version_id}/restore"
)
def restore_project_scoped_analysis_rule_version(
    project_slug: str,
    version_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> Dict[str, Any]:
    return restore_project_analysis_rule_version(
        run_id=_project_analysis_scope_key(project_slug),
        version_id=version_id,
        db=db,
        principal=principal,
    )


@router.delete(
    "/api/projects/{project_slug}/analysis-rule-versions/{version_id}/permanent"
)
def permanently_delete_project_scoped_analysis_rule_version(
    project_slug: str,
    version_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> Dict[str, Any]:
    return permanently_delete_project_analysis_rule_version(
        run_id=_project_analysis_scope_key(project_slug),
        version_id=version_id,
        db=db,
        principal=principal,
    )


# ── Correction Management Endpoints (for /reviews page) ─────────────


def _serialize_user(user: Optional[User]) -> Optional[Dict[str, Any]]:
    if not user:
        return None
    return {
        "id": user.id,
        "email": user.email,
        "display_name": user.display_name or user.email.split("@")[0],
    }


def _load_users_map(db: Session, user_ids: set[str]) -> Dict[str, User]:
    if not user_ids:
        return {}
    users = db.query(User).filter(User.id.in_(sorted(user_ids))).all()
    return {u.id: u for u in users}


def _strip_model_provider(model_name: str) -> str:
    if not model_name:
        return ""
    idx = model_name.find("/")
    return model_name[idx + 1 :] if idx > 0 else model_name


def _run_display_name(run: Optional[Run]) -> str:
    if not run:
        return ""
    if isinstance(run.run_config, dict):
        configured = str(run.run_config.get("run_name") or "").strip()
        if configured:
            return configured
    return str(run.external_run_id or run.id or "").strip()


def _load_runs_map(db: Session, run_ids: set[str]) -> Dict[str, Run]:
    if not run_ids:
        return {}
    runs = Run.active(db).filter(Run.id.in_(sorted(run_ids))).all()
    return {run.id: run for run in runs}


def _run_name_value(
    run_id: str, external_run_id: Optional[str], configured_name: Optional[str]
) -> str:
    configured = str(configured_name or "").strip()
    if configured:
        return configured
    return str(external_run_id or run_id or "").strip()


def _normalize_snapshot_value(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    trimmed = value.strip()
    if not trimmed:
        return value
    if not (
        (trimmed.startswith("{") and trimmed.endswith("}"))
        or (trimmed.startswith("[") and trimmed.endswith("]"))
    ):
        return value
    try:
        parsed = ast.literal_eval(trimmed)
    except (SyntaxError, ValueError):
        return value
    return parsed


def _serialize_review_fields(
    c: ReviewCorrection,
    *,
    users_by_id: Dict[str, User],
    runs_by_id: Dict[str, Run],
) -> Dict[str, Any]:
    ai_root_cause = (c.ai_root_cause or "").strip()
    ai_is_unanalyzed = ai_root_cause.lower() == "unanalyzed"
    run = runs_by_id.get(c.run_id)
    run_trace_stats = (
        run.run_metadata.get("trace_stats")
        if run and isinstance(run.run_metadata, dict)
        else None
    )
    has_reasoning = bool(
        isinstance(run_trace_stats, dict)
        and (
            run_trace_stats.get("has_reasoning")
            or run_trace_stats.get("has_reasoning_tokens")
            or (run_trace_stats.get("avg_reasoning_tokens") or 0) > 0
        )
    )
    return {
        "id": c.id,
        "revision_id": c.revision_id,
        "run_id": c.run_id,
        "item_id": c.item_id,
        "metric_name": c.metric_name,
        "task": c.task,
        "dataset": run.dataset if run else "",
        "model": _strip_model_provider(run.model or "") if run else "",
        "has_reasoning": has_reasoning,
        "run_name": _run_display_name(run),
        "input_snapshot": _normalize_snapshot_value(c.input_snapshot),
        "expected_snapshot": _normalize_snapshot_value(c.expected_snapshot),
        "output_snapshot": _normalize_snapshot_value(c.output_snapshot),
        "scores_snapshot": _normalize_snapshot_value(c.scores_snapshot),
        "ai_root_cause": "" if ai_is_unanalyzed else c.ai_root_cause,
        "ai_root_causes": (
            []
            if ai_is_unanalyzed
            else normalize_root_causes(c.ai_root_causes or c.ai_root_cause)
        ),
        "ai_category_taxonomy": (
            {}
            if ai_is_unanalyzed
            else normalize_category_taxonomy(
                getattr(c, "ai_category_taxonomy", None)
            )
        ),
        "ai_root_cause_detail": "" if ai_is_unanalyzed else c.ai_root_cause_detail,
        "ai_root_cause_note": "" if ai_is_unanalyzed else c.ai_root_cause_note,
        "ai_confidence": None if ai_is_unanalyzed else c.ai_confidence,
        "ai_solution": "" if ai_is_unanalyzed else c.ai_solution,
        "ai_solution_note": "" if ai_is_unanalyzed else c.ai_solution_note,
        "human_root_cause": c.human_root_cause,
        "human_root_causes": normalize_root_causes(
            c.human_root_causes or c.human_root_cause
        ),
        "human_category_taxonomy": normalize_category_taxonomy(
            getattr(c, "human_category_taxonomy", None)
        ),
        "human_root_cause_detail": c.human_root_cause_detail,
        "human_root_cause_note": c.human_root_cause_note,
        "human_solution": c.human_solution,
        "human_solution_note": c.human_solution_note,
        "corrected_by": _serialize_user(users_by_id.get(c.corrected_by_user_id)),
        "created_at": to_api_timestamp(c.created_at),
        "status": c.status.value if hasattr(c.status, "value") else c.status,
        "is_active": bool(c.is_active),
        "reviewed_by": _serialize_user(users_by_id.get(c.reviewed_by_user_id)),
        "reviewed_at": to_api_timestamp(c.reviewed_at),
        "review_comment": c.review_comment or "",
    }


def _build_history_map(
    db: Session,
    corrections: List[ReviewCorrection],
) -> tuple[Dict[tuple[str, str, Optional[str]], List[Dict[str, Any]]], Dict[str, User]]:
    keys = sorted({(c.run_id, c.item_id) for c in corrections})
    if not keys:
        return {}, {}

    revisions = (
        db.query(RootCauseRevision)
        .filter(tuple_(RootCauseRevision.run_id, RootCauseRevision.item_id).in_(keys))
        .order_by(
            RootCauseRevision.run_id.asc(),
            RootCauseRevision.item_id.asc(),
            RootCauseRevision.revision_number.desc(),
        )
        .all()
    )
    all_candidates = (
        db.query(ReviewCorrection)
        .filter(tuple_(ReviewCorrection.run_id, ReviewCorrection.item_id).in_(keys))
        .order_by(ReviewCorrection.created_at.desc())
        .all()
    )

    user_ids: set[str] = {
        uid
        for uid in [
            *(r.actor_user_id for r in revisions if r.actor_user_id),
            *(c.corrected_by_user_id for c in all_candidates if c.corrected_by_user_id),
            *(c.reviewed_by_user_id for c in all_candidates if c.reviewed_by_user_id),
        ]
        if uid
    }
    users_by_id = _load_users_map(db, user_ids)
    runs_by_id = _load_runs_map(db, {run_id for run_id, _ in keys})

    candidates_by_revision: Dict[int, ReviewCorrection] = {}
    orphan_candidates: Dict[tuple[str, str, Optional[str]], List[ReviewCorrection]] = {}
    for candidate in all_candidates:
        if (
            candidate.revision_id is not None
            and candidate.revision_id not in candidates_by_revision
        ):
            candidates_by_revision[candidate.revision_id] = candidate
        elif candidate.revision_id is None:
            orphan_candidates.setdefault(
                (candidate.run_id, candidate.item_id, candidate.metric_name), []
            ).append(candidate)

    history_map: Dict[tuple[str, str, Optional[str]], List[Dict[str, Any]]] = {}
    revisions_by_key: Dict[tuple[str, str, Optional[str]], List[RootCauseRevision]] = {}
    for revision in revisions:
        revisions_by_key.setdefault(
            (revision.run_id, revision.item_id, None), []
        ).append(revision)

    for key, revision_list in revisions_by_key.items():
        entries: List[Dict[str, Any]] = []
        for revision in revision_list:
            review_candidate = candidates_by_revision.get(revision.id)
            entries.append(
                {
                    "revision_id": revision.id,
                    "revision_number": revision.revision_number,
                    "actor_source": revision.actor_source,
                    "actor_user": _serialize_user(
                        users_by_id.get(revision.actor_user_id)
                    ),
                    "before_state": revision.before_state or {},
                    "after_state": revision.after_state or {},
                    "backfilled_from_legacy": bool(revision.backfilled_from_legacy),
                    "created_at": to_api_timestamp(revision.created_at),
                    "review": (
                        _serialize_review_fields(
                            review_candidate,
                            users_by_id=users_by_id,
                            runs_by_id=runs_by_id,
                        )
                        if review_candidate
                        else None
                    ),
                }
            )
        for orphan in orphan_candidates.get(key, []):
            entries.append(
                {
                    "revision_id": None,
                    "revision_number": None,
                    "actor_source": "legacy",
                    "actor_user": _serialize_user(
                        users_by_id.get(orphan.corrected_by_user_id)
                    ),
                    "before_state": {},
                    "after_state": {},
                    "backfilled_from_legacy": True,
                    "created_at": to_api_timestamp(orphan.created_at),
                    "review": _serialize_review_fields(
                        orphan, users_by_id=users_by_id, runs_by_id=runs_by_id
                    ),
                }
            )
        history_map[key] = sorted(
            entries,
            key=lambda entry: (
                (
                    entry["revision_number"]
                    if entry["revision_number"] is not None
                    else -1
                ),
                entry["created_at"] or "",
            ),
            reverse=True,
        )

    for key, candidates in orphan_candidates.items():
        if key in history_map:
            continue
        history_map[key] = [
            {
                "revision_id": None,
                "revision_number": None,
                "actor_source": "legacy",
                "actor_user": _serialize_user(
                    users_by_id.get(candidate.corrected_by_user_id)
                ),
                "before_state": {},
                "after_state": {},
                "backfilled_from_legacy": True,
                "created_at": to_api_timestamp(candidate.created_at),
                "review": _serialize_review_fields(
                    candidate, users_by_id=users_by_id, runs_by_id=runs_by_id
                ),
            }
            for candidate in candidates
        ]

    return history_map, users_by_id


def _serialize_correction(
    c: ReviewCorrection,
    *,
    users_by_id: Dict[str, User],
    runs_by_id: Dict[str, Run],
    history: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    payload = _serialize_review_fields(
        c, users_by_id=users_by_id, runs_by_id=runs_by_id
    )
    payload["history"] = history or []
    return payload


def _serialize_corrections_with_history(
    db: Session,
    corrections: List[ReviewCorrection],
) -> List[Dict[str, Any]]:
    history_map, users_by_id = _build_history_map(db, corrections)
    runs_by_id = _load_runs_map(db, {correction.run_id for correction in corrections})
    serialized: List[Dict[str, Any]] = []
    for correction in corrections:
        serialized.append(
            _serialize_correction(
                correction,
                users_by_id=users_by_id,
                runs_by_id=runs_by_id,
                history=history_map.get(
                    (correction.run_id, correction.item_id, correction.metric_name), []
                ),
            )
        )
    return serialized


def _require_active_candidate(correction: ReviewCorrection) -> None:
    if not correction.is_active:
        raise HTTPException(
            status_code=409, detail="Historical corrections are immutable"
        )


def _approve_candidate(
    db: Session,
    *,
    correction: ReviewCorrection,
    reviewer_id: Optional[str],
    comment: str,
    reviewed_at: datetime,
) -> None:
    _require_active_candidate(correction)

    has_human_label = any(
        str(value or "").strip()
        for value in (
            correction.human_root_cause,
            correction.human_root_cause_detail,
            correction.human_root_cause_note,
            correction.human_solution,
            correction.human_solution_note,
        )
    ) or bool(correction.human_root_causes)
    if not has_human_label and str(correction.ai_root_cause or "").strip():
        correction.human_root_cause = correction.ai_root_cause or ""
        correction.human_root_causes = normalize_root_causes(
            correction.ai_root_causes or correction.ai_root_cause
        )
        correction.human_category_taxonomy = normalize_category_taxonomy(
            getattr(correction, "ai_category_taxonomy", None)
        )
        correction.human_root_cause_detail = correction.ai_root_cause_detail or ""
        correction.human_root_cause_note = correction.ai_root_cause_note or ""
        correction.human_solution = correction.ai_solution or ""
        correction.human_solution_note = correction.ai_solution_note or ""

    metric_scope = (
        ReviewCorrection.metric_name.is_(None)
        if correction.metric_name is None
        else ReviewCorrection.metric_name == correction.metric_name
    )
    older_approved = (
        db.query(ReviewCorrection)
        .filter(
            ReviewCorrection.run_id == correction.run_id,
            ReviewCorrection.item_id == correction.item_id,
            metric_scope,
            ReviewCorrection.id != correction.id,
            ReviewCorrection.status == CorrectionStatus.APPROVED,
        )
        .all()
    )
    for candidate in older_approved:
        candidate.status = CorrectionStatus.SUPERSEDED
        candidate.is_active = False

    correction.status = CorrectionStatus.APPROVED
    correction.is_active = True
    correction.reviewed_by_user_id = reviewer_id
    correction.reviewed_at = reviewed_at
    correction.review_comment = comment


def _reject_candidate(
    db: Session,
    *,
    correction: ReviewCorrection,
    reviewer_id: Optional[str],
    comment: str,
    reviewed_at: datetime,
) -> None:
    """Reject a review candidate while preserving its full audit history."""
    _require_active_candidate(correction)
    correction.status = CorrectionStatus.REJECTED
    correction.reviewed_by_user_id = reviewer_id
    correction.reviewed_at = reviewed_at
    correction.review_comment = comment


def _sync_legacy_summary_after_metric_deletion(
    *,
    run: Run,
    meta: dict[str, Any],
    deleted_metric_name: str,
    metric_analyses: dict[str, Any],
) -> dict[str, Any]:
    """Keep the compatibility item summary aligned with metric diagnoses."""
    legacy_metric_name = str(meta.get("root_cause_metric_name") or "").strip()
    if (
        meta.get("root_cause_source") == "human"
        or legacy_metric_name != deleted_metric_name
    ):
        return _sync_item_analysis_warning(meta)

    run_metric_names = [str(metric_name) for metric_name in (run.metrics or [])]
    run_metric_name_set = set(run_metric_names)
    ordered_metric_names = [
        *run_metric_names,
        *(
            str(metric_name)
            for metric_name in metric_analyses
            if str(metric_name) not in run_metric_name_set
        ),
    ]
    replacement: tuple[str, dict[str, Any]] | None = None
    for metric_name in ordered_metric_names:
        analysis = metric_analyses.get(metric_name)
        if (
            isinstance(analysis, dict)
            and not analysis.get("error")
            and analysis_root_causes(analysis)
        ):
            replacement = (metric_name, analysis)
            break

    if replacement is None:
        return _sync_item_analysis_warning(build_item_metadata(meta, {}))

    replacement_metric_name, analysis = replacement
    source = str(analysis.get("source") or "").strip()
    if source not in {"ai", "human", "system"}:
        source = "ai"
    solution = str(analysis.get("solution") or "").strip()
    synced = build_item_metadata(
        meta,
        {
            "root_cause": analysis.get("root_cause"),
            "root_causes": analysis_root_causes(analysis),
            "category_taxonomy": normalize_category_taxonomy(
                analysis.get("category_taxonomy")
            ),
            "root_cause_detail": analysis.get("root_cause_detail"),
            "root_cause_reason": analysis.get("root_cause_reason"),
            "root_cause_note": analysis.get("root_cause_note"),
            "root_cause_source": source,
            "root_cause_confidence": analysis.get("confidence"),
            "solution": solution,
            "solution_note": analysis.get("solution_note"),
            "solution_source": source if solution else "",
        },
    )
    synced["root_cause_metric_name"] = replacement_metric_name
    return _sync_item_analysis_warning(synced)


def _delete_active_candidate(
    db: Session,
    *,
    correction: ReviewCorrection,
    reviewer_id: Optional[str],
    comment: str,
    reviewed_at: datetime,
) -> None:
    """Remove a candidate from reviews while retaining a rejected audit record."""
    _require_active_candidate(correction)
    run = Run.active(db).filter(Run.id == correction.run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    item = (
        db.query(RunItem)
        .filter(
            RunItem.run_id == correction.run_id,
            RunItem.item_id == correction.item_id,
        )
        .first()
    )
    if not item:
        raise HTTPException(status_code=404, detail="Run item not found")

    if correction.metric_name:
        meta = dict(item.item_metadata) if isinstance(item.item_metadata, dict) else {}
        metric_analyses = dict(meta.get("metric_analyses") or {})
        metric_analyses.pop(correction.metric_name, None)
        if metric_analyses:
            meta["metric_analyses"] = metric_analyses
        else:
            meta.pop("metric_analyses", None)
        item.item_metadata = _sync_legacy_summary_after_metric_deletion(
            run=run,
            meta=meta,
            deleted_metric_name=correction.metric_name,
            metric_analyses=metric_analyses,
        )
        correction.status = CorrectionStatus.REJECTED
        correction.is_active = False
        correction.reviewed_by_user_id = reviewer_id
        correction.reviewed_at = reviewed_at
        correction.review_comment = comment
        return

    apply_root_cause_change(
        db,
        run=run,
        item=item,
        actor_user_id=reviewer_id,
        actor_source="system",
        next_state={},
    )

    # Keep the row for review history, but deactivate it so it is deleted from
    # the active Reviews collection. apply_root_cause_change may supersede it,
    # so record the requested rejection after clearing the run item state.
    correction.status = CorrectionStatus.REJECTED
    correction.is_active = False
    correction.reviewed_by_user_id = reviewer_id
    correction.reviewed_at = reviewed_at
    correction.review_comment = comment


@router.get("/api/corrections")
def list_corrections(
    project_slug: Optional[str] = Query(None),
    task: Optional[List[str]] = Query(None),
    dataset: Optional[List[str]] = Query(None),
    model: Optional[List[str]] = Query(None),
    run_name: Optional[List[str]] = Query(None),
    source: Optional[str] = Query(None),
    conf_min: int = Query(0, ge=0, le=100),
    conf_max: int = Query(100, ge=0, le=100),
    status: Optional[str] = Query(None, alias="status"),
    search: Optional[str] = Query(None),
    limit: Optional[int] = Query(None, ge=1, le=500),
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> Dict[str, Any]:
    """List all corrections with optional filtering."""
    run_name_expr = func.coalesce(
        cast(Run.run_config.op("->>")("run_name"), String), ""
    )
    ai_root_cause_expr = func.btrim(func.coalesce(ReviewCorrection.ai_root_cause, ""))
    ai_root_cause_detail_expr = func.btrim(
        func.coalesce(ReviewCorrection.ai_root_cause_detail, "")
    )
    ai_root_cause_note_expr = func.btrim(
        func.coalesce(ReviewCorrection.ai_root_cause_note, "")
    )
    ai_solution_expr = func.btrim(func.coalesce(ReviewCorrection.ai_solution, ""))
    ai_solution_note_expr = func.btrim(
        func.coalesce(ReviewCorrection.ai_solution_note, "")
    )
    human_root_cause_expr = func.btrim(
        func.coalesce(ReviewCorrection.human_root_cause, "")
    )
    human_root_cause_detail_expr = func.btrim(
        func.coalesce(ReviewCorrection.human_root_cause_detail, "")
    )
    human_root_cause_note_expr = func.btrim(
        func.coalesce(ReviewCorrection.human_root_cause_note, "")
    )
    human_solution_expr = func.btrim(func.coalesce(ReviewCorrection.human_solution, ""))
    human_solution_note_expr = func.btrim(
        func.coalesce(ReviewCorrection.human_solution_note, "")
    )

    has_ai_data = or_(
        and_(ai_root_cause_expr != "", func.lower(ai_root_cause_expr) != "unanalyzed"),
        ai_root_cause_detail_expr != "",
        ai_root_cause_note_expr != "",
        ai_solution_expr != "",
        ai_solution_note_expr != "",
    )
    has_human_data = or_(
        human_root_cause_expr != "",
        human_root_cause_detail_expr != "",
        human_root_cause_note_expr != "",
        human_solution_expr != "",
        human_solution_note_expr != "",
    )
    is_changed = or_(
        ai_root_cause_expr != human_root_cause_expr,
        ai_root_cause_detail_expr != human_root_cause_detail_expr,
        ai_root_cause_note_expr != human_root_cause_note_expr,
        ai_solution_expr != human_solution_expr,
        ai_solution_note_expr != human_solution_note_expr,
    )

    active_query = (
        db.query(ReviewCorrection)
        .join(Run, Run.id == ReviewCorrection.run_id)
        .filter(ReviewCorrection.is_active.is_(True))
    )
    active_query = apply_reviewable_run_filter(active_query, db, principal)
    if project_slug:
        project = (
            db.query(Project)
            .filter(Project.slug == project_slug, Project.is_active.is_(True))
            .first()
        )
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        active_query = active_query.filter(Run.project_id == project.id)

    def apply_filter_set(base_query, *, exclude: Optional[str] = None):
        query_obj = base_query
        if task and exclude != "task":
            query_obj = query_obj.filter(ReviewCorrection.task.in_(task))
        if dataset and exclude != "dataset":
            query_obj = query_obj.filter(Run.dataset.in_(dataset))
        if model and exclude != "model":
            query_obj = query_obj.filter(
                or_(
                    *(
                        [Run.model == value for value in model]
                        + [Run.model.ilike(f"%/{value}") for value in model]
                    )
                )
            )
        if run_name and exclude != "run_name":
            query_obj = query_obj.filter(
                or_(
                    Run.external_run_id.in_(run_name),
                    run_name_expr.in_(run_name),
                    Run.id.in_(run_name),
                )
            )
        if source == "ai_only":
            query_obj = query_obj.filter(
                has_ai_data,
                or_(~has_human_data, ~is_changed),
            )
        elif source == "human_only":
            query_obj = query_obj.filter(has_human_data, ~has_ai_data)
        elif source == "corrected":
            query_obj = query_obj.filter(has_ai_data, has_human_data, is_changed)
        if conf_min > 0 or conf_max < 100:
            lo = conf_min / 100.0
            hi = conf_max / 100.0
            query_obj = query_obj.filter(
                ReviewCorrection.ai_confidence.is_not(None),
                ReviewCorrection.ai_confidence >= lo,
                ReviewCorrection.ai_confidence <= hi,
            )
        if status and exclude != "status":
            try:
                cs = CorrectionStatus(status)
                query_obj = query_obj.filter(ReviewCorrection.status == cs)
            except ValueError:
                pass
        if search:
            like = f"%{search}%"
            query_obj = query_obj.filter(
                or_(
                    ReviewCorrection.task.ilike(like),
                    ReviewCorrection.item_id.ilike(like),
                    ReviewCorrection.human_root_cause.ilike(like),
                    ReviewCorrection.ai_root_cause.ilike(like),
                    Run.dataset.ilike(like),
                    Run.model.ilike(like),
                    Run.external_run_id.ilike(like),
                    run_name_expr.ilike(like),
                )
            )
        return query_obj

    def facet_value_expr(key: str):
        if key == "task":
            return ReviewCorrection.task
        if key == "dataset":
            return Run.dataset
        if key == "model":
            return Run.model
        if key == "run_name":
            return run_name_expr
        raise ValueError(f"Unsupported facet key: {key}")

    def build_facet_counts(key: str) -> Dict[str, int]:
        facet_query = apply_filter_set(active_query, exclude=key)
        if key == "model":
            rows = (
                facet_query.with_entities(Run.model, func.count(ReviewCorrection.id))
                .group_by(Run.model)
                .all()
            )
            counts: Dict[str, int] = {}
            for raw_model, count in rows:
                if not raw_model:
                    continue
                display = _strip_model_provider(raw_model or "")
                counts[display] = counts.get(display, 0) + int(count or 0)
            return counts
        if key == "run_name":
            rows = (
                facet_query.with_entities(
                    Run.id,
                    Run.external_run_id,
                    run_name_expr,
                    func.count(ReviewCorrection.id),
                )
                .group_by(Run.id, Run.external_run_id, run_name_expr)
                .all()
            )
            counts: Dict[str, int] = {}
            for run_id_value, external_run_id, configured_name, count in rows:
                display = _run_name_value(
                    run_id_value, external_run_id, configured_name
                )
                if not display:
                    continue
                counts[display] = counts.get(display, 0) + int(count or 0)
            return counts
        value_expr = facet_value_expr(key)
        rows = (
            facet_query.with_entities(value_expr, func.count(ReviewCorrection.id))
            .group_by(value_expr)
            .all()
        )
        return {
            str(value): int(count or 0)
            for value, count in rows
            if str(value or "").strip()
        }

    filtered_query = apply_filter_set(active_query)
    filtered_total = (
        filtered_query.with_entities(func.count(ReviewCorrection.id)).scalar() or 0
    )

    query = filtered_query.order_by(ReviewCorrection.created_at.desc())
    if limit is not None:
        query = query.limit(limit)
    corrections = query.all()

    # Compute stats excluding status filter so stat cards show the breakdown
    stats_query = apply_filter_set(active_query, exclude="status")
    total = stats_query.with_entities(func.count(ReviewCorrection.id)).scalar() or 0
    pending = (
        stats_query.filter(ReviewCorrection.status == CorrectionStatus.PENDING)
        .with_entities(func.count(ReviewCorrection.id))
        .scalar()
        or 0
    )
    approved = (
        stats_query.filter(ReviewCorrection.status == CorrectionStatus.APPROVED)
        .with_entities(func.count(ReviewCorrection.id))
        .scalar()
        or 0
    )
    rejected = (
        stats_query.filter(ReviewCorrection.status == CorrectionStatus.REJECTED)
        .with_entities(func.count(ReviewCorrection.id))
        .scalar()
        or 0
    )

    stats = {
        "total": total,
        "pending": pending,
        "approved": approved,
        "rejected": rejected,
    }

    # Get distinct tasks for filter dropdown
    task_rows = (
        apply_filter_set(active_query, exclude="task")
        .with_entities(ReviewCorrection.task)
        .distinct()
        .order_by(ReviewCorrection.task)
        .all()
    )
    tasks = [r[0] for r in task_rows]
    dataset_rows = (
        apply_filter_set(active_query, exclude="dataset")
        .with_entities(Run.dataset)
        .distinct()
        .order_by(Run.dataset)
        .all()
    )
    datasets = [r[0] for r in dataset_rows if r[0]]
    model_rows = (
        apply_filter_set(active_query, exclude="model")
        .with_entities(Run.model)
        .distinct()
        .order_by(Run.model)
        .all()
    )
    models = [_strip_model_provider(r[0] or "") for r in model_rows if r[0]]
    run_rows = (
        apply_filter_set(active_query, exclude="run_name")
        .with_entities(Run.id, Run.external_run_id, run_name_expr.label("run_name"))
        .distinct()
        .all()
    )
    run_names = sorted(
        {
            (_run_name_value(run_id, external, configured_name))
            for run_id, external, configured_name in run_rows
            if _run_name_value(run_id, external, configured_name)
        }
    )

    return {
        "corrections": _serialize_corrections_with_history(db, corrections),
        "total": filtered_total,
        "stats": stats,
        "tasks": tasks,
        "datasets": datasets,
        "models": sorted(set(models)),
        "run_names": run_names,
        "facet_counts": {
            "task": build_facet_counts("task"),
            "dataset": build_facet_counts("dataset"),
            "model": build_facet_counts("model"),
            "run_name": build_facet_counts("run_name"),
        },
    }


@router.get("/api/corrections/{correction_id}")
def get_correction(
    correction_id: int,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> Dict[str, Any]:
    """Get a single correction by ID."""
    c = db.query(ReviewCorrection).filter(ReviewCorrection.id == correction_id).first()
    if not c:
        raise HTTPException(status_code=404, detail="Correction not found")
    run = Run.active(db).filter(Run.id == c.run_id).first()
    if not run or not can_review_run(db, principal, run):
        raise HTTPException(status_code=403, detail="Access denied")
    return _serialize_corrections_with_history(db, [c])[0]


@router.put("/api/corrections/{correction_id}")
def update_correction(
    correction_id: int,
    request: Dict[str, Any],
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> Dict[str, Any]:
    """Apply a new human revision from the reviews page."""
    c = db.query(ReviewCorrection).filter(ReviewCorrection.id == correction_id).first()
    if not c:
        raise HTTPException(status_code=404, detail="Correction not found")
    _require_active_candidate(c)

    run = Run.active(db).filter(Run.id == c.run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    if not can_review_run(db, principal, run):
        raise HTTPException(status_code=403, detail="Access denied")
    item = (
        db.query(RunItem)
        .filter(RunItem.run_id == c.run_id, RunItem.item_id == c.item_id)
        .first()
    )
    if not item:
        raise HTTPException(status_code=404, detail="Run item not found")

    patch: Dict[str, Any] = {}
    for request_key, state_key in [
        ("human_root_cause", "root_cause"),
        ("human_root_causes", "root_causes"),
        ("root_causes", "root_causes"),
        ("human_category_taxonomy", "category_taxonomy"),
        ("category_taxonomy", "category_taxonomy"),
        ("human_root_cause_detail", "root_cause_detail"),
        ("human_root_cause_note", "root_cause_note"),
        ("human_solution", "solution"),
        ("human_solution_note", "solution_note"),
    ]:
        if request_key in request:
            patch[state_key] = request.get(request_key)

    if c.metric_name:
        meta = dict(item.item_metadata) if isinstance(item.item_metadata, dict) else {}
        metric_analyses = dict(meta.get("metric_analyses") or {})
        analysis = dict(metric_analyses.get(c.metric_name) or {})
        if "root_causes" in patch:
            root_causes = normalize_root_causes(
                patch.get("root_causes")
            )
            if root_causes:
                analysis["root_causes"] = root_causes
                analysis["root_cause"] = root_causes[0]
            else:
                for field in (
                    "root_causes",
                    "root_cause",
                    "root_cause_detail",
                    "root_cause_reason",
                    "root_cause_note",
                    "confidence",
                ):
                    analysis.pop(field, None)
        elif "root_cause" in patch:
            root_cause = str(patch.get("root_cause") or "").strip()
            if root_cause:
                analysis["root_cause"] = root_cause
                analysis["root_causes"] = [root_cause]
            else:
                for field in (
                    "root_causes",
                    "root_cause",
                    "root_cause_detail",
                    "root_cause_reason",
                    "root_cause_note",
                    "confidence",
                ):
                    analysis.pop(field, None)
        for field in (
            "root_cause_detail",
            "root_cause_note",
            "solution",
            "solution_note",
        ):
            if field not in patch:
                continue
            value = str(patch.get(field) or "").strip()
            if value:
                analysis[field] = value
            else:
                analysis.pop(field, None)
                if field == "solution":
                    analysis.pop("solution_note", None)
        if "category_taxonomy" in patch:
            taxonomy = normalize_category_taxonomy(patch.get("category_taxonomy"))
            if taxonomy:
                analysis["category_taxonomy"] = taxonomy
            else:
                analysis.pop("category_taxonomy", None)
        analysis.pop("error", None)
        analysis.pop("confidence", None)
        analysis["source"] = "human"
        meaningful = {
            key: value
            for key, value in analysis.items()
            if key != "source" and value not in (None, "", [])
        }
        if meaningful:
            metric_analyses[c.metric_name] = analysis
        else:
            metric_analyses.pop(c.metric_name, None)
        if metric_analyses:
            meta["metric_analyses"] = metric_analyses
        else:
            meta.pop("metric_analyses", None)
        _sync_item_analysis_warning(meta)
        item.item_metadata = meta
        target = replace_metric_review_candidate(
            db,
            run=run,
            item=item,
            metric_name=c.metric_name,
            analysis=analysis if meaningful else {},
            actor_user_id=(
                principal.user.id if principal.auth_type != "none" else None
            ),
            actor_source="human",
        )
        db.commit()
        if target is None:
            return _serialize_corrections_with_history(db, [c])[0]
        return _serialize_corrections_with_history(db, [target])[0]

    result = apply_root_cause_change(
        db,
        run=run,
        item=item,
        actor_user_id=principal.user.id if principal.auth_type != "none" else None,
        actor_source="human",
        human_patch=patch,
    )
    db.commit()
    target = (
        result.candidate
        or (
            db.query(ReviewCorrection)
            .filter(
                ReviewCorrection.run_id == c.run_id,
                ReviewCorrection.item_id == c.item_id,
                ReviewCorrection.is_active.is_(True),
            )
            .first()
        )
        or c
    )
    return _serialize_corrections_with_history(db, [target])[0]


@router.post("/api/corrections/{correction_id}/approve")
def approve_correction(
    correction_id: int,
    request: Dict[str, Any],
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> Dict[str, Any]:
    """Approve a correction for use as analysis-rule evidence."""
    correction = (
        db.query(ReviewCorrection).filter(ReviewCorrection.id == correction_id).first()
    )
    if not correction:
        raise HTTPException(status_code=404, detail="Correction not found")
    run = Run.active(db).filter(Run.id == correction.run_id).first()
    if not run or not can_review_run(db, principal, run):
        raise HTTPException(status_code=403, detail="Access denied")

    target = correction
    if not correction.is_active:
        metric_scope = (
            ReviewCorrection.metric_name.is_(None)
            if correction.metric_name is None
            else ReviewCorrection.metric_name == correction.metric_name
        )
        active_candidate = (
            db.query(ReviewCorrection)
            .filter(
                ReviewCorrection.run_id == correction.run_id,
                ReviewCorrection.item_id == correction.item_id,
                metric_scope,
                ReviewCorrection.is_active.is_(True),
            )
            .first()
        )
        if active_candidate:
            target = active_candidate

    _approve_candidate(
        db,
        correction=target,
        reviewer_id=principal.user.id if principal.auth_type != "none" else None,
        comment=(request.get("comment") or "").strip(),
        reviewed_at=utc_now_naive(),
    )

    db.commit()
    return _serialize_corrections_with_history(db, [target])[0]


@router.post("/api/corrections/approve-metric-analysis")
def approve_metric_analysis(
    request: Dict[str, Any],
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> Dict[str, Any]:
    """Materialize and approve one saved per-metric analysis."""
    run_id = str(request.get("run_id") or "").strip()
    item_id = str(request.get("item_id") or "").strip()
    metric_name = str(request.get("metric_name") or "").strip()
    if not run_id or not item_id or not metric_name:
        raise HTTPException(
            status_code=400,
            detail="run_id, item_id, and metric_name required",
        )

    run = Run.active(db).filter(Run.id == run_id).first()
    if not run or not can_review_run(db, principal, run):
        raise HTTPException(status_code=403, detail="Access denied")
    item = (
        db.query(RunItem)
        .filter(RunItem.run_id == run.id, RunItem.item_id == item_id)
        .first()
    )
    if not item:
        raise HTTPException(status_code=404, detail="Run item not found")

    metric_analyses = (
        item.item_metadata.get("metric_analyses", {})
        if isinstance(item.item_metadata, dict)
        else {}
    )
    analysis = metric_analyses.get(metric_name)
    if (
        not isinstance(analysis, dict)
        or not str(analysis.get("root_cause") or "").strip()
    ):
        raise HTTPException(status_code=404, detail="Metric analysis not found")

    candidate = (
        db.query(ReviewCorrection)
        .filter(
            ReviewCorrection.run_id == run.id,
            ReviewCorrection.item_id == item.item_id,
            ReviewCorrection.metric_name == metric_name,
            ReviewCorrection.is_active.is_(True),
        )
        .order_by(ReviewCorrection.created_at.desc(), ReviewCorrection.id.desc())
        .first()
    )
    if candidate is None:
        source = str(analysis.get("source") or "ai").lower()
        candidate = replace_metric_review_candidate(
            db,
            run=run,
            item=item,
            metric_name=metric_name,
            analysis=analysis,
            actor_user_id=(
                principal.user.id if principal.auth_type != "none" else None
            ),
            actor_source="human" if source == "human" else "ai",
        )
        if candidate is None:
            raise HTTPException(
                status_code=409, detail="Metric analysis is not reviewable"
            )
        db.flush()

    _approve_candidate(
        db,
        correction=candidate,
        reviewer_id=principal.user.id if principal.auth_type != "none" else None,
        comment=(request.get("comment") or "").strip(),
        reviewed_at=utc_now_naive(),
    )
    db.commit()
    return _serialize_corrections_with_history(db, [candidate])[0]


@router.post("/api/corrections/{correction_id}/reject")
def reject_correction(
    correction_id: int,
    request: Dict[str, Any],
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> Dict[str, Any]:
    """Reject a correction so it is excluded from analysis-rule evidence."""
    c = db.query(ReviewCorrection).filter(ReviewCorrection.id == correction_id).first()
    if not c:
        raise HTTPException(status_code=404, detail="Correction not found")
    _require_active_candidate(c)
    run = Run.active(db).filter(Run.id == c.run_id).first()
    if not run or not can_review_run(db, principal, run):
        raise HTTPException(status_code=403, detail="Access denied")

    _reject_candidate(
        db,
        correction=c,
        reviewer_id=principal.user.id if principal.auth_type != "none" else None,
        comment=(request.get("comment") or "").strip(),
        reviewed_at=utc_now_naive(),
    )

    db.commit()
    return _serialize_corrections_with_history(db, [c])[0]


@router.post("/api/corrections/{correction_id}/reset")
def reset_correction(
    correction_id: int,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> Dict[str, Any]:
    """Reset a correction back to pending status."""
    c = db.query(ReviewCorrection).filter(ReviewCorrection.id == correction_id).first()
    if not c:
        raise HTTPException(status_code=404, detail="Correction not found")
    _require_active_candidate(c)
    run = Run.active(db).filter(Run.id == c.run_id).first()
    if not run or not can_review_run(db, principal, run):
        raise HTTPException(status_code=403, detail="Access denied")

    c.status = CorrectionStatus.PENDING
    c.reviewed_by_user_id = None
    c.reviewed_at = None
    c.review_comment = ""

    db.commit()
    return _serialize_corrections_with_history(db, [c])[0]


class BulkActionRequest(BaseModel):
    ids: List[int]
    action: str  # approve | reject | reset | delete
    comment: str = ""


@router.post("/api/corrections/bulk")
def bulk_correction_action(
    request: BulkActionRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> Dict[str, Any]:
    """Perform a bulk action on multiple corrections."""
    if not request.ids:
        raise HTTPException(status_code=400, detail="No correction IDs provided")

    corrections = (
        db.query(ReviewCorrection)
        .filter(
            ReviewCorrection.id.in_(request.ids),
            ReviewCorrection.is_active.is_(True),
        )
        .all()
    )

    if not corrections:
        raise HTTPException(status_code=404, detail="No corrections found")

    runs_by_id = {
        run.id: run
        for run in Run.active(db)
        .filter(Run.id.in_({c.run_id for c in corrections}))
        .all()
    }
    for correction in corrections:
        run = runs_by_id.get(correction.run_id)
        if not run or not can_review_run(db, principal, run):
            raise HTTPException(status_code=403, detail="Access denied")

    now = utc_now_naive()
    reviewer_id = principal.user.id if principal.auth_type != "none" else None
    affected = 0

    for c in corrections:
        if request.action == "approve":
            _approve_candidate(
                db,
                correction=c,
                reviewer_id=reviewer_id,
                comment=request.comment,
                reviewed_at=now,
            )
            affected += 1
        elif request.action == "reject":
            _reject_candidate(
                db,
                correction=c,
                reviewer_id=reviewer_id,
                comment=request.comment,
                reviewed_at=now,
            )
            affected += 1
        elif request.action == "reset":
            c.status = CorrectionStatus.PENDING
            c.reviewed_by_user_id = None
            c.reviewed_at = None
            c.review_comment = ""
            affected += 1
        elif request.action == "delete":
            _delete_active_candidate(
                db,
                correction=c,
                reviewer_id=reviewer_id,
                comment=request.comment
                or "Rejected automatically after deletion request.",
                reviewed_at=now,
            )
            affected += 1

    db.commit()
    return {"ok": True, "affected": affected}


@router.delete("/api/corrections/{correction_id}")
def delete_correction(
    correction_id: int,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> Dict[str, Any]:
    """Delete a correction from reviews and retain it as rejected history."""
    c = db.query(ReviewCorrection).filter(ReviewCorrection.id == correction_id).first()
    if not c:
        raise HTTPException(status_code=404, detail="Correction not found")
    run = Run.active(db).filter(Run.id == c.run_id).first()
    if not run or not can_review_run(db, principal, run):
        raise HTTPException(status_code=403, detail="Access denied")
    _delete_active_candidate(
        db,
        correction=c,
        reviewer_id=principal.user.id if principal.auth_type != "none" else None,
        comment="Rejected automatically after deletion request.",
        reviewed_at=utc_now_naive(),
    )
    db.commit()
    return {
        "ok": True,
        "deleted_id": correction_id,
        "status": CorrectionStatus.REJECTED.value,
    }
