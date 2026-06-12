"""Audit EI-3: CheckpointWriter must respect an existing checkpoint header.

Resuming a run used to regenerate the CSV header from the CURRENT metric
order while appending to a file whose header had the OLD order — values
silently landed under the wrong columns. The writer now reuses the existing
header as its fieldnames and refuses to append when the metric sets differ.
"""

import csv

import pytest

from qym.core.checkpoint import (
    CheckpointWriter,
    build_checkpoint_header,
    load_checkpoint_state,
    serialize_checkpoint_row,
)


def _row(item_id, scores, metric_meta=None):
    return serialize_checkpoint_row(
        dataset_name="ds",
        run_name="run",
        run_metadata={},
        run_config={},
        trace_id=f"t-{item_id}",
        item_id=item_id,
        item_input=f"input-{item_id}",
        item_metadata={},
        output="ok",
        expected_output="exp",
        time_seconds=0.1,
        task_started_at_ms=1,
        scores=scores,
        metric_meta=metric_meta or {},
    )


def _read(path):
    with open(path, "r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return reader.fieldnames, list(reader)


def test_resume_with_reordered_metrics_lands_values_under_correct_columns(tmp_path):
    path = tmp_path / "ckpt.csv"

    writer = CheckpointWriter(str(path), metrics=["a", "b"])
    writer.open()
    writer.append_row(_row("item_0", {"a": 0.1, "b": 0.9}))
    writer.close()

    # Resume the same run but with the metrics declared in a different order.
    resumed = CheckpointWriter(str(path), metrics=["b", "a"])
    resumed.open()
    resumed.append_row(_row("item_1", {"b": 0.8, "a": 0.2}))
    resumed.close()

    fieldnames, rows = _read(path)

    # Header keeps the ORIGINAL column order and is not duplicated.
    assert fieldnames == build_checkpoint_header(["a", "b"])
    assert len(rows) == 2
    assert all(r["item_id"] != "item_id" for r in rows)  # no second header row

    # Values land under the correct columns despite the reordered metrics.
    assert rows[0]["a_score"] == "0.1"
    assert rows[0]["b_score"] == "0.9"
    assert rows[1]["a_score"] == "0.2"
    assert rows[1]["b_score"] == "0.8"

    # And the resumed file still parses cleanly.
    state = load_checkpoint_state(str(path))
    assert state.completed_item_ids == {"item_0", "item_1"}
    assert state.metrics == ["a", "b"]


def test_resume_with_mismatched_metric_set_raises_naming_both_sets(tmp_path):
    path = tmp_path / "ckpt.csv"

    writer = CheckpointWriter(str(path), metrics=["a", "b"])
    writer.open()
    writer.append_row(_row("item_0", {"a": 0.1, "b": 0.9}))
    writer.close()

    mismatched = CheckpointWriter(str(path), metrics=["a", "c"])
    with pytest.raises(ValueError) as excinfo:
        mismatched.open()

    message = str(excinfo.value)
    # The error names BOTH metric sets so the user can see the mismatch.
    assert "'a'" in message and "'b'" in message and "'c'" in message

    # The existing file is untouched: same header, same single data row.
    fieldnames, rows = _read(path)
    assert fieldnames == build_checkpoint_header(["a", "b"])
    assert len(rows) == 1


def test_open_on_missing_or_empty_file_writes_fresh_header(tmp_path):
    missing = tmp_path / "fresh.csv"
    writer = CheckpointWriter(str(missing), metrics=["a"])
    writer.open()
    writer.append_row(_row("item_0", {"a": 1.0}))
    writer.close()
    fieldnames, rows = _read(missing)
    assert fieldnames == build_checkpoint_header(["a"])
    assert len(rows) == 1

    empty = tmp_path / "empty.csv"
    empty.write_text("", encoding="utf-8")
    writer = CheckpointWriter(str(empty), metrics=["a"])
    writer.open()
    writer.append_row(_row("item_1", {"a": 0.5}))
    writer.close()
    fieldnames, rows = _read(empty)
    assert fieldnames == build_checkpoint_header(["a"])
    assert len(rows) == 1


def test_resume_header_only_file_appends_without_duplicate_header(tmp_path):
    path = tmp_path / "header_only.csv"
    writer = CheckpointWriter(str(path), metrics=["a", "b"])
    writer.open()
    writer.close()  # header written, no rows yet

    resumed = CheckpointWriter(str(path), metrics=["b", "a"])
    resumed.open()
    resumed.append_row(_row("item_0", {"a": 0.3, "b": 0.7}))
    resumed.close()

    fieldnames, rows = _read(path)
    assert fieldnames == build_checkpoint_header(["a", "b"])
    assert len(rows) == 1
    assert rows[0]["a_score"] == "0.3"
    assert rows[0]["b_score"] == "0.7"


def test_resume_preserves_extra_audit_columns(tmp_path):
    """Files edited by the dashboard gain audit columns; appends must not break."""
    path = tmp_path / "audited.csv"
    header = build_checkpoint_header(["a"]) + ["a__meta__modified"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=header)
        w.writeheader()
        row = _row("item_0", {"a": 1.0})
        row["a__meta__modified"] = "true"
        w.writerow(row)

    resumed = CheckpointWriter(str(path), metrics=["a"])
    resumed.open()
    resumed.append_row(_row("item_1", {"a": 0.5}))
    resumed.close()

    fieldnames, rows = _read(path)
    assert fieldnames == header
    assert len(rows) == 2
    assert rows[1]["a_score"] == "0.5"
    assert rows[1]["a__meta__modified"] == ""  # restval fills missing keys
