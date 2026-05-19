"""TLS configuration helpers for qym platform HTTP clients."""

from __future__ import annotations

import os
import ssl
from typing import Optional
from urllib import request as urlrequest


_FALSE_VALUES = {"0", "false", "no", "off", "disable", "disabled"}
_TRUE_VALUES = {"1", "true", "yes", "on", "enable", "enabled"}


def _get_bool_env(name: str, *, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in _FALSE_VALUES:
        return False
    if normalized in _TRUE_VALUES:
        return True
    return default


def ssl_verify_enabled() -> bool:
    """Return whether platform HTTPS certificate verification is enabled."""

    if "QYM_PLATFORM_SSL_VERIFY" in os.environ:
        return _get_bool_env("QYM_PLATFORM_SSL_VERIFY", default=True)
    return _get_bool_env("QYM_SSL_VERIFY", default=True)


def ca_bundle_path() -> Optional[str]:
    """Return a custom CA bundle path for platform HTTPS calls, if configured."""

    return os.getenv("QYM_PLATFORM_CA_BUNDLE") or os.getenv("QYM_CA_BUNDLE")


def ssl_context() -> Optional[ssl.SSLContext]:
    """Build the SSL context used for platform HTTPS calls.

    Returning ``None`` lets urllib use Python's default verified context,
    including standard variables such as SSL_CERT_FILE.
    """

    if not ssl_verify_enabled():
        return ssl._create_unverified_context()

    cafile = ca_bundle_path()
    if cafile:
        return ssl.create_default_context(cafile=cafile)

    return None


def urlopen(req: urlrequest.Request, *, timeout: float):
    """Open a urllib request with qym platform TLS settings applied."""

    context = ssl_context()
    if context is None:
        return urlrequest.urlopen(req, timeout=timeout)
    return urlrequest.urlopen(req, timeout=timeout, context=context)
