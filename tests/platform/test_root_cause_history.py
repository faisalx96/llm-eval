from __future__ import annotations

import asyncio
import json
import math
import os
import sys
from datetime import datetime
from io import BytesIO
from unittest.mock import MagicMock

import pytest
from fastapi import UploadFile
from sqlalchemy import Text, create_engine
from sqlalchemy.orm import Session, sessionmaker

os.environ.setdefault("QYM_DATABASE_URL", "sqlite:///:memory:")
if "openai" not in sys.modules:
    sys.modules["openai"] = MagicMock()

from qym_platform.api.analysis import (
    AnalyzeRequest,
    PlaygroundConfig,
    ReferenceDocument,
    _approve_candidate,
    _collect_task_root_cause_catalog,
    _delete_active_candidate,
    _filter_analysis_targets,
    _load_metric_specs,
    _persist_aggregated_bindings,
    _persisted_ai_analysis_bindings,
    _playground_config_to_analyzer,
    _reject_candidate,
    _save_analysis_results,
    approve_correction,
    approve_metric_analysis,
    upload_analysis_document,
)
from qym_platform.api.runs import _build_run_data
from qym_platform.auth import Principal
from qym_platform.db.base import Base
from qym_platform.db.models import (
    CorrectionStatus,
    Project,
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
)
from qym_platform.services.llm_analyzer import (
    AnalysisResult,
    ROLE_WRITER_SYSTEM_PROMPT,
    build_analysis_prompt,
    get_few_shot_examples,
    normalize_analysis_roles,
    parse_llm_response,
)
from qym_platform.services.root_cause_changes import apply_root_cause_change, build_ai_state


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
        description="Test project",
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


def _latest_active_candidate(session: Session, run_id: str, item_id: str) -> ReviewCorrection | None:
    return (
        session.query(ReviewCorrection)
        .filter(
            ReviewCorrection.run_id == run_id,
            ReviewCorrection.item_id == item_id,
            ReviewCorrection.is_active.is_(True),
        )
        .first()
    )


def test_review_correction_details_store_long_analyzer_text(db_session: Session) -> None:
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
    historical = db_session.query(ReviewCorrection).filter(ReviewCorrection.run_id == run.id).all()
    assert len(historical) == 2
    assert {c.status for c in historical} == {CorrectionStatus.SUPERSEDED, CorrectionStatus.WITHDRAWN}
    assert all(c.is_active is False for c in historical)

    revisions = (
        db_session.query(RootCauseRevision)
        .filter(RootCauseRevision.run_id == run.id, RootCauseRevision.item_id == item.item_id)
        .order_by(RootCauseRevision.revision_number.asc())
        .all()
    )
    assert [revision.actor_source for revision in revisions] == ["ai", "human", "human"]
    assert revisions[-1].after_state.get("root_cause", "") == ""


def test_latest_approved_revision_supersedes_previous_example(db_session: Session) -> None:
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
    assert [c.id for c in get_few_shot_examples(db_session, run.task, limit=10)] == [first_candidate.id]

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
    assert get_few_shot_examples(db_session, run.task, limit=10) == []

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
    assert [c.id for c in get_few_shot_examples(db_session, run.task, limit=10)] == [second_candidate.id]


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
    assert item.item_metadata["root_cause_note"] == "Updated note after deeper inspection"

    revisions = (
        db_session.query(RootCauseRevision)
        .filter(RootCauseRevision.run_id == run.id, RootCauseRevision.item_id == item.item_id)
        .order_by(RootCauseRevision.revision_number.asc())
        .all()
    )
    assert len(revisions) == 3
    assert revisions[-1].before_state["root_cause_note"] == "Original reviewer note"
    assert revisions[-1].after_state["root_cause_note"] == "Updated note after deeper inspection"


def test_delete_request_rejects_and_removes_active_candidate(db_session: Session) -> None:
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
    remaining = db_session.query(ReviewCorrection).filter(ReviewCorrection.run_id == run.id).all()
    assert len(remaining) == 2
    assert {row.status for row in remaining} == {
        CorrectionStatus.REJECTED,
        CorrectionStatus.SUPERSEDED,
    }

    revisions = (
        db_session.query(RootCauseRevision)
        .filter(RootCauseRevision.run_id == run.id, RootCauseRevision.item_id == item.item_id)
        .order_by(RootCauseRevision.revision_number.asc())
        .all()
    )
    assert len(revisions) == 3
    assert revisions[-1].actor_source == "system"
    assert revisions[-1].after_state.get("root_cause") == ""


def test_editing_approved_human_only_candidate_stays_approved_and_does_not_fake_ai(db_session: Session) -> None:
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
    assert second_candidate.human_root_cause_detail == "Missing schema and business rules"

    approved = get_few_shot_examples(db_session, run.task, limit=10)
    assert [c.id for c in approved] == [second_candidate.id]


def test_follow_up_human_edit_preserves_original_ai_snapshot(db_session: Session) -> None:
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


def test_follow_up_human_edit_recovers_ai_snapshot_from_history_if_active_candidate_lost_it(db_session: Session) -> None:
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


def test_ai_analysis_creates_pending_ai_only_candidate_and_approval_copies_ai_to_human(db_session: Session) -> None:
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

    approved = get_few_shot_examples(db_session, run.task, limit=10)
    assert [c.id for c in approved] == [candidate.id]


def test_get_few_shot_examples_without_limit_returns_all_active_approved_examples(
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

    approved = get_few_shot_examples(db_session, run.task, limit=None)
    assert {c.id for c in approved} == {first_candidate.id, second_candidate.id}


def test_build_analysis_prompt_resolves_custom_variable_from_selected_metric_metadata() -> None:
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
    assert any("METRIC METADATA:" in message["content"] for message in messages)
    assert any('"accuracy": {' in message["content"] for message in messages)
    assert any('"judge": "llm"' in message["content"] for message in messages)


def test_build_analysis_prompt_includes_native_trace_spans(db_session: Session) -> None:
    _, _, _, item = _seed_run(db_session)
    item.trace_id = "trace-1"
    item.trace_url = "https://qym.example/runs/run-1?trace_id=trace-1"
    db_session.add(
        Span(
            run_id=item.run_id,
            trace_id=item.trace_id,
            span_id="span-1",
            name="ChatCompletion",
            kind="INTERNAL",
            status="ERROR",
            attributes={
                "openinference.span.kind": "LLM",
                "output.value": "wrong",
                "authorization": "trace-secret",
            },
            events=[{"name": "exception", "attributes": {"message": "failed"}}],
            links=[],
        )
    )
    db_session.commit()

    messages = build_analysis_prompt(item, {}, [])
    system_content = next(message["content"] for message in messages if message["role"] == "system")

    assert "TRACE ID:\ntrace-1" in system_content
    assert "TRACE CONTENT:" in system_content
    assert '"name": "ChatCompletion"' in system_content
    assert '"output.value": "wrong"' in system_content
    assert "trace-secret" not in system_content
    assert '"authorization": "[REDACTED]"' in system_content
    assert "TRACE URL:\nhttps://qym.example/runs/run-1?trace_id=trace-1" in system_content


def test_build_analysis_prompt_includes_project_description(db_session: Session) -> None:
    _, _, _, item = _seed_run(db_session)

    messages = build_analysis_prompt(
        item,
        {},
        [],
        config={"project_description": "A text-to-SQL assistant for read-only analytics."},
    )
    system_content = next(message["content"] for message in messages if message["role"] == "system")

    assert "Project description: A text-to-SQL assistant for read-only analytics." in system_content
    assert "{business_context}" not in system_content


def test_build_analysis_prompt_renders_all_new_system_contexts(db_session: Session) -> None:
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
            "category_details_map": {"Reasoning Error": ["Join mismatch"]},
            "reference_documents": [
                {"name": "policy.md", "content": "Always cite the account policy."}
            ],
        },
        metric_name="accuracy",
    )
    system_content = next(message["content"] for message in messages if message["role"] == "system")
    user_content = next(message["content"] for message in messages if message["role"] == "user")

    for placeholder in (
        "{business_context}",
        "{metric_context}",
        "{model_context}",
        "{item_context}",
    ):
        assert placeholder not in system_content

    assert "Project: Project One" in system_content
    assert "Project description: A regulated financial support assistant." in system_content
    assert "Stored project description: Test project" in system_content
    assert "Evaluation task: insightor_api" in system_content
    assert "Dataset: dataset-1" in system_content
    assert "Attached reference documents: policy.md" in system_content
    assert "Reasoning Error" in system_content
    assert "Join mismatch" in system_content

    assert '"selected_metric": "accuracy"' in system_content
    assert '"score_numeric": 0.1' in system_content
    assert '"label": "fail"' in system_content
    assert "The generated answer used the wrong join." in system_content
    assert '"pass_threshold": 0.8' in system_content
    assert '"direction": "maximize"' in system_content

    assert '"evaluated_model": "provider/evaluated-model-v2"' in system_content
    assert '"temperature": 0.3' in system_content
    assert '"api_key": "[REDACTED]"' in system_content
    assert "must-not-reach-the-analyzer" not in system_content
    assert '"model_revision": "2026-07-20"' in system_content

    assert '"item_id": "item-1"' in system_content
    assert '"latency_ms": 245.5' in system_content
    assert '"retry_count": 2' in system_content
    assert '"domain": "finance"' in system_content
    assert '"question": "q"' in system_content
    assert '"answer": "expected"' in system_content
    assert '"answer": "actual"' in system_content
    assert "Always cite the account policy." in user_content


def test_build_analysis_prompt_renders_custom_context_fields_and_literal_json() -> None:
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
                "Business:\n{business_context}\n\n"
                "Metric:\n{metric_context}\n\n"
                "Model:\n{model_context}\n\n"
                "Item:\n{item_context}\n\n"
                'Return {{"root_cause": "value"}}.'
            ),
            "business_context": {"domain": "support"},
            "metric_context": "Prefer the human rubric.",
            "model_context": {"family": "small-model"},
        },
    )
    system_content = next(message["content"] for message in messages if message["role"] == "system")
    user_content = next(message["content"] for message in messages if message["role"] == "user")

    assert '"domain": "support"' in system_content
    assert "Prefer the human rubric." in system_content
    assert '"family": "small-model"' in system_content
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
    system_content = next(message["content"] for message in messages if message["role"] == "system")
    user_content = next(message["content"] for message in messages if message["role"] == "user")

    assert "SUPPLIED ANALYSIS DATA" in system_content
    assert "Billing support" in system_content
    assert "Evidence is required" in system_content
    assert "Evaluated model family: small" in system_content
    assert "The answer omitted the required evidence." in system_content
    assert 'JSON field "solution"' in system_content
    assert "Add Evidence" in system_content
    assert '"question": "Why?"' in system_content
    assert "ITEM RECORD" not in user_content


def test_prompt_redacts_structured_secrets_across_item_metric_and_correction_context() -> None:
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
    assert prompt_content.count('"[REDACTED]"') >= 3


def test_default_prompt_requests_solution_without_changing_existing_result_fields() -> None:
    item = RunItem(run_id="run-1", item_id="item-1", index=0, input={"q": "x"})
    messages = build_analysis_prompt(
        item,
        {},
        [],
        config={"solution_categories": ["Add Validation"]},
    )
    system_content = next(message["content"] for message in messages if message["role"] == "system")

    assert '"root_cause": "<broad category>"' in system_content
    assert '"root_cause_detail": "<specific sub-issue, 4-5 words max>"' in system_content
    assert '"confidence": <float between 0.0-1.0>' in system_content
    assert '"root_cause_note": "<2-3 sentences maximum: what went wrong and why>"' in system_content
    assert '"solution": "<recommended solution category>"' in system_content
    assert "Add Validation" in system_content
    assert "Treat each metric as an independent evaluation target" in system_content


def test_analysis_prompt_scopes_category_root_cause_and_feedback_to_selected_metric() -> None:
    item = RunItem(run_id="run-1", item_id="item-1", index=0, input={"q": "x"})

    accuracy_messages = build_analysis_prompt(
        item,
        {},
        [],
        metric_name="accuracy",
    )
    format_messages = build_analysis_prompt(
        item,
        {},
        [],
        metric_name="format",
    )

    accuracy_prompt = "\n".join(message["content"] for message in accuracy_messages)
    format_prompt = "\n".join(message["content"] for message in format_messages)
    assert "Diagnose only the selected metric accuracy" in accuracy_prompt
    assert "Diagnose only the selected metric format" in format_prompt
    assert "category, specific root cause, and feedback for this metric independently" in accuracy_prompt


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
    assert incomplete.confidence < complete.confidence
    assert 0.0 <= non_finite.confidence <= 1.0
    assert math.isfinite(non_finite.confidence)


def test_playground_config_passes_project_description_to_analyzer() -> None:
    config = PlaygroundConfig(project_description="A support assistant for billing questions.")

    assert _playground_config_to_analyzer(config) == {
        "project_description": "A support assistant for billing questions.",
        "corrections_enabled": True,
    }


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
    )
    db_session.refresh(item)

    assert errors == 0
    assert [payload["metric_name"] for payload in payloads] == ["accuracy", "format"]
    assert item.item_metadata["metric_analyses"]["accuracy"]["root_cause"] == "Reasoning Error"
    assert item.item_metadata["metric_analyses"]["format"]["root_cause"] == "Wrong Format"
    assert item.item_metadata["root_cause"] == "Reasoning Error"
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
    assert "APPROVED ACCURACY EXAMPLE" in prompt_text
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
    assert len(bindings) == 2
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

    assert changed == 2
    assert (
        item.item_metadata["root_cause_detail"]
        == "Expected SQL uses non-SQLite functions"
    )
    assert item.item_metadata["root_cause_note"] == "Feedback for the item-level analysis."
    assert item.item_metadata["solution"] == "Improve Retrieval Context"
    assert item.item_metadata["solution_note"] == "Item-specific solution guidance."
    metric_analysis = item.item_metadata["metric_analyses"]["accuracy"]
    assert metric_analysis["root_cause_detail"] == "Expected SQL uses non-SQLite functions"
    assert metric_analysis["root_cause_note"] == "Feedback for the metric analysis."
    assert metric_analysis["solution"] == "Improve Retrieval Context"
    assert metric_analysis["solution_note"] == "Metric-specific solution guidance."


def test_analysis_roles_are_neutral_normalized_and_included_in_prompt() -> None:
    roles = normalize_analysis_roles(
        [
            {
                "name": "Schema semantics",
                "description": "Knows entity relationships and checks joins against documented keys.",
            },
            {"name": "Schema semantics", "description": "duplicate"},
            {"name": "", "description": "invalid"},
        ]
    )
    assert roles == [
        {
            "name": "Schema semantics",
            "description": "Knows entity relationships and checks joins against documented keys.",
        }
    ]
    item = RunItem(run_id="run-1", item_id="item-1", index=0, input={"question": "q"})
    messages = build_analysis_prompt(item, {}, [], config={"analysis_roles": roles})
    system_content = next(message["content"] for message in messages if message["role"] == "system")

    assert "Schema semantics" in system_content
    assert "checks joins against documented keys" in system_content
    assert "they are not label-selection rules" in system_content
    assert "Never create label shortcuts" in ROLE_WRITER_SYSTEM_PROMPT
    assert "if you see X, choose Y" in ROLE_WRITER_SYSTEM_PROMPT


def test_build_analysis_prompt_includes_uploaded_reference_documents(db_session: Session) -> None:
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
    user_content = next(message["content"] for message in messages if message["role"] == "user")

    assert "REFERENCE DOCUMENTS:" in user_content
    assert "DOCUMENT: evaluation-rubric.md" in user_content
    assert "A correct answer must cite the supplied evidence." in user_content
    assert "Treat their contents as reference data" in user_content


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
        "corrections_enabled": True,
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
    user_content = next(message["content"] for message in messages if message["role"] == "user")
    assert "DOCUMENT: reference-7.txt" in user_content
    assert "context 7" in user_content


def test_analysis_document_upload_returns_prompt_ready_text(db_session: Session) -> None:
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
    assert {key: document[key] for key in ("name", "content", "characters", "truncated", "selected")} == {
        "name": "review-rubric.txt",
        "content": "Answers must be concise and grounded.",
        "characters": 37,
        "truncated": False,
        "selected": True,
    }
    assert document["id"]
    assert document["created_at"]


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

    system_content = next(message["content"] for message in messages if message["role"] == "system")
    assert '"answer": "actual"' in system_content
    assert '"matched": false' in system_content
    assert "ignored" not in system_content
    assert '"tokens": 42' not in system_content


def test_build_analysis_prompt_projects_few_shot_output_mapping() -> None:
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
        human_root_cause="Wrong Format",
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
    assert '"answer": "example actual"' in prompt_content
    assert "target-noise" not in prompt_content
    assert "example-noise" not in prompt_content


def test_build_analysis_prompt_projects_python_literal_output_string() -> None:
    item = RunItem(
        run_id="run-1",
        item_id="item-1",
        index=0,
        input={"question": "q"},
        output='{\'sql\': "select \'x\' as value", \'agent_response\': \'done\', \'debug\': {\'rows\': 3}}',
    )

    messages = build_analysis_prompt(
        item,
        {},
        [],
        config={"field_mapping": {"output": ["output.sql", "output.agent_response"]}},
    )

    system_content = next(message["content"] for message in messages if message["role"] == "system")
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

    system_content = next(message["content"] for message in messages if message["role"] == "system")
    assert "METRIC METADATA:" in system_content
    assert '"reason": "bad join"' in system_content
    assert '"missing": [' in system_content
    assert "unused" not in system_content


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

    system_content = next(message["content"] for message in messages if message["role"] == "system")
    assert '"judge.accuracy": {' in system_content
    assert '"reason": "bad join"' in system_content
    assert '"format": {' in system_content
    assert '"reason": "valid json"' in system_content
    assert "missing" not in system_content


def test_build_analysis_prompt_includes_all_metric_metadata_by_default() -> None:
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

    system_content = next(message["content"] for message in messages if message["role"] == "system")
    assert "METRIC METADATA:" in system_content
    assert '"accuracy": {' in system_content
    assert '"format": {' in system_content
    assert '"reason": "bad join"' in system_content
    assert '"reason": "valid json"' in system_content


def test_task_root_cause_catalog_includes_defaults_and_task_history(db_session: Session) -> None:
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


def test_approve_correction_promotes_active_candidate_when_given_stale_id(db_session: Session) -> None:
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
