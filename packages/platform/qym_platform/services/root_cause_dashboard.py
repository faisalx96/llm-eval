"""Read-only project-wide root-cause dashboard aggregation.

The dashboard deliberately reads the same current metric-scoped analysis state
used by the run and review pages.  It does not call the analyzer, backfill
labels, or update review candidates.  The aggregation is kept here instead of
in the analyzer API so the reporting surface remains isolated from analysis
execution and persistence.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Iterable, Mapping, Sequence

from qym_platform.datetime_utils import to_api_timestamp
from qym_platform.db.models import (
    AuditLog,
    ReviewCorrection,
    RootCauseRevision,
    Run,
    RunItem,
    RunItemScore,
    RunMetricSpec,
)
from qym_platform.services.approved_diagnoses import load_approved_diagnoses
from sqlalchemy import or_
from sqlalchemy.orm import Session
from qym_platform.services.root_cause_categories import analysis_root_causes

DEFAULT_PASS_THRESHOLD = 0.8
MAX_CHANGE_EVENTS = 500
ALL_METRICS_SENTINEL = "__all__"


@dataclass(frozen=True)
class DashboardFilters:
    """Normalized dashboard filters supplied by the read-only API."""

    run_ids: tuple[str, ...] = ()
    task: tuple[str, ...] = ()
    dataset: tuple[str, ...] = ()
    model: tuple[str, ...] = ()
    metric: tuple[str, ...] = ()
    category: tuple[str, ...] = ()
    detail: tuple[str, ...] = ()
    outcome: tuple[str, ...] = ()
    source: tuple[str, ...] = ()
    review_status: tuple[str, ...] = ()
    from_date: datetime | None = None
    to_date: datetime | None = None


@dataclass
class _Snapshot:
    runs: list[Run] = field(default_factory=list)
    occurrences: list[dict[str, Any]] = field(default_factory=list)
    score_stats: dict[tuple[str, str], dict[str, Any]] = field(default_factory=dict)
    metric_specs: dict[tuple[str, str], RunMetricSpec] = field(default_factory=dict)
    changes: list[dict[str, Any]] = field(default_factory=list)
    failed_pairs: set[tuple[str, str]] = field(default_factory=set)


def normalize_label(value: Any) -> str:
    """Normalize only typography for safe grouping; never perform semantic merging."""

    text = unicodedata.normalize("NFKC", str(value or "")).strip()
    text = re.sub(r"[\W_]+", " ", text, flags=re.UNICODE)
    return re.sub(r"\s+", " ", text).strip().casefold()


def _display_label(value: Any, fallback: str = "Unspecified") -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).strip()
    return re.sub(r"\s+", " ", text) or fallback


def _display_categories(state: Mapping[str, Any]) -> str:
    categories = analysis_root_causes(state)
    return ", ".join(categories)


def _unique(values: Iterable[Any]) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return tuple(result)


def _enum_value(value: Any) -> str:
    return str(getattr(value, "value", value) or "").strip()


def _model_name(value: Any) -> str:
    text = str(value or "").strip()
    return text.split("/", 1)[-1] if "/" in text else text


def _run_name(run: Run) -> str:
    config = run.run_config if isinstance(run.run_config, dict) else {}
    return str(config.get("run_name") or run.external_run_id or run.id)


def _run_timestamp(run: Run) -> datetime | None:
    return run.started_at or run.created_at or run.updated_at


def _metric_spec_payload(spec: RunMetricSpec | None) -> dict[str, Any]:
    direction = _direction(spec)
    return {
        "direction": direction,
        "score_type": str(spec.score_type or "") if spec else "",
        "pass_threshold": (
            float(spec.pass_threshold)
            if spec and spec.pass_threshold is not None
            else DEFAULT_PASS_THRESHOLD
        ),
        "unit": str(spec.unit or "") if spec else "",
        "precision": (
            int(spec.precision) if spec and spec.precision is not None else None
        ),
        "sample_reducer": str(spec.sample_reducer or "mean") if spec else "mean",
        "run_reducer": str(spec.run_reducer or "mean") if spec else "mean",
    }


def _direction(spec: RunMetricSpec | None) -> str:
    value = str(spec.direction or "maximize").strip().lower() if spec else "maximize"
    return (
        "minimize" if value in {"minimize", "lower", "lower_is_better"} else "maximize"
    )


def _pass_threshold(spec: RunMetricSpec | None) -> float:
    return (
        float(spec.pass_threshold)
        if spec and spec.pass_threshold is not None
        else DEFAULT_PASS_THRESHOLD
    )


def _score_outcome(
    item: RunItem, score: RunItemScore | None, spec: RunMetricSpec | None
) -> str:
    if item.error:
        return "error"
    if score is None or score.score_numeric is None:
        return "unscored"
    value = float(score.score_numeric)
    threshold = _pass_threshold(spec)
    passed = (
        value <= threshold if _direction(spec) == "minimize" else value >= threshold
    )
    return "passed" if passed else "failed"


def _score_value(item: RunItem, score: RunItemScore | None) -> float | None:
    if item.error:
        # Match the main dashboard's run-score semantics: errors contribute zero.
        return 0.0
    if score is None or score.score_numeric is None:
        return None
    return float(score.score_numeric)


def _metric_analysis_entries(
    run: Run,
    item: RunItem,
    approved_entries: Sequence[Mapping[str, Any]] = (),
) -> list[dict[str, Any]]:
    """Return only reviewer-approved diagnosis entries for one item."""

    metadata = item.item_metadata if isinstance(item.item_metadata, dict) else {}
    default_metric = str(metadata.get("root_cause_metric_name") or "").strip()
    if not default_metric:
        metrics = list(run.metrics or [])
        default_metric = metrics[0] if len(metrics) == 1 else "unscoped"

    entries: list[dict[str, Any]] = []
    for approved in approved_entries:
        category = _display_label(approved.get("category"), "")
        if not category:
            continue
        entries.append(
            {
                "metric_name": str(approved.get("metric_name") or default_metric),
                "category": category,
                "detail": _display_label(approved.get("detail"), "Unspecified"),
                "note": str(approved.get("note") or "").strip(),
                "confidence": approved.get("confidence"),
                "source": str(approved.get("source") or "unknown").strip().lower(),
                "review_status": "approved",
            }
        )
    return entries


def _latest_review_statuses(
    db: Session, run_ids: Sequence[str]
) -> dict[tuple[str, str, str], str]:
    if not run_ids:
        return {}
    rows = (
        db.query(ReviewCorrection)
        .filter(
            ReviewCorrection.run_id.in_(run_ids),
            ReviewCorrection.is_active.is_(True),
        )
        .order_by(ReviewCorrection.created_at.desc(), ReviewCorrection.id.desc())
        .all()
    )
    result: dict[tuple[str, str, str], str] = {}
    for row in rows:
        key = (row.run_id, row.item_id, str(row.metric_name or "").strip())
        if key not in result:
            result[key] = _enum_value(row.status) or "unreviewed"
    return result


def _load_changes(db: Session, run_ids: Sequence[str]) -> list[dict[str, Any]]:
    if not run_ids:
        return []
    events: list[dict[str, Any]] = []
    revisions = (
        db.query(RootCauseRevision)
        .filter(RootCauseRevision.run_id.in_(run_ids))
        .order_by(RootCauseRevision.created_at.desc(), RootCauseRevision.id.desc())
        .limit(MAX_CHANGE_EVENTS)
        .all()
    )
    for revision in revisions:
        before = (
            revision.before_state if isinstance(revision.before_state, dict) else {}
        )
        after = revision.after_state if isinstance(revision.after_state, dict) else {}
        before_category = _display_categories(before)
        after_category = _display_categories(after)
        events.append(
            {
                "id": f"revision:{revision.id}",
                "run_id": revision.run_id,
                "item_id": revision.item_id,
                "metric_name": "",
                "before_category": before_category,
                "category": after_category,
                "change": (
                    "cleared"
                    if before_category and not after_category
                    else ("new" if not before_category else "changed")
                ),
                "source": str(revision.actor_source or "system"),
                "timestamp": to_api_timestamp(revision.created_at),
            }
        )

    audit_scope = [AuditLog.entity_id.like(f"{run_id}:%") for run_id in run_ids]
    audit_rows = (
        db.query(AuditLog)
        .filter(
            AuditLog.entity_type == "run_item_metric_analysis",
            or_(*audit_scope),
        )
        .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        .limit(MAX_CHANGE_EVENTS)
        .all()
    )
    selected = set(run_ids)
    for row in audit_rows:
        entity_id = str(row.entity_id or "")
        run_id = next(
            (
                candidate
                for candidate in selected
                if entity_id.startswith(candidate + ":")
            ),
            None,
        )
        if not run_id:
            continue
        parts = entity_id.split(":")
        metric_name = parts[-1] if len(parts) >= 3 else ""
        item_id = ":".join(parts[1:-1]) if len(parts) >= 3 else ""
        before = row.before if isinstance(row.before, dict) else {}
        after = row.after if isinstance(row.after, dict) else {}
        before_category = _display_categories(before)
        after_category = _display_categories(after)
        events.append(
            {
                "id": f"audit:{row.id}",
                "run_id": run_id,
                "item_id": item_id,
                "metric_name": metric_name,
                "before_category": before_category,
                "category": after_category,
                "change": (
                    "cleared"
                    if before_category and not after_category
                    else ("new" if not before_category else "changed")
                ),
                "source": "human",
                "timestamp": to_api_timestamp(row.created_at),
            }
        )
    events.sort(key=lambda event: event.get("timestamp") or "", reverse=True)
    return events[:MAX_CHANGE_EVENTS]


def _run_payload(run: Run) -> dict[str, Any]:
    timestamp = _run_timestamp(run)
    return {
        "run_id": run.id,
        "run_name": _run_name(run),
        "external_run_id": str(run.external_run_id or ""),
        "task": str(run.task or ""),
        "dataset": str(run.dataset or ""),
        "model": _model_name(run.model),
        "status": _enum_value(run.status),
        "timestamp": to_api_timestamp(timestamp),
        "metrics": [str(metric) for metric in (run.metrics or [])],
    }


def _matches(values: Sequence[str], value: str) -> bool:
    return not values or value in values


def _load_snapshot(
    db: Session,
    project_id: str,
    filters: DashboardFilters,
    *,
    include_changes: bool = True,
) -> _Snapshot:
    query = Run.active(db).filter(Run.project_id == project_id)
    if filters.run_ids:
        query = query.filter(Run.id.in_(filters.run_ids))
    if filters.task:
        query = query.filter(Run.task.in_(filters.task))
    if filters.dataset:
        query = query.filter(Run.dataset.in_(filters.dataset))
    if filters.from_date:
        query = query.filter(Run.created_at >= filters.from_date)
    if filters.to_date:
        query = query.filter(Run.created_at <= filters.to_date)
    runs = query.order_by(Run.created_at.desc(), Run.id.desc()).all()
    if filters.model:
        runs = [run for run in runs if _model_name(run.model) in filters.model]
    snapshot = _Snapshot(runs=runs)
    run_ids = [run.id for run in runs]
    if not run_ids:
        return snapshot

    item_rows = (
        db.query(RunItem)
        .filter(RunItem.run_id.in_(run_ids))
        .order_by(RunItem.run_id.asc(), RunItem.index.asc(), RunItem.id.asc())
        .all()
    )
    score_rows = db.query(RunItemScore).filter(RunItemScore.run_id.in_(run_ids)).all()
    scores: dict[tuple[str, str, str], RunItemScore] = {
        (row.run_id, row.item_id, row.metric_name): row for row in score_rows
    }
    spec_rows = db.query(RunMetricSpec).filter(RunMetricSpec.run_id.in_(run_ids)).all()
    snapshot.metric_specs = {(row.run_id, row.metric_name): row for row in spec_rows}
    review_statuses = _latest_review_statuses(db, run_ids)
    approved_diagnoses = load_approved_diagnoses(db, run_ids, item_rows)
    runs_by_id = {run.id: run for run in runs}
    items_by_run: dict[str, list[RunItem]] = defaultdict(list)
    for item in item_rows:
        items_by_run[item.run_id].append(item)

    for run in runs:
        metrics = list(run.metrics or [])
        for item in items_by_run.get(run.id, []):
            for metric in metrics:
                score = scores.get((run.id, item.item_id, str(metric)))
                spec = snapshot.metric_specs.get((run.id, str(metric)))
                if _score_outcome(item, score, spec) in {"failed", "error"}:
                    snapshot.failed_pairs.add((run.id, item.item_id))
                stat = snapshot.score_stats.setdefault(
                    (run.id, str(metric)),
                    {"sum": 0.0, "scored_count": 0, "error_count": 0, "item_count": 0},
                )
                stat["item_count"] += 1
                if item.error:
                    stat["error_count"] += 1
                elif score is not None and score.score_numeric is not None:
                    stat["sum"] += float(score.score_numeric)
                    stat["scored_count"] += 1
            if item.error and not metrics:
                snapshot.failed_pairs.add((run.id, item.item_id))

            entries = _metric_analysis_entries(
                run,
                item,
                approved_diagnoses.get((run.id, item.item_id), ()),
            )
            for entry in entries:
                metric_name = str(entry["metric_name"] or "unscoped")
                if not _matches(filters.metric, metric_name):
                    continue
                category = str(entry["category"] or "Unspecified")
                detail = str(entry["detail"] or "Unspecified")
                category_key = normalize_label(category)
                detail_key = normalize_label(detail)
                if filters.category and not any(
                    normalize_label(value) == category_key for value in filters.category
                ):
                    continue
                if filters.detail and not any(
                    normalize_label(value) == detail_key for value in filters.detail
                ):
                    continue
                score = scores.get((run.id, item.item_id, metric_name))
                spec = snapshot.metric_specs.get((run.id, metric_name))
                outcome = _score_outcome(item, score, spec)
                source = (
                    str(entry.get("source") or "unknown").strip().lower() or "unknown"
                )
                review_status = str(entry.get("review_status") or "").strip().lower()
                if not review_status:
                    review_status = review_statuses.get(
                        (run.id, item.item_id, metric_name)
                    )
                if review_status is None:
                    review_status = review_statuses.get(
                        (run.id, item.item_id, ""), "unreviewed"
                    )
                if (
                    not _matches(filters.outcome, outcome)
                    or not _matches(filters.source, source)
                    or not _matches(filters.review_status, review_status)
                ):
                    continue
                snapshot.occurrences.append(
                    {
                        "run_id": run.id,
                        "run_name": _run_name(run),
                        "run_timestamp": to_api_timestamp(_run_timestamp(run)),
                        "task": str(run.task or ""),
                        "dataset": str(run.dataset or ""),
                        "model": _model_name(run.model),
                        "item_id": item.item_id,
                        "item_index": int(item.index or 0),
                        "metric_name": metric_name,
                        "category": category,
                        "category_key": category_key,
                        "detail": detail,
                        "detail_key": detail_key,
                        "note": entry.get("note") or "",
                        "confidence": entry.get("confidence"),
                        "source": source,
                        "review_status": review_status,
                        "outcome": outcome,
                        "score": _score_value(item, score),
                    }
                )

    # Changes are project-wide by default; narrow them to the run filters above.
    if include_changes:
        snapshot.changes = _load_changes(db, list(runs_by_id))
    return snapshot


def _average(values: Iterable[float | None]) -> float | None:
    numbers = [float(value) for value in values if value is not None]
    return sum(numbers) / len(numbers) if numbers else None


def _failure_rate(rows: Sequence[Mapping[str, Any]]) -> float:
    if not rows:
        return 0.0
    failures = sum(row.get("outcome") in {"failed", "error"} for row in rows)
    return failures / len(rows)


def _sorted_counts(rows: Iterable[Mapping[str, Any]], key: str) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        value = str(row.get(key) or "Unspecified")
        identity = normalize_label(value)
        current = grouped.setdefault(identity, {"value": value, "count": 0})
        current["count"] += 1
    return sorted(
        grouped.values(), key=lambda item: (-item["count"], item["value"].casefold())
    )


def _group_by(
    rows: Sequence[dict[str, Any]], key: str
) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[normalize_label(row.get(key))].append(row)
    return grouped


def _run_score_payload(
    run: Run,
    metric_name: str,
    score_stats: Mapping[tuple[str, str], Mapping[str, Any]],
    spec: RunMetricSpec | None,
) -> dict[str, Any]:
    stat = score_stats.get((run.id, metric_name), {})
    denominator = int(stat.get("scored_count", 0) or 0) + int(
        stat.get("error_count", 0) or 0
    )
    return {
        "run_id": run.id,
        "metric_name": metric_name,
        "average": (float(stat.get("sum", 0.0)) / denominator) if denominator else None,
        "scored_count": int(stat.get("scored_count", 0) or 0),
        "error_count": int(stat.get("error_count", 0) or 0),
        "item_count": int(stat.get("item_count", 0) or 0),
        "spec": _metric_spec_payload(spec),
    }


def _category_group(rows: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped = _group_by(rows, "category")
    result: list[dict[str, Any]] = []
    total = len(rows)
    for _, group in grouped.items():
        first = group[0]
        details = _sorted_counts(group, "detail")
        result.append(
            {
                "category": first["category"],
                "count": len(group),
                "share": len(group) / total if total else 0.0,
                "affected_items": len(
                    {(row["run_id"], row["item_id"]) for row in group}
                ),
                "run_count": len({row["run_id"] for row in group}),
                "metric_count": len({row["metric_name"] for row in group}),
                "metrics": _sorted_counts(group, "metric_name"),
                "details": details,
                "average_score": _average(row.get("score") for row in group),
                "failure_rate": _failure_rate(group),
            }
        )
    return sorted(
        result, key=lambda item: (-item["count"], item["category"].casefold())
    )


def _metric_group(rows: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped = _group_by(rows, "metric_name")
    result: list[dict[str, Any]] = []
    for _, group in grouped.items():
        first = group[0]
        result.append(
            {
                "metric_name": first["metric_name"],
                "count": len(group),
                "affected_items": len(
                    {(row["run_id"], row["item_id"]) for row in group}
                ),
                "run_count": len({row["run_id"] for row in group}),
                "categories": _sorted_counts(group, "category"),
                "average_score": _average(row.get("score") for row in group),
                "failure_rate": _failure_rate(group),
            }
        )
    return sorted(
        result, key=lambda item: (-item["count"], item["metric_name"].casefold())
    )


def _run_group(
    runs: Sequence[Run],
    rows: Sequence[dict[str, Any]],
    snapshot: _Snapshot,
    score_metric: str | None,
) -> list[dict[str, Any]]:
    grouped = _group_by(rows, "run_id")
    result: list[dict[str, Any]] = []
    for run in runs:
        group = grouped.get(normalize_label(run.id), [])
        score = None
        if score_metric:
            score = _run_score_payload(
                run,
                score_metric,
                snapshot.score_stats,
                snapshot.metric_specs.get((run.id, score_metric)),
            )
        result.append(
            {
                **_run_payload(run),
                "occurrence_count": len(group),
                "affected_items": len({row["item_id"] for row in group}),
                "categories": _sorted_counts(group, "category"),
                "metrics": _sorted_counts(group, "metric_name"),
                "average_score": _average(row.get("score") for row in group),
                "failure_rate": _failure_rate(group),
                "score": score,
            }
        )
    return result


def _facets(snapshot: _Snapshot) -> dict[str, Any]:
    runs = snapshot.runs
    rows = snapshot.occurrences
    run_facets = []
    for run in runs:
        run_facets.append(_run_payload(run))
    return {
        "runs": run_facets,
        "tasks": sorted({str(run.task or "") for run in runs if str(run.task or "")}),
        "datasets": sorted(
            {str(run.dataset or "") for run in runs if str(run.dataset or "")}
        ),
        "models": sorted(
            {_model_name(run.model) for run in runs if _model_name(run.model)}
        ),
        "metrics": sorted(
            {str(row["metric_name"]) for row in rows if row.get("metric_name")}
        ),
        "score_metrics": sorted(
            {
                str(metric)
                for run in runs
                for metric in (run.metrics or [])
                if str(metric)
            }
        ),
        "categories": _sorted_counts(rows, "category"),
        "details": _sorted_counts(rows, "detail"),
        "outcomes": _sorted_counts(rows, "outcome"),
        "sources": _sorted_counts(rows, "source"),
        "review_statuses": _sorted_counts(rows, "review_status"),
    }


def _choose_score_metric(
    snapshot: _Snapshot, requested: str | None = None
) -> str | None:
    if requested:
        return requested
    counts = Counter(
        row["metric_name"]
        for row in snapshot.occurrences
        if row.get("metric_name") != "unscoped"
    )
    if counts:
        return counts.most_common(1)[0][0]
    for run in snapshot.runs:
        if run.metrics:
            return str(run.metrics[0])
    return None


def build_dashboard_payload(
    db: Session,
    project: Any,
    filters: DashboardFilters,
    *,
    score_metric: str | None = None,
) -> dict[str, Any]:
    snapshot = _load_snapshot(db, project.id, filters)
    selected_metric = _choose_score_metric(snapshot, score_metric)
    rows = snapshot.occurrences
    failed_pairs = snapshot.failed_pairs
    diagnosed_failed_pairs = {
        (row["run_id"], row["item_id"])
        for row in rows
        if row["outcome"] in {"failed", "error"}
    }
    category_groups = _category_group(rows)
    most_repeated = category_groups[0] if category_groups else None
    summary = {
        "diagnosis_occurrences": len(rows),
        "affected_run_item_pairs": len(
            {(row["run_id"], row["item_id"]) for row in rows}
        ),
        "runs_with_diagnoses": len({row["run_id"] for row in rows}),
        "categories": len(category_groups),
        "most_repeated_category": most_repeated,
        "failure_coverage": {
            "diagnosed_failed_pairs": len(diagnosed_failed_pairs),
            "failed_pairs": len(failed_pairs),
            "rate": (
                len(diagnosed_failed_pairs) / len(failed_pairs) if failed_pairs else 0.0
            ),
        },
        "selected_score_metric": selected_metric,
    }
    score_payload = {
        "metric_name": selected_metric,
        "runs": (
            [
                _run_score_payload(
                    run,
                    selected_metric,
                    snapshot.score_stats,
                    snapshot.metric_specs.get((run.id, selected_metric)),
                )
                for run in snapshot.runs
            ]
            if selected_metric
            else []
        ),
    }
    trend = []
    for run in sorted(
        snapshot.runs,
        key=lambda current: (_run_timestamp(current) or datetime.min, current.id),
    ):
        run_rows = [row for row in rows if row["run_id"] == run.id]
        score = next(
            (item for item in score_payload["runs"] if item["run_id"] == run.id), None
        )
        trend.append(
            {
                "run_id": run.id,
                "run_name": _run_name(run),
                "timestamp": to_api_timestamp(_run_timestamp(run)),
                "occurrence_count": len(run_rows),
                "categories": _sorted_counts(run_rows, "category"),
                "score": score,
            }
        )
    return {
        "project": {"id": project.id, "slug": project.slug, "name": project.name},
        "filters": {
            "run_ids": list(filters.run_ids),
            "task": list(filters.task),
            "dataset": list(filters.dataset),
            "model": list(filters.model),
            "metric": list(filters.metric),
            "category": list(filters.category),
            "detail": list(filters.detail),
            "outcome": list(filters.outcome),
            "source": list(filters.source),
            "review_status": list(filters.review_status),
            "from_date": to_api_timestamp(filters.from_date),
            "to_date": to_api_timestamp(filters.to_date),
        },
        "facets": _facets(snapshot),
        "summary": summary,
        "scores": score_payload,
        "groups": {
            "by_run": _run_group(snapshot.runs, rows, snapshot, selected_metric),
            "by_metric": _metric_group(rows),
            "by_category": category_groups,
        },
        "trends": {"runs": trend, "changes": snapshot.changes},
    }


def build_occurrences_payload(
    db: Session,
    project: Any,
    filters: DashboardFilters,
    *,
    limit: int = 100,
    offset: int = 0,
) -> dict[str, Any]:
    snapshot = _load_snapshot(db, project.id, filters, include_changes=False)
    rows = snapshot.occurrences
    page = rows[offset : offset + limit]
    return {
        "project": {"id": project.id, "slug": project.slug, "name": project.name},
        "total": len(rows),
        "offset": offset,
        "limit": limit,
        "occurrences": page,
    }


def _comparison_matrix(
    rows: Sequence[dict[str, Any]],
    run_ids: Sequence[str],
    group_key: str,
) -> list[dict[str, Any]]:
    grouped = _group_by(rows, group_key)
    run_totals = Counter(row["run_id"] for row in rows)
    matrix: list[dict[str, Any]] = []
    for _, group_rows in grouped.items():
        label = group_rows[0][group_key]
        per_run: dict[str, dict[str, Any]] = {}
        for run_id in run_ids:
            run_rows = [row for row in group_rows if row["run_id"] == run_id]
            per_run[run_id] = {
                "count": len(run_rows),
                "share": (
                    len(run_rows) / run_totals[run_id] if run_totals[run_id] else 0.0
                ),
                "average_score": _average(row.get("score") for row in run_rows),
                "failure_rate": _failure_rate(run_rows),
            }
        matrix.append(
            {
                group_key: label,
                "runs": per_run,
                "total_count": len(group_rows),
            }
        )
    return sorted(
        matrix,
        key=lambda item: (-item["total_count"], str(item[group_key]).casefold()),
    )


def _comparison_status(
    raw_delta: float | None, direction: str, tolerance: float
) -> str:
    if raw_delta is None or abs(raw_delta) <= tolerance:
        return "tied"
    improved = raw_delta > 0 if direction == "maximize" else raw_delta < 0
    return "improved" if improved else "regressed"


def build_compare_payload(
    db: Session,
    project: Any,
    run_ids: Sequence[str],
    filters: DashboardFilters,
    *,
    score_metric: str | None = None,
    baseline_run_id: str | None = None,
) -> dict[str, Any]:
    selected_ids = _unique(run_ids)
    if len(selected_ids) < 2 or len(selected_ids) > 8:
        raise ValueError("Select between 2 and 8 runs to compare")
    scoped_filters = DashboardFilters(
        run_ids=selected_ids,
        task=filters.task,
        dataset=filters.dataset,
        model=filters.model,
        metric=filters.metric,
        category=filters.category,
        detail=filters.detail,
        outcome=filters.outcome,
        source=filters.source,
        review_status=filters.review_status,
        from_date=filters.from_date,
        to_date=filters.to_date,
    )
    snapshot = _load_snapshot(db, project.id, scoped_filters)
    if len(snapshot.runs) != len(selected_ids):
        raise ValueError("One or more selected runs is not available in this project")
    all_metrics_requested = score_metric == ALL_METRICS_SENTINEL
    selected_metric = (
        None if all_metrics_requested else _choose_score_metric(snapshot, score_metric)
    )
    comparison_rows = [
        row
        for row in snapshot.occurrences
        if all_metrics_requested
        or not selected_metric
        or row.get("metric_name") == selected_metric
    ]
    baseline = baseline_run_id if baseline_run_id in selected_ids else selected_ids[0]
    run_map = {run.id: run for run in snapshot.runs}
    score_rows: list[dict[str, Any]] = []
    baseline_score: float | None = None
    baseline_direction = "maximize"
    compatibility = {"comparable": True, "reason": "", "missing_run_ids": []}
    if all_metrics_requested:
        compatibility = {
            "comparable": False,
            "reason": "Select a specific metric to compare scores",
            "missing_run_ids": [],
        }
    if selected_metric:
        baseline_spec = snapshot.metric_specs.get((baseline, selected_metric))
        baseline_direction = _direction(baseline_spec)
        missing_run_ids = [
            run_id
            for run_id in selected_ids
            if selected_metric not in (run_map[run_id].metrics or [])
            and (run_id, selected_metric) not in snapshot.score_stats
        ]
        semantic_keys = {
            (
                _direction(snapshot.metric_specs.get((run_id, selected_metric))),
                (
                    str(snapshot.metric_specs.get((run_id, selected_metric)).unit or "")
                    if snapshot.metric_specs.get((run_id, selected_metric))
                    else ""
                ),
                (
                    str(
                        snapshot.metric_specs.get((run_id, selected_metric)).score_type
                        or ""
                    )
                    if snapshot.metric_specs.get((run_id, selected_metric))
                    else ""
                ),
            )
            for run_id in selected_ids
        }
        if missing_run_ids or len(semantic_keys) > 1:
            compatibility = {
                "comparable": False,
                "reason": (
                    "Metric is not available in every selected run"
                    if missing_run_ids
                    else "Metric direction, unit, or score type differs between runs"
                ),
                "missing_run_ids": missing_run_ids,
            }
        baseline_score_payload = _run_score_payload(
            run_map[baseline], selected_metric, snapshot.score_stats, baseline_spec
        )
        baseline_score = baseline_score_payload["average"]
        for run_id in selected_ids:
            spec = snapshot.metric_specs.get((run_id, selected_metric))
            score = _run_score_payload(
                run_map[run_id], selected_metric, snapshot.score_stats, spec
            )
            raw_delta = (
                score["average"] - baseline_score
                if score["average"] is not None and baseline_score is not None
                else None
            )
            direction = _direction(spec)
            precision = spec.precision if spec and spec.precision is not None else None
            tolerance = (
                (10 ** (-int(precision))) / 2
                if precision is not None and int(precision) >= 0
                else 1e-9
            )
            score_rows.append(
                {
                    **score,
                    "raw_delta": raw_delta,
                    "improvement_delta": (
                        -raw_delta
                        if direction == "minimize" and raw_delta is not None
                        else raw_delta
                    ),
                    "comparison_status": (
                        "baseline"
                        if run_id == baseline
                        and compatibility["comparable"]
                        and score["average"] is not None
                        else (
                            "unavailable"
                            if not compatibility["comparable"]
                            or score["average"] is None
                            else _comparison_status(raw_delta, direction, tolerance)
                        )
                    ),
                    "comparison_state": (
                        "comparable" if compatibility["comparable"] else "unavailable"
                    ),
                }
            )

    category_matrix = _comparison_matrix(comparison_rows, selected_ids, "category")
    metric_matrix = _comparison_matrix(comparison_rows, selected_ids, "metric_name")
    total_occurrences = len(comparison_rows)
    run_summary = []
    for run_id in selected_ids:
        run_rows = [row for row in comparison_rows if row["run_id"] == run_id]
        run_summary.append(
            {
                "run_id": run_id,
                "run_name": _run_name(run_map[run_id]),
                "count": len(run_rows),
                "share": (
                    len(run_rows) / total_occurrences if total_occurrences else 0.0
                ),
                "average_score": _average(row.get("score") for row in run_rows),
                "failure_rate": _failure_rate(run_rows),
            }
        )

    best_run_id = None
    if score_rows:
        comparable = [row for row in score_rows if row.get("average") is not None]
        if comparable and compatibility["comparable"]:
            best_run_id = (
                max(comparable, key=lambda row: row["average"])["run_id"]
                if baseline_direction == "maximize"
                else min(comparable, key=lambda row: row["average"])["run_id"]
            )
    return {
        "project": {"id": project.id, "slug": project.slug, "name": project.name},
        "run_ids": list(selected_ids),
        "baseline_run_id": baseline,
        "score_metric": (
            ALL_METRICS_SENTINEL if all_metrics_requested else selected_metric
        ),
        "score_direction": baseline_direction,
        "score_compatibility": compatibility,
        "runs": [_run_payload(run_map[run_id]) for run_id in selected_ids],
        "score_comparison": score_rows,
        "category_matrix": category_matrix,
        "metric_matrix": metric_matrix,
        "run_summary": run_summary,
        "summary": {
            "occurrences": len(comparison_rows),
            "categories": len(category_matrix),
            "best_run_id": best_run_id,
            "changes": len(snapshot.changes),
        },
        "changes": snapshot.changes,
    }
