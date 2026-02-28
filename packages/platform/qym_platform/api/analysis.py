from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from qym_platform.auth import Principal, require_ui_principal
from qym_platform.db.models import ReviewCorrection, Run, RunItem, RunItemScore
from qym_platform.deps import get_db
from qym_platform.services.llm_analyzer import (
    AnalysisResult,
    analyze_items_batch,
    build_client,
    get_few_shot_examples,
)

router = APIRouter(tags=["analysis"])


class AnalyzeRequest(BaseModel):
    """Filter criteria for which items to analyze."""

    metric: Optional[str] = None
    max_score: Optional[float] = None
    item_filter: str = "all"  # all | failed | passed | errors
    threshold: float = 0.8
    only_unanalyzed: bool = True
    complexity: Optional[List[str]] = None
    domain: Optional[List[str]] = None
    root_cause: Optional[List[str]] = None
    item_ids: Optional[List[str]] = None
    concurrency: int = Field(default=5, ge=1, le=20)


def _get_llm_config(principal: Principal) -> dict[str, Any]:
    """Extract and validate LLM config from the current user."""
    cfg = principal.user.llm_config if isinstance(principal.user.llm_config, dict) else {}
    if not cfg.get("llm_api_key"):
        raise HTTPException(
            status_code=400,
            detail="LLM not configured. Please set up your LLM provider in your Profile page.",
        )
    return cfg


@router.post("/api/runs/{run_id}/analyze")
async def analyze_run_items(
    run_id: str,
    request: AnalyzeRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> Dict[str, Any]:
    """Trigger LLM-powered root cause analysis for selected items in a run."""
    llm_config = _get_llm_config(principal)

    run = db.query(Run).filter(Run.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    # Load all items for this run
    all_items: list[RunItem] = (
        db.query(RunItem)
        .filter(RunItem.run_id == run.id)
        .order_by(RunItem.index.asc())
        .all()
    )

    # Load all scores for this run, grouped by item_id
    all_scores = db.query(RunItemScore).filter(RunItemScore.run_id == run.id).all()
    scores_by_item: dict[str, dict[str, RunItemScore]] = {}
    for s in all_scores:
        scores_by_item.setdefault(s.item_id, {})[s.metric_name] = s

    # Apply filters
    metric = request.metric or (run.metrics[0] if run.metrics else None)
    filtered_items: list[RunItem] = []

    for item in all_items:
        md = item.item_metadata if isinstance(item.item_metadata, dict) else {}

        # Explicit item_ids filter
        if request.item_ids and item.item_id not in request.item_ids:
            continue

        # Skip already-analyzed items if requested
        if request.only_unanalyzed and md.get("root_cause"):
            continue

        # Item filter (pass/fail/errors)
        is_error = bool(item.error)
        if request.item_filter == "errors" and not is_error:
            continue
        if request.item_filter == "failed" and not is_error and metric:
            item_scores = scores_by_item.get(item.item_id, {})
            score = item_scores.get(metric)
            if score and score.score_numeric is not None and score.score_numeric >= request.threshold:
                continue
        if request.item_filter == "passed":
            if is_error:
                continue
            if metric:
                item_scores = scores_by_item.get(item.item_id, {})
                score = item_scores.get(metric)
                if not score or score.score_numeric is None or score.score_numeric < request.threshold:
                    continue

        # Max score filter
        if request.max_score is not None and metric:
            item_scores = scores_by_item.get(item.item_id, {})
            score = item_scores.get(metric)
            if score and score.score_numeric is not None and score.score_numeric > request.max_score:
                continue

        # Complexity filter
        if request.complexity is not None:
            item_complexity = str(md.get("complexity", "")).lower()
            if item_complexity not in [c.lower() for c in request.complexity]:
                continue

        # Domain filter
        if request.domain is not None:
            item_domain = str(md.get("domain", "")).lower()
            if item_domain not in [d.lower() for d in request.domain]:
                continue

        # Root cause filter
        if request.root_cause is not None:
            item_rc = md.get("root_cause", "")
            if "__none__" in request.root_cause and not item_rc:
                pass  # include items with no root cause
            elif item_rc not in request.root_cause:
                continue

        filtered_items.append(item)

    if not filtered_items:
        return {"total_analyzed": 0, "results": [], "errors": 0}

    # Get few-shot examples from correction bank
    corrections = get_few_shot_examples(db, task=run.task, limit=5)

    # Build items list with their scores
    items_with_scores = [
        (item, scores_by_item.get(item.item_id, {})) for item in filtered_items
    ]

    # Run async LLM analysis
    client = build_client(llm_config)
    model = llm_config.get("llm_model", "gpt-4o-mini")
    results: list[AnalysisResult] = await analyze_items_batch(
        client=client,
        model=model,
        items=items_with_scores,
        corrections=corrections,
        concurrency=request.concurrency,
    )

    # Save results to item_metadata
    response_results = []
    error_count = 0
    for result in results:
        item = next((i for i in filtered_items if i.item_id == result.item_id), None)
        if not item:
            continue

        if result.error:
            error_count += 1

        meta = dict(item.item_metadata) if isinstance(item.item_metadata, dict) else {}
        meta["root_cause"] = result.root_cause
        meta["root_cause_note"] = result.root_cause_note
        meta["root_cause_source"] = "ai"
        meta["root_cause_confidence"] = result.confidence
        item.item_metadata = meta

        response_results.append(
            {
                "item_id": result.item_id,
                "root_cause": result.root_cause,
                "root_cause_note": result.root_cause_note,
                "confidence": result.confidence,
                "error": result.error,
            }
        )

    db.commit()

    return {
        "total_analyzed": len(results),
        "results": response_results,
        "errors": error_count,
    }


@router.get("/api/runs/{run_id}/analysis-config")
def get_analysis_config(
    run_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> Dict[str, Any]:
    """Return analysis configuration for the frontend."""
    cfg = principal.user.llm_config if isinstance(principal.user.llm_config, dict) else {}

    run = db.query(Run).filter(Run.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    items = db.query(RunItem).filter(RunItem.run_id == run.id).all()
    total = len(items)
    with_rc = sum(
        1
        for i in items
        if isinstance(i.item_metadata, dict) and i.item_metadata.get("root_cause")
    )
    ai_assigned = sum(
        1
        for i in items
        if isinstance(i.item_metadata, dict)
        and i.item_metadata.get("root_cause_source") == "ai"
    )

    correction_count = (
        db.query(ReviewCorrection).filter(ReviewCorrection.task == run.task).count()
    )

    return {
        "llm_configured": bool(cfg.get("llm_api_key")),
        "model": cfg.get("llm_model") if cfg.get("llm_api_key") else None,
        "total_items": total,
        "items_with_root_cause": with_rc,
        "items_ai_assigned": ai_assigned,
        "items_without_root_cause": total - with_rc,
        "correction_bank_size": correction_count,
    }
