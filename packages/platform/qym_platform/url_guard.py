from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlsplit

# Environments where outbound URL restrictions are relaxed (local development).
_DEV_ENVIRONMENTS = {"dev", "development", "test", "testing", "local"}


def is_dev_environment(environment: str) -> bool:
    return (environment or "").strip().lower() in _DEV_ENVIRONMENTS


def _is_blocked_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """True for addresses an outbound LLM call must never target (SSRF guard)."""
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return (
        ip.is_loopback  # 127/8, ::1
        or ip.is_link_local  # 169.254/16 (cloud metadata), fe80::/10
        or ip.is_private  # 10/8, 172.16/12, 192.168/16, fc00::/7
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def validate_llm_base_url(raw_url: str, *, environment: str) -> None:
    """Validate an outbound LLM base URL to prevent SSRF / provider-key exfiltration.

    Raises ValueError with a user-facing message when the URL is unacceptable.
    Outside dev/test/local environments this requires https, rejects URLs with
    embedded credentials, and rejects hosts that resolve to loopback, private,
    link-local (incl. cloud metadata), or otherwise internal addresses. DNS
    resolution via socket.getaddrinfo is the only network activity performed.
    """
    url = (raw_url or "").strip()
    if not url:
        raise ValueError("LLM base URL is required")
    try:
        parsed = urlsplit(url)
        port = parsed.port  # may raise ValueError for an out-of-range port
    except ValueError:
        raise ValueError("LLM base URL is not a valid URL")

    dev = is_dev_environment(environment)
    if parsed.scheme == "http":
        if not dev:
            raise ValueError("LLM base URL must use https")
    elif parsed.scheme != "https":
        raise ValueError("LLM base URL must use http(s)")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("LLM base URL must not contain embedded credentials")
    hostname = parsed.hostname
    if not hostname:
        raise ValueError("LLM base URL must include a hostname")
    if dev:
        return

    try:
        literal_ip = ipaddress.ip_address(hostname)
    except ValueError:
        literal_ip = None
    if literal_ip is not None:
        if _is_blocked_ip(literal_ip):
            raise ValueError("LLM base URL must not point at a private or internal address")
        return

    try:
        infos = socket.getaddrinfo(hostname, port or (443 if parsed.scheme == "https" else 80), proto=socket.IPPROTO_TCP)
    except OSError as exc:
        raise ValueError("LLM base URL hostname could not be resolved") from exc
    for info in infos:
        address = str(info[4][0]).split("%", 1)[0]
        try:
            resolved = ipaddress.ip_address(address)
        except ValueError:
            continue
        if _is_blocked_ip(resolved):
            raise ValueError("LLM base URL must not point at a private or internal address")
