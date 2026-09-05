from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from qym_platform.api.analysis import (
    _analysis_example_filter_query,
    _analysis_example_query,
    _approve_candidate,
    _save_analysis_results,
    list_corrections,
)
from qym_platform.api.runs import _apply_metric_analysis_patch, update_root_cause
from qym_platform.auth import Principal
from qym_platform.db.base import Base
from qym_platform.db.models import (
    CorrectionStatus,
    Project,
    ReviewCorrection,
    Run,
    RunItem,
    RunItemPassScore,
    RunItemScore,
    RunWorkflowStatus,
    User,
    UserRole,
)
from qym_platform.services.llm_analyzer import AnalysisResult
from qym_platform.services.root_cause_changes import (
    PASS_ANALYSIS_META_KEY,
    apply_human_patch,
    build_ai_state,
)


ISSUES = [
    {
        "category": "Agent behavior",
        "subcategory": "Retrieval omission",
        "finding": "The lookup omitted a valid active status.",
    },
    {
        "category": "Agent behavior",
        "subcategory": "Predicate construction",
        "finding": "The final filter used OR instead of AND.",
    },
]


@pytest.fixture
def db_session() -> Session:
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def _sqlite_functions(connection, _record) -> None:
        connection.create_function("btrim", 1, lambda value: str(value or "").strip())

    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


def _seed_run(session: Session) -> tuple[User, Run, RunItem]:
    actor = User(id="issue-user", email="issue-user@example.com")
    project = Project(
        id="issue-project",
        name="Issue Project",
        slug="issue-project",
        created_by_user_id=actor.id,
        is_active=True,
    )
    run = Run(
        id="issue-run",
        project_id=project.id,
        created_by_user_id=actor.id,
        owner_user_id=actor.id,
        task="issue-task",
        dataset="issue-dataset",
        metrics=["accuracy"],
        status=RunWorkflowStatus.COMPLETED,
    )
    item = RunItem(
        run_id=run.id,
        item_id="issue-item",
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
        score_numeric=0.0,
        meta={"reason": "wrong"},
    )
    session.add_all([actor, project, run, item, score])
    session.commit()
    return actor, run, item


def test_human_patches_keep_independent_issue_findings() -> None:
    ai_state = build_ai_state(
        root_cause="",
        root_cause_issues=ISSUES,
        confidence=0.91,
    )

    updated = apply_human_patch(
        ai_state,
        {
            "root_cause_issues": [
                ISSUES[0],
                {
                    **ISSUES[1],
                    "finding": "A reviewer confirmed the boolean mismatch.",
                },
            ]
        },
    )

    assert updated["root_cause_issues"][0] == ISSUES[0]
    assert updated["root_cause_issues"][1]["finding"] == (
        "A reviewer confirmed the boolean mismatch."
    )
    assert updated["root_causes"] == ["Agent behavior"]
    assert updated["root_cause_detail"] == "Retrieval omission"
    assert updated["root_cause_note"] == ISSUES[0]["finding"]
    assert updated["root_cause_source"] == "human"


def test_canonical_human_patch_claims_previously_unanalyzed_item() -> None:
    updated = apply_human_patch({}, {"root_cause_issues": ISSUES})

    assert updated["root_cause_issues"] == ISSUES
    assert updated["root_cause_source"] == "human"


@pytest.mark.parametrize(
    "apply_patch", [apply_human_patch, _apply_metric_analysis_patch]
)
@pytest.mark.parametrize(
    "categories, retained_indexes, added",
    [
        (["Agent behavior", "Evaluator"], [0, 1, 2], []),
        (["Agent behavior"], [0, 2], []),
        (["Evaluator"], [1], []),
        (["Evaluator", "New category"], [1], ["New category"]),
        ([], [], []),
    ],
)
def test_legacy_category_patch_preserves_issue_associations(
    apply_patch, categories, retained_indexes, added
) -> None:
    issues = [ISSUES[0], {**ISSUES[0], "category": "Evaluator"}, ISSUES[1]]
    before = build_ai_state(root_cause="", root_cause_issues=issues)
    updated = apply_patch(before, {"root_causes": categories})

    expected = [issues[index] for index in retained_indexes] + [
        {"category": category, "subcategory": "", "finding": ""} for category in added
    ]
    assert updated.get("root_cause_issues", []) == expected
    assert before["root_cause_issues"] == issues


def test_metric_issue_edit_updates_only_its_review_scope(db_session: Session) -> None:
    actor, run, item = _seed_run(db_session)
    actor.role = UserRole.ADMIN
    principal = Principal(user=actor, auth_type="none")
    run.metrics = ["accuracy", "style"]
    results = [
        AnalysisResult(
            item_id=item.item_id,
            metric_name=metric,
            root_cause="",
            root_cause_note="",
            root_cause_issues=ISSUES,
            confidence=0.9,
        )
        for metric in run.metrics
    ]
    _save_analysis_results(
        db_session, run, [(item, metric) for metric in run.metrics], results, principal
    )
    changed = [ISSUES[0], {**ISSUES[1], "finding": "Reviewer confirmed this issue."}]

    response = update_root_cause(
        {
            "run_id": run.id,
            "item_id": item.item_id,
            "metric_name": "accuracy",
            "root_cause_issues": changed,
        },
        db_session,
        principal,
    )
    db_session.refresh(item)

    assert response["ok"] is True
    analyses = item.item_metadata["metric_analyses"]
    assert analyses["accuracy"]["root_cause_issues"] == changed
    assert analyses["style"]["root_cause_issues"] == ISSUES
    active = db_session.query(ReviewCorrection).filter_by(is_active=True).all()
    assert sorted(candidate.metric_name for candidate in active) == [
        "accuracy",
        "style",
    ]
    corrected = next(
        candidate for candidate in active if candidate.metric_name == "accuracy"
    )
    assert corrected.human_root_cause_issues == changed


def test_repeat_issue_edit_preserves_other_passes(db_session: Session) -> None:
    actor, run, item = _seed_run(db_session)
    actor.role = UserRole.ADMIN
    run.samples = 2
    scores = [
        RunItemPassScore(
            run_id=run.id,
            item_id=item.item_id,
            metric_name="accuracy",
            pass_number=pass_number,
            score_numeric=0,
            meta={
                PASS_ANALYSIS_META_KEY: {"root_cause_issues": ISSUES, "source": "ai"}
            },
        )
        for pass_number in (1, 2)
    ]
    db_session.add_all(scores)
    db_session.commit()
    changed = [{**ISSUES[0], "finding": "Second pass finding."}]

    response = update_root_cause(
        {
            "run_id": run.id,
            "item_id": item.item_id,
            "metric_name": "accuracy",
            "pass_number": 2,
            "root_cause_issues": changed,
        },
        db_session,
        Principal(user=actor, auth_type="none"),
    )

    assert response["ok"] is True
    assert scores[0].meta[PASS_ANALYSIS_META_KEY]["root_cause_issues"] == ISSUES
    assert scores[1].meta[PASS_ANALYSIS_META_KEY]["root_cause_issues"] == changed
    assert db_session.query(ReviewCorrection).count() == 0


def test_metric_patch_projects_legacy_fields_without_collapsing_issues() -> None:
    updated = _apply_metric_analysis_patch({}, {"root_cause_issues": ISSUES})

    assert updated["root_cause_issues"] == ISSUES
    assert updated["root_cause"] == "Agent behavior"
    assert updated["root_causes"] == ["Agent behavior"]
    assert updated["root_cause_detail"] == "Retrieval omission"
    assert updated["root_cause_note"] == ISSUES[0]["finding"]

    legacy_edit = _apply_metric_analysis_patch(
        updated, {"root_cause_note": "Updated primary finding."}
    )
    assert legacy_edit["root_cause_issues"][0]["finding"] == (
        "Updated primary finding."
    )
    assert legacy_edit["root_cause_issues"][1] == ISSUES[1]


def test_analysis_persistence_and_approval_round_trip_all_issues(
    db_session: Session,
) -> None:
    actor, run, item = _seed_run(db_session)
    result = AnalysisResult(
        item_id=item.item_id,
        metric_name="accuracy",
        root_cause="",
        root_cause_note="",
        root_cause_issues=ISSUES,
        confidence=0.91,
    )

    payloads, error_count = _save_analysis_results(
        db_session,
        run,
        [(item, "accuracy")],
        [result],
        Principal(user=actor, auth_type="none"),
    )
    db_session.refresh(item)
    candidate = db_session.query(ReviewCorrection).one()

    assert error_count == 0
    assert payloads[0]["root_cause_issues"] == ISSUES
    assert item.item_metadata["root_cause_issues"] == ISSUES
    assert (
        item.item_metadata["metric_analyses"]["accuracy"]["root_cause_issues"] == ISSUES
    )
    assert candidate.ai_root_cause_issues == ISSUES
    assert candidate.ai_root_cause_detail == "Retrieval omission"
    assert candidate.human_root_cause_issues == []

    _approve_candidate(
        db_session,
        correction=candidate,
        reviewer_id=actor.id,
        comment="Approved both diagnoses.",
        reviewed_at=datetime.utcnow(),
    )
    db_session.commit()
    db_session.refresh(candidate)

    assert candidate.human_root_cause_issues == ISSUES
    assert candidate.human_root_causes == ["Agent behavior"]
    assert candidate.human_root_cause_detail == "Retrieval omission"
    assert candidate.human_root_cause_note == ISSUES[0]["finding"]


def test_review_filters_search_and_compare_every_issue(db_session: Session) -> None:
    actor, run, item = _seed_run(db_session)
    result = AnalysisResult(
        item_id=item.item_id,
        metric_name="accuracy",
        root_cause="",
        root_cause_note="",
        root_cause_issues=ISSUES,
        confidence=0.91,
    )
    _save_analysis_results(
        db_session,
        run,
        [(item, "accuracy")],
        [result],
        Principal(user=actor, auth_type="none"),
    )
    candidate = db_session.query(ReviewCorrection).one()

    def listed(*, search: str | None = None, source: str | None = None):
        return list_corrections(
            project_slug=None,
            task=None,
            dataset=None,
            model=None,
            run_name=None,
            source=source,
            conf_min=0,
            conf_max=100,
            status=None,
            search=search,
            limit=None,
            db=db_session,
            principal=Principal(user=actor, auth_type="none"),
        )["corrections"]

    assert [row["id"] for row in listed(search="OR instead")] == [candidate.id]

    candidate.human_root_cause = "Agent behavior"
    candidate.human_root_causes = ["Agent behavior"]
    candidate.human_root_cause_detail = "Retrieval omission"
    candidate.human_root_cause_note = ISSUES[0]["finding"]
    candidate.human_root_cause_issues = [
        ISSUES[0],
        {**ISSUES[1], "finding": "A reviewer changed only this finding."},
    ]
    db_session.commit()

    corrected = listed(source="corrected")
    assert [row["id"] for row in corrected] == [candidate.id]
    assert corrected[0]["human_root_cause_issues"][1]["finding"] == (
        "A reviewer changed only this finding."
    )


def test_migrated_legacy_ai_issue_matches_identical_human_projection(
    db_session: Session,
) -> None:
    actor, run, item = _seed_run(db_session)
    result = AnalysisResult(
        item_id=item.item_id,
        metric_name="accuracy",
        root_cause="",
        root_cause_note="",
        root_cause_issues=[ISSUES[0]],
        confidence=0.91,
    )
    _save_analysis_results(
        db_session,
        run,
        [(item, "accuracy")],
        [result],
        Principal(user=actor, auth_type="none"),
    )
    candidate = db_session.query(ReviewCorrection).one()
    candidate.ai_root_cause_issues = None
    candidate.human_root_cause = candidate.ai_root_cause
    candidate.human_root_causes = list(candidate.ai_root_causes or [])
    candidate.human_root_cause_issues = [ISSUES[0]]
    candidate.human_root_cause_detail = candidate.ai_root_cause_detail
    candidate.human_root_cause_note = candidate.ai_root_cause_note
    candidate.status = CorrectionStatus.APPROVED
    db_session.commit()

    listed = list_corrections(
        project_slug=None,
        task=None,
        dataset=None,
        model=None,
        run_name=None,
        source="ai_only",
        conf_min=0,
        conf_max=100,
        status=None,
        search=None,
        limit=None,
        db=db_session,
        principal=Principal(user=actor, auth_type="none"),
    )["corrections"]
    assert [row["id"] for row in listed] == [candidate.id]

    example_query = _analysis_example_filter_query(
        _analysis_example_query(db_session, run),
        task=None,
        dataset=None,
        model=None,
        run_name=None,
        user_id=None,
        source="ai_only",
        conf_min=0,
        conf_max=100,
        search=None,
    )
    assert [row.id for row in example_query.all()] == [candidate.id]
