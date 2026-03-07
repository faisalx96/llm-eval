from __future__ import annotations

import ast
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import and_, func, or_, tuple_
from sqlalchemy.orm import Session

from qym_platform.auth import Principal, require_ui_principal
from qym_platform.db.models import CorrectionStatus, ReviewCorrection, RootCauseRevision, Run, RunItem, RunItemScore, User
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
from qym_platform.services.root_cause_changes import apply_root_cause_change, build_ai_state

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

    # Save results to item_metadata and revision history
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
            item.item_metadata = meta
        else:
            if "analysis_error" in meta:
                meta.pop("analysis_error", None)
                item.item_metadata = meta
            apply_root_cause_change(
                db,
                run=run,
                item=item,
                actor_user_id=principal.user.id if principal.auth_type != "none" else None,
                actor_source="ai",
                next_state=build_ai_state(
                    root_cause=result.root_cause,
                    root_cause_detail=result.root_cause_detail,
                    root_cause_note=result.root_cause_note,
                    confidence=result.confidence,
                    solution=result.solution,
                    solution_note=result.solution_note,
                ),
            )

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
            ReviewCorrection.is_active.is_(True),
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
        db.query(ReviewCorrection)
        .filter(
            ReviewCorrection.task == run.task,
            ReviewCorrection.status == CorrectionStatus.APPROVED,
            ReviewCorrection.is_active.is_(True),
        )
        .count()
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


def _serialize_user(user: Optional[User]) -> Optional[Dict[str, Any]]:
    if not user:
        return None
    return {
        "id": user.id,
        "email": user.email,
        "display_name": user.display_name or user.email.split("@")[0],
    }


def _load_users_map(db: Session, user_ids: set[str]) -> Dict[str, User]:
    if not user_ids:
        return {}
    users = db.query(User).filter(User.id.in_(sorted(user_ids))).all()
    return {u.id: u for u in users}


def _strip_model_provider(model_name: str) -> str:
    if not model_name:
        return ""
    idx = model_name.find("/")
    return model_name[idx + 1:] if idx > 0 else model_name


def _run_display_name(run: Optional[Run]) -> str:
    if not run:
        return ""
    if isinstance(run.run_config, dict):
        configured = str(run.run_config.get("run_name") or "").strip()
        if configured:
            return configured
    return str(run.external_run_id or run.id or "").strip()


def _load_runs_map(db: Session, run_ids: set[str]) -> Dict[str, Run]:
    if not run_ids:
        return {}
    runs = db.query(Run).filter(Run.id.in_(sorted(run_ids))).all()
    return {run.id: run for run in runs}


def _run_name_value(run_id: str, external_run_id: Optional[str], configured_name: Optional[str]) -> str:
    configured = str(configured_name or "").strip()
    if configured:
        return configured
    return str(external_run_id or run_id or "").strip()


def _normalize_snapshot_value(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    trimmed = value.strip()
    if not trimmed:
        return value
    if not (
        (trimmed.startswith("{") and trimmed.endswith("}"))
        or (trimmed.startswith("[") and trimmed.endswith("]"))
    ):
        return value
    try:
        parsed = ast.literal_eval(trimmed)
    except (SyntaxError, ValueError):
        return value
    return parsed


def _serialize_review_fields(
    c: ReviewCorrection,
    *,
    users_by_id: Dict[str, User],
    runs_by_id: Dict[str, Run],
) -> Dict[str, Any]:
    ai_root_cause = (c.ai_root_cause or "").strip()
    ai_is_unanalyzed = ai_root_cause.lower() == "unanalyzed"
    run = runs_by_id.get(c.run_id)
    return {
        "id": c.id,
        "revision_id": c.revision_id,
        "run_id": c.run_id,
        "item_id": c.item_id,
        "task": c.task,
        "dataset": run.dataset if run else "",
        "model": _strip_model_provider(run.model or "") if run else "",
        "run_name": _run_display_name(run),
        "input_snapshot": _normalize_snapshot_value(c.input_snapshot),
        "expected_snapshot": _normalize_snapshot_value(c.expected_snapshot),
        "output_snapshot": _normalize_snapshot_value(c.output_snapshot),
        "scores_snapshot": _normalize_snapshot_value(c.scores_snapshot),
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
        "corrected_by": _serialize_user(users_by_id.get(c.corrected_by_user_id)),
        "created_at": c.created_at.isoformat() if c.created_at else None,
        "status": c.status.value if hasattr(c.status, "value") else c.status,
        "is_active": bool(c.is_active),
        "reviewed_by": _serialize_user(users_by_id.get(c.reviewed_by_user_id)),
        "reviewed_at": c.reviewed_at.isoformat() if c.reviewed_at else None,
        "review_comment": c.review_comment or "",
    }


def _build_history_map(
    db: Session,
    corrections: List[ReviewCorrection],
) -> tuple[Dict[tuple[str, str], List[Dict[str, Any]]], Dict[str, User]]:
    keys = sorted({(c.run_id, c.item_id) for c in corrections})
    if not keys:
        return {}, {}

    revisions = (
        db.query(RootCauseRevision)
        .filter(tuple_(RootCauseRevision.run_id, RootCauseRevision.item_id).in_(keys))
        .order_by(
            RootCauseRevision.run_id.asc(),
            RootCauseRevision.item_id.asc(),
            RootCauseRevision.revision_number.desc(),
        )
        .all()
    )
    all_candidates = (
        db.query(ReviewCorrection)
        .filter(tuple_(ReviewCorrection.run_id, ReviewCorrection.item_id).in_(keys))
        .order_by(ReviewCorrection.created_at.desc())
        .all()
    )

    user_ids: set[str] = {
        uid
        for uid in [
            *(r.actor_user_id for r in revisions if r.actor_user_id),
            *(c.corrected_by_user_id for c in all_candidates if c.corrected_by_user_id),
            *(c.reviewed_by_user_id for c in all_candidates if c.reviewed_by_user_id),
        ]
        if uid
    }
    users_by_id = _load_users_map(db, user_ids)
    runs_by_id = _load_runs_map(db, {run_id for run_id, _ in keys})

    candidates_by_revision: Dict[int, ReviewCorrection] = {}
    orphan_candidates: Dict[tuple[str, str], List[ReviewCorrection]] = {}
    for candidate in all_candidates:
        if candidate.revision_id is not None and candidate.revision_id not in candidates_by_revision:
            candidates_by_revision[candidate.revision_id] = candidate
        elif candidate.revision_id is None:
            orphan_candidates.setdefault((candidate.run_id, candidate.item_id), []).append(candidate)

    history_map: Dict[tuple[str, str], List[Dict[str, Any]]] = {}
    revisions_by_key: Dict[tuple[str, str], List[RootCauseRevision]] = {}
    for revision in revisions:
        revisions_by_key.setdefault((revision.run_id, revision.item_id), []).append(revision)

    for key, revision_list in revisions_by_key.items():
        entries: List[Dict[str, Any]] = []
        for revision in revision_list:
            review_candidate = candidates_by_revision.get(revision.id)
            entries.append(
                {
                    "revision_id": revision.id,
                    "revision_number": revision.revision_number,
                    "actor_source": revision.actor_source,
                    "actor_user": _serialize_user(users_by_id.get(revision.actor_user_id)),
                    "before_state": revision.before_state or {},
                    "after_state": revision.after_state or {},
                    "backfilled_from_legacy": bool(revision.backfilled_from_legacy),
                    "created_at": revision.created_at.isoformat() if revision.created_at else None,
                    "review": (
                        _serialize_review_fields(
                            review_candidate,
                            users_by_id=users_by_id,
                            runs_by_id=runs_by_id,
                        )
                        if review_candidate
                        else None
                    ),
                }
            )
        for orphan in orphan_candidates.get(key, []):
            entries.append(
                {
                    "revision_id": None,
                    "revision_number": None,
                    "actor_source": "legacy",
                    "actor_user": _serialize_user(users_by_id.get(orphan.corrected_by_user_id)),
                    "before_state": {},
                    "after_state": {},
                    "backfilled_from_legacy": True,
                    "created_at": orphan.created_at.isoformat() if orphan.created_at else None,
                    "review": _serialize_review_fields(orphan, users_by_id=users_by_id, runs_by_id=runs_by_id),
                }
            )
        history_map[key] = sorted(
            entries,
            key=lambda entry: (
                entry["revision_number"] if entry["revision_number"] is not None else -1,
                entry["created_at"] or "",
            ),
            reverse=True,
        )

    for key, candidates in orphan_candidates.items():
        if key in history_map:
            continue
        history_map[key] = [
            {
                "revision_id": None,
                "revision_number": None,
                "actor_source": "legacy",
                "actor_user": _serialize_user(users_by_id.get(candidate.corrected_by_user_id)),
                "before_state": {},
                "after_state": {},
                "backfilled_from_legacy": True,
                "created_at": candidate.created_at.isoformat() if candidate.created_at else None,
                "review": _serialize_review_fields(candidate, users_by_id=users_by_id, runs_by_id=runs_by_id),
            }
            for candidate in candidates
        ]

    return history_map, users_by_id


def _serialize_correction(
    c: ReviewCorrection,
    *,
    users_by_id: Dict[str, User],
    runs_by_id: Dict[str, Run],
    history: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    payload = _serialize_review_fields(c, users_by_id=users_by_id, runs_by_id=runs_by_id)
    payload["history"] = history or []
    return payload


def _serialize_corrections_with_history(
    db: Session,
    corrections: List[ReviewCorrection],
) -> List[Dict[str, Any]]:
    history_map, users_by_id = _build_history_map(db, corrections)
    runs_by_id = _load_runs_map(db, {correction.run_id for correction in corrections})
    serialized: List[Dict[str, Any]] = []
    for correction in corrections:
        serialized.append(
            _serialize_correction(
                correction,
                users_by_id=users_by_id,
                runs_by_id=runs_by_id,
                history=history_map.get((correction.run_id, correction.item_id), []),
            )
        )
    return serialized


def _require_active_candidate(correction: ReviewCorrection) -> None:
    if not correction.is_active:
        raise HTTPException(status_code=409, detail="Historical corrections are immutable")


def _approve_candidate(
    db: Session,
    *,
    correction: ReviewCorrection,
    reviewer_id: Optional[str],
    comment: str,
    reviewed_at: datetime,
) -> None:
    _require_active_candidate(correction)

    has_human_label = any(
        str(value or "").strip()
        for value in (
            correction.human_root_cause,
            correction.human_root_cause_detail,
            correction.human_root_cause_note,
            correction.human_solution,
            correction.human_solution_note,
        )
    )
    if not has_human_label and str(correction.ai_root_cause or "").strip():
        correction.human_root_cause = correction.ai_root_cause or ""
        correction.human_root_cause_detail = correction.ai_root_cause_detail or ""
        correction.human_root_cause_note = correction.ai_root_cause_note or ""
        correction.human_solution = correction.ai_solution or ""
        correction.human_solution_note = correction.ai_solution_note or ""

    older_approved = (
        db.query(ReviewCorrection)
        .filter(
            ReviewCorrection.run_id == correction.run_id,
            ReviewCorrection.item_id == correction.item_id,
            ReviewCorrection.id != correction.id,
            ReviewCorrection.status == CorrectionStatus.APPROVED,
        )
        .all()
    )
    for candidate in older_approved:
        candidate.status = CorrectionStatus.SUPERSEDED
        candidate.is_active = False

    correction.status = CorrectionStatus.APPROVED
    correction.is_active = True
    correction.reviewed_by_user_id = reviewer_id
    correction.reviewed_at = reviewed_at
    correction.review_comment = comment


def _delete_active_candidate(db: Session, correction: ReviewCorrection) -> None:
    _require_active_candidate(correction)

    run = db.query(Run).filter(Run.id == correction.run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    item = (
        db.query(RunItem)
        .filter(RunItem.run_id == correction.run_id, RunItem.item_id == correction.item_id)
        .first()
    )
    if not item:
        raise HTTPException(status_code=404, detail="Run item not found")

    apply_root_cause_change(
        db,
        run=run,
        item=item,
        actor_user_id=None,
        actor_source="system",
        next_state={},
    )
    db.delete(correction)


@router.get("/api/corrections")
def list_corrections(
    task: Optional[List[str]] = Query(None),
    dataset: Optional[List[str]] = Query(None),
    model: Optional[List[str]] = Query(None),
    run_name: Optional[List[str]] = Query(None),
    source: Optional[str] = Query(None),
    conf_min: int = Query(0, ge=0, le=100),
    conf_max: int = Query(100, ge=0, le=100),
    status: Optional[str] = Query(None, alias="status"),
    search: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> Dict[str, Any]:
    """List all corrections with optional filtering."""
    run_name_expr = func.coalesce(Run.run_config.op("->>")("run_name"), "")
    ai_root_cause_expr = func.btrim(func.coalesce(ReviewCorrection.ai_root_cause, ""))
    ai_root_cause_detail_expr = func.btrim(func.coalesce(ReviewCorrection.ai_root_cause_detail, ""))
    ai_root_cause_note_expr = func.btrim(func.coalesce(ReviewCorrection.ai_root_cause_note, ""))
    ai_solution_expr = func.btrim(func.coalesce(ReviewCorrection.ai_solution, ""))
    ai_solution_note_expr = func.btrim(func.coalesce(ReviewCorrection.ai_solution_note, ""))
    human_root_cause_expr = func.btrim(func.coalesce(ReviewCorrection.human_root_cause, ""))
    human_root_cause_detail_expr = func.btrim(func.coalesce(ReviewCorrection.human_root_cause_detail, ""))
    human_root_cause_note_expr = func.btrim(func.coalesce(ReviewCorrection.human_root_cause_note, ""))
    human_solution_expr = func.btrim(func.coalesce(ReviewCorrection.human_solution, ""))
    human_solution_note_expr = func.btrim(func.coalesce(ReviewCorrection.human_solution_note, ""))

    has_ai_data = or_(
        and_(ai_root_cause_expr != "", func.lower(ai_root_cause_expr) != "unanalyzed"),
        ai_root_cause_detail_expr != "",
        ai_root_cause_note_expr != "",
        ai_solution_expr != "",
        ai_solution_note_expr != "",
    )
    has_human_data = or_(
        human_root_cause_expr != "",
        human_root_cause_detail_expr != "",
        human_root_cause_note_expr != "",
        human_solution_expr != "",
        human_solution_note_expr != "",
    )
    is_changed = or_(
        ai_root_cause_expr != human_root_cause_expr,
        ai_root_cause_detail_expr != human_root_cause_detail_expr,
        ai_root_cause_note_expr != human_root_cause_note_expr,
        ai_solution_expr != human_solution_expr,
        ai_solution_note_expr != human_solution_note_expr,
    )

    active_query = (
        db.query(ReviewCorrection)
        .join(Run, Run.id == ReviewCorrection.run_id)
        .filter(ReviewCorrection.is_active.is_(True))
    )
    def apply_filter_set(base_query, *, exclude: Optional[str] = None):
        query_obj = base_query
        if task and exclude != "task":
            query_obj = query_obj.filter(ReviewCorrection.task.in_(task))
        if dataset and exclude != "dataset":
            query_obj = query_obj.filter(Run.dataset.in_(dataset))
        if model and exclude != "model":
            query_obj = query_obj.filter(
                or_(
                    *([Run.model == value for value in model] + [Run.model.ilike(f"%/{value}") for value in model])
                )
            )
        if run_name and exclude != "run_name":
            query_obj = query_obj.filter(
                or_(
                    Run.external_run_id.in_(run_name),
                    run_name_expr.in_(run_name),
                    Run.id.in_(run_name),
                )
            )
        if source == "ai_only":
            query_obj = query_obj.filter(
                has_ai_data,
                or_(~has_human_data, ~is_changed),
            )
        elif source == "human_only":
            query_obj = query_obj.filter(has_human_data, ~has_ai_data)
        elif source == "corrected":
            query_obj = query_obj.filter(has_ai_data, has_human_data, is_changed)
        if conf_min > 0 or conf_max < 100:
            lo = conf_min / 100.0
            hi = conf_max / 100.0
            query_obj = query_obj.filter(
                ReviewCorrection.ai_confidence.is_not(None),
                ReviewCorrection.ai_confidence >= lo,
                ReviewCorrection.ai_confidence <= hi,
            )
        if status and exclude != "status":
            try:
                cs = CorrectionStatus(status)
                query_obj = query_obj.filter(ReviewCorrection.status == cs)
            except ValueError:
                pass
        if search:
            like = f"%{search}%"
            query_obj = query_obj.filter(
                or_(
                    ReviewCorrection.task.ilike(like),
                    ReviewCorrection.item_id.ilike(like),
                    ReviewCorrection.human_root_cause.ilike(like),
                    ReviewCorrection.ai_root_cause.ilike(like),
                    Run.dataset.ilike(like),
                    Run.model.ilike(like),
                    Run.external_run_id.ilike(like),
                    run_name_expr.ilike(like),
                )
            )
        return query_obj

    def facet_value_expr(key: str):
        if key == "task":
            return ReviewCorrection.task
        if key == "dataset":
            return Run.dataset
        if key == "model":
            return Run.model
        if key == "run_name":
            return run_name_expr
        raise ValueError(f"Unsupported facet key: {key}")

    def build_facet_counts(key: str) -> Dict[str, int]:
        facet_query = apply_filter_set(active_query, exclude=key)
        if key == "model":
            rows = facet_query.with_entities(Run.model, func.count(ReviewCorrection.id)).group_by(Run.model).all()
            counts: Dict[str, int] = {}
            for raw_model, count in rows:
                if not raw_model:
                    continue
                display = _strip_model_provider(raw_model or "")
                counts[display] = counts.get(display, 0) + int(count or 0)
            return counts
        if key == "run_name":
            rows = (
                facet_query
                .with_entities(Run.id, Run.external_run_id, run_name_expr, func.count(ReviewCorrection.id))
                .group_by(Run.id, Run.external_run_id, run_name_expr)
                .all()
            )
            counts: Dict[str, int] = {}
            for run_id_value, external_run_id, configured_name, count in rows:
                display = _run_name_value(run_id_value, external_run_id, configured_name)
                if not display:
                    continue
                counts[display] = counts.get(display, 0) + int(count or 0)
            return counts
        value_expr = facet_value_expr(key)
        rows = facet_query.with_entities(value_expr, func.count(ReviewCorrection.id)).group_by(value_expr).all()
        return {
            str(value): int(count or 0)
            for value, count in rows
            if str(value or "").strip()
        }

    query = apply_filter_set(active_query).order_by(ReviewCorrection.created_at.desc())

    corrections = query.all()

    # Compute stats excluding status filter so stat cards show the breakdown
    stats_query = apply_filter_set(active_query, exclude="status")
    total = stats_query.with_entities(func.count(ReviewCorrection.id)).scalar() or 0
    pending = stats_query.filter(ReviewCorrection.status == CorrectionStatus.PENDING).with_entities(
        func.count(ReviewCorrection.id)
    ).scalar() or 0
    approved = stats_query.filter(ReviewCorrection.status == CorrectionStatus.APPROVED).with_entities(
        func.count(ReviewCorrection.id)
    ).scalar() or 0
    rejected = stats_query.filter(ReviewCorrection.status == CorrectionStatus.REJECTED).with_entities(
        func.count(ReviewCorrection.id)
    ).scalar() or 0

    stats = {"total": total, "pending": pending, "approved": approved, "rejected": rejected}

    # Get distinct tasks for filter dropdown
    task_rows = (
        apply_filter_set(active_query, exclude="task")
        .with_entities(ReviewCorrection.task)
        .distinct()
        .order_by(ReviewCorrection.task)
        .all()
    )
    tasks = [r[0] for r in task_rows]
    dataset_rows = (
        apply_filter_set(active_query, exclude="dataset")
        .with_entities(Run.dataset)
        .distinct()
        .order_by(Run.dataset)
        .all()
    )
    datasets = [r[0] for r in dataset_rows if r[0]]
    model_rows = (
        apply_filter_set(active_query, exclude="model")
        .with_entities(Run.model)
        .distinct()
        .order_by(Run.model)
        .all()
    )
    models = [_strip_model_provider(r[0] or "") for r in model_rows if r[0]]
    run_rows = (
        apply_filter_set(active_query, exclude="run_name")
        .with_entities(Run.id, Run.external_run_id, run_name_expr.label("run_name"))
        .distinct()
        .all()
    )
    run_names = sorted(
        {
            (
                _run_name_value(run_id, external, configured_name)
            )
            for run_id, external, configured_name in run_rows
            if _run_name_value(run_id, external, configured_name)
        }
    )

    return {
        "corrections": _serialize_corrections_with_history(db, corrections),
        "stats": stats,
        "tasks": tasks,
        "datasets": datasets,
        "models": sorted(set(models)),
        "run_names": run_names,
        "facet_counts": {
            "task": build_facet_counts("task"),
            "dataset": build_facet_counts("dataset"),
            "model": build_facet_counts("model"),
            "run_name": build_facet_counts("run_name"),
        },
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
    return _serialize_corrections_with_history(db, [c])[0]


@router.put("/api/corrections/{correction_id}")
def update_correction(
    correction_id: int,
    request: Dict[str, Any],
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_ui_principal),
) -> Dict[str, Any]:
    """Apply a new human revision from the reviews page."""
    c = db.query(ReviewCorrection).filter(ReviewCorrection.id == correction_id).first()
    if not c:
        raise HTTPException(status_code=404, detail="Correction not found")
    _require_active_candidate(c)

    run = db.query(Run).filter(Run.id == c.run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    item = (
        db.query(RunItem)
        .filter(RunItem.run_id == c.run_id, RunItem.item_id == c.item_id)
        .first()
    )
    if not item:
        raise HTTPException(status_code=404, detail="Run item not found")

    patch: Dict[str, Any] = {}
    for request_key, state_key in [
        ("human_root_cause", "root_cause"),
        ("human_root_cause_detail", "root_cause_detail"),
        ("human_root_cause_note", "root_cause_note"),
        ("human_solution", "solution"),
        ("human_solution_note", "solution_note"),
    ]:
        if request_key in request:
            patch[state_key] = request.get(request_key)

    result = apply_root_cause_change(
        db,
        run=run,
        item=item,
        actor_user_id=principal.user.id if principal.auth_type != "none" else None,
        actor_source="human",
        human_patch=patch,
    )
    db.commit()
    target = result.candidate or (
        db.query(ReviewCorrection)
        .filter(
            ReviewCorrection.run_id == c.run_id,
            ReviewCorrection.item_id == c.item_id,
            ReviewCorrection.is_active.is_(True),
        )
        .first()
    ) or c
    return _serialize_corrections_with_history(db, [target])[0]


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
    _approve_candidate(
        db,
        correction=c,
        reviewer_id=principal.user.id if principal.auth_type != "none" else None,
        comment=(request.get("comment") or "").strip(),
        reviewed_at=datetime.utcnow(),
    )

    db.commit()
    return _serialize_corrections_with_history(db, [c])[0]


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
    _require_active_candidate(c)

    c.status = CorrectionStatus.REJECTED
    c.reviewed_by_user_id = principal.user.id if principal.auth_type != "none" else None
    c.reviewed_at = datetime.utcnow()
    c.review_comment = (request.get("comment") or "").strip()

    db.commit()
    return _serialize_corrections_with_history(db, [c])[0]


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
    _require_active_candidate(c)

    c.status = CorrectionStatus.PENDING
    c.reviewed_by_user_id = None
    c.reviewed_at = None
    c.review_comment = ""

    db.commit()
    return _serialize_corrections_with_history(db, [c])[0]


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
        .filter(
            ReviewCorrection.id.in_(request.ids),
            ReviewCorrection.is_active.is_(True),
        )
        .all()
    )

    if not corrections:
        raise HTTPException(status_code=404, detail="No corrections found")

    now = datetime.utcnow()
    reviewer_id = principal.user.id if principal.auth_type != "none" else None
    affected = 0

    for c in corrections:
        if request.action == "approve":
            _approve_candidate(
                db,
                correction=c,
                reviewer_id=reviewer_id,
                comment=request.comment,
                reviewed_at=now,
            )
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
            _delete_active_candidate(db, c)
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
    _delete_active_candidate(db, c)
    db.commit()
    return {"ok": True, "deleted_id": correction_id}
