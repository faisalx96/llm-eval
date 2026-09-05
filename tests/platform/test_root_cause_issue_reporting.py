from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from qym_platform.db.base import Base
from qym_platform.db.models import (
    CorrectionStatus,
    Project,
    ReviewCorrection,
    Run,
    RunItem,
    RunItemScore,
    RunMetricSpec,
)
from qym_platform.services.approved_diagnoses import load_approved_diagnoses
from qym_platform.services.insights_engine import build_insight_data
from qym_platform.services.root_cause_dashboard import (
    DashboardFilters,
    build_dashboard_payload,
    build_occurrences_payload,
)


def _session_with_two_issues() -> tuple[Session, Project, Run, RunItem]:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    project = Project(
        id="project-1",
        name="Reporting project",
        slug="reporting-project",
        created_by_user_id="user-1",
    )
    run = Run(
        id="run-1",
        project_id=project.id,
        created_by_user_id="user-1",
        owner_user_id="user-1",
        task="qa",
        dataset="support",
        model="openai/model-a",
        metrics=["accuracy"],
    )
    item = RunItem(
        run_id=run.id,
        item_id="item-1",
        index=0,
        input={"question": "Find active records"},
        output={"count": 1},
        item_metadata={},
    )
    issues = [
        {
            "category": "Agent",
            "subcategory": "Retrieval failure",
            "finding": "The value search omitted active status A.",
        },
        {
            "category": "Agent",
            "subcategory": "Retrieval failure",
            "finding": "The value search also omitted active status B.",
        },
    ]
    ai_issues = [
        {
            "category": "Agent",
            "subcategory": "Retrieval failure",
            "finding": "The original AI finding must not replace the review.",
        }
    ]
    session.add_all(
        [
            project,
            run,
            item,
            RunItemScore(
                run_id=run.id,
                item_id=item.item_id,
                metric_name="accuracy",
                score_numeric=0.0,
            ),
            RunMetricSpec(
                run_id=run.id,
                metric_name="accuracy",
                score_type="numeric",
                direction="maximize",
                pass_threshold=0.8,
            ),
            ReviewCorrection(
                run_id=run.id,
                item_id=item.item_id,
                metric_name="accuracy",
                task=run.task,
                ai_root_cause="Agent",
                ai_root_causes=["Agent"],
                ai_root_cause_issues=ai_issues,
                human_root_cause="Agent",
                human_root_causes=["Agent"],
                human_root_cause_issues=issues,
                human_root_cause_detail="Retrieval failure",
                human_root_cause_note=issues[0]["finding"],
                status=CorrectionStatus.APPROVED,
                is_active=True,
            ),
        ]
    )
    session.commit()
    return session, project, run, item


def test_approved_and_dashboard_reporting_preserve_both_issue_findings() -> None:
    session, project, run, item = _session_with_two_issues()
    try:
        approved = load_approved_diagnoses(session, [run.id], [item])
        entries = approved[(run.id, item.item_id)]
        assert [entry["note"] for entry in entries] == [
            "The value search omitted active status A.",
            "The value search also omitted active status B.",
        ]
        assert {entry["source"] for entry in entries} == {"human"}

        occurrences = build_occurrences_payload(session, project, DashboardFilters())
        assert occurrences["total"] == 2
        assert [entry["note"] for entry in occurrences["occurrences"]] == [
            "The value search omitted active status A.",
            "The value search also omitted active status B.",
        ]

        dashboard = build_dashboard_payload(session, project, DashboardFilters())
        assert dashboard["summary"]["diagnosis_occurrences"] == 2
        assert dashboard["summary"]["affected_run_item_pairs"] == 1
        assert dashboard["groups"]["by_category"][0]["count"] == 2
        assert dashboard["groups"]["by_category"][0]["affected_items"] == 1
    finally:
        session.close()


def test_insights_count_repeated_issue_records_without_double_counting_items() -> None:
    session, _project, run, _item = _session_with_two_issues()
    try:
        insights = build_insight_data(
            session,
            run.project_id,
            minimum_category_items=1,
            minimum_root_cause_occurrences=2,
        )

        assert [insight.category for insight in insights] == ["Agent"]
        root_cause = insights[0].root_causes["Retrieval failure"]
        assert root_cause.models == {"model-a": 2}
        assert root_cause.datasets == {"support": 2}
        assert root_cause.metrics == {"accuracy": {"success": 0, "fail": 2}}
    finally:
        session.close()
