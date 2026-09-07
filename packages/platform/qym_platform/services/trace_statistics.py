"""Delta-maintained trace statistics with durable, indexed item contributions.

A run row lock serializes source mutations and projection updates. Existing runs
are backfilled once; subsequent refreshes read only touched traces/items. Public
metadata contains the original presentation schema, never the private ledger.
"""

from __future__ import annotations

import copy
import math
from typing import Optional

from sqlalchemy import insert
from sqlalchemy.orm import Session

from qym_platform.db.models import (
    Run,
    RunItem,
    RunTraceAggregate,
    RunTraceContribution,
    RunTraceNamedContribution,
    RunTraceSummary,
    Span,
)


def _chunks(values, size=400):
    values = list(values)
    return (values[pos : pos + size] for pos in range(0, len(values), size))


def _named_entries(bucket):
    totals = bucket.get("outer_scope_parent_span_ms") or {}
    counts = bucket.get("outer_scope_parent_span_counts") or {}
    for position, (name, value) in enumerate(totals.items()):
        try:
            duration = float(value)
            count = int(counts.get(name) or 0)
        except (TypeError, ValueError):
            continue
        if count > 0 and math.isfinite(duration) and duration >= 0:
            yield name, duration, count, position


def _apply_delta(totals, bucket, sign):
    totals["items"] += sign
    numeric = totals["bucket"]
    for key, value in bucket.items():
        if isinstance(value, (int, float)) and math.isfinite(value):
            numeric[key] = numeric.get(key, 0) + sign * value
    for name, duration, count, _ in _named_entries(bucket):
        entry = totals["names"].setdefault(name, {"total": 0.0, "count": 0})
        entry["total"] += sign * duration
        entry["count"] += sign * count
        if entry["count"] <= 0:
            totals["names"].pop(name, None)


def refresh_trace_statistics(
    db: Session,
    run: Run,
    *,
    touched_trace_ids: Optional[set[str]] = None,
    touched_item_ids: Optional[set[str]] = None,
) -> None:
    # Imported lazily: ingestion owns the established span classification and
    # public reducers, shared by incremental and full-rebuild paths.
    from qym_platform.api.ingest import (
        _build_run_trace_stats,
        _build_trace_buckets_from_spans,
        _empty_trace_bucket,
        _public_trace_bucket,
        _sanitize_for_json,
        _trace_bucket_from_aggregate,
    )

    db.flush()
    db.query(Run.id).filter(Run.id == run.id).with_for_update().one()
    summary = (
        db.query(RunTraceSummary).filter_by(run_id=run.id).populate_existing().first()
    )
    rebuild = summary is None or touched_trace_ids is None
    if rebuild:
        db.query(RunTraceContribution).filter_by(run_id=run.id).delete(
            synchronize_session=False
        )
        db.query(RunTraceNamedContribution).filter_by(run_id=run.id).delete(
            synchronize_session=False
        )
        totals = {"items": 0, "bucket": {}, "names": {}}
        items = db.query(RunItem).filter_by(run_id=run.id).order_by(RunItem.id).all()
        aggregates = {
            row.trace_id: row
            for row in db.query(RunTraceAggregate).filter_by(run_id=run.id)
        }
        if touched_trace_ids is None:
            spans = db.query(Span).filter_by(run_id=run.id).all()
            rebuild_traces = set(aggregates) | {span.trace_id for span in spans}
        else:
            # Existing installations can have cached historical aggregates
            # without raw spans. A one-time ledger backfill must keep those
            # untouched caches, just as the old batched refresh did.
            rebuild_traces = set(touched_trace_ids) | {
                item.trace_id
                for item in items
                if item.trace_id and item.trace_id not in aggregates
            }
            spans = []
            for chunk in _chunks(rebuild_traces):
                spans.extend(
                    db.query(Span)
                    .filter(Span.run_id == run.id, Span.trace_id.in_(chunk))
                    .all()
                )
        rebuilt = _build_trace_buckets_from_spans(spans)
        existing = {}
        if summary is None:
            summary = RunTraceSummary(run_id=run.id)
            db.add(summary)
    else:
        totals = copy.deepcopy(summary.totals)
        rebuild_traces = set(touched_trace_ids or ())
        ids = set(touched_item_ids or ())
        # IDs are queried in bounded chunks; unrelated raw item payloads are
        # never loaded. Include both old and new mappings, including deletions.
        item_map = {}
        for chunk in _chunks(rebuild_traces):
            for item in db.query(RunItem).filter(
                RunItem.run_id == run.id, RunItem.trace_id.in_(chunk)
            ):
                item_map[item.item_id] = item
            ids.update(
                row[0]
                for row in db.query(RunTraceContribution.item_id).filter(
                    RunTraceContribution.run_id == run.id,
                    RunTraceContribution.trace_id.in_(chunk),
                )
            )
        ids.update(item_map)
        for chunk in _chunks(ids):
            for item in db.query(RunItem).filter(
                RunItem.run_id == run.id, RunItem.item_id.in_(chunk)
            ):
                item_map[item.item_id] = item
        items = sorted(item_map.values(), key=lambda item: item.id)
        existing = {}
        for chunk in _chunks(ids):
            for row in db.query(RunTraceContribution).filter(
                RunTraceContribution.run_id == run.id,
                RunTraceContribution.item_id.in_(chunk),
            ):
                existing[row.item_id] = row
        relevant_traces = rebuild_traces | {
            item.trace_id for item in items if item.trace_id
        }
        aggregates = {}
        for chunk in _chunks(relevant_traces):
            for row in db.query(RunTraceAggregate).filter(
                RunTraceAggregate.run_id == run.id,
                RunTraceAggregate.trace_id.in_(chunk),
            ):
                aggregates[row.trace_id] = row
        # A newly linked trace may predate its cache. Rebuild only that trace.
        rebuild_traces.update(relevant_traces - aggregates.keys())
        spans = []
        for chunk in _chunks(rebuild_traces):
            spans.extend(
                db.query(Span)
                .filter(Span.run_id == run.id, Span.trace_id.in_(chunk))
                .all()
            )
        rebuilt = _build_trace_buckets_from_spans(spans)

    for trace_id in rebuild_traces:
        bucket = rebuilt.get(trace_id) or _empty_trace_bucket()
        agg = aggregates.get(trace_id)
        if agg is None:
            agg = RunTraceAggregate(run_id=run.id, trace_id=trace_id)
            aggregates[trace_id] = agg
            db.add(agg)
        for key in (
            "span_count",
            "tokens",
            "cost",
            "llm_calls",
            "tool_calls",
            "tool_errors",
            "malformed_tool_calls",
            "noisy_reasoning",
            "provider_errors",
            "has_reasoning",
            "has_reasoning_tokens",
            "reasoning_tokens",
        ):
            setattr(agg, key, bucket.get(key, 0))
        agg.raw_bucket = _sanitize_for_json(bucket)

    affected_ids = set(existing) | {item.item_id for item in items}
    affected_names = set()
    for old in existing.values():
        if old.included:
            _apply_delta(totals, old.bucket, -1)
            affected_names.update(name for name, *_ in _named_entries(old.bucket))
    for chunk in _chunks(affected_ids):
        db.query(RunTraceNamedContribution).filter(
            RunTraceNamedContribution.run_id == run.id,
            RunTraceNamedContribution.item_id.in_(chunk),
        ).delete(synchronize_session=False)
    named_rows = []
    retained = set()
    for item in items:
        retained.add(item.item_id)
        agg = aggregates.get(item.trace_id)
        bucket = (
            _trace_bucket_from_aggregate(agg)
            if agg is not None
            else _empty_trace_bucket()
        )
        has_spans = int(bucket.get("span_count") or 0) > 0
        included = has_spans and not item.error
        metadata = dict(item.item_metadata or {})
        if has_spans:
            metadata["trace_stats"] = _sanitize_for_json(_public_trace_bucket(bucket))
        else:
            metadata.pop("trace_stats", None)
        item.item_metadata = _sanitize_for_json(metadata)
        state = existing.get(item.item_id)
        if state is None:
            state = RunTraceContribution(run_id=run.id, item_id=item.item_id)
            db.add(state)
        state.item_order, state.trace_id = item.id, item.trace_id
        state.included, state.bucket = bool(included), _sanitize_for_json(bucket)
        if included:
            _apply_delta(totals, bucket, 1)
            for name, _, _, position in _named_entries(bucket):
                affected_names.add(name)
                named_rows.append(
                    dict(
                        run_id=run.id,
                        item_id=item.item_id,
                        name=name,
                        item_order=item.id,
                        name_position=position,
                    )
                )
    for item_id in set(existing) - retained:
        db.delete(existing[item_id])
    for chunk in _chunks(named_rows):
        db.execute(insert(RunTraceNamedContribution), chunk)
    db.flush()
    for name in affected_names:
        entry = totals["names"].get(name)
        if entry is not None:
            first = (
                db.query(
                    RunTraceNamedContribution.item_order,
                    RunTraceNamedContribution.name_position,
                )
                .filter_by(run_id=run.id, name=name)
                .order_by(
                    RunTraceNamedContribution.item_order,
                    RunTraceNamedContribution.name_position,
                )
                .first()
            )
            entry["order"] = list(first) if first else [0, 0]

    bucket = dict(totals["bucket"])
    names = sorted(
        totals["names"].items(), key=lambda pair: pair[1].get("order", [0, 0])
    )
    bucket["outer_scope_parent_span_ms"] = {
        name: entry["total"] for name, entry in names
    }
    bucket["outer_scope_parent_span_counts"] = {
        name: entry["count"] for name, entry in names
    }
    if totals["items"]:
        # Aggregate latencies and tool success use sums/counts; item averages
        # alone need the number of eligible items rather than one summed bucket.
        public = _build_run_trace_stats([bucket])
        for key in (
            "avg_tokens",
            "avg_llm_calls",
            "avg_tool_calls",
            "avg_reasoning_tokens",
        ):
            public[key] /= totals["items"]
    else:
        public = {"has_spans": False}
    summary.totals = _sanitize_for_json(totals)
    metadata = dict(run.run_metadata or {})
    metadata["trace_stats"] = _sanitize_for_json(public)
    run.run_metadata = metadata
