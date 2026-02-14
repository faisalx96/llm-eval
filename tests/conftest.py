import pytest
from unittest.mock import MagicMock, AsyncMock
import sys
from pathlib import Path

# Mock external heavy dependencies before they are imported by app code
mock_rich = MagicMock()
mock_rich.__path__ = []  # Mark as a package
sys.modules["rich"] = mock_rich
sys.modules["rich.console"] = MagicMock()
sys.modules["rich.live"] = MagicMock()
sys.modules["rich.panel"] = MagicMock()
sys.modules["rich.progress"] = MagicMock()
sys.modules["rich.table"] = MagicMock()
sys.modules["rich.align"] = MagicMock()
sys.modules["rich.text"] = MagicMock()
sys.modules["rich.layout"] = MagicMock()
sys.modules["rich.columns"] = MagicMock()
sys.modules["rich.rule"] = MagicMock()
sys.modules["rich.box"] = MagicMock()
sys.modules["rich.style"] = MagicMock()
sys.modules["rich.theme"] = MagicMock()
sys.modules["rich.progress_bar"] = MagicMock()
sys.modules["rich.spinner"] = MagicMock()

repo_root = Path(__file__).resolve().parents[1]
sdk_root = repo_root / "packages" / "sdk"
platform_root = repo_root / "packages" / "platform"
for p in (str(sdk_root), str(platform_root), str(repo_root)):
    if p not in sys.path:
        sys.path.insert(0, p)

mock_langfuse_pkg = MagicMock()
mock_langfuse_pkg.__path__ = []
sys.modules["langfuse"] = mock_langfuse_pkg

# Mock other optional heavy deps that may not be installed in test env
for _mod in ("arabic_reshaper", "bidi", "bidi.algorithm", "openpyxl"):
    if _mod not in sys.modules:
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
