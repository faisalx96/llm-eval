"""run_started platform event emission (HP-4 regression tests).

The run_started seed event used to reference ``self.total_items`` (an
attribute that does not exist) inside a swallowed try/except, so the event
silently never fired. These tests drive the real arun() emit path with a spy
event stream (no HTTP) and assert the event carries the dataset size.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import pytest

import qym.core.evaluator as evaluator_module
from qym.core.dataset import InMemoryDataset
from qym.core.evaluator import Evaluator


class _FakeRunHandle:
    run_id = "run-spy-123"
    live_url = "http://platform.test/runs/run-spy-123"


class _FakePlatformClient:
    """Stands in for PlatformClient: create_run succeeds without HTTP."""

    def __init__(self, platform_url: str, api_key: str) -> None:
        self.platform_url = platform_url
        self.api_key = api_key

    def create_run(self, **kwargs: Any) -> _FakeRunHandle:
        return _FakeRunHandle()


class _SpyEventStream:
    """Stands in for PlatformEventStream: records emits, no threads/HTTP."""

    instances: List["_SpyEventStream"] = []

    def __init__(self, platform_url: str, api_key: str, run_id: str) -> None:
        self.platform_url = platform_url
        self.api_key = api_key
        self.run_id = run_id
        self.events: List[Tuple[str, Dict[str, Any]]] = []
        self.closed = False
        _SpyEventStream.instances.append(self)

    def emit(self, type_: str, payload: Dict[str, Any], *, sync: bool = False) -> None:
        self.events.append((type_, payload))

    def flush(self, timeout: Optional[float] = None) -> bool:
        return True

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def spy_stream(monkeypatch):
    _SpyEventStream.instances = []
    monkeypatch.setattr(evaluator_module, "PlatformClient", _FakePlatformClient)
    monkeypatch.setattr(evaluator_module, "PlatformEventStream", _SpyEventStream)
    yield _SpyEventStream
    _SpyEventStream.instances = []


def _echo_task(text):
    return text


def _exact(output, expected):
    return 1.0 if output == expected else 0.0


@pytest.mark.asyncio
async def test_run_started_emitted_with_total_items(spy_stream):
    items = [
        {"id": f"item-{i}", "input": f"value-{i}", "expected_output": f"value-{i}"}
        for i in range(3)
    ]
    dataset = InMemoryDataset(items, name="run-started-ds")

    evaluator = Evaluator(
        task=_echo_task,
        dataset=dataset,
        metrics=[_exact],
        config={
            "run_name": "run-started-test",
            "checkpoint_enabled": False,
            "platform_api_key": "test-key",
            "max_concurrency": 2,
        },
    )

    result = await evaluator.arun(show_tui=False)

    assert len(spy_stream.instances) == 1
    stream = spy_stream.instances[0]
    emitted_types = [t for t, _ in stream.events]
    run_started_payloads = [p for t, p in stream.events if t == "run_started"]
    assert len(run_started_payloads) == 1, (
        f"expected exactly one run_started event, got: {emitted_types}"
    )

    payload = run_started_payloads[0]
    assert payload["total_items"] == len(items) == 3
    assert payload["dataset"] == "run-started-ds"
    assert payload["run_metadata"]["total_items"] == 3
    assert payload["run_config"]["run_name"] == evaluator.run_name
    assert payload["started_at"]

    # The run itself completed and run_completed was sent through the stream.
    assert result.total_items == 3
    assert "run_completed" in emitted_types
    assert stream.closed is True


@pytest.mark.asyncio
async def test_run_started_precedes_item_events(spy_stream):
    items = [{"id": "only", "input": "x", "expected_output": "x"}]
    dataset = InMemoryDataset(items, name="ordering-ds")

    evaluator = Evaluator(
        task=_echo_task,
        dataset=dataset,
        metrics=[_exact],
        config={
            "run_name": "run-started-ordering",
            "checkpoint_enabled": False,
            "platform_api_key": "test-key",
            "max_concurrency": 1,
        },
    )

    await evaluator.arun(show_tui=False)

    stream = spy_stream.instances[0]
    emitted_types = [t for t, _ in stream.events]
    assert emitted_types, "no platform events were emitted"
    assert emitted_types[0] == "run_started"
