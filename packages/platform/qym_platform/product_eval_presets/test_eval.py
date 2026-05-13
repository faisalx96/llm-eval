"""Self-contained product eval preset for API smoke testing."""

from __future__ import annotations

import time
from typing import Any, Dict, List


MODEL = "test-model"
DEFAULT_RUN_NAME = "product-eval-test"


class TestDatasetItem:
    def __init__(
        self,
        *,
        id: str,
        input: Dict[str, Any],
        expected_output: Any,
        metadata: Dict[str, Any] | None = None,
    ) -> None:
        self.id = id
        self.input = input
        self.expected_output = expected_output
        self.metadata = metadata or {}


class TestDataset:
    name = "product-eval-test-dataset"

    def __init__(self) -> None:
        self._items: List[TestDatasetItem] = []
        for index in range(1, 51):
            text = f"item-{index:03d}"
            self._items.append(
                TestDatasetItem(
                    id=text,
                    input={"text": text, "delay_seconds": 5.0},
                    expected_output=text.upper(),
                    metadata={"case": "uppercase", "index": index},
                )
            )

    def get_items(self) -> List[TestDatasetItem]:
        return list(self._items)

    def __len__(self) -> int:
        return len(self._items)


EVAL_DATASET = TestDataset()


def test_task(text: str, delay_seconds: float = 5.0, **_: Any) -> str:
    time.sleep(delay_seconds)
    return text.upper()


def exact_match(output: Any, expected: Any, input_data: Any = None) -> Dict[str, Any]:
    return {
        "score": 1.0 if output == expected else 0.0,
        "metadata": {"expected": expected, "output": output},
    }
