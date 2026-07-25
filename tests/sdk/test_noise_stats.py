"""Tests for report_k estimators, clustered bootstrap, and the noise report.

The noise report answers: is a week-over-week delta real, or explainable by
run-to-run luck? Key acceptance cases mirror the design validation:
an identical agent re-run must read "within_noise"; a planted improvement
must read "improved".
"""

import itertools
import random

import pytest

from qym.core.group_analysis import compare_group_runs
from qym.core.reducers import (
    clustered_mean_ci,
    group_stats,
    noise_report,
    unbiased_pass_at_k,
)
from qym.core.results import EvaluationResult


def _result(name, scores, *, metric="accuracy"):
    result = EvaluationResult(dataset_name="dataset", run_name=name, metrics=[metric])
    for item_id, score in scores.items():
        result.add_input(item_id, f"input-{item_id}")
        result.add_result(
            item_id,
            {
                "input": f"input-{item_id}",
                "output": "out",
                "expected": "exp",
                "scores": {metric: score},
                "time": 0.1,
                "retry_count": 0,
            },
        )
    return result


def _binary_group(pass_probs, n_runs, rng, *, metric="accuracy"):
    """One group of n_runs results over items with given true pass rates."""
    runs = []
    for run_idx in range(n_runs):
        scores = {
            item_id: 1.0 if rng.random() < prob else 0.0
            for item_id, prob in pass_probs.items()
        }
        runs.append(_result(f"run-{run_idx}", scores, metric=metric))
    return runs


# ── report_k estimators ──────────────────────────────────────────────


def test_group_stats_report_k_equals_mean_over_subsets():
    # pass@3 estimated from 9 passes == exact mean over all C(9,3) subsets.
    passes = [1, 1, 0, 1, 0, 0, 1, 0, 1]  # c = 5 of n = 9
    items = {"item": [float(value) for value in passes]}
    stats = group_stats(items, report_k=3)
    subset_means = [
        1.0 if any(passes[i] for i in combo) else 0.0
        for combo in itertools.combinations(range(9), 3)
    ]
    expected = sum(subset_means) / len(subset_means)
    assert stats["pass_at_k"] == pytest.approx(expected)
    assert stats["report_k"] == 3


def test_group_stats_without_report_k_is_observed():
    items = {"a": [1.0, 0.0, 0.0], "b": [0.0, 0.0, 0.0], "c": [1.0, 1.0, 1.0]}
    stats = group_stats(items)
    assert stats["pass_at_k"] == pytest.approx(2 / 3)  # any-pass fraction
    assert stats["pass_hat_k"] == pytest.approx(1 / 3)  # all-pass fraction


def test_report_k_clamps_to_items_with_fewer_passes():
    items = {"full": [1.0] * 9, "short": [0.0, 1.0]}  # one item has 2 passes
    stats = group_stats(items, report_k=3)
    expected_short = unbiased_pass_at_k(2, 1, 2)  # clamped to k=2
    assert stats["pass_at_k"] == pytest.approx((1.0 + expected_short) / 2)


# ── clustered bootstrap ──────────────────────────────────────────────


def test_clustered_mean_ci_wider_than_flat_for_correlated_items():
    # Items are internally consistent (all-1 or all-0): the item is the true
    # unit of variation, so the clustered interval must be wider than a flat
    # resample of the pooled passes.
    from qym.core.reducers import mean_ci

    groups = [[1.0] * 6 for _ in range(10)] + [[0.0] * 6 for _ in range(10)]
    flat = [score for group in groups for score in group]
    clustered = clustered_mean_ci(groups, seed=1)
    pooled = mean_ci(flat, seed=1)
    assert clustered["mean"] == pytest.approx(pooled["mean"])
    clustered_width = clustered["ci_high"] - clustered["ci_low"]
    pooled_width = pooled["ci_high"] - pooled["ci_low"]
    assert clustered_width > pooled_width * 1.5


def test_clustered_mean_ci_empty_and_single():
    assert clustered_mean_ci([]) == {"mean": 0.0, "ci_low": 0.0, "ci_high": 0.0}
    single = clustered_mean_ci([[0.5, 0.7]])
    assert single["mean"] == pytest.approx(0.6)
    assert single["ci_low"] == single["ci_high"] == pytest.approx(0.6)


# ── noise report: pure function ──────────────────────────────────────


def _flaky_universe(rng, n_items=100):
    """Item pass-probabilities mimicking a flaky agent (mix of 0/flaky/1)."""
    probs = {}
    for i in range(n_items):
        roll = rng.random()
        if roll < 0.3:
            prob = 0.0
        elif roll < 0.6:
            prob = 1.0
        else:
            prob = rng.uniform(0.2, 0.8)
        probs[f"item-{i}"] = prob
    return probs


def _draw_scores(probs, n_runs, rng):
    return {
        item_id: [1.0 if rng.random() < prob else 0.0 for _ in range(n_runs)]
        for item_id, prob in probs.items()
    }


def test_identical_agent_reads_within_noise():
    # Same true pass rates on both sides: any delta is pure run luck.
    # With a 95% band a single metric flags ~5% of the time; require the
    # verdict to be clean across seeds in aggregate (>=80% within_noise).
    flags = 0
    trials = 20
    for seed in range(trials):
        rng = random.Random(seed)
        probs = _flaky_universe(rng)
        left = _draw_scores(probs, 9, rng)
        right = _draw_scores(probs, 9, rng)
        report = noise_report(left, right, report_k=3)
        if report["pass_at_k"]["verdict"] != "within_noise":
            flags += 1
    assert flags <= trials * 0.2


def test_planted_improvement_reads_improved():
    rng = random.Random(7)
    probs = _flaky_universe(rng)
    left = _draw_scores(probs, 9, rng)
    improved = {
        item_id: min(1.0, prob + 0.15) if prob < 1.0 else prob
        for item_id, prob in probs.items()
    }
    # Decisively fix a handful of always-fail items too.
    fixed = 0
    for item_id, prob in improved.items():
        if prob == 0.0 and fixed < 8:
            improved[item_id] = 0.95
            fixed += 1
    right = _draw_scores(improved, 9, rng)
    report = noise_report(left, right, report_k=3)
    assert report["pass_at_k"]["verdict"] == "improved"
    assert report["avg_at_k"]["verdict"] == "improved"
    assert report["pass_at_k"]["delta"] > 0
    assert report["pass_at_k"]["p_value"] < 0.05


def test_planted_regression_reads_regressed():
    rng = random.Random(11)
    probs = _flaky_universe(rng)
    left = _draw_scores(probs, 9, rng)
    worse = {item_id: prob * 0.6 for item_id, prob in probs.items()}
    right = _draw_scores(worse, 9, rng)
    report = noise_report(left, right, report_k=3)
    assert report["pass_at_k"]["verdict"] == "regressed"
    assert report["pass_at_k"]["delta"] < 0


def test_noise_report_no_shared_items():
    report = noise_report({"a": [1.0]}, {"b": [1.0]})
    assert report["pass_at_k"] is None
    assert report["avg_at_k"] is None


def test_noise_report_reliability_has_no_band():
    rng = random.Random(3)
    probs = _flaky_universe(rng)
    left = _draw_scores(probs, 4, rng)
    right = _draw_scores(probs, 4, rng)
    assert noise_report(left, right)["reliability"] is None


def test_noise_band_shrinks_with_more_runs():
    rng = random.Random(5)
    probs = _flaky_universe(rng)
    few = noise_report(
        _draw_scores(probs, 3, rng), _draw_scores(probs, 3, rng), report_k=3
    )
    many = noise_report(
        _draw_scores(probs, 15, rng), _draw_scores(probs, 15, rng), report_k=3
    )
    assert many["pass_at_k"]["half_width"] < few["pass_at_k"]["half_width"]


# ── compare_group_runs integration ───────────────────────────────────


def test_compare_group_runs_carries_noise_and_report_k():
    rng = random.Random(2)
    probs = {f"item-{i}": rng.choice([0.0, 0.5, 1.0]) for i in range(40)}
    left = _binary_group(probs, 6, rng)
    right = _binary_group(probs, 6, rng)
    result = compare_group_runs(
        left, right, metric="accuracy", report_k=3, confidence=0.95
    )
    assert result["report_k"] == 3
    noise = result["noise"]
    for name in ("pass_at_k", "pass_hat_k", "avg_at_k"):
        assert noise[name] is not None
        assert set(noise[name]) == {"delta", "half_width", "p_value", "verdict"}
    assert noise["reliability"] is None
    # The published delta must be the same quantity the noise report judged.
    assert result["deltas"]["pass_at_k"] == pytest.approx(
        noise["pass_at_k"]["delta"]
    )


def test_compare_group_runs_estimator_matches_observed_without_report_k():
    rng = random.Random(4)
    probs = {f"item-{i}": rng.choice([0.0, 0.5, 1.0]) for i in range(20)}
    left = _binary_group(probs, 5, rng)
    right = _binary_group(probs, 5, rng)
    result = compare_group_runs(left, right, metric="accuracy")
    observed_left = sum(
        1 for item in result["items"] if item["left_pass_count"] > 0
    ) / result["eligible_items"]
    assert result["left"]["pass_at_k"] == pytest.approx(observed_left)


def test_avg_band_absent_when_single_score_per_side():
    # One score per item per side: within-item variance is not estimable,
    # so avg_at_k must get no band (None), never a false ±0.
    left = {f"i{i}": [float(i % 2)] for i in range(10)}
    right = {f"i{i}": [1.0] for i in range(10)}
    report = noise_report(left, right)
    assert report["avg_at_k"] is None
    assert report["pass_at_k"] is not None  # binomial band still exists
