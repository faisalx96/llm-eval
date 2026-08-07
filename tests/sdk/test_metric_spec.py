"""Typed metric declaration and validation tests."""

import pytest

from qym import Metric, MetricSpec
from qym.core.dataset import InMemoryDataset
from qym.core.evaluator import Evaluator
from qym.core.multi_runner import MultiModelRunner


def _dataset():
    return InMemoryDataset([{"input": "x", "expected": "x"}], name="typed")


def test_metric_compact_form_is_resolved_by_evaluator():
    def passed(output, expected):
        return output == expected

    evaluator = Evaluator(
        lambda value: value,
        _dataset(),
        [Metric(passed, score_type="boolean")],
        config={"otel_enabled": False, "live_mode": "local"},
    )

    assert evaluator.metrics == {"passed": passed}
    assert evaluator.metric_specs["passed"].score_type == "boolean"
    assert evaluator._metric_specs_payload()["passed"]["schema_version"] == 1


def test_metric_compact_form_is_preserved_by_parallel_runner():
    def passed(output, expected):
        return output == expected

    metric = Metric(passed, score_type="boolean")
    runner = MultiModelRunner.from_runs(
        [
            {
                "name": "typed-parallel",
                "task": lambda value: value,
                "dataset": _dataset(),
                "metrics": [metric],
                "config": {"otel_enabled": False, "live_mode": "local"},
            }
        ]
    )

    assert runner.specs[0].metrics == [metric]
    assert runner._build_run_matrix()[0]["metrics"] == ["passed"]


@pytest.mark.parametrize(
    ("score_type", "value", "expected"),
    [
        ("boolean", True, 1.0),
        ("boolean", False, 0.0),
        ("boolean", 1, 1.0),
        ("percentage", 0.4, 0.4),
        ("count", 3, 3.0),
        ("number", 0.4, 0.4),
    ],
)
def test_metric_spec_validates_observations(score_type, value, expected):
    assert MetricSpec(score_type=score_type).validate_score(value) == expected


@pytest.mark.parametrize(
    ("score_type", "value"),
    [
        ("boolean", 0.5),
        ("percentage", 1.1),
        ("percentage", True),
        ("count", 2.5),
        ("count", -1),
        ("number", float("inf")),
    ],
)
def test_metric_spec_rejects_ambiguous_or_invalid_observations(score_type, value):
    with pytest.raises((TypeError, ValueError)):
        MetricSpec(score_type=score_type).validate_score(value)


def test_metric_requires_explicit_type_or_spec():
    with pytest.raises(ValueError, match="score_type"):
        Metric(lambda output: 1)


def test_duplicate_metric_names_are_rejected():
    def score(output):
        return 1

    with pytest.raises(ValueError, match="Duplicate metric name"):
        Evaluator(
            lambda value: value,
            _dataset(),
            [Metric(score, score_type="count"), Metric(score, score_type="count")],
            config={"otel_enabled": False, "live_mode": "local"},
        )
