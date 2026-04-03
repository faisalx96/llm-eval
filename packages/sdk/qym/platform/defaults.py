from __future__ import annotations

from ..utils.env import get_platform_url_env

#
# Platform URL policy:
# - End users should not have to pass the platform URL every time.
# - Prefer QYM_PLATFORM_URL for SDK usage.
# - Accept QYM_BASE_URL as a compatibility alias.
# - For local dev, fall back to localhost.
#

DEFAULT_PLATFORM_URL = get_platform_url_env("http://localhost:8000")
