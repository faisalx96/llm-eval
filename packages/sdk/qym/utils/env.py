"""Environment loading helpers."""

import os
from pathlib import Path
from typing import Optional


def load_cwd_dotenv(*, override: bool = False) -> Optional[str]:
    """Load the current working directory's `.env` if it exists.

    Library code must not call `load_dotenv()` without an explicit path because
    python-dotenv may walk upward from the library/module location and pick up
    an unrelated `.env` from another repository or from site-packages parents.
    """
    dotenv_path = Path.cwd() / ".env"
    if not dotenv_path.is_file():
        return None

    try:
        from dotenv import load_dotenv
    except ImportError:
        return None

    load_dotenv(dotenv_path=dotenv_path, override=override)
    return str(dotenv_path)


def get_platform_url_env(default: str = "http://localhost:8000") -> str:
    """Return the platform URL from QYM_BASE_URL."""
    return (os.getenv("QYM_BASE_URL") or default).rstrip("/")


def get_langfuse_host_env(default: str = "") -> str:
    """Return the Langfuse host, preferring LANGFUSE_HOST.

    LANGFUSE_BASE_URL is accepted as a compatibility alias.
    """
    return (
        os.getenv("LANGFUSE_HOST")
        or os.getenv("LANGFUSE_BASE_URL")
        or default
    ).rstrip("/")
