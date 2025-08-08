"""Pytest configuration and shared fixtures."""

import asyncio
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import Mock, patch

import pytest

# Test configuration
TEST_DATA_DIR = Path(__file__).parent / "data"
FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def mock_langfuse_client():
    """Mock Langfuse client for testing."""
    client = Mock()
    client.get_dataset = Mock()
    return client


@pytest.fixture
def sample_dataset_items():
    """Sample dataset items for testing."""
    return [
        MockDatasetItem(
            input="What is the capital of France?", expected_output="Paris", id="item_1"
        ),
        MockDatasetItem(input="What is 2 + 2?", expected_output="4", id="item_2"),
        MockDatasetItem(
            input="What color is the sky?", expected_output="Blue", id="item_3"
        ),
    ]


@pytest.fixture
def mock_dataset(mock_langfuse_client, sample_dataset_items):
    """Mock dataset for testing."""
    dataset = Mock()
    dataset.get_items.return_value = sample_dataset_items
    return dataset


@pytest.fixture
def simple_task_function():
    """Simple task function for testing."""

    async def task(input_text):
        """Echo the input with a prefix."""
        return f"Response: {input_text}"

    return task


@pytest.fixture
def mock_task_adapter():
    """Mock task adapter for testing."""
    adapter = Mock()
    adapter.arun = Mock()
    return adapter


@pytest.fixture
def temp_dir():
    """Temporary directory for test files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def sample_evaluation_results():
    """Sample evaluation results for testing export functionality."""
    return {
        "item_1": {
            "output": "Response: What is the capital of France?",
            "scores": {"exact_match": 0.0, "contains": 1.0},
            "success": True,
            "time": 0.5,
        },
        "item_2": {
            "output": "Response: What is 2 + 2?",
            "scores": {"exact_match": 0.0, "contains": 1.0},
            "success": True,
            "time": 0.3,
        },
    }


@pytest.fixture
def mock_env_vars():
    """Mock environment variables for testing."""
    env_vars = {
        "LANGFUSE_PUBLIC_KEY": "pk-lf-test-key",
        "LANGFUSE_SECRET_KEY": "sk-lf-test-key",
        "LANGFUSE_HOST": "https://test.langfuse.com",
    }
    with patch.dict(os.environ, env_vars):
        yield env_vars


@pytest.fixture
def performance_baseline():
    """Performance baseline data for regression testing."""
    return {
        "evaluation_time_per_item": 1.0,  # seconds
        "memory_usage_mb": 100,
        "cpu_usage_percent": 50,
    }


class MockDatasetItem:
    """Mock dataset item for testing."""

    def __init__(self, input: str, expected_output: str = None, id: str = None):
        self.input = input
        self.expected_output = expected_output
        self.id = id or "test_item"

    def run(self, run_name: str = None, run_metadata: Dict = None):
        """Mock run context manager."""
        return MockTrace()


class MockTrace:
    """Mock trace context for testing."""

    def __init__(self):
        self.scores = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass

    def score_trace(self, name: str, value: Any, data_type: str = None):
        """Mock score trace method."""
        self.scores.append({"name": name, "value": value, "data_type": data_type})


# Test data creation helpers
def create_test_dataset_file(temp_dir: Path, name: str, items: List[Dict]) -> Path:
    """Create a test dataset file."""
    dataset_file = temp_dir / f"{name}.json"
    with open(dataset_file, "w") as f:
        json.dump({"items": items}, f, indent=2)
    return dataset_file


def create_test_task_file(temp_dir: Path, task_code: str) -> Path:
    """Create a test task file."""
    task_file = temp_dir / "test_task.py"
    with open(task_file, "w") as f:
        f.write(task_code)
    return task_file


# Performance test helpers
@pytest.fixture
def performance_monitor():
    """Performance monitoring fixture."""
    import time

    class PerformanceMonitor:
        def __init__(self):
            self.start_time = None
            self.end_time = None
            self.start_memory = None
            self.peak_memory = None

            # Try to import psutil for memory monitoring
            try:
                import psutil

                self.process = psutil.Process()
                self._has_psutil = True
            except ImportError:
                self.process = None
                self._has_psutil = False

        def start(self):
            self.start_time = time.time()
            if self._has_psutil:
                self.start_memory = self.process.memory_info().rss / 1024 / 1024  # MB

        def stop(self):
            self.end_time = time.time()
            if self._has_psutil:
                self.peak_memory = self.process.memory_info().rss / 1024 / 1024  # MB

        def get_duration(self):
            if self.start_time and self.end_time:
                return self.end_time - self.start_time
            return None

        def get_memory_usage(self):
            if self._has_psutil and self.start_memory and self.peak_memory:
                return self.peak_memory - self.start_memory
            return None

    return PerformanceMonitor()


# Skip markers for optional dependencies
def skip_if_no_deepeval():
    """Skip test if DeepEval is not available."""
    try:
        import deepeval

        return False
    except ImportError:
        return True


def skip_if_no_openai():
    """Skip test if OpenAI is not available."""
    return not os.getenv("OPENAI_API_KEY")


# Pytest markers
pytestmark = [
    pytest.mark.filterwarnings("ignore:.*deprecated.*:DeprecationWarning"),
    pytest.mark.filterwarnings("ignore:.*PendingDeprecationWarning.*"),
]
