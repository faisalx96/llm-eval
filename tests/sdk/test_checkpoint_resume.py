from qym.core.checkpoint import (
    CheckpointWriter,
    load_checkpoint_state,
    iter_checkpoint_rows,
    parse_checkpoint_row,
    serialize_checkpoint_row,
)


def test_checkpoint_round_trip(tmp_path):
    path = tmp_path / "checkpoint.csv"
    writer = CheckpointWriter(str(path), metrics=["m1"])
    writer.open()

    row = serialize_checkpoint_row(
        dataset_name="ds",
        run_name="run",
        run_metadata={},
        run_config={},
        trace_id="t1",
        item_id="item_0",
        item_input="input",
        item_metadata={"a": 1},
        output="out",
        expected_output="exp",
        time_seconds=0.2,
        task_started_at_ms=123,
        scores={"m1": 0.75},
        metric_meta={"m1": {"note": "ok"}},
    )
    writer.append_row(row)
    writer.close()

    state = load_checkpoint_state(str(path))
    assert state is not None
    assert state.completed_item_ids == {"item_0"}
    assert state.error_item_ids == set()

    rows = list(iter_checkpoint_rows(str(path)))
    assert len(rows) == 1
    item_id, result, is_error = parse_checkpoint_row(rows[0], ["m1"])
    assert item_id == "item_0"
    assert is_error is False
    score = result["scores"]["m1"]
    assert isinstance(score, dict)
    assert score["score"] == 0.75
