import pytest
from unittest.mock import MagicMock, AsyncMock
import sys

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

mock_langfuse_pkg = MagicMock()
mock_langfuse_pkg.__path__ = []
sys.modules["langfuse"] = mock_langfuse_pkg

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
