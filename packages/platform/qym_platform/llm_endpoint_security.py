"""Runtime SSRF protections for OpenAI-compatible LLM endpoints."""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

import httpx


class LlmEndpointValidationError(ValueError):
    """Raised when an LLM endpoint is unsafe or malformed."""


def validate_llm_base_url(value: str, *, allow_private: bool) -> str:
    """Validate an LLM URL against the addresses it resolves to now."""
    normalized = str(value or "").strip().rstrip("/")
    parsed = urlparse(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise LlmEndpointValidationError(
            "LLM base URL must be an absolute http:// or https:// URL"
        )
    if parsed.username or parsed.password or parsed.fragment:
        raise LlmEndpointValidationError(
            "LLM base URL cannot contain credentials or a URL fragment"
        )
    if allow_private:
        return normalized
    try:
        addresses = {
            ipaddress.ip_address(sockaddr[0])
            for *_, sockaddr in socket.getaddrinfo(
                parsed.hostname, parsed.port or 443
            )
        }
    except (OSError, ValueError) as exc:
        raise LlmEndpointValidationError(
            "LLM base URL hostname could not be resolved"
        ) from exc
    if not addresses or any(not address.is_global for address in addresses):
        raise LlmEndpointValidationError(
            "LLM base URL resolves to a non-public address. Set "
            "QYM_ALLOW_PRIVATE_LLM_BASE_URLS=true only for trusted local providers."
        )
    return normalized


class ValidatingAsyncTransport(httpx.AsyncBaseTransport):
    """Re-check DNS immediately before each LLM HTTP request."""

    def __init__(self, *, allow_private: bool) -> None:
        self._allow_private = allow_private
        self._transport = httpx.AsyncHTTPTransport(retries=0)

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        validate_llm_base_url(str(request.url), allow_private=self._allow_private)
        return await self._transport.handle_async_request(request)

    async def aclose(self) -> None:
        await self._transport.aclose()


def create_llm_http_client(*, allow_private: bool) -> httpx.AsyncClient:
    """Create a client that blocks redirects and validates every hop target."""
    return httpx.AsyncClient(
        transport=ValidatingAsyncTransport(allow_private=allow_private),
        follow_redirects=False,
    )
