"""Deterministic, read-only candidate relationship analysis.

This module intentionally has no dependency on the analyzer or an LLM client.
It builds one observation for every stable ``run × item × metric`` execution,
derives a small allow-listed set of safe predicates, and evaluates target
relationships with Fisher exact tests and project-wide Benjamini--Hochberg
correction.

The implementation keeps the statistical representation separate from the
presentation representation.  Raw identifiers, trace payloads, prompts,
outputs, notes, and diagnosis provenance can be used to locate evidence but
never become candidate factors or returned relationship values.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import math
import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Iterable, Mapping, Optional, Sequence

from scipy.stats import fisher_exact
from sqlalchemy.orm import Session

from qym_platform.datetime_utils import to_api_timestamp, utc_now_naive
from qym_platform.db.models import (
    DatasetItem,
    DatasetVersion,
    Run,
    RunItem,
    RunItemAttempt,
    RunItemScore,
    RunMetricSpec,
    RunTraceAggregate,
    RunWorkflowStatus,
    Span,
)


SCHEMA_VERSION = 1
POLICY_VERSION = "candidate-relationships-v1"
CATEGORY_THRESHOLD = 10
DETAIL_THRESHOLD = 10
MIN_SUPPORT = 10
MIN_COVERAGE = 0.50
MAX_COVERAGE_BIAS = 0.10
MAX_DIAGNOSIS_COVERAGE_BIAS = 0.20
MIN_RATE_DIFFERENCE = 0.10
MIN_RELATIVE_RISK = 1.50
MAX_RELATIVE_RISK = 0.67
MAX_ARITY = 3

_LIVE_STATUSES = {
    RunWorkflowStatus.DRAFT.value,
    RunWorkflowStatus.PENDING.value,
    RunWorkflowStatus.RUNNING.value,
}
_FAILURE_OUTCOMES = {"failed", "error"}
_SENSITIVE_KEY_RE = re.compile(
    r"(?:^|[_ .-])(id|ids|uuid|key|token|secret|password|passwd|prompt|message|messages|"
    r"input|output|expected|actual|answer|note|notes|reason|reasoning|error|exception|"
    r"trace|span|url|uri|content|text|raw|metadata_json)(?:$|[_ .-])",
    re.IGNORECASE,
)
_SECRET_VALUE_RE = re.compile(
    r"(?:sk-[A-Za-z0-9_-]{12,}|bearer\s+[A-Za-z0-9._~-]{12,}|"
    r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9._~-]{10,})",
    re.IGNORECASE,
)
_SAFE_NAME_RE = re.compile(r"^[^\x00-\x1f\x7f]{1,120}$")
_ERROR_CLASS_RE = re.compile(r"([A-Za-z][A-Za-z0-9]*(?:Error|Exception|Failure|Timeout))")
_MODEL_ATTR_KEYS = (
    "llm.model_name",
    "llm.model",
    "gen_ai.request.model",
    "gen_ai.response.model",
    "model_name",
)
_TOOL_ATTR_KEYS = (
    "gen_ai.tool.name",
    "tool.name",
    "tool_name",
    "function.name",
)
_DIAGNOSIS_KEYS = {
    "root_cause",
    "root_cause_detail",
    "root_cause_note",
    "root_cause_source",
    "root_cause_confidence",
    "root_cause_metric_name",
    "analysis_error",
    "solution",
    "solution_note",
    "solution_source",
    "confidence",
    "review_status",
    "analyzer_model",
    "analyzer_provenance",
    "analysis_timestamp",
}
_UNSTABLE_RUN_CONFIG_KEYS = {
    "run_name",
    "external_run_id",
    "run_id",
}
_TRACE_NUMERIC_KEYS = {
    "tokens": "trace.tokens",
    "cost": "trace.cost",
    "llm_calls": "trace.llm_calls",
    "tool_calls": "trace.tool_calls",
    "tool_errors": "trace.tool_errors",
    "malformed_tool_calls": "trace.malformed_tool_calls",
    "noisy_reasoning": "trace.noisy_reasoning",
    "provider_errors": "trace.provider_errors",
    "reasoning_tokens": "trace.reasoning_tokens",
}
_TRACE_LATENCY_KEYS = {
    "avg_llm_ms": "trace.avg_llm_ms",
    "avg_tool_ms": "trace.avg_tool_ms",
    "avg_retriever_ms": "trace.avg_retriever_ms",
    "avg_evaluator_ms": "trace.avg_evaluator_ms",
    "avg_top_level_chain_ms": "trace.avg_top_level_chain_ms",
}


def normalize_label(value: Any) -> str:
    """Normalize typography without semantically merging labels."""

    text = unicodedata.normalize("NFKC", str(value or "")).strip()
    text = re.sub(r"[\W_]+", " ", text, flags=re.UNICODE)
    return re.sub(r"\s+", " ", text).strip().casefold()


def _display_label(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).strip()
    return re.sub(r"\s+", " ", text)


def _enum_value(value: Any) -> str:
    return str(getattr(value, "value", value) or "").strip()


def _is_finite_number(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError, OverflowError):
        return False


def _float(value: Any) -> float | None:
    return float(value) if _is_finite_number(value) else None


def _safe_text(value: Any, *, max_length: int = 120) -> str | None:
    if not isinstance(value, str):
        return None
    text = unicodedata.normalize("NFKC", value).strip()
    if not text or len(text) > max_length or not _SAFE_NAME_RE.match(text):
        return None
    if _SECRET_VALUE_RE.search(text):
        return None
    if text.lower().startswith(("http://", "https://", "file://")):
        return None
    return text


def _safe_metadata_key(key: Any) -> bool:
    text = str(key or "").strip()
    if not text or len(text) > 80:
        return False
    return not bool(_SENSITIVE_KEY_RE.search(text))


def _safe_scalar(value: Any, *, max_length: int = 120) -> Any:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value) if isinstance(value, float) else int(value)
    return _safe_text(value, max_length=max_length)


def _key_part(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).strip().casefold()
    return re.sub(r"[^a-z0-9]+", "_", text).strip("_") or "value"


def _humanize_field(field_name: str) -> str:
    labels = {
        "run.model": "model",
        "run.task": "task",
        "run.dataset": "dataset",
        "run.dataset_version": "dataset version",
        "run.metric": "metric",
        "run.status": "run status",
        "execution.error_class": "error class",
        "execution.latency_ms": "latency",
        "execution.retry_count": "retry count",
        "execution.pass_count": "pass count",
        "execution.attempt_count": "attempt count",
        "trace.tools_used": "tool",
        "trace.llm_models": "trace model",
        "trace.tool_error": "tool errors",
        "trace.provider_error": "provider errors",
        "trace.malformed_tool_call": "malformed tool calls",
        "trace.has_reasoning": "reasoning",
        "trace.has_reasoning_tokens": "reasoning tokens",
    }
    if field_name in labels:
        return labels[field_name]
    return field_name.replace(".", " ").replace("_", " ")


def _value_key(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return format(value, ".12g")
    return unicodedata.normalize("NFKC", str(value)).strip().casefold()


def _canonical_json(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _canonical_json(value[key]) for key in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [_canonical_json(item) for item in value]
    if isinstance(value, set):
        return sorted(_canonical_json(item) for item in value)
    if isinstance(value, float):
        return round(value, 12)
    return value


def _safe_json_value(value: Any) -> Any:
    """Return a JSON-safe numeric value, never an Infinity/NaN."""

    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {key: _safe_json_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_safe_json_value(item) for item in value]
    return value


@dataclass
class _FieldDefinition:
    name: str
    source: str
    kind: str
    authority: int
    dynamic: bool = False
    admitted_value_count: int = 0


@dataclass(frozen=True)
class _Predicate:
    key: str
    field: str
    operator: str
    value: Any
    text: str
    source: str
    authority: int
    kind: str
    field_cardinality: int = 0

    def canonical(self) -> dict[str, Any]:
        return {
            "field": self.field,
            "operator": self.operator,
            "value": _canonical_json(self.value),
        }

    def payload(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "field": self.field,
            "operator": self.operator,
            "value": _safe_json_value(self.value),
            "text": self.text,
            "source": self.source,
        }


@dataclass
class _Observation:
    index: int
    run_id: str
    run_name: str
    run_timestamp: datetime | None
    task: str
    dataset: str
    dataset_version: str | None
    model: str
    status: str
    item_id: str
    item_index: int
    metric: str
    category: str | None
    category_key: str | None
    detail: str | None
    detail_key: str | None
    outcome: str
    score: float | None
    fields: dict[str, Any] = field(default_factory=dict)

    @property
    def diagnosed(self) -> bool:
        return bool(self.category_key)


@dataclass
class _Target:
    key: str
    level: str
    category: str
    category_key: str
    detail: str | None
    detail_key: str | None
    target_mask: int
    population_mask: int
    qualified_count: int


@dataclass
class _CandidateStats:
    factor_mask: int
    factor_count: int
    target_with: int
    target_without: int
    comparison_with: int
    comparison_without: int
    observed_rate: float
    comparison_rate: float
    rate_difference: float
    relative_risk: float
    odds_ratio: float
    coverage: float
    target_coverage: float
    comparison_coverage: float
    diagnosis_target_coverage: float
    diagnosis_comparison_coverage: float
    p_value: float | None = None
    q_value: float | None = None


@dataclass
class _CandidateEvaluation:
    target: _Target
    predicates: tuple[_Predicate, ...]
    stats: _CandidateStats
    direction: str
    relationship_id: str = ""
    removed_reason: str | None = None


@dataclass
class _Gate:
    entered: int = 0
    removed: int = 0
    survived: int = 0
    reasons: Counter[str] = field(default_factory=Counter)

    def enter(self, count: int = 1) -> None:
        self.entered += int(count)

    def remove(self, reason: str, count: int = 1) -> None:
        self.removed += int(count)
        self.reasons[str(reason)] += int(count)

    def survive(self, count: int = 1) -> None:
        self.survived += int(count)

    def payload(self) -> dict[str, Any]:
        return {
            "entered": self.entered,
            "removed": self.removed,
            "survived": self.survived,
            "reasons": dict(sorted(self.reasons.items())),
        }


class _Inventory:
    def __init__(self) -> None:
        self.considered: dict[str, dict[str, Any]] = {}
        self.excluded: dict[str, dict[str, Any]] = {}

    def add_considered(self, definition: _FieldDefinition, *, reason: str = "admitted") -> None:
        self.considered.setdefault(
            definition.name,
            {
                "name": definition.name,
                "source": definition.source,
                "kind": definition.kind,
                "dynamic": definition.dynamic,
                "reason": reason,
            },
        )

    def add_excluded(self, name: str, source: str, reason: str) -> None:
        key = f"{source}:{name}"
        self.excluded.setdefault(
            key,
            {"name": name, "source": source, "reason": reason},
        )

    def payload(self) -> dict[str, list[dict[str, Any]]]:
        return {
            "considered": [self.considered[key] for key in sorted(self.considered)],
            "excluded": [self.excluded[key] for key in sorted(self.excluded)],
        }


@dataclass
class _AnalysisBundle:
    payload: dict[str, Any]
    observations: list[_Observation]
    relationship_evaluations: dict[str, _CandidateEvaluation]


def _chunks(values: Sequence[str], size: int = 500) -> Iterable[Sequence[str]]:
    for start in range(0, len(values), size):
        yield values[start : start + size]


def _run_name(run: Run) -> str:
    config = run.run_config if isinstance(run.run_config, dict) else {}
    return str(config.get("run_name") or run.external_run_id or run.id)


def _run_timestamp(run: Run) -> datetime | None:
    return run.started_at or run.created_at or run.updated_at


def _model_name(value: Any) -> str:
    return str(value or "").strip()


def _direction(spec: RunMetricSpec | None) -> str:
    value = str(spec.direction or "maximize").strip().lower() if spec else "maximize"
    return "minimize" if value in {"minimize", "lower", "lower_is_better"} else "maximize"


def _pass_threshold(spec: RunMetricSpec | None) -> float:
    return float(spec.pass_threshold) if spec and spec.pass_threshold is not None else 0.8


def _outcome(item: RunItem, score: RunItemScore | None, spec: RunMetricSpec | None) -> str:
    if item.error:
        return "error"
    if score is None or score.score_numeric is None:
        return "unscored"
    value = float(score.score_numeric)
    threshold = _pass_threshold(spec)
    passed = value <= threshold if _direction(spec) == "minimize" else value >= threshold
    return "passed" if passed else "failed"


def _score(item: RunItem, score: RunItemScore | None) -> float | None:
    if item.error:
        return 0.0
    return _float(score.score_numeric) if score is not None else None


def _error_class(error: Any) -> str | None:
    text = _safe_text(error, max_length=500)
    if not text:
        return None
    match = _ERROR_CLASS_RE.search(text)
    if match:
        return match.group(1)
    lower = text.casefold()
    for needle, label in (
        ("timeout", "Timeout"),
        ("rate limit", "RateLimit"),
        ("too many requests", "RateLimit"),
        ("authentication", "Authentication"),
        ("permission", "Permission"),
        ("validation", "Validation"),
        ("connection", "Connection"),
    ):
        if needle in lower:
            return label
    return "ExecutionError"


def _shape(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, dict):
        return "object"
    if isinstance(value, list):
        return "array"
    if isinstance(value, str):
        return "string"
    if isinstance(value, (int, float)):
        return "number"
    return "other"


def _size_bucket(value: Any) -> str:
    if value is None:
        return "empty"
    if isinstance(value, dict):
        size = len(value)
    elif isinstance(value, (list, tuple, set)):
        size = len(value)
    elif isinstance(value, str):
        size = len(value)
    else:
        return "scalar"
    if size == 0:
        return "empty"
    if size <= 4:
        return "small"
    if size <= 20:
        return "medium"
    return "large"


def _add_field(
    observation: _Observation,
    definitions: dict[str, _FieldDefinition],
    name: str,
    value: Any,
    *,
    source: str,
    kind: str = "categorical",
    authority: int = 1,
    dynamic: bool = False,
) -> None:
    if value is None:
        return
    if kind == "collection":
        if not isinstance(value, (list, tuple, set)):
            return
        values = {
            clean
            for raw in value
            for clean in [_safe_text(raw, max_length=80)]
            if clean is not None
        }
        # An empty collection is useful as a known false arm, but only when
        # the collection itself was present on the observation.
        if not values and not isinstance(value, (list, tuple, set)):
            return
        current = observation.fields.setdefault(name, set())
        if isinstance(current, set):
            current.update(values)
        definitions.setdefault(
            name,
            _FieldDefinition(name, source, kind, authority, dynamic=dynamic),
        )
        return
    if kind == "numeric":
        clean_number = _float(value)
        if clean_number is None:
            return
        observation.fields[name] = clean_number
    elif kind == "boolean":
        if not isinstance(value, bool):
            return
        observation.fields[name] = value
    else:
        clean = _safe_scalar(value, max_length=200 if name == "run.model" else 120)
        if clean is None:
            return
        observation.fields[name] = clean
    definitions.setdefault(
        name,
        _FieldDefinition(name, source, kind, authority, dynamic=dynamic),
    )


def _add_safe_mapping_fields(
    observation: _Observation,
    definitions: dict[str, _FieldDefinition],
    mapping: Any,
    *,
    prefix: str,
    source: str,
    authority: int,
    inventory: _Inventory,
    depth: int = 0,
) -> None:
    if not isinstance(mapping, dict) or depth > 2:
        return
    for raw_key, raw_value in mapping.items():
        key = str(raw_key or "").strip()
        field_name = f"{prefix}.{_key_part(key)}"
        if not _safe_metadata_key(key):
            inventory.add_excluded(field_name, source, "sensitive_or_unstable_key")
            continue
        if isinstance(raw_value, dict):
            _add_safe_mapping_fields(
                observation,
                definitions,
                raw_value,
                prefix=field_name,
                source=source,
                authority=authority,
                inventory=inventory,
                depth=depth + 1,
            )
            continue
        if isinstance(raw_value, (list, tuple, set)):
            _add_field(
                observation,
                definitions,
                field_name,
                raw_value,
                source=source,
                kind="collection",
                authority=authority,
                dynamic=True,
            )
            continue
        if isinstance(raw_value, (int, float, bool)):
            # Stable numeric configuration is allowed as a numeric source;
            # arbitrary item metadata numbers are intentionally not inferred.
            kind = "numeric" if isinstance(raw_value, (int, float)) and not isinstance(raw_value, bool) else "boolean"
            _add_field(
                observation,
                definitions,
                field_name,
                raw_value,
                source=source,
                kind=kind,
                authority=authority,
                dynamic=True,
            )
            continue
        clean = _safe_text(raw_value)
        if clean is None:
            inventory.add_excluded(field_name, source, "unsupported_or_unsafe_value")
            continue
        _add_field(
            observation,
            definitions,
            field_name,
            clean,
            source=source,
            authority=authority,
            dynamic=True,
        )


def _trace_value_from_bucket(bucket: Mapping[str, Any], key: str) -> Any:
    if key in bucket:
        return bucket.get(key)
    raw = bucket.get("raw_bucket")
    if isinstance(raw, dict) and key in raw:
        return raw.get(key)
    return None


def _trace_latency_from_bucket(bucket: Mapping[str, Any], name: str) -> float | None:
    direct = _float(bucket.get(name))
    if direct is not None:
        return direct
    raw = bucket.get("raw_bucket")
    raw = raw if isinstance(raw, dict) else bucket
    totals = {
        "avg_llm_ms": ("llm_duration_ms_total", "llm_duration_ms_count"),
        "avg_tool_ms": ("tool_duration_ms_total", "tool_duration_ms_count"),
        "avg_retriever_ms": ("retriever_duration_ms_total", "retriever_duration_ms_count"),
        "avg_evaluator_ms": ("evaluator_duration_ms_total", "evaluator_duration_ms_count"),
        "avg_top_level_chain_ms": (
            "top_level_chain_duration_ms_total",
            "top_level_chain_duration_ms_count",
        ),
    }
    total_key, count_key = totals[name]
    total = _float(raw.get(total_key))
    count = _float(raw.get(count_key))
    if total is None or count is None or count <= 0:
        return None
    return total / count


def _trace_context(
    item: RunItem,
    attempts: Sequence[RunItemAttempt],
    aggregates_by_trace: Mapping[str, RunTraceAggregate],
    spans_by_trace: Mapping[str, Sequence[Span]],
) -> dict[str, Any] | None:
    trace_ids = {
        str(trace_id).strip()
        for trace_id in [
            item.trace_id,
            *(attempt.trace_id for attempt in attempts),
        ]
        if str(trace_id or "").strip()
    }
    if not trace_ids:
        metadata = item.item_metadata if isinstance(item.item_metadata, dict) else {}
        stats = metadata.get("trace_stats")
        if not isinstance(stats, dict) or not stats.get("has_spans"):
            return None
    context: dict[str, Any] = {
        "tools": set(),
        "llm_models": set(),
        "has_trace": True,
        "tool_errors": 0,
        "provider_errors": 0,
        "malformed_tool_calls": 0,
        "noisy_reasoning": 0,
        "has_reasoning": False,
        "has_reasoning_tokens": False,
        "numeric": defaultdict(float),
        "latency": {},
    }
    trace_seen = set()
    for trace_id in sorted(trace_ids):
        if trace_id in trace_seen:
            continue
        trace_seen.add(trace_id)
        aggregate = aggregates_by_trace.get(trace_id)
        bucket: dict[str, Any] = {}
        if aggregate is not None:
            bucket.update(
                {
                    "tokens": aggregate.tokens,
                    "cost": aggregate.cost,
                    "llm_calls": aggregate.llm_calls,
                    "tool_calls": aggregate.tool_calls,
                    "tool_errors": aggregate.tool_errors,
                    "malformed_tool_calls": getattr(aggregate, "malformed_tool_calls", 0),
                    "noisy_reasoning": getattr(aggregate, "noisy_reasoning", 0),
                    "provider_errors": getattr(aggregate, "provider_errors", 0),
                    "has_reasoning": aggregate.has_reasoning,
                    "has_reasoning_tokens": aggregate.has_reasoning_tokens,
                    "reasoning_tokens": aggregate.reasoning_tokens,
                    "raw_bucket": aggregate.raw_bucket,
                }
            )
        for key in _TRACE_NUMERIC_KEYS:
            value = _float(_trace_value_from_bucket(bucket, key))
            if value is not None:
                context["numeric"][key] += value
        for key in _TRACE_LATENCY_KEYS:
            value = _trace_latency_from_bucket(bucket, key)
            if value is not None:
                current = context["latency"].get(key)
                context["latency"][key] = value if current is None else (current + value) / 2.0
        context["tool_errors"] += int(_trace_value_from_bucket(bucket, "tool_errors") or 0)
        context["provider_errors"] += int(_trace_value_from_bucket(bucket, "provider_errors") or 0)
        context["malformed_tool_calls"] += int(
            _trace_value_from_bucket(bucket, "malformed_tool_calls") or 0
        )
        context["noisy_reasoning"] += int(_trace_value_from_bucket(bucket, "noisy_reasoning") or 0)
        context["has_reasoning"] = context["has_reasoning"] or bool(
            _trace_value_from_bucket(bucket, "has_reasoning")
        )
        context["has_reasoning_tokens"] = context["has_reasoning_tokens"] or bool(
            _trace_value_from_bucket(bucket, "has_reasoning_tokens")
        )

        for span in spans_by_trace.get(trace_id, []):
            attrs = span.attributes if isinstance(span.attributes, dict) else {}
            kind = str(
                attrs.get("openinference.span.kind")
                or attrs.get("ai.openinference.span.kind")
                or ""
            ).upper()
            if kind == "RETRIEVE":
                kind = "RETRIEVER"
            if kind == "TOOL":
                tool_name = next(
                    (
                        _safe_text(attrs.get(key), max_length=80)
                        for key in _TOOL_ATTR_KEYS
                        if _safe_text(attrs.get(key), max_length=80)
                    ),
                    _safe_text(span.name, max_length=80),
                )
                if tool_name:
                    context["tools"].add(tool_name)
                if str(span.status or "").upper() == "ERROR":
                    context["tool_errors"] += 1
            if kind == "LLM":
                for attr_key in _MODEL_ATTR_KEYS:
                    model = _safe_text(attrs.get(attr_key), max_length=200)
                    if model:
                        context["llm_models"].add(model)
                        break
            classification = str(attrs.get("qym.response.classification") or "")
            if classification == "provider_error":
                context["provider_errors"] += 1
            elif classification == "malformed_tool_call":
                context["malformed_tool_calls"] += 1
            elif classification == "noisy_reasoning":
                context["noisy_reasoning"] += 1
            if kind in {"LLM", "TOOL", "RETRIEVER", "EVALUATOR"}:
                latency_key = {
                    "LLM": "avg_llm_ms",
                    "TOOL": "avg_tool_ms",
                    "RETRIEVER": "avg_retriever_ms",
                    "EVALUATOR": "avg_evaluator_ms",
                }[kind]
                duration = _float(span.duration_ms)
                if duration is not None:
                    previous = context["latency"].get(latency_key)
                    context["latency"][latency_key] = (
                        duration
                        if previous is None
                        else (previous + duration) / 2.0
                    )

    if not trace_ids:
        metadata = item.item_metadata if isinstance(item.item_metadata, dict) else {}
        stats = metadata.get("trace_stats")
        if isinstance(stats, dict):
            context["has_trace"] = bool(stats.get("has_spans"))
            for key in _TRACE_NUMERIC_KEYS:
                value = _float(stats.get(key.removeprefix("trace.")))
                if value is not None:
                    context["numeric"][key.removeprefix("trace.")] = value
            for key in _TRACE_LATENCY_KEYS:
                value = _float(stats.get(key.removeprefix("trace.")))
                if value is not None:
                    context["latency"][key] = value
            context["tool_errors"] = int(stats.get("tool_errors") or 0)
            context["provider_errors"] = int(stats.get("provider_errors") or 0)
            context["malformed_tool_calls"] = int(stats.get("malformed_tool_calls") or 0)
            context["noisy_reasoning"] = int(stats.get("noisy_reasoning") or 0)
            context["has_reasoning"] = bool(stats.get("has_reasoning"))
            context["has_reasoning_tokens"] = bool(stats.get("has_reasoning_tokens"))
    return context if context.get("has_trace") else None


def _diagnosis(run: Run, item: RunItem, metric: str) -> tuple[dict[str, Any] | None, str | None]:
    metadata = item.item_metadata if isinstance(item.item_metadata, dict) else {}
    metric_analyses = metadata.get("metric_analyses")
    if isinstance(metric_analyses, dict) and metric_analyses:
        if metric not in metric_analyses:
            return None, None
        raw = metric_analyses.get(metric)
        if not isinstance(raw, dict):
            return None, "invalid_diagnosis_payload"
        if raw.get("error") or raw.get("analysis_error"):
            return None, "analysis_error"
        raw_category = raw.get("root_cause")
        if raw_category in (None, ""):
            return None, None
        if not isinstance(raw_category, str):
            return None, "invalid_diagnosis_payload"
        category = _display_label(raw_category)
        if not category or len(category) > 200:
            return None, "invalid_diagnosis_payload"
        raw_detail = raw.get("root_cause_detail")
        if raw_detail not in (None, "") and not isinstance(raw_detail, str):
            return None, "invalid_diagnosis_payload"
        detail = _display_label(raw_detail) if raw_detail not in (None, "") else None
        if detail and len(detail) > 200:
            return None, "invalid_diagnosis_payload"
        return {"category": category, "detail": detail}, None

    if metadata.get("analysis_error"):
        return None, "analysis_error"
    raw_category = metadata.get("root_cause")
    if raw_category in (None, ""):
        return None, None
    if not isinstance(raw_category, str):
        return None, "invalid_diagnosis_payload"
    category = _display_label(raw_category)
    if not category or len(category) > 200:
        return None, "invalid_diagnosis_payload"
    metric_name = str(metadata.get("root_cause_metric_name") or "").strip()
    metrics = [str(value) for value in (run.metrics or []) if str(value).strip()]
    if metric_name and metric_name != metric:
        return None, None
    if not metric_name and len(metrics) > 1:
        return None, None
    raw_detail = metadata.get("root_cause_detail")
    if raw_detail not in (None, "") and not isinstance(raw_detail, str):
        return None, "invalid_diagnosis_payload"
    detail = _display_label(raw_detail) if raw_detail not in (None, "") else None
    return {"category": category, "detail": detail}, None


def _empty_execution(item: RunItem, score: RunItemScore | None, attempts: Sequence[RunItemAttempt]) -> bool:
    return not any(
        value is not None
        for value in (item.input, item.expected, item.output, item.error, score, *attempts)
    )


def _load_rows(
    db: Session,
    project_id: str,
) -> tuple[
    list[Run],
    list[RunItem],
    dict[tuple[str, str, str], RunItemScore],
    dict[tuple[str, str], RunMetricSpec],
    dict[tuple[str, str], list[RunItemAttempt]],
    dict[str, RunTraceAggregate],
    dict[str, list[Span]],
    dict[int, DatasetItem],
    dict[str, DatasetVersion],
]:
    runs = [
        run
        for run in Run.active(db)
        .filter(Run.project_id == project_id)
        .order_by(Run.created_at.asc(), Run.id.asc())
        .all()
        if _enum_value(run.status) not in _LIVE_STATUSES
    ]
    run_ids = [run.id for run in runs]
    if not run_ids:
        return [], [], {}, {}, {}, {}, {}, {}, {}

    items: list[RunItem] = []
    scores: dict[tuple[str, str, str], RunItemScore] = {}
    specs: dict[tuple[str, str], RunMetricSpec] = {}
    attempts: dict[tuple[str, str], list[RunItemAttempt]] = defaultdict(list)
    aggregates: dict[str, RunTraceAggregate] = {}
    spans: dict[str, list[Span]] = defaultdict(list)
    dataset_item_ids: set[int] = set()
    dataset_version_ids = {run.dataset_version_id for run in runs if run.dataset_version_id}

    for chunk in _chunks(run_ids):
        items.extend(
            db.query(RunItem)
            .filter(RunItem.run_id.in_(chunk))
            .order_by(RunItem.run_id.asc(), RunItem.index.asc(), RunItem.id.asc())
            .all()
        )
        for row in db.query(RunItemScore).filter(RunItemScore.run_id.in_(chunk)).all():
            scores[(row.run_id, row.item_id, row.metric_name)] = row
        for row in db.query(RunMetricSpec).filter(RunMetricSpec.run_id.in_(chunk)).all():
            specs[(row.run_id, row.metric_name)] = row
        for row in db.query(RunItemAttempt).filter(RunItemAttempt.run_id.in_(chunk)).all():
            attempts[(row.run_id, row.item_id)].append(row)
        for row in db.query(RunTraceAggregate).filter(RunTraceAggregate.run_id.in_(chunk)).all():
            aggregates[str(row.trace_id)] = row
        for row in db.query(Span).filter(Span.run_id.in_(chunk)).all():
            spans[str(row.trace_id)].append(row)
    for item in items:
        if item.dataset_item_pk:
            dataset_item_ids.add(int(item.dataset_item_pk))

    dataset_items: dict[int, DatasetItem] = {}
    for chunk in _chunks([str(value) for value in sorted(dataset_item_ids)]):
        for row in db.query(DatasetItem).filter(DatasetItem.id.in_([int(value) for value in chunk])).all():
            dataset_items[int(row.id)] = row
    dataset_versions = {
        row.id: row
        for chunk in _chunks(sorted(dataset_version_ids))
        for row in db.query(DatasetVersion).filter(DatasetVersion.id.in_(chunk)).all()
    }
    return runs, items, scores, specs, attempts, aggregates, spans, dataset_items, dataset_versions


def _build_observations(
    db: Session,
    project_id: str,
    inventory: _Inventory,
    scope_gate: _Gate,
) -> tuple[list[_Observation], int, int]:
    (
        runs,
        items,
        scores,
        specs,
        attempts,
        aggregates,
        spans,
        dataset_items,
        dataset_versions,
    ) = _load_rows(db, project_id)
    definitions: dict[str, _FieldDefinition] = {}
    run_map = {run.id: run for run in runs}
    items_by_run: dict[str, list[RunItem]] = defaultdict(list)
    for item in items:
        items_by_run[item.run_id].append(item)
    total_potential = 0
    invalid_count = 0
    observations: list[_Observation] = []

    for run in runs:
        run_metric_names = {str(metric) for metric in (run.metrics or []) if str(metric).strip()}
        run_metric_names.update(
            metric_name
            for (run_id, _item_id, metric_name) in scores
            if run_id == run.id
        )
        for item in items_by_run.get(run.id, []):
            item_attempts = attempts.get((run.id, item.item_id), [])
            item_metrics = dict(item.item_metadata) if isinstance(item.item_metadata, dict) else {}
            metric_analyses = item_metrics.get("metric_analyses")
            metric_names = set(run_metric_names)
            if isinstance(metric_analyses, dict):
                metric_names.update(str(metric) for metric in metric_analyses if str(metric).strip())
            if not metric_names:
                inventory.add_excluded("execution", "execution", "missing_metric")
                continue
            dataset_version = dataset_versions.get(run.dataset_version_id)
            dataset_item = dataset_items.get(int(item.dataset_item_pk)) if item.dataset_item_pk else None
            labels = dataset_item.labels if dataset_item is not None else []
            for metric in sorted(metric_names):
                total_potential += 1
                score_row = scores.get((run.id, item.item_id, metric))
                if _empty_execution(item, score_row, item_attempts):
                    scope_gate.enter()
                    scope_gate.remove("empty_execution")
                    continue
                diagnosis, diagnosis_error = _diagnosis(run, item, metric)
                if diagnosis_error:
                    scope_gate.enter()
                    scope_gate.remove(diagnosis_error)
                    invalid_count += 1
                    continue
                category = diagnosis.get("category") if diagnosis else None
                detail = diagnosis.get("detail") if diagnosis else None
                category_key = normalize_label(category) if category else None
                detail_key = normalize_label(detail) if detail else None
                observation = _Observation(
                    index=len(observations),
                    run_id=run.id,
                    run_name=_run_name(run),
                    run_timestamp=_run_timestamp(run),
                    task=str(run.task or ""),
                    dataset=str(run.dataset or ""),
                    dataset_version=(str(dataset_version.version) if dataset_version else None),
                    model=_model_name(run.model),
                    status=_enum_value(run.status),
                    item_id=item.item_id,
                    item_index=int(item.index or 0),
                    metric=metric,
                    category=category,
                    category_key=category_key,
                    detail=detail,
                    detail_key=detail_key,
                    outcome=_outcome(item, score_row, specs.get((run.id, metric))),
                    score=_score(item, score_row),
                )
                _add_field(observation, definitions, "run.model", run.model, source="run", authority=0)
                _add_field(observation, definitions, "run.task", run.task, source="run", authority=0)
                _add_field(observation, definitions, "run.dataset", run.dataset, source="run", authority=0)
                _add_field(
                    observation,
                    definitions,
                    "run.dataset_version",
                    dataset_version.version if dataset_version else None,
                    source="dataset",
                    authority=0,
                )
                _add_field(observation, definitions, "run.status", _enum_value(run.status), source="run", authority=0)
                _add_field(observation, definitions, "run.metric", metric, source="run", authority=0)
                run_config = run.run_config if isinstance(run.run_config, dict) else {}
                stable_run_config = {}
                for key, value in run_config.items():
                    if str(key) in _UNSTABLE_RUN_CONFIG_KEYS:
                        inventory.add_excluded(
                            f"run.config.{_key_part(key)}",
                            "run_config",
                            "identifier_or_unstable_value",
                        )
                        continue
                    stable_run_config[key] = value
                _add_safe_mapping_fields(
                    observation,
                    definitions,
                    stable_run_config,
                    prefix="run.config",
                    source="run_config",
                    authority=0,
                    inventory=inventory,
                )
                run_metadata = run.run_metadata if isinstance(run.run_metadata, dict) else {}
                _add_safe_mapping_fields(
                    observation,
                    definitions,
                    run_metadata,
                    prefix="run.metadata",
                    source="run_metadata",
                    authority=2,
                    inventory=inventory,
                )
                if labels:
                    _add_field(
                        observation,
                        definitions,
                        "item.dataset_labels",
                        labels,
                        source="dataset",
                        kind="collection",
                        authority=0,
                    )
                item_metadata = item.item_metadata if isinstance(item.item_metadata, dict) else {}
                for key in item_metadata:
                    if str(key) in _DIAGNOSIS_KEYS:
                        inventory.add_excluded(
                            f"item.metadata.{_key_part(key)}",
                            "item_metadata",
                            "diagnosis_derived",
                        )
                _add_safe_mapping_fields(
                    observation,
                    definitions,
                    {
                        key: value
                        for key, value in item_metadata.items()
                        if key not in _DIAGNOSIS_KEYS
                        and key not in {
                            "metric_analyses",
                            "trace_stats",
                            "retry_count",
                            "task_started_at_ms",
                        }
                    },
                    prefix="item.metadata",
                    source="item_metadata",
                    authority=2,
                    inventory=inventory,
                )
                # Only deterministic shape/size summaries of content are
                # candidates; the underlying values are never retained here.
                for prefix, value in (
                    ("item.input", item.input),
                    ("item.expected", item.expected),
                    ("item.output", item.output),
                ):
                    _add_field(observation, definitions, f"{prefix}.shape", _shape(value), source="item", authority=1)
                    _add_field(observation, definitions, f"{prefix}.size", _size_bucket(value), source="item", authority=1)
                _add_field(
                    observation,
                    definitions,
                    "execution.error_class",
                    _error_class(item.error),
                    source="execution",
                    authority=1,
                )
                _add_field(observation, definitions, "execution.latency_ms", item.latency_ms, source="execution", kind="numeric", authority=1)
                _add_field(observation, definitions, "execution.retry_count", item.retry_count, source="execution", kind="numeric", authority=1)
                pass_count = len({int(attempt.pass_number or 1) for attempt in item_attempts}) if item_attempts else max(int(run.samples or 1), 1)
                _add_field(observation, definitions, "execution.pass_count", pass_count, source="execution", kind="numeric", authority=1)
                _add_field(observation, definitions, "execution.attempt_count", len(item_attempts) if item_attempts else 1, source="execution", kind="numeric", authority=1)

                trace = _trace_context(item, item_attempts, aggregates, spans)
                if trace:
                    for trace_key, field_name in _TRACE_NUMERIC_KEYS.items():
                        _add_field(
                            observation,
                            definitions,
                            field_name,
                            trace["numeric"].get(trace_key),
                            source="trace",
                            kind="numeric",
                            authority=3,
                        )
                    for trace_key, field_name in _TRACE_LATENCY_KEYS.items():
                        _add_field(
                            observation,
                            definitions,
                            field_name,
                            trace["latency"].get(trace_key),
                            source="trace",
                            kind="numeric",
                            authority=3,
                        )
                    _add_field(observation, definitions, "trace.tools_used", trace["tools"], source="trace", kind="collection", authority=3)
                    differing_models = {
                        model
                        for model in trace["llm_models"]
                        if model and model != observation.model
                    }
                    _add_field(observation, definitions, "trace.llm_models", differing_models, source="trace", kind="collection", authority=3)
                    _add_field(observation, definitions, "trace.tool_error", trace["tool_errors"] > 0, source="trace", kind="boolean", authority=3)
                    _add_field(observation, definitions, "trace.provider_error", trace["provider_errors"] > 0, source="trace", kind="boolean", authority=3)
                    _add_field(observation, definitions, "trace.malformed_tool_call", trace["malformed_tool_calls"] > 0, source="trace", kind="boolean", authority=3)
                    _add_field(observation, definitions, "trace.has_reasoning", trace["has_reasoning"], source="trace", kind="boolean", authority=3)
                    _add_field(observation, definitions, "trace.has_reasoning_tokens", trace["has_reasoning_tokens"], source="trace", kind="boolean", authority=3)
                observations.append(observation)
                scope_gate.enter()
                scope_gate.survive()

    # The field definitions are only used for candidate generation below, but
    # inventory is intentionally populated after all observations exist so it
    # can distinguish admitted repeated fields from unique metadata.
    for definition in definitions.values():
        inventory.add_considered(definition)
    return observations, total_potential, invalid_count


def _predicate_matches(predicate: _Predicate, value: Any) -> bool:
    if value is None:
        return False
    if predicate.operator == "contains":
        return isinstance(value, set) and predicate.value in value
    if predicate.operator == "equals":
        return _value_key(value) == _value_key(predicate.value)
    if predicate.operator == "not_equals":
        return _value_key(value) != _value_key(predicate.value)
    if predicate.operator == "less_equal":
        return _is_finite_number(value) and float(value) <= float(predicate.value)
    if predicate.operator == "greater_equal":
        return _is_finite_number(value) and float(value) >= float(predicate.value)
    return False


def _predicate_text(field_name: str, operator: str, value: Any) -> str:
    field = _humanize_field(field_name)
    if operator == "contains":
        return f"{field} {value} was used"
    if operator == "equals" and isinstance(value, bool):
        return f"{field} were present" if value else f"{field} were absent"
    if operator == "equals":
        return f"{field} is {value}"
    if operator == "not_equals":
        return f"{field} is nonzero"
    if operator == "less_equal":
        return f"{field} is at or below {float(value):.3g}"
    if operator == "greater_equal":
        return f"{field} is at or above {float(value):.3g}"
    return f"{field} {operator} {value}"


def _new_predicate(
    field_def: _FieldDefinition,
    operator: str,
    value: Any,
    *,
    cardinality: int,
) -> _Predicate:
    value_key = _value_key(value)
    key = f"{field_def.name}|{operator}|{value_key}"
    return _Predicate(
        key=key,
        field=field_def.name,
        operator=operator,
        value=value,
        text=_predicate_text(field_def.name, operator, value),
        source=field_def.source,
        authority=field_def.authority,
        kind=field_def.kind,
        field_cardinality=cardinality,
    )


def _quantile(values: Sequence[float], fraction: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    position = (len(ordered) - 1) * fraction
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _build_predicates(
    observations: Sequence[_Observation],
    inventory: _Inventory,
    field_safety_gate: _Gate,
    redundancy_gate: _Gate,
) -> tuple[list[_Predicate], dict[str, int], dict[str, int]]:
    # Recover definitions from the observed field names and their source from
    # the inventory; this keeps observation payloads free of schema metadata.
    definitions: dict[str, _FieldDefinition] = {}
    for entry in inventory.considered.values():
        definitions[entry["name"]] = _FieldDefinition(
            entry["name"],
            entry["source"],
            entry["kind"],
            {"run": 0, "dataset": 0, "item": 1, "execution": 1, "run_config": 0, "run_metadata": 2, "item_metadata": 2, "trace": 3}.get(entry["source"], 2),
            dynamic=bool(entry.get("dynamic")),
        )
    generated: list[_Predicate] = []
    for definition in definitions.values():
        values = [observation.fields.get(definition.name) for observation in observations]
        non_null = [value for value in values if value is not None]
        if not non_null:
            inventory.add_excluded(definition.name, definition.source, "no_usable_values")
            continue
        candidates: list[_Predicate] = []
        if definition.kind == "numeric":
            numbers = [float(value) for value in non_null if _is_finite_number(value)]
            if not numbers:
                inventory.add_excluded(definition.name, definition.source, "unsupported_numeric_values")
                continue
            candidates.extend(
                [
                    _new_predicate(definition, "equals", 0.0, cardinality=2),
                    _new_predicate(definition, "not_equals", 0.0, cardinality=2),
                ]
            )
            if len(numbers) >= 40:
                q1 = _quantile(numbers, 0.25)
                q3 = _quantile(numbers, 0.75)
                candidates.extend(
                    [
                        _new_predicate(definition, "less_equal", round(q1, 12), cardinality=2),
                        _new_predicate(definition, "greater_equal", round(q3, 12), cardinality=2),
                    ]
                )
        elif definition.kind == "collection":
            members = [member for value in non_null if isinstance(value, set) for member in value]
            counts = Counter(members)
            repeated = sorted(member for member, count in counts.items() if count >= 2)
            definition.admitted_value_count = len(repeated)
            if not repeated:
                inventory.add_excluded(definition.name, definition.source, "not_repeated")
                continue
            candidates = [_new_predicate(definition, "contains", member, cardinality=len(repeated)) for member in repeated]
        elif definition.kind == "boolean":
            definition.admitted_value_count = 1
            if any(value is True for value in non_null):
                candidates = [_new_predicate(definition, "equals", True, cardinality=1)]
        else:
            counts = Counter(_value_key(value) for value in non_null)
            if definition.dynamic:
                repeated_keys = {key for key, count in counts.items() if count >= 2}
                if not repeated_keys:
                    inventory.add_excluded(definition.name, definition.source, "not_repeated")
                    continue
                definition.admitted_value_count = len(repeated_keys)
                candidates = [
                    _new_predicate(
                        definition,
                        "equals",
                        next(value for value in non_null if _value_key(value) == key),
                        cardinality=len(repeated_keys),
                    )
                    for key in sorted(repeated_keys)
                ]
            else:
                distinct = sorted({_value_key(value) for value in non_null})
                definition.admitted_value_count = len(distinct)
                candidates = [
                    _new_predicate(
                        definition,
                        "equals",
                        next(value for value in non_null if _value_key(value) == key),
                        cardinality=len(distinct),
                    )
                    for key in distinct
                ]
        field_safety_gate.enter(len(candidates))
        if not candidates:
            field_safety_gate.remove("no_admitted_predicate")
            continue
        field_safety_gate.survive(len(candidates))
        generated.extend(candidates)

    # Redundancy is defined over the complete observation mapping.  A model
    # mirrored in item metadata therefore keeps the run field, while an
    # identical trace-derived copy is removed.
    by_signature: dict[tuple[Any, ...], _Predicate] = {}
    admitted: list[_Predicate] = []
    for predicate in sorted(generated, key=lambda item: (item.authority, item.field, item.key)):
        signature = tuple(
            None if observation.fields.get(predicate.field) is None else _predicate_matches(predicate, observation.fields.get(predicate.field))
            for observation in observations
        )
        existing = by_signature.get(signature)
        if existing is not None:
            redundancy_gate.enter()
            redundancy_gate.remove("redundant_field")
            inventory.add_excluded(predicate.field, predicate.source, f"redundant_with:{existing.field}")
            continue
        by_signature[signature] = predicate
        redundancy_gate.enter()
        redundancy_gate.survive()
        admitted.append(predicate)

    # A globally unsupported factor can never satisfy the two ten-execution
    # arms of a project target.  Filtering it here keeps one-factor analysis
    # bounded on projects with identifier-like high cardinality fields.
    bits_by_predicate: dict[str, int] = {}
    complete_bits_by_field: dict[str, int] = {}
    for field_name in definitions:
        bits = 0
        for index, observation in enumerate(observations):
            if observation.fields.get(field_name) is not None:
                bits |= 1 << index
        complete_bits_by_field[field_name] = bits
    for predicate in admitted:
        bits = 0
        for index, observation in enumerate(observations):
            if _predicate_matches(predicate, observation.fields.get(predicate.field)):
                bits |= 1 << index
        bits_by_predicate[predicate.key] = bits
    filtered: list[_Predicate] = []
    for predicate in admitted:
        support = bits_by_predicate[predicate.key].bit_count()
        complete = complete_bits_by_field.get(predicate.field, 0).bit_count()
        if support < MIN_SUPPORT or complete - support < MIN_SUPPORT:
            inventory.add_excluded(predicate.field, predicate.source, "constant_or_low_exposure")
            continue
        filtered.append(predicate)
    return filtered, bits_by_predicate, complete_bits_by_field


def _generate_candidate_specs(
    observations: Sequence[_Observation],
    predicates: Sequence[_Predicate],
    predicate_bits: Mapping[str, int],
) -> list[tuple[tuple[_Predicate, ...], int]]:
    predicate_map = {predicate.key: predicate for predicate in predicates}
    by_field = {predicate.field: predicate.field_cardinality for predicate in predicates}
    combo_allowed = {
        predicate.key
        for predicate in predicates
        if by_field.get(predicate.field, 0) <= 20
    }
    true_keys_by_observation: list[list[str]] = []
    for index, observation in enumerate(observations):
        keys = [
            predicate.key
            for predicate in predicates
            if predicate.key in predicate_bits
            and (predicate_bits[predicate.key] >> index) & 1
        ]
        true_keys_by_observation.append(sorted(keys))
    combo_counts: Counter[tuple[str, ...]] = Counter()
    for keys in true_keys_by_observation:
        eligible = [key for key in keys if key in combo_allowed]
        for arity in (2, 3):
            for combination in itertools.combinations(eligible, arity):
                fields = [predicate_map[key].field for key in combination]
                if len(set(fields)) != len(fields):
                    continue
                combo_counts[combination] += 1
    candidates: list[tuple[tuple[_Predicate, ...], int]] = []
    for predicate in sorted(predicates, key=lambda item: item.key):
        candidates.append(((predicate,), predicate_bits[predicate.key]))
    for combination, count in sorted(combo_counts.items()):
        if count < MIN_SUPPORT:
            continue
        predicate_tuple = tuple(predicate_map[key] for key in combination)
        factor_bits = predicate_bits[combination[0]]
        for key in combination[1:]:
            factor_bits &= predicate_bits[key]
        candidates.append((predicate_tuple, factor_bits))
    return candidates


def _mask_for_observations(observations: Sequence[_Observation], predicate: Any) -> int:
    mask = 0
    for index in predicate:
        mask |= 1 << int(index)
    return mask


def _target_key(level: str, category_key: str, detail_key: str | None) -> str:
    return f"{level}:{category_key}:{detail_key or ''}"


def _build_targets(observations: Sequence[_Observation], target_gate: _Gate) -> tuple[list[_Target], list[dict[str, Any]]]:
    all_mask = (1 << len(observations)) - 1 if observations else 0
    diagnosed_mask = sum((1 << observation.index) for observation in observations if observation.diagnosed)
    category_counts: Counter[str] = Counter(
        observation.category_key for observation in observations if observation.category_key
    )
    category_display: dict[str, str] = {}
    for observation in observations:
        if observation.category_key:
            category_display.setdefault(observation.category_key, observation.category or observation.category_key)
    targets: list[_Target] = []
    below_details: list[dict[str, Any]] = []
    for category_key in sorted(category_counts):
        category_count = category_counts[category_key]
        target_gate.enter()
        if category_count < CATEGORY_THRESHOLD:
            target_gate.remove("below_category_threshold")
        else:
            category_mask = sum(
                1 << observation.index
                for observation in observations
                if observation.category_key == category_key
            )
            population_mask = sum(
                1 << observation.index
                for observation in observations
                if observation.diagnosed or observation.outcome in _FAILURE_OUTCOMES
            )
            targets.append(
                _Target(
                    key=_target_key("category", category_key, None),
                    level="category",
                    category=category_display[category_key],
                    category_key=category_key,
                    detail=None,
                    detail_key=None,
                    target_mask=category_mask,
                    population_mask=population_mask,
                    qualified_count=category_count,
                )
            )
            target_gate.survive()
        detail_counts = Counter(
            observation.detail_key
            for observation in observations
            if observation.category_key == category_key and observation.detail_key
        )
        detail_display: dict[str, str] = {}
        for observation in observations:
            if observation.category_key == category_key and observation.detail_key:
                detail_display.setdefault(observation.detail_key, observation.detail or observation.detail_key)
        for detail_key in sorted(detail_counts):
            count = detail_counts[detail_key]
            if count < DETAIL_THRESHOLD:
                below_details.append(
                    {
                        "category": category_display[category_key],
                        "category_key": category_key,
                        "detail": detail_display[detail_key],
                        "detail_key": detail_key,
                        "count": count,
                    }
                )
                target_gate.enter()
                target_gate.remove("below_detail_threshold")
                continue
            detail_mask = sum(
                1 << observation.index
                for observation in observations
                if observation.category_key == category_key and observation.detail_key == detail_key
            )
            parent_mask = sum(
                1 << observation.index
                for observation in observations
                if observation.category_key == category_key and observation.detail_key
            )
            targets.append(
                _Target(
                    key=_target_key("detail", category_key, detail_key),
                    level="detail",
                    category=category_display[category_key],
                    category_key=category_key,
                    detail=detail_display[detail_key],
                    detail_key=detail_key,
                    target_mask=detail_mask,
                    population_mask=parent_mask,
                    qualified_count=count,
                )
            )
            target_gate.enter()
            target_gate.survive()
    return targets, below_details


def _rate(count: int, denominator: int) -> float:
    return count / denominator if denominator else 0.0


def _relative_risk(observed: float, comparison: float) -> float:
    if comparison == 0:
        return math.inf if observed > 0 else 0.0
    return observed / comparison


def _odds_ratio(a: int, b: int, c: int, d: int) -> float:
    denominator = b * c
    numerator = a * d
    if denominator == 0:
        return math.inf if numerator > 0 else 0.0
    return numerator / denominator


def _candidate_stats(
    target: _Target,
    factor_mask: int,
    complete_mask: int,
    diagnosed_mask: int,
) -> _CandidateStats:
    population = target.population_mask
    factor_arm = population & factor_mask
    comparison_arm = population & ~factor_mask
    target_with = (target.target_mask & factor_arm).bit_count()
    target_without = (target.target_mask & comparison_arm).bit_count()
    comparison_with = ((population & ~target.target_mask) & factor_arm).bit_count()
    comparison_without = ((population & ~target.target_mask) & comparison_arm).bit_count()
    factor_count = factor_arm.bit_count()
    comparison_count = comparison_arm.bit_count()
    observed_rate = _rate(target_with, factor_count)
    comparison_rate = _rate(target_without, comparison_count)
    target_coverage = _rate((factor_arm & complete_mask).bit_count(), factor_count)
    comparison_coverage = _rate((comparison_arm & complete_mask).bit_count(), comparison_count)
    diagnosis_target_coverage = _rate((factor_arm & diagnosed_mask).bit_count(), factor_count)
    diagnosis_comparison_coverage = _rate((comparison_arm & diagnosed_mask).bit_count(), comparison_count)
    p_value: float | None = None
    if factor_count and comparison_count:
        try:
            _odds, p_value = fisher_exact(
                [[target_with, target_without], [comparison_with, comparison_without]],
                alternative="two-sided",
            )
            p_value = float(p_value)
        except (ValueError, TypeError):
            p_value = None
    return _CandidateStats(
        factor_mask=factor_mask,
        factor_count=factor_count,
        target_with=target_with,
        target_without=target_without,
        comparison_with=comparison_with,
        comparison_without=comparison_without,
        observed_rate=observed_rate,
        comparison_rate=comparison_rate,
        rate_difference=observed_rate - comparison_rate,
        relative_risk=_relative_risk(observed_rate, comparison_rate),
        odds_ratio=_odds_ratio(target_with, target_without, comparison_with, comparison_without),
        coverage=_rate((population & complete_mask).bit_count(), population.bit_count()),
        target_coverage=target_coverage,
        comparison_coverage=comparison_coverage,
        diagnosis_target_coverage=diagnosis_target_coverage,
        diagnosis_comparison_coverage=diagnosis_comparison_coverage,
        p_value=p_value,
    )


def _effect_direction(stats: _CandidateStats) -> str | None:
    if stats.relative_risk >= MIN_RELATIVE_RISK and stats.rate_difference >= MIN_RATE_DIFFERENCE:
        return "more_common"
    if stats.relative_risk <= MAX_RELATIVE_RISK and stats.rate_difference <= -MIN_RATE_DIFFERENCE:
        return "less_common"
    return None


def _bh_adjust(p_values: Sequence[float]) -> list[float]:
    if not p_values:
        return []
    order = sorted(range(len(p_values)), key=lambda index: (p_values[index], index))
    adjusted = [1.0] * len(p_values)
    running = 1.0
    total = len(p_values)
    for rank in range(total, 0, -1):
        index = order[rank - 1]
        running = min(running, p_values[index] * total / rank)
        adjusted[index] = min(1.0, running)
    return adjusted


def _rr_magnitude(relative_risk: float) -> float:
    if relative_risk in {0.0, math.inf}:
        return math.inf
    return abs(math.log(relative_risk))


def _complexity_improves(candidate: _CandidateStats, subset: _CandidateStats) -> bool:
    rate_gain = abs(candidate.rate_difference) - abs(subset.rate_difference)
    rr_gain = _rr_magnitude(candidate.relative_risk) - _rr_magnitude(subset.relative_risk)
    return rate_gain >= 0.05 or (
        _rr_magnitude(subset.relative_risk) > 0
        and _rr_magnitude(candidate.relative_risk)
        >= _rr_magnitude(subset.relative_risk) * 1.25
    )


def _relationship_id(target: _Target, predicates: Sequence[_Predicate], direction: str) -> str:
    payload = {
        "policy_version": POLICY_VERSION,
        "target_level": target.level,
        "category": target.category_key,
        "detail": target.detail_key or "",
        "direction": direction,
        "factors": [predicate.canonical() for predicate in predicates],
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    return f"rel_{digest[:32]}"


def _percentage(value: float) -> float:
    return round(value * 100.0, 4)


def _relationship_payload(
    evaluation: _CandidateEvaluation,
    observations: Sequence[_Observation],
    project_slug: str,
) -> dict[str, Any]:
    target = evaluation.target
    stats = evaluation.stats
    support_mask = stats.factor_mask & target.population_mask
    support_rows = [observation for observation in observations if (support_mask >> observation.index) & 1]
    relative_risk = None if not math.isfinite(stats.relative_risk) else round(stats.relative_risk, 8)
    odds_ratio = None if not math.isfinite(stats.odds_ratio) else round(stats.odds_ratio, 8)
    if evaluation.direction == "less_common" and stats.relative_risk > 0 and math.isfinite(stats.relative_risk):
        multiplier = 1.0 / stats.relative_risk
        effect_phrase = f"{multiplier:.1f}× less often"
    elif evaluation.direction == "more_common" and math.isfinite(stats.relative_risk):
        effect_phrase = f"{stats.relative_risk:.1f}× more often"
    else:
        effect_phrase = "more often" if evaluation.direction == "more_common" else "less often"
    factor_text = " and ".join(predicate.text for predicate in evaluation.predicates)
    if len(evaluation.predicates) > 1:
        present_phrase = "all factors were present"
        absent_phrase = "one or more factors were missing"
    else:
        present_phrase = "the condition was present"
        absent_phrase = "the condition was absent"
    statement = (
        f"{target.category if target.level == 'category' else target.detail} appeared {effect_phrase} "
        f"when {factor_text}. The issue rate was {_percentage(stats.observed_rate):.1f}% when "
        f"{present_phrase} versus {_percentage(stats.comparison_rate):.1f}% when {absent_phrase}."
    )
    breadth = {
        "runs": len({row.run_id for row in support_rows}),
        "items": len({(row.run_id, row.item_id) for row in support_rows}),
        "models": len({row.model for row in support_rows if row.model}),
        "dataset_versions": len({row.dataset_version for row in support_rows if row.dataset_version}),
    }
    return {
        "relationship_id": evaluation.relationship_id,
        "target_level": target.level,
        "category": target.category,
        "category_key": target.category_key,
        "detail": target.detail,
        "detail_key": target.detail_key,
        "direction": evaluation.direction,
        "arity": len(evaluation.predicates),
        "factors": [predicate.payload() for predicate in evaluation.predicates],
        "statement": statement,
        "support": stats.factor_count,
        "raw_execution_support": stats.factor_count,
        "target_support": stats.target_with,
        "comparison_support": stats.comparison_with,
        "breadth": breadth,
        "observed_rate": round(stats.observed_rate, 8),
        "comparison_rate": round(stats.comparison_rate, 8),
        "rate_difference": round(stats.rate_difference, 8),
        "relative_risk": relative_risk,
        "odds_ratio": odds_ratio,
        "p_value": stats.p_value,
        "q_value": stats.q_value,
        "coverage": round(stats.coverage, 8),
        "target_coverage": round(stats.target_coverage, 8),
        "comparison_coverage": round(stats.comparison_coverage, 8),
        "diagnosis_coverage": {
            "with_factor": round(stats.diagnosis_target_coverage, 8),
            "without_factor": round(stats.diagnosis_comparison_coverage, 8),
        },
        "drilldown_url": (
            f"/api/projects/{project_slug}/insights/relationships/"
            f"{evaluation.relationship_id}/occurrences"
        ),
    }


def _relationship_sort_key(relationship: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        float(relationship.get("q_value") if relationship.get("q_value") is not None else 1.0),
        -abs(float(relationship.get("rate_difference") or 0.0)),
        -int(relationship.get("support") or 0),
        int(relationship.get("arity") or 0),
        str(relationship.get("relationship_id") or ""),
    )


def _category_payload(
    category_key: str,
    observations: Sequence[_Observation],
    relationships: Sequence[dict[str, Any]],
    below_details: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    category_rows = [row for row in observations if row.category_key == category_key]
    category = next((row.category for row in category_rows if row.category), category_key)
    details = [
        {
            "detail": detail["detail"],
            "detail_key": detail["detail_key"],
            "count": detail["count"],
            "relationships": [],
        }
        for detail in below_details
        if detail["category_key"] == category_key
    ]
    return {
        "category": category,
        "category_key": category_key,
        "count": len(category_rows),
        "relationships": list(relationships),
        "detail_groups": details,
        "below_threshold_details": details,
    }


def _policy() -> dict[str, Any]:
    return {
        "version": POLICY_VERSION,
        "category_threshold": CATEGORY_THRESHOLD,
        "detail_threshold": DETAIL_THRESHOLD,
        "minimum_support": MIN_SUPPORT,
        "minimum_coverage": MIN_COVERAGE,
        "maximum_coverage_bias": MAX_COVERAGE_BIAS,
        "maximum_diagnosis_coverage_bias": MAX_DIAGNOSIS_COVERAGE_BIAS,
        "minimum_rate_difference": MIN_RATE_DIFFERENCE,
        "minimum_relative_risk": MIN_RELATIVE_RISK,
        "maximum_relative_risk": MAX_RELATIVE_RISK,
        "maximum_arity": MAX_ARITY,
        "fisher_alternative": "two-sided",
        "multiple_testing": "benjamini-hochberg across project candidates",
        "persistence": "none",
        "eligibility": "failed/error executions plus diagnosed passed executions for category targets",
    }


def _compute_analysis(db: Session, project: Any) -> _AnalysisBundle:
    scope_gate = _Gate()
    target_gate = _Gate()
    field_gate = _Gate()
    redundancy_gate = _Gate()
    coverage_gate = _Gate()
    generation_gate = _Gate()
    effect_gate = _Gate()
    reliability_gate = _Gate()
    complexity_gate = _Gate()
    subsumption_gate = _Gate()
    gates = {
        "scope_and_integrity": scope_gate,
        "target_support": target_gate,
        "field_safety": field_gate,
        "redundancy": redundancy_gate,
        "variation_and_exposure": _Gate(),
        "coverage_bias": coverage_gate,
        "candidate_generation": generation_gate,
        "abnormal_effect": effect_gate,
        "statistical_reliability": reliability_gate,
        "incremental_complexity": complexity_gate,
        "subsumption": subsumption_gate,
    }
    inventory = _Inventory()
    observations, total_potential, invalid_count = _build_observations(
        db, project.id, inventory, scope_gate
    )
    targets, below_details = _build_targets(observations, target_gate)
    predicates, predicate_bits, complete_bits = _build_predicates(
        observations, inventory, field_gate, redundancy_gate
    )
    candidates = _generate_candidate_specs(observations, predicates, predicate_bits)
    diagnosed_mask = sum((1 << observation.index) for observation in observations if observation.diagnosed)
    all_evaluations: list[_CandidateEvaluation] = []
    stats_by_target: dict[str, dict[frozenset[str], _CandidateStats]] = defaultdict(dict)
    candidate_key_sets: dict[tuple[str, frozenset[str]], tuple[_Predicate, ...]] = {}

    for target in targets:
        for predicate_tuple, factor_mask in candidates:
            generation_gate.enter()
            generation_gate.survive()
            variation_gate = gates["variation_and_exposure"]
            variation_gate.enter()
            factor_complete = complete_bits.get(predicate_tuple[0].field, 0)
            for predicate in predicate_tuple[1:]:
                factor_complete &= complete_bits.get(predicate.field, 0)
            stats = _candidate_stats(target, factor_mask, factor_complete, diagnosed_mask)
            stats_by_target[target.key][frozenset(predicate.key for predicate in predicate_tuple)] = stats
            candidate_key_sets[(target.key, frozenset(predicate.key for predicate in predicate_tuple))] = predicate_tuple
            if stats.factor_count < MIN_SUPPORT or (target.population_mask & ~factor_mask).bit_count() < MIN_SUPPORT:
                variation_gate.remove("insufficient_exposure")
                continue
            variation_gate.survive()
            coverage_gate.enter()
            coverage_delta = abs(stats.target_coverage - stats.comparison_coverage)
            diagnosis_delta = abs(stats.diagnosis_target_coverage - stats.diagnosis_comparison_coverage)
            if (
                stats.coverage < MIN_COVERAGE
                or stats.target_coverage < MIN_COVERAGE
                or stats.comparison_coverage < MIN_COVERAGE
            ):
                coverage_gate.remove("insufficient_field_coverage")
                continue
            if coverage_delta > MAX_COVERAGE_BIAS:
                coverage_gate.remove("coverage_bias")
                continue
            if target.level == "category" and (
                stats.diagnosis_target_coverage < MIN_COVERAGE
                or stats.diagnosis_comparison_coverage < MIN_COVERAGE
                or diagnosis_delta > MAX_DIAGNOSIS_COVERAGE_BIAS
            ):
                coverage_gate.remove("diagnosis_coverage_bias")
                continue
            coverage_gate.survive()
            effect_gate.enter()
            direction = _effect_direction(stats)
            if direction is None:
                effect_gate.remove("normal_or_weak_effect")
                continue
            effect_gate.survive()
            all_evaluations.append(
                _CandidateEvaluation(target, predicate_tuple, stats, direction)
            )

    # The p-value correction includes every candidate that made it through the
    # effect gate, including candidates that later fail q <= .05.
    p_values = [evaluation.stats.p_value if evaluation.stats.p_value is not None else 1.0 for evaluation in all_evaluations]
    q_values = _bh_adjust(p_values)
    reliable: list[_CandidateEvaluation] = []
    for evaluation, q_value in zip(all_evaluations, q_values):
        evaluation.stats.q_value = q_value
        reliability_gate.enter()
        if q_value > 0.05:
            reliability_gate.remove("not_significant_after_correction")
            continue
        reliability_gate.survive()
        reliable.append(evaluation)

    incremental: list[_CandidateEvaluation] = []
    for evaluation in reliable:
        complexity_gate.enter()
        if len(evaluation.predicates) > 1:
            keys = [predicate.key for predicate in evaluation.predicates]
            target_stats = stats_by_target[evaluation.target.key]
            failed = False
            for size in range(1, len(keys)):
                for subset_keys in itertools.combinations(keys, size):
                    subset_stats = target_stats.get(frozenset(subset_keys))
                    if subset_stats is not None and not _complexity_improves(evaluation.stats, subset_stats):
                        failed = True
                        break
                if failed:
                    break
            if failed:
                complexity_gate.remove("no_incremental_value")
                continue
        complexity_gate.survive()
        incremental.append(evaluation)

    # Subsumption is scoped to the same target and direction.  A shorter,
    # authoritative relationship wins when its execution support is virtually
    # identical to a more complex or duplicate relationship.
    incremental.sort(
        key=lambda evaluation: (
            evaluation.target.key,
            evaluation.direction,
            len(evaluation.predicates),
            sum(predicate.authority for predicate in evaluation.predicates),
            tuple(predicate.key for predicate in evaluation.predicates),
        )
    )
    survivors: list[_CandidateEvaluation] = []
    for evaluation in incremental:
        subsumption_gate.enter()
        current_mask = evaluation.stats.factor_mask & evaluation.target.population_mask
        current_count = current_mask.bit_count()
        redundant = False
        for existing in survivors:
            if existing.target.key != evaluation.target.key or existing.direction != evaluation.direction:
                continue
            existing_mask = existing.stats.factor_mask & existing.target.population_mask
            existing_count = existing_mask.bit_count()
            overlap = (current_mask & existing_mask).bit_count()
            if max(current_count, existing_count) and overlap / max(current_count, existing_count) >= 0.95:
                redundant = True
                break
        if redundant:
            subsumption_gate.remove("subsumed")
            continue
        subsumption_gate.survive()
        evaluation.relationship_id = _relationship_id(
            evaluation.target, evaluation.predicates, evaluation.direction
        )
        survivors.append(evaluation)

    relationships = [
        _relationship_payload(evaluation, observations, project.slug)
        for evaluation in survivors
    ]
    relationships.sort(key=_relationship_sort_key)
    relationship_by_id = {
        relationship["relationship_id"]: evaluation
        for relationship, evaluation in zip(
            [_relationship_payload(evaluation, observations, project.slug) for evaluation in survivors],
            survivors,
        )
    }
    # Recompute payloads once after sorting so the public map remains exactly
    # aligned with the internal evaluation used by occurrence drilldown.
    relationships_by_evaluation = {
        evaluation.relationship_id: _relationship_payload(evaluation, observations, project.slug)
        for evaluation in survivors
    }
    category_relationships: dict[str, list[dict[str, Any]]] = defaultdict(list)
    detail_relationships: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for evaluation in survivors:
        relation = relationships_by_evaluation[evaluation.relationship_id]
        if evaluation.target.level == "category":
            category_relationships[evaluation.target.category_key].append(relation)
        else:
            detail_relationships[evaluation.target.key].append(relation)
    for values in category_relationships.values():
        values.sort(key=_relationship_sort_key)
    for values in detail_relationships.values():
        values.sort(key=_relationship_sort_key)

    categories: list[dict[str, Any]] = []
    for category_key in sorted(set(category_relationships) | {target.category_key for target in targets if target.level == "detail" and target.key in detail_relationships}):
        category_relation_rows = category_relationships.get(category_key, [])
        detail_targets = [target for target in targets if target.level == "detail" and target.category_key == category_key and target.key in detail_relationships]
        category_rows = [row for row in observations if row.category_key == category_key]
        category = next((row.category for row in category_rows if row.category), category_key)
        detail_groups = []
        for target in sorted(detail_targets, key=lambda current: (current.detail or "").casefold()):
            detail_groups.append(
                {
                    "detail": target.detail,
                    "detail_key": target.detail_key,
                    "count": target.qualified_count,
                    "relationships": detail_relationships[target.key],
                }
            )
        categories.append(
            {
                "category": category,
                "category_key": category_key,
                "count": len(category_rows),
                "relationships": category_relation_rows,
                "detail_groups": detail_groups,
                "below_threshold_details": [
                    detail for detail in below_details if detail["category_key"] == category_key
                ],
            }
        )
    categories.sort(
        key=lambda category: (
            _relationship_sort_key(category["relationships"][0])
            if category["relationships"]
            else _relationship_sort_key(category["detail_groups"][0]["relationships"][0])
            if category["detail_groups"] and category["detail_groups"][0]["relationships"]
            else (1.0, 0, 0, 0, category["category_key"]),
            category["category"].casefold(),
        )
    )

    analyzed_mask = 0
    for observation in observations:
        if observation.diagnosed or observation.outcome in _FAILURE_OUTCOMES:
            analyzed_mask |= 1 << observation.index
    diagnosis_count = sum(1 for observation in observations if observation.diagnosed)
    eligible_count = len(observations)
    diagnosis_coverage = diagnosis_count / eligible_count if eligible_count else 0.0
    if diagnosis_count == 0:
        empty_state = "no_root_cause_diagnoses"
    elif not targets:
        empty_state = "diagnoses_below_threshold"
    elif not survivors and coverage_gate.reasons.get("insufficient_field_coverage", 0) + coverage_gate.reasons.get("coverage_bias", 0) + coverage_gate.reasons.get("diagnosis_coverage_bias", 0) > effect_gate.entered // 2:
        empty_state = "insufficient_coverage"
    elif not survivors:
        empty_state = "no_surviving_relationships"
    else:
        empty_state = None

    counts = {
        "total": total_potential,
        "eligible": eligible_count,
        "diagnosed": diagnosis_count,
        "analyzed": analyzed_mask.bit_count(),
        "diagnosis_coverage": round(diagnosis_coverage, 8),
        "surviving_candidates": len(relationships),
        "represented_categories": len(categories),
        "excluded_scope": invalid_count + max(0, total_potential - eligible_count - invalid_count),
    }
    payload = {
        "schema_version": SCHEMA_VERSION,
        "project": {"id": project.id, "slug": project.slug, "name": project.name},
        "generated_at": to_api_timestamp(utc_now_naive()),
        "policy": _policy(),
        "gate_policy": _policy(),
        "counts": counts,
        "field_inventory": inventory.payload(),
        "gates": {name: gate.payload() for name, gate in gates.items()},
        "categories": categories,
        "below_threshold_details": below_details,
        "empty_state": empty_state,
    }
    return _AnalysisBundle(payload, observations, relationship_by_id)


def build_relationship_analysis(db: Session, project: Any) -> dict[str, Any]:
    """Compute the complete project-wide relationship analysis on demand."""

    return _compute_analysis(db, project).payload


def build_relationship_occurrences(
    db: Session,
    project: Any,
    relationship_id: str,
    *,
    limit: int = 100,
    offset: int = 0,
) -> dict[str, Any] | None:
    """Return paginated evidence for a current relationship hash.

    ``None`` means that the ID is stale because the project changed or the
    requested relationship was never a survivor under the current policy.
    """

    bundle = _compute_analysis(db, project)
    evaluation = bundle.relationship_evaluations.get(relationship_id)
    if evaluation is None:
        return None
    support_mask = evaluation.stats.factor_mask & evaluation.target.population_mask
    rows = [
        observation
        for observation in bundle.observations
        if (support_mask >> observation.index) & 1
    ]
    rows.sort(
        key=lambda row: (
            row.run_timestamp or datetime.min,
            row.run_id,
            row.item_index,
            row.item_id,
            row.metric,
        )
    )
    page = rows[offset : offset + limit]
    target = evaluation.target
    predicate_keys = [predicate.key for predicate in evaluation.predicates]
    occurrence_rows = []
    for row in page:
        occurrence_rows.append(
            {
                "run_id": row.run_id,
                "run_name": row.run_name,
                "run_url": f"/projects/{project.slug}/runs/{row.run_id}",
                "timestamp": to_api_timestamp(row.run_timestamp),
                "item_id": row.item_id,
                "item_index": row.item_index,
                "metric": row.metric,
                "category": row.category,
                "detail": row.detail,
                "model": row.model,
                "dataset": row.dataset,
                "dataset_version": row.dataset_version,
                "outcome": row.outcome,
                "score": row.score,
                "factor_values": [
                    {
                        "key": key,
                        "present": all(
                            _predicate_matches(predicate, row.fields.get(predicate.field))
                            for predicate in evaluation.predicates
                            if predicate.key == key
                        ),
                    }
                    for key in predicate_keys
                ],
                "is_target": row.category_key == target.category_key
                and (target.level == "category" or row.detail_key == target.detail_key),
            }
        )
    relationship = _relationship_payload(evaluation, bundle.observations, project.slug)
    return {
        "schema_version": SCHEMA_VERSION,
        "relationship": relationship,
        "total": len(rows),
        "offset": offset,
        "limit": limit,
        "occurrences": occurrence_rows,
    }
