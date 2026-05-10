from __future__ import annotations

import csv
import io
import json
import logging
import math
import sys
from collections import defaultdict

csv.field_size_limit(sys.maxsize)
from typing import Any, Dict, Optional


def _sanitize_for_json(obj: Any) -> Any:
    """Replace NaN/Infinity with None so PostgreSQL JSON accepts the data."""
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        return None
    if isinstance(obj, dict):
        return {k: _sanitize_for_json(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize_for_json(v) for v in obj]
    return obj


logger = logging.getLogger(__name__)

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from qym_platform.auth import (
    Principal,
    require_api_key_principal,
    require_api_key_scope,
)
from qym_platform.datetime_utils import to_storage_utc, utc_now_naive
from qym_platform.db.models import (
    Project,
    Run,
    RunEvent,
    RunItem,
    RunItemScore,
    RunTraceAggregate,
    RunWorkflowStatus,
    Span,
)
from qym_platform.db.models import RunItemAttempt
from qym_platform.deps import get_db
from qym_platform.events import (
    ItemAttemptStartedPayload,
    ItemAttemptFinishedPayload,
    ItemCompletedPayload,
    ItemFailedPayload,
    ItemStartedPayload,
    MetadataUpdatePayload,
    MetricScoredPayload,
    RunCompletedPayload,
    RunHeartbeatPayload,
    RunEventV1,
    RunStartedPayload,
    SpanCompletedPayload,
)
from qym_platform.item_identity import (
    build_identity_fingerprint,
    looks_like_positional_item_id,
)
from qym_platform.services.run_lifecycle import (
    mark_run_running,
    mark_run_terminal,
    touch_run_event,
)
from qym_platform.settings import PlatformSettings


router = APIRouter(prefix="/v1", tags=["ingestion"])

_TRACE_LATENCY_FIELDS = {
    "llm": ("llm_duration_ms_total", "llm_duration_ms_count", "avg_llm_ms"),
    "tool": ("tool_duration_ms_total", "tool_duration_ms_count", "avg_tool_ms"),
    "retriever": (
        "retriever_duration_ms_total",
        "retriever_duration_ms_count",
        "avg_retriever_ms",
    ),
    "evaluator": (
        "evaluator_duration_ms_total",
        "evaluator_duration_ms_count",
        "avg_evaluator_ms",
    ),
    "top_level_chain": (
        "top_level_chain_duration_ms_total",
        "top_level_chain_duration_ms_count",
        "avg_top_level_chain_ms",
    ),
}


def _extract_reasoning_signal(attrs: Dict[str, Any]) -> Dict[str, Any]:
    """Return reasoning presence/tokens for a serialized LLM span."""
    has_reasoning_text = False
    reasoning_tokens = 0

    for key, value in (attrs or {}).items():
        if not value:
            continue
        if key.endswith(".reasoning"):
            has_reasoning_text = True
            break

    token_candidates = [
        attrs.get("llm.token_count.completion_details.reasoning"),
        attrs.get("gen_ai.usage.completion_tokens_details.reasoning_tokens"),
        attrs.get("gen_ai.usage.output_tokens_details.reasoning"),
        attrs.get("gen_ai.usage.reasoning_tokens"),
    ]
    for raw_value in token_candidates:
        if raw_value in (None, "", 0, "0"):
            continue
        try:
            reasoning_tokens = max(reasoning_tokens, int(float(raw_value)))
        except (ValueError, TypeError):
            continue

    output_value = attrs.get("output.value")
    if isinstance(output_value, str) and output_value:
        try:
            parsed = json.loads(output_value)
        except (TypeError, ValueError, json.JSONDecodeError):
            parsed = None
        if isinstance(parsed, dict):
            usage = parsed.get("usage")
            if isinstance(usage, dict):
                completion_details = usage.get("completion_tokens_details")
                if isinstance(completion_details, dict):
                    raw_reasoning_tokens = completion_details.get("reasoning_tokens")
                    if raw_reasoning_tokens not in (None, "", 0, "0"):
                        try:
                            reasoning_tokens = max(
                                reasoning_tokens, int(float(raw_reasoning_tokens))
                            )
                        except (ValueError, TypeError):
                            pass
            choices = parsed.get("choices")
            if isinstance(choices, list):
                for choice in choices:
                    if not isinstance(choice, dict):
                        continue
                    message = choice.get("message")
                    if isinstance(message, dict) and message.get("reasoning"):
                        has_reasoning_text = True
                        break

    has_reasoning_tokens = reasoning_tokens > 0
    return {
        "has_reasoning": has_reasoning_text or has_reasoning_tokens,
        "has_reasoning_tokens": has_reasoning_tokens,
        "reasoning_tokens": reasoning_tokens,
    }


def _empty_trace_bucket() -> Dict[str, Any]:
    bucket = {
        "span_count": 0,
        "tokens": 0,
        "cost": 0.0,
        "llm_calls": 0,
        "tool_calls": 0,
        "tool_errors": 0,
        "malformed_tool_calls": 0,
        "noisy_reasoning": 0,
        "provider_errors": 0,
        "has_reasoning": False,
        "has_reasoning_tokens": False,
        "reasoning_tokens": 0,
        "outer_scope_parent_span_ms": {},
        "outer_scope_parent_span_counts": {},
    }
    for total_key, count_key, _avg_key in _TRACE_LATENCY_FIELDS.values():
        bucket[total_key] = 0.0
        bucket[count_key] = 0
    return bucket


def _span_oi_kind(attrs: Dict[str, Any]) -> str:
    raw = str(
        (attrs or {}).get("openinference.span.kind", "")
        or (attrs or {}).get("ai.openinference.span.kind", "")
    ).upper()
    if raw == "RETRIEVE":
        return "RETRIEVER"
    return raw


def _span_usage_scope(attrs: Dict[str, Any]) -> str:
    return str((attrs or {}).get("qym.usage_scope", "") or "").lower()


def _trace_latency_average(bucket: Dict[str, Any], bucket_name: str) -> Optional[float]:
    total_key, count_key, _avg_key = _TRACE_LATENCY_FIELDS[bucket_name]
    total = float(bucket.get(total_key) or 0.0)
    count = int(bucket.get(count_key) or 0)
    if count <= 0:
        return None
    return total / count


def _trace_latency_average_from_buckets(
    item_buckets: list[dict[str, Any]], bucket_name: str
) -> Optional[float]:
    total_key, count_key, _avg_key = _TRACE_LATENCY_FIELDS[bucket_name]
    total = sum(float(bucket.get(total_key) or 0.0) for bucket in item_buckets)
    count = sum(int(bucket.get(count_key) or 0) for bucket in item_buckets)
    if count <= 0:
        return None
    return total / count


def _named_latency_averages_from_buckets(
    item_buckets: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    totals: dict[str, float] = defaultdict(float)
    counts: dict[str, int] = defaultdict(int)
    first_seen_order: dict[str, int] = {}

    for bucket in item_buckets:
        bucket_totals = bucket.get("outer_scope_parent_span_ms") or {}
        bucket_counts = bucket.get("outer_scope_parent_span_counts") or {}
        if not isinstance(bucket_totals, dict) or not isinstance(bucket_counts, dict):
            continue
        for name, total in bucket_totals.items():
            count = int(bucket_counts.get(name) or 0)
            if count <= 0:
                continue
            try:
                duration = float(total)
            except (TypeError, ValueError):
                continue
            if not math.isfinite(duration) or duration < 0:
                continue
            if name not in first_seen_order:
                first_seen_order[name] = len(first_seen_order)
            totals[name] += duration
            counts[name] += count

    averages: list[dict[str, Any]] = []
    for name, total in totals.items():
        count = counts.get(name, 0)
        if count <= 0:
            continue
        averages.append({"name": name, "avg_ms": total / count, "count": count})
    averages.sort(key=lambda item: first_seen_order.get(str(item.get("name")), 0))
    return averages


def _accumulate_trace_latency(
    bucket: Dict[str, Any], bucket_name: str, duration_ms: Any
) -> None:
    try:
        duration = float(duration_ms)
    except (TypeError, ValueError):
        return
    if not math.isfinite(duration) or duration < 0:
        return
    total_key, count_key, _avg_key = _TRACE_LATENCY_FIELDS[bucket_name]
    bucket[total_key] += duration
    bucket[count_key] += 1


def _accumulate_named_outer_scope_parent_latency(
    bucket: Dict[str, Any], name: str, duration_ms: Any
) -> None:
    name = str(name or "").strip()
    if not name:
        return
    try:
        duration = float(duration_ms)
    except (TypeError, ValueError):
        return
    if not math.isfinite(duration) or duration < 0:
        return
    totals = bucket.setdefault("outer_scope_parent_span_ms", {})
    counts = bucket.setdefault("outer_scope_parent_span_counts", {})
    if not isinstance(totals, dict) or not isinstance(counts, dict):
        return
    totals[name] = float(totals.get(name) or 0.0) + duration
    counts[name] = int(counts.get(name) or 0) + 1


def _public_trace_bucket(bucket: Dict[str, Any]) -> Dict[str, Any]:
    public = {
        "tokens": int(bucket.get("tokens") or 0),
        "cost": float(bucket.get("cost") or 0.0),
        "llm_calls": int(bucket.get("llm_calls") or 0),
        "tool_calls": int(bucket.get("tool_calls") or 0),
        "tool_errors": int(bucket.get("tool_errors") or 0),
        "malformed_tool_calls": int(bucket.get("malformed_tool_calls") or 0),
        "noisy_reasoning": int(bucket.get("noisy_reasoning") or 0),
        "provider_errors": int(bucket.get("provider_errors") or 0),
        "has_reasoning": bool(bucket.get("has_reasoning")),
        "has_reasoning_tokens": bool(bucket.get("has_reasoning_tokens")),
        "reasoning_tokens": int(bucket.get("reasoning_tokens") or 0),
    }
    for bucket_name, (_total_key, _count_key, avg_key) in _TRACE_LATENCY_FIELDS.items():
        public[avg_key] = _trace_latency_average(bucket, bucket_name)
    public["outer_scope_parent_spans"] = _named_latency_averages_from_buckets([bucket])
    return public


def _tool_call_attempts(bucket: Dict[str, Any]) -> int:
    """Return attempted tool calls, including malformed assistant responses."""
    return int(bucket.get("tool_calls") or 0) + int(
        bucket.get("malformed_tool_calls") or 0
    )


def _apply_response_classification(
    bucket: Dict[str, Any], attrs: Dict[str, Any]
) -> None:
    classification = attrs.get("qym.response.classification")
    if classification == "malformed_tool_call":
        bucket["malformed_tool_calls"] += 1
        bucket["tool_errors"] += 1
    elif classification == "noisy_reasoning":
        bucket["noisy_reasoning"] += 1
    elif classification == "provider_error":
        bucket["provider_errors"] += 1


def _trace_bucket_from_aggregate(agg: RunTraceAggregate) -> Dict[str, Any]:
    bucket = {
        "span_count": int(agg.span_count or 0),
        "tokens": int(agg.tokens or 0),
        "cost": float(agg.cost or 0.0),
        "llm_calls": int(agg.llm_calls or 0),
        "tool_calls": int(agg.tool_calls or 0),
        "tool_errors": int(agg.tool_errors or 0),
        "malformed_tool_calls": int(getattr(agg, "malformed_tool_calls", 0) or 0),
        "noisy_reasoning": int(getattr(agg, "noisy_reasoning", 0) or 0),
        "provider_errors": int(getattr(agg, "provider_errors", 0) or 0),
        "has_reasoning": bool(agg.has_reasoning),
        "has_reasoning_tokens": bool(agg.has_reasoning_tokens),
        "reasoning_tokens": int(agg.reasoning_tokens or 0),
    }
    for total_key, count_key, _avg_key in _TRACE_LATENCY_FIELDS.values():
        bucket[total_key] = 0.0
        bucket[count_key] = 0
    return bucket


def _apply_span_to_bucket(
    bucket: Dict[str, Any],
    *,
    attributes: Dict[str, Any],
    status: Optional[str],
    duration_ms: Any = None,
    parent_oi_kind: Optional[str] = None,
    exclude_usage: bool = False,
) -> None:
    bucket["span_count"] += 1
    attrs = attributes or {}
    if exclude_usage or _span_usage_scope(attrs) == "metric":
        return

    oi_kind = _span_oi_kind(attrs)
    if oi_kind == "LLM":
        bucket["llm_calls"] += 1
        _accumulate_trace_latency(bucket, "llm", duration_ms)
        tokens = attrs.get("llm.token_count.total") or attrs.get(
            "gen_ai.usage.total_tokens"
        )
        if tokens is not None:
            try:
                bucket["tokens"] += int(float(tokens))
            except (ValueError, TypeError):
                pass
        cost = attrs.get("llm.cost.total")
        if cost is not None:
            try:
                bucket["cost"] += float(cost)
            except (ValueError, TypeError):
                pass
        reasoning_signal = _extract_reasoning_signal(attrs)
        bucket["has_reasoning"] = bucket["has_reasoning"] or bool(
            reasoning_signal["has_reasoning"]
        )
        bucket["has_reasoning_tokens"] = bucket["has_reasoning_tokens"] or bool(
            reasoning_signal["has_reasoning_tokens"]
        )
        bucket["reasoning_tokens"] += int(reasoning_signal["reasoning_tokens"] or 0)
    elif oi_kind == "TOOL":
        bucket["tool_calls"] += 1
        _accumulate_trace_latency(bucket, "tool", duration_ms)
        if (status or "").upper() == "ERROR":
            bucket["tool_errors"] += 1
    elif oi_kind == "RETRIEVER":
        _accumulate_trace_latency(bucket, "retriever", duration_ms)
    elif oi_kind == "EVALUATOR":
        _accumulate_trace_latency(bucket, "evaluator", duration_ms)
    elif oi_kind == "CHAIN" and parent_oi_kind != "CHAIN":
        _accumulate_trace_latency(bucket, "top_level_chain", duration_ms)

    if oi_kind != "TOOL":
        _apply_response_classification(bucket, attrs)


def _build_trace_buckets_from_spans(spans: list[Span]) -> Dict[str, Dict[str, Any]]:
    spans_by_trace: Dict[str, list[Span]] = defaultdict(list)
    for span in spans:
        spans_by_trace[span.trace_id].append(span)

    trace_buckets: Dict[str, Dict[str, Any]] = {}
    for trace_id, trace_spans in spans_by_trace.items():
        bucket = _empty_trace_bucket()
        spans_by_id = {span.span_id: span for span in trace_spans}
        metric_root_ids = {
            span.span_id
            for span in trace_spans
            if span.name == "eval_metrics"
            or _span_usage_scope(span.attributes or {}) == "metric"
        }
        metric_descendant_ids: set[str] = set()

        def _is_metric_descendant(span: Span) -> bool:
            parent_id = span.parent_span_id
            seen: set[str] = set()
            while parent_id:
                if parent_id in metric_root_ids:
                    return True
                if parent_id in seen:
                    return False
                seen.add(parent_id)
                parent = spans_by_id.get(parent_id)
                if parent is None:
                    return False
                parent_id = parent.parent_span_id
            return False

        for span in trace_spans:
            if _span_usage_scope(span.attributes or {}) == "metric" or _is_metric_descendant(
                span
            ):
                metric_descendant_ids.add(span.span_id)

        roots = [
            span
            for span in trace_spans
            if not span.parent_span_id or span.parent_span_id not in spans_by_id
        ]
        non_metric_roots = [
            span for span in roots if span.span_id not in metric_descendant_ids
        ]
        if len(non_metric_roots) == 1:
            root = non_metric_roots[0]
            outer_scope_parent_spans = [
                span
                for span in trace_spans
                if span.parent_span_id == root.span_id
                and span.span_id not in metric_descendant_ids
                and span.span_id not in metric_root_ids
            ]
        else:
            outer_scope_parent_spans = [
                span for span in non_metric_roots if span.span_id not in metric_root_ids
            ]
        for span in outer_scope_parent_spans:
            oi_kind = _span_oi_kind(span.attributes or {})
            if oi_kind in {"LLM", "TOOL", "RETRIEVER"}:
                continue
            _accumulate_named_outer_scope_parent_latency(
                bucket, span.name, span.duration_ms
            )

        for span in trace_spans:
            parent = spans_by_id.get(span.parent_span_id or "")
            parent_oi_kind = _span_oi_kind(parent.attributes or {}) if parent else None
            _apply_span_to_bucket(
                bucket,
                attributes=span.attributes or {},
                status=span.status,
                duration_ms=span.duration_ms,
                parent_oi_kind=parent_oi_kind,
                exclude_usage=span.span_id in metric_descendant_ids,
            )
        trace_buckets[trace_id] = bucket
    return trace_buckets


def _build_run_trace_stats(item_buckets: list[dict[str, Any]]) -> Dict[str, Any]:
    if not item_buckets:
        return {"has_spans": False}

    n = len(item_buckets)
    total_tool_errors = sum(int(b.get("tool_errors") or 0) for b in item_buckets)
    total_tool_attempts = sum(_tool_call_attempts(b) for b in item_buckets)
    tool_success_rate = (
        (1 - total_tool_errors / total_tool_attempts)
        if total_tool_attempts > 0
        else None
    )
    trace_stats = {
        "avg_tokens": sum(int(b.get("tokens") or 0) for b in item_buckets) / n,
        "avg_llm_calls": sum(int(b.get("llm_calls") or 0) for b in item_buckets) / n,
        "avg_tool_calls": sum(int(b.get("tool_calls") or 0) for b in item_buckets) / n,
        "tool_success_rate": tool_success_rate,
        "total_malformed_tool_calls": sum(
            int(b.get("malformed_tool_calls") or 0) for b in item_buckets
        ),
        "total_noisy_reasoning": sum(
            int(b.get("noisy_reasoning") or 0) for b in item_buckets
        ),
        "total_provider_errors": sum(
            int(b.get("provider_errors") or 0) for b in item_buckets
        ),
        "has_reasoning": any(bool(b.get("has_reasoning")) for b in item_buckets),
        "has_reasoning_tokens": any(
            bool(b.get("has_reasoning_tokens")) for b in item_buckets
        ),
        "avg_reasoning_tokens": sum(
            int(b.get("reasoning_tokens") or 0) for b in item_buckets
        )
        / n,
        "has_spans": True,
    }
    for bucket_name, (_total_key, _count_key, avg_key) in _TRACE_LATENCY_FIELDS.items():
        trace_stats[avg_key] = _trace_latency_average_from_buckets(
            item_buckets, bucket_name
        )
    trace_stats["outer_scope_parent_spans"] = _named_latency_averages_from_buckets(
        item_buckets
    )
    return trace_stats


def _refresh_live_trace_stats(db: Session, run: Run) -> None:
    db.flush()
    items = db.query(RunItem).filter(RunItem.run_id == run.id).all()
    trace_ids = sorted({item.trace_id for item in items if item.trace_id})
    trace_buckets: Dict[str, Dict[str, Any]] = {}
    if trace_ids:
        spans = (
            db.query(Span)
            .filter(Span.run_id == run.id, Span.trace_id.in_(trace_ids))
            .all()
        )
        trace_buckets = _build_trace_buckets_from_spans(spans)

    item_buckets: list[dict[str, Any]] = []
    for item in items:
        bucket = trace_buckets.get(item.trace_id or "")
        md = dict(item.item_metadata) if isinstance(item.item_metadata, dict) else {}
        if bucket and int(bucket.get("span_count") or 0) > 0:
            md["trace_stats"] = _sanitize_for_json(_public_trace_bucket(bucket))
            item_buckets.append(bucket)
        else:
            md.pop("trace_stats", None)
        item.item_metadata = _sanitize_for_json(md)

    current = dict(run.run_metadata) if isinstance(run.run_metadata, dict) else {}
    current["trace_stats"] = _build_run_trace_stats(item_buckets)
    run.run_metadata = _sanitize_for_json(current)


def _upsert_trace_aggregate(
    db: Session, run_id: str, payload: SpanCompletedPayload
) -> None:
    agg = (
        db.query(RunTraceAggregate)
        .filter(
            RunTraceAggregate.run_id == run_id,
            RunTraceAggregate.trace_id == payload.trace_id,
        )
        .first()
    )
    if not agg:
        agg = RunTraceAggregate(run_id=run_id, trace_id=payload.trace_id)
        db.add(agg)
        db.flush()

    spans = (
        db.query(Span)
        .filter(Span.run_id == run_id, Span.trace_id == payload.trace_id)
        .all()
    )
    bucket = _build_trace_buckets_from_spans(spans).get(
        payload.trace_id, _empty_trace_bucket()
    )
    agg.span_count = int(bucket["span_count"])
    agg.tokens = int(bucket["tokens"])
    agg.cost = float(bucket["cost"])
    agg.llm_calls = int(bucket["llm_calls"])
    agg.tool_calls = int(bucket["tool_calls"])
    agg.tool_errors = int(bucket["tool_errors"])
    agg.malformed_tool_calls = int(bucket["malformed_tool_calls"])
    agg.noisy_reasoning = int(bucket["noisy_reasoning"])
    agg.provider_errors = int(bucket["provider_errors"])
    agg.has_reasoning = bool(bucket["has_reasoning"])
    agg.has_reasoning_tokens = bool(bucket["has_reasoning_tokens"])
    agg.reasoning_tokens = int(bucket["reasoning_tokens"])


def _store_trace_stats(db: Session, run: Run) -> None:
    """Compute trace metrics from stored OTEL spans and persist them.

    Stores run-level stats in run.run_metadata["trace_stats"] and
    per-item stats in each RunItem.item_metadata["trace_stats"].
    Called once when a run completes.
    """
    spans = db.query(Span).filter(Span.run_id == run.id).all()
    if not spans:
        logger.warning("_store_trace_stats: no spans found for run %s", run.id)
        return
    logger.info("_store_trace_stats: found %d spans for run %s", len(spans), run.id)

    # Map last-attempt trace_id -> item
    items = (
        db.query(RunItem)
        .filter(RunItem.run_id == run.id, RunItem.trace_id.isnot(None))
        .all()
    )
    # Group spans by trace_id and compute per-item stats
    trace_buckets = _build_trace_buckets_from_spans(spans)

    # Reconcile persistent per-trace aggregates with final span-derived truth.
    db.query(RunTraceAggregate).filter(RunTraceAggregate.run_id == run.id).delete(
        synchronize_session=False
    )
    for trace_id, bucket in trace_buckets.items():
        db.add(
            RunTraceAggregate(
                run_id=run.id,
                trace_id=trace_id,
                span_count=int(bucket["span_count"]),
                tokens=int(bucket["tokens"]),
                cost=float(bucket["cost"]),
                llm_calls=int(bucket["llm_calls"]),
                tool_calls=int(bucket["tool_calls"]),
                tool_errors=int(bucket["tool_errors"]),
                malformed_tool_calls=int(bucket["malformed_tool_calls"]),
                noisy_reasoning=int(bucket["noisy_reasoning"]),
                provider_errors=int(bucket["provider_errors"]),
                has_reasoning=bool(bucket["has_reasoning"]),
                has_reasoning_tokens=bool(bucket["has_reasoning_tokens"]),
                reasoning_tokens=int(bucket["reasoning_tokens"]),
            )
        )

    # Store per-item stats from the last-attempt trace only.
    item_buckets: list[dict[str, Any]] = []
    for item in items:
        trace_id = item.trace_id or ""
        bucket = trace_buckets.get(trace_id)
        md = dict(item.item_metadata) if isinstance(item.item_metadata, dict) else {}
        if bucket is not None and int(bucket.get("span_count") or 0) > 0:
            sanitized = _sanitize_for_json(_public_trace_bucket(bucket))
            md["trace_stats"] = sanitized
            item_buckets.append(bucket)
        else:
            md.pop("trace_stats", None)
        item.item_metadata = md

    current = dict(run.run_metadata) if isinstance(run.run_metadata, dict) else {}
    current["trace_stats"] = _build_run_trace_stats(item_buckets)
    run.run_metadata = _sanitize_for_json(current)


class CreateRunRequest(BaseModel):
    external_run_id: Optional[str] = None
    task: str
    dataset: str
    model: Optional[str] = None
    metrics: list[str] = Field(default_factory=list)
    run_metadata: Dict[str, Any] = Field(default_factory=dict)
    run_config: Dict[str, Any] = Field(default_factory=dict)


_PAYLOAD_TYPE = {
    "run_started": RunStartedPayload,
    "item_started": ItemStartedPayload,
    "item_attempt_started": ItemAttemptStartedPayload,
    "item_attempt_finished": ItemAttemptFinishedPayload,
    "metric_scored": MetricScoredPayload,
    "item_completed": ItemCompletedPayload,
    "item_failed": ItemFailedPayload,
    "run_completed": RunCompletedPayload,
    "run_heartbeat": RunHeartbeatPayload,
    "metadata_update": MetadataUpdatePayload,
    "span_completed": SpanCompletedPayload,
}


def _build_item_meta(ts_ms, retry_count=0):
    md = {}
    if ts_ms:
        md["task_started_at_ms"] = ts_ms
    if retry_count > 0:
        md["retry_count"] = retry_count
    return md


@router.post("/runs")
def create_run(
    req: CreateRunRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_api_key_principal),
) -> Dict[str, Any]:
    require_api_key_scope(principal, "runs:write")
    if not principal.project_id:
        raise HTTPException(status_code=403, detail="API key is not bound to a project")
    run = Run(
        project_id=principal.project_id,
        external_run_id=req.external_run_id,
        created_by_user_id=principal.user.id,
        owner_user_id=principal.user.id,
        task=req.task,
        dataset=req.dataset,
        model=req.model,
        metrics=req.metrics,
        run_metadata=req.run_metadata,
        run_config=req.run_config,
        status=RunWorkflowStatus.RUNNING,
        started_at=utc_now_naive(),
        last_event_at=utc_now_naive(),
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    settings = PlatformSettings()
    project = db.query(Project).filter(Project.id == run.project_id).first()
    if project and project.slug:
        live_path = f"/projects/{project.slug}/runs/{run.id}"
    else:
        live_path = f"/run/{run.id}"
    live_url = f"{settings.base_url.rstrip('/')}{live_path}"
    return {"run_id": run.id, "live_url": live_url}


@router.post("/runs/{run_id}/events")
async def ingest_events(
    run_id: str,
    request: Request,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_api_key_principal),
) -> JSONResponse:
    require_api_key_scope(principal, "runs:write")
    run = db.query(Run).filter(Run.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    if run.deleted_at is not None:
        raise HTTPException(
            status_code=410, detail=f"Run was deleted on {run.deleted_at.isoformat()}"
        )
    if run.owner_user_id != principal.user.id:
        raise HTTPException(status_code=403, detail="Forbidden")
    if principal.project_id and run.project_id != principal.project_id:
        raise HTTPException(status_code=403, detail="Forbidden")

    item_cache: Dict[str, Optional[RunItem]] = {}
    attempt_cache: Dict[tuple[str, int], Optional[RunItemAttempt]] = {}
    score_cache: Dict[tuple[str, str], Optional[RunItemScore]] = {}

    def _get_item(item_id: str) -> Optional[RunItem]:
        if item_id in item_cache:
            return item_cache[item_id]
        item = (
            db.query(RunItem)
            .filter(RunItem.run_id == run_id, RunItem.item_id == item_id)
            .first()
        )
        item_cache[item_id] = item
        return item

    def _remember_item(item: RunItem) -> RunItem:
        item_cache[item.item_id] = item
        return item

    def _get_score(item_id: str, metric_name: str) -> Optional[RunItemScore]:
        key = (item_id, metric_name)
        if key in score_cache:
            return score_cache[key]
        score = (
            db.query(RunItemScore)
            .filter(
                RunItemScore.run_id == run_id,
                RunItemScore.item_id == item_id,
                RunItemScore.metric_name == metric_name,
            )
            .first()
        )
        score_cache[key] = score
        return score

    def _remember_score(score: RunItemScore) -> RunItemScore:
        score_cache[(score.item_id, score.metric_name)] = score
        return score

    def _get_attempt(item_id: str, attempt_number: int) -> Optional[RunItemAttempt]:
        key = (item_id, attempt_number)
        if key in attempt_cache:
            return attempt_cache[key]
        attempt = (
            db.query(RunItemAttempt)
            .filter(
                RunItemAttempt.run_id == run_id,
                RunItemAttempt.item_id == item_id,
                RunItemAttempt.attempt_number == attempt_number,
            )
            .first()
        )
        attempt_cache[key] = attempt
        return attempt

    def _remember_attempt(attempt: RunItemAttempt) -> RunItemAttempt:
        attempt_cache[(attempt.item_id, attempt.attempt_number)] = attempt
        return attempt

    # Read NDJSON stream
    body = await request.body()
    try:
        text = body.decode("utf-8")
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid encoding")

    applied = 0
    skipped = 0
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            raw = json.loads(line)
            evt = RunEventV1.model_validate(raw)
        except Exception as e:
            # Skip malformed events instead of rejecting the entire batch.
            # One bad span_completed must never take down an item_completed.
            logger.warning("Skipping malformed event for run %s: %s", run_id, e)
            continue
        if str(evt.run_id) != run_id:
            # run_id mismatch is a real error — skip this event
            logger.warning("Skipping event with run_id mismatch for run %s", run_id)
            continue

        existing = (
            db.query(RunEvent)
            .filter(RunEvent.run_id == run_id, RunEvent.event_id == str(evt.event_id))
            .first()
        )
        if existing:
            skipped += 1
            continue

        # Store event (optional but useful)
        db.add(
            RunEvent(
                run_id=run_id,
                event_id=str(evt.event_id),
                sequence=evt.sequence,
                type=evt.type,
                sent_at=evt.sent_at,
                payload=raw.get("payload") or {},
            )
        )

        # Apply side-effects into normalized tables
        # Parse payload explicitly based on event type to avoid Union ambiguity
        raw_payload = raw.get("payload") or {}
        payload_cls = _PAYLOAD_TYPE.get(evt.type)
        payload = (
            payload_cls.model_validate(raw_payload) if payload_cls else evt.payload
        )
        logger.debug(
            "Ingest run=%s type=%s payload_type=%s",
            run_id,
            evt.type,
            type(payload).__name__,
        )
        touch_run_event(run, evt.sent_at)

        if isinstance(payload, RunStartedPayload):
            run.external_run_id = payload.external_run_id
            run.task = payload.task
            run.dataset = payload.dataset
            run.model = payload.model
            run.metrics = payload.metrics
            md = _sanitize_for_json(dict(payload.run_metadata or {}))
            if payload.total_items is not None:
                md["total_items"] = int(payload.total_items)
            run.run_metadata = md
            run.run_config = _sanitize_for_json(payload.run_config)
            run.started_at = to_storage_utc(payload.started_at)
            mark_run_running(run)
            logger.debug("Run %s status -> RUNNING", run_id)

        elif isinstance(payload, RunHeartbeatPayload):
            mark_run_running(run)
            logger.debug("Run %s heartbeat observed", run_id)

        elif isinstance(payload, ItemStartedPayload):
            mark_run_running(run)
            item = _get_item(payload.item_id)
            if not item:
                item = _remember_item(
                    RunItem(
                        run_id=run_id,
                        item_id=payload.item_id,
                        index=payload.index,
                        input=_sanitize_for_json(payload.input),
                        expected=_sanitize_for_json(payload.expected),
                        item_metadata=_sanitize_for_json(payload.item_metadata),
                    )
                )
                db.add(item)
            else:
                item.index = payload.index
                item.input = _sanitize_for_json(payload.input)
                item.expected = _sanitize_for_json(payload.expected)
                item.item_metadata = _sanitize_for_json(payload.item_metadata)

        elif isinstance(payload, ItemAttemptStartedPayload):
            mark_run_running(run)
            item = _get_item(payload.item_id)
            if not item:
                item = _remember_item(
                    RunItem(
                        run_id=run_id,
                        item_id=payload.item_id,
                        index=payload.index if payload.index is not None else 0,
                        input={},
                        expected=None,
                        item_metadata=_build_item_meta(payload.task_started_at_ms),
                        trace_id=payload.trace_id,
                        trace_url=payload.trace_url,
                    )
                )
                db.add(item)
            else:
                if item.index == 0 and payload.index is not None and payload.index != 0:
                    item.index = payload.index
                item.trace_id = payload.trace_id
                item.trace_url = payload.trace_url
                md = dict(item.item_metadata or {})
                if payload.task_started_at_ms:
                    md["task_started_at_ms"] = payload.task_started_at_ms
                if md != (item.item_metadata or {}):
                    item.item_metadata = _sanitize_for_json(md)
            try:
                _refresh_live_trace_stats(db, run)
            except Exception:
                logger.warning(
                    "Failed to refresh live trace stats for run %s",
                    run_id,
                    exc_info=True,
                )

        elif isinstance(payload, ItemAttemptFinishedPayload):
            mark_run_running(run)
            attempt = _get_attempt(payload.item_id, payload.attempt_number)
            if not attempt:
                attempt = _remember_attempt(
                    RunItemAttempt(
                        run_id=run_id,
                        item_id=payload.item_id,
                        attempt_number=payload.attempt_number,
                        status=payload.status,
                        latency_ms=payload.latency_ms,
                        task_started_at_ms=payload.task_started_at_ms,
                        trace_id=payload.trace_id,
                        trace_url=payload.trace_url,
                        error=payload.error,
                        is_last_attempt=payload.is_last_attempt,
                    )
                )
                db.add(attempt)
            else:
                attempt.status = payload.status
                attempt.latency_ms = payload.latency_ms
                attempt.task_started_at_ms = payload.task_started_at_ms
                attempt.trace_id = payload.trace_id
                attempt.trace_url = payload.trace_url
                attempt.error = payload.error
                attempt.is_last_attempt = payload.is_last_attempt
            if payload.is_last_attempt:
                (
                    db.query(RunItemAttempt)
                    .filter(
                        RunItemAttempt.run_id == run_id,
                        RunItemAttempt.item_id == payload.item_id,
                        RunItemAttempt.attempt_number != payload.attempt_number,
                        RunItemAttempt.is_last_attempt.is_(True),
                    )
                    .update({"is_last_attempt": False}, synchronize_session=False)
                )

        elif isinstance(payload, MetricScoredPayload):
            mark_run_running(run)
            score = _get_score(payload.item_id, payload.metric_name)
            if not score:
                score = _remember_score(
                    RunItemScore(
                        run_id=run_id,
                        item_id=payload.item_id,
                        metric_name=payload.metric_name,
                        score_numeric=payload.score_numeric,
                        score_raw=_sanitize_for_json(payload.score_raw),
                        meta=_sanitize_for_json(payload.meta),
                        label=payload.label,
                        explanation=payload.explanation,
                    )
                )
                db.add(score)
            else:
                score.score_numeric = payload.score_numeric
                score.score_raw = _sanitize_for_json(payload.score_raw)
                score.meta = _sanitize_for_json(payload.meta)
                score.label = payload.label
                score.explanation = payload.explanation

        elif isinstance(payload, ItemCompletedPayload):
            mark_run_running(run)
            # Determine task_started_at_ms: prefer explicit value from SDK,
            # fall back to event sent_at minus latency_ms for older SDKs.
            ts_ms = payload.task_started_at_ms
            if ts_ms is None and payload.latency_ms and evt.sent_at:
                try:
                    ts_ms = int(evt.sent_at.timestamp() * 1000 - payload.latency_ms)
                except Exception:
                    pass

            item = _get_item(payload.item_id)
            if not item:
                item = _remember_item(
                    RunItem(
                        run_id=run_id,
                        item_id=payload.item_id,
                        index=payload.index if payload.index is not None else 0,
                        input={},
                        expected=None,
                        output=_sanitize_for_json(payload.output),
                        error=None,
                        latency_ms=payload.latency_ms,
                        retry_count=payload.retry_count,
                        trace_id=payload.trace_id,
                        trace_url=payload.trace_url,
                        item_metadata=_build_item_meta(ts_ms, payload.retry_count),
                    )
                )
                db.add(item)
            else:
                # Update index if it was 0 (placeholder) and we now have the real index
                if item.index == 0 and payload.index is not None and payload.index != 0:
                    item.index = payload.index
                item.output = _sanitize_for_json(payload.output)
                item.error = None
                item.latency_ms = payload.latency_ms
                item.retry_count = payload.retry_count
                item.trace_id = payload.trace_id
                item.trace_url = payload.trace_url
                # Merge metadata into item_metadata
                md = dict(item.item_metadata or {})
                if ts_ms:
                    md["task_started_at_ms"] = ts_ms
                if payload.retry_count > 0:
                    md["retry_count"] = payload.retry_count
                else:
                    md.pop("retry_count", None)
                if md != (item.item_metadata or {}):
                    item.item_metadata = _sanitize_for_json(md)
            try:
                _refresh_live_trace_stats(db, run)
            except Exception:
                logger.warning(
                    "Failed to refresh live trace stats for run %s",
                    run_id,
                    exc_info=True,
                )

        elif isinstance(payload, ItemFailedPayload):
            mark_run_running(run)
            item = _get_item(payload.item_id)
            if not item:
                item = _remember_item(
                    RunItem(
                        run_id=run_id,
                        item_id=payload.item_id,
                        index=payload.index if payload.index is not None else 0,
                        input={},
                        expected=None,
                        output=None,
                        error=payload.error,
                        latency_ms=payload.latency_ms,
                        retry_count=payload.retry_count,
                        trace_id=payload.trace_id,
                        trace_url=payload.trace_url,
                        item_metadata=_build_item_meta(
                            payload.task_started_at_ms, payload.retry_count
                        ),
                    )
                )
                db.add(item)
            else:
                # Update index if it was 0 (placeholder) and we now have the real index
                if item.index == 0 and payload.index is not None and payload.index != 0:
                    item.index = payload.index
                item.error = payload.error
                item.latency_ms = payload.latency_ms
                item.retry_count = payload.retry_count
                item.trace_id = payload.trace_id
                item.trace_url = payload.trace_url
                md = dict(item.item_metadata or {})
                if payload.task_started_at_ms:
                    md["task_started_at_ms"] = payload.task_started_at_ms
                if payload.retry_count > 0:
                    md["retry_count"] = payload.retry_count
                else:
                    md.pop("retry_count", None)
                if md != (item.item_metadata or {}):
                    item.item_metadata = _sanitize_for_json(md)
            try:
                _refresh_live_trace_stats(db, run)
            except Exception:
                logger.warning(
                    "Failed to refresh live trace stats for run %s",
                    run_id,
                    exc_info=True,
                )

        elif isinstance(payload, RunCompletedPayload):
            _FINAL_STATUS = {
                "COMPLETED": RunWorkflowStatus.COMPLETED,
                "FAILED": RunWorkflowStatus.FAILED,
                "STOPPED": RunWorkflowStatus.STOPPED,
            }
            mark_run_terminal(
                run,
                _FINAL_STATUS.get(payload.final_status, RunWorkflowStatus.FAILED),
                ended_at=payload.ended_at,
            )
            logger.debug("Run %s status -> %s", run_id, payload.final_status)
            # Allow the client to attach final metadata (e.g., langfuse_url) at completion time.
            try:
                md = (
                    payload.summary.get("run_metadata")
                    if isinstance(payload.summary, dict)
                    else None
                )
                if isinstance(md, dict) and md:
                    current = (
                        run.run_metadata if isinstance(run.run_metadata, dict) else {}
                    )
                    run.run_metadata = _sanitize_for_json({**current, **md})
            except Exception:
                pass

            # ⚡ Compute and store trace stats from OTEL spans
            try:
                db.flush()  # ensure all spans from this batch are visible
                _store_trace_stats(db, run)
            except Exception:
                logger.warning(
                    "Failed to compute trace stats for run %s", run_id, exc_info=True
                )

        elif isinstance(payload, MetadataUpdatePayload):
            mark_run_running(run)
            # Update run metadata mid-flight (e.g., langfuse_url once available)
            current = run.run_metadata if isinstance(run.run_metadata, dict) else {}
            updates = {}
            if payload.langfuse_url:
                updates["langfuse_url"] = payload.langfuse_url
            if payload.langfuse_dataset_id:
                updates["langfuse_dataset_id"] = payload.langfuse_dataset_id
            if payload.langfuse_run_id:
                updates["langfuse_run_id"] = payload.langfuse_run_id
            if payload.extra:
                updates.update(payload.extra)
            if updates:
                run.run_metadata = _sanitize_for_json({**current, **updates})

        elif isinstance(payload, SpanCompletedPayload):
            mark_run_running(run)
            # Store OTEL span data for native trace viewing.
            # Wrapped in a savepoint so a span-storage failure (e.g. pending
            # migration) never rolls back the rest of the batch (items, metrics).
            span_inserted = False
            try:
                nested = db.begin_nested()
                existing = (
                    db.query(Span)
                    .filter(
                        Span.run_id == run_id,
                        Span.span_id == payload.span_id,
                    )
                    .first()
                )
                if not existing:
                    span_kwargs = dict(
                        run_id=run_id,
                        trace_id=payload.trace_id,
                        span_id=payload.span_id,
                        parent_span_id=payload.parent_span_id,
                        name=payload.name,
                        kind=payload.kind,
                        start_time_ns=payload.start_time_ns,
                        end_time_ns=payload.end_time_ns,
                        duration_ms=payload.duration_ms,
                        status=payload.status,
                        attributes=_sanitize_for_json(payload.attributes),
                        events=_sanitize_for_json(payload.events),
                        links=_sanitize_for_json(payload.links),
                    )
                    db.add(Span(**span_kwargs))
                    span_inserted = True
                nested.commit()
            except Exception as e:
                logger.warning("Span storage failed for run %s: %s", run_id, e)
            if span_inserted:
                try:
                    nested = db.begin_nested()
                    _upsert_trace_aggregate(db, run_id, payload)
                    _refresh_live_trace_stats(db, run)
                    nested.commit()
                except Exception as e:
                    logger.warning(
                        "Live trace aggregation failed for run %s: %s", run_id, e
                    )

        applied += 1

    db.commit()
    return JSONResponse({"ok": True, "applied": applied, "skipped": skipped})


@router.post("/runs:upload")
async def upload_run(
    file: UploadFile = File(...),
    task: str = Form(...),
    dataset: str = Form(...),
    model: Optional[str] = Form(default=None),
    external_run_id: Optional[str] = Form(default=None),
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_api_key_principal),
) -> Dict[str, Any]:
    """Upload a saved results file (CSV/JSON/XLSX) and ingest into DB."""
    require_api_key_scope(principal, "runs:write")
    if not principal.project_id:
        raise HTTPException(status_code=403, detail="API key is not bound to a project")
    filename = (file.filename or "").lower()
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Empty upload")

    # Create run as completed by default (file upload is post-hoc)
    run = Run(
        project_id=principal.project_id,
        external_run_id=external_run_id,
        created_by_user_id=principal.user.id,
        owner_user_id=principal.user.id,
        task=task,
        dataset=dataset,
        model=model,
        metrics=[],
        run_metadata={},
        run_config={},
        status=RunWorkflowStatus.COMPLETED,
        started_at=utc_now_naive(),
        ended_at=utc_now_naive(),
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    if filename.endswith(".json"):
        data = json.loads(raw.decode("utf-8"))
        metrics = list(data.get("metrics") or [])
        run.metrics = metrics
        run.dataset = str(data.get("dataset_name") or dataset)
        # Ingest items
        inputs = data.get("inputs") or {}
        metadatas = data.get("metadatas") or {}
        results = data.get("results") or {}
        errors = data.get("errors") or {}
        for idx, (item_id, inp) in enumerate(inputs.items()):
            md = metadatas.get(item_id) or {}
            r = results.get(item_id)
            err = errors.get(item_id)
            if r:
                out = r.get("output")
                exp = r.get("expected")
                latency_ms = float(r.get("time") or 0.0) * 1000.0
                trace_id = r.get("trace_id")
                item = RunItem(
                    run_id=run.id,
                    item_id=str(item_id),
                    index=idx,
                    input=inp,
                    expected=exp,
                    output=out,
                    error=None,
                    latency_ms=latency_ms,
                    trace_id=trace_id,
                    trace_url=r.get("trace_url"),
                    item_metadata=md if isinstance(md, dict) else {},
                )
                db.add(item)
                scores = r.get("scores") or {}
                for m in metrics:
                    val = scores.get(m)
                    score_numeric = None
                    if isinstance(val, (int, float, bool)):
                        score_numeric = float(val)
                    elif isinstance(val, dict) and isinstance(
                        val.get("score"), (int, float, bool)
                    ):
                        score_numeric = float(val["score"])
                    meta = {}
                    if isinstance(val, dict) and isinstance(val.get("metadata"), dict):
                        meta = val["metadata"]
                    db.add(
                        RunItemScore(
                            run_id=run.id,
                            item_id=str(item_id),
                            metric_name=str(m),
                            score_numeric=score_numeric,
                            score_raw=val,
                            meta=meta,
                        )
                    )
            elif err:
                err_msg = err.get("error") if isinstance(err, dict) else str(err)
                db.add(
                    RunItem(
                        run_id=run.id,
                        item_id=str(item_id),
                        index=idx,
                        input=inp,
                        expected=None,
                        output=None,
                        error=str(err_msg),
                        latency_ms=None,
                        trace_id=(
                            err.get("trace_id") if isinstance(err, dict) else None
                        ),
                        trace_url=None,
                        item_metadata=md if isinstance(md, dict) else {},
                    )
                )
        db.commit()

    elif filename.endswith(".csv"):
        text = raw.decode("utf-8")
        reader = csv.DictReader(io.StringIO(text))
        fieldnames = list(reader.fieldnames or [])
        metrics = [
            c.replace("_score", "")
            for c in fieldnames
            if c.endswith("_score") and "__meta__" not in c
        ]
        run.metrics = metrics
        rows = list(reader)

        if rows:
            first = rows[0]
            if not run.external_run_id and first.get("run_name"):
                run.external_run_id = first["run_name"]
            if first.get("dataset_name"):
                run.dataset = first["dataset_name"]
            if first.get("run_metadata"):
                try:
                    run.run_metadata = _sanitize_for_json(
                        json.loads(first["run_metadata"])
                    )
                except (json.JSONDecodeError, TypeError):
                    pass
            if first.get("run_config"):
                try:
                    run.run_config = _sanitize_for_json(json.loads(first["run_config"]))
                except (json.JSONDecodeError, TypeError):
                    pass

        fingerprint_counts: Dict[str, int] = {}
        for idx, row in enumerate(rows):
            raw_meta = row.get("item_metadata") or ""
            try:
                parsed_meta = json.loads(raw_meta) if raw_meta else {}
            except (json.JSONDecodeError, TypeError):
                parsed_meta = {}
            raw_item_id = str(row.get("item_id") or "").strip()
            if raw_item_id and not looks_like_positional_item_id(raw_item_id):
                item_id = raw_item_id
            else:
                fingerprint = build_identity_fingerprint(
                    input_value=row.get("input") or "",
                    expected_value=row.get("expected_output") or "",
                    metadata=parsed_meta,
                )
                fingerprint_counts[fingerprint] = (
                    fingerprint_counts.get(fingerprint, 0) + 1
                )
                item_id = f"csv_{fingerprint}__{fingerprint_counts[fingerprint]:04d}"
            output = str(row.get("output") or "")
            is_error = output.startswith("ERROR:")
            item = RunItem(
                run_id=run.id,
                item_id=item_id,
                index=idx,
                input=row.get("input"),
                expected=row.get("expected_output"),
                output=None if is_error else row.get("output"),
                error=(output[6:].strip() if is_error else None),
                item_metadata=parsed_meta if isinstance(parsed_meta, dict) else {},
                latency_ms=(float(row.get("time") or 0.0) * 1000.0),
                trace_id=row.get("trace_id") or None,
                trace_url=None,
            )
            db.add(item)

            for m in metrics:
                raw_val = row.get(f"{m}_score")
                score_numeric = None
                try:
                    if not is_error and raw_val not in (None, "", "N/A"):
                        score_numeric = float(raw_val)
                    elif is_error:
                        score_numeric = 0.0
                except Exception:
                    score_numeric = None

                meta: Dict[str, Any] = {}
                for col in fieldnames:
                    if col.startswith(f"{m}__meta__"):
                        k = col[len(f"{m}__meta__") :]
                        if k == "json":
                            raw_json = row.get(col, "")
                            if raw_json:
                                try:
                                    parsed = json.loads(raw_json)
                                    if isinstance(parsed, dict):
                                        meta.update(_sanitize_for_json(parsed))
                                    else:
                                        meta[k] = raw_json
                                except (json.JSONDecodeError, TypeError):
                                    meta[k] = raw_json
                        else:
                            meta[k] = row.get(col)
                db.add(
                    RunItemScore(
                        run_id=run.id,
                        item_id=item_id,
                        metric_name=m,
                        score_numeric=score_numeric,
                        score_raw=raw_val,
                        meta=meta,
                    )
                )
        db.commit()
    else:
        raise HTTPException(
            status_code=400, detail="Unsupported file type (use .csv or .json)"
        )

    settings = PlatformSettings()
    live_url = f"{settings.base_url.rstrip('/')}/run/{run.id}"
    return {"run_id": run.id, "live_url": live_url}
