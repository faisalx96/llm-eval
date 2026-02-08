import csv
from pathlib import Path

from qym.core.checkpoint import build_checkpoint_header, serialize_checkpoint_row
from qym.core.run_discovery import RunDiscovery
from qym.server.dashboard_server import rebuild_langfuse_urls


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
):
    return serialize_checkpoint_row(
        dataset_name="dataset_a",
        run_name="run-250101-0101",
        run_metadata=run_metadata,
        run_config={"max_concurrency": 4, "timeout": 30},
        trace_id=f"trace-{item_id}",
        item_id=item_id,
        item_input=f"input-{item_id}",
        item_metadata={},
        output=output,
        expected_output="expected",
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


def test_dashboard_api_rebuilds_nested_langfuse_urls(tmp_path):
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
                "langfuse_dataset_id": "dataset-123",
                "langfuse_run_id": "run-123",
            },
            item_id="item_0",
            output="ok",
            score=1.0,
        )
    ]
    _write_checkpoint_rows(csv_path, ["accuracy"], rows)

    payload = RunDiscovery(str(results_dir)).scan(force_refresh=True).to_dict()
    rebuild_langfuse_urls(
        payload,
        langfuse_host="https://cloud.langfuse.com",
        langfuse_project_id="project-123",
    )

    run = _first_run_payload(payload)
    assert run["langfuse_url"] == (
        "https://cloud.langfuse.com/project/project-123/datasets/dataset-123/runs/run-123"
    )
