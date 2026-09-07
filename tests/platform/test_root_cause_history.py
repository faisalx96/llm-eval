from __future__ import annotations

import asyncio
import json
import math
import os
import sys
from datetime import datetime
from io import BytesIO
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException, UploadFile
from sqlalchemy import Text, create_engine
from sqlalchemy.orm import Session, sessionmaker

os.environ.setdefault("QYM_DATABASE_URL", "sqlite:///:memory:")
if "openai" not in sys.modules:
    sys.modules["openai"] = MagicMock()

from qym_platform.api.analysis import (
    AnalysisContextUpdate,
    AnalysisRuleMergeRequest,
    AnalysisRuleVersionCreate,
    AnalysisRuleVersionPublish,
    AnalyzeRequest,
    AnalyzerRuleConfig,
    PlaygroundConfig,
    ReferenceDocument,
    RuleInferenceRequest,
    _analysis_config_with_project_context,
    _aggregate_run_analysis_results,
    _approve_candidate,
    _collect_task_root_cause_catalog,
    _create_analysis_rule_version,
    _delete_active_candidate,
    _filter_analysis_targets,
    _load_metric_specs,
    _list_analysis_examples,
    _persist_aggregated_bindings,
    _persisted_ai_analysis_bindings,
    _playground_config_to_analyzer,
    _resolve_analysis_rule_version,
    _reject_candidate,
    _save_analysis_results,
    _validate_requested_metric,
    activate_project_analysis_rule_version,
    approve_correction,
    approve_metric_analysis,
    compare_project_analysis_rule_versions,
    create_project_analysis_rule_version,
    delete_project_analysis_rule_version,
    infer_project_analysis_rules,
    list_project_analysis_rule_versions,
    merge_project_analysis_rule_versions,
    permanently_delete_project_analysis_rule_version,
    publish_project_analysis_rule_version,
    update_analysis_context,
    upload_analysis_document,
)
from qym_platform.api import analysis as analysis_api
from qym_platform.api.runs import _build_run_data
from qym_platform.auth import Principal
from qym_platform.db.base import Base
from qym_platform.db.models import (
    AnalyzerDocument,
    CorrectionStatus,
    Project,
    ProjectAnalysisRuleAlias,
    ProjectAnalysisRuleMergeParent,
    ProjectAnalysisRuleVersion,
    ProjectMembership,
    ProjectRole,
    ReviewCorrection,
    RootCauseRevision,
    Run,
    RunItem,
    RunItemScore,
    RunMetricSpec,
    RunWorkflowStatus,
    Span,
    User,
    UserRole,
)
from qym_platform.services.analysis_aggregation import (
    AggregationResponse,
    AnalysisAggregationError,
)
from qym_platform.services import llm_analyzer as llm_analyzer_service
from qym_platform.services.llm_analyzer import (
    MAX_ANALYSIS_FALLBACK_PROMPT_CHARS,
    MAX_ANALYSIS_PROMPT_CHARS,
    MAX_TRACE_CHARS,
    ROOT_CAUSE_CATEGORIES,
    RULE_WRITER_SYSTEM_PROMPT,
    AnalysisRule,
    AnalysisResult,
    analyze_single_item,
    build_analysis_prompt,
    get_all_approved_examples,
    get_few_shot_examples,
    normalize_analysis_rules,
    parse_llm_response,
    prompt_character_count,
)
from qym_platform.services.document_extractor import (
    MAX_REFERENCE_DOCUMENT_CHARS,
    MAX_REFERENCE_DOCUMENT_CONTENT_CHARS,
)
from qym_platform.services.root_cause_changes import (
    apply_root_cause_change,
    build_ai_state,
    replace_metric_review_candidate,
)


@pytest.fixture
def db_session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def _seed_run(session: Session) -> tuple[User, User, Run, RunItem]:
    actor = User(id="user-1", email="user1@example.com")
    reviewer = User(id="user-2", email="user2@example.com")
    project = Project(
        id="project-1",
        name="Project One",
        slug="project-one",
        created_by_user_id=actor.id,
        is_active=True,
    )
    run = Run(
        id="run-1",
        project_id=project.id,
        created_by_user_id=actor.id,
        owner_user_id=actor.id,
        task="insightor_api",
        dataset="dataset-1",
        metrics=["accuracy"],
        status=RunWorkflowStatus.COMPLETED,
    )
    item = RunItem(
        run_id=run.id,
        item_id="item-1",
        index=0,
        input={"question": "q"},
        expected={"answer": "expected"},
        output={"answer": "actual"},
        item_metadata={},
    )
    score = RunItemScore(
        run_id=run.id,
        item_id=item.item_id,
        metric_name="accuracy",
        score_numeric=0.1,
        meta={"reason": "wrong answer"},
    )
    memberships = [
        ProjectMembership(
            project_id=project.id,
            user_id=actor.id,
            role=ProjectRole.MEMBER,
            added_by_user_id=actor.id,
        ),
        ProjectMembership(
            project_id=project.id,
            user_id=reviewer.id,
            role=ProjectRole.MANAGER,
            added_by_user_id=actor.id,
        ),
    ]
    session.add_all([actor, reviewer, project, run, item, score, *memberships])
    session.commit()
    return actor, reviewer, run, item


def _latest_active_candidate(
    session: Session, run_id: str, item_id: str
) -> ReviewCorrection | None:
    return (
        session.query(ReviewCorrection)
        .filter(
            ReviewCorrection.run_id == run_id,
            ReviewCorrection.item_id == item_id,
            ReviewCorrection.is_active.is_(True),
        )
        .first()
    )


def test_review_correction_details_store_long_analyzer_text(
    db_session: Session,
) -> None:
    assert isinstance(ReviewCorrection.__table__.c.ai_root_cause_detail.type, Text)
    assert isinstance(ReviewCorrection.__table__.c.human_root_cause_detail.type, Text)

    actor, _, run, item = _seed_run(db_session)
    long_detail = (
        "The natural-language request and expected SQL disagree about aggregation, "
        "because the expected query selects a non-grouped institution name alongside "
        "SUM(total_transactions), while the request asks for every institution and the "
        "schema already defines total_transactions as an institution-level value."
    )
    assert len(long_detail) > 200

    change = apply_root_cause_change(
        db_session,
        run=run,
        item=item,
        actor_user_id=actor.id,
        actor_source="ai",
        next_state=build_ai_state(
            root_cause="Dataset Issue",
            root_cause_detail=long_detail,
            root_cause_note="The reference answer is inconsistent with the request.",
            confidence=0.95,
        ),
    )
    db_session.commit()

    assert change.candidate is not None
    db_session.refresh(change.candidate)
    assert change.candidate.ai_root_cause_detail == long_detail
    assert item.item_metadata["root_cause_detail"] == long_detail


def test_assign_then_clear_withdraws_active_candidate(db_session: Session) -> None:
    actor, _, run, item = _seed_run(db_session)

    apply_root_cause_change(
        db_session,
        run=run,
        item=item,
        actor_user_id=actor.id,
        actor_source="ai",
        next_state=build_ai_state(
            root_cause="Wrong Format",
            root_cause_detail="Refusal message returned instead of SQL query",
            root_cause_note="Model refused instead of producing SQL.",
            confidence=0.96,
        ),
    )
    apply_root_cause_change(
        db_session,
        run=run,
        item=item,
        actor_user_id=actor.id,
        actor_source="human",
        human_patch={
            "root_cause": "Wrong Format",
            "root_cause_detail": "Refusal message returned instead of SQL query",
            "root_cause_note": "Confirmed by reviewer.",
        },
    )
    db_session.commit()

    active = _latest_active_candidate(db_session, run.id, item.item_id)
    assert active is not None
    assert active.status == CorrectionStatus.PENDING

    apply_root_cause_change(
        db_session,
        run=run,
        item=item,
        actor_user_id=actor.id,
        actor_source="human",
        human_patch={"root_cause": ""},
    )
    db_session.commit()
    db_session.refresh(item)

    assert item.item_metadata.get("root_cause") is None
    assert _latest_active_candidate(db_session, run.id, item.item_id) is None

    # The AI change snapshots its own review candidate (superseded by the
    # human confirmation); the human candidate is withdrawn by the clear.
    historical = (
        db_session.query(ReviewCorrection)
        .filter(ReviewCorrection.run_id == run.id)
        .all()
    )
    assert len(historical) == 2
    assert {c.status for c in historical} == {
        CorrectionStatus.SUPERSEDED,
        CorrectionStatus.WITHDRAWN,
    }
    assert all(c.is_active is False for c in historical)

    revisions = (
        db_session.query(RootCauseRevision)
        .filter(
            RootCauseRevision.run_id == run.id,
            RootCauseRevision.item_id == item.item_id,
        )
        .order_by(RootCauseRevision.revision_number.asc())
        .all()
    )
    assert [revision.actor_source for revision in revisions] == ["ai", "human", "human"]
    assert revisions[-1].after_state.get("root_cause", "") == ""


def test_latest_approved_revision_supersedes_previous_example(
    db_session: Session,
) -> None:
    actor, reviewer, run, item = _seed_run(db_session)

    apply_root_cause_change(
        db_session,
        run=run,
        item=item,
        actor_user_id=actor.id,
        actor_source="ai",
        next_state=build_ai_state(
            root_cause="Wrong Format",
            root_cause_detail="Refusal message",
            root_cause_note="Model refused.",
            confidence=0.91,
        ),
    )
    first_change = apply_root_cause_change(
        db_session,
        run=run,
        item=item,
        actor_user_id=actor.id,
        actor_source="human",
        human_patch={
            "root_cause": "Wrong Format",
            "root_cause_detail": "Returned refusal copy",
            "root_cause_note": "Initial correction",
        },
    )
    db_session.commit()

    first_candidate = first_change.candidate
    assert first_candidate is not None
    _approve_candidate(
        db_session,
        correction=first_candidate,
        reviewer_id=reviewer.id,
        comment="Approved initial example",
        reviewed_at=datetime.utcnow(),
    )
    db_session.commit()

    db_session.refresh(first_candidate)
    assert first_candidate.status == CorrectionStatus.APPROVED
    assert first_candidate.is_active is True
    assert [
        c.id
        for c in get_few_shot_examples(db_session, run.task, run.project_id, limit=10)
    ] == [first_candidate.id]

    second_change = apply_root_cause_change(
        db_session,
        run=run,
        item=item,
        actor_user_id=actor.id,
        actor_source="human",
        human_patch={
            "root_cause_detail": "Returned privacy refusal instead of SQL query",
            "root_cause_note": "Refined correction",
        },
    )
    db_session.commit()

    second_candidate = second_change.candidate
    assert second_candidate is not None
    db_session.refresh(first_candidate)
    assert first_candidate.status == CorrectionStatus.APPROVED
    assert first_candidate.is_active is False
    assert get_few_shot_examples(db_session, run.task, run.project_id, limit=10) == []

    _approve_candidate(
        db_session,
        correction=second_candidate,
        reviewer_id=reviewer.id,
        comment="Approved refined example",
        reviewed_at=datetime.utcnow(),
    )
    db_session.commit()

    db_session.refresh(first_candidate)
    db_session.refresh(second_candidate)
    assert first_candidate.status == CorrectionStatus.SUPERSEDED
    assert first_candidate.is_active is False
    assert second_candidate.status == CorrectionStatus.APPROVED
    assert second_candidate.is_active is True
    assert [
        c.id
        for c in get_few_shot_examples(db_session, run.task, run.project_id, limit=10)
    ] == [second_candidate.id]


def test_few_shot_examples_are_scoped_to_the_run_project(
    db_session: Session,
) -> None:
    actor, _reviewer, run, _item = _seed_run(db_session)
    other_project = Project(
        id="project-2",
        name="Project Two",
        slug="project-two",
        created_by_user_id=actor.id,
        is_active=True,
    )
    other_run = Run(
        id="run-2",
        project_id=other_project.id,
        created_by_user_id=actor.id,
        owner_user_id=actor.id,
        task=run.task,
        dataset="dataset-2",
        metrics=["accuracy"],
        status=RunWorkflowStatus.COMPLETED,
    )
    local = ReviewCorrection(
        run_id=run.id,
        item_id="local-item",
        task=run.task,
        ai_root_cause="Reasoning Error",
        human_root_cause="Reasoning Error",
        status=CorrectionStatus.APPROVED,
        is_active=True,
    )
    foreign = ReviewCorrection(
        run_id=other_run.id,
        item_id="foreign-item",
        task=run.task,
        input_snapshot={"private": "other-project-data"},
        ai_root_cause="Dataset Issue",
        human_root_cause="Dataset Issue",
        status=CorrectionStatus.APPROVED,
        is_active=True,
    )
    db_session.add_all([other_project, other_run, local, foreign])
    db_session.commit()

    examples = get_few_shot_examples(db_session, run.task, run.project_id, limit=10)
    selected = get_few_shot_examples(
        db_session,
        run.task,
        run.project_id,
        limit=10,
        correction_ids=[foreign.id],
    )

    assert [example.id for example in examples] == [local.id]
    assert selected == []


def test_feedback_only_edit_creates_new_pending_revision(db_session: Session) -> None:
    actor, reviewer, run, item = _seed_run(db_session)

    apply_root_cause_change(
        db_session,
        run=run,
        item=item,
        actor_user_id=actor.id,
        actor_source="ai",
        next_state=build_ai_state(
            root_cause="Context Missing",
            root_cause_detail="Missing schema context",
            root_cause_note="Prompt lacked schema info.",
            confidence=0.87,
        ),
    )
    first_change = apply_root_cause_change(
        db_session,
        run=run,
        item=item,
        actor_user_id=actor.id,
        actor_source="human",
        human_patch={
            "root_cause": "Context Missing",
            "root_cause_detail": "Missing schema context",
            "root_cause_note": "Original reviewer note",
        },
    )
    db_session.commit()

    _approve_candidate(
        db_session,
        correction=first_change.candidate,
        reviewer_id=reviewer.id,
        comment="Approved",
        reviewed_at=datetime.utcnow(),
    )
    db_session.commit()

    note_change = apply_root_cause_change(
        db_session,
        run=run,
        item=item,
        actor_user_id=actor.id,
        actor_source="human",
        human_patch={"root_cause_note": "Updated note after deeper inspection"},
    )
    db_session.commit()
    db_session.refresh(item)

    new_candidate = note_change.candidate
    assert new_candidate is not None
    assert new_candidate.status == CorrectionStatus.PENDING
    assert new_candidate.is_active is True
    assert item.item_metadata["root_cause"] == "Context Missing"
    assert (
        item.item_metadata["root_cause_note"] == "Updated note after deeper inspection"
    )

    revisions = (
        db_session.query(RootCauseRevision)
        .filter(
            RootCauseRevision.run_id == run.id,
            RootCauseRevision.item_id == item.item_id,
        )
        .order_by(RootCauseRevision.revision_number.asc())
        .all()
    )
    assert len(revisions) == 3
    assert revisions[-1].before_state["root_cause_note"] == "Original reviewer note"
    assert (
        revisions[-1].after_state["root_cause_note"]
        == "Updated note after deeper inspection"
    )


def test_delete_request_rejects_and_removes_active_candidate(
    db_session: Session,
) -> None:
    actor, reviewer, run, item = _seed_run(db_session)

    apply_root_cause_change(
        db_session,
        run=run,
        item=item,
        actor_user_id=actor.id,
        actor_source="ai",
        next_state=build_ai_state(
            root_cause="Wrong Format",
            root_cause_detail="Refusal response",
            root_cause_note="AI guess",
            confidence=0.82,
        ),
    )
    change = apply_root_cause_change(
        db_session,
        run=run,
        item=item,
        actor_user_id=actor.id,
        actor_source="human",
        human_patch={
            "root_cause": "Context Missing",
            "root_cause_detail": "Missing schema context",
            "root_cause_note": "Human correction",
        },
    )
    db_session.commit()

    candidate = change.candidate
    assert candidate is not None
    _approve_candidate(
        db_session,
        correction=candidate,
        reviewer_id=reviewer.id,
        comment="Approved correction",
        reviewed_at=datetime.utcnow(),
    )
    db_session.commit()

    rejected_at = datetime.utcnow()
    _delete_active_candidate(
        db_session,
        correction=candidate,
        reviewer_id=reviewer.id,
        comment="Rejected automatically after deletion request.",
        reviewed_at=rejected_at,
    )
    db_session.commit()
    db_session.refresh(item)
    db_session.refresh(candidate)

    assert item.item_metadata.get("root_cause") is None
    assert item.item_metadata.get("root_cause_detail") is None
    assert item.item_metadata.get("root_cause_note") is None
    assert item.item_metadata.get("root_cause_source") is None
    assert _latest_active_candidate(db_session, run.id, item.item_id) is None
    assert candidate.status == CorrectionStatus.REJECTED
    assert candidate.is_active is False
    assert candidate.reviewed_by_user_id == reviewer.id
    assert candidate.review_comment == "Rejected automatically after deletion request."
    # Both the rejected candidate and superseded AI snapshot remain available
    # for audit history.
    remaining = (
        db_session.query(ReviewCorrection)
        .filter(ReviewCorrection.run_id == run.id)
        .all()
    )
    assert len(remaining) == 2
    assert {row.status for row in remaining} == {
        CorrectionStatus.REJECTED,
        CorrectionStatus.SUPERSEDED,
    }

    revisions = (
        db_session.query(RootCauseRevision)
        .filter(
            RootCauseRevision.run_id == run.id,
            RootCauseRevision.item_id == item.item_id,
        )
        .order_by(RootCauseRevision.revision_number.asc())
        .all()
    )
    assert len(revisions) == 3
    assert revisions[-1].actor_source == "system"
    assert revisions[-1].after_state.get("root_cause") == ""


def test_deleting_metric_reviews_retargets_then_clears_legacy_summary(
    db_session: Session,
) -> None:
    actor, reviewer, run, item = _seed_run(db_session)
    run.metrics = ["accuracy", "format"]
    results = [
        AnalysisResult(
            item_id=item.item_id,
            metric_name="accuracy",
            root_cause="Reasoning Error",
            root_cause_detail="Wrong join key",
            root_cause_note="Accuracy diagnosis",
            confidence=0.9,
            solution="Add Output Validation",
        ),
        AnalysisResult(
            item_id=item.item_id,
            metric_name="format",
            root_cause="Wrong Format",
            root_cause_detail="Invalid response envelope",
            root_cause_note="Format diagnosis",
            confidence=0.8,
            solution="Refine Prompt Instructions",
        ),
    ]
    _save_analysis_results(
        db_session,
        run,
        [(item, "accuracy"), (item, "format")],
        results,
        Principal(user=actor, auth_type="none"),
    )
    candidates = (
        db_session.query(ReviewCorrection)
        .filter(
            ReviewCorrection.run_id == run.id,
            ReviewCorrection.item_id == item.item_id,
            ReviewCorrection.is_active.is_(True),
        )
        .order_by(ReviewCorrection.metric_name.asc())
        .all()
    )

    _delete_active_candidate(
        db_session,
        correction=candidates[0],
        reviewer_id=reviewer.id,
        comment="Delete accuracy review.",
        reviewed_at=datetime.utcnow(),
    )
    db_session.commit()
    db_session.refresh(item)

    assert set(item.item_metadata["metric_analyses"]) == {"format"}
    assert item.item_metadata["root_cause_metric_name"] == "format"
    assert item.item_metadata["root_cause"] == "Wrong Format"
    assert item.item_metadata["root_cause_detail"] == "Invalid response envelope"
    assert item.item_metadata["root_cause_note"] == "Format diagnosis"

    _delete_active_candidate(
        db_session,
        correction=candidates[1],
        reviewer_id=reviewer.id,
        comment="Delete format review.",
        reviewed_at=datetime.utcnow(),
    )
    db_session.commit()
    db_session.refresh(item)

    assert "metric_analyses" not in item.item_metadata
    assert "root_cause_metric_name" not in item.item_metadata
    assert "root_cause" not in item.item_metadata
    assert "root_cause_detail" not in item.item_metadata
    assert "root_cause_note" not in item.item_metadata
    assert "solution" not in item.item_metadata


def test_deleting_metric_review_preserves_independent_human_item_summary(
    db_session: Session,
) -> None:
    actor, reviewer, run, item = _seed_run(db_session)
    item.item_metadata = {
        "root_cause": "Context Missing",
        "root_cause_detail": "Missing schema context",
        "root_cause_note": "Human-authored item diagnosis",
        "root_cause_source": "human",
        "metric_analyses": {
            "accuracy": {
                "source": "ai",
                "root_cause": "Reasoning Error",
                "root_cause_detail": "Wrong join key",
            }
        },
    }
    candidate = ReviewCorrection(
        run_id=run.id,
        item_id=item.item_id,
        metric_name="accuracy",
        task=run.task,
        ai_root_cause="Reasoning Error",
        ai_root_cause_detail="Wrong join key",
        human_root_cause="",
        corrected_by_user_id=actor.id,
        is_active=True,
        status=CorrectionStatus.PENDING,
    )
    db_session.add(candidate)
    db_session.commit()

    _delete_active_candidate(
        db_session,
        correction=candidate,
        reviewer_id=reviewer.id,
        comment="Delete metric review.",
        reviewed_at=datetime.utcnow(),
    )
    db_session.commit()
    db_session.refresh(item)

    assert "metric_analyses" not in item.item_metadata
    assert item.item_metadata["root_cause"] == "Context Missing"
    assert item.item_metadata["root_cause_detail"] == "Missing schema context"
    assert item.item_metadata["root_cause_note"] == "Human-authored item diagnosis"
    assert item.item_metadata["root_cause_source"] == "human"


def test_editing_approved_human_only_candidate_stays_approved_and_does_not_fake_ai(
    db_session: Session,
) -> None:
    actor, reviewer, run, item = _seed_run(db_session)

    first_change = apply_root_cause_change(
        db_session,
        run=run,
        item=item,
        actor_user_id=actor.id,
        actor_source="human",
        human_patch={
            "root_cause": "Context Missing",
            "root_cause_detail": "Missing schema",
            "root_cause_note": "Initial human-only label",
        },
    )
    db_session.commit()

    first_candidate = first_change.candidate
    assert first_candidate is not None
    _approve_candidate(
        db_session,
        correction=first_candidate,
        reviewer_id=reviewer.id,
        comment="Approved human-only example",
        reviewed_at=datetime.utcnow(),
    )
    db_session.commit()

    second_change = apply_root_cause_change(
        db_session,
        run=run,
        item=item,
        actor_user_id=actor.id,
        actor_source="human",
        human_patch={
            "root_cause_detail": "Missing schema and business rules",
            "root_cause_note": "Edited human-only label",
        },
    )
    db_session.commit()

    second_candidate = second_change.candidate
    assert second_candidate is not None
    db_session.refresh(first_candidate)
    db_session.refresh(second_candidate)

    assert first_candidate.status == CorrectionStatus.SUPERSEDED
    assert first_candidate.is_active is False
    assert second_candidate.status == CorrectionStatus.APPROVED
    assert second_candidate.is_active is True
    assert second_candidate.ai_root_cause == ""
    assert second_candidate.ai_root_cause_detail == ""
    assert second_candidate.ai_root_cause_note == ""
    assert second_candidate.human_root_cause == "Context Missing"
    assert (
        second_candidate.human_root_cause_detail == "Missing schema and business rules"
    )

    approved = get_few_shot_examples(db_session, run.task, run.project_id, limit=10)
    assert [c.id for c in approved] == [second_candidate.id]


def test_follow_up_human_edit_preserves_original_ai_snapshot(
    db_session: Session,
) -> None:
    actor, _reviewer, run, item = _seed_run(db_session)

    ai_change = apply_root_cause_change(
        db_session,
        run=run,
        item=item,
        actor_user_id=None,
        actor_source="ai",
        next_state=build_ai_state(
            root_cause="Reasoning Error",
            root_cause_detail="Wrong join",
            root_cause_note="AI baseline note",
            confidence=0.91,
            solution="Query Fix",
            solution_note="AI solution note",
        ),
    )
    db_session.commit()
    # AI changes now enter the review queue as pending candidates
    assert ai_change.candidate is not None
    assert ai_change.candidate.status == CorrectionStatus.PENDING

    first_human_change = apply_root_cause_change(
        db_session,
        run=run,
        item=item,
        actor_user_id=actor.id,
        actor_source="human",
        human_patch={
            "root_cause": "Question Understanding",
        },
    )
    db_session.commit()

    first_candidate = first_human_change.candidate
    assert first_candidate is not None
    assert first_candidate.ai_root_cause == "Reasoning Error"
    assert first_candidate.ai_root_cause_detail == "Wrong join"
    assert first_candidate.ai_root_cause_note == "AI baseline note"
    assert first_candidate.human_root_cause == "Question Understanding"

    second_human_change = apply_root_cause_change(
        db_session,
        run=run,
        item=item,
        actor_user_id=actor.id,
        actor_source="human",
        human_patch={
            "root_cause_detail": "Wrong filter values",
            "root_cause_note": "Human follow-up note",
        },
    )
    db_session.commit()

    second_candidate = second_human_change.candidate
    assert second_candidate is not None
    db_session.refresh(first_candidate)
    db_session.refresh(second_candidate)

    assert first_candidate.status == CorrectionStatus.SUPERSEDED
    assert first_candidate.is_active is False
    assert second_candidate.is_active is True
    assert second_candidate.ai_root_cause == "Reasoning Error"
    assert second_candidate.ai_root_cause_detail == "Wrong join"
    assert second_candidate.ai_root_cause_note == "AI baseline note"
    assert second_candidate.ai_confidence == 0.91
    assert second_candidate.ai_solution == "Query Fix"
    assert second_candidate.ai_solution_note == "AI solution note"
    assert second_candidate.human_root_cause == "Question Understanding"
    assert second_candidate.human_root_cause_detail == "Wrong filter values"
    assert second_candidate.human_root_cause_note == "Human follow-up note"


def test_follow_up_human_edit_recovers_ai_snapshot_from_history_if_active_candidate_lost_it(
    db_session: Session,
) -> None:
    actor, _reviewer, run, item = _seed_run(db_session)

    apply_root_cause_change(
        db_session,
        run=run,
        item=item,
        actor_user_id=None,
        actor_source="ai",
        next_state=build_ai_state(
            root_cause="Reasoning Error",
            root_cause_detail="Wrong join",
            root_cause_note="AI baseline note",
            confidence=0.91,
        ),
    )
    db_session.commit()

    first_human_change = apply_root_cause_change(
        db_session,
        run=run,
        item=item,
        actor_user_id=actor.id,
        actor_source="human",
        human_patch={"root_cause": "Question Understanding"},
    )
    db_session.commit()

    first_candidate = first_human_change.candidate
    assert first_candidate is not None
    assert first_candidate.ai_root_cause == "Reasoning Error"

    # Simulate a bad historical row where the active candidate lost its AI snapshot.
    first_candidate.ai_root_cause = ""
    first_candidate.ai_root_cause_detail = ""
    first_candidate.ai_root_cause_note = ""
    first_candidate.ai_confidence = None
    db_session.commit()

    second_human_change = apply_root_cause_change(
        db_session,
        run=run,
        item=item,
        actor_user_id=actor.id,
        actor_source="human",
        human_patch={"root_cause_detail": "Wrong filter values"},
    )
    db_session.commit()

    second_candidate = second_human_change.candidate
    assert second_candidate is not None
    assert second_candidate.ai_root_cause == "Reasoning Error"
    assert second_candidate.ai_root_cause_detail == "Wrong join"
    assert second_candidate.ai_root_cause_note == "AI baseline note"
    assert second_candidate.ai_confidence == 0.91


def test_ai_analysis_creates_pending_ai_only_candidate_and_approval_copies_ai_to_human(
    db_session: Session,
) -> None:
    actor, reviewer, run, item = _seed_run(db_session)

    change = apply_root_cause_change(
        db_session,
        run=run,
        item=item,
        actor_user_id=actor.id,
        actor_source="ai",
        next_state=build_ai_state(
            root_cause="Reasoning Error",
            root_cause_detail="Wrong join",
            root_cause_note="AI baseline note",
            confidence=0.87,
            solution="Query Fix",
            solution_note="Add the missing predicate",
        ),
    )
    db_session.commit()

    candidate = change.candidate
    assert candidate is not None
    assert candidate.status == CorrectionStatus.PENDING
    assert candidate.is_active is True
    assert candidate.ai_root_cause == "Reasoning Error"
    assert candidate.ai_root_cause_detail == "Wrong join"
    assert candidate.human_root_cause == ""
    assert candidate.human_root_cause_detail == ""

    _approve_candidate(
        db_session,
        correction=candidate,
        reviewer_id=reviewer.id,
        comment="AI suggestion is correct",
        reviewed_at=datetime.utcnow(),
    )
    db_session.commit()
    db_session.refresh(candidate)

    assert candidate.status == CorrectionStatus.APPROVED
    assert candidate.human_root_cause == "Reasoning Error"
    assert candidate.human_root_cause_detail == "Wrong join"
    assert candidate.human_root_cause_note == "AI baseline note"
    assert candidate.human_solution == "Query Fix"
    assert candidate.human_solution_note == "Add the missing predicate"

    approved = get_few_shot_examples(db_session, run.task, run.project_id, limit=10)
    assert [c.id for c in approved] == [candidate.id]


def test_get_few_shot_examples_without_limit_returns_active_examples_within_cap(
    db_session: Session,
) -> None:
    actor, reviewer, run, item = _seed_run(db_session)

    first_change = apply_root_cause_change(
        db_session,
        run=run,
        item=item,
        actor_user_id=actor.id,
        actor_source="human",
        human_patch={
            "root_cause": "Wrong Format",
            "root_cause_detail": "First approved example",
        },
    )
    db_session.commit()
    first_candidate = first_change.candidate
    assert first_candidate is not None
    _approve_candidate(
        db_session,
        correction=first_candidate,
        reviewer_id=reviewer.id,
        comment="Approve first example",
        reviewed_at=datetime.utcnow(),
    )

    second_run = Run(
        id="run-2",
        project_id=run.project_id,
        created_by_user_id=actor.id,
        owner_user_id=actor.id,
        task=run.task,
        dataset="dataset-2",
        metrics=["accuracy"],
        status=RunWorkflowStatus.COMPLETED,
    )
    second_item = RunItem(
        run_id=second_run.id,
        item_id="item-2",
        index=0,
        input={"question": "q2"},
        expected={"answer": "expected-2"},
        output={"answer": "actual-2"},
        item_metadata={},
    )
    second_score = RunItemScore(
        run_id=second_run.id,
        item_id=second_item.item_id,
        metric_name="accuracy",
        score_numeric=0.2,
        meta={"reason": "second wrong answer"},
    )
    db_session.add_all([second_run, second_item, second_score])
    db_session.commit()

    second_change = apply_root_cause_change(
        db_session,
        run=second_run,
        item=second_item,
        actor_user_id=actor.id,
        actor_source="human",
        human_patch={
            "root_cause": "Context Missing",
            "root_cause_detail": "Second approved example",
        },
    )
    db_session.commit()
    second_candidate = second_change.candidate
    assert second_candidate is not None
    _approve_candidate(
        db_session,
        correction=second_candidate,
        reviewer_id=reviewer.id,
        comment="Approve second example",
        reviewed_at=datetime.utcnow(),
    )
    db_session.commit()

    approved = get_few_shot_examples(db_session, run.task, run.project_id, limit=None)
    assert {c.id for c in approved} == {first_candidate.id, second_candidate.id}


def test_build_analysis_prompt_resolves_custom_variable_from_selected_metric_metadata() -> (
    None
):
    item = RunItem(
        run_id="run-1",
        item_id="item-1",
        index=0,
        input={"question": "q"},
        expected={"answer": "expected"},
        output={"answer": "actual"},
        item_metadata={"difficulty": "hard"},
    )
    score = RunItemScore(
        run_id="run-1",
        item_id="item-1",
        metric_name="accuracy",
        score_numeric=0.2,
        meta={"reason": "bad join", "judge": "llm"},
    )

    messages = build_analysis_prompt(
        item,
        {"accuracy": score},
        [],
        config={
            "additional_instructions": "Use signal: {metric_reason}",
            "custom_variable_mapping": {"metric_reason": "metric_metadata.reason"},
        },
        metric_name="accuracy",
    )

    assert any("Use signal: bad join" in message["content"] for message in messages)
    assert any("SELECTED METRIC RESULT:" in message["content"] for message in messages)
    assert any('"accuracy": {' in message["content"] for message in messages)
    assert any('"judge": "llm"' in message["content"] for message in messages)


def test_build_analysis_prompt_organizes_native_trace_payload(
    db_session: Session,
) -> None:
    _, _, _, item = _seed_run(db_session)
    item.trace_id = "trace-1"
    db_session.add_all(
        [
            Span(
                run_id=item.run_id,
                trace_id=item.trace_id,
                span_id="span-1",
                name="ChatCompletion",
                kind="INTERNAL",
                status="ERROR",
                attributes={
                    "openinference.span.kind": "LLM",
                    "input.value": '{"messages":[{"role":"user","content":"q"}]}',
                    "output.value": '{"answer":"actual"}',
                    "llm.input_messages.0.message.role": "system",
                    "llm.input_messages.0.message.content": "You are a SQL agent.",
                    "llm.input_messages.1.message.role": "user",
                    "llm.input_messages.1.message.content": "Use the archived orders table.",
                    "llm.output_messages.0.message.role": "assistant",
                    "llm.output_messages.0.message.content": "The join returned no rows.",
                    "llm.output_messages.0.message.reasoning": "The customer key may be stale.",
                    "llm.output_messages.0.message.tool_calls.0.tool_call.id": "call-123",
                    (
                        "llm.output_messages.0.message.tool_calls.0."
                        "tool_call.function.name"
                    ): "query_sql",
                    (
                        "llm.output_messages.0.message.tool_calls.0."
                        "tool_call.function.arguments"
                    ): '{"sql":"select * from archived_orders"}',
                    "llm.output_messages.1.message.role": "assistant",
                    "llm.output_messages.1.message.content": '{"answer":"actual"}',
                    "gen_ai.completion.0.reasoning": "The customer key may be stale.",
                    "llm.token_count.total": 987,
                    "qym.response.classification": "noisy_reasoning",
                    "authorization": "trace-secret",
                },
                events=[{"name": "exception", "attributes": {"message": "failed"}}],
                links=[],
            ),
            Span(
                run_id=item.run_id,
                trace_id=item.trace_id,
                span_id="span-2",
                parent_span_id="span-1",
                name="tool:query_sql",
                kind="INTERNAL",
                status="ERROR",
                attributes={
                    "openinference.span.kind": "TOOL",
                    "tool.name": "query_sql",
                    "input.value": '{"sql":"select * from archived_orders","authorization":"trace-secret"}',
                    "output.value": '{"error":"table unavailable"}',
                    "qym.tool.error_source": "json",
                },
                events=[
                    {
                        "name": "exception",
                        "time_unix_nano": 123,
                        "attributes": {
                            "exception.type": "DatabaseError",
                            "exception.message": "table unavailable",
                        },
                    },
                ],
                links=[{"trace_id": "linked-trace"}],
            ),
        ]
    )
    db_session.commit()

    messages = build_analysis_prompt(item, {}, [])
    system_content = next(
        message["content"] for message in messages if message["role"] == "system"
    )

    assert "TRACE EVIDENCE:\n" in system_content
    assert "Agent trace:" in system_content
    assert "Evaluation trace:\n(none)" in system_content
    assert "Step 1 — ChatCompletion:" in system_content
    assert "Step 2 — tool:query_sql:" in system_content
    assert "CALL:" in system_content
    assert "THINKING:" in system_content
    assert "OUTPUT:" in system_content
    assert '"authorization": "[REDACTED]"' in system_content
    assert "trace-secret" not in system_content
    assert "ChatCompletion" in system_content
    assert "You are a SQL agent." in system_content
    assert "Use the archived orders table." in system_content
    assert "The join returned no rows." in system_content
    assert "table unavailable" in system_content
    assert "span_id" not in system_content
    assert "parent_span_id" not in system_content
    assert "input.value" not in system_content
    assert "linked-trace" not in system_content

    without_trace_messages = build_analysis_prompt(
        item,
        {},
        [],
        config={"include_fields": {"trace": False}},
    )
    without_trace = next(
        message["content"]
        for message in without_trace_messages
        if message["role"] == "system"
    )
    assert "TRACE EVIDENCE:" not in without_trace
    assert "Agent trace:" not in without_trace
    assert "You are a SQL agent." not in without_trace
    assert system_content.count("The customer key may be stale.") == 1


@pytest.mark.parametrize("trace_text", ["trace evidence ", "دليل التتبع "])
def test_large_trace_preserves_late_tools_evaluation_and_other_context(
    db_session: Session,
    trace_text: str,
) -> None:
    _, _, _, item = _seed_run(db_session)
    item.trace_id = "large-trace"
    item.input = {"question": "q" * 18_000 + "INPUT_TAIL"}
    item.expected = {"answer": "e" * 18_000 + "EXPECTED_TAIL"}
    item.output = {"answer": "o" * 18_000 + "OUTPUT_TAIL"}
    item.item_metadata = {"context": "METADATA_AFTER_TRACE"}
    long_output = trace_text * (360_000 // len(trace_text)) + "AGENT_FINAL_EVIDENCE"
    for index, (name, kind, output) in enumerate(
        [
            ("agent-call", "LLM", long_output),
            ("query-tool", "TOOL", "LATE_TOOL_ERROR_EVIDENCE"),
            ("judge-call", "LLM", "EVALUATION_FINAL_EVIDENCE"),
        ]
    ):
        db_session.add(
            Span(
                run_id=item.run_id,
                trace_id=item.trace_id,
                span_id=f"large-span-{index}",
                start_time_ns=index + 1,
                name=name,
                attributes={"openinference.span.kind": kind, "output.value": output},
            )
        )
    db_session.commit()
    score = RunItemScore(
        run_id=item.run_id,
        item_id=item.item_id,
        metric_name="accuracy",
        score_numeric=0.2,
        explanation="METRIC_EVIDENCE_AFTER_TRACE",
    )
    organized_trace = llm_analyzer_service._organize_trace_content(item.trace_content)
    assert 320_000 < len(organized_trace) < MAX_TRACE_CHARS

    messages = build_analysis_prompt(
        item,
        {"accuracy": score},
        [],
        metric_name="accuracy",
        config={
            "reference_documents": [
                {"name": "first.md", "content": "a" * 40_000},
                {"name": "second.md", "content": "b" * 40_000},
            ]
        },
    )
    content = "\n".join(message["content"] for message in messages)
    assert organized_trace in content
    for evidence in (
        "AGENT_FINAL_EVIDENCE",
        "LATE_TOOL_ERROR_EVIDENCE",
        "EVALUATION_FINAL_EVIDENCE",
        "INPUT_TAIL",
        "EXPECTED_TAIL",
        "OUTPUT_TAIL",
        "METRIC_EVIDENCE_AFTER_TRACE",
        "METADATA_AFTER_TRACE",
        "a" * 40_000,
        "b" * 40_000,
    ):
        assert evidence in content
    assert 320_000 < prompt_character_count(messages) <= MAX_ANALYSIS_PROMPT_CHARS
    assert "characters omitted]" not in content
    assert "prompt context shortened before the provider request" not in content


def test_trace_beyond_new_limit_is_disclosed_without_changing_stored_spans(
    db_session: Session,
) -> None:
    _, _, _, item = _seed_run(db_session)
    item.trace_id = "over-limit-trace"
    source = "TRACE_START" + "x" * MAX_TRACE_CHARS + "BEYOND_TRACE_LIMIT"
    span = Span(
        run_id=item.run_id,
        trace_id=item.trace_id,
        span_id="over-limit-span",
        name="agent-call",
        attributes={"openinference.span.kind": "LLM", "output.value": source},
    )
    db_session.add(span)
    db_session.commit()
    organized = llm_analyzer_service._organize_trace_content(item.trace_content)
    messages = build_analysis_prompt(item, {}, [])
    content = "\n".join(message["content"] for message in messages)
    assert organized[:MAX_TRACE_CHARS].rstrip() in content
    assert f"[{len(organized) - MAX_TRACE_CHARS} characters omitted]" in content
    assert "BEYOND_TRACE_LIMIT" not in content
    assert prompt_character_count(messages) <= MAX_ANALYSIS_PROMPT_CHARS
    db_session.refresh(span)
    assert span.attributes["output.value"] == source

    excluded = build_analysis_prompt(
        item,
        {},
        [],
        config={"include_fields": {"trace": False}},
    )
    assert "TRACE_START" not in "\n".join(message["content"] for message in excluded)


def test_organize_trace_content_drops_chains_and_emits_deltas_by_section() -> None:
    def llm_span(
        span_id: str,
        parent_span_id: str,
        start_time_ns: int,
        input_messages: list[tuple[str, str]],
        output: str,
        thinking: str,
    ) -> dict[str, Any]:
        attributes: dict[str, Any] = {"openinference.span.kind": "LLM"}
        for index, (role, content) in enumerate(input_messages):
            attributes[f"llm.input_messages.{index}.message.role"] = role
            attributes[f"llm.input_messages.{index}.message.content"] = content
        attributes["llm.output_messages.0.message.role"] = "assistant"
        attributes["llm.output_messages.0.message.content"] = output
        attributes["llm.output_messages.0.message.reasoning"] = thinking
        return {
            "span_id": span_id,
            "parent_span_id": parent_span_id,
            "name": "ChatCompletion",
            "kind": "CLIENT",
            "start_time_ns": start_time_ns,
            "attributes": attributes,
            "events": [],
            "links": [],
        }

    organized = llm_analyzer_service._organize_trace_content(
        [
            {
                "span_id": "root-chain",
                "name": "item-chain",
                "kind": "INTERNAL",
                "start_time_ns": 1,
                "attributes": {"openinference.span.kind": "CHAIN"},
            },
            {
                "span_id": "agent-wrapper",
                "parent_span_id": "root-chain",
                "name": "agent-task",
                "kind": "INTERNAL",
                "start_time_ns": 2,
                "attributes": {"openinference.span.kind": "AGENT"},
            },
            llm_span(
                "agent-call-1",
                "agent-wrapper",
                3,
                [("system", "system once"), ("user", "question once")],
                "first answer",
                "think once",
            ),
            {
                "span_id": "empty-agent-call",
                "parent_span_id": "agent-wrapper",
                "name": "ChatCompletion",
                "kind": "CLIENT",
                "start_time_ns": 4,
                "attributes": {"openinference.span.kind": "LLM"},
            },
            llm_span(
                "agent-call-2",
                "agent-wrapper",
                5,
                [
                    ("system", "system once"),
                    ("user", "question once"),
                    ("assistant", "first answer"),
                    ("user", "new follow-up"),
                ],
                "second answer",
                "think twice",
            ),
            {
                "span_id": "evaluation-wrapper",
                "parent_span_id": "root-chain",
                "name": "eval_metrics",
                "kind": "INTERNAL",
                "start_time_ns": 5,
                "attributes": {"openinference.span.kind": "EVALUATOR"},
            },
            {
                "span_id": "evaluation-chain",
                "parent_span_id": "evaluation-wrapper",
                "name": "judge-chain",
                "kind": "INTERNAL",
                "start_time_ns": 6,
                "attributes": {"openinference.span.kind": "CHAIN"},
            },
            llm_span(
                "evaluation-call-1",
                "evaluation-chain",
                7,
                [("system", "judge instructions"), ("user", "first answer")],
                "score one",
                "judge thinking one",
            ),
            llm_span(
                "evaluation-call-2",
                "evaluation-chain",
                8,
                [
                    ("system", "judge instructions"),
                    ("user", "first answer"),
                    ("assistant", "score one"),
                    ("user", "next metric"),
                ],
                "final score",
                "judge thinking two",
            ),
        ]
    )

    assert organized.index("Agent trace:") < organized.index("Evaluation trace:")
    assert "item-chain" not in organized
    assert "agent-task" not in organized
    assert "judge-chain" not in organized
    assert organized.count("system once") == 1
    assert organized.count("question once") == 1
    assert organized.count("new follow-up") == 1
    assert organized.count("think once") == 1
    assert organized.count("think twice") == 1
    assert "(no new content)" not in organized
    assert "Agent trace:\nStep 1 — ChatCompletion:" in organized
    assert "Agent trace:\nStep 1 — ChatCompletion:\nCALL:" in organized
    agent_trace = organized.split("Evaluation trace:", 1)[0]
    assert "Step 2 — ChatCompletion:" in agent_trace
    assert "Step 3 — ChatCompletion:" not in agent_trace
    assert "Evaluation trace:\nStep 1 — ChatCompletion:" in organized
    assert organized.count("Step 2 — ChatCompletion:") == 2


def test_build_analysis_prompt_ignores_legacy_project_description(
    db_session: Session,
) -> None:
    _, _, _, item = _seed_run(db_session)

    messages = build_analysis_prompt(
        item,
        {},
        [],
        config={
            "project_description": "A text-to-SQL assistant for read-only analytics."
        },
    )
    system_content = next(
        message["content"] for message in messages if message["role"] == "system"
    )

    assert "Project description:" not in system_content
    assert "Stored project description:" not in system_content
    assert "{business_context}" not in system_content


def test_build_analysis_prompt_omits_redundant_system_contexts(
    db_session: Session,
) -> None:
    _, _, run, item = _seed_run(db_session)
    run.model = "provider/evaluated-model-v2"
    run.run_config = {
        "temperature": 0.3,
        "api_key": "must-not-reach-the-analyzer",
    }
    run.run_metadata = {"model_revision": "2026-07-20", "region": "sa-east"}
    item.latency_ms = 245.5
    item.retry_count = 2
    item.item_metadata = {"domain": "finance", "source": "golden-set"}
    score = (
        db_session.query(RunItemScore)
        .filter(
            RunItemScore.run_id == run.id,
            RunItemScore.item_id == item.item_id,
            RunItemScore.metric_name == "accuracy",
        )
        .one()
    )
    score.label = "fail"
    score.explanation = "The generated answer used the wrong join."
    score.meta = {"reason": "wrong answer", "judge_version": "v3"}
    db_session.add(
        RunMetricSpec(
            run_id=run.id,
            metric_name="accuracy",
            position=0,
            score_type="percentage",
            direction="maximize",
            pass_threshold=0.8,
            sample_reducer="mean",
            run_reducer="mean",
        )
    )
    db_session.commit()

    messages = build_analysis_prompt(
        item,
        {"accuracy": score},
        [],
        config={
            "project_description": "A regulated financial support assistant.",
            "root_cause_categories": ["Reasoning Error"],
            "approved_category_details": {"Reasoning Error": ["Join mismatch"]},
            "reference_documents": [
                {"name": "policy.md", "content": "Always cite the account policy."}
            ],
        },
        metric_name="accuracy",
    )
    system_content = next(
        message["content"] for message in messages if message["role"] == "system"
    )
    user_content = next(
        message["content"] for message in messages if message["role"] == "user"
    )

    for placeholder in (
        "{business_context}",
        "{metric_context}",
        "{model_context}",
        "{item_context}",
    ):
        assert placeholder not in system_content

    for heading in (
        "BUSINESS CONTEXT:",
        "METRIC CONTEXT:",
        "MODEL CONTEXT:",
    ):
        assert heading not in system_content
    assert "Project: Project One" not in system_content
    assert "Project description:" not in system_content
    assert "Stored project description:" not in system_content
    assert "Evaluation task: insightor_api" not in system_content
    assert "Dataset: dataset-1" not in system_content
    assert "Attached reference documents: policy.md" not in system_content
    assert "Reasoning Error" in system_content
    assert "Join mismatch" in system_content

    assert '"selected_metric": "accuracy"' not in system_content
    assert '"score": 0.1' in system_content
    assert '"label": "fail"' in system_content
    assert "The generated answer used the wrong join." in system_content
    assert '"pass_threshold": 0.8' not in system_content
    assert '"direction": "maximize"' not in system_content

    assert '"evaluated_model": "provider/evaluated-model-v2"' not in system_content
    assert '"temperature": 0.3' not in system_content
    assert '"api_key": "[REDACTED]"' not in system_content
    assert "must-not-reach-the-analyzer" not in system_content
    assert '"model_revision": "2026-07-20"' not in system_content

    assert '"item_id": "item-1"' not in system_content
    assert '"latency_ms": 245.5' not in system_content
    assert '"retry_count": 2' not in system_content
    assert '"domain": "finance"' in system_content
    assert '"question": "q"' in system_content
    assert '"answer": "expected"' in system_content
    assert '"answer": "actual"' in system_content
    assert "Always cite the account policy." in user_content


def test_build_analysis_prompt_removes_legacy_context_fields_and_preserves_literal_json() -> None:
    item = RunItem(
        run_id="detached-run",
        item_id="item-1",
        index=0,
        input={"question": "Why?"},
        output={"answer": "Because."},
    )
    messages = build_analysis_prompt(
        item,
        {},
        [],
        config={
            "system_prompt": (
                "Categories:\n{categories}\n\n"
                "**BUSINESS CONTEXT**\n{business_context}\n\n"
                "**METRIC CONTEXT**\n{metric_context}\n\n"
                "**MODEL CONTEXT**\n{model_context}\n\n"
                "Item:\n{item_context}\n\n"
                'Return {{"root_cause": "value"}}.'
            ),
            "business_context": {"domain": "support"},
            "metric_context": "Prefer the human rubric.",
            "model_context": {"family": "small-model"},
        },
    )
    system_content = next(
        message["content"] for message in messages if message["role"] == "system"
    )
    user_content = next(
        message["content"] for message in messages if message["role"] == "user"
    )

    assert '"domain": "support"' not in system_content
    assert "Prefer the human rubric." not in system_content
    assert '"family": "small-model"' not in system_content
    assert "{business_context}" not in system_content
    assert "{metric_context}" not in system_content
    assert "{model_context}" not in system_content
    assert "BUSINESS CONTEXT" not in system_content
    assert "METRIC CONTEXT" not in system_content
    assert "MODEL CONTEXT" not in system_content
    assert '"question": "Why?"' in system_content
    assert 'Return {"root_cause": "value"}.' in system_content
    assert "INPUT:" not in user_content


def test_custom_system_prompt_appends_all_omitted_analyzer_context() -> None:
    item = RunItem(
        run_id="run-1",
        item_id="item-1",
        index=0,
        input={"question": "Why?"},
        output={"answer": "Because."},
    )
    score = RunItemScore(
        run_id="run-1",
        item_id="item-1",
        metric_name="accuracy",
        score_numeric=0.2,
        explanation="The answer omitted the required evidence.",
    )

    messages = build_analysis_prompt(
        item,
        {"accuracy": score},
        [],
        config={
            "system_prompt": "Classify the item and return JSON.",
            "business_context": "Billing support",
            "metric_context": "Evidence is required",
            "model_context": "Evaluated model family: small",
            "solution_categories": ["Add Evidence"],
        },
        metric_name="accuracy",
    )
    system_content = next(
        message["content"] for message in messages if message["role"] == "system"
    )
    user_content = next(
        message["content"] for message in messages if message["role"] == "user"
    )

    assert "SUPPLIED ANALYSIS DATA" in system_content
    assert "Billing support" not in system_content
    assert "Evidence is required" not in system_content
    assert "Evaluated model family: small" not in system_content
    assert "The answer omitted the required evidence." in system_content
    assert 'JSON field "solution"' not in system_content
    assert "Add Evidence" not in system_content
    assert '"question": "Why?"' in system_content
    assert "ITEM RECORD" not in user_content


def test_prompt_redacts_item_and_metric_secrets_and_excludes_correction_context() -> (
    None
):
    item = RunItem(
        run_id="run-1",
        item_id="item-1",
        index=0,
        input='{"question": "q", "access_token": "item-secret"}',
        output={"answer": "actual"},
    )
    score = RunItemScore(
        run_id="run-1",
        item_id="item-1",
        metric_name="accuracy",
        score_numeric=0.2,
        meta={"reason": "bad join", "judge": {"api_key": "metric-secret"}},
    )
    correction = ReviewCorrection(
        run_id="run-1",
        item_id="item-2",
        task="task",
        input_snapshot={"question": "example", "password": "correction-secret"},
        human_root_cause="Reasoning Error",
        status=CorrectionStatus.APPROVED,
        is_active=True,
    )

    messages = build_analysis_prompt(item, {"accuracy": score}, [correction])
    prompt_content = "\n".join(message["content"] for message in messages)

    assert "item-secret" not in prompt_content
    assert "metric-secret" not in prompt_content
    assert "correction-secret" not in prompt_content
    assert prompt_content.count('"[REDACTED]"') >= 2


def test_default_prompt_requests_only_diagnosis_fields() -> (
    None
):
    item = RunItem(run_id="run-1", item_id="item-1", index=0, input={"q": "x"})
    messages = build_analysis_prompt(
        item,
        {},
        [],
        config={"solution_categories": ["Add Validation"]},
    )
    system_content = next(
        message["content"] for message in messages if message["role"] == "system"
    )

    assert '"root_cause_issues": [' in system_content
    assert (
        '"subcategory": "<reusable failure mechanism, 2-6 words>"'
        in system_content
    )
    assert '"confidence": <float between 0.0-1.0>' in system_content
    assert (
        '"finding": "<2-3 sentences maximum: the item-specific diagnosis>"'
        in system_content
    )
    assert '"solution"' not in system_content
    assert "Add Validation" not in system_content
    assert "Analyze only the selected metric" in system_content
    assert (
        "not restate this item's specific table, column, entity, date, function"
        in system_content
    )
    assert "recommendation or remediation fields" in system_content


def test_approved_correction_is_excluded_from_analysis_prompt() -> None:
    item = RunItem(run_id="run-1", item_id="item-1", index=0, input={"q": "x"})
    correction = ReviewCorrection(
        run_id="run-1",
        item_id="item-2",
        task="task",
        input_snapshot={"question": "private example question"},
        expected_snapshot={"answer": "private expected answer"},
        output_snapshot={"answer": "private actual answer"},
        human_root_cause="Private Correction Category",
        human_root_cause_detail="Missing account policy",
        human_root_cause_note="The private reviewer diagnosis.",
        human_solution="Improve Retrieval Context",
        human_solution_note="Retrieve the account policy before answering.",
        status=CorrectionStatus.APPROVED,
        is_active=True,
    )

    messages = build_analysis_prompt(item, {}, [correction])
    prompt = "\n".join(message["content"] for message in messages)

    assert "--- Example ---" not in prompt
    assert "private example question" not in prompt
    assert "private expected answer" not in prompt
    assert "private actual answer" not in prompt
    assert "Private Correction Category" not in prompt
    assert "Missing account policy" not in prompt
    assert "The private reviewer diagnosis." not in prompt
    assert "Improve Retrieval Context" not in prompt
    assert "Retrieve the account policy before answering." not in prompt


def test_analysis_prompt_excludes_redundant_telemetry_and_duplicate_context() -> None:
    item = RunItem(
        run_id="run-sensitive-id",
        item_id="item-sensitive-id",
        index=17,
        input={
            "sql_prompt": "List active customers",
            "sql_context": "CREATE TABLE customers(id INT, active BOOL)",
        },
        expected="SELECT id FROM customers WHERE active = TRUE",
        output="SELECT id FROM customers",
        latency_ms=812.4,
        retry_count=3,
        item_metadata={
            "sql_prompt": "List active customers",
            "sql_context": "CREATE TABLE customers(id INT, active BOOL)",
            "task_started_at_ms": 123456,
            "trace_stats": {"span_count": 42, "token_count": 9001},
            "domain": "analytics",
            "solution": "Use a WHERE clause",
        },
    )
    score = RunItemScore(
        run_id=item.run_id,
        item_id=item.item_id,
        metric_name="execution_accuracy",
        score_numeric=0.0,
        score_raw={
            "score": 0.0,
            "metadata": {"reason": "Result rows differ"},
        },
        meta={"reason": "Result rows differ"},
    )
    correction = ReviewCorrection(
        run_id="other-run",
        item_id="example-item",
        task="text2sql",
        metric_name="execution_accuracy",
        input_snapshot={"sql_prompt": "Count customers"},
        scores_snapshot={
            "execution_accuracy": 0.0,
            "format": 1.0,
        },
        human_root_cause="Reasoning Error",
        human_root_cause_detail="Missing filter predicate",
        human_root_cause_note="The query omitted the required active filter.",
        human_solution="Refine Prompt Instructions",
        human_solution_note="Tell the model to preserve all filters.",
        status=CorrectionStatus.APPROVED,
        is_active=True,
    )

    messages = build_analysis_prompt(
        item,
        {"execution_accuracy": score},
        [correction],
        config={
            "root_cause_categories": [
                *ROOT_CAUSE_CATEGORIES,
                "Dataset issue",
            ],
            "solution_categories": ["Refine Prompt Instructions"],
        },
        metric_name="execution_accuracy",
    )
    prompt = "\n".join(message["content"] for message in messages)

    assert prompt.count("- Dataset Issue") == 1
    assert "- Dataset issue" not in prompt
    assert prompt.count("2. subcategory") == 1
    assert prompt.count('"sql_prompt": "List active customers"') == 1
    assert '"domain": "analytics"' in prompt
    assert "ITEM RECORD" not in prompt
    assert "item-sensitive-id" not in prompt
    assert "run-sensitive-id" not in prompt
    assert "latency_ms" not in prompt
    assert "retry_count" not in prompt
    assert "trace_stats" not in prompt
    assert "token_count" not in prompt
    assert '"format": 1.0' not in prompt
    assert "solution" not in prompt.casefold()


def test_analysis_prompt_scopes_category_root_cause_and_feedback_to_selected_metric() -> (
    None
):
    item = RunItem(run_id="run-1", item_id="item-1", index=0, input={"q": "x"})
    accuracy_score = RunItemScore(
        run_id="run-1",
        item_id="item-1",
        metric_name="accuracy",
        score_numeric=0.25,
    )
    format_score = RunItemScore(
        run_id="run-1",
        item_id="item-1",
        metric_name="format",
        score_numeric=1.0,
    )
    scores = {"accuracy": accuracy_score, "format": format_score}

    accuracy_messages = build_analysis_prompt(
        item,
        scores,
        [],
        metric_name="accuracy",
    )
    format_messages = build_analysis_prompt(
        item,
        scores,
        [],
        metric_name="format",
    )

    accuracy_prompt = "\n".join(message["content"] for message in accuracy_messages)
    format_prompt = "\n".join(message["content"] for message in format_messages)
    accuracy_user_message = next(
        message["content"]
        for message in accuracy_messages
        if message["role"] == "user"
    )
    format_user_message = next(
        message["content"] for message in format_messages if message["role"] == "user"
    )

    assert '"selected_metric": "accuracy"' not in accuracy_prompt
    assert '"accuracy": {' in accuracy_prompt
    assert '"format": {' not in accuracy_prompt
    assert '"selected_metric": "format"' not in format_prompt
    assert '"format": {' in format_prompt
    assert '"accuracy": {' not in format_prompt
    assert accuracy_user_message == "Return only the JSON object required by the system prompt."
    assert format_user_message == "Return only the JSON object required by the system prompt."


def test_parse_llm_response_calibrates_and_bounds_confidence() -> None:
    complete = parse_llm_response(
        json.dumps(
            {
                "root_cause": "Reasoning Error",
                "root_cause_detail": "The join condition used the wrong key.",
                "confidence": 0.9,
                "root_cause_note": "The metric explanation and actual SQL both identify the incorrect customer join.",
                "solution": "Add Output Validation",
            }
        ),
        "item-1",
    )
    incomplete = parse_llm_response(
        '{"root_cause":"Unlisted Cause","confidence":0.9}',
        "item-2",
    )
    non_finite = parse_llm_response(
        '{"root_cause":"Reasoning Error","confidence":"NaN"}',
        "item-3",
    )

    assert complete.confidence == 0.9
    assert complete.solution == ""
    assert incomplete.confidence < complete.confidence
    assert 0.0 <= non_finite.confidence <= 1.0
    assert math.isfinite(non_finite.confidence)


@pytest.mark.asyncio
async def test_analyze_single_item_sends_max_tokens_and_records_provenance() -> None:
    response = SimpleNamespace(
        id="provider-request-1",
        usage=SimpleNamespace(
            prompt_tokens=100,
            completion_tokens=20,
            total_tokens=120,
        ),
        choices=[
            SimpleNamespace(
                finish_reason="stop",
                message=SimpleNamespace(
                    content=json.dumps(
                        {
                            "root_cause": "Reasoning Error",
                            "root_cause_detail": "Wrong join key",
                            "root_cause_note": "The SQL joined the wrong columns.",
                            "confidence": 0.8,
                            "solution": "Add Output Validation",
                        }
                    )
                ),
            )
        ],
    )
    create = AsyncMock(return_value=response)
    client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))
    )
    item = RunItem(run_id="run-1", item_id="item-1", index=0, input={"q": "x"})

    result = await analyze_single_item(
        client,
        "test-model",
        item,
        {},
        [],
        max_tokens=321,
    )

    assert create.await_args.kwargs["temperature"] == 0.0
    assert create.await_args.kwargs["max_tokens"] == 321
    assert result.analyzer_model == "test-model"
    assert result.provider_request_id == "provider-request-1"
    assert result.total_tokens == 120
    assert len(result.prompt_hash) == 64


def test_playground_config_has_no_project_description_override() -> None:
    config = PlaygroundConfig(
        project_description="A support assistant for billing questions."
    )

    assert "project_description" not in PlaygroundConfig.model_fields
    assert _playground_config_to_analyzer(config) is None


def test_playground_config_passes_run_context_toggles_to_analyzer() -> None:
    config = PlaygroundConfig(
        include_project_rules=False,
        include_project_documents=False,
        include_fields={"trace": False},
    )

    assert _playground_config_to_analyzer(config) == {
        "_include_project_rules": False,
        "_include_project_documents": False,
        "include_fields": {"trace": False},
    }


def test_rule_request_models_allow_more_than_twenty_rules() -> None:
    rules = [
        {
            "title": f"Rule {index}",
            "instruction": f"Check requirement {index}.",
        }
        for index in range(21)
    ]

    playground_config = PlaygroundConfig.model_validate({"analysis_rules": rules})
    context_update = AnalysisContextUpdate.model_validate({"analysis_rules": rules})

    assert len(playground_config.analysis_rules or []) == 21
    assert len(context_update.analysis_rules) == 21


def test_analysis_targets_include_every_failed_metric_and_skip_each_completed_metric(
    db_session: Session,
) -> None:
    _, _, run, item = _seed_run(db_session)
    run.metrics = ["accuracy", "format", "quality"]
    db_session.add_all(
        [
            RunItemScore(
                run_id=run.id,
                item_id=item.item_id,
                metric_name="format",
                score_numeric=0.2,
            ),
            RunItemScore(
                run_id=run.id,
                item_id=item.item_id,
                metric_name="quality",
                score_numeric=0.95,
            ),
        ]
    )
    for position, metric_name in enumerate(run.metrics):
        db_session.add(
            RunMetricSpec(
                run_id=run.id,
                metric_name=metric_name,
                position=position,
                score_type="percentage",
                direction="maximize",
                pass_threshold=0.8,
                sample_reducer="mean",
                run_reducer="mean",
            )
        )
    db_session.commit()

    scores = db_session.query(RunItemScore).filter(RunItemScore.run_id == run.id).all()
    scores_by_item = {item.item_id: {score.metric_name: score for score in scores}}
    request = AnalyzeRequest(item_filter="failed", only_unanalyzed=True)

    targets = _filter_analysis_targets(
        run,
        request,
        [item],
        scores_by_item,
        _load_metric_specs(db_session, run),
    )
    assert [(target.item_id, metric) for target, metric in targets] == [
        (item.item_id, "accuracy"),
        (item.item_id, "format"),
    ]

    item.item_metadata = {
        "metric_analyses": {
            "accuracy": {"root_cause": "Reasoning Error", "source": "ai"}
        }
    }
    db_session.commit()
    remaining = _filter_analysis_targets(
        run,
        request,
        [item],
        scores_by_item,
        _load_metric_specs(db_session, run),
    )
    assert [(target.item_id, metric) for target, metric in remaining] == [
        (item.item_id, "format")
    ]


def test_analysis_targets_protect_human_labels_per_metric(
    db_session: Session,
) -> None:
    _, _, run, item = _seed_run(db_session)
    run.metrics = ["accuracy", "format"]
    format_score = RunItemScore(
        run_id=run.id,
        item_id=item.item_id,
        metric_name="format",
        score_numeric=0.2,
    )
    item.item_metadata = {
        "root_cause": "Legacy AI",
        "root_cause_source": "ai",
        "metric_analyses": {
            "accuracy": {"source": "human", "root_cause": "Manual Category"},
            "format": {"source": "ai", "root_cause": "Old Category"},
        },
    }
    db_session.add(format_score)
    db_session.commit()
    scores = db_session.query(RunItemScore).filter(RunItemScore.run_id == run.id).all()
    scores_by_item = {
        item.item_id: {score.metric_name: score for score in scores}
    }

    protected = _filter_analysis_targets(
        run,
        AnalyzeRequest(
            metrics=["accuracy", "format"],
            item_filter="failed",
            only_unanalyzed=False,
            allow_human_overwrite=False,
        ),
        [item],
        scores_by_item,
        {},
    )
    assert [(target.item_id, metric) for target, metric in protected] == [
        (item.item_id, "format")
    ]

    human_override = _filter_analysis_targets(
        run,
        AnalyzeRequest(
            metrics=["accuracy", "format"],
            item_filter="failed",
            only_unanalyzed=True,
            allow_human_overwrite=True,
        ),
        [item],
        scores_by_item,
        {},
    )
    assert [(target.item_id, metric) for target, metric in human_override] == [
        (item.item_id, "accuracy")
    ]


def test_analysis_targets_protect_human_detail_only_labels(
    db_session: Session,
) -> None:
    _, _, run, item = _seed_run(db_session)
    item.item_metadata = {
        "metric_analyses": {
            "accuracy": {
                "source": "human",
                "root_cause_note": "Reviewer explanation without a category yet",
            }
        }
    }
    db_session.commit()
    score = (
        db_session.query(RunItemScore)
        .filter(
            RunItemScore.run_id == run.id,
            RunItemScore.item_id == item.item_id,
            RunItemScore.metric_name == "accuracy",
        )
        .one()
    )

    targets = _filter_analysis_targets(
        run,
        AnalyzeRequest(item_filter="failed", only_unanalyzed=True),
        [item],
        {item.item_id: {"accuracy": score}},
        {},
    )
    assert targets == []


def test_unknown_requested_metric_is_rejected(db_session: Session) -> None:
    _actor, _reviewer, run, item = _seed_run(db_session)

    with pytest.raises(HTTPException, match="Unknown metric 'missing'") as exc_info:
        _validate_requested_metric(run, {item.item_id: {}}, "missing")

    assert exc_info.value.status_code == 400


def test_analysis_targets_only_include_selected_metrics(db_session: Session) -> None:
    _, _, run, item = _seed_run(db_session)
    run.metrics = ["accuracy", "format", "quality"]

    targets = _filter_analysis_targets(
        run,
        AnalyzeRequest(
            metrics=["format", "quality"],
            item_filter="failed",
            only_unanalyzed=False,
        ),
        [item],
        {item.item_id: {}},
        {},
    )

    assert [(target.item_id, metric) for target, metric in targets] == [
        (item.item_id, "format"),
        (item.item_id, "quality"),
    ]


def test_empty_metric_selection_analyzes_nothing(db_session: Session) -> None:
    _, _, run, item = _seed_run(db_session)

    targets = _filter_analysis_targets(
        run,
        AnalyzeRequest(metrics=[], item_filter="failed", only_unanalyzed=False),
        [item],
        {item.item_id: {}},
        {},
    )

    assert targets == []


def test_analysis_target_limit_uses_deterministic_severity_order(
    db_session: Session,
) -> None:
    _, _, run, first_item = _seed_run(db_session)
    second_item = RunItem(
        run_id=run.id,
        item_id="item-2",
        index=1,
        input={"question": "second"},
        item_metadata={},
    )
    third_item = RunItem(
        run_id=run.id,
        item_id="item-3",
        index=2,
        input={"question": "third"},
        item_metadata={},
    )
    second_score = RunItemScore(
        run_id=run.id,
        item_id=second_item.item_id,
        metric_name="accuracy",
        score_numeric=0.4,
    )
    third_score = RunItemScore(
        run_id=run.id,
        item_id=third_item.item_id,
        metric_name="accuracy",
        score_numeric=0.0,
    )
    db_session.add_all([second_item, third_item, second_score, third_score])
    db_session.commit()
    first_score = (
        db_session.query(RunItemScore)
        .filter(
            RunItemScore.run_id == run.id,
            RunItemScore.item_id == first_item.item_id,
        )
        .one()
    )

    targets = _filter_analysis_targets(
        run,
        AnalyzeRequest(
            metrics=["accuracy"],
            item_filter="failed",
            only_unanalyzed=False,
            limit=2,
        ),
        [first_item, second_item, third_item],
        {
            first_item.item_id: {"accuracy": first_score},
            second_item.item_id: {"accuracy": second_score},
            third_item.item_id: {"accuracy": third_score},
        },
        {},
    )

    assert [(item.item_id, metric) for item, metric in targets] == [
        ("item-3", "accuracy"),
        ("item-1", "accuracy"),
    ]


def test_analysis_target_limit_counts_items_and_keeps_selected_metrics(
    db_session: Session,
) -> None:
    _, _, run, first_item = _seed_run(db_session)
    run.metrics = ["accuracy", "format"]
    second_item = RunItem(
        run_id=run.id,
        item_id="item-2",
        index=1,
        input={"question": "second"},
        item_metadata={},
    )
    first_scores = {
        "accuracy": db_session.query(RunItemScore)
        .filter(
            RunItemScore.run_id == run.id,
            RunItemScore.item_id == first_item.item_id,
            RunItemScore.metric_name == "accuracy",
        )
        .one(),
        "format": RunItemScore(
            run_id=run.id,
            item_id=first_item.item_id,
            metric_name="format",
            score_numeric=0.2,
        ),
    }
    second_scores = {
        "accuracy": RunItemScore(
            run_id=run.id,
            item_id=second_item.item_id,
            metric_name="accuracy",
            score_numeric=0.4,
        ),
        "format": RunItemScore(
            run_id=run.id,
            item_id=second_item.item_id,
            metric_name="format",
            score_numeric=0.5,
        ),
    }
    db_session.add_all([second_item, first_scores["format"], *second_scores.values()])
    db_session.commit()

    targets = _filter_analysis_targets(
        run,
        AnalyzeRequest(
            metrics=["accuracy", "format"],
            item_filter="failed",
            only_unanalyzed=False,
            limit=1,
        ),
        [first_item, second_item],
        {first_item.item_id: first_scores, second_item.item_id: second_scores},
        {},
    )

    assert [(item.item_id, metric) for item, metric in targets] == [
        ("item-1", "accuracy"),
        ("item-1", "format"),
    ]


def test_analysis_targets_do_not_apply_max_score_as_an_upper_bound_to_minimize_metrics(
    db_session: Session,
) -> None:
    _, _, run, item = _seed_run(db_session)
    run.metrics = ["latency"]
    score = RunItemScore(
        run_id=run.id,
        item_id=item.item_id,
        metric_name="latency",
        score_numeric=0.9,
    )
    spec = RunMetricSpec(
        run_id=run.id,
        metric_name="latency",
        position=0,
        score_type="number",
        direction="minimize",
        pass_threshold=0.2,
        sample_reducer="mean",
        run_reducer="mean",
    )
    db_session.add_all([score, spec])
    db_session.commit()

    targets = _filter_analysis_targets(
        run,
        AnalyzeRequest(item_filter="failed", max_score=0.8),
        [item],
        {item.item_id: {"latency": score}},
        {"latency": spec},
    )

    assert [(target.item_id, metric) for target, metric in targets] == [
        (item.item_id, "latency")
    ]


def test_analysis_results_are_saved_by_metric_with_legacy_item_summary(
    db_session: Session,
) -> None:
    actor, reviewer, run, item = _seed_run(db_session)
    results = [
        AnalysisResult(
            item_id=item.item_id,
            metric_name="accuracy",
            root_cause="Reasoning Error",
            root_cause_detail="Wrong join key",
            root_cause_reason="The output shows the model joined records using the wrong key.",
            root_cause_note="The metric explanation identifies the join mismatch.",
            confidence=0.9,
            solution="Add Output Validation",
        ),
        AnalysisResult(
            item_id=item.item_id,
            metric_name="format",
            root_cause="Wrong Format",
            root_cause_detail="Invalid response envelope",
            root_cause_note="The output omitted the required response wrapper.",
            confidence=0.8,
            solution="Refine Prompt Instructions",
        ),
    ]

    payloads, errors = _save_analysis_results(
        db_session,
        run,
        [(item, "accuracy"), (item, "format")],
        results,
        Principal(user=actor, auth_type="none"),
        analyzer_rule_version_id="rule-version-v1",
    )
    db_session.refresh(item)

    assert errors == 0
    assert [payload["metric_name"] for payload in payloads] == ["accuracy", "format"]
    assert payloads[0]["root_cause_reason"] == (
        "The output shows the model joined records using the wrong key."
    )
    assert (
        item.item_metadata["metric_analyses"]["accuracy"]["root_cause"]
        == "Reasoning Error"
    )
    assert item.item_metadata["metric_analyses"]["accuracy"]["root_cause_reason"] == (
        "The output shows the model joined records using the wrong key."
    )
    assert (
        item.item_metadata["metric_analyses"]["format"]["root_cause"] == "Wrong Format"
    )
    assert (
        item.item_metadata["metric_analyses"]["accuracy"][
            "analyzer_rule_version_id"
        ]
        == "rule-version-v1"
    )
    assert item.item_metadata["root_cause"] == "Reasoning Error"
    assert item.item_metadata["root_cause_reason"] == (
        "The output shows the model joined records using the wrong key."
    )
    assert item.item_metadata["root_cause_metric_name"] == "accuracy"
    candidates = (
        db_session.query(ReviewCorrection)
        .filter(
            ReviewCorrection.run_id == run.id,
            ReviewCorrection.item_id == item.item_id,
            ReviewCorrection.is_active.is_(True),
        )
        .order_by(ReviewCorrection.metric_name.asc())
        .all()
    )
    assert [candidate.metric_name for candidate in candidates] == ["accuracy", "format"]
    assert [candidate.ai_root_cause for candidate in candidates] == [
        "Reasoning Error",
        "Wrong Format",
    ]
    assert [candidate.ai_root_cause_note for candidate in candidates] == [
        "The metric explanation identifies the join mismatch.",
        "The output omitted the required response wrapper.",
    ]
    candidates[0].human_root_cause = candidates[0].ai_root_cause
    candidates[0].human_root_cause_note = "APPROVED ACCURACY EXAMPLE"
    candidates[1].human_root_cause = candidates[1].ai_root_cause
    candidates[1].human_root_cause_note = "APPROVED FORMAT EXAMPLE"
    prompt = build_analysis_prompt(item, {}, candidates, metric_name="accuracy")
    prompt_text = "\n".join(message["content"] for message in prompt)
    assert "APPROVED ACCURACY EXAMPLE" not in prompt_text
    assert "APPROVED FORMAT EXAMPLE" not in prompt_text

    _approve_candidate(
        db_session,
        correction=candidates[0],
        reviewer_id=reviewer.id,
        comment="Approve accuracy only",
        reviewed_at=datetime.utcnow(),
    )
    db_session.commit()
    db_session.refresh(candidates[0])
    db_session.refresh(candidates[1])
    assert candidates[0].status == CorrectionStatus.APPROVED
    assert candidates[1].status == CorrectionStatus.PENDING
    assert candidates[1].is_active is True

    row = _build_run_data(db_session, run)["snapshot"]["rows"][0]
    assert row["review_corrections"] == {
        "accuracy": {"id": candidates[0].id, "status": "approved"},
        "format": {"id": candidates[1].id, "status": "pending"},
    }


def test_untaxonomized_ai_category_is_saved_with_item_warning(
    db_session: Session,
) -> None:
    actor, _, run, item = _seed_run(db_session)
    warning = (
        "Warning: AI selected category 'Novel Failure' without complete taxonomy. "
        "The diagnosis was accepted for this item; add taxonomy guidance before "
        "relying on this label in future analyses."
    )
    result = AnalysisResult(
        item_id=item.item_id,
        metric_name="accuracy",
        root_cause="Novel Failure",
        root_cause_note="The output shows a project-specific failure.",
        confidence=0.6,
        warning=warning,
    )

    payloads, errors = _save_analysis_results(
        db_session,
        run,
        [(item, "accuracy")],
        [result],
        Principal(user=actor, auth_type="none"),
    )
    db_session.refresh(item)

    assert errors == 0
    assert payloads[0]["error"] is None
    assert payloads[0]["warning"] == warning
    assert item.item_metadata["analysis_warning"] == warning
    assert item.item_metadata["metric_analyses"]["accuracy"]["root_cause"] == (
        "Novel Failure"
    )
    assert item.item_metadata["metric_analyses"]["accuracy"]["warning"] == warning


def test_approve_metric_analysis_materializes_legacy_metric_candidate(
    db_session: Session,
) -> None:
    _, reviewer, run, item = _seed_run(db_session)
    item.item_metadata = {
        "metric_analyses": {
            "accuracy": {
                "source": "ai",
                "root_cause": "Reasoning Error",
                "root_cause_detail": "Wrong join key",
                "root_cause_note": "Legacy per-metric analysis",
                "confidence": 0.9,
                "solution": "Add Output Validation",
            },
            "format": {
                "source": "ai",
                "root_cause": "Wrong Format",
                "root_cause_detail": "Invalid response envelope",
            },
        }
    }
    db_session.commit()

    result = approve_metric_analysis(
        {
            "run_id": run.id,
            "item_id": item.item_id,
            "metric_name": "accuracy",
            "comment": "",
        },
        db=db_session,
        principal=Principal(auth_type="api_key", user=reviewer),
    )

    assert result["metric_name"] == "accuracy"
    assert result["status"] == "approved"
    candidates = (
        db_session.query(ReviewCorrection)
        .filter(ReviewCorrection.run_id == run.id, ReviewCorrection.is_active.is_(True))
        .all()
    )
    assert [(candidate.metric_name, candidate.status) for candidate in candidates] == [
        ("accuracy", CorrectionStatus.APPROVED)
    ]


@pytest.mark.asyncio
async def test_approved_metric_analysis_is_immutable_to_new_ai_analysis(
    db_session: Session,
) -> None:
    actor, reviewer, run, item = _seed_run(db_session)
    approved_analysis = {
        "source": "ai",
        "root_cause": "Reasoning Error",
        "root_causes": ["Reasoning Error"],
        "root_cause_detail": "Approved detail",
        "root_cause_note": "Keep the reviewed diagnosis.",
    }
    item.item_metadata = {"metric_analyses": {"accuracy": approved_analysis}}
    db_session.commit()

    candidate = replace_metric_review_candidate(
        db_session,
        run=run,
        item=item,
        metric_name="accuracy",
        analysis=approved_analysis,
        actor_user_id=actor.id,
        actor_source="ai",
    )
    assert candidate is not None
    _approve_candidate(
        db_session,
        correction=candidate,
        reviewer_id=reviewer.id,
        comment="Keep reviewed diagnosis",
        reviewed_at=datetime.utcnow(),
    )
    db_session.commit()

    approved_keys = analysis_api._active_approved_review_keys(
        db_session, run, {item.item_id}
    )
    score = (
        db_session.query(RunItemScore)
        .filter(
            RunItemScore.run_id == run.id,
            RunItemScore.item_id == item.item_id,
            RunItemScore.metric_name == "accuracy",
        )
        .one()
    )
    targets = _filter_analysis_targets(
        run,
        AnalyzeRequest(
            metrics=["accuracy"],
            item_filter="failed",
            only_unanalyzed=False,
        ),
        [item],
        {item.item_id: {"accuracy": score}},
        {},
        approved_review_keys=approved_keys,
    )
    assert targets == []

    fresh_result = AnalysisResult(
        item_id=item.item_id,
        metric_name="accuracy",
        root_cause="Dataset Issue",
        root_cause_detail="Fresh AI detail",
        root_cause_note="This must not replace the review snapshot.",
        confidence=0.95,
    )
    payloads, errors = _save_analysis_results(
        db_session,
        run,
        [(item, "accuracy")],
        [fresh_result],
        Principal(user=actor, auth_type="none"),
    )
    assert errors == 0
    assert payloads[0]["persistence_status"] == "skipped_approved_protection"

    db_session.refresh(item)
    db_session.refresh(candidate)
    assert item.item_metadata["metric_analyses"]["accuracy"] == approved_analysis
    assert candidate.status == CorrectionStatus.APPROVED
    assert candidate.is_active is True
    assert [
        correction.id
        for correction in get_few_shot_examples(
            db_session, run.task, run.project_id, limit=10
        )
    ] == [candidate.id]
    picker = _list_analysis_examples(
        scope_id=run.id,
        page=1,
        page_size=50,
        task=None,
        dataset=None,
        model=None,
        run_name=None,
        user_id=None,
        source=None,
        conf_min=0,
        conf_max=100,
        search=None,
        selected_ids=None,
        selected_only=False,
        db=db_session,
        principal=Principal(user=reviewer, auth_type="none"),
    )
    assert picker["matching_ids"] == [candidate.id]

    # The service-level guard protects direct AI writes as well as the API
    # persistence boundary.
    returned_candidate = replace_metric_review_candidate(
        db_session,
        run=run,
        item=item,
        metric_name="accuracy",
        analysis={
            "source": "ai",
            "root_cause": "Another AI category",
            "root_cause_detail": "Another AI detail",
        },
        actor_user_id=actor.id,
        actor_source="ai",
    )
    assert returned_candidate is candidate

    parse = AsyncMock()
    client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(parse=parse))
    )
    categories, changed = await _aggregate_run_analysis_results(
        db=db_session,
        run=run,
        all_items=[item],
        analysis_targets=[(item, "accuracy")],
        new_results=[fresh_result],
        client=client,
        model="test-model",
        analyzer_config=None,
        principal=Principal(user=actor, auth_type="none"),
    )
    assert categories == {}
    assert changed == 0
    parse.assert_not_awaited()


def test_ai_root_cause_change_cannot_supersede_approved_item_candidate(
    db_session: Session,
) -> None:
    actor, reviewer, run, item = _seed_run(db_session)
    human_change = apply_root_cause_change(
        db_session,
        run=run,
        item=item,
        actor_user_id=actor.id,
        actor_source="human",
        human_patch={
            "root_cause": "Context Missing",
            "root_cause_detail": "Approved item detail",
            "root_cause_note": "Approved item note",
        },
    )
    candidate = human_change.candidate
    assert candidate is not None
    _approve_candidate(
        db_session,
        correction=candidate,
        reviewer_id=reviewer.id,
        comment="Approve item diagnosis",
        reviewed_at=datetime.utcnow(),
    )
    db_session.commit()
    revision_count = db_session.query(RootCauseRevision).count()

    ai_change = apply_root_cause_change(
        db_session,
        run=run,
        item=item,
        actor_user_id=actor.id,
        actor_source="ai",
        next_state=build_ai_state(
            root_cause="Dataset Issue",
            root_cause_detail="Fresh AI item detail",
            root_cause_note="Fresh AI item note",
            confidence=0.99,
        ),
    )
    db_session.commit()
    db_session.refresh(item)
    db_session.refresh(candidate)

    assert ai_change.changed is False
    assert ai_change.candidate is candidate
    assert item.item_metadata["root_cause"] == "Context Missing"
    assert item.item_metadata["root_cause_detail"] == "Approved item detail"
    assert candidate.status == CorrectionStatus.APPROVED
    assert candidate.is_active is True
    assert db_session.query(RootCauseRevision).count() == revision_count


def test_new_analysis_overwrites_old_item_and_metric_analysis(
    db_session: Session,
) -> None:
    actor, _, run, item = _seed_run(db_session)
    old_change = apply_root_cause_change(
        db_session,
        run=run,
        item=item,
        actor_user_id=actor.id,
        actor_source="ai",
        next_state=build_ai_state(
            root_cause="Old Category",
            root_cause_detail="Old detail",
            root_cause_note="Old feedback",
            confidence=0.7,
        ),
    )
    old_candidate = old_change.candidate
    assert old_candidate is not None
    meta = dict(item.item_metadata)
    meta["metric_analyses"] = {
        "accuracy": {
            "source": "ai",
            "root_cause": "Old Category",
            "root_cause_detail": "Old detail",
            "root_cause_note": "Old feedback",
        }
    }
    item.item_metadata = meta
    db_session.commit()

    result = AnalysisResult(
        item_id=item.item_id,
        metric_name="accuracy",
        root_cause="Dataset Issue",
        root_cause_detail="Expected SQL mismatches request",
        root_cause_note="Fresh item-specific feedback",
        confidence=0.92,
    )
    _save_analysis_results(
        db_session,
        run,
        [(item, "accuracy")],
        [result],
        Principal(user=actor, auth_type="none"),
    )
    db_session.refresh(item)

    assert item.item_metadata["root_cause"] == "Dataset Issue"
    assert item.item_metadata["root_cause_detail"] == "Expected SQL mismatches request"
    assert item.item_metadata["root_cause_note"] == "Fresh item-specific feedback"
    metric_analysis = item.item_metadata["metric_analyses"]["accuracy"]
    assert metric_analysis["root_cause"] == "Dataset Issue"
    assert metric_analysis["root_cause_detail"] == "Expected SQL mismatches request"
    assert metric_analysis["root_cause_note"] == "Fresh item-specific feedback"
    db_session.refresh(old_candidate)
    assert old_candidate.is_active is False
    active_candidate = (
        db_session.query(ReviewCorrection)
        .filter(
            ReviewCorrection.run_id == run.id,
            ReviewCorrection.item_id == item.item_id,
            ReviewCorrection.is_active.is_(True),
        )
        .one()
    )
    assert active_candidate.metric_name == "accuracy"
    assert active_candidate.ai_root_cause == "Dataset Issue"
    assert active_candidate.ai_root_cause_detail == "Expected SQL mismatches request"


def test_save_analysis_results_preserves_human_metric_without_explicit_overwrite(
    db_session: Session,
) -> None:
    actor, _, run, item = _seed_run(db_session)
    human_analysis = {
        "source": "human",
        "root_cause": "Manual Category",
        "root_cause_detail": "Manual detail",
        "root_cause_note": "Keep this reviewer explanation.",
    }
    item.item_metadata = {
        "root_cause": "Legacy AI",
        "root_cause_source": "ai",
        "metric_analyses": {"accuracy": human_analysis},
    }
    db_session.commit()
    human_candidate = replace_metric_review_candidate(
        db_session,
        run=run,
        item=item,
        metric_name="accuracy",
        analysis=human_analysis,
        actor_user_id=actor.id,
        actor_source="human",
    )
    assert human_candidate is not None
    db_session.commit()

    result = AnalysisResult(
        item_id=item.item_id,
        metric_name="accuracy",
        root_cause="Fresh AI Category",
        root_cause_detail="Fresh AI detail",
        root_cause_note="Fresh AI note",
        confidence=0.92,
    )
    _save_analysis_results(
        db_session,
        run,
        [(item, "accuracy")],
        [result],
        Principal(user=actor, auth_type="none"),
    )
    db_session.refresh(item)
    db_session.refresh(human_candidate)

    assert item.item_metadata["metric_analyses"]["accuracy"] == human_analysis
    assert human_candidate.is_active is True
    assert human_candidate.human_root_cause == "Manual Category"

    _save_analysis_results(
        db_session,
        run,
        [(item, "accuracy")],
        [result],
        Principal(user=actor, auth_type="none"),
        allow_human_overwrite=True,
    )
    db_session.refresh(item)
    db_session.refresh(human_candidate)

    assert item.item_metadata["metric_analyses"]["accuracy"]["source"] == "ai"
    assert item.item_metadata["metric_analyses"]["accuracy"]["root_cause"] == (
        "Fresh AI Category"
    )
    assert human_candidate.is_active is False


def test_save_analysis_results_reloads_concurrent_human_metric_before_persisting(
    db_session: Session,
) -> None:
    actor, _, run, item = _seed_run(db_session)
    # Keep the AI session's item stale while a reviewer session commits a human
    # diagnosis, matching the state transition that can happen during an LLM call.
    assert item.item_metadata in (None, {})
    reviewer_session = sessionmaker(bind=db_session.get_bind())()
    try:
        reviewer_item = (
            reviewer_session.query(RunItem)
            .filter(RunItem.run_id == run.id, RunItem.item_id == item.item_id)
            .one()
        )
        human_analysis = {
            "source": "human",
            "root_cause": "Manual Category",
            "root_cause_detail": "Reviewer diagnosis committed during analysis",
        }
        reviewer_item.item_metadata = {
            "metric_analyses": {"accuracy": human_analysis}
        }
        reviewer_session.commit()
    finally:
        reviewer_session.close()

    result = AnalysisResult(
        item_id=item.item_id,
        metric_name="accuracy",
        root_cause="Fresh AI Category",
        root_cause_detail="Fresh AI detail",
        root_cause_note="Fresh AI note",
        confidence=0.92,
    )
    payloads, errors = _save_analysis_results(
        db_session,
        run,
        [(item, "accuracy")],
        [result],
        Principal(user=actor, auth_type="none"),
    )
    db_session.refresh(item)

    assert errors == 0
    assert payloads[0]["persistence_status"] == "skipped_human_protection"
    assert item.item_metadata["metric_analyses"]["accuracy"] == human_analysis


def test_save_analysis_results_does_not_replace_human_metric_with_ai_error(
    db_session: Session,
) -> None:
    actor, _, run, item = _seed_run(db_session)
    human_analysis = {
        "source": "human",
        "root_cause": "Manual Category",
        "root_cause_detail": "Keep the reviewer diagnosis on analyzer failure",
    }
    item.item_metadata = {"metric_analyses": {"accuracy": human_analysis}}
    db_session.commit()

    result = AnalysisResult(
        item_id=item.item_id,
        metric_name="accuracy",
        root_cause="",
        root_cause_note="",
        confidence=0.0,
        error="Analyzer request timed out",
    )
    payloads, errors = _save_analysis_results(
        db_session,
        run,
        [(item, "accuracy")],
        [result],
        Principal(user=actor, auth_type="none"),
    )
    db_session.refresh(item)

    assert errors == 0
    assert payloads[0]["persistence_status"] == "skipped_human_protection"
    assert item.item_metadata["metric_analyses"]["accuracy"] == human_analysis


def test_persisted_ai_labels_can_be_reaggregated_without_changing_feedback(
    db_session: Session,
) -> None:
    actor, _, run, item = _seed_run(db_session)
    item.item_metadata = {
        "root_cause": "Dataset Issue",
        "root_cause_detail": "Expected SQL uses non-SQLite function",
        "root_cause_note": "Feedback for the item-level analysis.",
        "solution": "Provide Schema Context",
        "solution_note": "Item-specific solution guidance.",
        "root_cause_source": "ai",
        "metric_analyses": {
            "accuracy": {
                "source": "ai",
                "root_cause": "Dataset Issue",
                "root_cause_detail": "Expected SQL uses MONTH() not in SQLite",
                "root_cause_note": "Feedback for the metric analysis.",
                "solution": "Attach Relevant Schema",
                "solution_note": "Metric-specific solution guidance.",
            }
        },
    }
    db_session.commit()

    bindings = _persisted_ai_analysis_bindings([item], [])
    assert len(bindings) == 1
    assert bindings[0].metric_name == "accuracy"
    for binding in bindings:
        binding.result.root_cause_detail = "Expected SQL uses non-SQLite functions"
        binding.result.solution = "Improve Retrieval Context"

    changed = _persist_aggregated_bindings(
        db_session,
        run,
        bindings,
        Principal(user=actor, auth_type="none"),
    )
    db_session.commit()
    db_session.refresh(item)

    assert changed == 1
    assert (
        item.item_metadata["root_cause_detail"]
        == "Expected SQL uses non-SQLite function"
    )
    assert (
        item.item_metadata["root_cause_note"] == "Feedback for the item-level analysis."
    )
    assert item.item_metadata["solution"] == "Provide Schema Context"
    assert item.item_metadata["solution_note"] == "Item-specific solution guidance."
    metric_analysis = item.item_metadata["metric_analyses"]["accuracy"]
    assert (
        metric_analysis["root_cause_detail"] == "Expected SQL uses non-SQLite functions"
    )
    assert metric_analysis["root_cause_note"] == "Feedback for the metric analysis."
    assert metric_analysis["solution"] == "Improve Retrieval Context"
    assert metric_analysis["solution_note"] == "Metric-specific solution guidance."


def test_persisted_aggregation_labels_respect_selected_metric_scope(
    db_session: Session,
) -> None:
    _, _, _, item = _seed_run(db_session)
    item.item_metadata = {
        "root_cause": "Legacy item diagnosis",
        "root_cause_source": "ai",
        "metric_analyses": {
            "accuracy": {"source": "ai", "root_cause": "Reasoning Error"},
            "format": {"source": "ai", "root_cause": "Wrong Format"},
        },
    }

    bindings = _persisted_ai_analysis_bindings(
        [item],
        [],
        metric_scope={"format"},
    )

    assert [
        (binding.metric_name, binding.result.root_cause) for binding in bindings
    ] == [("format", "Wrong Format")]


def test_persisted_aggregation_ignores_deleted_metric_legacy_summary(
    db_session: Session,
) -> None:
    _, _, _, item = _seed_run(db_session)
    item.item_metadata = {
        "root_cause": "Dataset Issue",
        "root_cause_detail": "Expected SQL mismatch",
        "root_cause_source": "ai",
        "root_cause_metric_name": "accuracy",
    }

    bindings = _persisted_ai_analysis_bindings([item], [])

    assert bindings == []


@pytest.mark.asyncio
async def test_zero_target_aggregation_is_a_noop_without_llm_calls(
    db_session: Session,
) -> None:
    actor, _reviewer, run, item = _seed_run(db_session)
    item.item_metadata = {
        "root_cause": "Reasoning Error",
        "root_cause_source": "ai",
    }
    db_session.commit()
    parse = AsyncMock()
    client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(parse=parse))
    )

    categories, changed = await _aggregate_run_analysis_results(
        db=db_session,
        run=run,
        all_items=[item],
        analysis_targets=[],
        new_results=[],
        client=client,
        model="test-model",
        analyzer_config=None,
        principal=Principal(user=actor, auth_type="none"),
    )

    assert categories == {"Reasoning Error": 1}
    assert changed == 0
    parse.assert_not_awaited()


@pytest.mark.asyncio
async def test_forced_aggregation_reprocesses_saved_labels_and_records_status(
    db_session: Session,
) -> None:
    actor, _reviewer, run, item = _seed_run(db_session)
    item.item_metadata = {
        "metric_analyses": {
            "accuracy": {
                "source": "ai",
                "root_cause": "Reasoning Error",
                "root_cause_detail": "Failure variant one",
            },
            "format": {
                "source": "ai",
                "root_cause": "Reasoning Error",
                "root_cause_detail": "Failure variant two",
            },
        }
    }
    db_session.commit()
    client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(
                parse=AsyncMock(
                    return_value=SimpleNamespace(
                        choices=[
                            SimpleNamespace(
                                message=SimpleNamespace(
                                    parsed=AggregationResponse.model_validate(
                                        {
                                            "category_clusters": [],
                                            "detail_clusters": [
                                                {
                                                    "canonical_label": (
                                                        "Shared failure mechanism"
                                                    ),
                                                    "member_ids": ["d0", "d1"],
                                                }
                                            ],
                                        }
                                    )
                                )
                            )
                        ]
                    )
                )
            )
        )
    )

    categories, changed = await _aggregate_run_analysis_results(
        db=db_session,
        run=run,
        all_items=[item],
        analysis_targets=[],
        new_results=[],
        client=client,
        model="test-model",
        analyzer_config={"root_cause_categories": ["Reasoning Error"]},
        principal=Principal(user=actor, auth_type="none"),
        force=True,
    )
    db_session.commit()
    db_session.refresh(item)
    db_session.refresh(run)

    assert categories == {"Reasoning Error": 2}
    assert changed == 2
    metric_analyses = item.item_metadata["metric_analyses"]
    assert {
        analysis["root_cause_detail"] for analysis in metric_analyses.values()
    } == {"Shared failure mechanism"}
    assert run.run_metadata["analysis_aggregation"]["status"] == "succeeded"
    assert run.run_metadata["analysis_aggregation"]["metrics"] is None
    assert run.run_metadata["analysis_aggregation"]["aggregated"] == 2


@pytest.mark.asyncio
async def test_forced_aggregation_skips_active_approved_metric_labels(
    db_session: Session,
) -> None:
    actor, reviewer, run, item = _seed_run(db_session)
    item.item_metadata = {
        "metric_analyses": {
            "accuracy": {
                "source": "ai",
                "root_cause": "Reasoning Error",
                "root_cause_detail": "Approved detail",
            }
        }
    }
    db_session.commit()

    candidate = replace_metric_review_candidate(
        db_session,
        run=run,
        item=item,
        metric_name="accuracy",
        analysis=item.item_metadata["metric_analyses"]["accuracy"],
        actor_user_id=actor.id,
        actor_source="ai",
    )
    assert candidate is not None
    db_session.flush()
    _approve_candidate(
        db_session,
        correction=candidate,
        reviewer_id=reviewer.id,
        comment="Keep approved diagnosis",
        reviewed_at=datetime.utcnow(),
    )
    db_session.commit()

    client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(parse=AsyncMock()))
    )
    categories, changed = await _aggregate_run_analysis_results(
        db=db_session,
        run=run,
        all_items=[item],
        analysis_targets=[],
        new_results=[],
        client=client,
        model="test-model",
        analyzer_config=None,
        principal=Principal(user=actor, auth_type="none"),
        force=True,
    )
    db_session.commit()
    db_session.refresh(item)
    db_session.refresh(candidate)

    assert categories == {}
    assert changed == 0
    assert item.item_metadata["metric_analyses"]["accuracy"]["root_cause_detail"] == (
        "Approved detail"
    )
    assert candidate.status == CorrectionStatus.APPROVED
    assert candidate.is_active is True
    client.chat.completions.parse.assert_not_awaited()


@pytest.mark.asyncio
async def test_failed_aggregation_restores_raw_new_labels(
    db_session: Session,
) -> None:
    actor, _reviewer, run, item = _seed_run(db_session)
    results = [
        AnalysisResult(
            item_id=item.item_id,
            metric_name="accuracy",
            root_cause="dataset",
            root_cause_note="first",
            confidence=0.8,
        ),
        AnalysisResult(
            item_id=item.item_id,
            metric_name="format",
            root_cause="datasets",
            root_cause_note="second",
            confidence=0.8,
        ),
    ]
    invalid_response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(parsed=None, refusal=None))]
    )
    client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(parse=AsyncMock(return_value=invalid_response))
        )
    )

    with pytest.raises(AnalysisAggregationError):
        await _aggregate_run_analysis_results(
            db=db_session,
            run=run,
            all_items=[item],
            analysis_targets=[(item, "accuracy"), (item, "format")],
            new_results=results,
            client=client,
            model="test-model",
            analyzer_config=None,
            principal=Principal(user=actor, auth_type="none"),
        )

    assert [result.root_cause for result in results] == ["dataset", "datasets"]


def test_analysis_rules_are_normalized_and_included_in_prompt() -> None:
    rules = normalize_analysis_rules(
        [
            {
                "title": "Schema semantics",
                "instruction": "Check joins against the documented entity keys.",
            },
            {"title": "Schema semantics", "instruction": "duplicate"},
            {"title": "", "instruction": "invalid"},
        ]
    )
    assert rules == [
        {
            "title": "Schema semantics",
            "instruction": "Check joins against the documented entity keys.",
        }
    ]
    item = RunItem(run_id="run-1", item_id="item-1", index=0, input={"question": "q"})
    messages = build_analysis_prompt(item, {}, [], config={"analysis_rules": rules})
    system_content = next(
        message["content"] for message in messages if message["role"] == "system"
    )

    assert "Schema semantics" in system_content
    assert "Check joins against the documented entity keys" in system_content
    assert "ANALYSIS RULES (diagnostic guidance for this root-cause analyzer):" in system_content
    assert (
        "1. Schema semantics\nCheck joins against the documented entity keys."
        in system_content
    )
    assert "diagnostic guidance for this root-cause analyzer" in system_content
    assert "not a judge rubric, pass/fail criteria" in system_content
    assert "classification aid" in system_content
    assert "signal-to-mechanism" in system_content
    assert "business requirements" in RULE_WRITER_SYSTEM_PROMPT
    assert "decision logic" in RULE_WRITER_SYSTEM_PROMPT
    assert "downstream LLM analyzer" in RULE_WRITER_SYSTEM_PROMPT
    assert (
        "must be reusable across multiple evaluation items" in RULE_WRITER_SYSTEM_PROMPT
    )
    assert "must not be item-specific" in RULE_WRITER_SYSTEM_PROMPT
    complete_writer_prompt = llm_analyzer_service._writer_system_instructions(None)
    assert "DIAGNOSTIC CLASSIFICATION CONTRACT" in complete_writer_prompt
    assert "classify the root cause" in complete_writer_prompt
    assert "conditional root-cause category" in complete_writer_prompt
    assert "make the analyzer the grammatical subject" in complete_writer_prompt
    assert "Do not write scoring criteria" in complete_writer_prompt
    assert (
        "operating instructions for the evaluated agent/model" in complete_writer_prompt
    )
    assert "remediation and prevention advice" in complete_writer_prompt
    assert "generalizable beyond the supplied examples" in complete_writer_prompt
    assert "must not be item-specific" in complete_writer_prompt
    assert "title and instruction" in complete_writer_prompt
    assert (
        "Return {\"rules\":[]} when the supplied data supports no generalizable rule."
        in complete_writer_prompt
    )

    more_than_twenty = normalize_analysis_rules(
        [
            {"title": f"Rule {index}", "instruction": f"Instruction {index}."}
            for index in range(21)
        ]
    )
    assert len(more_than_twenty) == 21


def test_rule_inference_metadata_is_validated_persisted_and_not_injected() -> None:
    source = "Approved policy excerpt: every answer must cite the retrieved record."
    explanation = (
        "This lets the analyzer distinguish an evidence gap from a reasoning error "
        "when the output omits a required citation."
    )
    rules = normalize_analysis_rules(
        [
            {
                "title": "Evidence grounding",
                "instruction": "Check whether the response connects its conclusion to retrieved evidence.",
                "inferred_from": source,
                "explanation": explanation,
            }
        ]
    )

    assert rules == [
        {
            "title": "Evidence grounding",
            "instruction": "Check whether the response connects its conclusion to retrieved evidence.",
            "inferred_from": source,
            "explanation": explanation,
        }
    ]
    model = AnalysisRule.model_validate(rules[0])
    assert model.inferred_from == source
    assert model.explanation == explanation

    item = RunItem(run_id="run-1", item_id="item-1", index=0, input={"question": "q"})
    messages = build_analysis_prompt(item, {}, [], config={"analysis_rules": rules})
    system_content = next(
        message["content"] for message in messages if message["role"] == "system"
    )
    assert "Evidence grounding" in system_content
    assert "Check whether the response connects its conclusion" in system_content
    assert source not in system_content
    assert explanation not in system_content
    complete_writer_prompt = llm_analyzer_service._writer_system_instructions(None)
    assert '"inferred_from"' in complete_writer_prompt
    assert '"explanation"' in complete_writer_prompt


def test_rule_writer_returns_inference_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    completion = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content=json.dumps(
                        {
                            "rules": [
                                {
                                    "title": "Evidence grounding",
                                    "instruction": "Compare conclusions with retrieved evidence.",
                                    "inferred_from": "The approved policy requires citations.",
                                    "explanation": "This helps localize unsupported conclusions.",
                                }
                            ]
                        }
                    )
                )
            )
        ]
    )
    monkeypatch.setattr(
        llm_analyzer_service,
        "create_chat_completion_compat",
        AsyncMock(return_value=completion),
    )

    rules = asyncio.run(
        llm_analyzer_service.infer_analysis_rules(
            SimpleNamespace(),
            "test-model",
            reference_documents=[
                {"name": "policy.md", "content": "The approved policy requires citations."}
            ],
            corrections=[],
        )
    )

    assert rules == [
        {
            "title": "Evidence grounding",
            "instruction": "Compare conclusions with retrieved evidence.",
            "inferred_from": "The approved policy requires citations.",
            "explanation": "This helps localize unsupported conclusions.",
        }
    ]


def test_rule_writer_rejects_generated_rules_without_audit_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    completion = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content=(
                        '{"rules":[{"title":"Evidence",'
                        '"instruction":"Check the evidence."}]}'
                    )
                )
            )
        ]
    )
    monkeypatch.setattr(
        llm_analyzer_service,
        "create_chat_completion_compat",
        AsyncMock(return_value=completion),
    )

    with pytest.raises(ValueError, match="did not contain usable rules"):
        asyncio.run(
            llm_analyzer_service.infer_analysis_rules(
                SimpleNamespace(),
                "test-model",
                reference_documents=[
                    {"name": "policy.md", "content": "Use the supplied evidence."}
                ],
                corrections=[],
            )
        )


def test_rule_writer_accepts_an_explicit_empty_rule_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    completion = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content='{"rules":[]}'))]
    )
    monkeypatch.setattr(
        llm_analyzer_service,
        "create_chat_completion_compat",
        AsyncMock(return_value=completion),
    )
    existing_rules = [
        {
            "id": "rule-existing",
            "title": "Evidence",
            "instruction": "Check the supplied evidence.",
        }
    ]

    rules = asyncio.run(
        llm_analyzer_service.infer_analysis_rules(
            SimpleNamespace(),
            "test-model",
            existing_rules=existing_rules,
            reference_documents=[
                {"name": "policy.md", "content": "No distinct new insight."}
            ],
            corrections=[],
        )
    )

    assert rules == existing_rules


def test_custom_rule_writer_prompt_keeps_classification_contract() -> None:
    messages = llm_analyzer_service._writer_messages(
        existing_rules=[],
        reference_documents=[
            {"name": "policy.md", "content": "The response must cite evidence."}
        ],
        correction_payload=[],
        system_prompt="Extract useful project rules.",
        update=False,
    )

    system_prompt = messages[0]["content"]
    assert system_prompt.startswith("Extract useful project rules.")
    assert "DIAGNOSTIC CLASSIFICATION CONTRACT" in system_prompt
    assert system_prompt.count("DIAGNOSTIC CLASSIFICATION CONTRACT") == 1
    assert "SOURCE HANDLING CONTRACT" in system_prompt
    assert "RULE WRITING CONTRACT" in system_prompt
    assert "classify the root cause" in system_prompt
    assert "inferred_from" in system_prompt
    legacy_prompt = (
        llm_analyzer_service.RULE_WRITER_SYSTEM_PROMPT
        + "\n\n"
        + llm_analyzer_service.RULE_WRITER_FIXED_CONTRACT
    )
    assert (
        llm_analyzer_service.normalize_rule_writer_system_prompt(legacy_prompt)
        == llm_analyzer_service.RULE_WRITER_SYSTEM_PROMPT
    )
    legacy_messages = llm_analyzer_service._writer_messages(
        existing_rules=[],
        reference_documents=[
            {"name": "policy.md", "content": "The response must cite evidence."}
        ],
        correction_payload=[],
        system_prompt=legacy_prompt,
        update=False,
    )
    assert (
        legacy_messages[0]["content"].count("DIAGNOSTIC CLASSIFICATION CONTRACT")
        == 1
    )


def test_all_approved_examples_are_returned_without_cap(
    db_session: Session,
) -> None:
    actor, reviewer, run, _ = _seed_run(db_session)
    corrections = []
    for index in range(25):
        corrections.append(
            ReviewCorrection(
                run_id=run.id,
                item_id=f"example-{index}",
                task=run.task,
                input_snapshot={
                    "question": (
                        f"Explain why record {index} failed the documented validation rule."
                    )
                },
                expected_snapshot={"answer": "A grounded English explanation."},
                output_snapshot={"answer": "An unsupported English explanation."},
                scores_snapshot={},
                ai_root_cause="Reasoning Error",
                human_root_cause="Reasoning Error",
                human_root_cause_detail="Unsupported conclusion",
                human_root_cause_note="The response did not cite the available evidence.",
                corrected_by_user_id=actor.id,
                reviewed_by_user_id=reviewer.id,
                status=CorrectionStatus.APPROVED,
                is_active=True,
            )
        )
    corrections.append(
        ReviewCorrection(
            run_id=run.id,
            item_id="spanish-example",
            task=run.task,
            input_snapshot={
                "question": (
                    "La respuesta ignoró el filtro solicitado y devolvió datos incorrectos."
                )
            },
            expected_snapshot=None,
            output_snapshot=None,
            scores_snapshot={},
            ai_root_cause="Reasoning Error",
            human_root_cause="Reasoning Error",
            corrected_by_user_id=actor.id,
            reviewed_by_user_id=reviewer.id,
            status=CorrectionStatus.APPROVED,
            is_active=True,
        )
    )
    db_session.add_all(corrections)
    db_session.commit()

    approved = get_all_approved_examples(
        db_session,
        task=run.task,
        project_id=run.project_id,
    )

    assert len(approved) == 26
    assert {correction.item_id for correction in approved} == {
        *(f"example-{index}" for index in range(25)),
        "spanish-example",
    }


def test_rule_writer_prompt_includes_every_approved_example(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    completion = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content=(
                        '{"rules":[{"title":"Evidence","instruction":'
                        '"Check every conclusion against the supplied evidence.",'
                        '"inferred_from":"Approved examples.",'
                        '"explanation":"The examples show an evidence gap."}]}'
                    )
                )
            )
        ]
    )
    create_completion = AsyncMock(return_value=completion)
    monkeypatch.setattr(
        llm_analyzer_service,
        "create_chat_completion_compat",
        create_completion,
    )
    corrections = [
        SimpleNamespace(
            input_snapshot={"question": f"English approved example {index}"},
            expected_snapshot={"answer": f"Expected {index}"},
            output_snapshot={"answer": f"Actual {index}"},
            ai_root_cause="Reasoning Error",
            human_root_cause="Reasoning Error",
            human_root_cause_detail=f"Evidence gap {index}",
            human_root_cause_note="The response was not supported by the evidence.",
            human_solution="Add validation",
            human_solution_note="Validate the answer against the retrieved context.",
        )
        for index in range(25)
    ]

    asyncio.run(
        llm_analyzer_service.infer_analysis_rules(
            SimpleNamespace(),
            "test-model",
            reference_documents=[],
            corrections=corrections,
        )
    )

    messages = create_completion.await_args.kwargs["messages"]
    assert "max_tokens" not in create_completion.await_args.kwargs
    assert "max_completion_tokens" not in create_completion.await_args.kwargs
    assert create_completion.await_args.kwargs["temperature"] == 0.0
    user_prompt = next(
        message["content"] for message in messages if message["role"] == "user"
    )
    assert "English approved example 0" in user_prompt
    assert "English approved example 24" in user_prompt
    assert user_prompt.count('"approved_root_cause"') == 25
    assert "Add validation" not in user_prompt
    assert "Validate the answer against the retrieved context." not in user_prompt
    assert '"approved_solution"' not in user_prompt

    payload = json.loads(user_prompt[user_prompt.index("{") :])
    example = payload["approved_correction_examples"][0]
    assert set(example) == {
        "input",
        "expected",
        "output",
        "previous_ai_root_cause",
        "previous_ai_root_causes",
        "previous_ai_root_cause_issues",
        "approved_root_cause",
        "approved_root_causes",
        "approved_root_cause_issues",
        "approved_detail",
        "reviewer_reasoning",
    }
    assert example["approved_root_causes"] == ["Reasoning Error"]
    assert example["approved_root_cause_issues"][0]["subcategory"] == "Evidence gap 0"
    assert "previous_ai_category_taxonomy" not in example
    assert "approved_category_taxonomy" not in example


def test_rule_writer_processes_large_example_bank_after_documents_in_patches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    completion = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content=(
                        '{"rules":[{"title":"Evidence","instruction":'
                        '"Check the supplied evidence.",'
                        '"inferred_from":"Supplied project data.",'
                        '"explanation":"The source establishes an evidence requirement."}]}'
                    )
                )
            )
        ]
    )
    create_completion = AsyncMock(return_value=completion)
    monkeypatch.setattr(
        llm_analyzer_service,
        "create_chat_completion_compat",
        create_completion,
    )
    corrections = [
        SimpleNamespace(
            input_snapshot={"question": f"Approved example {index}"},
            expected_snapshot={"answer": f"Expected {index}"},
            output_snapshot={"answer": f"Actual {index}"},
            ai_root_cause="Reasoning Error",
            human_root_cause="Reasoning Error",
            human_root_cause_detail=f"Evidence gap {index}",
            human_root_cause_note="n" * 800,
        )
        for index in range(220)
    ]
    stats: dict[str, Any] = {}

    asyncio.run(
        llm_analyzer_service.infer_analysis_rules(
            SimpleNamespace(),
            "test-model",
            reference_documents=[
                {"name": "rubric.md", "content": "Use the supplied evidence."}
            ],
            corrections=corrections,
            stats=stats,
        )
    )

    assert stats["document_patches"] == 1
    assert stats["approved_example_patches"] > 1
    assert stats["writer_calls"] == 1 + stats["approved_example_patches"]
    assert stats["patching_used"] is True
    assert all(
        patch["prompt_characters"]
        <= llm_analyzer_service.MAX_RULE_WRITER_PROMPT_CHARS
        for patch in stats["patches"]
    )

    payloads = []
    for call in create_completion.await_args_list:
        user_prompt = next(
            message["content"]
            for message in call.kwargs["messages"]
            if message["role"] == "user"
        )
        payloads.append(json.loads(user_prompt[user_prompt.index("{") :]))
    assert payloads[0]["reference_documents"]
    assert payloads[0]["approved_correction_examples"] == []
    assert all(not payload["reference_documents"] for payload in payloads[1:])
    assert sum(
        len(payload["approved_correction_examples"]) for payload in payloads
    ) == len(corrections)


def test_rule_writer_carries_generated_rules_into_later_patches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(llm_analyzer_service, "MAX_RULE_WRITER_DOCUMENT_CHARS", 12)
    completions = [
        SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content=json.dumps(
                            {
                                "rules": [
                                    {
                                        "title": "First patch rule",
                                        "instruction": "Use the first source signal.",
                                        "inferred_from": "First document part.",
                                        "explanation": "It establishes the first signal.",
                                    }
                                ]
                            }
                        )
                    )
                )
            ]
        ),
        SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content=json.dumps(
                            {
                                "rules": [
                                    {
                                        "title": "Second patch rule",
                                        "instruction": "Use the second source signal.",
                                        "inferred_from": "Second document part.",
                                        "explanation": "It establishes a distinct signal.",
                                    }
                                ]
                            }
                        )
                    )
                )
            ]
        ),
    ]
    create_completion = AsyncMock(side_effect=completions)
    monkeypatch.setattr(
        llm_analyzer_service,
        "create_chat_completion_compat",
        create_completion,
    )
    stats: dict[str, Any] = {}

    rules = asyncio.run(
        llm_analyzer_service.infer_analysis_rules(
            SimpleNamespace(),
            "test-model",
            reference_documents=[
                {"name": "policy.md", "content": "first-part--second-part"}
            ],
            corrections=[],
            stats=stats,
        )
    )

    assert [rule["title"] for rule in rules] == [
        "First patch rule",
        "Second patch rule",
    ]
    second_user_prompt = create_completion.await_args_list[1].kwargs["messages"][1][
        "content"
    ]
    second_payload = json.loads(second_user_prompt[second_user_prompt.index("{") :])
    assert [rule["title"] for rule in second_payload["existing_rules"]] == [
        "First patch rule"
    ]
    assert stats["patching_used"] is True


@pytest.mark.parametrize(
    "content",
    [
        (
            "Here is the ruleset:\n```json\n"
            '{"rules":[{"title":"Evidence","instruction":"Check the evidence.",'
            '"inferred_from":"Evidence policy.",'
            '"explanation":"It identifies unsupported conclusions."}]}\n'
            "```"
        ),
        (
            '[{"title":"Evidence","instruction":"Check the evidence.",'
            '"inferred_from":"Evidence policy.",'
            '"explanation":"It identifies unsupported conclusions."}]'
        ),
        (
            "```python\n"
            "{'analysis_rules': [{'title': 'Evidence', "
            "'instruction': 'Check the evidence.', "
            "'inferred_from': 'Evidence policy.', "
            "'explanation': 'It identifies unsupported conclusions.'}]}\n```"
        ),
        [
            {
                "type": "text",
                "text": (
                    '{"rules":[{"title":"Evidence",'
                    '"instruction":"Check the evidence.",'
                    '"inferred_from":"Evidence policy.",'
                    '"explanation":"It identifies unsupported conclusions."}]}'
                ),
            }
        ],
    ],
)
def test_rule_writer_accepts_compatible_provider_output_shapes(
    monkeypatch: pytest.MonkeyPatch,
    content: Any,
) -> None:
    completion = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
    )
    monkeypatch.setattr(
        llm_analyzer_service,
        "create_chat_completion_compat",
        AsyncMock(return_value=completion),
    )

    rules = asyncio.run(
        llm_analyzer_service.infer_analysis_rules(
            SimpleNamespace(),
            "test-model",
            reference_documents=[
                {"name": "Evidence policy", "content": "Use the supplied evidence."}
            ],
            corrections=[],
        )
    )

    assert rules == [
        {
            "title": "Evidence",
            "instruction": "Check the evidence.",
            "inferred_from": "Evidence policy.",
            "explanation": "It identifies unsupported conclusions.",
        }
    ]


def test_rule_writer_uses_reasoning_when_content_is_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    completion = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content="",
                    reasoning=(
                        '{"rules":[{"title":"Evidence",'
                        '"instruction":"Check the evidence.",'
                        '"inferred_from":"Evidence policy.",'
                        '"explanation":"It identifies unsupported conclusions."}]}'
                    ),
                )
            )
        ]
    )
    monkeypatch.setattr(
        llm_analyzer_service,
        "create_chat_completion_compat",
        AsyncMock(return_value=completion),
    )

    rules = asyncio.run(
        llm_analyzer_service.infer_analysis_rules(
            SimpleNamespace(),
            "test-model",
            reference_documents=[
                {"name": "Evidence policy", "content": "Use the supplied evidence."}
            ],
            corrections=[],
        )
    )

    assert rules[0]["title"] == "Evidence"


def test_rule_updater_preserves_existing_ids_and_allows_add_edit_delete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    completion = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content=json.dumps(
                        {
                            "rules": [
                                {
                                    "id": "rule-keep",
                                    "title": "Renamed evidence rule",
                                    "instruction": "Use the updated evidence policy.",
                                    "inferred_from": "Existing approved policy excerpt.",
                                    "explanation": "It helps explain unsupported conclusions.",
                                },
                                {
                                    "title": "New rule",
                                    "instruction": "Use the new project requirement.",
                                    "inferred_from": "New project requirement.",
                                    "explanation": "It supplies a new diagnostic signal.",
                                },
                            ]
                        }
                    )
                )
            )
        ]
    )
    create_completion = AsyncMock(return_value=completion)
    monkeypatch.setattr(
        llm_analyzer_service,
        "create_chat_completion_compat",
        create_completion,
    )

    rules = asyncio.run(
        llm_analyzer_service.update_analysis_rules(
            SimpleNamespace(),
            "test-model",
            existing_rules=[
                {
                    "id": "rule-keep",
                    "title": "Evidence",
                    "instruction": "Use the evidence.",
                    "inferred_from": "Existing approved policy excerpt.",
                    "explanation": "It helps explain unsupported conclusions.",
                },
                {
                    "id": "rule-delete",
                    "title": "Stale",
                    "instruction": "Remove this stale rule.",
                },
            ],
            reference_documents=[
                {"name": "Evidence policy", "content": "Use the supplied evidence."}
            ],
            corrections=[],
        )
    )

    assert rules == [
        {
            "id": "rule-keep",
            "title": "Renamed evidence rule",
            "instruction": "Use the updated evidence policy.",
            "inferred_from": "Existing approved policy excerpt.",
            "explanation": "It helps explain unsupported conclusions.",
        },
        {
            "title": "New rule",
            "instruction": "Use the new project requirement.",
            "inferred_from": "New project requirement.",
            "explanation": "It supplies a new diagnostic signal.",
        },
    ]
    system_prompt = create_completion.await_args.kwargs["messages"][0]["content"]
    assert "Preserve the exact id" in system_prompt
    user_prompt = create_completion.await_args.kwargs["messages"][1]["content"]
    assert "rule-delete" in user_prompt


def test_rule_generator_appends_only_distinct_rules_and_preserves_existing_rules(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    completion = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content=json.dumps(
                        {
                            "rules": [
                                {
                                    "id": "rule-existing",
                                    "title": "Renamed evidence rule",
                                    "instruction": "A revised instruction.",
                                    "inferred_from": "Existing policy excerpt.",
                                    "explanation": "Existing audit explanation.",
                                },
                                {
                                    "title": "Evidence",
                                    "instruction": "Repeat the existing evidence check.",
                                    "inferred_from": "Existing policy excerpt.",
                                    "explanation": "Existing audit explanation.",
                                },
                                {
                                    "title": "New diagnostic signal",
                                    "instruction": "Use the new project requirement as a distinct diagnostic signal.",
                                    "inferred_from": "New project requirement.",
                                    "explanation": "It adds a distinct classification signal.",
                                },
                            ]
                        }
                    )
                )
            )
        ]
    )
    create_completion = AsyncMock(return_value=completion)
    monkeypatch.setattr(
        llm_analyzer_service,
        "create_chat_completion_compat",
        create_completion,
    )
    existing_rules = [
        {
            "id": "rule-existing",
            "title": "Evidence",
            "instruction": "Use the supplied evidence.",
            "inferred_from": "Existing policy excerpt.",
            "explanation": "Existing audit explanation.",
        }
    ]

    rules = asyncio.run(
        llm_analyzer_service.generate_analysis_rules(
            SimpleNamespace(),
            "test-model",
            existing_rules=existing_rules,
            reference_documents=[
                {"name": "policy.md", "content": "Use the new project requirement."}
            ],
            corrections=[],
        )
    )

    assert rules[0] == existing_rules[0]
    assert rules[1:] == [
        {
            "title": "New diagnostic signal",
            "instruction": "Use the new project requirement as a distinct diagnostic signal.",
            "inferred_from": "New project requirement.",
            "explanation": "It adds a distinct classification signal.",
        }
    ]
    system_prompt = create_completion.await_args.kwargs["messages"][0]["content"]
    assert "existing rules" in system_prompt
    assert "immutable" in system_prompt
    user_prompt = create_completion.await_args.kwargs["messages"][1]["content"]
    assert '"existing_rules"' in user_prompt
    assert "Existing policy excerpt." in user_prompt


@pytest.mark.parametrize("publish_before_generate", [False, True])
def test_project_rule_generation_is_append_only_for_drafts_and_published_versions(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    publish_before_generate: bool,
) -> None:
    _, manager, run, _ = _seed_run(db_session)
    principal = Principal(user=manager, auth_type="session")
    created = update_analysis_context(
        run.id,
        AnalysisContextUpdate(
            analysis_rules=[
                AnalyzerRuleConfig(
                    title="Evidence",
                    instruction="Use the supplied evidence.",
                )
            ]
        ),
        db_session,
        principal,
    )
    original_rules = [dict(rule) for rule in created["analysis_rules"]]
    target_version_id = created["rule_version"]["id"]
    if publish_before_generate:
        published = publish_project_analysis_rule_version(
            run.id,
            created["rule_version"]["id"],
            AnalysisRuleVersionPublish(set_alias="production"),
            db_session,
            principal,
        )
        target_version_id = published["version"]["id"]

    db_session.add(
        AnalyzerDocument(
            project_id=run.project_id,
            uploaded_by_user_id=manager.id,
            name="policy.md",
            content="Use the new project requirement.",
            characters=len("Use the new project requirement."),
            enabled=True,
        )
    )
    db_session.commit()

    monkeypatch.setattr(
        analysis_api,
        "_get_llm_config",
        lambda *_args, **_kwargs: {"llm_model": "test-model"},
    )
    monkeypatch.setattr(analysis_api, "build_client", lambda *_args: object())
    generated = AsyncMock(
        return_value=[
            {
                **original_rules[0],
                "title": "Changed evidence title",
                "instruction": "Changed evidence instruction.",
            },
            {
                "title": "New diagnostic signal",
                "instruction": "Use the new project requirement as a diagnostic signal.",
            },
        ]
    )
    monkeypatch.setattr(analysis_api, "infer_analysis_rules", generated)

    result = asyncio.run(
        infer_project_analysis_rules(
            run.id,
            RuleInferenceRequest(
                include_documents=True,
                include_examples=False,
                mode="update",
                rule_version_id=target_version_id,
            ),
            db_session,
            principal,
        )
    )

    assert generated.await_args.kwargs["existing_rules"] == original_rules
    assert result["mode"] == "generate"
    assert result["generated_rule_count"] == 1
    assert result["changes"] == {
        "added": 1,
        "removed": 0,
        "changed": 0,
        "unchanged": 1,
    }
    assert result["analysis_rules"][0] == original_rules[0]
    assert result["analysis_rules"][1]["title"] == "New diagnostic signal"

    if publish_before_generate:
        assert result["created_new_version"] is True
        assert result["rule_version"]["id"] != target_version_id
        assert result["rule_version"]["parent_version_id"] == target_version_id
        published_version = db_session.get(
            ProjectAnalysisRuleVersion, target_version_id
        )
        assert published_version is not None
        assert published_version.rules == original_rules
    else:
        assert result["created_new_version"] is False
        assert result["rule_version"]["id"] == target_version_id
        assert (
            db_session.query(ProjectAnalysisRuleVersion).count()
            == 1
        )


def test_analysis_context_can_edit_and_add_rules_beyond_twenty(
    db_session: Session,
) -> None:
    _, manager, run, _ = _seed_run(db_session)
    principal = Principal(user=manager, auth_type="session")
    initial_rules = [
        AnalyzerRuleConfig(
            title=f"Rule {index}",
            instruction=f"Check requirement {index}.",
        )
        for index in range(21)
    ]

    created = update_analysis_context(
        run.id,
        AnalysisContextUpdate(
            project_description="Test project",
            analysis_rules=initial_rules,
        ),
        db_session,
        principal,
    )

    assert len(created["analysis_rules"]) == 21

    edited_rules = [
        AnalyzerRuleConfig(
            id=rule["id"],
            title=rule["title"],
            instruction=(
                "Check the updated requirement."
                if index == 0
                else rule["instruction"]
            ),
        )
        for index, rule in enumerate(created["analysis_rules"])
    ]
    edited_rules.append(
        AnalyzerRuleConfig(
            title="New rule",
            instruction="Check the newly added requirement.",
        )
    )

    updated = update_analysis_context(
        run.id,
        AnalysisContextUpdate(
            project_description="Test project",
            rule_version_id=created["rule_version"]["id"],
            analysis_rules=edited_rules,
        ),
        db_session,
        principal,
    )

    assert len(updated["analysis_rules"]) == 22
    assert updated["analysis_rules"][0] == {
        "id": created["analysis_rules"][0]["id"],
        "title": "Rule 0",
        "instruction": "Check the updated requirement.",
    }
    assert updated["analysis_rules"][-1]["title"] == "New rule"


def test_project_analysis_rule_versions_follow_draft_publish_production_lifecycle(
    db_session: Session,
) -> None:
    _, manager, run, _ = _seed_run(db_session)
    manager_principal = Principal(user=manager, auth_type="session")

    first = update_analysis_context(
        run.id,
        AnalysisContextUpdate(
            project_description="Test project",
            analysis_rules=[
                AnalyzerRuleConfig(
                    title="Grounding",
                    instruction="Reject claims unsupported by the supplied context.",
                )
            ],
        ),
        db_session,
        manager_principal,
    )
    assert first["rule_version"]["version"] == 1
    assert first["rule_version"]["name"] == "v1"
    assert first["rule_version"]["status"] == "draft"
    assert first["rule_version"]["is_active"] is False
    assert first["rule_version"]["created_by"] == {
        "id": manager.id,
        "display_name": "user2",
    }
    assert first["rule_version"]["created_at"]
    assert first["rule_version"]["updated_at"]

    with pytest.raises(HTTPException) as draft_alias:
        activate_project_analysis_rule_version(
            run.id,
            first["rule_version"]["id"],
            db_session,
            manager_principal,
        )
    assert draft_alias.value.status_code == 409

    published = publish_project_analysis_rule_version(
        run.id,
        "v1",
        AnalysisRuleVersionPublish(set_alias="production"),
        db_session,
        manager_principal,
    )
    assert published["version"]["status"] == "published"
    assert published["version"]["is_active"] is True
    assert "production" in published["version"]["aliases"]
    assert published["version"]["content_hash"]

    with pytest.raises(HTTPException) as immutable:
        update_analysis_context(
            run.id,
            AnalysisContextUpdate(
                project_description="Test project",
                analysis_rules=[
                    AnalyzerRuleConfig(
                        title="Changed",
                        instruction="Published rules must remain unchanged.",
                    )
                ],
                rule_version_id=first["rule_version"]["id"],
            ),
            db_session,
            manager_principal,
        )
    assert immutable.value.status_code == 409

    second = create_project_analysis_rule_version(
        run.id,
        AnalysisRuleVersionCreate(from_version="production"),
        db_session,
        manager_principal,
    )
    assert second["version"]["version"] == 2
    assert second["version"]["name"] == "v2"
    assert second["version"]["status"] == "draft"
    assert second["version"]["parent_version_id"] == first["rule_version"]["id"]
    original_rule_id = second["version"]["rules"][0]["id"]

    updated = update_analysis_context(
        run.id,
        AnalysisContextUpdate(
            project_description="Test project",
            rule_version_id=second["version"]["id"],
            analysis_rules=[
                AnalyzerRuleConfig(
                    id=original_rule_id,
                    title="Grounding",
                    instruction="Use only evidence supplied with the current item.",
                ),
                AnalyzerRuleConfig(
                    title="Read-only SQL",
                    instruction="Treat data-changing SQL as an instruction-following failure.",
                ),
            ],
        ),
        db_session,
        manager_principal,
    )
    assert updated["analysis_rules"][0]["id"] == original_rule_id

    comparison = compare_project_analysis_rule_versions(
        run.id,
        "v2",
        "v1",
        db_session,
        manager_principal,
    )
    assert comparison["summary"] == {
        "added": 1,
        "removed": 0,
        "changed": 1,
        "unchanged": 0,
    }


def test_publishing_without_promotion_keeps_existing_production(
    db_session: Session,
) -> None:
    _, manager, run, _ = _seed_run(db_session)
    manager_principal = Principal(user=manager, auth_type="session")
    first = update_analysis_context(
        run.id,
        AnalysisContextUpdate(
            project_description="Test project",
            analysis_rules=[
                AnalyzerRuleConfig(
                    title="Evidence",
                    instruction="Use the current item evidence.",
                )
            ],
        ),
        db_session,
        manager_principal,
    )
    publish_project_analysis_rule_version(
        run.id,
        "v1",
        AnalysisRuleVersionPublish(set_alias="production"),
        db_session,
        manager_principal,
    )
    second = create_project_analysis_rule_version(
        run.id,
        AnalysisRuleVersionCreate(from_version="production"),
        db_session,
        manager_principal,
    )
    publish_project_analysis_rule_version(
        run.id,
        "v2",
        AnalysisRuleVersionPublish(),
        db_session,
        manager_principal,
    )
    history = list_project_analysis_rule_versions(
        run.id, False, db_session, manager_principal
    )
    assert history["production_version_id"] == first["rule_version"]["id"]
    assert second["version"]["id"] != history["production_version_id"]


def test_run_owner_can_delete_analysis_rule_version(
    db_session: Session,
) -> None:
    actor, _manager, run, _ = _seed_run(db_session)
    version = _create_analysis_rule_version(
        db_session,
        project_id=run.project_id,
        rules=[{"title": "Evidence", "instruction": "Use supplied evidence."}],
        source="manual",
        actor_user_id=actor.id,
        force_new=True,
    )
    _create_analysis_rule_version(
        db_session,
        project_id=run.project_id,
        rules=[{"title": "Keep", "instruction": "Keep one version alive."}],
        source="manual",
        actor_user_id=actor.id,
        force_new=True,
        parent=version,
    )
    db_session.commit()

    history = list_project_analysis_rule_versions(
        run.id,
        False,
        db_session,
        Principal(user=actor, auth_type="session"),
    )
    assert history["can_delete"] is True

    deleted = delete_project_analysis_rule_version(
        run.id,
        version.id,
        db_session,
        Principal(user=actor, auth_type="session"),
    )

    assert deleted["deleted_version_id"] == version.id
    assert db_session.get(ProjectAnalysisRuleVersion, version.id) is None


def test_rule_version_merge_previews_conflicts_and_merges_into_draft(
    db_session: Session,
) -> None:
    _, manager, run, _ = _seed_run(db_session)
    principal = Principal(user=manager, auth_type="session")
    base_payload = update_analysis_context(
        run.id,
        AnalysisContextUpdate(
            project_description="Test project",
            analysis_rules=[
                AnalyzerRuleConfig(
                    title="Evidence",
                    instruction="Use the supplied evidence.",
                )
            ],
        ),
        db_session,
        principal,
    )
    base_version = base_payload["rule_version"]
    publish_project_analysis_rule_version(
        run.id,
        str(base_version["version"]),
        AnalysisRuleVersionPublish(set_alias="production"),
        db_session,
        principal,
    )
    target_payload = create_project_analysis_rule_version(
        run.id,
        AnalysisRuleVersionCreate(from_version=str(base_version["version"])),
        db_session,
        principal,
    )
    source_payload = create_project_analysis_rule_version(
        run.id,
        AnalysisRuleVersionCreate(from_version=str(base_version["version"])),
        db_session,
        principal,
    )
    rule_id = base_version["rules"][0]["id"]
    target_id = target_payload["version"]["id"]
    source_id = source_payload["version"]["id"]
    update_analysis_context(
        run.id,
        AnalysisContextUpdate(
            project_description="Test project",
            rule_version_id=target_id,
            analysis_rules=[
                AnalyzerRuleConfig(
                    id=rule_id,
                    title="Evidence",
                    instruction="Use target evidence.",
                ),
                AnalyzerRuleConfig(
                    title="Target only",
                    instruction="Preserve the target branch rule.",
                ),
            ],
        ),
        db_session,
        principal,
    )
    update_analysis_context(
        run.id,
        AnalysisContextUpdate(
            project_description="Test project",
            rule_version_id=source_id,
            analysis_rules=[
                AnalyzerRuleConfig(
                    id=rule_id,
                    title="Evidence",
                    instruction="Use incoming evidence.",
                ),
                AnalyzerRuleConfig(
                    title="Source only",
                    instruction="Bring in the source branch rule.",
                ),
            ],
        ),
        db_session,
        principal,
    )

    preview = merge_project_analysis_rule_versions(
        run.id,
        target_id,
        AnalysisRuleMergeRequest(source_version=source_id),
        db_session,
        principal,
    )["preview"]

    assert preview["base_version_id"] == base_version["id"]
    assert preview["summary"]["conflicts"] == 1
    conflict_key = preview["conflicts"][0]["key"]

    merged = merge_project_analysis_rule_versions(
        run.id,
        target_id,
        AnalysisRuleMergeRequest(
            source_version=source_id,
            apply=True,
            resolutions={conflict_key: "source"},
        ),
        db_session,
        principal,
    )

    assert merged["version"]["id"] == target_id
    assert merged["merge"]["created_new_draft"] is False
    assert {
        rule["title"]: rule["instruction"] for rule in merged["version"]["rules"]
    } == {
        "Evidence": "Use incoming evidence.",
        "Target only": "Preserve the target branch rule.",
        "Source only": "Bring in the source branch rule.",
    }
    assert (
        db_session.query(ProjectAnalysisRuleMergeParent)
        .filter(
            ProjectAnalysisRuleMergeParent.version_id == target_id,
            ProjectAnalysisRuleMergeParent.parent_version_id == source_id,
        )
        .one_or_none()
        is not None
    )


def test_merging_into_published_rule_version_creates_child_draft(
    db_session: Session,
) -> None:
    _, manager, run, _ = _seed_run(db_session)
    principal = Principal(user=manager, auth_type="session")
    base_payload = update_analysis_context(
        run.id,
        AnalysisContextUpdate(
            project_description="Test project",
            analysis_rules=[
                AnalyzerRuleConfig(title="Base", instruction="Base instruction.")
            ],
        ),
        db_session,
        principal,
    )
    base_id = base_payload["rule_version"]["id"]
    publish_project_analysis_rule_version(
        run.id,
        str(base_payload["rule_version"]["version"]),
        AnalysisRuleVersionPublish(set_alias="production"),
        db_session,
        principal,
    )
    source_payload = create_project_analysis_rule_version(
        run.id,
        AnalysisRuleVersionCreate(from_version=str(base_payload["rule_version"]["version"])),
        db_session,
        principal,
    )
    source_id = source_payload["version"]["id"]
    base_rule_id = base_payload["rule_version"]["rules"][0]["id"]
    update_analysis_context(
        run.id,
        AnalysisContextUpdate(
            project_description="Test project",
            rule_version_id=source_id,
            analysis_rules=[
                AnalyzerRuleConfig(
                    id=base_rule_id,
                    title="Base",
                    instruction="Updated on the source branch.",
                )
            ],
        ),
        db_session,
        principal,
    )

    merged = merge_project_analysis_rule_versions(
        run.id,
        base_id,
        AnalysisRuleMergeRequest(source_version=source_id, apply=True),
        db_session,
        principal,
    )

    assert merged["version"]["id"] not in {base_id, source_id}
    assert merged["version"]["status"] == "draft"
    assert merged["version"]["parent_version_id"] == base_id
    assert merged["merge"]["created_new_draft"] is True
    assert merged["version"]["rules"][0]["instruction"] == "Updated on the source branch."
    assert db_session.get(ProjectAnalysisRuleVersion, base_id).status.value == "published"


def test_deleting_production_rule_uses_another_non_deleted_published_version(
    db_session: Session,
) -> None:
    _, manager, run, _ = _seed_run(db_session)
    principal = Principal(user=manager, auth_type="session")
    first = update_analysis_context(
        run.id,
        AnalysisContextUpdate(
            project_description="Test project",
            analysis_rules=[
                AnalyzerRuleConfig(title="First", instruction="First rule.")
            ],
        ),
        db_session,
        principal,
    )
    publish_project_analysis_rule_version(
        run.id,
        "v1",
        AnalysisRuleVersionPublish(set_alias="production"),
        db_session,
        principal,
    )
    second = create_project_analysis_rule_version(
        run.id,
        AnalysisRuleVersionCreate(from_version="v1"),
        db_session,
        principal,
    )
    publish_project_analysis_rule_version(
        run.id,
        "v2",
        AnalysisRuleVersionPublish(),
        db_session,
        principal,
    )

    deleted = delete_project_analysis_rule_version(
        run.id, first["rule_version"]["id"], db_session, principal
    )

    assert deleted["active_version"]["id"] == second["version"]["id"]
    assert (
        db_session.get(
            ProjectAnalysisRuleVersion,
            first["rule_version"]["id"],
        )
        is None
    )
    remaining = db_session.get(ProjectAnalysisRuleVersion, second["version"]["id"])
    assert remaining is not None
    assert remaining.parent_version_id is None
    assert remaining.base_version_id is None
    assert (
        db_session.query(ProjectAnalysisRuleAlias)
        .filter(
            ProjectAnalysisRuleAlias.project_id == run.project_id,
            ProjectAnalysisRuleAlias.alias == "production",
        )
        .first()
        is None
    )
    assert (
        _resolve_analysis_rule_version(db_session, run.project_id, "production").id
        == second["version"]["id"]
    )


def test_deleted_draft_is_removed_and_cannot_be_resolved_or_edited(
    db_session: Session,
) -> None:
    _, manager, run, _ = _seed_run(db_session)
    principal = Principal(user=manager, auth_type="session")
    created = update_analysis_context(
        run.id,
        AnalysisContextUpdate(
            project_description="Test project",
            analysis_rules=[AnalyzerRuleConfig(title="Draft", instruction="Draft rule.")],
        ),
        db_session,
        principal,
    )
    version_id = created["rule_version"]["id"]
    version = db_session.get(ProjectAnalysisRuleVersion, version_id)
    assert version is not None
    _create_analysis_rule_version(
        db_session,
        project_id=run.project_id,
        rules=[{"title": "Keep", "instruction": "Keep one version alive."}],
        source="manual",
        actor_user_id=manager.id,
        force_new=True,
        parent=version,
    )
    db_session.commit()
    delete_project_analysis_rule_version(run.id, version_id, db_session, principal)
    assert db_session.get(ProjectAnalysisRuleVersion, version_id) is None

    with pytest.raises(HTTPException) as resolve_error:
        _resolve_analysis_rule_version(db_session, run.project_id, version_id)
    assert resolve_error.value.status_code == 404

    with pytest.raises(HTTPException) as update_error:
        update_analysis_context(
            run.id,
            AnalysisContextUpdate(
                project_description="Test project",
                rule_version_id=version_id,
                analysis_rules=[
                    AnalyzerRuleConfig(title="Changed", instruction="Must not save.")
                ],
            ),
            db_session,
            principal,
        )
    assert update_error.value.status_code == 404


def test_last_live_rule_version_cannot_be_deleted(db_session: Session) -> None:
    actor, manager, run, _ = _seed_run(db_session)
    version = _create_analysis_rule_version(
        db_session,
        project_id=run.project_id,
        rules=[{"title": "Required", "instruction": "Keep this version."}],
        source="manual",
        actor_user_id=actor.id,
        force_new=True,
    )
    db_session.commit()

    with pytest.raises(HTTPException) as exc_info:
        delete_project_analysis_rule_version(
            run.id,
            version.id,
            db_session,
            Principal(user=manager, auth_type="session"),
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "At least one rule version must remain"
    assert db_session.get(ProjectAnalysisRuleVersion, version.id) is not None


def test_permanent_rule_deletion_returns_conflict_when_referenced(
    db_session: Session,
) -> None:
    actor, manager, run, _ = _seed_run(db_session)
    manager.role = UserRole.ADMIN
    principal = Principal(user=manager, auth_type="session")
    parent = _create_analysis_rule_version(
        db_session,
        project_id=run.project_id,
        rules=[{"title": "Parent", "instruction": "Parent rule."}],
        source="manual",
        actor_user_id=actor.id,
    )
    child = _create_analysis_rule_version(
        db_session,
        project_id=run.project_id,
        rules=[{"title": "Child", "instruction": "Child rule."}],
        source="manual",
        actor_user_id=actor.id,
        force_new=True,
        parent=parent,
    )
    parent.deleted_at = datetime.utcnow()
    db_session.commit()

    with pytest.raises(HTTPException) as exc_info:
        permanently_delete_project_analysis_rule_version(
            run.id, parent.id, db_session, principal
        )

    assert exc_info.value.status_code == 409
    assert "descendant versions" in str(exc_info.value.detail)
    assert db_session.get(ProjectAnalysisRuleVersion, child.id) is not None


def test_item_level_change_preserves_metric_specific_candidates(
    db_session: Session,
) -> None:
    actor, _, run, item = _seed_run(db_session)
    metric_candidate = ReviewCorrection(
        run_id=run.id,
        item_id=item.item_id,
        metric_name="accuracy",
        task=run.task,
        ai_root_cause="Metric-only cause",
        human_root_cause="",
        is_active=True,
        status=CorrectionStatus.PENDING,
    )
    db_session.add(metric_candidate)
    db_session.commit()

    apply_root_cause_change(
        db_session,
        run=run,
        item=item,
        actor_user_id=actor.id,
        actor_source="human",
        human_patch={"root_cause": "Item-level cause"},
    )
    db_session.commit()
    db_session.refresh(metric_candidate)

    assert metric_candidate.is_active is True
    assert metric_candidate.status == CorrectionStatus.PENDING


def test_identical_analysis_rules_do_not_create_duplicate_version(
    db_session: Session,
) -> None:
    _, manager, run, _ = _seed_run(db_session)
    request = AnalysisContextUpdate(
        project_description="Test project",
        analysis_rules=[
            AnalyzerRuleConfig(
                title="Evidence",
                instruction="Use the current item evidence.",
            )
        ],
    )
    principal = Principal(user=manager, auth_type="session")

    first = update_analysis_context(run.id, request, db_session, principal)
    second = update_analysis_context(run.id, request, db_session, principal)

    assert first["rule_version"]["id"] == second["rule_version"]["id"]
    assert (
        db_session.query(ProjectAnalysisRuleVersion)
        .filter(ProjectAnalysisRuleVersion.project_id == run.project_id)
        .count()
        == 1
    )


def test_updating_published_rules_does_not_fork_version(
    db_session: Session,
) -> None:
    _, manager, run, _ = _seed_run(db_session)
    principal = Principal(user=manager, auth_type="session")
    rules = [
        AnalyzerRuleConfig(
            title="Evidence",
            instruction="Use the current item evidence.",
        )
    ]
    created = update_analysis_context(
        run.id,
        AnalysisContextUpdate(
            analysis_rules=rules,
        ),
        db_session,
        principal,
    )
    published = publish_project_analysis_rule_version(
        run.id,
        str(created["rule_version"]["version"]),
        AnalysisRuleVersionPublish(set_alias="production"),
        db_session,
        principal,
    )

    updated = update_analysis_context(
        run.id,
        AnalysisContextUpdate(
            analysis_rules=[
                AnalyzerRuleConfig(**rule)
                for rule in published["version"]["rules"]
            ],
            rule_version_id=published["version"]["id"],
        ),
        db_session,
        principal,
    )

    assert updated["rule_version"]["id"] == published["version"]["id"]
    assert updated["rule_version"]["status"] == "published"
    assert (
        db_session.query(ProjectAnalysisRuleVersion)
        .filter(ProjectAnalysisRuleVersion.project_id == run.project_id)
        .count()
        == 1
    )


def test_explicit_create_analysis_rule_version_snapshots_even_without_edits(
    db_session: Session,
) -> None:
    _, manager, run, _ = _seed_run(db_session)
    principal = Principal(user=manager, auth_type="session")
    rules = [
        AnalyzerRuleConfig(
            title="Evidence",
            instruction="Use the current item evidence.",
        )
    ]
    first = update_analysis_context(
        run.id,
        AnalysisContextUpdate(
            project_description="Test project",
            analysis_rules=rules,
        ),
        db_session,
        principal,
    )

    second = update_analysis_context(
        run.id,
        AnalysisContextUpdate(
            project_description="Test project",
            analysis_rules=rules,
            create_new_version=True,
        ),
        db_session,
        principal,
    )

    assert second["rule_version"]["id"] != first["rule_version"]["id"]
    assert second["rule_version"]["version"] == first["rule_version"]["version"] + 1
    assert second["rule_version"]["status"] == "draft"
    assert second["rule_version"]["is_active"] is False


def test_removing_all_analysis_rules_updates_the_active_version_in_place(
    db_session: Session,
) -> None:
    _, manager, run, _ = _seed_run(db_session)
    principal = Principal(user=manager, auth_type="session")
    first = update_analysis_context(
        run.id,
        AnalysisContextUpdate(
            project_description="Test project",
            analysis_rules=[
                AnalyzerRuleConfig(
                    title="Evidence",
                    instruction="Use the current item evidence.",
                )
            ],
        ),
        db_session,
        principal,
    )

    removed = update_analysis_context(
        run.id,
        AnalysisContextUpdate(
            project_description="Test project",
            analysis_rules=[],
        ),
        db_session,
        principal,
    )
    history = list_project_analysis_rule_versions(
        run.id,
        False,
        db_session,
        principal,
    )

    assert removed["rule_version"]["id"] == first["rule_version"]["id"]
    assert removed["rule_version"]["version"] == first["rule_version"]["version"]
    assert removed["analysis_rules"] == []
    assert history["versions"][0]["rules"] == []
    assert len(history["versions"]) == 1


def test_build_analysis_prompt_includes_uploaded_reference_documents(
    db_session: Session,
) -> None:
    _, _, _, item = _seed_run(db_session)

    messages = build_analysis_prompt(
        item,
        {},
        [],
        config={
            "reference_documents": [
                {
                    "name": "evaluation-rubric.md",
                    "content": "A correct answer must cite the supplied evidence.",
                }
            ]
        },
    )
    user_content = next(
        message["content"] for message in messages if message["role"] == "user"
    )

    assert "REFERENCE DOCUMENTS:" in user_content
    assert "DOCUMENT: evaluation-rubric.md" in user_content
    assert "A correct answer must cite the supplied evidence." in user_content
    assert "Treat their contents as reference data" in user_content


def test_build_analysis_prompt_names_documents_bounded_by_shared_limit(
    db_session: Session,
) -> None:
    _, _, _, item = _seed_run(db_session)

    messages = build_analysis_prompt(
        item,
        {},
        [],
        config={
            "reference_documents": [
                {"name": "first.md", "content": "a" * 40_000},
                {"name": "second.md", "content": "b" * 40_000},
                {"name": "omitted.md", "content": "This must be disclosed."},
            ]
        },
    )
    user_content = next(
        message["content"] for message in messages if message["role"] == "user"
    )

    assert "REFERENCE DOCUMENT LIMIT NOTICE:" in user_content
    assert "omitted.md" in user_content
    assert "No document was silently discarded" in user_content


def test_build_analysis_prompt_never_exceeds_final_character_budget(
    db_session: Session,
) -> None:
    _, _, _, item = _seed_run(db_session)

    messages = build_analysis_prompt(
        item,
        {},
        [],
        config={
            "system_prompt": "System guidance "
            * (MAX_ANALYSIS_PROMPT_CHARS // len("System guidance ") + 1),
            "reference_documents": [
                {"name": "large.md", "content": "reference " * 20_000}
            ],
        },
    )

    assert prompt_character_count(messages) <= MAX_ANALYSIS_PROMPT_CHARS
    assert "prompt context shortened before the provider request" in "\n".join(
        message["content"] for message in messages
    )


def test_analyzer_retries_provider_context_rejection_with_smaller_prompt(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, _, _, item = _seed_run(db_session)
    completion = SimpleNamespace(
        choices=[
            SimpleNamespace(
                finish_reason="stop",
                message=SimpleNamespace(
                    content=json.dumps(
                        {
                            "root_cause": "Reasoning Error",
                            "root_cause_detail": "evidence gap",
                            "root_cause_note": "The answer was not grounded.",
                            "confidence": 0.8,
                        }
                    )
                ),
            )
        ]
    )
    create_completion = AsyncMock(
        side_effect=[RuntimeError("maximum context length exceeded"), completion]
    )
    monkeypatch.setattr(
        llm_analyzer_service,
        "create_chat_completion_compat",
        create_completion,
    )

    result = asyncio.run(
        analyze_single_item(
            SimpleNamespace(),
            "test-model",
            item,
            {},
            [],
            config={"system_prompt": "System guidance " * 10_000},
        )
    )

    assert result.error is None
    assert create_completion.await_count == 2
    first_messages = create_completion.await_args_list[0].kwargs["messages"]
    second_messages = create_completion.await_args_list[1].kwargs["messages"]
    assert prompt_character_count(second_messages) < prompt_character_count(first_messages)
    assert prompt_character_count(second_messages) <= MAX_ANALYSIS_FALLBACK_PROMPT_CHARS


def test_project_context_uses_only_enabled_reference_documents(
    db_session: Session,
) -> None:
    owner, _, run, _ = _seed_run(db_session)
    db_session.add_all(
        [
            AnalyzerDocument(
                project_id=run.project_id,
                uploaded_by_user_id=owner.id,
                name="enabled.md",
                content="Use this context.",
                characters=17,
                enabled=True,
            ),
            AnalyzerDocument(
                project_id=run.project_id,
                uploaded_by_user_id=owner.id,
                name="excluded.md",
                content="Do not use this context.",
                characters=24,
                enabled=False,
            ),
        ]
    )
    db_session.commit()

    config = _analysis_config_with_project_context(db_session, run, {})

    assert config is not None
    assert config["reference_documents"] == [
        {"name": "enabled.md", "content": "Use this context."}
    ]


def test_run_context_toggles_control_prompt_sources(db_session: Session) -> None:
    _, _, run, item = _seed_run(db_session)
    item.trace_id = "trace-toggle"
    db_session.add(
        Span(
            run_id=item.run_id,
            trace_id=item.trace_id,
            span_id="trace-toggle-span",
            name="trace-toggle-step",
            kind="INTERNAL",
            attributes={
                "openinference.span.kind": "LLM",
                "llm.input_messages.0.message.role": "user",
                "llm.input_messages.0.message.content": "trace-only input",
                "llm.output_messages.0.message.role": "assistant",
                "llm.output_messages.0.message.content": "trace-only output",
            },
            events=[],
        )
    )
    db_session.commit()

    supplied_context = {
        "analysis_rules": [
            {"title": "Context-only rule", "instruction": "Use this rule."}
        ],
        "reference_documents": [
            {"name": "context-only.md", "content": "Use this document."}
        ],
        "include_fields": {"trace": True},
    }
    enabled_config = _analysis_config_with_project_context(
        db_session,
        run,
        {
            **supplied_context,
            "_include_project_rules": True,
            "_include_project_documents": True,
        },
    )
    disabled_config = _analysis_config_with_project_context(
        db_session,
        run,
        {
            **supplied_context,
            "_include_project_rules": False,
            "_include_project_documents": False,
            "include_fields": {"trace": False},
        },
    )

    enabled_prompt = "\n".join(
        message["content"]
        for message in build_analysis_prompt(item, {}, [], config=enabled_config)
    )
    disabled_prompt = "\n".join(
        message["content"]
        for message in build_analysis_prompt(item, {}, [], config=disabled_config)
    )

    assert "Context-only rule" in enabled_prompt
    assert "Use this document." in enabled_prompt
    assert "trace-only output" in enabled_prompt
    assert "Context-only rule" not in disabled_prompt
    assert "Use this document." not in disabled_prompt
    assert "trace-only output" not in disabled_prompt
    assert "TRACE EVIDENCE:\n" not in disabled_prompt


def test_playground_config_passes_reference_documents_to_analyzer() -> None:
    config = PlaygroundConfig(
        reference_documents=[
            ReferenceDocument(name="schema.txt", content="orders(id, customer_id)")
        ]
    )

    assert _playground_config_to_analyzer(config) == {
        "reference_documents": [
            {"name": "schema.txt", "content": "orders(id, customer_id)"}
        ],
    }


def test_analyzer_accepts_more_than_five_reference_documents() -> None:
    documents = [
        ReferenceDocument(name=f"reference-{index}.txt", content=f"context {index}")
        for index in range(8)
    ]
    config = PlaygroundConfig(reference_documents=documents)
    analyzer_config = _playground_config_to_analyzer(config)
    assert analyzer_config is not None
    assert len(analyzer_config["reference_documents"]) == 8

    item = RunItem(
        run_id="run-1",
        item_id="item-1",
        index=0,
        input={"question": "q"},
        output={"answer": "a"},
    )
    messages = build_analysis_prompt(item, {}, [], config=analyzer_config)
    user_content = next(
        message["content"] for message in messages if message["role"] == "user"
    )
    assert "DOCUMENT: reference-7.txt" in user_content
    assert "context 7" in user_content


def test_analysis_document_upload_returns_prompt_ready_text(
    db_session: Session,
) -> None:
    actor, _, run, _ = _seed_run(db_session)
    upload = UploadFile(
        filename="review-rubric.txt",
        file=BytesIO(b"Answers must be concise and grounded."),
    )

    payload = asyncio.run(
        upload_analysis_document(
            run_id=run.id,
            file=upload,
            db=db_session,
            principal=Principal(user=actor, auth_type="none"),
        )
    )

    document = payload["document"]
    assert {
        key: document[key]
        for key in ("name", "content", "characters", "truncated", "selected")
    } == {
        "name": "review-rubric.txt",
        "content": "Answers must be concise and grounded.",
        "characters": 37,
        "truncated": False,
        "selected": True,
    }
    assert document["id"]
    assert document["created_at"]


def test_analysis_document_upload_requires_and_reports_large_content_decision(
    db_session: Session,
) -> None:
    actor, _, run, _ = _seed_run(db_session)
    raw = b"x" * (MAX_REFERENCE_DOCUMENT_CONTENT_CHARS + 1)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            upload_analysis_document(
                run_id=run.id,
                file=UploadFile(filename="large.txt", file=BytesIO(raw)),
                db=db_session,
                principal=Principal(user=actor, auth_type="none"),
                large_document_action="ask",
            )
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "DOCUMENT_CONTENT_LIMIT"
    assert exc_info.value.detail["content_will_be_cut"] is True

    shortened = asyncio.run(
        upload_analysis_document(
            run_id=run.id,
            file=UploadFile(filename="large-shortened.txt", file=BytesIO(raw)),
            db=db_session,
            principal=Principal(user=actor, auth_type="none"),
            large_document_action="truncate",
        )
    )
    shortened_document = shortened["document"]
    assert shortened["content_decision"] == "truncate"
    assert shortened_document["characters"] == MAX_REFERENCE_DOCUMENT_CHARS
    assert shortened_document["truncated"] is True
    assert "prompt-safe limit" in shortened["warning"]

    full = asyncio.run(
        upload_analysis_document(
            run_id=run.id,
            file=UploadFile(filename="large-full.txt", file=BytesIO(raw)),
            db=db_session,
            principal=Principal(user=actor, auth_type="none"),
            large_document_action="full",
        )
    )
    full_document = full["document"]
    assert full["content_decision"] == "full"
    assert full_document["characters"] == MAX_REFERENCE_DOCUMENT_CONTENT_CHARS
    assert full_document["content_over_limit"] is True
    assert "absolute content limit" in full["warning"]


def test_rule_inference_rejects_stale_explicit_example_selection(
    db_session: Session,
) -> None:
    _, manager, run, _ = _seed_run(db_session)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            infer_project_analysis_rules(
                run.id,
                RuleInferenceRequest(
                    include_documents=False,
                    include_examples=True,
                    approved_example_ids=[999999],
                ),
                db_session,
                Principal(user=manager, auth_type="none"),
            )
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "APPROVED_EXAMPLES_CHANGED"
    assert exc_info.value.detail["missing_ids"] == [999999]


def test_approved_example_picker_is_paged_and_filters_by_user(
    db_session: Session,
) -> None:
    actor, manager, run, _ = _seed_run(db_session)
    run.model = "gpt-4o"
    corrections = [
        ReviewCorrection(
            run_id=run.id,
            item_id=f"picker-item-{index}",
            metric_name="accuracy",
            task=run.task,
            input_snapshot={"question": f"Question {index}"},
            expected_snapshot={"answer": f"Expected {index}"},
            output_snapshot={"answer": f"Actual {index}"},
            scores_snapshot={},
            ai_root_cause="Reasoning Error",
            ai_root_cause_detail=f"AI detail {index}",
            human_root_cause="Reasoning Error",
            human_root_cause_detail=f"Approved detail {index}",
            human_root_cause_note="Approved by review.",
            corrected_by_user_id=actor.id,
            reviewed_by_user_id=manager.id,
            ai_confidence=0.8,
            status=CorrectionStatus.APPROVED,
            is_active=True,
        )
        for index in range(25)
    ]
    alternate_run = Run(
        id="run-picker-alt",
        project_id=run.project_id,
        created_by_user_id=actor.id,
        owner_user_id=actor.id,
        task=run.task,
        dataset="dataset-2",
        model="gpt-4o-mini",
        metrics=["accuracy"],
        status=RunWorkflowStatus.COMPLETED,
    )
    alternate_correction = ReviewCorrection(
        run_id=alternate_run.id,
        item_id="picker-item-alternate",
        metric_name="accuracy",
        task=run.task,
        input_snapshot={"question": "Alternate question"},
        expected_snapshot={"answer": "Alternate expected"},
        output_snapshot={"answer": "Alternate actual"},
        scores_snapshot={},
        ai_root_cause="Reasoning Error",
        human_root_cause="Reasoning Error",
        corrected_by_user_id=actor.id,
        reviewed_by_user_id=manager.id,
        ai_confidence=0.8,
        status=CorrectionStatus.APPROVED,
        is_active=True,
    )
    db_session.add_all([*corrections, alternate_run, alternate_correction])
    db_session.commit()

    payload = _list_analysis_examples(
        scope_id=run.id,
        page=2,
        page_size=10,
        task=[run.task],
        dataset=[run.dataset],
        model=None,
        run_name=None,
        user_id=[actor.id],
        source=None,
        conf_min=70,
        conf_max=90,
        search="picker-item",
        selected_ids=[corrections[0].id],
        db=db_session,
        principal=Principal(user=manager, auth_type="none"),
    )

    assert payload["total"] == 25
    assert payload["page"] == 2
    assert payload["page_count"] == 3
    assert len(payload["examples"]) == 10
    assert payload["selected_ids"] == [corrections[0].id]
    assert payload["selected_count"] == 1
    assert payload["examples"][0]["source"] == "Corrected"
    assert payload["facets"]["users"]
    assert {user["id"] for user in payload["facets"]["users"]} == {
        actor.id,
        manager.id,
    }
    # Dataset options ignore the active dataset filter, while model options
    # still respect it because model is a different dimension.
    assert {"dataset-1", "dataset-2"}.issubset(payload["facets"]["datasets"])
    assert payload["facets"]["models"] == ["gpt-4o"]

    model_self_excluded = _list_analysis_examples(
        scope_id=run.id,
        page=1,
        page_size=10,
        task=[run.task],
        dataset=None,
        model=["gpt-4o"],
        run_name=None,
        user_id=None,
        source=None,
        conf_min=0,
        conf_max=100,
        search=None,
        selected_ids=None,
        db=db_session,
        principal=Principal(user=manager, auth_type="none"),
    )
    assert {"gpt-4o", "gpt-4o-mini"}.issubset(model_self_excluded["facets"]["models"])

    selected_payload = _list_analysis_examples(
        scope_id=run.id,
        page=1,
        page_size=10,
        task=None,
        dataset=None,
        model=None,
        run_name=None,
        user_id=None,
        source=None,
        conf_min=0,
        conf_max=100,
        search=None,
        selected_ids=[corrections[0].id],
        selected_only=True,
        db=db_session,
        principal=Principal(user=manager, auth_type="none"),
    )
    assert selected_payload["total"] == 1
    assert [example["id"] for example in selected_payload["examples"]] == [
        corrections[0].id
    ]


def test_build_analysis_prompt_projects_nested_output_mapping() -> None:
    item = RunItem(
        run_id="run-1",
        item_id="item-1",
        index=0,
        input={"question": "q"},
        expected={"answer": "expected"},
        output={
            "answer": "actual",
            "debug": {"retrieval": {"matched": False}, "tokens": 42},
            "ignored": "noise",
        },
    )

    messages = build_analysis_prompt(
        item,
        {},
        [],
        config={
            "field_mapping": {
                "output": [
                    "output.answer",
                    "output.debug.retrieval.matched",
                ],
            },
        },
    )

    system_content = next(
        message["content"] for message in messages if message["role"] == "system"
    )
    assert '"answer": "actual"' in system_content
    assert '"matched": false' in system_content
    assert "ignored" not in system_content
    assert '"tokens": 42' not in system_content


def test_build_analysis_prompt_does_not_project_correction_examples() -> None:
    item = RunItem(
        run_id="run-1",
        item_id="item-1",
        index=0,
        input={"question": "q"},
        expected={"answer": "expected"},
        output={
            "answer": "actual",
            "debug": {"trace": "target-noise"},
        },
    )
    correction = ReviewCorrection(
        run_id="run-1",
        item_id="item-2",
        task="insightor_api",
        input_snapshot={"question": "example q"},
        expected_snapshot={"answer": "example expected"},
        output_snapshot={
            "answer": "example actual",
            "debug": {"trace": "example-noise"},
        },
        human_root_cause="Private Example Category",
        status=CorrectionStatus.APPROVED,
        is_active=True,
    )

    messages = build_analysis_prompt(
        item,
        {},
        [correction],
        config={"field_mapping": {"output": ["output.answer"]}},
    )

    prompt_content = "\n\n".join(message["content"] for message in messages)
    assert '"answer": "actual"' in prompt_content
    assert '"answer": "example actual"' not in prompt_content
    assert "example q" not in prompt_content
    assert "example expected" not in prompt_content
    assert "Private Example Category" not in prompt_content
    assert "target-noise" not in prompt_content
    assert "example-noise" not in prompt_content


def test_build_analysis_prompt_projects_python_literal_output_string() -> None:
    item = RunItem(
        run_id="run-1",
        item_id="item-1",
        index=0,
        input={"question": "q"},
        output="{'sql': \"select 'x' as value\", 'agent_response': 'done', 'debug': {'rows': 3}}",
    )

    messages = build_analysis_prompt(
        item,
        {},
        [],
        config={"field_mapping": {"output": ["output.sql", "output.agent_response"]}},
    )

    system_content = next(
        message["content"] for message in messages if message["role"] == "system"
    )
    assert '"sql": "select \'x\' as value"' in system_content
    assert '"agent_response": "done"' in system_content
    assert "debug" not in system_content


def test_build_analysis_prompt_projects_nested_metric_metadata() -> None:
    item = RunItem(
        run_id="run-1",
        item_id="item-1",
        index=0,
        input={"question": "q"},
        output={"answer": "actual"},
    )
    score = RunItemScore(
        run_id="run-1",
        item_id="item-1",
        metric_name="accuracy",
        score_numeric=0.2,
        meta={
            "reason": "bad join",
            "rubric": {"coverage": {"missing": ["city"]}, "unused": True},
        },
    )

    messages = build_analysis_prompt(
        item,
        {"accuracy": score},
        [],
        config={
            "metadata_fields": [
                "metric_metadata.reason",
                "metric_metadata.rubric.coverage.missing",
            ],
        },
        metric_name="accuracy",
    )

    system_content = next(
        message["content"] for message in messages if message["role"] == "system"
    )
    assert "SELECTED METADATA:" in system_content
    assert '"reason": "bad join"' in system_content
    assert '"missing": [' in system_content
    selected_metadata = system_content.split("SELECTED METADATA:\n", 1)[1]
    assert '"unused": true' not in selected_metadata


def test_build_analysis_prompt_projects_metric_metadata_by_metric_name() -> None:
    item = RunItem(
        run_id="run-1",
        item_id="item-1",
        index=0,
        input={"question": "q"},
        output={"answer": "actual"},
    )
    accuracy = RunItemScore(
        run_id="run-1",
        item_id="item-1",
        metric_name="judge.accuracy",
        score_numeric=0.2,
        meta={"reason": "bad join", "rubric": {"missing": "city"}},
    )
    format_score = RunItemScore(
        run_id="run-1",
        item_id="item-1",
        metric_name="format",
        score_numeric=1.0,
        meta={"reason": "valid json"},
    )

    messages = build_analysis_prompt(
        item,
        {"judge.accuracy": accuracy, "format": format_score},
        [],
        config={
            "metadata_fields": [
                "metric_metadata:judge%2Eaccuracy.reason",
                "metric_metadata:format.reason",
            ],
        },
        metric_name="judge.accuracy",
    )

    system_content = next(
        message["content"] for message in messages if message["role"] == "system"
    )
    assert '"judge.accuracy": {' in system_content
    assert '"reason": "bad join"' in system_content
    assert '"format": {' in system_content
    assert '"reason": "valid json"' in system_content
    selected_metadata = system_content.split("SELECTED METADATA:\n", 1)[1]
    assert '"missing": "city"' not in selected_metadata


def test_build_analysis_prompt_includes_only_selected_metric_metadata_by_default() -> None:
    item = RunItem(
        run_id="run-1",
        item_id="item-1",
        index=0,
        input={"question": "q"},
        output={"answer": "actual"},
    )
    accuracy = RunItemScore(
        run_id="run-1",
        item_id="item-1",
        metric_name="accuracy",
        score_numeric=0.2,
        meta={"reason": "bad join"},
    )
    format_score = RunItemScore(
        run_id="run-1",
        item_id="item-1",
        metric_name="format",
        score_numeric=1.0,
        meta={"reason": "valid json"},
    )

    messages = build_analysis_prompt(
        item,
        {"accuracy": accuracy, "format": format_score},
        [],
        metric_name="accuracy",
    )

    system_content = next(
        message["content"] for message in messages if message["role"] == "system"
    )
    assert "SELECTED METRIC RESULT:" in system_content
    assert '"accuracy": {' in system_content
    assert '"format": {' not in system_content
    assert '"reason": "bad join"' in system_content
    assert '"reason": "valid json"' not in system_content


def test_task_root_cause_catalog_includes_defaults_and_task_history(
    db_session: Session,
) -> None:
    actor, reviewer, run, item = _seed_run(db_session)

    change = apply_root_cause_change(
        db_session,
        run=run,
        item=item,
        actor_user_id=actor.id,
        actor_source="ai",
        next_state=build_ai_state(
            root_cause="Reasoning Error",
            root_cause_detail="Join mismatch",
            root_cause_note="AI suggestion",
            confidence=0.8,
        ),
    )
    db_session.commit()

    candidate = change.candidate
    assert candidate is not None
    _approve_candidate(
        db_session,
        correction=candidate,
        reviewer_id=reviewer.id,
        comment="Approve task-specific label",
        reviewed_at=datetime.utcnow(),
    )
    db_session.commit()

    categories, details = _collect_task_root_cause_catalog(db_session, run, [item])

    assert "Hallucination" in categories
    assert "Reasoning Error" in categories
    # details are grouped per category
    assert "Join mismatch" in details.get("Reasoning Error", [])

    analyzer_config = analysis_api._analysis_config_with_category_catalog(
        db_session, run, [item], {}
    )
    assert analyzer_config is not None
    assert analyzer_config["category_example_counts"]["Reasoning Error"] == 1
    prompt = "\n".join(
        message["content"]
        for message in build_analysis_prompt(item, {}, [], config=analyzer_config)
    )
    assert "Approved examples: 1" in prompt


def test_approve_correction_promotes_active_candidate_when_given_stale_id(
    db_session: Session,
) -> None:
    actor, reviewer, run, item = _seed_run(db_session)

    first_change = apply_root_cause_change(
        db_session,
        run=run,
        item=item,
        actor_user_id=actor.id,
        actor_source="human",
        human_patch={
            "root_cause": "Context Missing",
            "root_cause_detail": "Missing schema",
        },
    )
    db_session.commit()
    stale_candidate = first_change.candidate
    assert stale_candidate is not None

    second_change = apply_root_cause_change(
        db_session,
        run=run,
        item=item,
        actor_user_id=actor.id,
        actor_source="human",
        human_patch={
            "root_cause": "Reasoning Error",
            "root_cause_detail": "Wrong join",
        },
    )
    db_session.commit()
    active_candidate = second_change.candidate
    assert active_candidate is not None
    db_session.refresh(stale_candidate)
    assert stale_candidate.is_active is False
    assert active_candidate.is_active is True

    principal = Principal(auth_type="api_key", user=reviewer)
    result = approve_correction(
        stale_candidate.id,
        {"comment": ""},
        db=db_session,
        principal=principal,
    )

    db_session.refresh(active_candidate)
    assert active_candidate.status == CorrectionStatus.APPROVED
    assert result["id"] == active_candidate.id
