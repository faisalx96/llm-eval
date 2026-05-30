from __future__ import annotations

import csv
import io
import json
import re
from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, Iterable, Optional
from uuid import uuid4

from fastapi import APIRouter, Body, Depends, File, Form, Header, HTTPException, Query, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import String, cast, func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from qym_platform.auth import Principal, require_api_key_scope, require_ui_principal
from qym_platform.datetime_utils import to_api_timestamp, utc_now_naive
from qym_platform.db.models import (
    ApiKey,
    Dataset,
    DatasetAlias,
    DatasetItem,
    DatasetItemRevision,
    DatasetVersion,
    DatasetVersionChange,
    DatasetVersionStatus,
    Project,
    Run,
    RunItem,
    RunItemScore,
    User,
)
from qym_platform.deps import get_db
from qym_platform.item_identity import build_identity_fingerprint
from qym_platform.permissions import has_project_access
from qym_platform.security import api_key_prefix, verify_api_key


router = APIRouter()


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (value or "").strip().lower()).strip("-")
    return slug or "dataset"


def _labels(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    if isinstance(value, list):
        return [str(part).strip() for part in value if str(part).strip()]
    return []


def _json_safe(value: Any) -> Any:
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            return None
        return value
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_safe(v) for v in value]
    return value


def _principal_from_bearer(db: Session, authorization: Optional[str]) -> Optional[Principal]:
    if not authorization:
        return None
    parts = authorization.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    token = parts[1].strip()
    if not token:
        return None
    row = (
        db.query(ApiKey)
        .filter(ApiKey.prefix == api_key_prefix(token))
        .filter(ApiKey.revoked_at.is_(None))
        .first()
    )
    if not row or not verify_api_key(token, row.key_hash):
        raise HTTPException(status_code=401, detail="Invalid API key")
    user = db.query(User).filter(User.id == row.user_id).first()
    if not user or not user.is_active:
        raise HTTPException(status_code=403, detail="User disabled")
    scopes = tuple(str(scope).strip() for scope in (row.scopes or []) if str(scope).strip())
    return Principal(user=user, auth_type="api_key", scopes=scopes, project_id=row.project_id)


def dataset_principal(
    request: Request,
    db: Session = Depends(get_db),
    authorization: Optional[str] = Header(default=None),
    x_user_email: Optional[str] = Header(default=None, alias="X-User-Email"),
    x_email: Optional[str] = Header(default=None, alias="X-Email"),
    x_admin_bootstrap: Optional[str] = Header(default=None, alias="X-Admin-Bootstrap"),
) -> Principal:
    api_principal = _principal_from_bearer(db, authorization)
    if api_principal:
        return api_principal
    return require_ui_principal(
        request=request,
        db=db,
        x_user_email=x_user_email,
        x_email=x_email,
        x_admin_bootstrap=x_admin_bootstrap,
    )


def _require_scope(principal: Principal, scope: str) -> None:
    if principal.auth_type == "api_key":
        require_api_key_scope(principal, scope)


def _project_for_request(db: Session, principal: Principal, project_slug: Optional[str]) -> Project:
    if principal.project_id:
        project = db.query(Project).filter(Project.id == principal.project_id).first()
        if not project:
            raise HTTPException(status_code=403, detail="API key project not found")
        return project
    if project_slug:
        project = db.query(Project).filter(Project.slug == project_slug).first()
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        if not has_project_access(db, principal, project.id):
            raise HTTPException(status_code=403, detail="Access denied")
        return project
    project = db.query(Project).order_by(Project.name).first()
    if not project:
        raise HTTPException(status_code=404, detail="No project found")
    if not has_project_access(db, principal, project.id):
        raise HTTPException(status_code=403, detail="Access denied")
    return project


def _get_dataset(db: Session, project: Project, ref: str) -> Dataset:
    dataset = (
        db.query(Dataset)
        .filter(
            Dataset.project_id == project.id,
            Dataset.deleted_at.is_(None),
            (Dataset.id == ref) | (Dataset.slug == ref) | (Dataset.name == ref),
        )
        .first()
    )
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")
    return dataset


def _resolve_version(db: Session, dataset: Dataset, ref: Optional[str]) -> DatasetVersion:
    clean = (ref or "production").strip() or "production"
    version = (
        db.query(DatasetVersion)
        .filter(DatasetVersion.dataset_id == dataset.id, DatasetVersion.version == clean)
        .first()
    )
    if version:
        return version
    alias = (
        db.query(DatasetAlias)
        .filter(DatasetAlias.dataset_id == dataset.id, DatasetAlias.alias == clean)
        .first()
    )
    if alias:
        version = db.query(DatasetVersion).filter(DatasetVersion.id == alias.dataset_version_id).first()
        if version:
            return version
    if clean == "production":
        version = (
            db.query(DatasetVersion)
            .filter(DatasetVersion.dataset_id == dataset.id, DatasetVersion.status == DatasetVersionStatus.PUBLISHED)
            .order_by(DatasetVersion.published_at.desc().nullslast(), DatasetVersion.created_at.desc())
            .first()
        )
        if version:
            return version
    raise HTTPException(status_code=404, detail=f"Dataset version or alias not found: {clean}")


def _require_draft(version: DatasetVersion) -> None:
    status = version.status.value if hasattr(version.status, "value") else str(version.status)
    if status != DatasetVersionStatus.DRAFT.value:
        raise HTTPException(status_code=409, detail="Only draft dataset versions can be edited")


def _item_payload(item: DatasetItem, *, run_count: Optional[int] = None) -> Dict[str, Any]:
    payload = {
        "id": item.id,
        "item_id": item.item_id,
        "index": item.index,
        "input": item.input,
        "expected_output": item.expected_output,
        "metadata": item.item_metadata or {},
        "labels": item.labels or [],
        "fingerprint": item.fingerprint,
        "created_at": to_api_timestamp(item.created_at),
        "updated_at": to_api_timestamp(item.updated_at),
    }
    if run_count is not None:
        payload["run_count"] = int(run_count)
    return payload


def _version_payload(db: Session, version: DatasetVersion, *, include_aliases: bool = True) -> Dict[str, Any]:
    aliases: list[str] = []
    if include_aliases:
        aliases = [
            row.alias
            for row in db.query(DatasetAlias)
            .filter(DatasetAlias.dataset_version_id == version.id)
            .order_by(DatasetAlias.alias)
            .all()
        ]
    run_count = db.query(Run.id).filter(Run.dataset_version_id == version.id, Run.deleted_at.is_(None)).count()
    return {
        "id": version.id,
        "dataset_id": version.dataset_id,
        "version": version.version,
        "description": version.description,
        "status": version.status.value if hasattr(version.status, "value") else str(version.status),
        "source_type": version.source_type,
        "source_uri": version.source_uri,
        "parent_version_id": version.parent_version_id,
        "base_version_id": version.base_version_id,
        "schema": version.schema or {},
        "labels": version.labels or [],
        "item_count": version.item_count,
        "content_hash": version.content_hash,
        "created_by_user_id": version.created_by_user_id,
        "published_by_user_id": version.published_by_user_id,
        "created_at": to_api_timestamp(version.created_at),
        "updated_at": to_api_timestamp(version.updated_at),
        "published_at": to_api_timestamp(version.published_at),
        "is_default": bool(version.is_default),
        "aliases": aliases,
        "run_count": run_count,
    }


def _dataset_payload(db: Session, dataset: Dataset) -> Dict[str, Any]:
    aliases = {
        row.alias: row.dataset_version_id
        for row in db.query(DatasetAlias).filter(DatasetAlias.dataset_id == dataset.id).all()
    }
    production = None
    if aliases.get("production"):
        production = db.query(DatasetVersion).filter(DatasetVersion.id == aliases["production"]).first()
    latest = (
        db.query(DatasetVersion)
        .filter(DatasetVersion.dataset_id == dataset.id)
        .order_by(DatasetVersion.created_at.desc())
        .first()
    )
    run_count = db.query(Run.id).filter(Run.dataset_id == dataset.id, Run.deleted_at.is_(None)).count()
    return {
        "id": dataset.id,
        "project_id": dataset.project_id,
        "name": dataset.name,
        "slug": dataset.slug,
        "description": dataset.description,
        "tags": dataset.tags or [],
        "created_by_user_id": dataset.created_by_user_id,
        "created_at": to_api_timestamp(dataset.created_at),
        "updated_at": to_api_timestamp(dataset.updated_at),
        "production_version": _version_payload(db, production, include_aliases=False) if production else None,
        "latest_version": _version_payload(db, latest, include_aliases=False) if latest else None,
        "run_count": run_count,
    }


def _record_change(db: Session, version: DatasetVersion, summary: Dict[str, Any]) -> None:
    db.add(
        DatasetVersionChange(
            dataset_version_id=version.id,
            parent_version_id=version.parent_version_id,
            change_summary=summary,
            created_at=utc_now_naive(),
        )
    )


def _record_item_revision(
    db: Session,
    version: DatasetVersion,
    item: Optional[DatasetItem],
    *,
    change_type: str,
    before: Optional[Dict[str, Any]],
    after: Optional[Dict[str, Any]],
    actor_user_id: str,
) -> None:
    count = (
        db.query(func.count(DatasetItemRevision.id))
        .filter(DatasetItemRevision.dataset_version_id == version.id)
        .scalar()
        or 0
    )
    db.add(
        DatasetItemRevision(
            dataset_item_id=item.id if item else None,
            dataset_version_id=version.id,
            revision_number=int(count) + 1,
            change_type=change_type,
            before=before or {},
            after=after or {},
            actor_user_id=actor_user_id,
            created_at=utc_now_naive(),
        )
    )


def _content_hash(items: Iterable[DatasetItem]) -> str:
    import hashlib

    payload = [
        {
            "item_id": item.item_id,
            "input": item.input,
            "expected_output": item.expected_output,
            "metadata": item.item_metadata or {},
            "labels": item.labels or [],
            "fingerprint": item.fingerprint,
        }
        for item in sorted(items, key=lambda row: (row.index, row.item_id))
    ]
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _parse_cell(raw: Any) -> Any:
    if raw is None:
        return ""
    text = str(raw)
    stripped = text.lstrip()
    if stripped[:1] in {"{", "["}:
        return json.loads(stripped)
    return text


def _combine_columns(row: Dict[str, Any], cols: list[str]) -> Any:
    """One column -> the raw (parsed) cell value; multiple columns -> a JSON object
    keyed by column name. Returns None when no columns are given."""
    if not cols:
        return None
    if len(cols) == 1:
        return _parse_cell(row.get(cols[0], ""))
    return {col: _parse_cell(row.get(col, "")) for col in cols}


def _items_from_csv(
    raw: bytes,
    *,
    input_cols: list[str],
    expected_cols: list[str],
    id_col: Optional[str],
    metadata_cols: list[str],
    label_cols: list[str],
) -> list[Dict[str, Any]]:
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
    fields = list(reader.fieldnames or [])
    if not input_cols:
        raise HTTPException(status_code=400, detail="At least one input column is required")
    for col in [c for c in input_cols + expected_cols + metadata_cols + label_cols if c and c not in fields]:
        raise HTTPException(status_code=400, detail=f"Missing column: {col}")
    items: list[Dict[str, Any]] = []
    for row in reader:
        metadata = {col: _parse_cell(row.get(col, "")) for col in metadata_cols}
        labels: list[str] = []
        for col in label_cols:
            labels.extend(_labels(row.get(col, "")))
        items.append(
            {
                "item_id": str(row.get(id_col, "")).strip() if id_col else "",
                "input": _combine_columns(row, input_cols),
                "expected_output": _combine_columns(row, expected_cols) if expected_cols else None,
                "metadata": metadata,
                "labels": sorted(set(labels)),
            }
        )
    return items


def _items_from_jsonl(raw: bytes) -> list[Dict[str, Any]]:
    items: list[Dict[str, Any]] = []
    for line_no, line in enumerate(raw.decode("utf-8").splitlines(), start=1):
        text = line.strip()
        if not text:
            continue
        try:
            obj = json.loads(text)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail=f"Invalid JSONL at line {line_no}: {exc}") from exc
        if not isinstance(obj, dict):
            raise HTTPException(status_code=400, detail=f"JSONL line {line_no} must be an object")
        items.append(
            {
                "item_id": str(obj.get("item_id") or obj.get("id") or "").strip(),
                "input": obj.get("input"),
                "expected_output": obj.get("expected_output", obj.get("expected")),
                "metadata": obj.get("metadata") or {},
                "labels": _labels(obj.get("labels")),
            }
        )
    return items


def _insert_items(db: Session, version: DatasetVersion, items: list[Dict[str, Any]]) -> None:
    duplicate_counts: dict[str, int] = defaultdict(int)
    seen_ids: set[str] = set()
    for index, source in enumerate(items):
        input_value = _json_safe(source.get("input"))
        expected = _json_safe(source.get("expected_output"))
        metadata = _json_safe(source.get("metadata") or {})
        labels = _labels(source.get("labels"))
        fingerprint = build_identity_fingerprint(input_value=input_value, expected_value=expected, metadata=metadata)
        item_id = str(source.get("item_id") or "").strip()
        if not item_id:
            duplicate_counts[fingerprint] += 1
            item_id = f"ds_{fingerprint}__{duplicate_counts[fingerprint]:04d}"
        if item_id in seen_ids:
            raise HTTPException(status_code=409, detail=f"Duplicate item_id: {item_id}")
        seen_ids.add(item_id)
        db.add(
            DatasetItem(
                dataset_version_id=version.id,
                item_id=item_id,
                index=index,
                input=input_value,
                expected_output=expected,
                item_metadata=metadata,
                labels=labels,
                fingerprint=fingerprint,
                created_at=utc_now_naive(),
                updated_at=utc_now_naive(),
            )
        )
    version.item_count = len(items)


class CreateDatasetRequest(BaseModel):
    name: str
    slug: Optional[str] = None
    description: str = ""
    tags: list[str] = Field(default_factory=list)
    project_slug: Optional[str] = None


class UpdateDatasetRequest(BaseModel):
    name: Optional[str] = None
    slug: Optional[str] = None
    description: Optional[str] = None
    tags: Optional[list[str]] = None


class CreateVersionRequest(BaseModel):
    version: Optional[str] = None
    description: str = ""
    labels: list[str] = Field(default_factory=list)
    from_version: Optional[str] = None
    from_alias: Optional[str] = None


class PublishVersionRequest(BaseModel):
    set_alias: Optional[str] = None


class SetAliasRequest(BaseModel):
    version: str


class UpsertItemRequest(BaseModel):
    item_id: Optional[str] = None
    input: Any
    expected_output: Any = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    labels: list[str] = Field(default_factory=list)


class BulkUpsertEntry(BaseModel):
    item_id: Optional[str] = None
    op: Optional[str] = None
    input: Any = None
    expected_output: Any = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    labels: list[str] = Field(default_factory=list)


class BulkItemsRequest(BaseModel):
    upserts: list[BulkUpsertEntry] = Field(default_factory=list)
    deletes: list[str] = Field(default_factory=list)


@router.get("/v1/datasets")
def list_datasets(
    project_slug: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
    principal: Principal = Depends(dataset_principal),
) -> Dict[str, Any]:
    _require_scope(principal, "datasets:read")
    project = _project_for_request(db, principal, project_slug)
    datasets = (
        db.query(Dataset)
        .filter(Dataset.project_id == project.id, Dataset.deleted_at.is_(None))
        .order_by(Dataset.name)
        .all()
    )
    return {"project": {"id": project.id, "slug": project.slug, "name": project.name}, "datasets": [_dataset_payload(db, ds) for ds in datasets]}


@router.post("/v1/datasets")
def create_dataset(
    req: CreateDatasetRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(dataset_principal),
) -> Dict[str, Any]:
    _require_scope(principal, "datasets:write")
    project = _project_for_request(db, principal, req.project_slug)
    dataset = Dataset(
        id=str(uuid4()),
        project_id=project.id,
        name=req.name.strip(),
        slug=_slugify(req.slug or req.name),
        description=req.description,
        tags=_labels(req.tags),
        created_by_user_id=principal.user.id,
        created_at=utc_now_naive(),
        updated_at=utc_now_naive(),
    )
    db.add(dataset)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Dataset slug already exists in this project") from exc
    return {"dataset": _dataset_payload(db, dataset)}


@router.get("/v1/datasets/{dataset_ref}")
def get_dataset(
    dataset_ref: str,
    project_slug: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
    principal: Principal = Depends(dataset_principal),
) -> Dict[str, Any]:
    _require_scope(principal, "datasets:read")
    project = _project_for_request(db, principal, project_slug)
    dataset = _get_dataset(db, project, dataset_ref)
    return {"dataset": _dataset_payload(db, dataset)}


@router.patch("/v1/datasets/{dataset_ref}")
def update_dataset(
    dataset_ref: str,
    req: UpdateDatasetRequest,
    project_slug: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
    principal: Principal = Depends(dataset_principal),
) -> Dict[str, Any]:
    _require_scope(principal, "datasets:write")
    project = _project_for_request(db, principal, project_slug)
    dataset = _get_dataset(db, project, dataset_ref)
    if req.name is not None:
        dataset.name = req.name.strip()
    if req.slug is not None:
        dataset.slug = _slugify(req.slug)
    if req.description is not None:
        dataset.description = req.description
    if req.tags is not None:
        dataset.tags = _labels(req.tags)
    dataset.updated_at = utc_now_naive()
    db.commit()
    return {"dataset": _dataset_payload(db, dataset)}


@router.delete("/v1/datasets/{dataset_ref}")
def delete_dataset(
    dataset_ref: str,
    project_slug: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
    principal: Principal = Depends(dataset_principal),
) -> Dict[str, Any]:
    _require_scope(principal, "datasets:delete")
    project = _project_for_request(db, principal, project_slug)
    dataset = _get_dataset(db, project, dataset_ref)
    dataset.deleted_at = utc_now_naive()
    db.commit()
    return {"ok": True}


@router.get("/v1/datasets/{dataset_ref}/versions")
def list_versions(
    dataset_ref: str,
    project_slug: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
    principal: Principal = Depends(dataset_principal),
) -> Dict[str, Any]:
    _require_scope(principal, "datasets:read")
    project = _project_for_request(db, principal, project_slug)
    dataset = _get_dataset(db, project, dataset_ref)
    versions = (
        db.query(DatasetVersion)
        .filter(DatasetVersion.dataset_id == dataset.id)
        .order_by(DatasetVersion.created_at.desc())
        .all()
    )
    return {"dataset": _dataset_payload(db, dataset), "versions": [_version_payload(db, version) for version in versions]}


@router.get("/v1/datasets/{dataset_ref}/runs")
def list_dataset_runs(
    dataset_ref: str,
    project_slug: Optional[str] = Query(default=None),
    version: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    principal: Principal = Depends(dataset_principal),
) -> Dict[str, Any]:
    _require_scope(principal, "datasets:read")
    project = _project_for_request(db, principal, project_slug)
    dataset = _get_dataset(db, project, dataset_ref)

    query = db.query(Run).filter(Run.deleted_at.is_(None), Run.dataset_id == dataset.id)
    if version:
        target = _resolve_version(db, dataset, version)
        query = query.filter(Run.dataset_version_id == target.id)

    total = query.count()
    runs = (
        query.order_by(Run.created_at.desc())
        .limit(limit)
        .offset(offset)
        .all()
    )

    # Map version ids -> labels for the runs on this page.
    version_labels = {
        v.id: v.version
        for v in db.query(DatasetVersion).filter(DatasetVersion.dataset_id == dataset.id).all()
    }
    run_ids = [run.id for run in runs]
    items_counts: Dict[str, int] = {}
    eval_scores: Dict[str, float] = {}
    if run_ids:
        items_counts = dict(
            db.query(RunItem.run_id, func.count(RunItem.id))
            .filter(RunItem.run_id.in_(run_ids))
            .group_by(RunItem.run_id)
            .all()
        )
        eval_scores = dict(
            db.query(RunItemScore.run_id, func.avg(RunItemScore.score_numeric))
            .filter(RunItemScore.run_id.in_(run_ids), RunItemScore.score_numeric.isnot(None))
            .group_by(RunItemScore.run_id)
            .all()
        )

    return {
        "runs": [
            {
                "id": run.id,
                "external_run_id": run.external_run_id,
                "status": run.status.value if hasattr(run.status, "value") else str(run.status),
                "task": run.task,
                "model": run.model,
                "started_at": to_api_timestamp(run.started_at),
                "completed_at": to_api_timestamp(run.ended_at),
                "eval_score": (round(float(eval_scores[run.id]), 4) if eval_scores.get(run.id) is not None else None),
                "version_label": version_labels.get(run.dataset_version_id),
                "items_count": int(items_counts.get(run.id, 0)),
            }
            for run in runs
        ],
        "total": total,
    }


@router.post("/v1/datasets/{dataset_ref}/versions")
def create_version(
    dataset_ref: str,
    req: CreateVersionRequest,
    project_slug: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
    principal: Principal = Depends(dataset_principal),
) -> Dict[str, Any]:
    _require_scope(principal, "datasets:write")
    project = _project_for_request(db, principal, project_slug)
    dataset = _get_dataset(db, project, dataset_ref)
    source_ref = req.from_version or req.from_alias
    parent = _resolve_version(db, dataset, source_ref) if source_ref else None
    version_name = (req.version or "").strip() or _next_version_name(db, dataset)
    version = DatasetVersion(
        id=str(uuid4()),
        dataset_id=dataset.id,
        version=version_name,
        description=req.description,
        status=DatasetVersionStatus.DRAFT,
        source_type="derived" if parent else "api",
        parent_version_id=parent.id if parent else None,
        base_version_id=parent.base_version_id or parent.id if parent else None,
        labels=_labels(req.labels),
        created_by_user_id=principal.user.id,
        created_at=utc_now_naive(),
        updated_at=utc_now_naive(),
    )
    db.add(version)
    db.flush()
    if parent:
        for item in db.query(DatasetItem).filter(DatasetItem.dataset_version_id == parent.id).order_by(DatasetItem.index).all():
            db.add(
                DatasetItem(
                    dataset_version_id=version.id,
                    item_id=item.item_id,
                    index=item.index,
                    input=item.input,
                    expected_output=item.expected_output,
                    item_metadata=dict(item.item_metadata or {}),
                    labels=list(item.labels or []),
                    fingerprint=item.fingerprint,
                    created_at=utc_now_naive(),
                    updated_at=utc_now_naive(),
                )
            )
        version.item_count = parent.item_count
    _record_change(db, version, {"type": "created", "from_version_id": parent.id if parent else None})
    db.commit()
    return {"version": _version_payload(db, version)}


@router.post("/v1/datasets/{dataset_ref}/versions/{version_ref}:publish")
def publish_version(
    dataset_ref: str,
    version_ref: str,
    req: PublishVersionRequest = Body(default_factory=PublishVersionRequest),
    project_slug: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
    principal: Principal = Depends(dataset_principal),
) -> Dict[str, Any]:
    _require_scope(principal, "datasets:write")
    project = _project_for_request(db, principal, project_slug)
    dataset = _get_dataset(db, project, dataset_ref)
    version = _resolve_version(db, dataset, version_ref)
    items = db.query(DatasetItem).filter(DatasetItem.dataset_version_id == version.id).order_by(DatasetItem.index).all()
    if not items:
        raise HTTPException(status_code=400, detail="Cannot publish an empty dataset version")
    seen = set()
    for item in items:
        if item.item_id in seen:
            raise HTTPException(status_code=409, detail=f"Duplicate item_id: {item.item_id}")
        seen.add(item.item_id)
    version.status = DatasetVersionStatus.PUBLISHED
    version.item_count = len(items)
    version.content_hash = _content_hash(items)
    version.published_by_user_id = principal.user.id
    version.published_at = utc_now_naive()
    version.updated_at = utc_now_naive()
    _record_change(db, version, {"type": "published", "item_count": len(items)})
    if req.set_alias:
        _set_alias(db, dataset, req.set_alias, version, principal.user.id)
    db.commit()
    return {"version": _version_payload(db, version)}


def _set_alias(db: Session, dataset: Dataset, alias_name: str, version: DatasetVersion, user_id: str) -> DatasetAlias:
    status = version.status.value if hasattr(version.status, "value") else str(version.status)
    if status != DatasetVersionStatus.PUBLISHED.value:
        raise HTTPException(status_code=409, detail="Aliases can only point to published versions")
    alias = (
        db.query(DatasetAlias)
        .filter(DatasetAlias.dataset_id == dataset.id, DatasetAlias.alias == alias_name)
        .first()
    )
    if not alias:
        alias = DatasetAlias(dataset_id=dataset.id, alias=alias_name, updated_by_user_id=user_id, updated_at=utc_now_naive(), dataset_version_id=version.id)
        db.add(alias)
    else:
        alias.dataset_version_id = version.id
        alias.updated_by_user_id = user_id
        alias.updated_at = utc_now_naive()
    _record_change(db, version, {"type": "alias_set", "alias": alias_name})
    return alias


def _next_version_name(db: Session, dataset: Dataset) -> str:
    highest = 0
    rows = db.query(DatasetVersion.version).filter(DatasetVersion.dataset_id == dataset.id).all()
    for (version_name,) in rows:
        match = re.fullmatch(r"v(\d+)", str(version_name or ""))
        if match:
            highest = max(highest, int(match.group(1)))
    return f"v{highest + 1}"


@router.post("/v1/datasets/{dataset_ref}/aliases/{alias_name}")
def set_alias(
    dataset_ref: str,
    alias_name: str,
    req: SetAliasRequest,
    project_slug: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
    principal: Principal = Depends(dataset_principal),
) -> Dict[str, Any]:
    _require_scope(principal, "datasets:write")
    project = _project_for_request(db, principal, project_slug)
    dataset = _get_dataset(db, project, dataset_ref)
    version = _resolve_version(db, dataset, req.version)
    alias = _set_alias(db, dataset, alias_name, version, principal.user.id)
    db.commit()
    return {"alias": {"dataset_id": dataset.id, "alias": alias.alias, "dataset_version_id": alias.dataset_version_id}}


@router.get("/v1/datasets/{dataset_ref}/lineage")
def get_lineage(
    dataset_ref: str,
    project_slug: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
    principal: Principal = Depends(dataset_principal),
) -> Dict[str, Any]:
    _require_scope(principal, "datasets:read")
    project = _project_for_request(db, principal, project_slug)
    dataset = _get_dataset(db, project, dataset_ref)
    versions = db.query(DatasetVersion).filter(DatasetVersion.dataset_id == dataset.id).order_by(DatasetVersion.created_at).all()
    changes = (
        db.query(DatasetVersionChange)
        .join(DatasetVersion, DatasetVersion.id == DatasetVersionChange.dataset_version_id)
        .filter(DatasetVersion.dataset_id == dataset.id)
        .order_by(DatasetVersionChange.created_at)
        .all()
    )
    return {
        "dataset": _dataset_payload(db, dataset),
        "versions": [_version_payload(db, version) for version in versions],
        "changes": [
            {
                "id": change.id,
                "dataset_version_id": change.dataset_version_id,
                "parent_version_id": change.parent_version_id,
                "change_summary": change.change_summary or {},
                "created_at": to_api_timestamp(change.created_at),
            }
            for change in changes
        ],
    }


@router.get("/v1/datasets/{dataset_ref}/versions/{version_ref}/items")
def list_items(
    dataset_ref: str,
    version_ref: str,
    project_slug: Optional[str] = Query(default=None),
    limit: int = Query(default=100, le=1000),
    offset: int = Query(default=0, ge=0),
    search: Optional[str] = Query(default=None),
    sort: str = Query(default="index_asc"),
    label: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
    principal: Principal = Depends(dataset_principal),
) -> Dict[str, Any]:
    _require_scope(principal, "datasets:read")
    project = _project_for_request(db, principal, project_slug)
    dataset = _get_dataset(db, project, dataset_ref)
    version = _resolve_version(db, dataset, version_ref)
    run_counts = dict(
        db.query(RunItem.dataset_item_pk, func.count(RunItem.id))
        .filter(RunItem.dataset_item_pk.isnot(None))
        .group_by(RunItem.dataset_item_pk)
        .all()
    )

    query = db.query(DatasetItem).filter(DatasetItem.dataset_version_id == version.id)
    if search:
        needle = f"%{search.strip().lower()}%"
        query = query.filter(
            or_(
                func.lower(DatasetItem.item_id).like(needle),
                func.lower(cast(DatasetItem.input, String)).like(needle),
                func.lower(cast(DatasetItem.expected_output, String)).like(needle),
            )
        )
    if label:
        query = query.filter(cast(DatasetItem.labels, String).like(f"%{label}%"))

    sort_key = (sort or "index_asc").lower()
    if sort_key == "index_desc":
        query = query.order_by(DatasetItem.index.desc(), DatasetItem.item_id)
    elif sort_key == "updated_desc":
        query = query.order_by(DatasetItem.updated_at.desc(), DatasetItem.item_id)
    elif sort_key == "item_id":
        query = query.order_by(DatasetItem.item_id)
    else:
        query = query.order_by(DatasetItem.index, DatasetItem.item_id)

    total = query.with_entities(func.count(DatasetItem.id)).order_by(None).scalar() or 0
    items = query.offset(offset).limit(limit).all()
    return {
        "dataset": _dataset_payload(db, dataset),
        "version": _version_payload(db, version),
        "items": [_item_payload(item, run_count=run_counts.get(item.id, 0)) for item in items],
        "total": int(total),
        "next_offset": offset + limit if offset + limit < int(total) else None,
    }


@router.post("/v1/datasets/{dataset_ref}/versions/{version_ref}/items")
def create_item(
    dataset_ref: str,
    version_ref: str,
    req: UpsertItemRequest,
    project_slug: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
    principal: Principal = Depends(dataset_principal),
) -> Dict[str, Any]:
    _require_scope(principal, "datasets:write")
    project = _project_for_request(db, principal, project_slug)
    dataset = _get_dataset(db, project, dataset_ref)
    version = _resolve_version(db, dataset, version_ref)
    _require_draft(version)
    input_value = _json_safe(req.input)
    expected = _json_safe(req.expected_output)
    metadata = _json_safe(req.metadata or {})
    max_index = (
        db.query(func.max(DatasetItem.index))
        .filter(DatasetItem.dataset_version_id == version.id)
        .scalar()
    )
    next_index = int(max_index) + 1 if max_index is not None else 0
    item_id = (req.item_id or "").strip() or f"item-{next_index + 1}"
    item = DatasetItem(
        dataset_version_id=version.id,
        item_id=item_id,
        index=next_index,
        input=input_value,
        expected_output=expected,
        item_metadata=metadata,
        labels=_labels(req.labels),
        fingerprint=build_identity_fingerprint(input_value=input_value, expected_value=expected, metadata=metadata),
        created_at=utc_now_naive(),
        updated_at=utc_now_naive(),
    )
    db.add(item)
    version.item_count = int(version.item_count or 0) + 1
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Dataset item ID already exists in this version") from exc
    _record_item_revision(
        db,
        version,
        item,
        change_type="created",
        before={},
        after=_item_payload(item),
        actor_user_id=principal.user.id,
    )
    db.commit()
    return {"item": _item_payload(item)}


@router.get("/v1/datasets/{dataset_ref}/versions/{version_ref}/items/{item_id}")
def get_item(
    dataset_ref: str,
    version_ref: str,
    item_id: str,
    project_slug: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
    principal: Principal = Depends(dataset_principal),
) -> Dict[str, Any]:
    _require_scope(principal, "datasets:read")
    project = _project_for_request(db, principal, project_slug)
    dataset = _get_dataset(db, project, dataset_ref)
    version = _resolve_version(db, dataset, version_ref)
    item = (
        db.query(DatasetItem)
        .filter(DatasetItem.dataset_version_id == version.id, DatasetItem.item_id == item_id)
        .first()
    )
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    run_count = db.query(RunItem.id).filter(RunItem.dataset_item_pk == item.id).count()
    return {"item": _item_payload(item, run_count=run_count)}


@router.patch("/v1/datasets/{dataset_ref}/versions/{version_ref}/items/{item_id}")
def update_item(
    dataset_ref: str,
    version_ref: str,
    item_id: str,
    req: UpsertItemRequest,
    project_slug: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
    principal: Principal = Depends(dataset_principal),
) -> Dict[str, Any]:
    _require_scope(principal, "datasets:write")
    project = _project_for_request(db, principal, project_slug)
    dataset = _get_dataset(db, project, dataset_ref)
    version = _resolve_version(db, dataset, version_ref)
    _require_draft(version)
    item = (
        db.query(DatasetItem)
        .filter(DatasetItem.dataset_version_id == version.id, DatasetItem.item_id == item_id)
        .first()
    )
    if not item:
        raise HTTPException(status_code=404, detail="Dataset item not found")
    before = _item_payload(item)
    input_value = _json_safe(req.input)
    expected = _json_safe(req.expected_output)
    metadata = _json_safe(req.metadata or {})
    item.item_id = (req.item_id or item.item_id).strip()
    item.input = input_value
    item.expected_output = expected
    item.item_metadata = metadata
    item.labels = _labels(req.labels)
    item.fingerprint = build_identity_fingerprint(input_value=input_value, expected_value=expected, metadata=metadata)
    item.updated_at = utc_now_naive()
    _record_item_revision(db, version, item, change_type="updated", before=before, after=_item_payload(item), actor_user_id=principal.user.id)
    db.commit()
    return {"item": _item_payload(item)}


@router.delete("/v1/datasets/{dataset_ref}/versions/{version_ref}/items/{item_id}")
def delete_item(
    dataset_ref: str,
    version_ref: str,
    item_id: str,
    project_slug: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
    principal: Principal = Depends(dataset_principal),
) -> Dict[str, Any]:
    _require_scope(principal, "datasets:write")
    project = _project_for_request(db, principal, project_slug)
    dataset = _get_dataset(db, project, dataset_ref)
    version = _resolve_version(db, dataset, version_ref)
    _require_draft(version)
    item = (
        db.query(DatasetItem)
        .filter(DatasetItem.dataset_version_id == version.id, DatasetItem.item_id == item_id)
        .first()
    )
    if not item:
        raise HTTPException(status_code=404, detail="Dataset item not found")
    before = _item_payload(item)
    _record_item_revision(db, version, item, change_type="deleted", before=before, after={}, actor_user_id=principal.user.id)
    db.delete(item)
    version.item_count = max(0, int(version.item_count or 0) - 1)
    db.commit()
    return {"ok": True}


@router.post("/v1/datasets/{dataset_ref}/versions/{version_ref}/items:bulk")
def bulk_items(
    dataset_ref: str,
    version_ref: str,
    req: BulkItemsRequest,
    project_slug: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
    principal: Principal = Depends(dataset_principal),
) -> Dict[str, Any]:
    _require_scope(principal, "datasets:write")
    project = _project_for_request(db, principal, project_slug)
    dataset = _get_dataset(db, project, dataset_ref)
    version = _resolve_version(db, dataset, version_ref)
    _require_draft(version)

    created: list[Dict[str, Any]] = []
    updated: list[Dict[str, Any]] = []
    deleted: list[str] = []

    for raw_id in req.deletes or []:
        target_id = (raw_id or "").strip()
        if not target_id:
            continue
        item = (
            db.query(DatasetItem)
            .filter(DatasetItem.dataset_version_id == version.id, DatasetItem.item_id == target_id)
            .first()
        )
        if not item:
            continue
        before = _item_payload(item)
        _record_item_revision(
            db, version, item, change_type="deleted", before=before, after={}, actor_user_id=principal.user.id,
        )
        db.delete(item)
        version.item_count = max(0, int(version.item_count or 0) - 1)
        deleted.append(target_id)

    db.flush()

    max_index = (
        db.query(func.max(DatasetItem.index))
        .filter(DatasetItem.dataset_version_id == version.id)
        .scalar()
    )
    next_index = int(max_index) + 1 if max_index is not None else 0

    for entry in req.upserts or []:
        input_value = _json_safe(entry.input)
        expected = _json_safe(entry.expected_output)
        metadata = _json_safe(entry.metadata or {})
        labels = _labels(entry.labels)
        fingerprint = build_identity_fingerprint(input_value=input_value, expected_value=expected, metadata=metadata)
        existing = None
        if entry.item_id:
            existing = (
                db.query(DatasetItem)
                .filter(DatasetItem.dataset_version_id == version.id, DatasetItem.item_id == entry.item_id.strip())
                .first()
            )
        op = (entry.op or "").lower()
        if existing and op != "create":
            before = _item_payload(existing)
            existing.input = input_value
            existing.expected_output = expected
            existing.item_metadata = metadata
            existing.labels = labels
            existing.fingerprint = fingerprint
            existing.updated_at = utc_now_naive()
            _record_item_revision(
                db, version, existing, change_type="updated", before=before, after=_item_payload(existing), actor_user_id=principal.user.id,
            )
            updated.append(_item_payload(existing))
        else:
            item_id = (entry.item_id or "").strip() or f"item-{next_index + 1}"
            new_item = DatasetItem(
                dataset_version_id=version.id,
                item_id=item_id,
                index=next_index,
                input=input_value,
                expected_output=expected,
                item_metadata=metadata,
                labels=labels,
                fingerprint=fingerprint,
                created_at=utc_now_naive(),
                updated_at=utc_now_naive(),
            )
            db.add(new_item)
            version.item_count = int(version.item_count or 0) + 1
            try:
                db.flush()
            except IntegrityError as exc:
                db.rollback()
                raise HTTPException(status_code=409, detail=f"Dataset item ID already exists: {item_id}") from exc
            _record_item_revision(
                db, version, new_item, change_type="created", before={}, after=_item_payload(new_item), actor_user_id=principal.user.id,
            )
            created.append(_item_payload(new_item))
            next_index += 1

    db.commit()
    return {
        "summary": {"created": len(created), "updated": len(updated), "deleted": len(deleted)},
        "created": created,
        "updated": updated,
        "deleted": deleted,
    }


@router.get("/v1/datasets/{dataset_ref}/versions/{version_ref}/items/{item_id}/runs")
def item_runs(
    dataset_ref: str,
    version_ref: str,
    item_id: str,
    project_slug: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
    principal: Principal = Depends(dataset_principal),
) -> Dict[str, Any]:
    _require_scope(principal, "datasets:read")
    project = _project_for_request(db, principal, project_slug)
    dataset = _get_dataset(db, project, dataset_ref)
    version = _resolve_version(db, dataset, version_ref)
    item = (
        db.query(DatasetItem)
        .filter(DatasetItem.dataset_version_id == version.id, DatasetItem.item_id == item_id)
        .first()
    )
    if not item:
        raise HTTPException(status_code=404, detail="Dataset item not found")
    rows = (
        db.query(Run, RunItem)
        .join(RunItem, RunItem.run_id == Run.id)
        .filter(
            Run.deleted_at.is_(None),
            Run.project_id == project.id,
            (
                (RunItem.dataset_item_pk == item.id)
                | ((Run.dataset_version_id == version.id) & (RunItem.item_id == item.item_id))
            ),
        )
        .order_by(Run.created_at.desc())
        .all()
    )
    return {
        "item": _item_payload(item),
        "runs": [
            {
                "run_id": run.id,
                "external_run_id": run.external_run_id,
                "task": run.task,
                "dataset": run.dataset,
                "model": run.model,
                "status": run.status.value if hasattr(run.status, "value") else str(run.status),
                "created_at": to_api_timestamp(run.created_at),
                "item_id": run_item.item_id,
                "trace_id": run_item.trace_id,
                "trace_url": run_item.trace_url,
                "error": run_item.error,
            }
            for run, run_item in rows
        ],
    }


@router.get("/v1/datasets/{dataset_ref}/versions/{version_ref}:compare")
def compare_versions(
    dataset_ref: str,
    version_ref: str,
    base: str = Query(...),
    project_slug: Optional[str] = Query(default=None),
    include_diffs: int = Query(default=0),
    db: Session = Depends(get_db),
    principal: Principal = Depends(dataset_principal),
) -> Dict[str, Any]:
    _require_scope(principal, "datasets:read")
    project = _project_for_request(db, principal, project_slug)
    dataset = _get_dataset(db, project, dataset_ref)
    target = _resolve_version(db, dataset, version_ref)
    base_version = _resolve_version(db, dataset, base)
    base_items = {item.item_id: item for item in db.query(DatasetItem).filter(DatasetItem.dataset_version_id == base_version.id).all()}
    target_items = {item.item_id: item for item in db.query(DatasetItem).filter(DatasetItem.dataset_version_id == target.id).all()}
    added = sorted(set(target_items) - set(base_items))
    removed = sorted(set(base_items) - set(target_items))
    changed = []
    unchanged = []
    field_diffs: list[Dict[str, Any]] = []
    want_diffs = bool(include_diffs)
    for item_id_key in sorted(set(base_items) & set(target_items)):
        b = base_items[item_id_key]
        t = target_items[item_id_key]
        if b.fingerprint == t.fingerprint and (b.labels or []) == (t.labels or []):
            unchanged.append(item_id_key)
        else:
            fields = []
            if b.input != t.input:
                fields.append("input")
            if b.expected_output != t.expected_output:
                fields.append("expected_output")
            if (b.item_metadata or {}) != (t.item_metadata or {}):
                fields.append("metadata")
            if (b.labels or []) != (t.labels or []):
                fields.append("labels")
            changed.append({"item_id": item_id_key, "fields": fields})
            if want_diffs:
                field_diffs.append(
                    {
                        "item_id": item_id_key,
                        "fields": fields,
                        "before": {
                            "input": b.input,
                            "expected_output": b.expected_output,
                            "metadata": b.item_metadata or {},
                            "labels": b.labels or [],
                        },
                        "after": {
                            "input": t.input,
                            "expected_output": t.expected_output,
                            "metadata": t.item_metadata or {},
                            "labels": t.labels or [],
                        },
                    }
                )
    response: Dict[str, Any] = {
        "base": _version_payload(db, base_version),
        "target": _version_payload(db, target),
        "summary": {"added": len(added), "removed": len(removed), "changed": len(changed), "unchanged": len(unchanged)},
        "added": added,
        "removed": removed,
        "changed": changed,
        "unchanged": unchanged,
    }
    if want_diffs:
        response["added_items"] = [_item_payload(target_items[i]) for i in added]
        response["removed_items"] = [_item_payload(base_items[i]) for i in removed]
        response["field_diffs"] = field_diffs
    return response


@router.post("/v1/datasets:upload")
async def upload_dataset(
    name: str = Form(...),
    project_slug: Optional[str] = Form(default=None),
    version: str = Form(default="v1"),
    description: str = Form(default=""),
    tags: str = Form(default=""),
    labels: str = Form(default=""),
    publish: bool = Form(default=False),
    set_alias: Optional[str] = Form(default=None),
    input_col: str = Form(default="input"),
    expected_col: str = Form(default="expected_output"),
    input_cols: str = Form(default=""),
    expected_cols: str = Form(default=""),
    id_col: Optional[str] = Form(default=None),
    metadata_cols: str = Form(default=""),
    label_cols: str = Form(default=""),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    principal: Principal = Depends(dataset_principal),
) -> Dict[str, Any]:
    _require_scope(principal, "datasets:write")
    project = _project_for_request(db, principal, project_slug)
    slug = _slugify(name)
    dataset = (
        db.query(Dataset)
        .filter(Dataset.project_id == project.id, Dataset.slug == slug, Dataset.deleted_at.is_(None))
        .first()
    )
    if not dataset:
        dataset = Dataset(id=str(uuid4()), project_id=project.id, name=name, slug=slug, tags=_labels(tags), created_by_user_id=principal.user.id, created_at=utc_now_naive(), updated_at=utc_now_naive())
        db.add(dataset)
        db.flush()
    # New-style callers (the dashboard) send the multi-column params input_cols/expected_cols,
    # where an empty expected_cols genuinely means "no expected output". Legacy callers (the SDK)
    # send the single-column input_col/expected_col, which carry the historical defaults.
    if input_cols:
        input_columns = _labels(input_cols)
        expected_columns = _labels(expected_cols)
    else:
        input_columns = [input_col] if input_col else []
        expected_columns = [expected_col] if expected_col else []
    raw = await file.read()
    filename = file.filename or ""
    if filename.lower().endswith(".jsonl"):
        source_type = "jsonl"
        items = _items_from_jsonl(raw)
    else:
        source_type = "csv"
        items = _items_from_csv(
            raw,
            input_cols=input_columns,
            expected_cols=expected_columns,
            id_col=id_col,
            metadata_cols=_labels(metadata_cols),
            label_cols=_labels(label_cols),
        )
    version_row = DatasetVersion(
        id=str(uuid4()),
        dataset_id=dataset.id,
        version=version,
        description=description,
        status=DatasetVersionStatus.DRAFT,
        source_type=source_type,
        source_uri=filename,
        labels=_labels(labels),
        schema={"input_cols": input_columns, "expected_cols": expected_columns, "id_col": id_col, "metadata_cols": _labels(metadata_cols), "label_cols": _labels(label_cols)},
        created_by_user_id=principal.user.id,
        created_at=utc_now_naive(),
        updated_at=utc_now_naive(),
    )
    db.add(version_row)
    db.flush()
    _insert_items(db, version_row, items)
    _record_change(db, version_row, {"type": "uploaded", "source_type": source_type, "item_count": len(items)})
    if publish:
        inserted = db.query(DatasetItem).filter(DatasetItem.dataset_version_id == version_row.id).all()
        version_row.status = DatasetVersionStatus.PUBLISHED
        version_row.published_by_user_id = principal.user.id
        version_row.published_at = utc_now_naive()
        version_row.content_hash = _content_hash(inserted)
        if set_alias:
            _set_alias(db, dataset, set_alias, version_row, principal.user.id)
    db.commit()
    return {"dataset": _dataset_payload(db, dataset), "version": _version_payload(db, version_row)}


@router.get("/v1/datasets/{dataset_ref}/versions/{version_ref}:download")
def download_version(
    dataset_ref: str,
    version_ref: str,
    project_slug: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
    principal: Principal = Depends(dataset_principal),
) -> Response:
    _require_scope(principal, "datasets:read")
    project = _project_for_request(db, principal, project_slug)
    dataset = _get_dataset(db, project, dataset_ref)
    version = _resolve_version(db, dataset, version_ref)
    items = db.query(DatasetItem).filter(DatasetItem.dataset_version_id == version.id).order_by(DatasetItem.index).all()
    lines = [
        json.dumps(
            {
                "item_id": item.item_id,
                "input": item.input,
                "expected_output": item.expected_output,
                "metadata": item.item_metadata or {},
                "labels": item.labels or [],
            },
            ensure_ascii=False,
        )
        for item in items
    ]
    filename = f"{dataset.slug}-{version.version}.jsonl"
    return Response(
        "\n".join(lines) + ("\n" if lines else ""),
        media_type="application/x-ndjson",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/v1/datasets/{dataset_ref}/versions/{version_ref}")
def get_version(
    dataset_ref: str,
    version_ref: str,
    project_slug: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
    principal: Principal = Depends(dataset_principal),
) -> Dict[str, Any]:
    _require_scope(principal, "datasets:read")
    project = _project_for_request(db, principal, project_slug)
    dataset = _get_dataset(db, project, dataset_ref)
    version = _resolve_version(db, dataset, version_ref)
    return {"dataset": _dataset_payload(db, dataset), "version": _version_payload(db, version)}


@router.get("/api/datasets/{dataset_ref}/versions/{version_ref}/items/{item_id}/revisions")
def item_revisions(
    dataset_ref: str,
    version_ref: str,
    item_id: str,
    project_slug: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
    principal: Principal = Depends(dataset_principal),
) -> Dict[str, Any]:
    _require_scope(principal, "datasets:read")
    project = _project_for_request(db, principal, project_slug)
    dataset = _get_dataset(db, project, dataset_ref)
    version = _resolve_version(db, dataset, version_ref)
    item = db.query(DatasetItem).filter(DatasetItem.dataset_version_id == version.id, DatasetItem.item_id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Dataset item not found")
    rows = (
        db.query(DatasetItemRevision)
        .filter(DatasetItemRevision.dataset_version_id == version.id, DatasetItemRevision.dataset_item_id == item.id)
        .order_by(DatasetItemRevision.revision_number.desc())
        .all()
    )
    return {
        "revisions": [
            {
                "id": row.id,
                "revision_number": row.revision_number,
                "change_type": row.change_type,
                "before": row.before,
                "after": row.after,
                "actor_user_id": row.actor_user_id,
                "created_at": to_api_timestamp(row.created_at),
            }
            for row in rows
        ]
    }
