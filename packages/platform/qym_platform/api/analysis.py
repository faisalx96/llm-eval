from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from qym_platform.auth import Principal, require_ui_principal
from qym_platform.db.models import ReviewCorrection, Run, RunItem, RunItemScore
from qym_platform.deps import get_db
from qym_platform.services.llm_analyzer import (
    DEFAULT_SYSTEM_PROMPT,
    ROOT_CAUSE_CATEGORIES,
    AnalysisResult,
    analyze_items_batch,
    analyze_single_item,
    build_analysis_prompt,
    build_client,
    get_few_shot_examples,
)

router = APIRouter(tags=["analysis"])


class PlaygroundConfig(BaseModel):
    """Configuration overrides for the AI evaluator playground."""

    system_prompt: Optional[str] = None
    root_cause_categories: Optional[List[str]] = None
    include_fields: Optional[Dict[str, bool]] = None
    correction_ids: Optional[List[int]] = None
    corrections_enabled: bool = True
    field_mapping: Optional[Dict[str, str]] = None  # e.g. {"input": "input.question", "expected": "expected"}
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None


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
    config: Optional[PlaygroundConfig] = None


class PreviewRequest(BaseModel):
    """Request to preview the LLM messages for an item."""

    item_id: str
    config: Optional[PlaygroundConfig] = None


class TestRequest(BaseModel):
    """Request to test analysis on 1-3 items without saving."""

    item_ids: List[str] = Field(..., min_length=1, max_length=3)
    config: Optional[PlaygroundConfig] = None


def _get_llm_config(principal: Principal) -> dict[str, Any]:
    """Extract and validate LLM config from the current user."""
    cfg = principal.user.llm_config if isinstance(principal.user.llm_config, dict) else {}
    if not cfg.get("llm_api_key"):
        raise HTTPException(
            status_code=400,
            detail="LLM not configured. Please set up your LLM provider in your Profile page.",
        )
    return cfg


def _playground_config_to_analyzer(pg: PlaygroundConfig | None) -> dict[str, Any] | None:
    """Convert PlaygroundConfig to the dict format expected by llm_analyzer."""
    if pg is None:
        return None
    cfg: dict[str, Any] = {}
    if pg.system_prompt is not None:
        cfg["system_prompt"] = pg.system_prompt
    if pg.root_cause_categories is not None:
        cfg["root_cause_categories"] = pg.root_cause_categories
    if pg.include_fields is not None:
        cfg["include_fields"] = pg.include_fields
    if pg.correction_ids is not None:
        cfg["correction_ids"] = pg.correction_ids
    cfg["corrections_enabled"] = pg.corrections_enabled
    if pg.field_mapping is not None:
        cfg["field_mapping"] = pg.field_mapping
    return cfg if cfg else None


def _load_run_items_and_scores(
    db: Session, run: Run
) -> tuple[list[RunItem], dict[str, dict[str, RunItemScore]]]:
    """Load all items and scores for a run."""
    all_items: list[RunItem] = (
        db.query(RunItem)
        .filter(RunItem.run_id == run.id)
        .order_by(RunItem.index.asc())
        .all()
    )
    all_scores = db.query(RunItemScore).filter(RunItemScore.run_id == run.id).all()
    scores_by_item: dict[str, dict[str, RunItemScore]] = {}
    for s in all_scores:
        scores_by_item.setdefault(s.item_id, {})[s.metric_name] = s
    return all_items, scores_by_item


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

    all_items, scores_by_item = _load_run_items_and_scores(db, run)

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

    # Convert playground config
    analyzer_config = _playground_config_to_analyzer(request.config)

    # Run async LLM analysis
    client = build_client(llm_config)
    model = llm_config.get("llm_model", "gpt-4o-mini")
    results: list[AnalysisResult] = await analyze_items_batch(
        client=client,
        model=model,
        items=items_with_scores,
        corrections=corrections,
        concurrency=request.concurrency,
        config=analyzer_config,
        temperature=request.config.temperature if request.config else None,
        max_tokens=request.config.max_tokens if request.config else None,
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


@router.post("/api/runs/{run_id}/analyze-preview")
def analyze_preview(
    run_id: str,
    request: PreviewRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> Dict[str, Any]:
    """Return the exact LLM messages for an item with custom config (no LLM call)."""
    run = db.query(Run).filter(Run.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    item = (
        db.query(RunItem)
        .filter(RunItem.run_id == run.id, RunItem.item_id == request.item_id)
        .first()
    )
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    scores_list = (
        db.query(RunItemScore)
        .filter(RunItemScore.run_id == run.id, RunItemScore.item_id == request.item_id)
        .all()
    )
    scores = {s.metric_name: s for s in scores_list}

    corrections = get_few_shot_examples(db, task=run.task, limit=5)
    analyzer_config = _playground_config_to_analyzer(request.config)
    messages = build_analysis_prompt(item, scores, corrections, config=analyzer_config)

    return {"messages": messages}


@router.post("/api/runs/{run_id}/analyze-test")
async def analyze_test(
    run_id: str,
    request: TestRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> Dict[str, Any]:
    """Run analysis on 1-3 items with custom config. Does NOT save to DB."""
    llm_config = _get_llm_config(principal)

    run = db.query(Run).filter(Run.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    items = (
        db.query(RunItem)
        .filter(RunItem.run_id == run.id, RunItem.item_id.in_(request.item_ids))
        .all()
    )
    if not items:
        raise HTTPException(status_code=404, detail="No matching items found")

    all_scores = (
        db.query(RunItemScore)
        .filter(
            RunItemScore.run_id == run.id,
            RunItemScore.item_id.in_(request.item_ids),
        )
        .all()
    )
    scores_by_item: dict[str, dict[str, RunItemScore]] = {}
    for s in all_scores:
        scores_by_item.setdefault(s.item_id, {})[s.metric_name] = s

    corrections = get_few_shot_examples(db, task=run.task, limit=5)
    analyzer_config = _playground_config_to_analyzer(request.config)

    client = build_client(llm_config)
    model = llm_config.get("llm_model", "gpt-4o-mini")

    results = []
    for item in items:
        item_scores = scores_by_item.get(item.item_id, {})

        # Build prompt messages so we can return the inputs alongside the result
        messages = build_analysis_prompt(
            item, item_scores, corrections, config=analyzer_config,
        )

        result = await analyze_single_item(
            client=client,
            model=model,
            item=item,
            scores=item_scores,
            corrections=corrections,
            config=analyzer_config,
            temperature=request.config.temperature if request.config else None,
            max_tokens=request.config.max_tokens if request.config else None,
        )
        results.append({
            "item_id": result.item_id,
            "root_cause": result.root_cause,
            "root_cause_note": result.root_cause_note,
            "confidence": result.confidence,
            "error": result.error,
            "messages": messages,
        })

    return {"results": results}


@router.get("/api/runs/{run_id}/corrections")
def get_corrections(
    run_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> Dict[str, Any]:
    """Return correction bank entries for the run's task."""
    run = db.query(Run).filter(Run.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    corrections = (
        db.query(ReviewCorrection)
        .filter(ReviewCorrection.task == run.task)
        .order_by(ReviewCorrection.created_at.desc())
        .limit(20)
        .all()
    )

    return {
        "corrections": [
            {
                "id": c.id,
                "item_id": c.item_id,
                "human_root_cause": c.human_root_cause,
                "human_root_cause_note": c.human_root_cause_note,
                "ai_root_cause": c.ai_root_cause,
                "ai_root_cause_note": c.ai_root_cause_note,
                "created_at": c.created_at.isoformat() if c.created_at else None,
            }
            for c in corrections
        ]
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
        "default_system_prompt": DEFAULT_SYSTEM_PROMPT,
        "default_categories": ROOT_CAUSE_CATEGORIES,
    }
