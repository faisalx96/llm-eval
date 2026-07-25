"""Runtime SSRF protections for OpenAI-compatible LLM endpoints."""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from urllib.parse import urlparse

import httpcore
import httpx


DNS_RESOLUTION_TIMEOUT_SECONDS = 5.0


class LlmEndpointValidationError(ValueError):
    """Raised when an LLM endpoint is unsafe or malformed."""


def _resolve_public_address(hostname: str, port: int, *, allow_private: bool) -> str:
    """Resolve one approved address that will be used for the socket connection."""
    if allow_private:
        return hostname
    try:
        addresses = {
            ipaddress.ip_address(sockaddr[0])
            for *_, sockaddr in socket.getaddrinfo(hostname, port)
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
    return str(sorted(addresses, key=str)[0])


def validate_llm_base_url(value: str, *, allow_private: bool) -> str:
    """Validate an LLM URL and resolve it once before creating a client."""
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
    _resolve_public_address(
        parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80),
        allow_private=allow_private,
    )
    return normalized


async def _resolve_public_address_async(
    hostname: str,
    port: int,
    *,
    allow_private: bool,
    timeout: float | None,
) -> str:
    """Resolve DNS off the event loop and cap it by the connection deadline."""
    if allow_private:
        return hostname
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(
                _resolve_public_address,
                hostname,
                port,
                allow_private=False,
            ),
            timeout=timeout or DNS_RESOLUTION_TIMEOUT_SECONDS,
        )
    except TimeoutError as exc:
        raise LlmEndpointValidationError("LLM base URL hostname resolution timed out") from exc


class PinnedAsyncNetworkBackend(httpcore.AsyncNetworkBackend):
    """Connect to the address we validated, while httpcore keeps host/SNI intact."""

    def __init__(self, *, allow_private: bool) -> None:
        self._allow_private = allow_private
        self._backend = httpcore.AnyIOBackend()

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: object = None,
    ) -> httpcore.AsyncNetworkStream:
        pinned_address = await _resolve_public_address_async(
            host,
            port,
            allow_private=self._allow_private,
            timeout=timeout,
        )
        return await self._backend.connect_tcp(
            pinned_address,
            port,
            timeout=timeout,
            local_address=local_address,
            socket_options=socket_options,
        )

    async def connect_unix_socket(
        self, path: str, timeout: float | None = None, socket_options: object = None
    ) -> httpcore.AsyncNetworkStream:
        raise LlmEndpointValidationError("Unix-socket LLM endpoints are not allowed")

    async def sleep(self, seconds: float) -> None:
        await self._backend.sleep(seconds)


class PinnedAsyncTransport(httpx.AsyncHTTPTransport):
    """HTTP transport whose TCP connections cannot perform a second DNS lookup."""

    def __init__(self, *, allow_private: bool) -> None:
        super().__init__(retries=0)
        self._pool = httpcore.AsyncConnectionPool(
            retries=0,
            network_backend=PinnedAsyncNetworkBackend(allow_private=allow_private),
        )



def create_llm_http_client(*, allow_private: bool) -> httpx.AsyncClient:
    """Create a client that blocks redirects and validates every hop target."""
    return httpx.AsyncClient(
        transport=PinnedAsyncTransport(allow_private=allow_private),
        follow_redirects=False,
    )
