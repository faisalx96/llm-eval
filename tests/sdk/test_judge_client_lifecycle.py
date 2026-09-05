"""Judge HTTP ownership across runs, loops, failures and cancellation."""

import asyncio
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from qym.core.dataset import InMemoryDataset
from qym.core.evaluator import Evaluator
from qym.metrics.judge_config import JudgeConfig
from qym.metrics.judges._client import (
    _active_scope,
    borrow_judge_client,
    judge_client_scope,
)
from qym.metrics.judges.base import llm_judge


@pytest.fixture
def clients(monkeypatch):
    created = []

    def factory(**kwargs):
        client = SimpleNamespace(settings=kwargs, close=AsyncMock())
        created.append(client)
        return client

    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(AsyncOpenAI=factory))
    response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content='{"verdict":"yes","explanation":"ok"}')
            )
        ]
    )
    monkeypatch.setattr(
        "qym.metrics.judges.base._call_with_retry", AsyncMock(return_value=response)
    )
    return created


def config(**overrides):
    return JudgeConfig(
        **{
            "model": "test",
            "api_key": "not-secret",
            "base_url": "http://unused.invalid",
            **overrides,
        }
    )


async def judge(cfg=None):
    return await llm_judge(
        system_prompt="test",
        user_prompt="test",
        choices={"yes": 1.0},
        config=cfg or config(),
    )


@pytest.mark.asyncio
async def test_run_scope_reuses_one_client_for_parallel_metrics_and_closes_once(
    clients,
):
    async with judge_client_scope():
        results = await asyncio.gather(*(judge() for _ in range(100)))
        assert all(result.score == 1.0 for result in results)
        assert len(clients) == 1
        clients[0].close.assert_not_awaited()
    clients[0].close.assert_awaited_once()
    assert _active_scope.get() is None


@pytest.mark.asyncio
async def test_connection_settings_are_isolated_but_models_reuse_transport(clients):
    async with judge_client_scope():
        for cfg in (
            config(),
            config(model="another"),
            config(api_key="second-key"),
            config(base_url="http://other.invalid"),
            config(timeout=2.0),
            config(),
        ):
            await judge(cfg)
        assert len(clients) == 4
    for client in clients:
        client.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_overlapping_runs_do_not_close_each_others_clients(clients):
    release = asyncio.Event()
    ready = asyncio.Event()

    async def longer():
        async with judge_client_scope():
            await judge()
            own = clients[-1]
            ready.set()
            await release.wait()
            own.close.assert_not_awaited()
            await judge()

    task = asyncio.create_task(longer())
    await ready.wait()
    async with judge_client_scope():
        await judge()
    assert len(clients) == 2
    clients[0].close.assert_not_awaited()
    clients[1].close.assert_awaited_once()
    release.set()
    await task
    clients[0].close.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mode", ["success", "request_error", "invalid_response", "cancel"]
)
async def test_standalone_calls_close_on_every_exit(clients, monkeypatch, mode):
    if mode == "request_error":
        monkeypatch.setattr(
            "qym.metrics.judges.base._call_with_retry",
            AsyncMock(side_effect=RuntimeError("fail")),
        )
    elif mode == "invalid_response":
        response = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="invalid"))]
        )
        monkeypatch.setattr(
            "qym.metrics.judges.base._call_with_retry", AsyncMock(return_value=response)
        )
    elif mode == "cancel":
        monkeypatch.setattr(
            "qym.metrics.judges.base._call_with_retry",
            AsyncMock(side_effect=asyncio.CancelledError),
        )
    if mode == "cancel":
        with pytest.raises(asyncio.CancelledError):
            await judge()
    else:
        await judge()
    assert len(clients) == 1
    clients[0].close.assert_awaited_once()


@pytest.mark.asyncio
async def test_cancel_during_close_finishes_cleanup_before_propagating(clients):
    entered, release = asyncio.Event(), asyncio.Event()

    async def close():
        entered.set()
        await release.wait()

    async def run():
        async with judge_client_scope():
            await judge()
            clients[0].close.side_effect = close

    task = asyncio.create_task(run())
    await entered.wait()
    task.cancel()
    await asyncio.sleep(0)
    task.cancel()
    assert not task.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    clients[0].close.assert_awaited_once()


@pytest.mark.asyncio
async def test_one_close_failure_does_not_skip_other_clients(clients):
    async with judge_client_scope():
        await judge()
        await judge(config(api_key="second"))
        clients[0].close.side_effect = RuntimeError("close failed")
    for client in clients:
        client.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_inherited_scope_is_not_reused_on_another_event_loop(clients):
    async with judge_client_scope():
        await judge()
        # to_thread copies ContextVars, but asyncio.run creates a different loop.
        await asyncio.to_thread(lambda: asyncio.run(judge()))
        assert len(clients) == 2
        clients[0].close.assert_not_awaited()
        clients[1].close.assert_awaited_once()
    clients[0].close.assert_awaited_once()


@pytest.mark.asyncio
async def test_evaluator_owns_one_client_for_all_items_and_releases_after_run(clients):
    async def task(input):
        return input

    async def metric(output, expected):
        return await judge()

    ev = Evaluator(
        task,
        InMemoryDataset([{"input": "hi", "expected": "hi"} for _ in range(20)]),
        [metric],
        config={
            "otel_enabled": False,
            "live_mode": "local",
            "checkpoint_enabled": False,
        },
    )
    result = await ev.arun(show_tui=False)
    assert len(result.results) == 20
    assert len(clients) == 1
    clients[0].close.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error", [RuntimeError("run failed"), asyncio.CancelledError()]
)
async def test_evaluator_exception_path_also_releases_client(
    clients, monkeypatch, error
):
    async def task(input):
        return input

    ev = Evaluator(task, InMemoryDataset([]), [], config={"otel_enabled": False})

    async def fail(*args):
        await judge()
        raise error

    monkeypatch.setattr(ev, "_arun", fail)
    with pytest.raises(type(error)):
        await ev.arun(show_tui=False)
    clients[0].close.assert_awaited_once()
