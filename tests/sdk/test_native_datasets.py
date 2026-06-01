from __future__ import annotations

import json
from pathlib import Path

import pytest

from qym.core.dataset import InMemoryDataset, JsonlDataset, resolve_dataset
from qym.utils.errors import DatasetNotFoundError


def test_jsonl_dataset_generates_stable_item_id(tmp_path: Path) -> None:
    path = tmp_path / "items.jsonl"
    path.write_text(json.dumps({"input": {"q": "hi"}, "expected_output": "ok", "metadata": {"slice": "smoke"}}) + "\n")

    dataset = JsonlDataset(path)
    item = dataset.get_items()[0]

    assert item.id.startswith("ds_")
    assert item.input == {"q": "hi"}
    assert item.expected_output == "ok"
    assert item.metadata == {"slice": "smoke"}


def test_in_memory_dataset() -> None:
    dataset = InMemoryDataset([{"id": "a", "input": "x", "expected": "y"}], name="mem")

    assert dataset.name == "mem"
    assert dataset.get_items()[0].id == "a"
    assert len(dataset) == 1


def test_named_dataset_without_platform_config_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("QYM_BASE_URL", raising=False)
    monkeypatch.delenv("QYM_API_KEY", raising=False)

    with pytest.raises(DatasetNotFoundError):
        resolve_dataset("not-a-local-file")
