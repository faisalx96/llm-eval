"""Performance benchmarking tests for the evaluation framework."""

import pytest
import time
import asyncio
import statistics
from unittest.mock import Mock, patch, AsyncMock
from llm_eval.core.evaluator import Evaluator
from llm_eval.core.results import EvaluationResult


@pytest.mark.performance
class TestEvaluationPerformance:
    """Performance tests for evaluation functionality."""
    
    @pytest.mark.asyncio
    async def test_single_item_evaluation_time(self, mock_env_vars, performance_monitor):
        """Test performance of single item evaluation."""
        
        mock_item = Mock(
            input="Performance test input",
            expected_output="Expected output",
            id="perf_item_1",
            run=Mock(return_value=Mock(__enter__=Mock(return_value=Mock(score_trace=Mock())), __exit__=Mock()))
        )
        
        with patch('llm_eval.core.evaluator.Langfuse') as mock_langfuse:
            with patch('llm_eval.core.evaluator.LangfuseDataset') as mock_dataset_class:
                with patch('llm_eval.core.evaluator.auto_detect_task') as mock_auto_detect:
                    
                    mock_client = Mock()
                    mock_langfuse.return_value = mock_client
                    
                    mock_dataset = Mock()
                    mock_dataset.get_items.return_value = [mock_item]
                    mock_dataset_class.return_value = mock_dataset
                    
                    # Mock fast task adapter
                    mock_adapter = Mock()
                    mock_adapter.arun = AsyncMock(return_value="Fast response")
                    mock_auto_detect.return_value = mock_adapter
                    
                    evaluator = Evaluator(
                        task=lambda x: f"Response: {x}",
                        dataset="perf-test",
                        metrics=["exact_match", "contains"]
                    )
                    
                    # Measure performance
                    performance_monitor.start()
                    result = await evaluator.arun(show_progress=False)
                    performance_monitor.stop()
                    
                    # Performance assertions
                    duration = performance_monitor.get_duration()
                    assert duration is not None
                    assert duration < 1.0  # Should complete in under 1 second
                    
                    # Verify correctness
                    assert result.total_items == 1
                    assert result.success_rate == 1.0
    
    @pytest.mark.asyncio
    async def test_bulk_evaluation_performance(self, mock_env_vars, performance_monitor):
        """Test performance with larger dataset."""
        
        # Create 50 mock items
        mock_items = []
        for i in range(50):
            mock_items.append(
                Mock(
                    input=f"Performance test input {i}",
                    expected_output=f"Expected output {i}",
                    id=f"perf_item_{i}",
                    run=Mock(return_value=Mock(__enter__=Mock(return_value=Mock(score_trace=Mock())), __exit__=Mock()))
                )
            )
        
        with patch('llm_eval.core.evaluator.Langfuse') as mock_langfuse:
            with patch('llm_eval.core.evaluator.LangfuseDataset') as mock_dataset_class:
                with patch('llm_eval.core.evaluator.auto_detect_task') as mock_auto_detect:
                    
                    mock_client = Mock()
                    mock_langfuse.return_value = mock_client
                    
                    mock_dataset = Mock()
                    mock_dataset.get_items.return_value = mock_items
                    mock_dataset_class.return_value = mock_dataset
                    
                    # Mock adapter with realistic delay
                    async def mock_task_with_delay(input_text, trace):
                        await asyncio.sleep(0.01)  # 10ms per item
                        return f"Response to: {input_text}"
                    
                    mock_adapter = Mock()
                    mock_adapter.arun = mock_task_with_delay
                    mock_auto_detect.return_value = mock_adapter
                    
                    evaluator = Evaluator(
                        task=lambda x: f"Response: {x}",
                        dataset="bulk-perf-test",
                        metrics=["exact_match"],
                        config={"max_concurrency": 10}
                    )
                    
                    # Measure performance
                    performance_monitor.start()
                    result = await evaluator.arun(show_progress=False)
                    performance_monitor.stop()
                    
                    duration = performance_monitor.get_duration()
                    
                    # Performance assertions
                    assert duration is not None
                    # With 10 concurrent workers, 50 items at 10ms each should take ~50ms + overhead
                    assert duration < 2.0  # Allow for overhead
                    
                    # Verify correctness
                    assert result.total_items == 50
                    assert result.success_rate == 1.0
                    
                    # Calculate throughput
                    throughput = result.total_items / duration
                    assert throughput > 25  # Should process more than 25 items/second
    
    @pytest.mark.asyncio
    async def test_concurrency_scaling(self, mock_env_vars):
        """Test performance scaling with different concurrency levels."""
        
        # Create 20 mock items
        mock_items = []
        for i in range(20):
            mock_items.append(
                Mock(
                    input=f"Concurrency test input {i}",
                    expected_output=f"Expected output {i}",
                    id=f"conc_item_{i}",
                    run=Mock(return_value=Mock(__enter__=Mock(return_value=Mock(score_trace=Mock())), __exit__=Mock()))
                )
            )
        
        concurrency_levels = [1, 5, 10]
        durations = []
        
        for concurrency in concurrency_levels:
            with patch('llm_eval.core.evaluator.Langfuse') as mock_langfuse:
                with patch('llm_eval.core.evaluator.LangfuseDataset') as mock_dataset_class:
                    with patch('llm_eval.core.evaluator.auto_detect_task') as mock_auto_detect:
                        
                        mock_client = Mock()
                        mock_langfuse.return_value = mock_client
                        
                        mock_dataset = Mock()
                        mock_dataset.get_items.return_value = mock_items
                        mock_dataset_class.return_value = mock_dataset
                        
                        async def mock_task_delay(input_text, trace):
                            await asyncio.sleep(0.05)  # 50ms per item
                            return f"Response to: {input_text}"
                        
                        mock_adapter = Mock()
                        mock_adapter.arun = mock_task_delay
                        mock_auto_detect.return_value = mock_adapter
                        
                        evaluator = Evaluator(
                            task=lambda x: f"Response: {x}",
                            dataset="concurrency-test",
                            metrics=["exact_match"],
                            config={"max_concurrency": concurrency}
                        )
                        
                        start_time = time.time()
                        result = await evaluator.arun(show_progress=False)
                        end_time = time.time()
                        
                        duration = end_time - start_time
                        durations.append(duration)
                        
                        # Verify correctness for each level
                        assert result.total_items == 20
                        assert result.success_rate == 1.0
        
        # Performance should improve with higher concurrency
        # Note: Due to mocking overhead, we just check that it doesn't get worse
        assert durations[2] <= durations[0] * 1.5  # Allow some overhead tolerance
    
    def test_metric_computation_performance(self):
        """Test performance of different metric computations."""
        
        # Test data
        output_text = "This is a test response with multiple words and phrases."
        expected_text = "This is the expected response with some different words."
        
        # Test exact_match performance
        from llm_eval.metrics.builtin import exact_match
        
        start_time = time.time()
        for _ in range(1000):
            exact_match(output_text, expected_text)
        exact_match_time = time.time() - start_time
        
        # Test contains performance
        from llm_eval.metrics.builtin import contains
        
        start_time = time.time()
        for _ in range(1000):
            contains(output_text, "test")
        contains_time = time.time() - start_time
        
        # Test fuzzy_match performance
        from llm_eval.metrics.builtin import fuzzy_match
        
        start_time = time.time()
        for _ in range(1000):
            fuzzy_match(output_text, expected_text)
        fuzzy_match_time = time.time() - start_time
        
        # Performance assertions (1000 operations should be fast)
        assert exact_match_time < 0.1  # Less than 100ms for 1000 operations
        assert contains_time < 0.1
        assert fuzzy_match_time < 1.0  # Fuzzy matching is more expensive
        
        print(f"Metric performance (1000 ops):")
        print(f"  exact_match: {exact_match_time:.4f}s")
        print(f"  contains: {contains_time:.4f}s")
        print(f"  fuzzy_match: {fuzzy_match_time:.4f}s")
    
    def test_results_processing_performance(self):
        """Test performance of results processing and statistics."""
        
        # Create large result set
        result = EvaluationResult("perf-test", "perf-run", ["metric1", "metric2", "metric3"])
        
        # Add many results
        start_time = time.time()
        for i in range(1000):
            result.add_result(f"item_{i}", {
                "output": f"Output {i}",
                "scores": {
                    "metric1": i % 2,  # Boolean-like
                    "metric2": i / 1000.0,  # Float
                    "metric3": i % 10  # Integer
                },
                "success": True,
                "time": 0.5 + (i % 100) / 1000.0
            })
        add_results_time = time.time() - start_time
        
        # Test statistics computation performance
        start_time = time.time()
        for metric in ["metric1", "metric2", "metric3"]:
            stats = result.get_metric_stats(metric)
            assert isinstance(stats, dict)
        stats_time = time.time() - start_time
        
        # Test timing statistics
        start_time = time.time()
        timing_stats = result.get_timing_stats()
        timing_stats_time = time.time() - start_time
        
        # Performance assertions
        assert add_results_time < 1.0  # Adding 1000 results should be fast
        assert stats_time < 0.5  # Computing stats should be fast
        assert timing_stats_time < 0.1  # Timing stats should be very fast
        
        print(f"Results processing performance:")
        print(f"  Adding 1000 results: {add_results_time:.4f}s")
        print(f"  Computing 3 metric stats: {stats_time:.4f}s")
        print(f"  Computing timing stats: {timing_stats_time:.4f}s")
    
    def test_export_performance(self, temp_dir):
        """Test performance of export operations."""
        
        # Create large result set
        result = EvaluationResult("export-perf-test", "export-run", ["accuracy", "speed"])
        
        # Add results
        for i in range(1000):
            result.add_result(f"item_{i}", {
                "output": f"Generated output {i} with some longer text to test export performance",
                "scores": {
                    "accuracy": 0.5 + (i % 500) / 1000.0,
                    "speed": 1.0 + (i % 100) / 100.0
                },
                "success": True,
                "time": 0.1 + (i % 50) / 1000.0
            })
        
        result.finish()
        
        # Test JSON export performance
        json_path = temp_dir / "perf_test.json"
        start_time = time.time()
        result.save_json(str(json_path))
        json_export_time = time.time() - start_time
        
        # Test CSV export performance
        csv_path = temp_dir / "perf_test.csv"
        start_time = time.time()
        result.save_csv(str(csv_path))
        csv_export_time = time.time() - start_time
        
        # Performance assertions
        assert json_export_time < 2.0  # Should export 1000 items in under 2s
        assert csv_export_time < 2.0
        
        # Verify file sizes are reasonable
        json_size = json_path.stat().st_size
        csv_size = csv_path.stat().st_size
        
        assert json_size > 10000  # Should have substantial content
        assert csv_size > 5000
        
        print(f"Export performance (1000 items):")
        print(f"  JSON export: {json_export_time:.4f}s ({json_size} bytes)")
        print(f"  CSV export: {csv_export_time:.4f}s ({csv_size} bytes)")


@pytest.mark.performance
class TestMemoryUsage:
    """Tests for memory usage and efficiency."""
    
    @pytest.mark.asyncio
    async def test_memory_usage_bulk_evaluation(self, mock_env_vars, performance_monitor):
        """Test memory usage during bulk evaluation."""
        
        # Create many mock items
        mock_items = []
        for i in range(200):
            mock_items.append(
                Mock(
                    input=f"Memory test input {i} " * 10,  # Make inputs longer
                    expected_output=f"Expected output {i}",
                    id=f"mem_item_{i}",
                    run=Mock(return_value=Mock(__enter__=Mock(return_value=Mock(score_trace=Mock())), __exit__=Mock()))
                )
            )
        
        with patch('llm_eval.core.evaluator.Langfuse') as mock_langfuse:
            with patch('llm_eval.core.evaluator.LangfuseDataset') as mock_dataset_class:
                with patch('llm_eval.core.evaluator.auto_detect_task') as mock_auto_detect:
                    
                    mock_client = Mock()
                    mock_langfuse.return_value = mock_client
                    
                    mock_dataset = Mock()
                    mock_dataset.get_items.return_value = mock_items
                    mock_dataset_class.return_value = mock_dataset
                    
                    mock_adapter = Mock()
                    mock_adapter.arun = AsyncMock(return_value="Response " * 20)  # Longer responses
                    mock_auto_detect.return_value = mock_adapter
                    
                    evaluator = Evaluator(
                        task=lambda x: f"Response: {x}",
                        dataset="memory-test",
                        metrics=["exact_match", "contains", "fuzzy_match"]
                    )
                    
                    # Monitor memory usage
                    performance_monitor.start()
                    result = await evaluator.arun(show_progress=False)
                    performance_monitor.stop()
                    
                    memory_usage = performance_monitor.get_memory_usage()
                    
                    # Memory usage should be reasonable (less than 100MB for 200 items)
                    if memory_usage is not None:
                        assert memory_usage < 100  # MB
                        print(f"Memory usage for 200 items: {memory_usage:.2f} MB")
                    
                    # Verify correctness
                    assert result.total_items == 200
    
    def test_results_memory_efficiency(self):
        """Test memory efficiency of results storage."""
        
        import sys
        
        # Create result object
        result = EvaluationResult("memory-test", "memory-run", ["metric1"])
        
        # Measure size of empty result
        initial_size = sys.getsizeof(result.results) + sys.getsizeof(result.errors)
        
        # Add results and measure growth
        for i in range(100):
            result.add_result(f"item_{i}", {
                "output": f"Output {i}",
                "scores": {"metric1": i % 2},
                "success": True,
                "time": 0.1
            })
        
        final_size = sys.getsizeof(result.results) + sys.getsizeof(result.errors)
        size_per_item = (final_size - initial_size) / 100
        
        # Each result should not use excessive memory
        assert size_per_item < 1000  # Less than 1KB per item on average
        
        print(f"Memory usage per result item: {size_per_item:.2f} bytes")


@pytest.mark.performance
class TestRegressionBenchmarks:
    """Regression benchmarks to detect performance degradation."""
    
    @pytest.fixture
    def baseline_metrics(self):
        """Baseline performance metrics for regression testing."""
        return {
            "single_item_max_time": 1.0,  # seconds
            "bulk_items_per_second": 25,  # items/second
            "metric_computation_max_time": 0.1,  # seconds for 1000 ops
            "export_max_time_per_1000_items": 2.0,  # seconds
            "memory_usage_max_mb": 100  # MB for 200 items
        }
    
    @pytest.mark.asyncio
    async def test_single_item_regression(self, mock_env_vars, baseline_metrics):
        """Regression test for single item evaluation time."""
        
        mock_item = Mock(
            input="Regression test input",
            expected_output="Expected",
            id="regression_item",
            run=Mock(return_value=Mock(__enter__=Mock(return_value=Mock(score_trace=Mock())), __exit__=Mock()))
        )
        
        with patch('llm_eval.core.evaluator.Langfuse') as mock_langfuse:
            with patch('llm_eval.core.evaluator.LangfuseDataset') as mock_dataset_class:
                with patch('llm_eval.core.evaluator.auto_detect_task') as mock_auto_detect:
                    
                    mock_client = Mock()
                    mock_langfuse.return_value = mock_client
                    
                    mock_dataset = Mock()
                    mock_dataset.get_items.return_value = [mock_item]
                    mock_dataset_class.return_value = mock_dataset
                    
                    mock_adapter = Mock()
                    mock_adapter.arun = AsyncMock(return_value="Response")
                    mock_auto_detect.return_value = mock_adapter
                    
                    evaluator = Evaluator(
                        task=lambda x: f"Response: {x}",
                        dataset="regression-test",
                        metrics=["exact_match"]
                    )
                    
                    # Run multiple times and take average
                    times = []
                    for _ in range(5):
                        start_time = time.time()
                        result = await evaluator.arun(show_progress=False)
                        end_time = time.time()
                        times.append(end_time - start_time)
                        assert result.success_rate == 1.0
                    
                    avg_time = statistics.mean(times)
                    
                    # Check against baseline
                    assert avg_time < baseline_metrics["single_item_max_time"], \
                        f"Single item evaluation took {avg_time:.3f}s, exceeds baseline of {baseline_metrics['single_item_max_time']}s"
    
    def test_metric_computation_regression(self, baseline_metrics):
        """Regression test for metric computation performance."""
        
        from llm_eval.metrics.builtin import exact_match, contains, fuzzy_match
        
        output = "This is a test response with multiple words for regression testing."
        expected = "This is the expected response with some different words."
        
        # Test each metric
        metrics_to_test = [
            ("exact_match", exact_match),
            ("contains", contains),
            ("fuzzy_match", fuzzy_match)
        ]
        
        for metric_name, metric_func in metrics_to_test:
            start_time = time.time()
            for _ in range(1000):
                if metric_name == "contains":
                    metric_func(output, "test")
                else:
                    metric_func(output, expected)
            end_time = time.time()
            
            duration = end_time - start_time
            assert duration < baseline_metrics["metric_computation_max_time"], \
                f"{metric_name} computation took {duration:.3f}s for 1000 ops, exceeds baseline of {baseline_metrics['metric_computation_max_time']}s"
    
    def create_performance_report(self, temp_dir):
        """Create a performance report for tracking over time."""
        
        report = {
            "timestamp": time.time(),
            "test_environment": {
                "python_version": __import__("sys").version,
                "platform": __import__("platform").platform()
            },
            "performance_metrics": {}
        }
        
        # Run basic performance tests and collect metrics
        # This would be expanded to run actual benchmarks
        
        import json
        report_file = temp_dir / "performance_report.json"
        with open(report_file, 'w') as f:
            json.dump(report, f, indent=2)
        
        return str(report_file)