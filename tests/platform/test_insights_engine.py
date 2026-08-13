from typing import Optional

from qym_platform.db.base import Base
from qym_platform.db.models import Run, RunItem, RunItemScore, RunMetricSpec, Span
from qym_platform.services.insights_engine import (
    DEFAULT_MIN_CATEGORY_ITEMS,
    DEFAULT_MIN_ROOT_CAUSE_OCCURRENCES,
    build_insight_data,
)
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _add_tool_span(
    session: Session,
    *,
    run_id: str,
    trace_id: str,
    span_id: str,
    name: str,
    parent_span_id: Optional[str] = None,
) -> None:
    session.add(
        Span(
            run_id=run_id,
            trace_id=trace_id,
            span_id=span_id,
            parent_span_id=parent_span_id,
            name=f"tool:{name}",
            kind="INTERNAL",
            status="OK",
            attributes={
                "openinference.span.kind": "TOOL",
                "tool.name": name,
            },
        )
    )


def _seed_engine_data(session: Session) -> Run:
    run = Run(
        id="run-1",
        project_id="project-1",
        created_by_user_id="user-1",
        owner_user_id="user-1",
        task="qa",
        dataset="support",
        model="openai/model-a",
        metrics=["accuracy", "latency"],
    )
    session.add_all(
        [
            run,
            RunMetricSpec(
                run_id=run.id,
                metric_name="accuracy",
                score_type="numeric",
                direction="maximize",
                pass_threshold=0.8,
            ),
            RunMetricSpec(
                run_id=run.id,
                metric_name="latency",
                score_type="numeric",
                direction="minimize",
                pass_threshold=100,
            ),
        ]
    )

    rows = [
        ("item-1", "Common cause", 0.9, 90.0),
        ("item-2", "common-cause", 0.7, 110.0),
        ("item-3", "Common cause", 0.95, 80.0),
        ("item-4", "Rare cause", 0.4, 50.0),
    ]
    for index, (item_id, detail, accuracy, latency) in enumerate(rows):
        metadata = {
            "root_cause": "Legacy category must not be counted",
            "metric_analyses": {
                "accuracy": {
                    "root_causes": (
                        ["Reasoning-Error", "Small category"]
                        if index == 0
                        else ["reasoning error"]
                    ),
                    "root_cause_detail": detail,
                }
            },
        }
        item = RunItem(
            run_id=run.id,
            item_id=item_id,
            index=index,
            input={"index": index},
            output={"answer": index},
            item_metadata=metadata,
            trace_id=f"trace-{index + 1}",
        )
        session.add_all(
            [
                item,
                RunItemScore(
                    run_id=run.id,
                    item_id=item_id,
                    metric_name="accuracy",
                    score_numeric=accuracy,
                ),
                RunItemScore(
                    run_id=run.id,
                    item_id=item_id,
                    metric_name="latency",
                    score_numeric=latency,
                ),
            ]
        )

    _add_tool_span(
        session,
        run_id=run.id,
        trace_id="trace-1",
        span_id="tool-1",
        name="search",
    )
    _add_tool_span(
        session,
        run_id=run.id,
        trace_id="trace-1",
        span_id="tool-2",
        name="search",
    )
    _add_tool_span(
        session,
        run_id=run.id,
        trace_id="trace-2",
        span_id="tool-3",
        name="search",
    )
    _add_tool_span(
        session,
        run_id=run.id,
        trace_id="trace-4",
        span_id="tool-4",
        name="calculator",
    )
    session.add(
        Span(
            run_id=run.id,
            trace_id="trace-1",
            span_id="evaluator-1",
            name="judge accuracy",
            kind="INTERNAL",
            status="OK",
            attributes={"openinference.span.kind": "EVALUATOR"},
        )
    )
    _add_tool_span(
        session,
        run_id=run.id,
        trace_id="trace-1",
        span_id="evaluation-tool",
        parent_span_id="evaluator-1",
        name="judge_tool",
    )
    session.commit()
    return run


def test_engine_applies_thresholds_and_populates_both_data_levels() -> None:
    session = _session()
    run = _seed_engine_data(session)

    insights = build_insight_data(
        session,
        "project-1",
        minimum_category_items=3,
        minimum_root_cause_occurrences=3,
        extra_data_by_run={run.id: {"deployment": "production", "team": "search"}},
    )

    assert [insight.category for insight in insights] == ["Reasoning-Error"]
    insight = insights[0]
    assert insight.models == {"model-a": 1}
    assert insight.datasets == {"support": 1}
    assert insight.tasks == {"qa": 1}
    assert insight.metrics == {
        "accuracy": {"success": 0, "fail": 1},
        "latency": {"success": 1, "fail": 0},
    }
    assert insight.tools == {"calculator": 1}
    assert insight.extra_data == {
        "runs": {run.id: {"deployment": "production", "team": "search"}}
    }

    assert list(insight.root_causes) == ["Common cause"]
    root_cause = insight.root_causes["Common cause"]
    assert root_cause.models == {"model-a": 3}
    assert root_cause.datasets == {"support": 3}
    assert root_cause.tasks == {"qa": 3}
    assert root_cause.metrics == {
        "accuracy": {"success": 2, "fail": 1},
        "latency": {"success": 2, "fail": 1},
    }
    assert root_cause.tools == {"search": 3}
    assert "judge_tool" not in root_cause.tools
    assert root_cause.extra_data == insight.extra_data


def test_default_thresholds_route_small_root_causes_to_the_category() -> None:
    session = _session()
    _seed_engine_data(session)

    insights = build_insight_data(session, "project-1")

    assert DEFAULT_MIN_CATEGORY_ITEMS == 3
    assert DEFAULT_MIN_ROOT_CAUSE_OCCURRENCES == 5
    assert len(insights) == 1
    assert insights[0].root_causes == {}
    assert insights[0].models == {"model-a": 4}
    assert insights[0].tools == {"search": 3, "calculator": 1}


def test_engine_validates_thresholds_and_empty_run_selection() -> None:
    session = _session()
    _seed_engine_data(session)

    assert build_insight_data(session, "project-1", run_ids=[]) == []

    try:
        build_insight_data(
            session,
            "project-1",
            minimum_root_cause_occurrences=0,
        )
    except ValueError as error:
        assert "minimum_root_cause_occurrences" in str(error)
    else:
        raise AssertionError("Expected an invalid threshold to raise ValueError")
