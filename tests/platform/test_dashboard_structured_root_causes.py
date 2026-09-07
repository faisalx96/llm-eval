"""Projection parity with structured issues and their real edit/provenance paths."""

from __future__ import annotations

import copy
import json

from qym_platform.api.analysis import _save_analysis_results
from qym_platform.api.runs import update_root_cause
from qym_platform.auth import Principal
from qym_platform.db.models import (
    ReviewCorrection,
    Run,
    RunItem,
    RunItemPassScore,
    RunItemScore,
    RunWorkflowStatus,
    User,
)
from qym_platform.services.llm_analyzer import AnalysisResult
from qym_platform.services.root_cause_changes import PASS_ANALYSIS_META_KEY
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_dashboard_durable_summaries import (
    Dimension,
    Summary,
    assert_legacy_parity,
    database,
    drain,
    item,
    projected,
    run,
    service,
)

ISSUES = [
    {
        "category": "Agent behavior",
        "subcategory": "Retrieval",
        "finding": "First independent private finding.",
    },
    {
        "category": "Agent behavior",
        "subcategory": "Predicate",
        "finding": "Second independent private finding.",
    },
    {
        "category": "Evaluation",
        "subcategory": "Reference",
        "finding": "Third independent private finding.",
    },
]


def _actor(db):
    return Principal(user=db.get(User, "u"), auth_type="none")


def _revision(engine):
    with Session(engine) as db:
        return db.get(Summary, "r").projection_revision


def test_multi_issue_analysis_and_metric_review_preserve_legacy_counts(database):
    with Session(database) as db:
        source_run = run(
            db, metrics=["accuracy", "style"], status=RunWorkflowStatus.COMPLETED
        )
        source_item = item(db)
        db.add_all(
            [
                RunItemScore(
                    run_id="r", item_id="i", metric_name=metric, score_numeric=0.0
                )
                for metric in source_run.metrics
            ]
        )
        db.commit()
        results = [
            AnalysisResult(
                item_id="i",
                metric_name=metric,
                root_cause="",
                root_cause_note="",
                root_cause_issues=copy.deepcopy(ISSUES),
                confidence=0.9,
            )
            for metric in source_run.metrics
        ]
        _save_analysis_results(
            db,
            source_run,
            [(source_item, metric) for metric in source_run.metrics],
            results,
            _actor(db),
        )
        db.commit()
    drain(database)
    assert_legacy_parity(database)
    # The existing runs-table chip counts primary category labels; the separate
    # root-cause occurrence dashboard counts independent issue findings.
    assert projected(database)["analysis_cause_count"] == 1
    previous_revision = _revision(database)
    changed = [
        dict(ISSUES[0], category="Human finding"),
        dict(ISSUES[1], finding="Reviewed second private finding."),
    ]
    with Session(database) as db:
        result = update_root_cause(
            {
                "run_id": "r",
                "item_id": "i",
                "metric_name": "accuracy",
                "root_cause_issues": changed,
            },
            db,
            _actor(db),
        )
        assert result["ok"]
        db.commit()
        analyses = db.scalar(select(RunItem)).item_metadata["metric_analyses"]
        assert analyses["accuracy"]["root_cause_issues"] == changed
        assert analyses["style"]["root_cause_issues"] == ISSUES
        correction = db.scalar(
            select(ReviewCorrection).where(
                ReviewCorrection.is_active.is_(True),
                ReviewCorrection.metric_name == "accuracy",
            )
        )
        assert correction.human_root_cause_issues == changed
        assert correction.ai_root_cause_issues == ISSUES
    drain(database)
    assert_legacy_parity(database)
    assert projected(database)["analysis_cause_count"] == 2
    assert _revision(database) > previous_revision
    with Session(database) as db:
        # Private findings remain in authoritative source/provenance records.
        wire = json.dumps(
            {**db.get(Dimension, "r").descriptor, **db.get(Summary, "r").data}
        )
        assert "private finding" not in wire


def test_finding_only_human_edit_advances_projection_revision(database):
    with Session(database) as db:
        source_run = run(db, metrics=["accuracy"], status=RunWorkflowStatus.COMPLETED)
        source_item = item(db)
        db.add(
            RunItemScore(
                run_id="r", item_id="i", metric_name="accuracy", score_numeric=0.0
            )
        )
        db.commit()
        _save_analysis_results(
            db,
            source_run,
            [(source_item, "accuracy")],
            [
                AnalysisResult(
                    item_id="i",
                    metric_name="accuracy",
                    root_cause="",
                    root_cause_note="",
                    root_cause_issues=copy.deepcopy(ISSUES),
                    confidence=0.9,
                )
            ],
            _actor(db),
        )
        db.commit()
    drain(database)
    previous = _revision(database)
    previous_count = projected(database)["analysis_cause_count"]
    changed = copy.deepcopy(ISSUES)
    changed[1]["finding"] = "Reviewer changes only the second finding."
    with Session(database) as db:
        update_root_cause(
            {
                "run_id": "r",
                "item_id": "i",
                "metric_name": "accuracy",
                "root_cause_issues": changed,
            },
            db,
            _actor(db),
        )
        db.commit()
        assert (
            db.scalar(select(RunItem)).item_metadata["metric_analyses"]["accuracy"][
                "root_cause_issues"
            ]
            == changed
        )
    drain(database)
    assert_legacy_parity(database)
    assert projected(database)["analysis_cause_count"] == previous_count
    assert _revision(database) > previous


def test_repeat_structured_issues_use_categories_per_pass_and_track_edits(database):
    with Session(database) as db:
        run(
            db,
            metrics=["accuracy"],
            samples=2,
            status=RunWorkflowStatus.COMPLETED,
            run_metadata={"total_items": 1, "last_completed_pass": 2},
        )
        item(db)
        for pass_number, issues in ((1, ISSUES), (2, ISSUES[:2])):
            db.add(
                RunItemPassScore(
                    run_id="r",
                    item_id="i",
                    metric_name="accuracy",
                    pass_number=pass_number,
                    score_numeric=0.0,
                    meta={
                        PASS_ANALYSIS_META_KEY: {
                            "root_cause_issues": copy.deepcopy(issues),
                            "root_cause": "stale legacy category",
                            "root_causes": ["stale legacy category"],
                            "source": "ai",
                        }
                    },
                )
            )
        db.commit()
    drain(database)
    assert_legacy_parity(database)
    summary = projected(database)
    assert summary["analysis_cause_count"] == 3
    assert [row["analysis_cause_count"] for row in summary["pass_summaries"]] == [2, 1]
    with Session(database) as db:
        update_root_cause(
            {
                "run_id": "r",
                "item_id": "i",
                "metric_name": "accuracy",
                "pass_number": 2,
                "root_cause_issues": [
                    dict(ISSUES[0], category="Human finding"),
                    ISSUES[1],
                ],
            },
            db,
            _actor(db),
        )
        db.commit()
        first = db.scalar(
            select(RunItemPassScore).where(RunItemPassScore.pass_number == 1)
        )
        assert first.meta[PASS_ANALYSIS_META_KEY]["root_cause_issues"] == ISSUES
        assert db.scalar(select(ReviewCorrection)) is None
    drain(database)
    assert_legacy_parity(database)
    assert projected(database)["analysis_cause_count"] == 4
    with Session(database) as db:
        update_root_cause(
            {
                "run_id": "r",
                "item_id": "i",
                "metric_name": "accuracy",
                "pass_number": 2,
                "root_cause_issues": [],
            },
            db,
            _actor(db),
        )
        db.commit()
    drain(database)
    assert_legacy_parity(database)
    assert projected(database)["analysis_cause_count"] == 2


def test_structured_issue_backfill_matches_current_legacy_endpoint(database):
    with Session(database) as db:
        db.info["dashboard_projection_worker"] = True
        run(db, metrics=["accuracy"], samples=2, status=RunWorkflowStatus.APPROVED)
        for number in range(5):
            item(
                db,
                str(number),
                item_metadata={
                    "root_cause": "Agent behavior",
                    "root_cause_issues": copy.deepcopy(ISSUES),
                },
            )
            for pass_number in (1, 2):
                db.add(
                    RunItemPassScore(
                        run_id="r",
                        item_id=str(number),
                        metric_name="accuracy",
                        pass_number=pass_number,
                        score_numeric=0.5,
                        meta={
                            PASS_ANALYSIS_META_KEY: {
                                "root_cause_issues": copy.deepcopy(ISSUES),
                                "source": "human",
                            }
                        },
                    )
                )
        db.commit()
    with Session(database) as db:
        service.bootstrap_partitions(db)
        db.commit()
    drain(database, max_events=2)
    assert_legacy_parity(database)
    assert projected(database)["analysis_cause_count"] == 4
