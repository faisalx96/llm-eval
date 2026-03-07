from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from qym_platform.db.models import (
    AuditLog,
    CorrectionStatus,
    ReviewCorrection,
    RootCauseRevision,
    Run,
    RunItem,
    RunItemScore,
)


MANAGED_ANALYSIS_KEYS = {
    "root_cause",
    "root_cause_detail",
    "root_cause_note",
    "root_cause_source",
    "root_cause_confidence",
    "solution",
    "solution_note",
    "solution_source",
}


@dataclass
class RootCauseChangeResult:
    changed: bool
    revision: Optional[RootCauseRevision]
    candidate: Optional[ReviewCorrection]
    before_state: dict[str, Any]
    after_state: dict[str, Any]


def extract_analysis_state(meta: dict[str, Any] | None) -> dict[str, Any]:
    md = meta if isinstance(meta, dict) else {}
    state = {
        "root_cause": str(md.get("root_cause", "") or "").strip(),
        "root_cause_detail": str(md.get("root_cause_detail", "") or "").strip(),
        "root_cause_note": str(md.get("root_cause_note", "") or "").strip(),
        "root_cause_source": str(md.get("root_cause_source", "") or "").strip(),
        "root_cause_confidence": md.get("root_cause_confidence"),
        "solution": str(md.get("solution", "") or "").strip(),
        "solution_note": str(md.get("solution_note", "") or "").strip(),
        "solution_source": str(md.get("solution_source", "") or "").strip(),
    }
    return normalize_analysis_state(state)


def normalize_analysis_state(state: dict[str, Any] | None) -> dict[str, Any]:
    src = state or {}
    normalized = {
        "root_cause": str(src.get("root_cause", "") or "").strip(),
        "root_cause_detail": str(src.get("root_cause_detail", "") or "").strip(),
        "root_cause_note": str(src.get("root_cause_note", "") or "").strip(),
        "root_cause_source": str(src.get("root_cause_source", "") or "").strip(),
        "root_cause_confidence": src.get("root_cause_confidence"),
        "solution": str(src.get("solution", "") or "").strip(),
        "solution_note": str(src.get("solution_note", "") or "").strip(),
        "solution_source": str(src.get("solution_source", "") or "").strip(),
    }

    if normalized["root_cause"].lower() == "unanalyzed":
        normalized["root_cause"] = ""
        normalized["root_cause_detail"] = ""
        normalized["root_cause_note"] = ""
        normalized["root_cause_source"] = ""
        normalized["root_cause_confidence"] = None

    if not normalized["root_cause"]:
        normalized["root_cause"] = ""
        normalized["root_cause_detail"] = ""
        normalized["root_cause_note"] = ""
        normalized["root_cause_source"] = ""
        normalized["root_cause_confidence"] = None

    if not normalized["solution"]:
        normalized["solution"] = ""
        normalized["solution_note"] = ""
        normalized["solution_source"] = ""

    if normalized["root_cause_source"] != "ai":
        normalized["root_cause_confidence"] = None
    if normalized["root_cause_source"] not in {"ai", "human", "system"}:
        normalized["root_cause_source"] = ""
    if normalized["solution_source"] not in {"ai", "human", "system"}:
        normalized["solution_source"] = ""

    return normalized


def build_item_metadata(existing_meta: dict[str, Any] | None, state: dict[str, Any]) -> dict[str, Any]:
    meta = dict(existing_meta) if isinstance(existing_meta, dict) else {}
    for key in MANAGED_ANALYSIS_KEYS:
        meta.pop(key, None)

    normalized = normalize_analysis_state(state)
    if normalized["root_cause"]:
        meta["root_cause"] = normalized["root_cause"]
        meta["root_cause_source"] = normalized["root_cause_source"]
        if normalized["root_cause_detail"]:
            meta["root_cause_detail"] = normalized["root_cause_detail"]
        if normalized["root_cause_note"]:
            meta["root_cause_note"] = normalized["root_cause_note"]
        if normalized["root_cause_confidence"] is not None:
            meta["root_cause_confidence"] = normalized["root_cause_confidence"]

    if normalized["solution"]:
        meta["solution"] = normalized["solution"]
        meta["solution_source"] = normalized["solution_source"]
        if normalized["solution_note"]:
            meta["solution_note"] = normalized["solution_note"]

    return meta


def apply_human_patch(before_state: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    state = dict(before_state)

    if "root_cause" in patch:
        root_cause = str(patch.get("root_cause") or "").strip()
        if root_cause:
            state["root_cause"] = root_cause
            state["root_cause_source"] = "human"
            state["root_cause_confidence"] = None
        else:
            state["root_cause"] = ""
            state["root_cause_detail"] = ""
            state["root_cause_note"] = ""
            state["root_cause_source"] = ""
            state["root_cause_confidence"] = None

    if "root_cause_detail" in patch:
        state["root_cause_detail"] = str(patch.get("root_cause_detail") or "").strip()
    if "root_cause_note" in patch:
        state["root_cause_note"] = str(patch.get("root_cause_note") or "").strip()
    if "solution" in patch:
        solution = str(patch.get("solution") or "").strip()
        if solution:
            state["solution"] = solution
            state["solution_source"] = "human"
        else:
            state["solution"] = ""
            state["solution_note"] = ""
            state["solution_source"] = ""
    if "solution_note" in patch:
        state["solution_note"] = str(patch.get("solution_note") or "").strip()

    if state.get("root_cause"):
        state["root_cause_source"] = "human"
        state["root_cause_confidence"] = None
    if state.get("solution"):
        state["solution_source"] = "human"

    return normalize_analysis_state(state)


def build_ai_state(
    *,
    root_cause: str,
    root_cause_detail: str = "",
    root_cause_note: str = "",
    confidence: Optional[float] = None,
    solution: str = "",
    solution_note: str = "",
) -> dict[str, Any]:
    return normalize_analysis_state(
        {
            "root_cause": root_cause,
            "root_cause_detail": root_cause_detail,
            "root_cause_note": root_cause_note,
            "root_cause_source": "ai" if (root_cause or "").strip().lower() != "unanalyzed" else "",
            "root_cause_confidence": confidence,
            "solution": solution,
            "solution_note": solution_note,
            "solution_source": "ai" if (solution or "").strip() else "",
        }
    )


def _next_revision_number(db: Session, run_id: str, item_id: str) -> int:
    max_revision = (
        db.query(func.max(RootCauseRevision.revision_number))
        .filter(RootCauseRevision.run_id == run_id, RootCauseRevision.item_id == item_id)
        .scalar()
    )
    return int(max_revision or 0) + 1


def _snapshot_scores(db: Session, run_id: str, item_id: str) -> dict[str, Any]:
    scores = (
        db.query(RunItemScore)
        .filter(RunItemScore.run_id == run_id, RunItemScore.item_id == item_id)
        .all()
    )
    snap: dict[str, Any] = {}
    for score in scores:
        snap[score.metric_name] = score.score_numeric if score.score_numeric is not None else score.score_raw
    return snap


def _build_candidate_snapshot(
    *,
    run: Run,
    item: RunItem,
    ai_state: dict[str, Any],
    after_state: dict[str, Any],
    actor_user_id: Optional[str],
    revision_id: int,
    scores_snapshot: dict[str, Any],
    created_at: datetime,
    status: CorrectionStatus = CorrectionStatus.PENDING,
    reviewed_by_user_id: Optional[str] = None,
    reviewed_at: Optional[datetime] = None,
    review_comment: str = "",
) -> ReviewCorrection:
    had_real_ai = ai_state.get("root_cause_source") == "ai" and bool(ai_state.get("root_cause"))
    return ReviewCorrection(
        run_id=run.id,
        item_id=item.item_id,
        task=run.task,
        input_snapshot=item.input,
        expected_snapshot=item.expected,
        output_snapshot=item.output,
        scores_snapshot=scores_snapshot,
        ai_root_cause=ai_state.get("root_cause", "") if had_real_ai else "",
        ai_root_cause_detail=ai_state.get("root_cause_detail", "") if had_real_ai else "",
        ai_root_cause_note=ai_state.get("root_cause_note", "") if had_real_ai else "",
        ai_confidence=ai_state.get("root_cause_confidence") if had_real_ai else None,
        ai_solution=ai_state.get("solution", "") if had_real_ai else "",
        ai_solution_note=ai_state.get("solution_note", "") if had_real_ai else "",
        human_root_cause=after_state.get("root_cause", ""),
        human_root_cause_detail=after_state.get("root_cause_detail", ""),
        human_root_cause_note=after_state.get("root_cause_note", ""),
        human_solution=after_state.get("solution", ""),
        human_solution_note=after_state.get("solution_note", ""),
        corrected_by_user_id=actor_user_id,
        revision_id=revision_id,
        is_active=True,
        status=status,
        reviewed_by_user_id=reviewed_by_user_id,
        reviewed_at=reviewed_at,
        review_comment=review_comment,
        created_at=created_at,
    )


def _build_ai_review_candidate(
    *,
    run: Run,
    item: RunItem,
    ai_state: dict[str, Any],
    actor_user_id: Optional[str],
    revision_id: int,
    scores_snapshot: dict[str, Any],
    created_at: datetime,
) -> ReviewCorrection:
    normalized_ai = normalize_analysis_state(ai_state)
    return ReviewCorrection(
        run_id=run.id,
        item_id=item.item_id,
        task=run.task,
        input_snapshot=item.input,
        expected_snapshot=item.expected,
        output_snapshot=item.output,
        scores_snapshot=scores_snapshot,
        ai_root_cause=normalized_ai.get("root_cause", ""),
        ai_root_cause_detail=normalized_ai.get("root_cause_detail", ""),
        ai_root_cause_note=normalized_ai.get("root_cause_note", ""),
        ai_confidence=normalized_ai.get("root_cause_confidence"),
        ai_solution=normalized_ai.get("solution", ""),
        ai_solution_note=normalized_ai.get("solution_note", ""),
        human_root_cause="",
        human_root_cause_detail="",
        human_root_cause_note="",
        human_solution="",
        human_solution_note="",
        corrected_by_user_id=actor_user_id,
        revision_id=revision_id,
        is_active=True,
        status=CorrectionStatus.PENDING,
        created_at=created_at,
    )


def _candidate_ai_state(candidate: ReviewCorrection) -> dict[str, Any]:
    ai_root_cause = str(candidate.ai_root_cause or "").strip()
    return normalize_analysis_state(
        {
            "root_cause": ai_root_cause,
            "root_cause_detail": candidate.ai_root_cause_detail or "",
            "root_cause_note": candidate.ai_root_cause_note or "",
            "root_cause_source": "ai" if ai_root_cause else "",
            "root_cause_confidence": candidate.ai_confidence,
            "solution": candidate.ai_solution or "",
            "solution_note": candidate.ai_solution_note or "",
            "solution_source": "ai" if str(candidate.ai_solution or "").strip() else "",
        }
    )


def _resolve_ai_baseline(
    db: Session,
    *,
    run_id: str,
    item_id: str,
    before_state: dict[str, Any],
    active_candidates: list[ReviewCorrection],
) -> dict[str, Any]:
    candidate_with_ai = next(
        (
            candidate
            for candidate in active_candidates
            if str(candidate.ai_root_cause or "").strip()
        ),
        None,
    )
    if candidate_with_ai is not None:
        return _candidate_ai_state(candidate_with_ai)
    historical_candidate_with_ai = (
        db.query(ReviewCorrection)
        .filter(
            ReviewCorrection.run_id == run_id,
            ReviewCorrection.item_id == item_id,
            ReviewCorrection.ai_root_cause.is_not(None),
            ReviewCorrection.ai_root_cause != "",
        )
        .order_by(ReviewCorrection.created_at.desc(), ReviewCorrection.id.desc())
        .first()
    )
    if historical_candidate_with_ai is not None:
        return _candidate_ai_state(historical_candidate_with_ai)
    if before_state.get("root_cause_source") == "ai" and before_state.get("root_cause"):
        return normalize_analysis_state(before_state)
    return normalize_analysis_state({})


def _deactivate_active_candidates(
    db: Session,
    *,
    run_id: str,
    item_id: str,
    deactivation_status: Optional[CorrectionStatus],
) -> None:
    active_candidates = (
        db.query(ReviewCorrection)
        .filter(
            ReviewCorrection.run_id == run_id,
            ReviewCorrection.item_id == item_id,
            ReviewCorrection.is_active.is_(True),
        )
        .all()
    )
    for candidate in active_candidates:
        candidate.is_active = False
        if candidate.status in {
            CorrectionStatus.PENDING,
            CorrectionStatus.REJECTED,
            CorrectionStatus.WITHDRAWN,
            CorrectionStatus.SUPERSEDED,
        } and deactivation_status is not None:
            candidate.status = deactivation_status


def _find_active_candidates(db: Session, *, run_id: str, item_id: str) -> list[ReviewCorrection]:
    return (
        db.query(ReviewCorrection)
        .filter(
            ReviewCorrection.run_id == run_id,
            ReviewCorrection.item_id == item_id,
            ReviewCorrection.is_active.is_(True),
        )
        .all()
    )


def apply_root_cause_change(
    db: Session,
    *,
    run: Run,
    item: RunItem,
    actor_user_id: Optional[str],
    actor_source: str,
    human_patch: dict[str, Any] | None = None,
    next_state: dict[str, Any] | None = None,
    revision_created_at: Optional[datetime] = None,
    backfilled_from_legacy: bool = False,
) -> RootCauseChangeResult:
    if actor_source not in {"human", "ai", "system"}:
        raise ValueError(f"Unsupported actor_source: {actor_source}")
    if (human_patch is None) == (next_state is None):
        raise ValueError("Provide exactly one of human_patch or next_state")

    before_state = extract_analysis_state(item.item_metadata if isinstance(item.item_metadata, dict) else {})
    after_state = (
        apply_human_patch(before_state, human_patch or {})
        if human_patch is not None
        else normalize_analysis_state(next_state)
    )

    if before_state == after_state:
        return RootCauseChangeResult(
            changed=False,
            revision=None,
            candidate=None,
            before_state=before_state,
            after_state=after_state,
        )

    item.item_metadata = build_item_metadata(item.item_metadata if isinstance(item.item_metadata, dict) else {}, after_state)

    created_at = revision_created_at or datetime.utcnow()
    revision = RootCauseRevision(
        run_id=run.id,
        item_id=item.item_id,
        revision_number=_next_revision_number(db, run.id, item.item_id),
        actor_user_id=actor_user_id,
        actor_source=actor_source,
        before_state=before_state,
        after_state=after_state,
        backfilled_from_legacy=backfilled_from_legacy,
        created_at=created_at,
    )
    db.add(revision)
    db.flush()

    candidate: Optional[ReviewCorrection] = None
    if actor_source == "human":
        active_candidates = _find_active_candidates(db, run_id=run.id, item_id=item.item_id)
        ai_baseline = _resolve_ai_baseline(
            db,
            run_id=run.id,
            item_id=item.item_id,
            before_state=before_state,
            active_candidates=active_candidates,
        )
        active_approved = next((c for c in active_candidates if c.status == CorrectionStatus.APPROVED), None)
        auto_approve_human_only = (
            active_approved is not None
            and ai_baseline.get("root_cause_source") != "ai"
            and not (active_approved.ai_root_cause or "").strip()
            and bool(after_state.get("root_cause"))
        )
        deactivation_status = CorrectionStatus.WITHDRAWN if not after_state.get("root_cause") else CorrectionStatus.SUPERSEDED
        _deactivate_active_candidates(
            db,
            run_id=run.id,
            item_id=item.item_id,
            deactivation_status=deactivation_status,
        )
        if after_state.get("root_cause"):
            candidate = _build_candidate_snapshot(
                run=run,
                item=item,
                ai_state=ai_baseline,
                after_state=after_state,
                actor_user_id=actor_user_id,
                revision_id=revision.id,
                scores_snapshot=_snapshot_scores(db, run.id, item.item_id),
                created_at=created_at,
                status=CorrectionStatus.APPROVED if auto_approve_human_only else CorrectionStatus.PENDING,
                reviewed_by_user_id=active_approved.reviewed_by_user_id if auto_approve_human_only else None,
                reviewed_at=created_at if auto_approve_human_only else None,
                review_comment=active_approved.review_comment if auto_approve_human_only else "",
            )
            db.add(candidate)
            if auto_approve_human_only and active_approved is not None:
                active_approved.status = CorrectionStatus.SUPERSEDED
    else:
        _deactivate_active_candidates(
            db,
            run_id=run.id,
            item_id=item.item_id,
            deactivation_status=CorrectionStatus.SUPERSEDED,
        )
        if after_state.get("root_cause"):
            candidate = _build_ai_review_candidate(
                run=run,
                item=item,
                ai_state=after_state,
                actor_user_id=actor_user_id,
                revision_id=revision.id,
                scores_snapshot=_snapshot_scores(db, run.id, item.item_id),
                created_at=created_at,
            )
            db.add(candidate)

    db.add(
        AuditLog(
            actor_user_id=actor_user_id,
            action=f"root_cause_change:{actor_source}",
            entity_type="root_cause_revision",
            entity_id=str(revision.id),
            before=before_state,
            after=after_state,
            created_at=created_at,
        )
    )

    return RootCauseChangeResult(
        changed=True,
        revision=revision,
        candidate=candidate,
        before_state=before_state,
        after_state=after_state,
    )
