import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from llm_eval.core.evaluator import Evaluator

class TestEvaluator:
    def test_init(self, mock_task, mock_langfuse, mock_dataset):
        """Test basic initialization of Evaluator with DI."""
        with patch("llm_eval.core.evaluator.auto_detect_task"):
            evaluator = Evaluator(
                task=mock_task,
                dataset=mock_dataset,  # Injected dataset
                metrics=["exact_match"],
                config={"run_name": "test-run"},
                langfuse_client=mock_langfuse  # Injected client
            )
            
            assert evaluator.dataset == mock_dataset
            assert evaluator.client == mock_langfuse
            assert evaluator.run_name == "test-run"
            assert "exact_match" in evaluator.metrics

    @pytest.mark.asyncio
    async def test_evaluate_item_success(self, mock_task, mock_langfuse, mock_dataset):
        """Test _evaluate_item method success path."""
        with patch("llm_eval.core.evaluator.auto_detect_task"):
            evaluator = Evaluator(
                task=mock_task,
                dataset=mock_dataset,
                metrics=[],
                config={"run_name": "test-run"},
                langfuse_client=mock_langfuse
            )
            
            # Mock internal components
            evaluator.task_adapter = MagicMock()
            evaluator.task_adapter.arun = AsyncMock(return_value="test_output")
            evaluator._notify_observer = MagicMock()
            evaluator._compute_metric = AsyncMock(return_value=1.0)
            evaluator.model_name = "test-model"
            
            # Mock item
            item = MagicMock()
            item.input = "test_input"
            item.run.return_value.__enter__.return_value = MagicMock()
            
            tracker = MagicMock()
            
            result = await evaluator._evaluate_item(0, item, tracker)
            
            assert result["success"] is True
            assert result["output"] == "test_output"
            tracker.start_item.assert_called_once_with(0)
            tracker.complete_item.assert_called_once_with(0)
