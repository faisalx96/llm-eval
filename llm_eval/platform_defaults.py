from __future__ import annotations

import os

#
# Platform URL policy:
# - End users should not have to pass the platform URL every time.
# - For internal deployments, set LLM_EVAL_PLATFORM_URL globally (e.g. via managed env/profile).
# - For local dev, we fall back to localhost.
#

DEFAULT_PLATFORM_URL = os.getenv("LLM_EVAL_PLATFORM_URL", "http://localhost:8000").rstrip("/")


