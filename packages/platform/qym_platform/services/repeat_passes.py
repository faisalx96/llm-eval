from __future__ import annotations

import re
from collections import defaultdict
from typing import Any, Dict, List, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from qym_platform.datetime_utils import utc_now_naive
from qym_platform.db.models import (
    AuditLog,
    Run,
    RunEvent,
    RunItem,
    RunItemAttempt,
    RunItemPassScore,
    RunItemScore,
    RunMetricAnalysis,
    RunTraceAggregate,
    RunWorkflowStatus,
    Span,
)


class RepeatPassDeletionError(ValueError):
    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


_PASS_META_KEY_RE = re.compile(r"^pass_(\d+)(_.+)$")


def _renumber_pass_edit_meta(
    stored_meta: Optional[Dict[str, Any]], deleted_pass: int
) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    for key, value in (stored_meta or {}).items():
        match = _PASS_META_KEY_RE.match(str(key))
        if not match:
            result[str(key)] = value
            continue
        pass_number = int(match.group(1))
        if pass_number == deleted_pass:
            continue
        if pass_number > deleted_pass:
            pass_number -= 1
        result[f"pass_{pass_number}{match.group(2)}"] = value
    return result


def _aggregate_meta(
    pass_values: Dict[int, Optional[float]],
    stored_meta: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    meta: Dict[str, Any] = {
        "sample_reducer": "mean",
        "samples_observed": sum(value is not None for value in pass_values.values()),
    }
    for key, value in (stored_meta or {}).items():
        if key in {"modified", "original_score"} or key.startswith("pass_"):
            meta[key] = value
    return meta


def _recover_completed_outputs(
    db: Session, run_id: str, wanted: set[tuple[str, int]]
) -> Dict[tuple[str, int], Any]:
    recovered: Dict[tuple[str, int], Any] = {}
    if not wanted:
        return recovered
    rows = (
        db.query(RunEvent.payload)
        .filter(RunEvent.run_id == run_id, RunEvent.type == "item_completed")
        .order_by(RunEvent.sequence.asc())
        .all()
    )
    for (payload,) in rows:
        if not isinstance(payload, dict):
            continue
        item_id = str(payload.get("item_id") or "")
        try:
            pass_number = max(1, int(payload.get("pass_number") or 1))
        except (TypeError, ValueError):
            pass_number = 1
        key = (item_id, pass_number)
        if key in wanted and "output" in payload:
            recovered[key] = payload.get("output")
    return recovered


def _refresh_trace_metadata(db: Session, run: Run) -> None:
    # Representative item/trace mappings changed outside ingestion. Invalidate
    # the private ledger atomically; the next live batch backfills it once.
    from qym_platform.db.models import (
        RunTraceContribution,
        RunTraceNamedContribution,
        RunTraceSummary,
    )

    for model in (RunTraceContribution, RunTraceNamedContribution, RunTraceSummary):
        db.query(model).filter(model.run_id == run.id).delete(synchronize_session=False)

    from qym_platform.api.ingest import (
        _build_run_trace_stats,
        _public_trace_bucket,
        _sanitize_for_json,
        _trace_bucket_from_aggregate,
    )

    aggregates = (
        db.query(RunTraceAggregate).filter(RunTraceAggregate.run_id == run.id).all()
    )
    run_metadata = dict(run.run_metadata) if isinstance(run.run_metadata, dict) else {}
    if "trace_stats" not in run_metadata and not aggregates:
        return

    buckets = {
        aggregate.trace_id: _trace_bucket_from_aggregate(aggregate)
        for aggregate in aggregates
    }
    run_buckets: List[Dict[str, Any]] = []
    for item in db.query(RunItem).filter(RunItem.run_id == run.id).all():
        bucket = buckets.get(item.trace_id or "")
        item_metadata = (
            dict(item.item_metadata) if isinstance(item.item_metadata, dict) else {}
        )
        if bucket and int(bucket.get("span_count") or 0) > 0:
            item_metadata["trace_stats"] = _sanitize_for_json(
                _public_trace_bucket(bucket)
            )
            if not item.error:
                run_buckets.append(bucket)
        else:
            item_metadata.pop("trace_stats", None)
        item.item_metadata = _sanitize_for_json(item_metadata)

    run_metadata["trace_stats"] = _build_run_trace_stats(run_buckets)
    run.run_metadata = _sanitize_for_json(run_metadata)


def _renumber_rows(db: Session, run_id: str, deleted_pass: int) -> None:
    # Use negative temporary values so unique constraints cannot collide while
    # old pass N+1 becomes new pass N.
    for model in (RunItemAttempt, RunItemPassScore):
        (
            db.query(model)
            .filter(model.run_id == run_id, model.pass_number > deleted_pass)
            .update(
                {model.pass_number: -model.pass_number},
                synchronize_session=False,
            )
        )
        db.flush()
        (
            db.query(model)
            .filter(model.run_id == run_id, model.pass_number < 0)
            .update(
                {model.pass_number: -model.pass_number - 1},
                synchronize_session=False,
            )
        )
        db.flush()


def _rewrite_events(
    db: Session,
    run: Run,
    deleted_pass: int,
    new_samples: int,
    exclusive_trace_ids: set[str],
) -> int:
    deleted_events = 0
    for event in db.query(RunEvent).filter(RunEvent.run_id == run.id).all():
        payload = dict(event.payload) if isinstance(event.payload, dict) else {}
        try:
            event_pass = (
                int(payload["pass_number"])
                if payload.get("pass_number") is not None
                else None
            )
        except (TypeError, ValueError):
            event_pass = None

        event_trace_id = str(payload.get("trace_id") or "")
        if event_pass == deleted_pass or (
            event.type == "span_completed" and event_trace_id in exclusive_trace_ids
        ):
            db.delete(event)
            deleted_events += 1
            continue
        if event_pass is not None and event_pass > deleted_pass:
            payload["pass_number"] = event_pass - 1

        if event.type == "run_started":
            event_config = (
                dict(payload.get("run_config"))
                if isinstance(payload.get("run_config"), dict)
                else {}
            )
            event_config["samples"] = new_samples
            payload["run_config"] = event_config
        elif event.type == "run_completed" and isinstance(payload.get("summary"), dict):
            summary = dict(payload["summary"])
            if "samples" in summary:
                summary["samples"] = new_samples
            summary_metadata = (
                dict(summary.get("run_metadata"))
                if isinstance(summary.get("run_metadata"), dict)
                else None
            )
            if summary_metadata is not None:
                summary_metadata["samples"] = new_samples
                summary_metadata["last_completed_pass"] = new_samples
                summary["run_metadata"] = summary_metadata
            payload["summary"] = summary
        event.payload = payload
    return deleted_events


def _rereduce_scores(
    db: Session,
    run_id: str,
    deleted_pass: int,
    selected_score_keys: set[tuple[str, str]],
) -> None:
    pass_scores_by_key: Dict[tuple[str, str], List[RunItemPassScore]] = defaultdict(
        list
    )
    for pass_score in (
        db.query(RunItemPassScore).filter(RunItemPassScore.run_id == run_id).all()
    ):
        pass_scores_by_key[(pass_score.item_id, pass_score.metric_name)].append(
            pass_score
        )

    aggregate_scores = (
        db.query(RunItemScore).filter(RunItemScore.run_id == run_id).all()
    )
    aggregates_by_key = {
        (score.item_id, score.metric_name): score for score in aggregate_scores
    }
    for key, siblings in pass_scores_by_key.items():
        aggregate = aggregates_by_key.get(key)
        if aggregate is None:
            aggregate = RunItemScore(
                run_id=run_id,
                item_id=key[0],
                metric_name=key[1],
            )
            db.add(aggregate)
        pass_values = {
            int(sibling.pass_number): sibling.score_numeric for sibling in siblings
        }
        numerics = [value for value in pass_values.values() if value is not None]
        reduced = sum(numerics) / len(numerics) if numerics else None
        aggregate.score_numeric = reduced
        aggregate.score_raw = reduced
        aggregate.meta = _aggregate_meta(
            pass_values,
            _renumber_pass_edit_meta(aggregate.meta, deleted_pass),
        )
        aggregate.label = None
        aggregate.explanation = None

    for key in selected_score_keys - set(pass_scores_by_key):
        aggregate = aggregates_by_key.get(key)
        if aggregate is not None:
            db.delete(aggregate)
    db.flush()


def _refresh_representative_items(db: Session, run_id: str) -> None:
    db.expire_all()
    final_attempts = (
        db.query(RunItemAttempt)
        .filter(
            RunItemAttempt.run_id == run_id,
            RunItemAttempt.is_last_attempt.is_(True),
        )
        .all()
    )
    attempts_by_item: Dict[str, List[RunItemAttempt]] = defaultdict(list)
    for attempt in final_attempts:
        attempts_by_item[attempt.item_id].append(attempt)
    attempt_counts = {
        (item_id, pass_number): count
        for item_id, pass_number, count in (
            db.query(
                RunItemAttempt.item_id,
                RunItemAttempt.pass_number,
                func.count(RunItemAttempt.id),
            )
            .filter(RunItemAttempt.run_id == run_id)
            .group_by(RunItemAttempt.item_id, RunItemAttempt.pass_number)
            .all()
        )
    }

    for item in db.query(RunItem).filter(RunItem.run_id == run_id).all():
        item_attempts = attempts_by_item.get(item.item_id) or []
        if not item_attempts:
            continue
        latest = max(item_attempts, key=lambda attempt: int(attempt.pass_number))
        latest_failed = str(latest.status or "").lower() == "failed"
        if latest_failed:
            successful = [
                attempt
                for attempt in item_attempts
                if str(attempt.status or "").lower() != "failed"
                and attempt.output is not None
            ]
            item.output = (
                max(successful, key=lambda attempt: int(attempt.pass_number)).output
                if successful
                else None
            )
            item.error = latest.error or "Pass failed"
        else:
            item.output = latest.output
            item.error = None
        item.latency_ms = latest.latency_ms
        item.trace_id = latest.trace_id
        item.trace_url = latest.trace_url
        item.retry_count = max(
            0,
            int(attempt_counts.get((item.item_id, latest.pass_number), 1)) - 1,
        )
        item_metadata = (
            dict(item.item_metadata) if isinstance(item.item_metadata, dict) else {}
        )
        if latest.task_started_at_ms is not None:
            item_metadata["task_started_at_ms"] = latest.task_started_at_ms
        else:
            item_metadata.pop("task_started_at_ms", None)
        if item.retry_count:
            item_metadata["retry_count"] = item.retry_count
        else:
            item_metadata.pop("retry_count", None)
        item.item_metadata = item_metadata


def delete_repeat_pass(
    db: Session,
    run: Run,
    pass_number: int,
    *,
    actor_user_id: Optional[str],
) -> Dict[str, Any]:
    """Delete one complete pass and repair all derived repeat-run state."""
    samples = int(run.samples or 1)
    if samples <= 1:
        raise RepeatPassDeletionError(400, "A run must retain at least one pass")
    if pass_number < 1 or pass_number > samples:
        raise RepeatPassDeletionError(400, "pass_number out of range for this run")
    if run.status == RunWorkflowStatus.RUNNING:
        raise RepeatPassDeletionError(
            409, "Cannot delete a pass while the run is active"
        )

    selected_attempts = (
        db.query(RunItemAttempt)
        .filter(
            RunItemAttempt.run_id == run.id,
            RunItemAttempt.pass_number == pass_number,
        )
        .all()
    )
    selected_scores = (
        db.query(RunItemPassScore)
        .filter(
            RunItemPassScore.run_id == run.id,
            RunItemPassScore.pass_number == pass_number,
        )
        .all()
    )
    if not selected_attempts and not selected_scores:
        raise RepeatPassDeletionError(404, "Pass has no stored data")

    selected_score_keys = {
        (score.item_id, score.metric_name) for score in selected_scores
    }
    selected_trace_ids = {
        str(attempt.trace_id) for attempt in selected_attempts if attempt.trace_id
    }

    remaining_final_attempts = (
        db.query(RunItemAttempt)
        .filter(
            RunItemAttempt.run_id == run.id,
            RunItemAttempt.pass_number != pass_number,
            RunItemAttempt.is_last_attempt.is_(True),
        )
        .all()
    )
    wanted_outputs = {
        (attempt.item_id, int(attempt.pass_number))
        for attempt in remaining_final_attempts
        if attempt.output is None and str(attempt.status or "").lower() != "failed"
    }
    recovered_outputs = _recover_completed_outputs(db, run.id, wanted_outputs)
    for attempt in remaining_final_attempts:
        key = (attempt.item_id, int(attempt.pass_number))
        if attempt.output is None and key in recovered_outputs:
            attempt.output = recovered_outputs[key]

    remaining_trace_ids = {
        str(trace_id)
        for (trace_id,) in (
            db.query(RunItemAttempt.trace_id)
            .filter(
                RunItemAttempt.run_id == run.id,
                RunItemAttempt.pass_number != pass_number,
                RunItemAttempt.trace_id.isnot(None),
            )
            .all()
        )
        if trace_id
    }
    exclusive_trace_ids = selected_trace_ids - remaining_trace_ids

    deleted_attempts = len(selected_attempts)
    deleted_scores = len(selected_scores)
    for attempt in selected_attempts:
        db.delete(attempt)
    for score in selected_scores:
        db.delete(score)
    db.flush()

    new_samples = samples - 1
    _renumber_rows(db, run.id, pass_number)
    deleted_events = _rewrite_events(
        db, run, pass_number, new_samples, exclusive_trace_ids
    )
    if exclusive_trace_ids:
        (
            db.query(Span)
            .filter(Span.run_id == run.id, Span.trace_id.in_(exclusive_trace_ids))
            .delete(synchronize_session=False)
        )
        (
            db.query(RunTraceAggregate)
            .filter(
                RunTraceAggregate.run_id == run.id,
                RunTraceAggregate.trace_id.in_(exclusive_trace_ids),
            )
            .delete(synchronize_session=False)
        )
    db.query(RunMetricAnalysis).filter(RunMetricAnalysis.run_id == run.id).delete(
        synchronize_session=False
    )

    _rereduce_scores(db, run.id, pass_number, selected_score_keys)
    _refresh_representative_items(db, run.id)

    run.samples = new_samples
    run_config = dict(run.run_config) if isinstance(run.run_config, dict) else {}
    run_config["samples"] = new_samples
    try:
        if int(run_config.get("report_k") or 0) > new_samples:
            run_config["report_k"] = new_samples
    except (TypeError, ValueError):
        pass
    run.run_config = run_config
    run_metadata = dict(run.run_metadata) if isinstance(run.run_metadata, dict) else {}
    run_metadata["samples"] = new_samples
    run_metadata["last_completed_pass"] = new_samples
    run.run_metadata = run_metadata
    run.updated_at = utc_now_naive()

    _refresh_trace_metadata(db, run)
    db.add(
        AuditLog(
            actor_user_id=actor_user_id,
            action="run.pass_deleted",
            entity_type="run",
            entity_id=run.id,
            before={"samples": samples, "pass_number": pass_number},
            after={
                "samples": new_samples,
                "deleted_attempts": deleted_attempts,
                "deleted_scores": deleted_scores,
                "deleted_events": deleted_events,
            },
        )
    )
    return {
        "ok": True,
        "run_id": run.id,
        "deleted_pass": pass_number,
        "samples": new_samples,
        "deleted_attempts": deleted_attempts,
        "deleted_scores": deleted_scores,
    }
