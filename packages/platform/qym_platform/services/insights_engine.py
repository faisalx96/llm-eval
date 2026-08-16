"""Build category-oriented insight data from persisted evaluation results."""

from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Optional, Union

from qym_platform.db.models import Run, RunItem, RunItemScore, RunMetricSpec, Span
from qym_platform.services.approved_diagnoses import load_approved_diagnoses
from qym_platform.services.insights_data import InsightData, RootCauseData
from sqlalchemy.orm import Session

DEFAULT_MIN_ROOT_CAUSE_OCCURRENCES = 5
DEFAULT_MIN_CATEGORY_ITEMS = 3
_DEFAULT_PASS_THRESHOLD = 0.8
_UNSPECIFIED = "Unspecified"

_ItemKey = tuple[str, str]


@dataclass
class _RootCauseGroup:
    label: str
    item_keys: set[_ItemKey] = field(default_factory=set)


@dataclass
class _CategoryGroup:
    label: str
    item_keys: set[_ItemKey] = field(default_factory=set)
    root_causes: dict[str, _RootCauseGroup] = field(default_factory=dict)


def _clean_label(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _label_key(value: Any) -> str:
    text = unicodedata.normalize("NFKC", _clean_label(value)).casefold()
    return re.sub(r"[\W_]+", " ", text, flags=re.UNICODE).strip()


def _model_name(value: Any) -> str:
    name = _clean_label(value)
    return name.split("/", 1)[-1] if "/" in name else name


def _analysis_entries(
    item: RunItem,
    approved_entries: Sequence[Mapping[str, Any]] = (),
) -> list[tuple[str, str]]:
    """Return category/detail pairs from reviewer-approved diagnoses only."""
    del item  # The entries have already been resolved against this item.
    return [
        (
            _clean_label(entry.get("category")),
            _clean_label(entry.get("detail")),
        )
        for entry in approved_entries
        if _clean_label(entry.get("category"))
    ]


def _group_items(
    runs: Sequence[Run],
    items: Sequence[RunItem],
    approved_diagnoses: Mapping[tuple[str, str], Sequence[Mapping[str, Any]]],
) -> tuple[dict[str, _CategoryGroup], dict[_ItemKey, RunItem]]:
    runs_by_id = {run.id: run for run in runs}
    items_by_key: dict[_ItemKey, RunItem] = {}
    categories: dict[str, _CategoryGroup] = {}

    for item in items:
        if item.run_id not in runs_by_id:
            continue
        item_key = (item.run_id, item.item_id)
        items_by_key[item_key] = item
        for category, root_cause in _analysis_entries(
            item,
            approved_diagnoses.get(item_key, ()),
        ):
            category_key = _label_key(category)
            if not category_key:
                continue
            category_group = categories.setdefault(
                category_key,
                _CategoryGroup(label=_clean_label(category)),
            )
            category_group.item_keys.add(item_key)

            root_cause_key = _label_key(root_cause)
            root_cause_group = category_group.root_causes.setdefault(
                root_cause_key,
                _RootCauseGroup(label=_clean_label(root_cause)),
            )
            root_cause_group.item_keys.add(item_key)
    return categories, items_by_key


def _metric_result(
    item: RunItem,
    score: Optional[RunItemScore],
    spec: Optional[RunMetricSpec],
) -> Optional[str]:
    if item.error:
        return "fail"
    if score is None or score.score_numeric is None:
        return None

    threshold = (
        float(spec.pass_threshold)
        if spec is not None and spec.pass_threshold is not None
        else _DEFAULT_PASS_THRESHOLD
    )
    direction = _clean_label(spec.direction).lower() if spec is not None else ""
    value = float(score.score_numeric)
    success = (
        value <= threshold
        if direction in {"minimize", "lower", "lower_is_better"}
        else value >= threshold
    )
    return "success" if success else "fail"


def _span_kind(span: Span) -> str:
    attributes = span.attributes if isinstance(span.attributes, dict) else {}
    value = (
        attributes.get("openinference.span.kind")
        or attributes.get("ai.openinference.span.kind")
        or attributes.get("span.kind")
        or span.kind
        or ""
    )
    return str(value).upper().replace("-", "_").replace(" ", "_")


def _is_evaluation_root(span: Span) -> bool:
    attributes = span.attributes if isinstance(span.attributes, dict) else {}
    if str(attributes.get("qym.usage_scope") or "").strip().lower() == "metric":
        return True
    if _span_kind(span) == "EVALUATOR":
        return True
    name = _clean_label(span.name).lower()
    return name == "eval_metrics" or (
        _span_kind(span) != "TOOL" and name.startswith(("evaluator", "judge", "metric"))
    )


def _is_evaluation_span(
    span: Span,
    spans_by_id: Mapping[str, Span],
    evaluation_root_ids: set[str],
) -> bool:
    current: Optional[Span] = span
    visited: set[str] = set()
    while current is not None:
        if current.span_id in evaluation_root_ids:
            return True
        parent_id = current.parent_span_id
        if not parent_id or parent_id in visited:
            return False
        visited.add(parent_id)
        current = spans_by_id.get(parent_id)
    return False


def _tool_name(span: Span) -> str:
    attributes = span.attributes if isinstance(span.attributes, dict) else {}
    name = _clean_label(
        attributes.get("tool.name")
        or attributes.get("gen_ai.tool.name")
        or attributes.get("ai.tool.name")
        or span.name
    )
    if name.lower().startswith("tool:"):
        name = name.split(":", 1)[1].strip()
    return "" if name.lower() in {"", "tool", "unknown"} else name


def _load_tools_by_trace(
    db: Session,
    trace_keys: set[tuple[str, str]],
) -> dict[tuple[str, str], dict[str, int]]:
    if not trace_keys:
        return {}
    run_ids = {run_id for run_id, _ in trace_keys}
    trace_ids = {trace_id for _, trace_id in trace_keys}
    rows = (
        db.query(Span)
        .filter(Span.run_id.in_(run_ids), Span.trace_id.in_(trace_ids))
        .order_by(Span.run_id.asc(), Span.trace_id.asc(), Span.id.asc())
        .all()
    )
    spans_by_trace: dict[tuple[str, str], list[Span]] = defaultdict(list)
    for span in rows:
        key = (span.run_id, span.trace_id)
        if key in trace_keys:
            spans_by_trace[key].append(span)

    result: dict[tuple[str, str], dict[str, int]] = {}
    for trace_key, spans in spans_by_trace.items():
        spans_by_id = {span.span_id: span for span in spans}
        evaluation_root_ids = {
            span.span_id for span in spans if _is_evaluation_root(span)
        }
        counts: dict[str, int] = {}
        for span in spans:
            if _span_kind(span) != "TOOL" or _is_evaluation_span(
                span, spans_by_id, evaluation_root_ids
            ):
                continue
            name = _tool_name(span)
            if name:
                counts[name] = counts.get(name, 0) + 1
        result[trace_key] = counts
    return result


def _increment(values: dict[str, int], name: Any, amount: int = 1) -> None:
    label = _clean_label(name) or _UNSPECIFIED
    values[label] = values.get(label, 0) + amount


def _populate_data(
    target: Union[InsightData, RootCauseData],
    item_keys: set[_ItemKey],
    *,
    runs_by_id: Mapping[str, Run],
    items_by_key: Mapping[_ItemKey, RunItem],
    scores_by_item: Mapping[_ItemKey, Mapping[str, RunItemScore]],
    specs: Mapping[tuple[str, str], RunMetricSpec],
    tools_by_trace: Mapping[tuple[str, str], Mapping[str, int]],
    extra_data_by_run: Mapping[str, Mapping[str, Any]],
) -> None:
    contributing_run_ids: set[str] = set()
    for item_key in sorted(item_keys):
        item = items_by_key[item_key]
        run = runs_by_id[item.run_id]
        contributing_run_ids.add(run.id)
        _increment(target.models, _model_name(run.model))
        _increment(target.datasets, run.dataset)
        _increment(target.tasks, run.task)

        item_scores = scores_by_item.get(item_key, {})
        metric_names = list(
            dict.fromkeys(
                [
                    *(_clean_label(metric) for metric in (run.metrics or [])),
                    *sorted(item_scores),
                ]
            )
        )
        for metric_name in metric_names:
            if not metric_name:
                continue
            result = _metric_result(
                item,
                item_scores.get(metric_name),
                specs.get((run.id, metric_name)),
            )
            if result is None:
                continue
            metric = target.metrics.setdefault(metric_name, {"success": 0, "fail": 0})
            metric[result] += 1

        if item.trace_id:
            for tool_name, count in tools_by_trace.get(
                (run.id, item.trace_id), {}
            ).items():
                _increment(target.tools, tool_name, count)

    run_extra_data = {
        run_id: dict(extra_data_by_run[run_id])
        for run_id in sorted(contributing_run_ids)
        if run_id in extra_data_by_run
    }
    if run_extra_data:
        target.add_extra_data("runs", run_extra_data)


def build_insight_data(
    db: Session,
    project_id: str,
    *,
    run_ids: Optional[Sequence[str]] = None,
    minimum_root_cause_occurrences: int = DEFAULT_MIN_ROOT_CAUSE_OCCURRENCES,
    minimum_category_items: int = DEFAULT_MIN_CATEGORY_ITEMS,
    extra_data_by_run: Optional[Mapping[str, Mapping[str, Any]]] = None,
) -> list[InsightData]:
    """Build one insight object for each category that meets its threshold."""
    if minimum_root_cause_occurrences < 1:
        raise ValueError("minimum_root_cause_occurrences must be at least 1")
    if minimum_category_items < 1:
        raise ValueError("minimum_category_items must be at least 1")

    query = Run.active(db).filter(Run.project_id == project_id)
    if run_ids is not None:
        selected_run_ids = tuple(
            dict.fromkeys(
                _clean_label(run_id) for run_id in run_ids if _clean_label(run_id)
            )
        )
        if not selected_run_ids:
            return []
        query = query.filter(Run.id.in_(selected_run_ids))
    runs = query.order_by(Run.created_at.asc(), Run.id.asc()).all()
    if not runs:
        return []

    loaded_run_ids = [run.id for run in runs]
    items = (
        db.query(RunItem)
        .filter(RunItem.run_id.in_(loaded_run_ids))
        .order_by(RunItem.run_id.asc(), RunItem.index.asc(), RunItem.id.asc())
        .all()
    )
    approved_diagnoses = load_approved_diagnoses(db, loaded_run_ids, items)
    categories, items_by_key = _group_items(runs, items, approved_diagnoses)
    qualifying_categories = [
        group
        for group in categories.values()
        if len(group.item_keys) >= minimum_category_items
    ]
    if not qualifying_categories:
        return []

    routed_item_keys: set[_ItemKey] = set()
    for category in qualifying_categories:
        routed_item_keys.update(category.item_keys)

    score_rows = (
        db.query(RunItemScore).filter(RunItemScore.run_id.in_(loaded_run_ids)).all()
    )
    scores_by_item: dict[_ItemKey, dict[str, RunItemScore]] = defaultdict(dict)
    for score in score_rows:
        scores_by_item[(score.run_id, score.item_id)][score.metric_name] = score

    spec_rows = (
        db.query(RunMetricSpec).filter(RunMetricSpec.run_id.in_(loaded_run_ids)).all()
    )
    specs = {(spec.run_id, spec.metric_name): spec for spec in spec_rows}
    trace_keys = {
        (item.run_id, item.trace_id)
        for item_key, item in items_by_key.items()
        if item_key in routed_item_keys and item.trace_id
    }
    tools_by_trace = _load_tools_by_trace(db, trace_keys)
    runs_by_id = {run.id: run for run in runs}
    supplied_extra_data = extra_data_by_run or {}

    qualifying_categories.sort(
        key=lambda group: (-len(group.item_keys), group.label.casefold())
    )
    insights: list[InsightData] = []
    for category in qualifying_categories:
        insight = InsightData(category=category.label)
        direct_item_keys: set[_ItemKey] = set()
        root_cause_groups = sorted(
            category.root_causes.values(),
            key=lambda group: (-len(group.item_keys), group.label.casefold()),
        )
        for root_cause in root_cause_groups:
            if (
                root_cause.label
                and len(root_cause.item_keys) >= minimum_root_cause_occurrences
            ):
                root_cause_data = RootCauseData()
                _populate_data(
                    root_cause_data,
                    root_cause.item_keys,
                    runs_by_id=runs_by_id,
                    items_by_key=items_by_key,
                    scores_by_item=scores_by_item,
                    specs=specs,
                    tools_by_trace=tools_by_trace,
                    extra_data_by_run=supplied_extra_data,
                )
                insight.root_causes[root_cause.label] = root_cause_data
            else:
                direct_item_keys.update(root_cause.item_keys)

        _populate_data(
            insight,
            direct_item_keys,
            runs_by_id=runs_by_id,
            items_by_key=items_by_key,
            scores_by_item=scores_by_item,
            specs=specs,
            tools_by_trace=tools_by_trace,
            extra_data_by_run=supplied_extra_data,
        )
        insights.append(insight)
    return insights


__all__ = [
    "DEFAULT_MIN_CATEGORY_ITEMS",
    "DEFAULT_MIN_ROOT_CAUSE_OCCURRENCES",
    "build_insight_data",
]
