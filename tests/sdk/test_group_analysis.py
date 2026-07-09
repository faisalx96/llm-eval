import pytest

from qym import GroupRunAnalysis, analyze_group_runs, compare_group_runs
from qym.core.group_analysis import parse_score_value
from qym.core.results import EvaluationResult


def _result(name, scores, *, metric="accuracy", errors=None, retries=None):
    result = EvaluationResult(
        dataset_name="dataset",
        run_name=name,
        metrics=[metric],
    )
    retries = retries or {}
    for item_id, score in scores.items():
        result.add_input(item_id, f"input-{item_id}")
        result.add_metadata(item_id, {"group": "test"})
        result.add_result(
            item_id,
            {
                "input": f"input-{item_id}",
                "output": f"output-{item_id}",
                "expected": f"expected-{item_id}",
                "scores": {metric: score},
                "time": 0.1,
                "retry_count": retries.get(item_id, 0),
            },
        )
    for item_id, message in (errors or {}).items():
        result.add_input(item_id, f"input-{item_id}")
        result.add_metadata(item_id, {"group": "test"})
        result.add_error(item_id, message, time_seconds=0.2)
    return result


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (1, 1.0),
        (0.25, 0.25),
        (True, 1.0),
        (False, 0.0),
        ("75%", 0.75),
        ("0.8", 0.8),
        ("true", 1.0),
        ("no", 0.0),
        ("\u2713", 1.0),
        ("\u2717", 0.0),
        ({"score": 0.6}, 0.6),
        ({"error": "boom"}, 0.0),
        ("N/A", None),
        ("null", None),
        ("not-a-score", None),
        (None, None),
    ],
)
def test_parse_score_value_matches_platform_rules(raw, expected):
    assert parse_score_value(raw) == expected


def test_analyze_group_runs_matches_item_level_platform_semantics():
    run1 = _result("run1", {"i1": 1.0, "i2": 0.0})
    run2 = _result("run2", {"i1": 0.0, "i2": 0.0, "i3": 1.0})
    run3 = _result("run3", {"i1": 1.0}, errors={"i2": "task failed"})

    summary = analyze_group_runs(
        [run1, run2, run3],
        metric="accuracy",
        threshold=0.8,
        track_distribution=True,
    )

    assert summary["k"] == 3
    assert summary["total_items"] == 3
    assert summary["total_score_count"] == 7
    assert summary["failed_count"] == 1
    assert summary["pass_at_k"] == pytest.approx(2 / 3)
    assert summary["pass_hat_k"] == pytest.approx(1 / 3)
    assert summary["avg_at_k"] == pytest.approx(3 / 7)
    assert summary["avg_score"] == pytest.approx(3 / 7)
    assert summary["max_at_k"] == pytest.approx(2 / 3)
    assert summary["consistency"] == pytest.approx(2 / 3)
    assert summary["reliability"] == pytest.approx(2 / 3)
    assert summary["correct_distribution"] == [1, 1, 1, 0]

    i2 = next(item for item in summary["items"] if item["item_id"] == "i2")
    assert i2["scores"] == [0.0, 0.0, 0.0]
    assert i2["failed_count"] == 1


def test_group_run_analysis_wrapper_uses_same_summary():
    run1 = _result("run1", {"i1": 1.0})
    run2 = _result("run2", {"i1": 0.0})

    summary = GroupRunAnalysis([run1, run2]).metric("accuracy", threshold=0.8)

    assert summary["pass_at_k"] == 1.0
    assert summary["pass_hat_k"] == 0.0
    assert summary["consistency"] == 0.0
    assert summary["reliability"] == 0.5


def test_compare_group_runs_uses_strict_eligibility_and_buckets():
    left1 = _result(
        "left1",
        {"i1": 1.0, "i2": 1.0, "i3": 0.0, "i4": 0.0, "i5": 1.0},
    )
    left2 = _result(
        "left2",
        {"i1": 1.0, "i2": 1.0, "i3": 0.0, "i4": 0.0, "i5": 0.0},
    )
    right1 = _result(
        "right1",
        {"i1": 0.0, "i2": 1.0, "i3": 1.0, "i4": 0.0, "i5": 1.0, "i6": 1.0},
    )
    right2 = _result(
        "right2",
        {"i1": 0.0, "i2": 1.0, "i3": 1.0, "i4": 0.0, "i5": 1.0, "i6": 1.0},
    )

    comparison = compare_group_runs(
        [left1, left2],
        [right1, right2],
        metric="accuracy",
        threshold=0.8,
    )

    assert comparison["eligible_items"] == 5
    assert comparison["left_run_count"] == 2
    assert comparison["right_run_count"] == 2
    assert comparison["left"]["pass_at_k"] == pytest.approx(3 / 5)
    assert comparison["left"]["pass_hat_k"] == pytest.approx(2 / 5)
    assert comparison["left"]["avg_at_k"] == pytest.approx(5 / 10)
    assert comparison["left"]["consistency"] == pytest.approx(4 / 5)
    assert comparison["left"]["reliability"] == pytest.approx(5 / 6)
    assert comparison["right"]["pass_at_k"] == pytest.approx(3 / 5)
    assert comparison["right"]["pass_hat_k"] == pytest.approx(3 / 5)
    assert comparison["right"]["avg_at_k"] == pytest.approx(6 / 10)
    assert comparison["right"]["consistency"] == 1.0
    assert comparison["right"]["reliability"] == 1.0
    assert comparison["deltas"]["avg_at_k"] == pytest.approx(0.1)
    assert comparison["buckets"]["a_sweeps_b"]["count"] == 1
    assert comparison["buckets"]["b_sweeps_a"]["count"] == 1
    assert comparison["buckets"]["both_pass"]["count"] == 1
    assert comparison["buckets"]["both_fail"]["count"] == 1
    assert "i6" not in {item["item_id"] for item in comparison["items"]}


def test_analyze_group_runs_tolerates_non_dict_item_metadata():
    # Langfuse/JSONL/custom datasets can attach non-dict metadata to items;
    # group analysis must not die on them (it previously raised in dict()).
    result = _result("run-1", {"i1": 1.0}, errors={"i2": "boom"})
    result.metadatas["i1"] = ["tag-a", "tag-b"]
    result.metadatas["i2"] = "free-form note"

    analysis = analyze_group_runs([result], metric="accuracy", threshold=0.8)

    assert analysis["total_items"] == 2
    assert analysis["failed_count"] == 1
    items = {item["item_id"]: item for item in analysis["items"]}
    assert items["i1"]["metadata"] == {}
    assert items["i2"]["metadata"] == {}
