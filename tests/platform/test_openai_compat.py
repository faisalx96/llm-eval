from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from qym_platform.openai_compat import create_chat_completion_compat


@pytest.mark.asyncio
async def test_retries_with_max_completion_tokens() -> None:
    create = AsyncMock(
        side_effect=[
            ValueError(
                "Unsupported parameter: 'max_tokens'; use 'max_completion_tokens'"
            ),
            SimpleNamespace(choices=[]),
        ]
    )
    client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))
    )

    await create_chat_completion_compat(
        client, model="reasoning-model", messages=[], max_tokens=123
    )

    assert create.await_count == 2
    assert "max_tokens" not in create.await_args.kwargs
    assert create.await_args.kwargs["max_completion_tokens"] == 123


@pytest.mark.asyncio
async def test_retries_without_unsupported_response_format() -> None:
    create = AsyncMock(
        side_effect=[
            ValueError("response_format is not supported by this provider"),
            SimpleNamespace(choices=[]),
        ]
    )
    client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))
    )

    await create_chat_completion_compat(
        client,
        model="compatible-model",
        messages=[],
        response_format={"type": "json_object"},
    )

    assert create.await_count == 2
    assert "response_format" not in create.await_args.kwargs
