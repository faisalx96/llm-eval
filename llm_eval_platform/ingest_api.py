from __future__ import annotations

import csv
import io
import json
from datetime import datetime
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from llm_eval_platform.auth import Principal, require_api_key_principal
from llm_eval_platform.db.models import Run, RunEvent, RunItem, RunItemScore, RunWorkflowStatus
from llm_eval_platform.deps import get_db
from llm_eval_platform.events import (
    ItemCompletedPayload,
    ItemFailedPayload,
    ItemStartedPayload,
    MetricScoredPayload,
    RunCompletedPayload,
    RunEventV1,
    RunStartedPayload,
)
from llm_eval_platform.settings import PlatformSettings


router = APIRouter(prefix="/v1", tags=["ingestion"])


class CreateRunRequest(BaseModel):
    external_run_id: Optional[str] = None
    task: str
    dataset: str
    model: Optional[str] = None
    metrics: list[str] = Field(default_factory=list)
    run_metadata: Dict[str, Any] = Field(default_factory=dict)
    run_config: Dict[str, Any] = Field(default_factory=dict)


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
            raise HTTPException(status_code=400, detail=f"Invalid event: {e}")
        if str(evt.run_id) != run_id:
            raise HTTPException(status_code=400, detail="run_id mismatch in event")

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
        payload = evt.payload
        if isinstance(payload, RunStartedPayload):
            run.external_run_id = payload.external_run_id
            run.task = payload.task
            run.dataset = payload.dataset
            run.model = payload.model
            run.metrics = payload.metrics
            md = dict(payload.run_metadata or {})
            if payload.total_items is not None:
                md["total_items"] = int(payload.total_items)
            run.run_metadata = md
            run.run_config = payload.run_config
            run.started_at = payload.started_at
            run.status = RunWorkflowStatus.RUNNING

        elif isinstance(payload, ItemStartedPayload):
            item = db.query(RunItem).filter(RunItem.run_id == run_id, RunItem.item_id == payload.item_id).first()
            if not item:
                item = RunItem(
                    run_id=run_id,
                    item_id=payload.item_id,
                    index=payload.index,
                    input=payload.input,
                    expected=payload.expected,
                    item_metadata=payload.item_metadata,
                )
                db.add(item)
            else:
                item.index = payload.index
                item.input = payload.input
                item.expected = payload.expected
                item.item_metadata = payload.item_metadata

        elif isinstance(payload, MetricScoredPayload):
            score = (
                db.query(RunItemScore)
                .filter(RunItemScore.run_id == run_id, RunItemScore.item_id == payload.item_id, RunItemScore.metric_name == payload.metric_name)
                .first()
            )
            if not score:
                score = RunItemScore(
                    run_id=run_id,
                    item_id=payload.item_id,
                    metric_name=payload.metric_name,
                    score_numeric=payload.score_numeric,
                    score_raw=payload.score_raw,
                    meta=payload.meta,
                )
                db.add(score)
            else:
                score.score_numeric = payload.score_numeric
                score.score_raw = payload.score_raw
                score.meta = payload.meta

        elif isinstance(payload, ItemCompletedPayload):
            item = db.query(RunItem).filter(RunItem.run_id == run_id, RunItem.item_id == payload.item_id).first()
            if not item:
                item = RunItem(
                    run_id=run_id,
                    item_id=payload.item_id,
                    index=0,
                    input={},
                    expected=None,
                    output=payload.output,
                    error=None,
                    latency_ms=payload.latency_ms,
                    trace_id=payload.trace_id,
                    trace_url=payload.trace_url,
                    item_metadata={},
                )
                db.add(item)
            else:
                item.output = payload.output
                item.error = None
                item.latency_ms = payload.latency_ms
                item.trace_id = payload.trace_id
                item.trace_url = payload.trace_url

        elif isinstance(payload, ItemFailedPayload):
            item = db.query(RunItem).filter(RunItem.run_id == run_id, RunItem.item_id == payload.item_id).first()
            if not item:
                item = RunItem(
                    run_id=run_id,
                    item_id=payload.item_id,
                    index=0,
                    input={},
                    expected=None,
                    output=None,
                    error=payload.error,
                    latency_ms=None,
                    trace_id=payload.trace_id,
                    trace_url=payload.trace_url,
                    item_metadata={},
                )
                db.add(item)
            else:
                item.error = payload.error
                item.trace_id = payload.trace_id
                item.trace_url = payload.trace_url

        elif isinstance(payload, RunCompletedPayload):
            run.ended_at = payload.ended_at
            run.status = RunWorkflowStatus.COMPLETED if payload.final_status == "COMPLETED" else RunWorkflowStatus.FAILED

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
        for idx, row in enumerate(rows):
            item_id = str(row.get("item_id") or f"row_{idx:06d}")
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
                item_metadata={},
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


