import csv
from pathlib import Path

from qym.core.checkpoint import build_checkpoint_header, serialize_checkpoint_row
from qym.core.run_discovery import RunDiscovery


def _write_checkpoint_rows(path: Path, metrics, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    header = build_checkpoint_header(metrics)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=header)
        writer.writeheader()
        writer.writerows(rows)


def _build_row(
    *,
    run_metadata,
    item_id,
    output,
    score,
    item_metadata=None,
    item_input=None,
    expected_output="expected",
):
    return serialize_checkpoint_row(
        dataset_name="dataset_a",
        run_name="run-250101-0101",
        run_metadata=run_metadata,
        run_config={"max_concurrency": 4, "timeout": 30},
        trace_id=f"trace-{item_id}",
        item_id=item_id,
        item_input=item_input if item_input is not None else f"input-{item_id}",
        item_metadata=item_metadata or {},
        output=output,
        expected_output=expected_output,
        time_seconds=0.25,
        task_started_at_ms=123,
        scores={"accuracy": score},
        metric_meta={},
    )


def _first_run_payload(data):
    for models in data.get("tasks", {}).values():
        for runs in models.values():
            if runs:
                return runs[0]
    raise AssertionError("No runs found in payload")


def test_run_discovery_uses_declared_total_for_completion(tmp_path):
    results_dir = tmp_path / "qym_results"
    csv_path = (
        results_dir
        / "task_alpha"
        / "provider-model"
        / "2025-01-01"
        / "run-250101-0101.csv"
    )

    rows = [
        _build_row(
            run_metadata={
                "model": "provider/model-a",
                "total_items": 5,
            },
            item_id="item_0",
            output="ok",
            score=1.0,
        ),
        _build_row(
            run_metadata={
                "model": "provider/model-a",
                "total_items": 5,
                "langfuse_dataset_id": "dataset-123",
                "langfuse_run_id": "run-123",
            },
            item_id="item_1",
            output="ERROR: boom",
            score="N/A",
        ),
    ]
    _write_checkpoint_rows(csv_path, ["accuracy"], rows)

    discovery = RunDiscovery(str(results_dir))
    index = discovery.scan(force_refresh=True)
    run = _first_run_payload(index.to_dict())

    assert run["total_items"] == 5
    assert run["success_count"] == 1
    assert run["error_count"] == 1
    assert run["langfuse_dataset_id"] == "dataset-123"
    assert run["langfuse_run_id"] == "run-123"
    assert run["model_name"] == "model-a"
    completion = (run["success_count"] + run["error_count"]) / run["total_items"]
    assert completion == 0.4


def test_run_discovery_builds_compare_ids_from_legacy_positional_item_ids(tmp_path):
    results_dir = tmp_path / "qym_results"
    csv_path = (
        results_dir
        / "task_alpha"
        / "provider-model"
        / "2025-01-01"
        / "run-250101-0101.csv"
    )

    rows = [
        _build_row(
            run_metadata={"model": "provider/model-a"},
            item_id="row_000000",
            output="ok",
            score=1.0,
        ),
        _build_row(
            run_metadata={"model": "provider/model-a"},
            item_id="row_000001",
            output="ok",
            score=0.0,
        ),
    ]
    _write_checkpoint_rows(csv_path, ["accuracy"], rows)

    data = RunDiscovery(str(results_dir)).get_run_data(str(csv_path))
    snapshot_rows = data["snapshot"]["rows"]

    assert data["run"]["compare_alignment_status"] == "aligned"
    assert snapshot_rows[0]["item_id"] == "row_000000"
    assert snapshot_rows[0]["compare_item_id"].startswith("csv_")
    assert snapshot_rows[1]["compare_item_id"].startswith("csv_")
    assert snapshot_rows[0]["compare_item_id"] != snapshot_rows[1]["compare_item_id"]


def test_run_discovery_compare_ids_match_reordered_legacy_rows(tmp_path):
    results_dir = tmp_path / "qym_results"
    csv_path_a = (
        results_dir
        / "task_alpha"
        / "provider-model-a"
        / "2025-01-01"
        / "run-250101-0101.csv"
    )
    csv_path_b = (
        results_dir
        / "task_alpha"
        / "provider-model-b"
        / "2025-01-01"
        / "run-250101-0202.csv"
    )

    rows_a = [
        _build_row(
            run_metadata={"model": "provider/model-a"},
            item_id="row_000000",
            output="ok",
            score=1.0,
        ),
        _build_row(
            run_metadata={"model": "provider/model-a"},
            item_id="row_000001",
            output="ok",
            score=0.0,
        ),
    ]
    rows_b = [rows_a[1], rows_a[0]]
    _write_checkpoint_rows(csv_path_a, ["accuracy"], rows_a)
    _write_checkpoint_rows(csv_path_b, ["accuracy"], rows_b)

    discovery = RunDiscovery(str(results_dir))
    data_a = discovery.get_run_data(str(csv_path_a))
    data_b = discovery.get_run_data(str(csv_path_b))

    compare_ids_a = {row["input"]: row["compare_item_id"] for row in data_a["snapshot"]["rows"]}
    compare_ids_b = {row["input"]: row["compare_item_id"] for row in data_b["snapshot"]["rows"]}

    assert compare_ids_a == compare_ids_b


def test_run_discovery_compare_ids_ignore_trace_stats_differences(tmp_path):
    results_dir = tmp_path / "qym_results"
    csv_path_a = (
        results_dir
        / "task_alpha"
        / "provider-model-a"
        / "2025-01-01"
        / "run-250101-0101.csv"
    )
    csv_path_b = (
        results_dir
        / "task_alpha"
        / "provider-model-b"
        / "2025-01-01"
        / "run-250101-0202.csv"
    )

    rows_a = [
        _build_row(
            run_metadata={"model": "provider/model-a"},
            item_id="row_000000",
            output="ok",
            score=1.0,
            item_metadata={"trace_stats": {"total_tokens": 42, "llm_calls": 1}},
        ),
        _build_row(
            run_metadata={"model": "provider/model-a"},
            item_id="row_000001",
            output="ok",
            score=0.0,
            item_metadata={"trace_stats": {"total_tokens": 84, "llm_calls": 2}},
        ),
    ]
    rows_b = [
        _build_row(
            run_metadata={"model": "provider/model-b"},
            item_id="row_000000",
            output="ok",
            score=1.0,
            item_metadata={"trace_stats": {"total_tokens": 420, "llm_calls": 3}},
        ),
        _build_row(
            run_metadata={"model": "provider/model-b"},
            item_id="row_000001",
            output="ok",
            score=0.0,
            item_metadata={"trace_stats": {"total_tokens": 840, "llm_calls": 4}},
        ),
    ]
    _write_checkpoint_rows(csv_path_a, ["accuracy"], rows_a)
    _write_checkpoint_rows(csv_path_b, ["accuracy"], rows_b)

    discovery = RunDiscovery(str(results_dir))
    data_a = discovery.get_run_data(str(csv_path_a))
    data_b = discovery.get_run_data(str(csv_path_b))

    compare_ids_a = {row["input"]: row["compare_item_id"] for row in data_a["snapshot"]["rows"]}
    compare_ids_b = {row["input"]: row["compare_item_id"] for row in data_b["snapshot"]["rows"]}

    assert compare_ids_a == compare_ids_b


def test_run_discovery_compare_ids_ignore_generated_csv_item_ids(tmp_path):
    results_dir = tmp_path / "qym_results"
    csv_path_a = (
        results_dir
        / "task_alpha"
        / "provider-model-a"
        / "2025-01-01"
        / "run-250101-0101.csv"
    )
    csv_path_b = (
        results_dir
        / "task_alpha"
        / "provider-model-b"
        / "2025-01-01"
        / "run-250101-0202.csv"
    )

    shared_input = "What is 2+2?"
    shared_expected = "4"

    rows_a = [
        _build_row(
            run_metadata={"model": "provider/model-a"},
            item_id="csv_9d87abc4a109c976c595__0001",
            item_input=shared_input,
            expected_output=shared_expected,
            output="ok",
            score=1.0,
        ),
    ]
    rows_b = [
        _build_row(
            run_metadata={"model": "provider/model-b"},
            item_id="csv_912a92090d65db565175__0001",
            item_input=shared_input,
            expected_output=shared_expected,
            output="ok",
            score=1.0,
        ),
    ]
    _write_checkpoint_rows(csv_path_a, ["accuracy"], rows_a)
    _write_checkpoint_rows(csv_path_b, ["accuracy"], rows_b)

    discovery = RunDiscovery(str(results_dir))
    data_a = discovery.get_run_data(str(csv_path_a))
    data_b = discovery.get_run_data(str(csv_path_b))

    compare_ids_a = [row["compare_item_id"] for row in data_a["snapshot"]["rows"]]
    compare_ids_b = [row["compare_item_id"] for row in data_b["snapshot"]["rows"]]

    assert compare_ids_a == compare_ids_b
