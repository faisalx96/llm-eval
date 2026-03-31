from __future__ import annotations

from typing import Any


def _should_retry_with_max_completion_tokens(exc: Exception) -> bool:
    message = str(exc)
    return (
        "Unsupported parameter: 'max_tokens'" in message
        and "max_completion_tokens" in message
    )


async def create_chat_completion_compat(client: Any, **kwargs: Any) -> Any:
    """Call chat completions and retry with max_completion_tokens when required."""
    try:
        return await client.chat.completions.create(**kwargs)
    except Exception as exc:
        if not _should_retry_with_max_completion_tokens(exc):
            raise
        if "max_tokens" not in kwargs:
            raise

        retry_kwargs = dict(kwargs)
        retry_kwargs["max_completion_tokens"] = retry_kwargs.pop("max_tokens")
        return await client.chat.completions.create(**retry_kwargs)
