"""Unit tests for metrics functionality."""

import pytest
from unittest.mock import Mock, patch
from llm_eval.metrics.builtin import exact_match, contains, fuzzy_match, response_time
from llm_eval.metrics.registry import get_metric, register_metric, list_metrics


@pytest.mark.unit
class TestBuiltinMetrics:
    """Test cases for built-in metrics."""
    
    def test_exact_match_identical(self):
        """Test exact match with identical strings."""
        assert exact_match("hello world", "hello world") == 1.0
    
    def test_exact_match_different(self):
        """Test exact match with different strings."""
        assert exact_match("hello world", "goodbye world") == 0.0
    
    def test_exact_match_case_sensitive(self):
        """Test exact match is case sensitive."""
        assert exact_match("Hello World", "hello world") == 0.0
    
    def test_exact_match_whitespace_trimmed(self):
        """Test exact match trims whitespace."""
        assert exact_match("  hello world  ", "hello world") == 1.0
        assert exact_match("hello world", "  hello world  ") == 1.0
    
    def test_exact_match_none_values(self):
        """Test exact match with None values."""
        assert exact_match(None, None) == 1.0
        assert exact_match("hello", None) == 0.0
        assert exact_match(None, "hello") == 0.0
    
    def test_exact_match_non_string(self):
        """Test exact match with non-string values."""
        assert exact_match(123, 123) == 1.0
        assert exact_match(123, "123") == 1.0
        assert exact_match(123, 456) == 0.0
    
    def test_contains_substring_present(self):
        """Test contains metric with substring present."""
        assert contains("hello world", "world") == 1.0
        assert contains("hello world", "hello") == 1.0
    
    def test_contains_substring_absent(self):
        """Test contains metric with substring absent."""
        assert contains("hello world", "goodbye") == 0.0
    
    def test_contains_case_insensitive(self):
        """Test contains metric is case insensitive."""
        assert contains("Hello World", "world") == 1.0
        assert contains("hello world", "WORLD") == 1.0
    
    def test_contains_none_values(self):
        """Test contains metric with None values."""
        assert contains(None, "test") == 0.0
        assert contains("test", None) == 0.0
        assert contains(None, None) == 0.0
    
    def test_contains_non_string(self):
        """Test contains metric with non-string values."""
        assert contains(123456, "234") == 1.0
        assert contains(123456, "789") == 0.0
    
    def test_fuzzy_match_identical(self):
        """Test fuzzy match with identical strings."""
        assert fuzzy_match("hello world", "hello world") == 1.0
    
    def test_fuzzy_match_similar(self):
        """Test fuzzy match with similar strings."""
        score = fuzzy_match("hello world", "helo world")
        assert 0.8 < score < 1.0
    
    def test_fuzzy_match_different(self):
        """Test fuzzy match with very different strings."""
        score = fuzzy_match("hello world", "goodbye universe")
        assert score < 0.5
    
    def test_fuzzy_match_custom_threshold(self):
        """Test fuzzy match with custom threshold."""
        # Similar strings above threshold
        assert fuzzy_match("hello world", "helo world", threshold=0.8) == 1.0
        # Similar strings below threshold
        assert fuzzy_match("hello world", "helo wrld", threshold=0.95) == 0.0
    
    def test_fuzzy_match_none_values(self):
        """Test fuzzy match with None values."""
        assert fuzzy_match(None, None) == 1.0
        assert fuzzy_match("hello", None) == 0.0
        assert fuzzy_match(None, "hello") == 0.0
    
    def test_response_time_valid(self):
        """Test response time metric with valid timing."""
        result = {"time": 1.5}
        assert response_time(result) == 1.5
    
    def test_response_time_missing(self):
        """Test response time metric with missing timing."""
        result = {"output": "test"}
        assert response_time(result) == 0.0
    
    def test_response_time_invalid_type(self):
        """Test response time metric with invalid timing."""
        result = {"time": "not a number"}
        assert response_time(result) == 0.0
    
    def test_response_time_none_result(self):
        """Test response time metric with None result."""
        assert response_time(None) == 0.0


@pytest.mark.unit 
class TestMetricRegistry:
    """Test cases for metric registry."""
    
    def test_get_builtin_metric(self):
        """Test getting built-in metrics."""
        metric = get_metric("exact_match")
        assert callable(metric)
        assert metric("test", "test") == 1.0
    
    def test_get_nonexistent_metric(self):
        """Test getting non-existent metric raises error."""
        with pytest.raises(ValueError) as exc_info:
            get_metric("nonexistent_metric")
        
        assert "Unknown metric: nonexistent_metric" in str(exc_info.value)
    
    def test_register_custom_metric(self):
        """Test registering custom metric."""
        def custom_metric(output, expected):
            return 0.5
        
        register_metric("custom_test", custom_metric)
        
        # Should be able to retrieve it
        retrieved = get_metric("custom_test")
        assert retrieved == custom_metric
        assert retrieved("any", "any") == 0.5
    
    def test_register_overwrite_warning(self):
        """Test warning when overriding existing metric."""
        def new_exact_match(output, expected):
            return 0.9
        
        with patch('llm_eval.metrics.registry.console') as mock_console:
            register_metric("exact_match", new_exact_match)
            mock_console.print.assert_called_once()
            assert "already exists" in str(mock_console.print.call_args)
        
        # Should use new implementation
        retrieved = get_metric("exact_match")
        assert retrieved("test", "test") == 0.9
    
    def test_list_metrics(self):
        """Test listing all available metrics."""
        metrics = list_metrics()
        
        assert isinstance(metrics, list)
        assert "exact_match" in metrics
        assert "contains" in metrics
        assert "fuzzy_match" in metrics
        assert "response_time" in metrics
    
    def test_list_metrics_after_registration(self):
        """Test listing metrics includes custom registered ones."""
        def another_custom(output, expected):
            return 1.0
        
        register_metric("another_custom", another_custom)
        metrics = list_metrics()
        
        assert "another_custom" in metrics


@pytest.mark.unit
@pytest.mark.skipif(
    pytest.importorskip("deepeval", reason="DeepEval not available"),
    reason="DeepEval tests require deepeval package"
)
class TestDeepEvalMetrics:
    """Test cases for DeepEval metric integration."""
    
    def test_discover_deepeval_metrics(self):
        """Test automatic discovery of DeepEval metrics."""
        from llm_eval.metrics.deepeval_metrics import discover_deepeval_metrics
        
        metrics = discover_deepeval_metrics()
        
        assert isinstance(metrics, dict)
        assert len(metrics) > 0
        
        # Check some expected metrics are discovered
        expected_metrics = ["answer_relevancy", "faithfulness", "hallucination"]
        for metric_name in expected_metrics:
            if metric_name in metrics:
                assert callable(metrics[metric_name])
    
    def test_create_deepeval_wrapper(self):
        """Test creating wrapper for DeepEval metrics."""
        from llm_eval.metrics.deepeval_metrics import create_deepeval_wrapper
        
        # Mock DeepEval metric class
        class MockDeepEvalMetric:
            def __init__(self, **kwargs):
                self.score = 0.85
            
            def measure(self, test_case):
                pass
        
        wrapper = create_deepeval_wrapper(MockDeepEvalMetric)
        
        assert callable(wrapper)
        assert wrapper.__name__ == "mockdeepeval"
    
    @pytest.mark.asyncio
    async def test_deepeval_wrapper_execution(self):
        """Test execution of DeepEval wrapper."""
        from llm_eval.metrics.deepeval_metrics import create_deepeval_wrapper
        
        # Mock DeepEval components
        with patch('llm_eval.metrics.deepeval_metrics.LLMTestCase') as mock_test_case:
            class MockMetric:
                def __init__(self):
                    self.score = 0.75
                
                def measure(self, test_case):
                    pass
            
            wrapper = create_deepeval_wrapper(MockMetric)
            
            result = await wrapper("test output", "expected output", "test input")
            
            assert result == 0.75
            mock_test_case.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_deepeval_wrapper_openai_error(self):
        """Test DeepEval wrapper handles OpenAI API key errors."""
        from llm_eval.metrics.deepeval_metrics import create_deepeval_wrapper
        
        class MockMetric:
            def measure(self, test_case):
                raise Exception("openai api_key required")
        
        wrapper = create_deepeval_wrapper(MockMetric)
        
        with pytest.raises(RuntimeError) as exc_info:
            await wrapper("test", "expected")
        
        assert "OpenAI API key" in str(exc_info.value)
    
    @pytest.mark.asyncio
    async def test_deepeval_wrapper_generic_error(self):
        """Test DeepEval wrapper handles generic errors."""
        from llm_eval.metrics.deepeval_metrics import create_deepeval_wrapper
        
        class MockMetric:
            def measure(self, test_case):
                raise Exception("Some other error")
        
        wrapper = create_deepeval_wrapper(MockMetric)
        
        with pytest.raises(RuntimeError) as exc_info:
            await wrapper("test", "expected")
        
        assert "Some other error" in str(exc_info.value)
    
    def test_get_deepeval_metrics_includes_builtin(self):
        """Test that get_deepeval_metrics includes built-in metrics."""
        from llm_eval.metrics.deepeval_metrics import get_deepeval_metrics
        
        metrics = get_deepeval_metrics()
        
        # Should include built-in exact_match
        assert "exact_match" in metrics
        assert callable(metrics["exact_match"])
        assert metrics["exact_match"]("test", "test") == 1.0


@pytest.mark.unit
class TestMetricUtilities:
    """Test cases for metric utility functions."""
    
    def test_metric_parameter_detection(self):
        """Test automatic parameter detection for metrics."""
        import inspect
        from llm_eval.core.evaluator import Evaluator
        
        # Mock evaluator for testing _compute_metric
        with patch('llm_eval.core.evaluator.Langfuse'):
            with patch('llm_eval.core.evaluator.LangfuseDataset'):
                with patch('llm_eval.core.evaluator.auto_detect_task'):
                    evaluator = Evaluator(
                        task=lambda x: x,
                        dataset="test",
                        metrics=["exact_match"]
                    )
        
        # Test single parameter function
        def single_param(output):
            return len(str(output))
        
        sig = inspect.signature(single_param)
        assert len(sig.parameters) == 1
        
        # Test two parameter function
        def two_param(output, expected):
            return 1.0 if str(output) == str(expected) else 0.0
        
        sig = inspect.signature(two_param)
        assert len(sig.parameters) == 2
        
        # Test three parameter function (for DeepEval compatibility)
        def three_param(output, expected, input_data):
            return 1.0 if str(input_data) in str(output) else 0.0
        
        sig = inspect.signature(three_param)
        assert len(sig.parameters) == 3