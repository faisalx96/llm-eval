from __future__ import annotations

from ..utils.env import get_platform_url_env

#
# Platform URL policy:
# - End users should not have to pass the platform URL every time.
# - Resolve from QYM_BASE_URL.
# - For local dev, fall back to localhost.
#

DEFAULT_PLATFORM_URL = get_platform_url_env("http://localhost:8000")
