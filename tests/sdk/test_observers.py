from unittest.mock import MagicMock, patch

import pytest

from qym import (
    EvaluationObserver,
    Evaluator,
    ProgressCallbackObserver,
    ProgressSnapshot,
)
from qym.core.multi_runner import MultiModelRunner
from qym.core.observers import CompositeEvaluationObserver


def test_progress_callback_observer_emits_structured_counts():
    snapshots = []
    observer = ProgressCallbackObserver(snapshots.append)

    observer.on_run_start(
        run_id="run-1",
        run_info={"dataset": "qa"},
        total_items=3,
        metrics=["exact_match"],
    )
    observer.on_item_start(run_id="run-1", item_index=0, payload={"input": "a"})
    observer.on_metric_result(
        run_id="run-1",
        item_index=0,
        metric_name="exact_match",
        score=1.0,
        metadata={"expected": "a"},
    )
    observer.on_item_complete(run_id="run-1", item_index=0, result={"output": "a"})
    observer.on_item_start(run_id="run-1", item_index=1)
    observer.on_item_error(run_id="run-1", item_index=1, error="boom")
    observer.on_run_complete(run_id="run-1", result_summary={"total_items": 3})

    assert [s.event for s in snapshots] == [
        "run_start",
        "item_start",
        "metric_result",
        "item_complete",
        "item_start",
        "item_error",
        "run_complete",
    ]

    assert snapshots[0].total_items == 3
    assert snapshots[0].pending == 3
    assert snapshots[0].metrics == ["exact_match"]
    assert snapshots[1].payload == {"input": "a"}
    assert snapshots[2].metric_name == "exact_match"
    assert snapshots[2].score == 1.0
    assert snapshots[2].metadata == {"expected": "a"}
    assert snapshots[3].completed == 1
    assert snapshots[3].finished == 1
    assert snapshots[3].percent_complete == pytest.approx(100 / 3)
    assert snapshots[5].failed == 1
    assert snapshots[5].pending == 1
    assert snapshots[-1].in_progress == 0
    assert snapshots[-1].completed == 1
    assert snapshots[-1].failed == 1


def test_progress_callback_observer_deduplicates_item_transitions():
    snapshots = []
    observer = ProgressCallbackObserver(snapshots.append)

    observer.on_run_start("run-1", {}, 1, [])
    observer.on_item_start("run-1", 0)
    observer.on_item_start("run-1", 0)
    observer.on_item_complete("run-1", 0, {})
    observer.on_item_complete("run-1", 0, {})

    assert snapshots[-1].completed == 1
    assert snapshots[-1].in_progress == 0
    assert snapshots[-1].pending == 0


def test_progress_callback_observer_includes_resume_counts():
    snapshots = []
    observer = ProgressCallbackObserver(snapshots.append)

    observer.on_run_start(
        "run-1",
        {"resume_completed": 2, "resume_failed": 1},
        5,
        [],
    )
    observer.on_item_start("run-1", 3)
    observer.on_item_complete("run-1", 3, {})

    assert snapshots[0].completed == 2
    assert snapshots[0].failed == 1
    assert snapshots[0].pending == 2
    assert snapshots[-1].completed == 3
    assert snapshots[-1].failed == 1
    assert snapshots[-1].pending == 1


def test_progress_callback_observer_is_public_api():
    assert issubclass(ProgressCallbackObserver, EvaluationObserver)
    assert ProgressSnapshot(run_id="run-1", event="run_start").percent_complete == 0.0


def test_progress_callback_observer_emits_run_matrix():
    snapshots = []
    observer = ProgressCallbackObserver(snapshots.append)

    observer.on_run_matrix(
        matrix_id="matrix-1",
        runs=[
            {
                "run_id": "run-a",
                "model": "model-a",
                "qym_url": None,
                "status": "pending",
            },
            {
                "run_id": "run-b",
                "model": "model-b",
                "qym_url": None,
                "status": "pending",
            },
        ],
        total_runs=2,
    )

    assert snapshots[0].event == "run_matrix"
    assert snapshots[0].run_id == "matrix-1"
    assert snapshots[0].total_runs == 2
    assert snapshots[0].run_matrix[0]["model"] == "model-a"
    assert snapshots[0].run_matrix[0]["qym_url"] is None


def test_composite_observer_ignores_callback_errors():
    calls = []

    def broken(_snapshot):
        raise RuntimeError("callback failed")

    composite = CompositeEvaluationObserver(
        [
            ProgressCallbackObserver(broken),
            ProgressCallbackObserver(calls.append),
        ]
    )

    composite.on_run_start(run_id="run-1", run_info={}, total_items=1, metrics=[])

    assert len(calls) == 1
    assert calls[0].event == "run_start"


def test_multi_model_runner_builds_initial_run_matrix():
    class Dataset:
        name = "qa-set"

        def get_items(self):
            return ["one", "two", "three"]

    def task(input_data):
        return input_data

    runner = MultiModelRunner.from_runs(
        [
            {
                "name": "qa",
                "task": task,
                "dataset": Dataset(),
                "metrics": ["exact_match"],
                "models": ["model-a", "model-b"],
            }
        ]
    )

    matrix = runner._build_run_matrix()

    assert len(matrix) == 2
    assert [entry["model"] for entry in matrix] == ["model-a", "model-b"]
    assert [entry["total_items"] for entry in matrix] == [3, 3]
    assert all(entry["qym_url"] is None for entry in matrix)
    assert all(entry["status"] == "pending" for entry in matrix)


def test_evaluator_accepts_progress_callback():
    snapshots = []
    dataset = MagicMock()
    dataset.name = "mock-dataset"

    with patch("qym.core.evaluator.auto_detect_task"):
        evaluator = Evaluator(
            task=lambda question: question,
            dataset=dataset,
            metrics=[],
            config={"run_name": "progress-callback", "otel_enabled": False},
            progress_callback=snapshots.append,
        )

    evaluator._notify_observer(
        "on_run_start",
        run_info={"dataset": "mock-dataset"},
        total_items=2,
        metrics=[],
    )

    assert snapshots[0].event == "run_start"
    assert snapshots[0].run_id == evaluator.run_name
    assert snapshots[0].total_items == 2
