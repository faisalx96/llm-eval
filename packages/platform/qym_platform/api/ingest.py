from __future__ import annotations

import csv
import io
import json
import logging
import math
import sys

csv.field_size_limit(sys.maxsize)
from datetime import datetime
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

from qym_platform.auth import Principal, require_api_key_principal
from qym_platform.db.models import Run, RunEvent, RunItem, RunItemScore, RunWorkflowStatus, Span
from qym_platform.deps import get_db
from qym_platform.events import (
    ItemCompletedPayload,
    ItemFailedPayload,
    ItemStartedPayload,
    MetadataUpdatePayload,
    MetricScoredPayload,
    RunCompletedPayload,
    RunEventV1,
    RunStartedPayload,
    SpanCompletedPayload,
)
from qym_platform.item_identity import build_identity_fingerprint, looks_like_positional_item_id
from qym_platform.settings import PlatformSettings


router = APIRouter(prefix="/v1", tags=["ingestion"])


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
    "metric_scored": MetricScoredPayload,
    "item_completed": ItemCompletedPayload,
    "item_failed": ItemFailedPayload,
    "run_completed": RunCompletedPayload,
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
    run = Run(
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
        started_at=datetime.utcnow(),
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    settings = PlatformSettings()
    live_url = f"{settings.base_url.rstrip('/')}/run/{run.id}"
    return {"run_id": run.id, "live_url": live_url}


@router.post("/runs/{run_id}/events")
async def ingest_events(
    run_id: str,
    request: Request,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_api_key_principal),
) -> JSONResponse:
    run = db.query(Run).filter(Run.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    if run.owner_user_id != principal.user.id:
        raise HTTPException(status_code=403, detail="Forbidden")

    item_cache: Dict[str, Optional[RunItem]] = {}
    score_cache: Dict[tuple[str, str], Optional[RunItemScore]] = {}

    def _get_item(item_id: str) -> Optional[RunItem]:
        if item_id in item_cache:
            return item_cache[item_id]
        item = db.query(RunItem).filter(RunItem.run_id == run_id, RunItem.item_id == item_id).first()
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

        existing = db.query(RunEvent).filter(RunEvent.run_id == run_id, RunEvent.event_id == str(evt.event_id)).first()
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
        payload = payload_cls.model_validate(raw_payload) if payload_cls else evt.payload
        logger.debug("Ingest run=%s type=%s payload_type=%s", run_id, evt.type, type(payload).__name__)

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
            run.started_at = payload.started_at
            run.status = RunWorkflowStatus.RUNNING
            logger.debug("Run %s status -> RUNNING", run_id)

        elif isinstance(payload, ItemStartedPayload):
            item = _get_item(payload.item_id)
            if not item:
                item = _remember_item(RunItem(
                    run_id=run_id,
                    item_id=payload.item_id,
                    index=payload.index,
                    input=_sanitize_for_json(payload.input),
                    expected=_sanitize_for_json(payload.expected),
                    item_metadata=_sanitize_for_json(payload.item_metadata),
                ))
                db.add(item)
            else:
                item.index = payload.index
                item.input = _sanitize_for_json(payload.input)
                item.expected = _sanitize_for_json(payload.expected)
                item.item_metadata = _sanitize_for_json(payload.item_metadata)

        elif isinstance(payload, MetricScoredPayload):
            score = _get_score(payload.item_id, payload.metric_name)
            if not score:
                score = _remember_score(RunItemScore(
                    run_id=run_id,
                    item_id=payload.item_id,
                    metric_name=payload.metric_name,
                    score_numeric=payload.score_numeric,
                    score_raw=_sanitize_for_json(payload.score_raw),
                    meta=_sanitize_for_json(payload.meta),
                    label=payload.label,
                    explanation=payload.explanation,
                ))
                db.add(score)
            else:
                score.score_numeric = payload.score_numeric
                score.score_raw = _sanitize_for_json(payload.score_raw)
                score.meta = _sanitize_for_json(payload.meta)
                score.label = payload.label
                score.explanation = payload.explanation

        elif isinstance(payload, ItemCompletedPayload):
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
                item = _remember_item(RunItem(
                    run_id=run_id,
                    item_id=payload.item_id,
                    index=payload.index if payload.index is not None else 0,
                    input={},
                    expected=None,
                    output=_sanitize_for_json(payload.output),
                    error=None,
                    latency_ms=payload.latency_ms,
                    trace_id=payload.trace_id,
                    trace_url=payload.trace_url,
                    item_metadata=_build_item_meta(ts_ms, payload.retry_count),
                ))
                db.add(item)
            else:
                # Update index if it was 0 (placeholder) and we now have the real index
                if item.index == 0 and payload.index is not None and payload.index != 0:
                    item.index = payload.index
                item.output = _sanitize_for_json(payload.output)
                item.error = None
                item.latency_ms = payload.latency_ms
                item.trace_id = payload.trace_id
                item.trace_url = payload.trace_url
                # Merge metadata into item_metadata
                md = dict(item.item_metadata or {})
                if ts_ms:
                    md["task_started_at_ms"] = ts_ms
                if payload.retry_count > 0:
                    md["retry_count"] = payload.retry_count
                if md != (item.item_metadata or {}):
                    item.item_metadata = _sanitize_for_json(md)

        elif isinstance(payload, ItemFailedPayload):
            item = _get_item(payload.item_id)
            if not item:
                item = _remember_item(RunItem(
                    run_id=run_id,
                    item_id=payload.item_id,
                    index=payload.index if payload.index is not None else 0,
                    input={},
                    expected=None,
                    output=None,
                    error=payload.error,
                    latency_ms=None,
                    trace_id=payload.trace_id,
                    trace_url=payload.trace_url,
                    item_metadata={},
                ))
                db.add(item)
            else:
                # Update index if it was 0 (placeholder) and we now have the real index
                if item.index == 0 and payload.index is not None and payload.index != 0:
                    item.index = payload.index
                item.error = payload.error
                item.trace_id = payload.trace_id
                item.trace_url = payload.trace_url

        elif isinstance(payload, RunCompletedPayload):
            run.ended_at = payload.ended_at
            _FINAL_STATUS = {"COMPLETED": RunWorkflowStatus.COMPLETED, "FAILED": RunWorkflowStatus.FAILED, "STOPPED": RunWorkflowStatus.STOPPED}
            run.status = _FINAL_STATUS.get(payload.final_status, RunWorkflowStatus.FAILED)
            logger.debug("Run %s status -> %s", run_id, payload.final_status)
            # Allow the client to attach final metadata (e.g., langfuse_url) at completion time.
            # This is safe because ingestion is authenticated (API key) and scoped to the run owner.
            try:
                md = payload.summary.get("run_metadata") if isinstance(payload.summary, dict) else None
                if isinstance(md, dict) and md:
                    current = run.run_metadata if isinstance(run.run_metadata, dict) else {}
                    run.run_metadata = _sanitize_for_json({**current, **md})
            except Exception:
                pass

        elif isinstance(payload, MetadataUpdatePayload):
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
            # Store OTEL span data for native trace viewing.
            # Wrapped in a savepoint so a span-storage failure (e.g. pending
            # migration) never rolls back the rest of the batch (items, metrics).
            try:
                nested = db.begin_nested()
                existing = db.query(Span).filter(
                    Span.run_id == run_id,
                    Span.span_id == payload.span_id,
                ).first()
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
                nested.commit()
            except Exception as e:
                logger.warning("Span storage failed for run %s: %s", run_id, e)

        applied += 1

    db.commit()
    return JSONResponse({"ok": True, "applied": applied, "skipped": skipped})


@router.post("/runs:upload")
async def upload_run(
    file: UploadFile = File(...),
    task: str = Form(...),
    dataset: str = Form(...),
    model: Optional[str] = Form(default=None),
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_api_key_principal),
) -> Dict[str, Any]:
    """Upload a saved results file (CSV/JSON/XLSX) and ingest into DB."""
    filename = (file.filename or "").lower()
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Empty upload")

    # Create run as completed by default (file upload is post-hoc)
    run = Run(
        external_run_id=None,
        created_by_user_id=principal.user.id,
        owner_user_id=principal.user.id,
        task=task,
        dataset=dataset,
        model=model,
        metrics=[],
        run_metadata={},
        run_config={},
        status=RunWorkflowStatus.COMPLETED,
        started_at=datetime.utcnow(),
        ended_at=datetime.utcnow(),
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
                scores = (r.get("scores") or {})
                for m in metrics:
                    val = scores.get(m)
                    score_numeric = None
                    if isinstance(val, (int, float, bool)):
                        score_numeric = float(val)
                    elif isinstance(val, dict) and isinstance(val.get("score"), (int, float, bool)):
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
                        trace_id=(err.get("trace_id") if isinstance(err, dict) else None),
                        trace_url=None,
                        item_metadata=md if isinstance(md, dict) else {},
                    )
                )
        db.commit()

    elif filename.endswith(".csv"):
        text = raw.decode("utf-8")
        reader = csv.DictReader(io.StringIO(text))
        fieldnames = list(reader.fieldnames or [])
        metrics = [c.replace("_score", "") for c in fieldnames if c.endswith("_score") and "__meta__" not in c]
        run.metrics = metrics
        rows = list(reader)
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
                fingerprint_counts[fingerprint] = fingerprint_counts.get(fingerprint, 0) + 1
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
        raise HTTPException(status_code=400, detail="Unsupported file type (use .csv or .json)")

    settings = PlatformSettings()
    live_url = f"{settings.base_url.rstrip('/')}/run/{run.id}"
    return {"run_id": run.id, "live_url": live_url}
