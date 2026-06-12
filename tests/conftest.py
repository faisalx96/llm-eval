import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

repo_root = Path(__file__).resolve().parents[1]
sdk_root = repo_root / "packages" / "sdk"
platform_root = repo_root / "packages" / "platform"
for p in (str(sdk_root), str(platform_root), str(repo_root)):
    if p not in sys.path:
        sys.path.insert(0, p)

# ── Environment isolation ──────────────────────────────────────────────
# The repo root contains a developer .env with real values (postgres URL,
# API key, oidc auth mode, ...). PlatformSettings loads cwd .env via
# pydantic-settings (env_file=".env"), and the SDK reads QYM_API_KEY /
# QYM_BASE_URL straight from the process environment. Tests must never
# depend on either, so pin/scrub everything auth- and network-relevant
# before collection (some modules construct settings at import time).
# Individual tests that need different values override via monkeypatch.
_env_patch = pytest.MonkeyPatch()


def pytest_configure(config):
    # Pinned: real env vars take precedence over .env in pydantic-settings.
    _env_patch.setenv("QYM_DATABASE_URL", "sqlite:///:memory:")
    _env_patch.setenv("QYM_ENVIRONMENT", "dev")
    _env_patch.setenv("QYM_AUTH_MODE", "none")
    _env_patch.setenv("QYM_AUTH_LOCAL_ENABLED", "false")
    # Scrubbed: a leaked QYM_API_KEY/QYM_BASE_URL makes SDK tests attempt
    # real HTTP against a running dev platform. Keys that exist in the repo
    # .env are pinned to empty string rather than deleted: Evaluator.__init__
    # calls load_cwd_dotenv(override=False), which re-injects deleted keys
    # from .env but skips keys that are present (even when empty). Empty is
    # falsy in every SDK lookup (`explicit or os.getenv(...)`), so it behaves
    # as unset.
    for _var in ("QYM_API_KEY", "QYM_PLATFORM_URL"):
        _env_patch.setenv(_var, "")
    # Not in .env, so deletion is safe and keeps PlatformSettings defaults.
    _env_patch.delenv("QYM_BASE_URL", raising=False)


def pytest_unconfigure(config):
    _env_patch.undo()

# Optional heavy dependencies: use the real package when installed; register a
# mock only when it's genuinely missing. Mocking installed packages corrupts
# unrelated imports (e.g. a mocked `rich` breaks `httpx`).
for _mod in (
    "rich",
    "langfuse",
    "arabic_reshaper",
    "bidi",
    "bidi.algorithm",
    "openai",
    "openpyxl",
):
    if _mod in sys.modules:
        continue
    try:
        _found = importlib.util.find_spec(_mod) is not None
    except (ImportError, ValueError):
        _found = False
    if not _found:
        _m = MagicMock()
        _m.__path__ = []
        sys.modules[_mod] = _m

@pytest.fixture
def mock_langfuse():
    mock = MagicMock()
    return mock

@pytest.fixture
def mock_dataset():
    mock = MagicMock()
    mock.get_items.return_value = []
    return mock

@pytest.fixture
def mock_task():
    return MagicMock()
