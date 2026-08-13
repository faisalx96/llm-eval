from __future__ import annotations

import codecs
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


def _free_slug_from_deleted(db: Session, project: Project, slug: str) -> None:
    """Release a slug held by soft-deleted datasets so it can be reused.

    Deleting a dataset is a soft delete (``deleted_at`` is set, the row stays), but the
    ``uq_dataset_project_slug`` unique index covers deleted rows too. Without this, once a
    dataset is deleted its name can never be reused. We rename any soft-deleted collider's
    slug to a tombstone, freeing the original slug while preserving the old row's data.
    """
    stale = (
        db.query(Dataset)
        .filter(
            Dataset.project_id == project.id,
            Dataset.slug == slug,
            Dataset.deleted_at.isnot(None),
        )
        .all()
    )
    for ds in stale:
        ds.slug = f"{slug}__deleted_{uuid4().hex[:8]}"
    if stale:
        db.flush()


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


def _user_payload(user: Optional[User]) -> Optional[Dict[str, Any]]:
    if not user:
        return None
    return {
        "id": user.id,
        "email": user.email,
        "display_name": user.display_name or user.email.split("@")[0],
    }


def _user_map(db: Session, user_ids: Iterable[Optional[str]]) -> Dict[str, User]:
    ids = {str(user_id) for user_id in user_ids if user_id}
    if not ids:
        return {}
    return {user.id: user for user in db.query(User).filter(User.id.in_(ids)).all()}


def _item_payload(
    item: DatasetItem,
    *,
    run_count: Optional[int] = None,
    result_summary: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
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
    if result_summary is not None:
        payload["result_summary"] = result_summary
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
    users = _user_map(db, [version.created_by_user_id, version.published_by_user_id])
    return {
        "id": version.id,
        "dataset_id": version.dataset_id,
        "version": version.version,
        "name": version.name or "",
        "description": version.description,
        "status": version.status.value if hasattr(version.status, "value") else str(version.status),
        "source_type": version.source_type,
        "source_uri": version.source_uri,
        "parent_version_id": version.parent_version_id,
        "base_version_id": version.base_version_id,
        "schema": version.schema or {},
        "labels": version.labels or [],
        "item_count": version.item_count,
        "run_count": int(run_count or 0),
        "content_hash": version.content_hash,
        "created_by_user_id": version.created_by_user_id,
        "published_by_user_id": version.published_by_user_id,
        "created_by": _user_payload(users.get(version.created_by_user_id)),
        "published_by": _user_payload(users.get(version.published_by_user_id)),
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
        "created_by": _user_payload(_user_map(db, [dataset.created_by_user_id]).get(dataset.created_by_user_id)),
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


def _item_changed(a: DatasetItem, b: DatasetItem) -> bool:
    return (
        a.fingerprint != b.fingerprint
        or (a.labels or []) != (b.labels or [])
        or a.input != b.input
        or a.expected_output != b.expected_output
        or (a.item_metadata or {}) != (b.item_metadata or {})
    )


def _version_delta_summary(db: Session, version: DatasetVersion) -> Dict[str, int]:
    current_items = {
        item.item_id: item
        for item in db.query(DatasetItem)
        .filter(DatasetItem.dataset_version_id == version.id)
        .all()
    }
    if not version.parent_version_id:
        return {
            "added": len(current_items),
            "modified": 0,
            "deleted": 0,
            "unchanged": 0,
        }
    parent_items = {
        item.item_id: item
        for item in db.query(DatasetItem)
        .filter(DatasetItem.dataset_version_id == version.parent_version_id)
        .all()
    }
    current_ids = set(current_items)
    parent_ids = set(parent_items)
    shared = current_ids & parent_ids
    modified = sum(1 for item_id in shared if _item_changed(parent_items[item_id], current_items[item_id]))
    return {
        "added": len(current_ids - parent_ids),
        "modified": modified,
        "deleted": len(parent_ids - current_ids),
        "unchanged": len(shared) - modified,
    }


def _score_numeric_value(score: RunItemScore) -> Optional[float]:
    if score.score_numeric is not None:
        return float(score.score_numeric)
    raw = score.score_raw
    if isinstance(raw, (int, float, bool)):
        return float(raw)
    if isinstance(raw, str):
        try:
            return float(raw)
        except ValueError:
            return None
    if isinstance(raw, dict):
        for key in ("score", "value"):
            value = raw.get(key)
            if isinstance(value, (int, float, bool)):
                return float(value)
            if isinstance(value, str):
                try:
                    return float(value)
                except ValueError:
                    continue
    return None


def _is_generated_item_id(value: Any) -> bool:
    text = str(value or "").strip()
    if not text:
        return True
    if re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}", text, flags=re.I):
        return True
    if re.fullmatch(r"item-\d+", text, flags=re.I):
        return True
    if re.fullmatch(r"ds_[0-9a-f]{64}__\d{4}", text, flags=re.I):
        return True
    return False


def _item_result_summaries(
    db: Session,
    version: DatasetVersion,
    items: list[DatasetItem],
) -> Dict[int, Dict[str, Any]]:
    if not items:
        return {}
    by_pk = {item.id: item for item in items}
    by_item_id = {item.item_id: item for item in items}
    rows = (
        db.query(Run, RunItem)
        .join(RunItem, RunItem.run_id == Run.id)
        .filter(
            Run.deleted_at.is_(None),
            Run.dataset_version_id == version.id,
            (
                RunItem.dataset_item_pk.in_(list(by_pk))
                | RunItem.item_id.in_(list(by_item_id))
            ),
        )
        .all()
    )
    summaries: Dict[int, Dict[str, Any]] = {
        item.id: {
            "run_count": 0,
            "success_count": 0,
            "error_count": 0,
            "avg_latency_ms": None,
            "avg_score": None,
            "metrics": {},
        }
        for item in items
    }
    run_item_keys_by_pk: Dict[int, set[tuple[str, str]]] = {item.id: set() for item in items}
    latencies_by_pk: Dict[int, list[float]] = {item.id: [] for item in items}
    for run, run_item in rows:
        item = by_pk.get(run_item.dataset_item_pk) if run_item.dataset_item_pk is not None else None
        if item is None:
            item = by_item_id.get(run_item.item_id)
        if item is None:
            continue
        summary = summaries[item.id]
        summary["run_count"] += 1
        if run_item.error:
            summary["error_count"] += 1
        else:
            summary["success_count"] += 1
        if run_item.latency_ms is not None:
            latencies_by_pk[item.id].append(float(run_item.latency_ms))
        run_item_keys_by_pk[item.id].add((run.id, run_item.item_id))

    all_run_ids = {run_id for keys in run_item_keys_by_pk.values() for run_id, _ in keys}
    all_item_ids = {item_id for keys in run_item_keys_by_pk.values() for _, item_id in keys}
    score_rows: list[RunItemScore] = []
    if all_run_ids and all_item_ids:
        score_rows = (
            db.query(RunItemScore)
            .filter(RunItemScore.run_id.in_(all_run_ids), RunItemScore.item_id.in_(all_item_ids))
            .all()
        )
    scores_by_key: Dict[tuple[str, str], list[RunItemScore]] = defaultdict(list)
    for score in score_rows:
        scores_by_key[(score.run_id, score.item_id)].append(score)

    for item in items:
        numeric_scores: list[float] = []
        metrics: Dict[str, Dict[str, Any]] = {}
        for key in run_item_keys_by_pk[item.id]:
            for score in scores_by_key.get(key, []):
                value = _score_numeric_value(score)
                if value is None:
                    continue
                numeric_scores.append(value)
                metric = metrics.setdefault(
                    score.metric_name,
                    {"count": 0, "avg": None, "min": None, "max": None, "_sum": 0.0},
                )
                metric["count"] += 1
                metric["_sum"] += value
                metric["min"] = value if metric["min"] is None else min(float(metric["min"]), value)
                metric["max"] = value if metric["max"] is None else max(float(metric["max"]), value)
        for metric in metrics.values():
            metric["avg"] = round(float(metric["_sum"]) / int(metric["count"]), 4) if metric["count"] else None
            metric.pop("_sum", None)
        latencies = latencies_by_pk[item.id]
        summary = summaries[item.id]
        summary["avg_latency_ms"] = round(sum(latencies) / len(latencies), 2) if latencies else None
        summary["avg_score"] = round(sum(numeric_scores) / len(numeric_scores), 4) if numeric_scores else None
        summary["metrics"] = metrics
    return summaries


def _version_metric_names(db: Session, version: DatasetVersion) -> list[str]:
    names: set[str] = set()
    score_rows = (
        db.query(RunItemScore.metric_name)
        .join(Run, Run.id == RunItemScore.run_id)
        .filter(
            Run.deleted_at.is_(None),
            Run.dataset_version_id == version.id,
        )
        .distinct()
        .order_by(RunItemScore.metric_name)
        .all()
    )
    names.update(str(metric_name) for (metric_name,) in score_rows if metric_name)
    run_rows = (
        db.query(Run.metrics)
        .filter(Run.deleted_at.is_(None), Run.dataset_version_id == version.id)
        .all()
    )
    for (metrics,) in run_rows:
        if isinstance(metrics, list):
            names.update(str(metric) for metric in metrics if metric)
    return sorted(names)


def _item_edit_counts(db: Session, version: DatasetVersion, items: list[DatasetItem]) -> Dict[int, int]:
    if not items:
        return {}
    versions_by_id = {
        row.id: row
        for row in db.query(DatasetVersion).filter(DatasetVersion.dataset_id == version.dataset_id).all()
    }
    chain_ids: list[str] = []
    seen: set[str] = set()
    cursor: Optional[DatasetVersion] = version
    while cursor and cursor.id not in seen:
        seen.add(cursor.id)
        chain_ids.append(cursor.id)
        cursor = versions_by_id.get(cursor.parent_version_id) if cursor.parent_version_id else None

    tracked = {
        item.id: {
            "item_id": item.item_id,
            "index": item.index,
            "use_index": _is_generated_item_id(item.item_id),
            "count": 0,
        }
        for item in items
    }
    revisions = (
        db.query(DatasetItemRevision)
        .filter(
            DatasetItemRevision.dataset_version_id.in_(chain_ids),
            DatasetItemRevision.change_type == "updated",
        )
        .all()
    )
    for revision in revisions:
        before = revision.before or {}
        after = revision.after or {}
        before_id = str(before.get("item_id") or "")
        after_id = str(after.get("item_id") or "")
        before_index = before.get("index")
        after_index = after.get("index")
        for item_pk, identity in tracked.items():
            if revision.dataset_item_id == item_pk:
                identity["count"] += 1
                break
            if identity["item_id"] in {before_id, after_id}:
                identity["count"] += 1
                break
            if identity["use_index"] and identity["index"] in {before_index, after_index}:
                identity["count"] += 1
                break
    return {item.id: int(tracked[item.id]["count"]) for item in items}


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


def _detach_item_revisions(db: Session, item: DatasetItem) -> None:
    db.query(DatasetItemRevision).filter(DatasetItemRevision.dataset_item_id == item.id).update(
        {DatasetItemRevision.dataset_item_id: None},
        synchronize_session=False,
    )


def _detach_item_run_results(db: Session, item: DatasetItem) -> None:
    db.query(RunItem).filter(RunItem.dataset_item_pk == item.id).update(
        {RunItem.dataset_item_pk: None},
        synchronize_session=False,
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
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            return text
    return text


def _combine_columns(row: Dict[str, Any], cols: list[str]) -> Any:
    """One column -> the raw (parsed) cell value; multiple columns -> a JSON object
    keyed by column name. Returns None when no columns are given."""
    if not cols:
        return None
    if len(cols) == 1:
        return _parse_cell(row.get(cols[0], ""))
    return {col: _parse_cell(row.get(col, "")) for col in cols}


def _decode_csv(raw: bytes) -> str:
    if not raw:
        raise HTTPException(status_code=400, detail="CSV file is empty")
    if raw.startswith((codecs.BOM_UTF32_LE, codecs.BOM_UTF32_BE)):
        encodings = ["utf-32"]
    elif raw.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        encodings = ["utf-16"]
    else:
        encodings = ["utf-8-sig", "cp1252"]
    for encoding in encodings:
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise HTTPException(
        status_code=400,
        detail="Unsupported CSV encoding; export as UTF-8, UTF-16, or Windows-1252",
    )


def _csv_reader(raw: bytes) -> csv.DictReader:
    text = _decode_csv(raw)
    try:
        dialect = csv.Sniffer().sniff(text[:65536], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    return csv.DictReader(io.StringIO(text, newline=""), dialect=dialect)


def _items_from_csv(
    raw: bytes,
    *,
    input_cols: list[str],
    expected_cols: list[str],
    id_col: Optional[str],
    metadata_cols: list[str],
    label_cols: list[str],
) -> list[Dict[str, Any]]:
    reader = _csv_reader(raw)
    raw_fields = list(reader.fieldnames or [])
    fields = [field.strip() if field is not None else "" for field in raw_fields]
    if not fields:
        raise HTTPException(status_code=400, detail="CSV has no header row")
    if any(not field for field in fields):
        raise HTTPException(status_code=400, detail="CSV contains an empty column header")
    duplicate_fields = sorted({field for field in fields if fields.count(field) > 1})
    if duplicate_fields:
        raise HTTPException(
            status_code=400,
            detail=f"CSV contains duplicate column headers: {', '.join(duplicate_fields)}",
        )
    reader.fieldnames = fields
    if not input_cols:
        raise HTTPException(status_code=400, detail="At least one input column is required")
    selected_cols = input_cols + expected_cols + metadata_cols + label_cols
    if id_col:
        selected_cols.append(id_col)
    for col in [c for c in selected_cols if c and c not in fields]:
        raise HTTPException(status_code=400, detail=f"Missing column: {col}")
    items: list[Dict[str, Any]] = []
    for row_number, row in enumerate(reader, start=2):
        extra_values = row.pop(None, None)
        if extra_values and any(str(value or "").strip() for value in extra_values):
            raise HTTPException(
                status_code=400,
                detail=f"CSV row {row_number} has more values than the header",
            )
        if not any(str(value or "").strip() for value in row.values()):
            continue
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
    name: str = ""
    description: str = ""
    labels: list[str] = Field(default_factory=list)
    from_version: Optional[str] = None
    from_alias: Optional[str] = None


class UpdateVersionRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None


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
    slug = _slugify(req.slug or req.name)
    _free_slug_from_deleted(db, project, slug)
    dataset = Dataset(
        id=str(uuid4()),
        project_id=project.id,
        name=req.name.strip(),
        slug=slug,
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
    avg_latencies: Dict[str, float] = {}
    metric_values_by_run: Dict[str, Dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    eval_values_by_run: Dict[str, list[float]] = defaultdict(list)
    if run_ids:
        items_counts = dict(
            db.query(RunItem.run_id, func.count(RunItem.id))
            .filter(RunItem.run_id.in_(run_ids))
            .group_by(RunItem.run_id)
            .all()
        )
        avg_latencies = {
            run_id: round(float(avg_latency), 2)
            for run_id, avg_latency in (
                db.query(RunItem.run_id, func.avg(RunItem.latency_ms))
                .filter(RunItem.run_id.in_(run_ids), RunItem.latency_ms.isnot(None))
                .group_by(RunItem.run_id)
                .all()
            )
            if avg_latency is not None
        }
        score_rows = (
            db.query(RunItemScore)
            .filter(RunItemScore.run_id.in_(run_ids))
            .all()
        )
        for score in score_rows:
            value = _score_numeric_value(score)
            if value is None:
                continue
            metric_values_by_run[score.run_id][score.metric_name].append(value)
            eval_values_by_run[score.run_id].append(value)

    metric_names = sorted({metric for metrics in metric_values_by_run.values() for metric in metrics})

    def run_metric_averages(run_id: str) -> Dict[str, Optional[float]]:
        metrics = metric_values_by_run.get(run_id, {})
        return {
            metric: round(sum(values) / len(values), 4) if values else None
            for metric, values in sorted(metrics.items())
        }

    def run_eval_score(run_id: str) -> Optional[float]:
        values = eval_values_by_run.get(run_id) or []
        return round(sum(values) / len(values), 4) if values else None

    return {
        "runs": [
            {
                "id": run.id,
                "run_name": (
                    str((run.run_config or {}).get("run_name") or "")
                    if isinstance(run.run_config, dict)
                    else ""
                )
                or run.external_run_id
                or run.id,
                "external_run_id": run.external_run_id,
                "status": run.status.value if hasattr(run.status, "value") else str(run.status),
                "task": run.task,
                "model": run.model,
                "started_at": to_api_timestamp(run.started_at),
                "completed_at": to_api_timestamp(run.ended_at),
                "avg_latency_ms": avg_latencies.get(run.id),
                "eval_score": run_eval_score(run.id),
                "metric_averages": run_metric_averages(run.id),
                "version_label": version_labels.get(run.dataset_version_id),
                "items_count": int(items_counts.get(run.id, 0)),
            }
            for run in runs
        ],
        "total": total,
        "metric_names": metric_names,
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
    version_name, display_name = _version_identity(db, dataset, req.version, req.name)
    version = DatasetVersion(
        id=str(uuid4()),
        dataset_id=dataset.id,
        version=version_name,
        name=display_name,
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


@router.patch("/v1/datasets/{dataset_ref}/versions/{version_ref}")
def update_version(
    dataset_ref: str,
    version_ref: str,
    req: UpdateVersionRequest,
    project_slug: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
    principal: Principal = Depends(dataset_principal),
) -> Dict[str, Any]:
    """Edit version metadata. The vN identifier itself is immutable."""
    _require_scope(principal, "datasets:write")
    project = _project_for_request(db, principal, project_slug)
    dataset = _get_dataset(db, project, dataset_ref)
    version = _resolve_version(db, dataset, version_ref)
    if req.name is not None:
        version.name = req.name.strip()
    if req.description is not None:
        version.description = req.description
    version.updated_at = utc_now_naive()
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


def _version_identity(db: Session, dataset: Dataset, requested_version: Optional[str], requested_name: str = "") -> tuple[str, str]:
    """Version identifiers are always sequential ``vN``; free text becomes the name.

    An explicitly requested ``vN`` that is still free is honored. Anything else
    (custom labels from older callers, or a collision) falls through to
    auto-numbering, preserving the free text as the display name.
    """
    requested = (requested_version or "").strip()
    name = (requested_name or "").strip()
    if re.fullmatch(r"v\d+", requested):
        taken = (
            db.query(DatasetVersion.id)
            .filter(DatasetVersion.dataset_id == dataset.id, DatasetVersion.version == requested)
            .first()
        )
        if not taken:
            return requested, name
    elif requested and not name:
        name = requested
    return _next_version_name(db, dataset), name


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
    user_ids: set[str] = set()
    for version in versions:
        if version.created_by_user_id:
            user_ids.add(version.created_by_user_id)
        if version.published_by_user_id:
            user_ids.add(version.published_by_user_id)
    users = _user_map(db, user_ids)
    version_payloads = []
    for version in versions:
        payload = _version_payload(db, version)
        payload["created_by"] = _user_payload(users.get(version.created_by_user_id))
        payload["published_by"] = _user_payload(users.get(version.published_by_user_id))
        payload["change_counts"] = _version_delta_summary(db, version)
        version_payloads.append(payload)
    return {
        "dataset": _dataset_payload(db, dataset),
        "versions": version_payloads,
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

    sort_raw = sort or "index_asc"
    sort_key = sort_raw.lower()
    computed_sort = (
        sort_key.startswith("runs_")
        or sort_key.startswith("edits_")
        or sort_key.startswith("latency_")
        or sort_key.startswith("metric:")
    )
    if computed_sort:
        all_items = query.order_by(DatasetItem.index, DatasetItem.item_id).all()
        all_result_summaries = _item_result_summaries(db, version, all_items)
        all_edit_counts = _item_edit_counts(db, version, all_items)
        direction = "desc" if sort_key.endswith("_desc") or sort_key.endswith(":desc") else "asc"

        def computed_value(row: DatasetItem) -> Any:
            summary = all_result_summaries.get(row.id, {}) or {}
            if sort_key.startswith("runs_"):
                return summary.get("run_count") or 0
            if sort_key.startswith("edits_"):
                return all_edit_counts.get(row.id, 0)
            if sort_key.startswith("latency_"):
                value = summary.get("avg_latency_ms")
                return float(value) if value is not None else None
            if sort_key.startswith("metric:"):
                parts = sort_raw.split(":")
                metric_name = parts[1] if len(parts) >= 2 else ""
                value = ((summary.get("metrics") or {}).get(metric_name) or {}).get("avg")
                return float(value) if value is not None else None
            return row.index

        def sort_tuple(row: DatasetItem) -> tuple[int, Any, int, str]:
            value = computed_value(row)
            missing = 1 if value is None else 0
            if isinstance(value, (int, float)) and direction == "desc":
                value = -value
            return (missing, value if value is not None else 0, row.index, row.item_id)

        all_items.sort(key=sort_tuple)
        total = len(all_items)
        items = all_items[offset : offset + limit]
        result_summaries = {item.id: all_result_summaries.get(item.id) for item in items}
        edit_counts = {item.id: all_edit_counts.get(item.id, 0) for item in items}
    else:
        if sort_key == "index_desc":
            query = query.order_by(DatasetItem.index.desc(), DatasetItem.item_id)
        elif sort_key == "updated_desc":
            query = query.order_by(DatasetItem.updated_at.desc(), DatasetItem.item_id)
        elif sort_key == "item_id" or sort_key == "item_id_asc":
            query = query.order_by(DatasetItem.item_id)
        elif sort_key == "item_id_desc":
            query = query.order_by(DatasetItem.item_id.desc())
        elif sort_key == "input_asc":
            query = query.order_by(cast(DatasetItem.input, String), DatasetItem.index)
        elif sort_key == "input_desc":
            query = query.order_by(cast(DatasetItem.input, String).desc(), DatasetItem.index)
        elif sort_key == "expected_asc":
            query = query.order_by(cast(DatasetItem.expected_output, String), DatasetItem.index)
        elif sort_key == "expected_desc":
            query = query.order_by(cast(DatasetItem.expected_output, String).desc(), DatasetItem.index)
        elif sort_key == "metadata_asc":
            query = query.order_by(cast(DatasetItem.item_metadata, String), DatasetItem.index)
        elif sort_key == "metadata_desc":
            query = query.order_by(cast(DatasetItem.item_metadata, String).desc(), DatasetItem.index)
        else:
            query = query.order_by(DatasetItem.index, DatasetItem.item_id)

        total = query.with_entities(func.count(DatasetItem.id)).order_by(None).scalar() or 0
        items = query.offset(offset).limit(limit).all()
        result_summaries = _item_result_summaries(db, version, items)
        edit_counts = _item_edit_counts(db, version, items)
    metric_names = _version_metric_names(db, version)
    return {
        "dataset": _dataset_payload(db, dataset),
        "version": _version_payload(db, version),
        "items": [
            _item_payload(
                item,
                run_count=(result_summaries.get(item.id, {}) or {}).get("run_count", 0),
                result_summary=result_summaries.get(item.id),
            )
            | {"edit_count": edit_counts.get(item.id, 0)}
            for item in items
        ],
        "metric_names": metric_names,
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
    _record_item_revision(db, version, None, change_type="deleted", before=before, after={}, actor_user_id=principal.user.id)
    _detach_item_revisions(db, item)
    _detach_item_run_results(db, item)
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
            db, version, None, change_type="deleted", before=before, after={}, actor_user_id=principal.user.id,
        )
        _detach_item_revisions(db, item)
        _detach_item_run_results(db, item)
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
    run_ids = [run.id for run, _ in rows]
    run_item_keys = {(run.id, run_item.item_id) for run, run_item in rows}
    score_rows: list[RunItemScore] = []
    if run_ids:
        score_rows = (
            db.query(RunItemScore)
            .filter(RunItemScore.run_id.in_(run_ids))
            .all()
        )
    scores_by_key: Dict[tuple[str, str], list[RunItemScore]] = defaultdict(list)
    for score in score_rows:
        key = (score.run_id, score.item_id)
        if key in run_item_keys:
            scores_by_key[key].append(score)
    users = _user_map(db, [run.owner_user_id for run, _ in rows])
    numeric_scores_by_metric: Dict[str, list[float]] = defaultdict(list)
    all_numeric_scores: list[float] = []
    latencies: list[float] = []
    error_count = 0
    for run, run_item in rows:
        if run_item.error:
            error_count += 1
        if run_item.latency_ms is not None:
            latencies.append(float(run_item.latency_ms))
        for score in scores_by_key.get((run.id, run_item.item_id), []):
            value = _score_numeric_value(score)
            if value is None:
                continue
            all_numeric_scores.append(value)
            numeric_scores_by_metric[score.metric_name].append(value)
    metric_aggregates = {
        metric: {
            "count": len(values),
            "avg": round(sum(values) / len(values), 4) if values else None,
            "min": min(values) if values else None,
            "max": max(values) if values else None,
        }
        for metric, values in sorted(numeric_scores_by_metric.items())
    }
    return {
        "item": _item_payload(item),
        "aggregates": {
            "run_count": len(rows),
            "success_count": len(rows) - error_count,
            "error_count": error_count,
            "avg_latency_ms": round(sum(latencies) / len(latencies), 2) if latencies else None,
            "avg_score": round(sum(all_numeric_scores) / len(all_numeric_scores), 4) if all_numeric_scores else None,
            "metrics": metric_aggregates,
        },
        "runs": [
            {
                "run_id": run.id,
                "run_name": (
                    str((run.run_config or {}).get("run_name") or "")
                    if isinstance(run.run_config, dict)
                    else ""
                )
                or run.external_run_id
                or run.id,
                "external_run_id": run.external_run_id,
                "task": run.task,
                "dataset": run.dataset,
                "model": run.model,
                "status": run.status.value if hasattr(run.status, "value") else str(run.status),
                "created_at": to_api_timestamp(run.created_at),
                "started_at": to_api_timestamp(run.started_at),
                "completed_at": to_api_timestamp(run.ended_at),
                "owner": _user_payload(users.get(run.owner_user_id)),
                "item_id": run_item.item_id,
                "output": run_item.output,
                "trace_id": run_item.trace_id,
                "trace_url": run_item.trace_url,
                "error": run_item.error,
                "latency_ms": run_item.latency_ms,
                "retry_count": run_item.retry_count,
                "scores": [
                    {
                        "metric_name": score.metric_name,
                        "score_numeric": score.score_numeric,
                        "score_raw": score.score_raw,
                        "label": score.label,
                        "explanation": score.explanation,
                    }
                    for score in scores_by_key.get((run.id, run_item.item_id), [])
                ],
            }
            for run, run_item in rows
        ],
    }


@router.get("/v1/datasets/{dataset_ref}/versions/{version_ref}/items/{item_id}/neighbors")
def item_neighbors(
    dataset_ref: str,
    version_ref: str,
    item_id: str,
    project_slug: Optional[str] = Query(default=None),
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
    rows = query.all()
    idx = next((i for i, row in enumerate(rows) if row.item_id == item_id), -1)
    if idx < 0:
        raise HTTPException(status_code=404, detail="Dataset item not found in current item set")
    previous_item = rows[idx - 1] if idx > 0 else None
    next_item = rows[idx + 1] if idx + 1 < len(rows) else None
    return {
        "item_id": item_id,
        "index": idx,
        "total": len(rows),
        "previous": _item_payload(previous_item) if previous_item else None,
        "next": _item_payload(next_item) if next_item else None,
    }


@router.get("/v1/datasets/{dataset_ref}/versions/{version_ref}/items/{item_id}/lineage")
def item_lineage(
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
    versions_by_id = {
        row.id: row
        for row in db.query(DatasetVersion).filter(DatasetVersion.dataset_id == dataset.id).all()
    }
    chain: list[DatasetVersion] = []
    seen: set[str] = set()
    cursor: Optional[DatasetVersion] = version
    while cursor and cursor.id not in seen:
        seen.add(cursor.id)
        chain.append(cursor)
        cursor = versions_by_id.get(cursor.parent_version_id) if cursor.parent_version_id else None
    chain.reverse()

    items_by_version = {
        row.dataset_version_id: row
        for row in db.query(DatasetItem)
        .filter(DatasetItem.dataset_version_id.in_([v.id for v in chain]), DatasetItem.item_id == item_id)
        .all()
    }
    revision_rows = (
        db.query(DatasetItemRevision)
        .filter(DatasetItemRevision.dataset_version_id.in_([v.id for v in chain]))
        .order_by(DatasetItemRevision.created_at, DatasetItemRevision.revision_number)
        .all()
    )
    relevant_revisions: list[DatasetItemRevision] = []
    for revision in revision_rows:
        before_id = (revision.before or {}).get("item_id")
        after_id = (revision.after or {}).get("item_id")
        if before_id == item_id or after_id == item_id:
            relevant_revisions.append(revision)
            continue
        item = items_by_version.get(revision.dataset_version_id)
        if item and revision.dataset_item_id == item.id:
            relevant_revisions.append(revision)
    users = _user_map(
        db,
        [r.actor_user_id for r in relevant_revisions]
        + [v.created_by_user_id for v in chain]
        + [v.published_by_user_id for v in chain],
    )
    revisions_by_version: Dict[str, list[DatasetItemRevision]] = defaultdict(list)
    for revision in relevant_revisions:
        revisions_by_version[revision.dataset_version_id].append(revision)
    return {
        "item_id": item_id,
        "lineage": [
            {
                "version": _version_payload(db, v),
                "item": _item_payload(items_by_version[v.id]) if v.id in items_by_version else None,
                "revisions": [
                    {
                        "id": row.id,
                        "revision_number": row.revision_number,
                        "change_type": row.change_type,
                        "before": row.before,
                        "after": row.after,
                        "actor_user_id": row.actor_user_id,
                        "actor": _user_payload(users.get(row.actor_user_id)),
                        "actor_email": (users.get(row.actor_user_id).email if users.get(row.actor_user_id) else None),
                        "actor_name": (users.get(row.actor_user_id).display_name if users.get(row.actor_user_id) else None),
                        "created_at": to_api_timestamp(row.created_at),
                    }
                    for row in revisions_by_version.get(v.id, [])
                ],
            }
            for v in chain
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
    revision_rows = (
        db.query(DatasetItemRevision)
        .filter(DatasetItemRevision.dataset_version_id == target.id)
        .order_by(DatasetItemRevision.created_at.desc(), DatasetItemRevision.revision_number.desc())
        .all()
    )
    latest_revision_by_item_id: Dict[str, DatasetItemRevision] = {}
    for revision in revision_rows:
        before_id = (revision.before or {}).get("item_id")
        after_id = (revision.after or {}).get("item_id")
        for candidate_id in (after_id, before_id):
            if candidate_id and candidate_id not in latest_revision_by_item_id:
                latest_revision_by_item_id[str(candidate_id)] = revision
    actor_users = _user_map(
        db,
        [revision.actor_user_id for revision in revision_rows]
        + [target.created_by_user_id, target.published_by_user_id],
    )

    def _revision_actor_payload(item_id_value: str) -> Optional[Dict[str, Any]]:
        revision = latest_revision_by_item_id.get(item_id_value)
        if revision:
            return _user_payload(actor_users.get(revision.actor_user_id))
        # Imported versions and legacy data may not have per-item revision rows.
        # In that case, the head version creator is the narrowest attribution we have.
        return _user_payload(actor_users.get(target.created_by_user_id or target.published_by_user_id))

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
            actor_payload = _revision_actor_payload(item_id_key)
            changed_entry = {
                "item_id": item_id_key,
                "base_index": b.index,
                "target_index": t.index,
                "fields": fields,
                "edited_by": actor_payload,
            }
            changed.append(changed_entry)
            if want_diffs:
                field_diffs.append(
                    {
                        "item_id": item_id_key,
                        "base_index": b.index,
                        "target_index": t.index,
                        "fields": fields,
                        "edited_by": actor_payload,
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
    version: str = Form(default=""),
    version_name: str = Form(default=""),
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
        _free_slug_from_deleted(db, project, slug)
        dataset = Dataset(id=str(uuid4()), project_id=project.id, name=name, slug=slug, description=description, tags=_labels(tags), created_by_user_id=principal.user.id, created_at=utc_now_naive(), updated_at=utc_now_naive())
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
    version_label, display_name = _version_identity(db, dataset, version, version_name)
    version_row = DatasetVersion(
        id=str(uuid4()),
        dataset_id=dataset.id,
        version=version_label,
        name=display_name,
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
    actor_ids = {row.actor_user_id for row in rows if row.actor_user_id}
    actors: Dict[str, Dict[str, Any]] = {}
    if actor_ids:
        for user in db.query(User.id, User.email, User.display_name).filter(User.id.in_(actor_ids)).all():
            actors[user.id] = {"email": user.email, "name": user.display_name}
    return {
        "revisions": [
            {
                "id": row.id,
                "revision_number": row.revision_number,
                "change_type": row.change_type,
                "before": row.before,
                "after": row.after,
                "actor_user_id": row.actor_user_id,
                "actor_email": actors.get(row.actor_user_id, {}).get("email"),
                "actor_name": actors.get(row.actor_user_id, {}).get("name"),
                "created_at": to_api_timestamp(row.created_at),
            }
            for row in rows
        ]
    }
