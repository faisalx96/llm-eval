from __future__ import annotations

import ast
import asyncio
import copy
import hashlib
import inspect
import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional, Union
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from anyio import CapacityLimiter, to_thread
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from qym_platform.auth import Principal, require_ui_principal
from qym_platform.datetime_utils import to_api_timestamp, utc_now_naive
from qym_platform.db.models import (
    AnalyzerDocument,
    AnalysisRuleVersionStatus,
    CorrectionStatus,
    Project,
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
    AnalysisResult,
    analyze_items_batch,
    analyze_single_item,
    build_analysis_prompt,
    build_client,
    get_all_approved_examples,
    infer_analysis_rules,
    normalize_analysis_rules,
    update_analysis_rules,
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
from qym_platform.settings import PlatformSettings
from sqlalchemy import String, and_, cast, func, or_, tuple_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, object_session

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


def _rule_status(version: ProjectAnalysisRuleVersion) -> str:
    return (
        version.status.value
        if hasattr(version.status, "value")
        else str(version.status or "")
    )


def _rule_content_hash(rules: list[dict[str, str]]) -> str:
    payload = json.dumps(
        rules, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _rules_with_stable_ids(
    value: Any,
    *,
    existing: list[dict[str, str]] | None = None,
) -> list[dict[str, str]]:
    normalized = normalize_analysis_rules(value)
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
    result: list[dict[str, str]] = []
    for index, rule in enumerate(normalized):
        raw = value[index] if isinstance(value, list) and index < len(value) else {}
        requested_id = (
            str(raw.get("id") or "").strip() if isinstance(raw, dict) else ""
        )
        prior = existing_by_id.get(requested_id) or existing_by_title.get(
            rule["title"].casefold()
        )
        result.append(
            {
                "id": requested_id
                or str((prior or {}).get("id") or "")
                or str(uuid4()),
                "title": rule["title"],
                "instruction": rule["instruction"],
            }
        )
    return result


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
    rules: list[dict[str, str]],
    source: str,
    actor_user_id: str | None,
    force_new: bool = False,
    parent: ProjectAnalysisRuleVersion | None = None,
    description: str = "",
) -> ProjectAnalysisRuleVersion:
    """Create a mutable draft derived from another rule version."""
    active = parent or _active_analysis_rule_version(db, project_id)
    normalized = _rules_with_stable_ids(rules, existing=active.rules if active else None)
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
    rules: list[dict[str, str]],
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
    rules: list[dict[str, str]] | None,
) -> tuple[dict[str, dict[str, str]], list[str]]:
    mapped: dict[str, dict[str, str]] = {}
    order: list[str] = []
    for rule in rules or []:
        if not isinstance(rule, dict):
            continue
        key = str(rule.get("id") or "").strip() or (
            "title:" + str(rule.get("title") or "").strip().casefold()
        )
        if not key or key in mapped:
            continue
        normalized = {
            "id": str(rule.get("id") or "").strip(),
            "title": str(rule.get("title") or "").strip(),
            "instruction": str(rule.get("instruction") or "").strip(),
        }
        mapped[key] = normalized
        order.append(key)
    return mapped, order


def _rule_equal(
    left: dict[str, str] | None, right: dict[str, str] | None
) -> bool:
    if left is None or right is None:
        return left is right
    return (
        str(left.get("title") or "").strip()
        == str(right.get("title") or "").strip()
        and str(left.get("instruction") or "").strip()
        == str(right.get("instruction") or "").strip()
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
    merged: dict[str, dict[str, str]] = {}
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


class AnalyzerRuleConfig(BaseModel):
    """One project rule applied during root-cause analysis."""

    id: Optional[str] = Field(default=None, max_length=36)
    title: str = Field(..., min_length=1, max_length=120)
    instruction: str = Field(..., min_length=1, max_length=4000)


class AnalyzerDocumentSelection(BaseModel):
    """Project-level inclusion state for one analyzer document."""

    selected: bool


class CategoryTaxonomyConfig(BaseModel):
    """Definition and selection criteria for one root-cause category."""

    description: str = Field(default="", max_length=2_000)
    when_to_use: str = Field(default="", max_length=2_000)


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
    solution_categories: Optional[List[str]] = Field(default=None, max_length=100)
    include_fields: Optional[Dict[str, bool]] = None
    field_mapping: Optional[Dict[str, MappingSource]] = (
        None  # e.g. {"input": "input.question", "expected": "expected"}
    )
    metadata_fields: Optional[List[str]] = Field(default=None, max_length=100)
    temperature: Optional[float] = Field(default=None, ge=0.0, le=2.0)
    max_tokens: Optional[int] = Field(default=None, ge=1, le=32_768)


class AnalyzeRequest(BaseModel):
    """Filter criteria for which items to analyze."""

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
    connection_id: Optional[str] = (
        None  # which project LLM connection to use; default if omitted
    )


class AggregateAnalysisRequest(BaseModel):
    """Re-run canonicalization over already-saved AI diagnoses."""

    metric: Optional[str] = None
    connection_id: Optional[str] = None


class PreviewRequest(BaseModel):
    """Request to preview the LLM messages for an item."""

    item_id: str
    metric: Optional[str] = None
    config: Optional[PlaygroundConfig] = None
    connection_id: Optional[str] = None


class TestRequest(BaseModel):
    """Request to test analysis on 1-3 items without saving."""

    item_ids: List[str] = Field(..., min_length=1, max_length=3)
    metric: Optional[str] = None
    config: Optional[PlaygroundConfig] = None
    connection_id: Optional[str] = None


class AnalysisContextUpdate(BaseModel):
    """Project-scoped analysis rules edited in the analyzer."""

    analysis_rules: List[AnalyzerRuleConfig] = Field(default_factory=list)
    create_new_version: bool = False
    rule_version_id: Optional[str] = None
    from_version: Optional[str] = None


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
    """Inputs for the project rule-writer agent."""

    include_documents: bool = True
    include_examples: bool = True
    mode: Literal["generate", "update"] = "generate"
    rule_version_id: Optional[str] = None
    connection_id: Optional[str] = None


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


def _analysis_config_with_category_catalog(
    db: Session,
    run: Run,
    items: List[RunItem],
    analyzer_config: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Add the task category catalog without overriding explicit playground edits."""
    config = dict(analyzer_config or {})
    categories, details = _collect_task_root_cause_catalog(db, run, items)
    taxonomy = _collect_task_root_cause_taxonomy(db, run, items)
    if "root_cause_categories" not in config:
        config["root_cause_categories"] = _ordered_unique(
            categories + list(taxonomy.keys())
        )
    if "category_details_map" not in config:
        config["category_details_map"] = details
    config["category_taxonomy"] = merge_category_taxonomies(
        taxonomy, config.get("category_taxonomy")
    )
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
        targets = targets[: request.limit]
    return targets


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
        db, run, all_items, analyzer_config
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
        db, run, all_items, analyzer_config
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
            db, run, all_items, analyzer_config
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


def _analysis_document_payload(document: AnalyzerDocument) -> Dict[str, Any]:
    return {
        "id": document.id,
        "name": document.name,
        "content": document.content,
        "characters": document.characters,
        "truncated": document.truncated,
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
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> Dict[str, Any]:
    """Extract and save a document to the run's project."""
    run = _document_library_run(db, principal, run_id, modify=True)

    try:
        raw = await file.read(MAX_REFERENCE_UPLOAD_BYTES + 1)
    finally:
        await file.close()

    if len(raw) > MAX_REFERENCE_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413, detail="The document exceeds the 10 MB upload limit."
        )

    try:
        document = await to_thread.run_sync(
            extract_document_text,
            file.filename or "document",
            raw,
            limiter=_DOCUMENT_EXTRACTION_LIMITER,
        )
    except UnsupportedDocumentError as exc:
        raise HTTPException(status_code=415, detail=str(exc)) from exc
    except DocumentExtractionError as exc:
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
    return {"document": _analysis_document_payload(stored)}


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
    approved_examples = get_all_approved_examples(
        db,
        task=run.task,
        project_id=run.project_id,
    )
    corrections = approved_examples if request.include_examples else []
    if not selected_documents and not corrections:
        action = "updated" if request.mode == "update" else "generated"
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
                "approved_examples_available": len(approved_examples),
                "documents_selected": request.include_documents,
                "approved_examples_selected": request.include_examples,
            },
        )
    llm_config = _get_llm_config(db, run.project_id, request.connection_id)
    target_version = (
        _resolve_analysis_rule_version(
            db, project.id, request.rule_version_id
        )
        if request.rule_version_id
        else _active_analysis_rule_version(db, project.id)
    )
    existing_rules = list(target_version.rules or []) if target_version else []

    try:
        inference_args = {
            "client": build_client(llm_config),
            "model": llm_config.get("llm_model", "gpt-4o-mini"),
            "reference_documents": [
                {"name": document.name, "content": document.content}
                for document in selected_documents
            ],
            "corrections": corrections,
        }
        if request.mode == "update":
            rules = await update_analysis_rules(
                existing_rules=existing_rules,
                **inference_args,
            )
        else:
            rules = await infer_analysis_rules(**inference_args)
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

    normalized_rules = _rules_with_stable_ids(rules, existing=existing_rules)
    if (
        target_version is not None
        and _rule_status(target_version) == AnalysisRuleVersionStatus.DRAFT.value
    ):
        version = target_version
        version.rules = normalized_rules
        version.source = (
            "inference_update" if request.mode == "update" else "inferred"
        )
        version.updated_at = utc_now_naive()
    else:
        version = _create_analysis_rule_version(
            db,
            project_id=project.id,
            rules=normalized_rules,
            source=(
                "inference_update" if request.mode == "update" else "inferred"
            ),
            actor_user_id=principal.user.id,
            force_new=True,
            parent=target_version,
        )
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
        "mode": request.mode,
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

    def keyed(version: ProjectAnalysisRuleVersion) -> dict[str, dict[str, str]]:
        result: dict[str, dict[str, str]] = {}
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
        db, run, [item], analyzer_config
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

    return {"messages": messages, "metric_name": preview_metric}


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
        db, run, items, analyzer_config
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
    correction_count = len(approved_corrections)
    enabled_document_count = (
        db.query(AnalyzerDocument)
        .filter(
            AnalyzerDocument.project_id == run.project_id,
            AnalyzerDocument.enabled.is_(True),
        )
        .count()
    )

    all_categories, category_details_map = _collect_task_root_cause_catalog(
        db, run, items
    )
    category_taxonomy = _collect_task_root_cause_taxonomy(db, run, items)
    correction_runs = _load_runs_map(
        db, {correction.run_id for correction in approved_corrections}
    )
    category_examples: Dict[str, List[Dict[str, Any]]] = {
        category: [] for category in all_categories
    }
    for correction in approved_corrections:
        categories = normalize_root_causes(
            correction.human_root_causes
            or correction.human_root_cause
            or correction.ai_root_causes
            or correction.ai_root_cause
        )
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
        "can_restore_analysis_rules": principal.user.role == UserRole.ADMIN,
        "total_items": total,
        "items_with_root_cause": with_rc,
        "items_ai_assigned": ai_assigned,
        "items_without_root_cause": total - with_rc,
        "correction_bank_size": correction_count,
        "approved_example_count": correction_count,
        "enabled_document_count": enabled_document_count,
        "default_system_prompt": DEFAULT_SYSTEM_PROMPT,
        "default_categories": all_categories,
        "max_root_cause_categories": DEFAULT_MAX_ROOT_CAUSE_CATEGORIES,
        "default_solution_categories": SOLUTION_CATEGORIES,
        "category_details_map": category_details_map,
        "category_taxonomy": category_taxonomy,
        "category_example_counts": {
            category: len(examples)
            for category, examples in category_examples.items()
        },
        "category_examples": category_examples,
        # Keep flat list for backwards compatibility
        "existing_details": _ordered_unique(
            [d for dets in category_details_map.values() for d in dets]
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


@router.post("/api/projects/{project_slug}/analysis-documents")
async def upload_project_analysis_document(
    project_slug: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> Dict[str, Any]:
    return await upload_analysis_document(
        run_id=_project_analysis_scope_key(project_slug),
        file=file,
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
        return meta

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
        return build_item_metadata(meta, {})

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
    return synced


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
                patch.get("root_causes"),
                max_categories=DEFAULT_MAX_ROOT_CAUSE_CATEGORIES,
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
