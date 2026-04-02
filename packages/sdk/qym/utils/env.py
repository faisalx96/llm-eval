"""Environment loading helpers."""

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
