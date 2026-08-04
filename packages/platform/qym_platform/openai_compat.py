from __future__ import annotations

from typing import Any


def _should_retry_with_max_completion_tokens(exc: Exception) -> bool:
    message = str(exc).lower()
    return "max_tokens" in message and "max_completion_tokens" in message


def _should_retry_without_response_format(exc: Exception) -> bool:
    message = str(exc).lower()
    return "response_format" in message and any(
        marker in message
        for marker in (
            "unsupported",
            "not supported",
            "unknown",
            "unrecognized",
            "invalid",
        )
    )


async def create_chat_completion_compat(client: Any, **kwargs: Any) -> Any:
    """Call chat completions with bounded compatibility retries."""
    call_kwargs = dict(kwargs)
    changed_max_tokens = False
    removed_response_format = False
    for attempt in range(3):
        try:
            return await client.chat.completions.create(**call_kwargs)
        except Exception as exc:
            if (
                not changed_max_tokens
                and "max_tokens" in call_kwargs
                and _should_retry_with_max_completion_tokens(exc)
            ):
                call_kwargs["max_completion_tokens"] = call_kwargs.pop("max_tokens")
                changed_max_tokens = True
                continue
            if (
                not removed_response_format
                and "response_format" in call_kwargs
                and _should_retry_without_response_format(exc)
            ):
                call_kwargs.pop("response_format", None)
                removed_response_format = True
                continue
            raise
    raise RuntimeError("LLM compatibility retries were exhausted")
