"""Test cases for natural language search functionality."""

import operator
from datetime import datetime
from unittest.mock import Mock

import pytest

from llm_eval.core.results import EvaluationResult
from llm_eval.core.search import SearchEngine, SearchQueryParser


class TestSearchQueryParser:
    """Test cases for SearchQueryParser class."""

    def setup_method(self):
        """Set up test fixtures."""
        self.parser = SearchQueryParser()
        self.available_metrics = [
            "exact_match",
            "answer_relevancy",
            "response_time",
            "accuracy_score",
        ]

    def test_empty_query(self):
        """Test parsing empty query."""
        result = self.parser.parse("", self.available_metrics)
        assert result["filters"] == []
        assert result["parsed"] == False
        assert result["raw_query"] == ""

    def test_failure_queries(self):
        """Test parsing failure-related queries."""
        queries = [
            "Show me failures",
            "Find all failed items",
            "Display errors",
            "List all failures",
        ]

        for query in queries:
            result = self.parser.parse(query, self.available_metrics)
            assert result["parsed"] == True
            assert len(result["filters"]) >= 1

            failure_filter = next(
                (f for f in result["filters"] if f["type"] == "success_status"), None
            )
            assert failure_filter is not None
            assert failure_filter["value"] == False

    def test_success_queries(self):
        """Test parsing success-related queries."""
        queries = [
            "Show me successful items",
            "Find all passed evaluations",
            "Display successes",
        ]

        for query in queries:
            result = self.parser.parse(query, self.available_metrics)
            assert result["parsed"] == True

            success_filter = next(
                (f for f in result["filters"] if f["type"] == "success_status"), None
            )
            assert success_filter is not None
            assert success_filter["value"] == True

    def test_slow_performance_queries(self):
        """Test parsing slow performance queries."""
        queries = [
            "Show me slow responses",
            "Find sluggish evaluations",
            "Display timeout items",
        ]

        for query in queries:
            result = self.parser.parse(query, self.available_metrics)
            assert result["parsed"] == True

            time_filter = next(
                (f for f in result["filters"] if f["type"] == "time_comparison"), None
            )
            assert time_filter is not None
            assert time_filter["operator"] == operator.gt
            assert time_filter["value"] == self.parser.default_thresholds["slow_time"]

    def test_fast_performance_queries(self):
        """Test parsing fast performance queries."""
        queries = [
            "Show me fast responses",
            "Find quick evaluations",
            "Display rapid items",
        ]

        for query in queries:
            result = self.parser.parse(query, self.available_metrics)
            assert result["parsed"] == True

            time_filter = next(
                (f for f in result["filters"] if f["type"] == "time_comparison"), None
            )
            assert time_filter is not None
            assert time_filter["operator"] == operator.lt
            assert time_filter["value"] == self.parser.default_thresholds["fast_time"]

    def test_time_threshold_queries(self):
        """Test parsing specific time threshold queries."""
        test_cases = [
            ("took more than 3 seconds", operator.gt, 3.0),
            ("took less than 2.5 seconds", operator.lt, 2.5),
            ("took more than 1 minute", operator.gt, 60.0),
            ("took less than 30 seconds", operator.lt, 30.0),
        ]

        for query, expected_op, expected_value in test_cases:
            result = self.parser.parse(query, self.available_metrics)
            assert result["parsed"] == True

            time_filter = next(
                (f for f in result["filters"] if f["type"] == "time_comparison"), None
            )
            assert time_filter is not None
            assert time_filter["operator"] == expected_op
            assert time_filter["value"] == expected_value

    def test_low_metric_queries(self):
        """Test parsing low metric score queries."""
        queries = [
            "Show me low relevancy scores",
            "Find poor accuracy items",
            "Display bad scores",
        ]

        for query in queries:
            result = self.parser.parse(query, self.available_metrics)
            assert result["parsed"] == True

            metric_filter = next(
                (f for f in result["filters"] if f["type"] == "metric_comparison"), None
            )
            assert metric_filter is not None
            assert metric_filter["operator"] == operator.lt
            assert metric_filter["value"] == self.parser.default_thresholds["low_score"]

    def test_high_metric_queries(self):
        """Test parsing high metric score queries."""
        queries = [
            "Show me high relevancy scores",
            "Find excellent accuracy items",
            "Display good scores",
        ]

        for query in queries:
            result = self.parser.parse(query, self.available_metrics)
            assert result["parsed"] == True

            metric_filter = next(
                (f for f in result["filters"] if f["type"] == "metric_comparison"), None
            )
            assert metric_filter is not None
            assert metric_filter["operator"] == operator.gt
            assert (
                metric_filter["value"] == self.parser.default_thresholds["high_score"]
            )

    def test_perfect_match_queries(self):
        """Test parsing perfect match queries."""
        queries = [
            "Show me perfect matches",
            "Find exact matches",
            "Display perfect scores",
        ]

        for query in queries:
            result = self.parser.parse(query, self.available_metrics)
            assert result["parsed"] == True

            metric_filter = next(
                (f for f in result["filters"] if f["type"] == "metric_comparison"), None
            )
            assert metric_filter is not None
            assert metric_filter["operator"] == operator.eq
            assert metric_filter["value"] == 1.0

    def test_zero_match_queries(self):
        """Test parsing zero match queries."""
        queries = ["Show me zero matches", "Find no match items", "Display zero scores"]

        for query in queries:
            result = self.parser.parse(query, self.available_metrics)
            assert result["parsed"] == True

            metric_filter = next(
                (f for f in result["filters"] if f["type"] == "metric_comparison"), None
            )
            assert metric_filter is not None
            assert metric_filter["operator"] == operator.eq
            assert metric_filter["value"] == 0.0

    def test_explicit_metric_comparisons(self):
        """Test parsing explicit metric comparison queries."""
        test_cases = [
            ("accuracy > 0.8", "accuracy", operator.gt, 0.8),
            ("exact_match >= 0.5", "exact_match", operator.ge, 0.5),
            ("relevancy < 0.3", "relevancy", operator.lt, 0.3),
            ("response_time <= 2.0", "response_time", operator.le, 2.0),
            ("accuracy_score = 1.0", "accuracy_score", operator.eq, 1.0),
            ("exact_match != 0", "exact_match", operator.ne, 0.0),
        ]

        for query, metric, expected_op, expected_value in test_cases:
            result = self.parser.parse(query, self.available_metrics)
            assert result["parsed"] == True

            metric_filter = next(
                (f for f in result["filters"] if f["type"] == "metric_comparison"), None
            )
            assert metric_filter is not None
            assert metric_filter["operator"] == expected_op
            assert metric_filter["value"] == expected_value

    def test_metric_threshold_queries(self):
        """Test parsing metric threshold queries."""
        test_cases = [
            ("accuracy above 0.8", "accuracy", operator.gt, 0.8),
            ("relevancy below 0.5", "relevancy", operator.lt, 0.5),
            ("exact_match over 0.9", "exact_match", operator.gt, 0.9),
            ("response_time under 3.0", "response_time", operator.lt, 3.0),
        ]

        for query, metric, expected_op, expected_value in test_cases:
            result = self.parser.parse(query, self.available_metrics)
            assert result["parsed"] == True

            metric_filter = next(
                (f for f in result["filters"] if f["type"] == "metric_comparison"), None
            )
            assert metric_filter is not None
            assert metric_filter["operator"] == expected_op
            assert metric_filter["value"] == expected_value

    def test_time_range_queries(self):
        """Test parsing time range queries."""
        test_cases = [
            ("between 1 and 5 seconds", 1.0, 5.0),
            ("between 0.5 and 2.5 seconds", 0.5, 2.5),
            ("between 1 and 2 minutes", 60.0, 120.0),
        ]

        for query, min_val, max_val in test_cases:
            result = self.parser.parse(query, self.available_metrics)
            assert result["parsed"] == True

            range_filter = next(
                (f for f in result["filters"] if f["type"] == "time_range"), None
            )
            assert range_filter is not None
            assert range_filter["min_value"] == min_val
            assert range_filter["max_value"] == max_val

    def test_metric_name_resolution(self):
        """Test metric name resolution with aliases."""
        # Test exact match
        result = self.parser._resolve_metric_name("exact_match", self.available_metrics)
        assert result == "exact_match"

        # Test alias resolution
        result = self.parser._resolve_metric_name("relevancy", self.available_metrics)
        assert result == "answer_relevancy"

        # Test partial match
        result = self.parser._resolve_metric_name("accuracy", self.available_metrics)
        assert result == "accuracy_score"

        # Test no match (returns original)
        result = self.parser._resolve_metric_name(
            "unknown_metric", self.available_metrics
        )
        assert result == "unknown_metric"

    def test_convert_to_numeric(self):
        """Test value conversion to numeric."""
        assert self.parser._convert_to_numeric(5) == 5.0
        assert self.parser._convert_to_numeric(3.14) == 3.14
        assert self.parser._convert_to_numeric(True) == 1.0
        assert self.parser._convert_to_numeric(False) == 0.0
        assert self.parser._convert_to_numeric("2.5") == 2.5
        assert self.parser._convert_to_numeric({"error": "test"}) is None
        assert self.parser._convert_to_numeric("invalid") is None


class TestEvaluationResultFiltering:
    """Test cases for filtering actual EvaluationResult objects."""

    def setup_method(self):
        """Set up test fixtures."""
        self.parser = SearchQueryParser()

        # Create mock evaluation result
        self.eval_result = EvaluationResult(
            dataset_name="test_dataset",
            run_name="test_run",
            metrics=["exact_match", "answer_relevancy", "response_time"],
        )

        # Add test results
        self.eval_result.results = {
            "item_0": {
                "output": "Good answer",
                "scores": {
                    "exact_match": 1.0,
                    "answer_relevancy": 0.9,
                    "response_time": 1.2,
                },
                "success": True,
                "time": 1.2,
            },
            "item_1": {
                "output": "Poor answer",
                "scores": {
                    "exact_match": 0.0,
                    "answer_relevancy": 0.3,
                    "response_time": 0.8,
                },
                "success": True,
                "time": 0.8,
            },
            "item_2": {
                "output": "Slow answer",
                "scores": {
                    "exact_match": 0.5,
                    "answer_relevancy": 0.7,
                    "response_time": 6.5,
                },
                "success": True,
                "time": 6.5,
            },
        }

        # Add error items
        self.eval_result.errors = {
            "item_3": "Timeout error",
            "item_4": "Connection failed",
        }

        self.eval_result.finish()

    def test_filter_failures(self):
        """Test filtering for failed evaluations."""
        result = self.parser.filter_results(self.eval_result, "Show me failures")

        assert result["total_matches"] == 2
        assert result["matched_items"] == []
        assert set(result["matched_errors"]) == {"item_3", "item_4"}

    def test_filter_successes(self):
        """Test filtering for successful evaluations."""
        result = self.parser.filter_results(self.eval_result, "Show me successes")

        assert result["total_matches"] == 3
        assert set(result["matched_items"]) == {"item_0", "item_1", "item_2"}
        assert result["matched_errors"] == []

    def test_filter_low_relevancy(self):
        """Test filtering for low relevancy scores."""
        result = self.parser.filter_results(
            self.eval_result, "Show me low relevancy scores"
        )

        assert result["total_matches"] == 1
        assert result["matched_items"] == ["item_1"]  # 0.3 < 0.5 (default threshold)

    def test_filter_perfect_matches(self):
        """Test filtering for perfect matches."""
        result = self.parser.filter_results(self.eval_result, "Show me perfect matches")

        assert result["total_matches"] == 1
        assert result["matched_items"] == ["item_0"]  # exact_match = 1.0

    def test_filter_slow_responses(self):
        """Test filtering for slow responses."""
        result = self.parser.filter_results(self.eval_result, "Show me slow responses")

        assert result["total_matches"] == 1
        assert result["matched_items"] == ["item_2"]  # 6.5s > 5.0s (default threshold)

    def test_filter_explicit_comparison(self):
        """Test filtering with explicit metric comparison."""
        result = self.parser.filter_results(self.eval_result, "answer_relevancy > 0.6")

        assert result["total_matches"] == 2
        assert set(result["matched_items"]) == {"item_0", "item_2"}  # 0.9 and 0.7 > 0.6

    def test_filter_time_threshold(self):
        """Test filtering with time threshold."""
        result = self.parser.filter_results(self.eval_result, "took more than 1 second")

        assert result["total_matches"] == 2
        assert set(result["matched_items"]) == {
            "item_0",
            "item_2",
        }  # 1.2s and 6.5s > 1.0s

    def test_filter_no_matches(self):
        """Test filtering with no matching results."""
        result = self.parser.filter_results(self.eval_result, "answer_relevancy > 0.95")

        assert result["total_matches"] == 0
        assert result["matched_items"] == []
        assert result["matched_errors"] == []

    def test_unparseable_query(self):
        """Test handling of unparseable queries."""
        result = self.parser.filter_results(
            self.eval_result, "some random text that means nothing"
        )

        # Should return all results when query can't be parsed
        assert result["total_matches"] == self.eval_result.total_items
        assert len(result["matched_items"]) == 3
        assert len(result["matched_errors"]) == 2


class TestSearchEngine:
    """Test cases for SearchEngine class."""

    def setup_method(self):
        """Set up test fixtures."""
        self.engine = SearchEngine()

        # Create mock evaluation result
        self.eval_result = EvaluationResult(
            dataset_name="test_dataset",
            run_name="test_run",
            metrics=["exact_match", "answer_relevancy"],
        )

        # Add some test data
        self.eval_result.results = {
            "item_0": {
                "scores": {"exact_match": 1.0, "answer_relevancy": 0.9},
                "success": True,
                "time": 1.0,
            }
        }
        self.eval_result.errors = {"item_1": "Error"}
        self.eval_result.finish()

    def test_search(self):
        """Test search functionality."""
        result = self.engine.search(self.eval_result, "Show me failures")

        assert "matched_items" in result
        assert "matched_errors" in result
        assert "total_matches" in result
        assert "query_info" in result

    def test_get_suggestions(self):
        """Test getting search suggestions."""
        suggestions = self.engine.get_suggestions(self.eval_result)

        assert isinstance(suggestions, list)
        assert len(suggestions) > 0
        assert (
            "Show me failures" in suggestions
        )  # Should suggest this since there are errors
        assert (
            "Show me successes" in suggestions
        )  # Should suggest this since there are results

        # Should include metric-based suggestions
        metric_suggestions = [
            s for s in suggestions if "exact_match" in s or "answer_relevancy" in s
        ]
        assert len(metric_suggestions) > 0


class TestComplexQueries:
    """Test cases for complex query combinations."""

    def setup_method(self):
        """Set up test fixtures."""
        self.parser = SearchQueryParser()

        # Create more complex evaluation result
        self.eval_result = EvaluationResult(
            dataset_name="complex_test",
            run_name="complex_run",
            metrics=["exact_match", "answer_relevancy", "accuracy_score"],
        )

        # Add varied test results
        test_data = [
            (
                "item_0",
                {"exact_match": 1.0, "answer_relevancy": 0.95, "accuracy_score": 0.9},
                True,
                0.5,
            ),
            (
                "item_1",
                {"exact_match": 0.0, "answer_relevancy": 0.2, "accuracy_score": 0.3},
                True,
                2.0,
            ),
            (
                "item_2",
                {"exact_match": 0.8, "answer_relevancy": 0.6, "accuracy_score": 0.7},
                True,
                1.5,
            ),
            (
                "item_3",
                {"exact_match": 0.3, "answer_relevancy": 0.4, "accuracy_score": 0.5},
                True,
                4.0,
            ),
            (
                "item_4",
                {"exact_match": 1.0, "answer_relevancy": 0.85, "accuracy_score": 0.95},
                True,
                7.0,
            ),
        ]

        for item_id, scores, success, time_val in test_data:
            self.eval_result.results[item_id] = {
                "scores": scores,
                "success": success,
                "time": time_val,
            }

        self.eval_result.finish()

    def test_multiple_pattern_matching(self):
        """Test queries that could match multiple patterns."""
        # This query could match both "failures" and "low relevancy" patterns
        result = self.parser.filter_results(
            self.eval_result, "Show me failed low relevancy scores"
        )

        assert result["parsed"] == True
        assert len(result["query_info"]["filters"]) >= 1

    def test_edge_case_values(self):
        """Test filtering with edge case metric values."""
        # Test exact boundary values
        result = self.parser.filter_results(self.eval_result, "accuracy_score >= 0.5")

        # Should include items with accuracy >= 0.5 (items 0, 2, 3, 4)
        assert result["total_matches"] == 4
        assert "item_1" not in result["matched_items"]  # 0.3 < 0.5

    def test_performance_with_large_dataset(self):
        """Test performance with larger dataset."""
        # Create larger evaluation result
        large_eval = EvaluationResult("large_test", "large_run", ["metric1", "metric2"])

        # Add 1000 items
        for i in range(1000):
            large_eval.results[f"item_{i}"] = {
                "scores": {
                    "metric1": i / 1000.0,  # 0.0 to 0.999
                    "metric2": (1000 - i) / 1000.0,  # 0.999 to 0.0
                },
                "success": True,
                "time": i / 100.0,  # 0.0 to 9.99 seconds
            }

        large_eval.finish()

        # Test filtering performance
        import time

        start_time = time.time()
        result = self.parser.filter_results(large_eval, "metric1 > 0.5")
        end_time = time.time()

        # Should complete quickly (< 1 second for 1000 items)
        assert (end_time - start_time) < 1.0

        # Should return correct number of matches (items 501-999, since 500/1000.0 = 0.5 is NOT > 0.5)
        assert result["total_matches"] == 499


if __name__ == "__main__":
    pytest.main([__file__])
