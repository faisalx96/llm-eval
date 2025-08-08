"""Unit tests for the core Evaluator class."""

import asyncio
from unittest.mock import AsyncMock, Mock, patch

import pytest

from llm_eval.core.evaluator import Evaluator
from llm_eval.core.results import EvaluationResult
from llm_eval.utils.errors import LangfuseConnectionError


@pytest.mark.unit
class TestEvaluator:
    """Test cases for the Evaluator class."""

    def test_evaluator_initialization(self, mock_env_vars):
        """Test basic evaluator initialization."""
        with patch("llm_eval.core.evaluator.Langfuse") as mock_langfuse:
            with patch("llm_eval.core.evaluator.LangfuseDataset") as mock_dataset:
                with patch("llm_eval.core.evaluator.auto_detect_task") as mock_adapter:

                    mock_client = Mock()
                    mock_langfuse.return_value = mock_client

                    evaluator = Evaluator(
                        task=lambda x: x,
                        dataset="test-dataset",
                        metrics=["exact_match", "contains"],
                    )

                    assert evaluator.dataset_name == "test-dataset"
                    assert len(evaluator.metrics) == 2
                    assert "exact_match" in evaluator.metrics
                    assert "contains" in evaluator.metrics
                    assert evaluator.max_concurrency == 10  # default
                    assert evaluator.timeout == 30.0  # default

    def test_evaluator_custom_config(self, mock_env_vars):
        """Test evaluator with custom configuration."""
        with patch("llm_eval.core.evaluator.Langfuse") as mock_langfuse:
            with patch("llm_eval.core.evaluator.LangfuseDataset") as mock_dataset:
                with patch("llm_eval.core.evaluator.auto_detect_task") as mock_adapter:

                    config = {
                        "max_concurrency": 5,
                        "timeout": 60,
                        "run_name": "custom-run",
                        "run_metadata": {"version": "1.0"},
                    }

                    evaluator = Evaluator(
                        task=lambda x: x,
                        dataset="test-dataset",
                        metrics=["exact_match"],
                        config=config,
                    )

                    assert evaluator.max_concurrency == 5
                    assert evaluator.timeout == 60
                    assert evaluator.run_name == "custom-run"
                    assert evaluator.run_metadata == {"version": "1.0"}

    @pytest.mark.skip(
        reason="Integration test requiring actual Langfuse connection - tested separately in test_evaluator_langfuse.py when Langfuse is available"
    )
    def test_langfuse_connection_error_missing_public_key(self):
        """Test error handling for missing Langfuse public key."""
        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(LangfuseConnectionError) as exc_info:
                Evaluator(
                    task=lambda x: x, dataset="test-dataset", metrics=["exact_match"]
                )

            assert "Missing Langfuse public key" in str(exc_info.value)

    @pytest.mark.skip(
        reason="Integration test requiring actual Langfuse connection - tested separately in test_evaluator_langfuse.py when Langfuse is available"
    )
    def test_langfuse_connection_error_missing_secret_key(self):
        """Test error handling for missing Langfuse secret key."""
        with patch.dict("os.environ", {"LANGFUSE_PUBLIC_KEY": "test-key"}, clear=True):
            with pytest.raises(LangfuseConnectionError) as exc_info:
                Evaluator(
                    task=lambda x: x, dataset="test-dataset", metrics=["exact_match"]
                )

            assert "Missing Langfuse secret key" in str(exc_info.value)

    def test_prepare_metrics_string_metrics(self, mock_env_vars):
        """Test metric preparation with string metric names."""
        with patch("llm_eval.core.evaluator.Langfuse"):
            with patch("llm_eval.core.evaluator.LangfuseDataset"):
                with patch("llm_eval.core.evaluator.auto_detect_task"):
                    with patch("llm_eval.core.evaluator.get_metric") as mock_get_metric:

                        mock_metric_func = Mock()
                        mock_get_metric.return_value = mock_metric_func

                        evaluator = Evaluator(
                            task=lambda x: x,
                            dataset="test-dataset",
                            metrics=["exact_match", "contains"],
                        )

                        assert len(evaluator.metrics) == 2
                        assert "exact_match" in evaluator.metrics
                        assert "contains" in evaluator.metrics
                        assert evaluator.metrics["exact_match"] == mock_metric_func
                        assert evaluator.metrics["contains"] == mock_metric_func

    def test_prepare_metrics_callable_metrics(self, mock_env_vars):
        """Test metric preparation with callable metrics."""
        with patch("llm_eval.core.evaluator.Langfuse"):
            with patch("llm_eval.core.evaluator.LangfuseDataset"):
                with patch("llm_eval.core.evaluator.auto_detect_task"):

                    def custom_metric(output, expected):
                        return 1.0

                    evaluator = Evaluator(
                        task=lambda x: x,
                        dataset="test-dataset",
                        metrics=[custom_metric],
                    )

                    assert len(evaluator.metrics) == 1
                    assert "custom_metric" in evaluator.metrics
                    assert evaluator.metrics["custom_metric"] == custom_metric

    def test_prepare_metrics_invalid_type(self, mock_env_vars):
        """Test error handling for invalid metric types."""
        with patch("llm_eval.core.evaluator.Langfuse"):
            with patch("llm_eval.core.evaluator.LangfuseDataset"):
                with patch("llm_eval.core.evaluator.auto_detect_task"):

                    with pytest.raises(ValueError) as exc_info:
                        Evaluator(
                            task=lambda x: x,
                            dataset="test-dataset",
                            metrics=[123],  # Invalid type
                        )

                    assert "Metric must be string or callable" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_compute_metric_sync_function(self, mock_env_vars):
        """Test computing metrics with synchronous functions."""
        with patch("llm_eval.core.evaluator.Langfuse"):
            with patch("llm_eval.core.evaluator.LangfuseDataset"):
                with patch("llm_eval.core.evaluator.auto_detect_task"):

                    def sync_metric(output, expected):
                        return 0.8

                    evaluator = Evaluator(
                        task=lambda x: x, dataset="test-dataset", metrics=[sync_metric]
                    )

                    result = await evaluator._compute_metric(
                        sync_metric, "test output", "expected"
                    )
                    assert result == 0.8

    @pytest.mark.asyncio
    async def test_compute_metric_async_function(self, mock_env_vars):
        """Test computing metrics with asynchronous functions."""
        with patch("llm_eval.core.evaluator.Langfuse"):
            with patch("llm_eval.core.evaluator.LangfuseDataset"):
                with patch("llm_eval.core.evaluator.auto_detect_task"):

                    async def async_metric(output, expected):
                        return 0.9

                    evaluator = Evaluator(
                        task=lambda x: x, dataset="test-dataset", metrics=[async_metric]
                    )

                    result = await evaluator._compute_metric(
                        async_metric, "test output", "expected"
                    )
                    assert result == 0.9

    @pytest.mark.asyncio
    async def test_compute_metric_single_param(self, mock_env_vars):
        """Test computing metrics with single parameter."""
        with patch("llm_eval.core.evaluator.Langfuse"):
            with patch("llm_eval.core.evaluator.LangfuseDataset"):
                with patch("llm_eval.core.evaluator.auto_detect_task"):

                    def single_param_metric(output):
                        return len(output)

                    evaluator = Evaluator(
                        task=lambda x: x,
                        dataset="test-dataset",
                        metrics=[single_param_metric],
                    )

                    result = await evaluator._compute_metric(
                        single_param_metric, "test", "expected"
                    )
                    assert result == 4

    @pytest.mark.asyncio
    async def test_compute_metric_three_params(self, mock_env_vars):
        """Test computing metrics with three parameters (including input)."""
        with patch("llm_eval.core.evaluator.Langfuse"):
            with patch("llm_eval.core.evaluator.LangfuseDataset"):
                with patch("llm_eval.core.evaluator.auto_detect_task"):

                    def three_param_metric(output, expected, input_data):
                        return 1.0 if input_data in output else 0.0

                    evaluator = Evaluator(
                        task=lambda x: x,
                        dataset="test-dataset",
                        metrics=[three_param_metric],
                    )

                    result = await evaluator._compute_metric(
                        three_param_metric, "test input response", "expected", "input"
                    )
                    assert result == 1.0

    def test_get_score_type_boolean(self, mock_env_vars):
        """Test score type detection for boolean values."""
        with patch("llm_eval.core.evaluator.Langfuse"):
            with patch("llm_eval.core.evaluator.LangfuseDataset"):
                with patch("llm_eval.core.evaluator.auto_detect_task"):

                    evaluator = Evaluator(
                        task=lambda x: x,
                        dataset="test-dataset",
                        metrics=["exact_match"],
                    )

                    assert evaluator._get_score_type(True) == "BOOLEAN"
                    assert evaluator._get_score_type(False) == "BOOLEAN"

    def test_get_score_type_numeric(self, mock_env_vars):
        """Test score type detection for numeric values."""
        with patch("llm_eval.core.evaluator.Langfuse"):
            with patch("llm_eval.core.evaluator.LangfuseDataset"):
                with patch("llm_eval.core.evaluator.auto_detect_task"):

                    evaluator = Evaluator(
                        task=lambda x: x,
                        dataset="test-dataset",
                        metrics=["exact_match"],
                    )

                    assert evaluator._get_score_type(42) == "NUMERIC"
                    assert evaluator._get_score_type(3.14) == "NUMERIC"

    def test_get_score_type_categorical(self, mock_env_vars):
        """Test score type detection for categorical values."""
        with patch("llm_eval.core.evaluator.Langfuse"):
            with patch("llm_eval.core.evaluator.LangfuseDataset"):
                with patch("llm_eval.core.evaluator.auto_detect_task"):

                    evaluator = Evaluator(
                        task=lambda x: x,
                        dataset="test-dataset",
                        metrics=["exact_match"],
                    )

                    assert evaluator._get_score_type("string") == "CATEGORICAL"
                    assert evaluator._get_score_type(["list"]) == "CATEGORICAL"
                    assert evaluator._get_score_type({"dict": "value"}) == "CATEGORICAL"

    @pytest.mark.asyncio
    async def test_evaluate_item_success(self, mock_env_vars, sample_dataset_items):
        """Test successful item evaluation."""
        with patch("llm_eval.core.evaluator.Langfuse"):
            with patch("llm_eval.core.evaluator.LangfuseDataset"):
                with patch(
                    "llm_eval.core.evaluator.auto_detect_task"
                ) as mock_auto_detect:

                    # Mock task adapter
                    mock_adapter = Mock()
                    mock_adapter.arun = AsyncMock(return_value="Test response")
                    mock_auto_detect.return_value = mock_adapter

                    # Mock metric
                    def mock_metric(output, expected):
                        return 0.75

                    evaluator = Evaluator(
                        task=lambda x: x, dataset="test-dataset", metrics=[mock_metric]
                    )
                    evaluator.task_adapter = mock_adapter

                    # Mock dataset item
                    item = sample_dataset_items[0]
                    semaphore = asyncio.Semaphore(1)

                    result = await evaluator._evaluate_item(item, 0, semaphore)

                    assert result["success"] is True
                    assert result["output"] == "Test response"
                    assert "scores" in result
                    assert "mock_metric" in result["scores"]
                    assert result["scores"]["mock_metric"] == 0.75

    @pytest.mark.asyncio
    async def test_evaluate_item_timeout(self, mock_env_vars, sample_dataset_items):
        """Test item evaluation timeout handling."""
        with patch("llm_eval.core.evaluator.Langfuse"):
            with patch("llm_eval.core.evaluator.LangfuseDataset"):
                with patch(
                    "llm_eval.core.evaluator.auto_detect_task"
                ) as mock_auto_detect:

                    # Mock task adapter that times out
                    mock_adapter = Mock()
                    mock_adapter.arun = AsyncMock(side_effect=asyncio.TimeoutError())
                    mock_auto_detect.return_value = mock_adapter

                    evaluator = Evaluator(
                        task=lambda x: x,
                        dataset="test-dataset",
                        metrics=["exact_match"],
                        config={"timeout": 0.1},
                    )
                    evaluator.task_adapter = mock_adapter

                    item = sample_dataset_items[0]
                    semaphore = asyncio.Semaphore(1)

                    with pytest.raises(TimeoutError) as exc_info:
                        await evaluator._evaluate_item(item, 0, semaphore)

                    assert "timed out" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_evaluate_item_task_error(self, mock_env_vars, sample_dataset_items):
        """Test item evaluation task error handling."""
        with patch("llm_eval.core.evaluator.Langfuse"):
            with patch("llm_eval.core.evaluator.LangfuseDataset"):
                with patch(
                    "llm_eval.core.evaluator.auto_detect_task"
                ) as mock_auto_detect:

                    # Mock task adapter that raises an error
                    mock_adapter = Mock()
                    mock_adapter.arun = AsyncMock(side_effect=Exception("Task failed"))
                    mock_auto_detect.return_value = mock_adapter

                    evaluator = Evaluator(
                        task=lambda x: x,
                        dataset="test-dataset",
                        metrics=["exact_match"],
                    )
                    evaluator.task_adapter = mock_adapter

                    item = sample_dataset_items[0]
                    semaphore = asyncio.Semaphore(1)

                    with pytest.raises(RuntimeError) as exc_info:
                        await evaluator._evaluate_item(item, 0, semaphore)

                    assert "Task execution failed" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_evaluate_item_metric_error(
        self, mock_env_vars, sample_dataset_items
    ):
        """Test item evaluation with metric error."""
        with patch("llm_eval.core.evaluator.Langfuse"):
            with patch("llm_eval.core.evaluator.LangfuseDataset"):
                with patch(
                    "llm_eval.core.evaluator.auto_detect_task"
                ) as mock_auto_detect:

                    # Mock task adapter
                    mock_adapter = Mock()
                    mock_adapter.arun = AsyncMock(return_value="Test response")
                    mock_auto_detect.return_value = mock_adapter

                    # Mock metric that raises an error
                    def failing_metric(output, expected):
                        raise ValueError("Metric calculation failed")

                    evaluator = Evaluator(
                        task=lambda x: x,
                        dataset="test-dataset",
                        metrics=[failing_metric],
                    )
                    evaluator.task_adapter = mock_adapter

                    item = sample_dataset_items[0]
                    semaphore = asyncio.Semaphore(1)

                    result = await evaluator._evaluate_item(item, 0, semaphore)

                    assert result["success"] is True  # Task succeeded
                    assert "scores" in result
                    assert "failing_metric" in result["scores"]
                    assert "error" in result["scores"]["failing_metric"]
                    assert "Metric calculation failed" in str(
                        result["scores"]["failing_metric"]["error"]
                    )
