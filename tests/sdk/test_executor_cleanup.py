"""Default thread-pool executor cleanup (HP-5 regression tests).

arun() used to call ``loop.get_default_executor()`` — not a real asyncio
API — inside a swallowed try/except, so the sized ThreadPoolExecutor was
never shut down and ``asyncio.run()`` could hang on idle worker threads.
The fix stores the executor on the evaluator/runner and shuts it down
explicitly; these tests assert the stored executor is actually shut down
after a tiny sync-task eval completes.
"""

from __future__ import annotations

import asyncio
import time

import pytest

import qym.core.evaluator as evaluator_module
from qym.core.dataset import InMemoryDataset
from qym.core.evaluator import Evaluator
from qym.core.multi_runner import MultiModelRunner


def _echo_task(text):
    # Plain sync function: runs via loop.run_in_executor on the default pool.
    return text


def _exact(output, expected):
    return 1.0 if output == expected else 0.0


def _tiny_items(n: int = 2):
    return [
        {"id": f"item-{i}", "input": f"value-{i}", "expected_output": f"value-{i}"}
        for i in range(n)
    ]


@pytest.mark.asyncio
async def test_sync_task_eval_shuts_down_default_executor(monkeypatch):
    # Keep the run fully offline: no platform branch.
    monkeypatch.setattr(evaluator_module, "PlatformClient", None)
    monkeypatch.delenv("QYM_API_KEY", raising=False)

    dataset = InMemoryDataset(_tiny_items(), name="executor-cleanup-ds")
    evaluator = Evaluator(
        task=_echo_task,
        dataset=dataset,
        metrics=[_exact],
        config={
            "run_name": "executor-cleanup",
            "checkpoint_enabled": False,
            "max_concurrency": 2,
        },
    )

    start = time.monotonic()
    result = await asyncio.wait_for(evaluator.arun(show_tui=False), timeout=60)
    elapsed = time.monotonic() - start

    assert result.total_items == 2
    assert elapsed < 30, f"tiny sync eval took {elapsed:.1f}s — executor likely hung"

    executor = evaluator._default_executor
    assert executor is not None, "evaluator did not store the executor it created"
    assert executor._shutdown is True, "default executor was not shut down"
    # The loop flag is reset so a later run on the same loop gets a fresh pool.
    loop = asyncio.get_running_loop()
    assert getattr(loop, "_qym_executor_set", False) is False


@pytest.mark.asyncio
async def test_multi_runner_shuts_down_default_executor(monkeypatch):
    monkeypatch.setattr(evaluator_module, "PlatformClient", None)
    monkeypatch.delenv("QYM_API_KEY", raising=False)

    runner = MultiModelRunner.from_runs(
        [
            {
                "task": _echo_task,
                "dataset": InMemoryDataset(_tiny_items(), name="multi-cleanup-ds"),
                "metrics": [_exact],
                "config": {
                    "run_name": "multi-executor-cleanup",
                    "checkpoint_enabled": False,
                    "max_concurrency": 2,
                },
            }
        ]
    )

    results = await asyncio.wait_for(
        runner.arun(show_tui=False, auto_save=False), timeout=60
    )

    assert len(results) == 1
    assert results[0].total_items == 2

    executor = runner._default_executor
    assert executor is not None, "runner did not store the executor it created"
    assert executor._shutdown is True, "runner default executor was not shut down"
