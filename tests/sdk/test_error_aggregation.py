"""Audit EI-1: errored metric values must be excluded from aggregation.

One shared convention (qym.core.results.is_errored_metric_value): a metric
result is *errored* iff its metadata (or the raw dict itself) carries an
'error' key, OR its score is None. Errored values are excluded from
means/min/max and surfaced via error counts — never averaged in as 0.0.
"""

import csv

import pytest

from qym.core.checkpoint import (
    CheckpointWriter,
    load_checkpoint_state,
    iter_checkpoint_rows,
    parse_checkpoint_row,
    serialize_checkpoint_row,
)
from qym.core.group_analysis import analyze_group_runs, parse_score_value
from qym.core.results import (
    EvaluationResult,
    is_error_row,
    is_errored_metric_cell,
    is_errored_metric_value,
)
from qym.core.run_discovery import RunDiscovery
from qym.metrics.result import MetricResult


# ---------------------------------------------------------------------------
# Shared helper: is_errored_metric_value
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    [
        None,  # score is None -> errored
        {"error": "boom"},
        {"score": 0, "error": "traceback..."},  # evaluator exception shape
        {"score": 0.0, "metadata": {"error": "metric timeout after 120s"}},
        {"score": None},
        MetricResult(score=0.0, kind="llm", metadata={"error": "LLM judge call failed"}),
        "ERROR: judge blew up",  # CSV-serialized top-level error
        "N/A",  # CSV-serialized task failure
        "{'score': 0, 'error': 'boom'}",  # stringified dict
        # stringified MetricResult repr
        "MetricResult(score=0.0, label=None, explanation=None, kind='llm', "
        "direction='maximize', metadata={'error': 'x'})",
    ],
)
def test_is_errored_metric_value_true(value):
    assert is_errored_metric_value(value) is True


@pytest.mark.parametrize(
    "value",
    [
        0.0,  # a real zero score is NOT an error
        1.0,
        True,
        False,
        "0.85",
        "false",
        {"score": 0.0},
        {"score": 0.9, "metadata": {"reason": "fine"}},
        MetricResult(score=0.0),
        MetricResult(score=1.0, label="good"),
        "",  # empty string is missing, not errored
    ],
)
def test_is_errored_metric_value_false(value):
    assert is_errored_metric_value(value) is False


def test_is_errored_metric_cell_detects_meta_json_error():
    row = {"acc_score": "0.0", "acc__meta__json": '{"error": "judge timeout"}'}
    assert is_errored_metric_cell(row, "acc") is True


def test_is_errored_metric_cell_detects_legacy_flattened_error_column():
    # EvaluationResult.save_csv flattens metadata into {metric}__meta__{key}
    row = {"acc_score": "0.0", "acc__meta__error": "judge timeout"}
    assert is_errored_metric_cell(row, "acc") is True


def test_is_errored_metric_cell_healthy_and_missing_cells():
    assert is_errored_metric_cell({"acc_score": "0.9"}, "acc") is False
    assert is_errored_metric_cell({"acc_score": "0.0"}, "acc") is False
    assert is_errored_metric_cell({}, "acc") is False  # missing column
    assert is_errored_metric_cell({"acc_score": ""}, "acc") is False


# ---------------------------------------------------------------------------
# is_error_row checks EVERY metric, not just the first
# ---------------------------------------------------------------------------


def test_is_error_row_not_error_when_only_first_metric_errored():
    # Old behavior: greping ERROR in the FIRST metric only marked this whole
    # row as failed, zeroing the healthy second metric. The row completed —
    # it is NOT an error row.
    row = {"output": "fine", "m1_score": "ERROR: judge died", "m2_score": "0.9"}
    assert is_error_row(row, ["m1", "m2"]) is False


def test_is_error_row_not_error_when_only_last_metric_errored():
    row = {"output": "fine", "m1_score": "0.4", "m2_score": "ERROR: judge died"}
    assert is_error_row(row, ["m1", "m2"]) is False


def test_is_error_row_when_all_metrics_errored():
    row = {"output": "fine", "m1_score": "ERROR: a", "m2_score": "N/A"}
    assert is_error_row(row, ["m1", "m2"]) is True


def test_is_error_row_on_task_failure_output():
    row = {"output": "ERROR: task crashed", "m1_score": "N/A", "m2_score": "N/A"}
    assert is_error_row(row, ["m1", "m2"]) is True


# ---------------------------------------------------------------------------
# EvaluationResult.get_metric_stats: exclusion + error_count
# ---------------------------------------------------------------------------


def _result_with_scores(metric, values):
    result = EvaluationResult(dataset_name="ds", run_name="run", metrics=[metric])
    for i, value in enumerate(values):
        result.add_result(f"item_{i}", {"scores": {metric: value}, "time": 0.1})
    return result


def test_get_metric_stats_excludes_errors_and_reports_error_count():
    result = _result_with_scores(
        "acc",
        [
            1.0,
            0.5,
            {"score": 0, "error": "traceback"},  # top-level error
            {"score": 0.0, "metadata": {"error": "judge timeout"}},  # nested
            MetricResult(score=0.0, metadata={"error": "llm failed"}),
        ],
    )
    stats = result.get_metric_stats("acc")
    # Behavior change (audit EI-1): errors were previously partially scored
    # as 0.0 and dragged the mean down; now all errored values are excluded.
    assert stats["mean"] == pytest.approx(0.75)
    assert stats["min"] == 0.5
    assert stats["max"] == 1.0
    assert stats["error_count"] == 3
    assert stats["success_rate"] == pytest.approx(2 / 5)
    # Existing keys remain stable for callers
    assert set(stats) >= {"mean", "std", "min", "max", "success_rate", "error_count"}


def test_get_metric_stats_zero_score_is_not_an_error():
    stats = _result_with_scores("acc", [0.0, 1.0]).get_metric_stats("acc")
    assert stats["mean"] == pytest.approx(0.5)
    assert stats["error_count"] == 0
    assert stats["success_rate"] == 1.0


def test_get_metric_stats_all_errored_reports_count():
    stats = _result_with_scores("acc", [{"error": "a"}, {"error": "b"}]).get_metric_stats("acc")
    assert stats["mean"] == 0.0
    assert stats["error_count"] == 2
    assert stats["success_rate"] == 0.0


def test_get_metric_stats_reads_metric_result_scores():
    # MetricResult instances (returned by judges) now contribute their score.
    stats = _result_with_scores(
        "acc", [MetricResult(score=0.9), MetricResult(score=0.7)]
    ).get_metric_stats("acc")
    assert stats["mean"] == pytest.approx(0.8)
    assert stats["error_count"] == 0


# ---------------------------------------------------------------------------
# MetricResult.from_raw preserves error markers (spec item 5)
# ---------------------------------------------------------------------------


def test_from_raw_preserves_error_in_metadata_with_zero_score():
    mr = MetricResult.from_raw({"score": 0, "error": "boom"})
    assert mr.score == 0.0  # backward compat for arithmetic
    assert mr.metadata["error"] == "boom"
    assert mr.is_errored is True
    assert is_errored_metric_value(mr) is True
    # ...and the legacy dict round-trip keeps the marker visible
    assert is_errored_metric_value(mr.to_legacy_dict()) is True


def test_from_raw_merges_sibling_metadata_with_error():
    mr = MetricResult.from_raw({"error": "boom", "metadata": {"attempt": 2}})
    assert mr.metadata["error"] == "boom"
    assert mr.metadata["attempt"] == 2


def test_metric_result_is_errored_false_for_healthy_results():
    assert MetricResult(score=0.0).is_errored is False
    assert MetricResult.from_raw(0.0).is_errored is False
    assert MetricResult.from_raw({"score": 1.0}).is_errored is False


# ---------------------------------------------------------------------------
# Group analysis uses the same exclusion
# ---------------------------------------------------------------------------


def test_parse_score_value_excludes_errored_values():
    # Behavior change (audit EI-1): previously {"error": ...} scored 0.0.
    assert parse_score_value({"error": "boom"}) is None
    assert parse_score_value({"score": 0.0, "metadata": {"error": "x"}}) is None
    assert parse_score_value(MetricResult(score=0.0, metadata={"error": "x"})) is None
    # Healthy values are unchanged
    assert parse_score_value({"score": 0.6}) == 0.6
    assert parse_score_value(MetricResult(score=0.4)) == 0.4


def test_analyze_group_runs_excludes_judge_errors_but_keeps_task_failures():
    run = EvaluationResult(dataset_name="ds", run_name="r1", metrics=["acc"])
    run.add_result("i1", {"scores": {"acc": 1.0}, "time": 0.1})
    # Judge errored on i2: excluded entirely (no usable signal), not 0.0
    run.add_result(
        "i2",
        {"scores": {"acc": {"score": 0.0, "metadata": {"error": "judge died"}}}, "time": 0.1},
    )
    # Task failure on i3: platform semantics keep it as a 0.0 failed attempt
    run.add_error("i3", "task exploded", time_seconds=0.2)

    summary = analyze_group_runs([run], metric="acc", threshold=0.8)

    assert summary["total_items"] == 2  # i1 + i3; i2 has no usable score
    assert summary["total_score_count"] == 2
    assert summary["avg_at_k"] == pytest.approx(0.5)  # (1.0 + 0.0) / 2
    assert summary["failed_count"] == 1
    item_ids = {item["item_id"] for item in summary["items"]}
    assert item_ids == {"i1", "i3"}


# ---------------------------------------------------------------------------
# RunDiscovery aggregation: per-metric exclusion, per-metric error counts
# ---------------------------------------------------------------------------


def _write_run_csv(results_dir, metrics, rows):
    csv_path = (
        results_dir / "task_x" / "model-x" / "2025-01-01" / "run-250101-0101.csv"
    )
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    from qym.core.checkpoint import build_checkpoint_header

    header = build_checkpoint_header(metrics)
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=header)
        writer.writeheader()
        writer.writerows(rows)
    return csv_path


def _row(item_id, output, scores, metric_meta=None):
    return serialize_checkpoint_row(
        dataset_name="ds",
        run_name="run-250101-0101",
        run_metadata={"model": "model-x"},
        run_config={},
        trace_id=f"t-{item_id}",
        item_id=item_id,
        item_input=f"input-{item_id}",
        item_metadata={},
        output=output,
        expected_output="exp",
        time_seconds=0.5,
        task_started_at_ms=1,
        scores=scores,
        metric_meta=metric_meta or {},
    )


def test_run_discovery_excludes_errored_metrics_per_metric(tmp_path):
    results_dir = tmp_path / "qym_results"
    rows = [
        # healthy row
        _row("i0", "ok", {"m1": 1.0, "m2": 0.5}),
        # m1 errored (judge failure serialized as ERROR string), m2 healthy
        _row("i1", "ok", {"m1": "ERROR: judge blew up", "m2": 1.0}),
        # m2 errored via nested metadata error (score cell still 0.0)
        _row(
            "i2",
            "ok",
            {"m1": 0.0, "m2": 0.0},
            metric_meta={"m2": {"error": "metric timeout after 120s"}},
        ),
        # full task failure: counted in totals, excluded from every mean
        _row("i3", "ERROR: task crashed", {"m1": "N/A", "m2": "N/A"}),
    ]
    _write_run_csv(results_dir, ["m1", "m2"], rows)

    run = None
    index = RunDiscovery(str(results_dir)).scan(force_refresh=True)
    for models in index.to_dict()["tasks"].values():
        for runs in models.values():
            run = runs[0]
    assert run is not None

    # Behavior change (audit EI-1): previously every metric on an error row
    # accumulated 0.0 (and i1's healthy m2 was zeroed because only the FIRST
    # metric was checked). Now exclusion is per-metric:
    # m1: scores [1.0 (i0), 0.0 (i2)] -> 0.5 ; errors: i1, i3
    # m2: scores [0.5 (i0), 1.0 (i1)] -> 0.75 ; errors: i2, i3
    assert run["metric_averages"]["m1"] == pytest.approx(0.5)
    assert run["metric_averages"]["m2"] == pytest.approx(0.75)
    assert run["metric_error_counts"] == {"m1": 2, "m2": 2}

    # Row-level totals: only i3 is a failed item; i1/i2 completed.
    assert run["total_items"] == 4
    assert run["error_count"] == 1
    assert run["success_count"] == 3
    assert run["success_rate"] == pytest.approx(3 / 4)


def test_run_discovery_row_with_all_metrics_errored_counts_as_error_row(tmp_path):
    results_dir = tmp_path / "qym_results"
    rows = [
        _row("i0", "ok", {"m1": 1.0}),
        # output is fine but the only metric errored on every metric ->
        # excluded from means, still counted in totals as a failed row.
        _row("i1", "ok", {"m1": "ERROR: judge blew up"}),
    ]
    _write_run_csv(results_dir, ["m1"], rows)

    index = RunDiscovery(str(results_dir)).scan(force_refresh=True)
    run = None
    for models in index.to_dict()["tasks"].values():
        for runs in models.values():
            run = runs[0]

    assert run["metric_averages"]["m1"] == pytest.approx(1.0)
    assert run["metric_error_counts"]["m1"] == 1
    assert run["error_count"] == 1
    assert run["success_count"] == 1


# ---------------------------------------------------------------------------
# CSV checkpoint round-trip: error markers must survive (spec item 6)
# ---------------------------------------------------------------------------


def test_checkpoint_round_trip_preserves_per_metric_errors(tmp_path):
    path = tmp_path / "ckpt.csv"
    writer = CheckpointWriter(str(path), metrics=["m1", "m2"])
    writer.open()
    # Evaluator serializes a top-level error dict as "ERROR: ..." in the
    # score cell, and nested metadata errors as score + __meta__json.
    writer.append_row(_row("i0", "ok", {"m1": "ERROR: judge blew up", "m2": 0.9}))
    writer.append_row(
        _row(
            "i1",
            "ok",
            {"m1": 0.7, "m2": 0.0},
            metric_meta={"m2": {"error": "metric timeout after 120s"}},
        )
    )
    writer.close()

    # Resume-side state: neither row is a whole-item failure (each still has
    # at least one healthy metric).
    state = load_checkpoint_state(str(path))
    assert state.completed_item_ids == {"i0", "i1"}
    assert state.error_item_ids == set()

    # Rebuild an EvaluationResult the way the evaluator does on resume and
    # verify the errors are still recognized and excluded from stats.
    result = EvaluationResult(dataset_name="ds", run_name="run", metrics=["m1", "m2"])
    for raw in iter_checkpoint_rows(str(path)):
        item_id, row_result, is_err = parse_checkpoint_row(raw, ["m1", "m2"])
        assert is_err is False
        result.add_result(item_id, row_result)

    m1 = result.get_metric_stats("m1")
    assert m1["mean"] == pytest.approx(0.7)
    assert m1["error_count"] == 1

    m2 = result.get_metric_stats("m2")
    assert m2["mean"] == pytest.approx(0.9)
    assert m2["error_count"] == 1


def test_checkpoint_round_trip_task_failure_row_is_error(tmp_path):
    path = tmp_path / "ckpt.csv"
    writer = CheckpointWriter(str(path), metrics=["m1"])
    writer.open()
    writer.append_row(_row("i0", "ERROR: task crashed", {"m1": "N/A"}))
    writer.close()

    state = load_checkpoint_state(str(path))
    assert state.error_item_ids == {"i0"}

    raw = next(iter(iter_checkpoint_rows(str(path))))
    _, _, is_err = parse_checkpoint_row(raw, ["m1"])
    assert is_err is True
