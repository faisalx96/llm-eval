from __future__ import annotations

import os
import sys
from datetime import datetime
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

os.environ.setdefault("QYM_DATABASE_URL", "sqlite:///:memory:")
if "openai" not in sys.modules:
    sys.modules["openai"] = MagicMock()

from qym_platform.api.analysis import _approve_candidate, _delete_active_candidate
from qym_platform.db.base import Base
from qym_platform.db.models import (
    CorrectionStatus,
    ReviewCorrection,
    RootCauseRevision,
    Run,
    RunItem,
    RunItemScore,
    RunWorkflowStatus,
    User,
)
from qym_platform.services.llm_analyzer import get_few_shot_examples
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
    run = Run(
        id="run-1",
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
    session.add_all([actor, reviewer, run, item, score])
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

    historical = db_session.query(ReviewCorrection).filter(ReviewCorrection.run_id == run.id).all()
    assert len(historical) == 1
    assert historical[0].status == CorrectionStatus.WITHDRAWN
    assert historical[0].is_active is False

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


def test_delete_active_approved_candidate_clears_run_item_state(db_session: Session) -> None:
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

    _delete_active_candidate(db_session, candidate)
    db_session.commit()
    db_session.refresh(item)

    assert item.item_metadata.get("root_cause") is None
    assert item.item_metadata.get("root_cause_detail") is None
    assert item.item_metadata.get("root_cause_note") is None
    assert item.item_metadata.get("root_cause_source") is None
    assert _latest_active_candidate(db_session, run.id, item.item_id) is None
    assert db_session.query(ReviewCorrection).filter(ReviewCorrection.run_id == run.id).count() == 0

    revisions = (
        db_session.query(RootCauseRevision)
        .filter(RootCauseRevision.run_id == run.id, RootCauseRevision.item_id == item.item_id)
        .order_by(RootCauseRevision.revision_number.asc())
        .all()
    )
    assert len(revisions) == 3
    assert revisions[-1].actor_source == "system"
    assert revisions[-1].after_state.get("root_cause", "") == ""


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
    assert ai_change.candidate is None

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
