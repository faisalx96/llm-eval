"""Run-owned, event-loop-scoped HTTP clients for judge metrics."""

from __future__ import annotations

import asyncio
import contextvars
import logging
from contextlib import asynccontextmanager
from typing import Any, Dict, Tuple

from ..judge_config import JudgeConfig

logger = logging.getLogger(__name__)
_active_scope: contextvars.ContextVar[Any] = contextvars.ContextVar(
    "qym_judge_client_scope", default=None
)


async def _finish_cleanup(coro) -> None:
    """Finish resource cleanup before propagating cancellation to the caller."""
    task = asyncio.create_task(coro)
    cancelled = False
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            cancelled = True
    task.result()
    if cancelled:
        raise asyncio.CancelledError


class _JudgeClientScope:
    def __init__(self) -> None:
        self.loop = asyncio.get_running_loop()
        self.clients: Dict[Tuple[Any, ...], Any] = {}
        self.closed = False

    def client(self, config: JudgeConfig):
        from openai import AsyncOpenAI

        if self.closed or self.loop is not asyncio.get_running_loop():
            raise RuntimeError(
                "Judge client scope is closed or belongs to another loop"
            )
        # Models/prompts can share a transport; credentials, endpoint and timeout
        # cannot. Include the constructor so patched/custom clients do not leak
        # across otherwise identical configurations.
        key = (AsyncOpenAI, config.api_key, config.base_url, config.timeout)
        if key not in self.clients:
            self.clients[key] = AsyncOpenAI(
                api_key=config.api_key,
                base_url=config.base_url,
                timeout=config.timeout,
            )
        return self.clients[key]

    async def close(self) -> None:
        self.closed = True
        clients, self.clients = list(self.clients.values()), {}
        for client in clients:
            try:
                await client.close()
            except Exception:
                logger.warning(
                    "Failed to close an LLM judge HTTP client", exc_info=True
                )


@asynccontextmanager
async def judge_client_scope():
    """Own clients for one evaluator invocation, including exceptional exits."""
    scope = _JudgeClientScope()
    token = _active_scope.set(scope)
    try:
        yield scope
    finally:
        _active_scope.reset(token)
        await _finish_cleanup(scope.close())


@asynccontextmanager
async def borrow_judge_client(config: JudgeConfig):
    """Reuse the current run's client; standalone judge calls own a short scope."""
    scope = _active_scope.get()
    if (
        scope is not None
        and not scope.closed
        and scope.loop is asyncio.get_running_loop()
    ):
        yield scope.client(config)
    else:
        async with judge_client_scope() as owned:
            yield owned.client(config)
