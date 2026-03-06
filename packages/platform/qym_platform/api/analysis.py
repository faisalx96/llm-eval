from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from qym_platform.auth import Principal, require_ui_principal
from qym_platform.db.models import CorrectionStatus, ReviewCorrection, Run, RunItem, RunItemScore, User
from qym_platform.deps import get_db
from qym_platform.services.llm_analyzer import (
    DEFAULT_SYSTEM_PROMPT,
    ROOT_CAUSE_CATEGORIES,
    SOLUTION_CATEGORIES,
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
    additional_instructions: Optional[str] = None
    custom_variable_mapping: Optional[Dict[str, str]] = None
    root_cause_categories: Optional[List[str]] = None
    root_cause_details: Optional[List[str]] = None
    solution_categories: Optional[List[str]] = None
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
    allow_human_overwrite: bool = False
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
    if pg.root_cause_details is not None:
        cfg["root_cause_details"] = pg.root_cause_details
    if pg.solution_categories is not None:
        cfg["solution_categories"] = pg.solution_categories
    if pg.include_fields is not None:
        cfg["include_fields"] = pg.include_fields
    if pg.correction_ids is not None:
        cfg["correction_ids"] = pg.correction_ids
    cfg["corrections_enabled"] = pg.corrections_enabled
    if pg.field_mapping is not None:
        cfg["field_mapping"] = pg.field_mapping
    if pg.additional_instructions is not None:
        cfg["additional_instructions"] = pg.additional_instructions
    if pg.custom_variable_mapping is not None:
        cfg["custom_variable_mapping"] = pg.custom_variable_mapping
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


@router.post("/api/runs/{run_id:path}/analyze")
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

        # Never overwrite human labels unless explicitly allowed
        if md.get("root_cause_source") == "human" and not request.allow_human_overwrite:
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

    # Convert playground config
    analyzer_config = _playground_config_to_analyzer(request.config)

    # Get few-shot examples from correction bank
    cfg_ids = (analyzer_config or {}).get("correction_ids")
    corrections = get_few_shot_examples(db, task=run.task, limit=5, correction_ids=cfg_ids)

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

        meta = dict(item.item_metadata) if isinstance(item.item_metadata, dict) else {}

        if result.error:
            error_count += 1
            meta["analysis_error"] = result.error
        else:
            meta.pop("analysis_error", None)
            meta["root_cause"] = result.root_cause
            meta["root_cause_detail"] = result.root_cause_detail
            meta["root_cause_note"] = result.root_cause_note
            meta["root_cause_source"] = "ai"
            meta["root_cause_confidence"] = result.confidence
            meta["solution"] = result.solution
            meta["solution_note"] = result.solution_note
            meta["solution_source"] = "ai"

        item.item_metadata = meta

        response_results.append(
            {
                "item_id": result.item_id,
                "root_cause": result.root_cause,
                "root_cause_detail": result.root_cause_detail,
                "root_cause_note": result.root_cause_note,
                "confidence": result.confidence,
                "solution": result.solution,
                "solution_note": result.solution_note,
                "error": result.error,
            }
        )

    db.commit()

    return {
        "total_analyzed": len(results),
        "results": response_results,
        "errors": error_count,
    }


@router.post("/api/runs/{run_id:path}/analyze-preview")
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

    analyzer_config = _playground_config_to_analyzer(request.config)
    cfg_ids = (analyzer_config or {}).get("correction_ids")
    corrections = get_few_shot_examples(db, task=run.task, limit=5, correction_ids=cfg_ids)
    messages = build_analysis_prompt(item, scores, corrections, config=analyzer_config)

    return {"messages": messages}


@router.post("/api/runs/{run_id:path}/analyze-test")
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

    analyzer_config = _playground_config_to_analyzer(request.config)
    cfg_ids = (analyzer_config or {}).get("correction_ids")
    corrections = get_few_shot_examples(db, task=run.task, limit=5, correction_ids=cfg_ids)

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
            "root_cause_detail": result.root_cause_detail,
            "root_cause_note": result.root_cause_note,
            "confidence": result.confidence,
            "solution": result.solution,
            "solution_note": result.solution_note,
            "error": result.error,
            "messages": messages,
        })

    return {"results": results}


@router.get("/api/runs/{run_id:path}/corrections")
def get_corrections(
    run_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> Dict[str, Any]:
    """Return approved correction bank entries for the run's task."""
    run = db.query(Run).filter(Run.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    corrections = (
        db.query(ReviewCorrection)
        .filter(
            ReviewCorrection.task == run.task,
            ReviewCorrection.status == CorrectionStatus.APPROVED,
        )
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
                "human_root_cause_detail": c.human_root_cause_detail,
                "human_root_cause_note": c.human_root_cause_note,
                "ai_root_cause": c.ai_root_cause,
                "ai_root_cause_detail": c.ai_root_cause_detail,
                "ai_root_cause_note": c.ai_root_cause_note,
                "ai_confidence": c.ai_confidence,
                "ai_solution": c.ai_solution,
                "human_solution": c.human_solution,
                "human_solution_note": c.human_solution_note,
                "input_snapshot": c.input_snapshot,
                "expected_snapshot": c.expected_snapshot,
                "output_snapshot": c.output_snapshot,
                "status": c.status.value if hasattr(c.status, "value") else (c.status or "pending"),
                "created_at": c.created_at.isoformat() if c.created_at else None,
            }
            for c in corrections
        ]
    }


@router.get("/api/runs/{run_id:path}/analysis-config")
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

    # Collect existing root_cause values from items and merge with defaults
    existing_categories = {
        str(i.item_metadata.get("root_cause", ""))
        for i in items
        if isinstance(i.item_metadata, dict) and i.item_metadata.get("root_cause")
    }
    # Defaults first, then any custom categories from the run (sorted)
    all_categories = list(ROOT_CAUSE_CATEGORIES) + sorted(
        existing_categories - set(ROOT_CAUSE_CATEGORIES)
    )

    # Collect existing root_cause_detail values from items
    existing_details = sorted({
        str(i.item_metadata.get("root_cause_detail", ""))
        for i in items
        if isinstance(i.item_metadata, dict) and i.item_metadata.get("root_cause_detail")
    })

    return {
        "llm_configured": bool(cfg.get("llm_api_key")),
        "model": cfg.get("llm_model") if cfg.get("llm_api_key") else None,
        "total_items": total,
        "items_with_root_cause": with_rc,
        "items_ai_assigned": ai_assigned,
        "items_without_root_cause": total - with_rc,
        "correction_bank_size": correction_count,
        "default_system_prompt": DEFAULT_SYSTEM_PROMPT,
        "default_categories": all_categories,
        "default_solution_categories": SOLUTION_CATEGORIES,
        "existing_details": existing_details,
    }


# ── Correction Management Endpoints (for /reviews page) ─────────────


def _serialize_correction(c: ReviewCorrection, db: Session) -> Dict[str, Any]:
    """Serialize a ReviewCorrection to a dict for the API."""
    corrected_by = None
    if c.corrected_by_user_id:
        user = db.query(User).filter(User.id == c.corrected_by_user_id).first()
        if user:
            corrected_by = {
                "id": user.id,
                "email": user.email,
                "display_name": user.display_name or user.email.split("@")[0],
            }

    reviewed_by = None
    if c.reviewed_by_user_id:
        user = db.query(User).filter(User.id == c.reviewed_by_user_id).first()
        if user:
            reviewed_by = {
                "id": user.id,
                "email": user.email,
                "display_name": user.display_name or user.email.split("@")[0],
            }

    ai_root_cause = (c.ai_root_cause or "").strip()
    ai_is_unanalyzed = ai_root_cause.lower() == "unanalyzed"

    return {
        "id": c.id,
        "run_id": c.run_id,
        "item_id": c.item_id,
        "task": c.task,
        "input_snapshot": c.input_snapshot,
        "expected_snapshot": c.expected_snapshot,
        "output_snapshot": c.output_snapshot,
        "scores_snapshot": c.scores_snapshot,
        "ai_root_cause": "" if ai_is_unanalyzed else c.ai_root_cause,
        "ai_root_cause_detail": "" if ai_is_unanalyzed else c.ai_root_cause_detail,
        "ai_root_cause_note": "" if ai_is_unanalyzed else c.ai_root_cause_note,
        "ai_confidence": None if ai_is_unanalyzed else c.ai_confidence,
        "ai_solution": "" if ai_is_unanalyzed else c.ai_solution,
        "ai_solution_note": "" if ai_is_unanalyzed else c.ai_solution_note,
        "human_root_cause": c.human_root_cause,
        "human_root_cause_detail": c.human_root_cause_detail,
        "human_root_cause_note": c.human_root_cause_note,
        "human_solution": c.human_solution,
        "human_solution_note": c.human_solution_note,
        "corrected_by": corrected_by,
        "created_at": c.created_at.isoformat() if c.created_at else None,
        "status": c.status.value if hasattr(c.status, "value") else c.status,
        "reviewed_by": reviewed_by,
        "reviewed_at": c.reviewed_at.isoformat() if c.reviewed_at else None,
        "review_comment": c.review_comment or "",
    }


@router.get("/api/corrections")
def list_corrections(
    task: Optional[str] = Query(None),
    status: Optional[str] = Query(None, alias="status"),
    search: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> Dict[str, Any]:
    """List all corrections with optional filtering."""
    from sqlalchemy import func, or_

    query = db.query(ReviewCorrection).order_by(ReviewCorrection.created_at.desc())

    if task:
        query = query.filter(ReviewCorrection.task == task)
    if status:
        try:
            cs = CorrectionStatus(status)
            query = query.filter(ReviewCorrection.status == cs)
        except ValueError:
            pass
    if search:
        like = f"%{search}%"
        query = query.filter(
            or_(
                ReviewCorrection.task.ilike(like),
                ReviewCorrection.item_id.ilike(like),
                ReviewCorrection.human_root_cause.ilike(like),
                ReviewCorrection.ai_root_cause.ilike(like),
            )
        )

    corrections = query.all()

    # Compute stats via COUNT queries (avoid loading all rows)
    total = db.query(func.count(ReviewCorrection.id)).scalar() or 0
    pending = db.query(func.count(ReviewCorrection.id)).filter(
        ReviewCorrection.status == CorrectionStatus.PENDING
    ).scalar() or 0
    approved = db.query(func.count(ReviewCorrection.id)).filter(
        ReviewCorrection.status == CorrectionStatus.APPROVED
    ).scalar() or 0
    rejected = db.query(func.count(ReviewCorrection.id)).filter(
        ReviewCorrection.status == CorrectionStatus.REJECTED
    ).scalar() or 0

    stats = {"total": total, "pending": pending, "approved": approved, "rejected": rejected}

    # Get distinct tasks for filter dropdown
    task_rows = db.query(ReviewCorrection.task).distinct().order_by(ReviewCorrection.task).all()
    tasks = [r[0] for r in task_rows]

    return {
        "corrections": [_serialize_correction(c, db) for c in corrections],
        "stats": stats,
        "tasks": tasks,
    }


@router.get("/api/corrections/{correction_id}")
def get_correction(
    correction_id: int,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> Dict[str, Any]:
    """Get a single correction by ID."""
    c = db.query(ReviewCorrection).filter(ReviewCorrection.id == correction_id).first()
    if not c:
        raise HTTPException(status_code=404, detail="Correction not found")
    return _serialize_correction(c, db)


@router.put("/api/corrections/{correction_id}")
def update_correction(
    correction_id: int,
    request: Dict[str, Any],
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> Dict[str, Any]:
    """Update a correction and sync the corresponding run item metadata."""
    c = db.query(ReviewCorrection).filter(ReviewCorrection.id == correction_id).first()
    if not c:
        raise HTTPException(status_code=404, detail="Correction not found")

    for field in [
        "human_root_cause", "human_root_cause_detail", "human_root_cause_note",
        "human_solution", "human_solution_note",
    ]:
        if field in request:
            setattr(c, field, (request[field] or "").strip())

    # Keep run/compare views consistent with review edits.
    item = (
        db.query(RunItem)
        .filter(RunItem.run_id == c.run_id, RunItem.item_id == c.item_id)
        .first()
    )
    if item:
        meta = dict(item.item_metadata) if isinstance(item.item_metadata, dict) else {}

        if c.human_root_cause:
            meta["root_cause"] = c.human_root_cause
            meta["root_cause_source"] = "human"
            meta.pop("root_cause_confidence", None)
        else:
            meta.pop("root_cause", None)
            meta.pop("root_cause_source", None)
            meta.pop("root_cause_confidence", None)
            meta.pop("root_cause_detail", None)
            meta.pop("root_cause_note", None)

        if c.human_root_cause_detail:
            meta["root_cause_detail"] = c.human_root_cause_detail
        else:
            meta.pop("root_cause_detail", None)

        if c.human_root_cause_note:
            meta["root_cause_note"] = c.human_root_cause_note
        else:
            meta.pop("root_cause_note", None)

        if c.human_solution:
            meta["solution"] = c.human_solution
            meta["solution_source"] = "human"
        else:
            meta.pop("solution", None)
            meta.pop("solution_source", None)

        if c.human_solution_note:
            meta["solution_note"] = c.human_solution_note
        else:
            meta.pop("solution_note", None)

        item.item_metadata = meta

    db.commit()
    return _serialize_correction(c, db)


@router.post("/api/corrections/{correction_id}/approve")
def approve_correction(
    correction_id: int,
    request: Dict[str, Any],
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> Dict[str, Any]:
    """Approve a correction so it feeds into few-shot examples."""
    c = db.query(ReviewCorrection).filter(ReviewCorrection.id == correction_id).first()
    if not c:
        raise HTTPException(status_code=404, detail="Correction not found")

    c.status = CorrectionStatus.APPROVED
    c.reviewed_by_user_id = principal.user.id if principal.auth_type != "none" else None
    c.reviewed_at = datetime.utcnow()
    c.review_comment = (request.get("comment") or "").strip()

    db.commit()
    return _serialize_correction(c, db)


@router.post("/api/corrections/{correction_id}/reject")
def reject_correction(
    correction_id: int,
    request: Dict[str, Any],
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> Dict[str, Any]:
    """Reject a correction (won't be used as few-shot example)."""
    c = db.query(ReviewCorrection).filter(ReviewCorrection.id == correction_id).first()
    if not c:
        raise HTTPException(status_code=404, detail="Correction not found")

    c.status = CorrectionStatus.REJECTED
    c.reviewed_by_user_id = principal.user.id if principal.auth_type != "none" else None
    c.reviewed_at = datetime.utcnow()
    c.review_comment = (request.get("comment") or "").strip()

    db.commit()
    return _serialize_correction(c, db)


@router.post("/api/corrections/{correction_id}/reset")
def reset_correction(
    correction_id: int,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> Dict[str, Any]:
    """Reset a correction back to pending status."""
    c = db.query(ReviewCorrection).filter(ReviewCorrection.id == correction_id).first()
    if not c:
        raise HTTPException(status_code=404, detail="Correction not found")

    c.status = CorrectionStatus.PENDING
    c.reviewed_by_user_id = None
    c.reviewed_at = None
    c.review_comment = ""

    db.commit()
    return _serialize_correction(c, db)


class BulkActionRequest(BaseModel):
    ids: List[int]
    action: str  # approve | reject | reset | delete
    comment: str = ""


@router.post("/api/corrections/bulk")
def bulk_correction_action(
    request: BulkActionRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> Dict[str, Any]:
    """Perform a bulk action on multiple corrections."""
    if not request.ids:
        raise HTTPException(status_code=400, detail="No correction IDs provided")

    corrections = (
        db.query(ReviewCorrection)
        .filter(ReviewCorrection.id.in_(request.ids))
        .all()
    )

    if not corrections:
        raise HTTPException(status_code=404, detail="No corrections found")

    now = datetime.utcnow()
    reviewer_id = principal.user.id if principal.auth_type != "none" else None
    affected = 0

    for c in corrections:
        if request.action == "approve":
            c.status = CorrectionStatus.APPROVED
            c.reviewed_by_user_id = reviewer_id
            c.reviewed_at = now
            c.review_comment = request.comment
            affected += 1
        elif request.action == "reject":
            c.status = CorrectionStatus.REJECTED
            c.reviewed_by_user_id = reviewer_id
            c.reviewed_at = now
            c.review_comment = request.comment
            affected += 1
        elif request.action == "reset":
            c.status = CorrectionStatus.PENDING
            c.reviewed_by_user_id = None
            c.reviewed_at = None
            c.review_comment = ""
            affected += 1
        elif request.action == "delete":
            db.delete(c)
            affected += 1

    db.commit()
    return {"ok": True, "affected": affected}


@router.delete("/api/corrections/{correction_id}")
def delete_correction(
    correction_id: int,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> Dict[str, Any]:
    """Delete a single correction."""
    c = db.query(ReviewCorrection).filter(ReviewCorrection.id == correction_id).first()
    if not c:
        raise HTTPException(status_code=404, detail="Correction not found")
    db.delete(c)
    db.commit()
    return {"ok": True, "deleted_id": correction_id}
