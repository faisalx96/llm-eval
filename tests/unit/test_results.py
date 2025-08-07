"""Unit tests for the EvaluationResult class."""

import pytest
import json
import csv
from datetime import datetime
from pathlib import Path
from llm_eval.core.results import EvaluationResult


@pytest.mark.unit
class TestEvaluationResult:
    """Test cases for the EvaluationResult class."""
    
    def test_initialization(self):
        """Test basic initialization of EvaluationResult."""
        result = EvaluationResult(
            dataset_name="test-dataset",
            run_name="test-run",
            metrics=["exact_match", "contains"]
        )
        
        assert result.dataset_name == "test-dataset"
        assert result.run_name == "test-run"
        assert result.metrics == ["exact_match", "contains"]
        assert isinstance(result.start_time, datetime)
        assert result.end_time is None
        assert result.results == {}
        assert result.errors == {}
    
    def test_add_result(self):
        """Test adding successful evaluation results."""
        result = EvaluationResult("test-dataset", "test-run", ["exact_match"])
        
        test_result = {
            "output": "Test output",
            "scores": {"exact_match": 1.0},
            "success": True,
            "time": 0.5
        }
        
        result.add_result("item_1", test_result)
        
        assert "item_1" in result.results
        assert result.results["item_1"] == test_result
    
    def test_add_error(self):
        """Test adding evaluation errors."""
        result = EvaluationResult("test-dataset", "test-run", ["exact_match"])
        
        result.add_error("item_1", "Connection timeout")
        
        assert "item_1" in result.errors
        assert result.errors["item_1"] == "Connection timeout"
    
    def test_finish(self):
        """Test marking evaluation as finished."""
        result = EvaluationResult("test-dataset", "test-run", ["exact_match"])
        
        assert result.end_time is None
        result.finish()
        assert isinstance(result.end_time, datetime)
        assert result.end_time > result.start_time
    
    def test_total_items(self):
        """Test total items calculation."""
        result = EvaluationResult("test-dataset", "test-run", ["exact_match"])
        
        assert result.total_items == 0
        
        result.add_result("item_1", {"success": True})
        result.add_result("item_2", {"success": True})
        result.add_error("item_3", "Error")
        
        assert result.total_items == 3
    
    def test_success_rate_empty(self):
        """Test success rate calculation with no items."""
        result = EvaluationResult("test-dataset", "test-run", ["exact_match"])
        assert result.success_rate == 0.0
    
    def test_success_rate_all_success(self):
        """Test success rate calculation with all successful items."""
        result = EvaluationResult("test-dataset", "test-run", ["exact_match"])
        
        result.add_result("item_1", {"success": True})
        result.add_result("item_2", {"success": True})
        
        assert result.success_rate == 1.0
    
    def test_success_rate_mixed(self):
        """Test success rate calculation with mixed results."""
        result = EvaluationResult("test-dataset", "test-run", ["exact_match"])
        
        result.add_result("item_1", {"success": True})
        result.add_result("item_2", {"success": True})
        result.add_error("item_3", "Error")
        result.add_error("item_4", "Error")
        
        assert result.success_rate == 0.5
    
    def test_duration_before_finish(self):
        """Test duration calculation before finishing."""
        result = EvaluationResult("test-dataset", "test-run", ["exact_match"])
        assert result.duration is None
    
    def test_duration_after_finish(self):
        """Test duration calculation after finishing."""
        result = EvaluationResult("test-dataset", "test-run", ["exact_match"])
        result.finish()
        
        duration = result.duration
        assert isinstance(duration, float)
        assert duration >= 0
    
    def test_get_metric_stats_empty(self):
        """Test metric statistics with no results."""
        result = EvaluationResult("test-dataset", "test-run", ["exact_match"])
        
        stats = result.get_metric_stats("exact_match")
        
        assert stats["mean"] == 0.0
        assert stats["std"] == 0.0
        assert stats["min"] == 0.0
        assert stats["max"] == 0.0
        assert stats["success_rate"] == 0.0
    
    def test_get_metric_stats_numeric(self):
        """Test metric statistics with numeric scores."""
        result = EvaluationResult("test-dataset", "test-run", ["accuracy"])
        
        result.add_result("item_1", {"scores": {"accuracy": 0.8}})
        result.add_result("item_2", {"scores": {"accuracy": 0.9}})
        result.add_result("item_3", {"scores": {"accuracy": 0.7}})
        
        stats = result.get_metric_stats("accuracy")
        
        assert stats["mean"] == pytest.approx(0.8, rel=1e-3)
        assert stats["std"] == pytest.approx(0.1, rel=1e-1)
        assert stats["min"] == 0.7
        assert stats["max"] == 0.9
        assert stats["success_rate"] == 1.0
    
    def test_get_metric_stats_boolean(self):
        """Test metric statistics with boolean scores."""
        result = EvaluationResult("test-dataset", "test-run", ["exact_match"])
        
        result.add_result("item_1", {"scores": {"exact_match": True}})
        result.add_result("item_2", {"scores": {"exact_match": False}})
        result.add_result("item_3", {"scores": {"exact_match": True}})
        
        stats = result.get_metric_stats("exact_match")
        
        assert stats["mean"] == pytest.approx(2.0/3.0, rel=1e-3)
        assert stats["min"] == 0.0
        assert stats["max"] == 1.0
        assert stats["success_rate"] == 1.0
    
    def test_get_metric_stats_with_errors(self):
        """Test metric statistics with some errors."""
        result = EvaluationResult("test-dataset", "test-run", ["accuracy"])
        
        result.add_result("item_1", {"scores": {"accuracy": 0.8}})
        result.add_result("item_2", {"scores": {"accuracy": {"error": "Failed"}}})
        result.add_result("item_3", {"scores": {"accuracy": 0.9}})
        
        stats = result.get_metric_stats("accuracy")
        
        assert stats["mean"] == pytest.approx(0.85, rel=1e-3)
        assert stats["success_rate"] == pytest.approx(2.0/3.0, rel=1e-3)
    
    def test_get_timing_stats_empty(self):
        """Test timing statistics with no results."""
        result = EvaluationResult("test-dataset", "test-run", ["exact_match"])
        
        stats = result.get_timing_stats()
        
        assert stats["mean"] == 0.0
        assert stats["std"] == 0.0
        assert stats["min"] == 0.0
        assert stats["max"] == 0.0
        assert stats["total"] == 0.0
    
    def test_get_timing_stats_with_times(self):
        """Test timing statistics with actual timing data."""
        result = EvaluationResult("test-dataset", "test-run", ["exact_match"])
        
        result.add_result("item_1", {"time": 0.5})
        result.add_result("item_2", {"time": 1.0})
        result.add_result("item_3", {"time": 0.75})
        
        stats = result.get_timing_stats()
        
        assert stats["mean"] == pytest.approx(0.75, rel=1e-3)
        assert stats["min"] == 0.5
        assert stats["max"] == 1.0
        assert stats["total"] == 2.25
    
    def test_summary_text(self):
        """Test text summary generation."""
        result = EvaluationResult("test-dataset", "test-run", ["exact_match"])
        
        result.add_result("item_1", {
            "scores": {"exact_match": 1.0},
            "time": 0.5
        })
        result.add_result("item_2", {
            "scores": {"exact_match": 0.0}, 
            "time": 0.3
        })
        result.add_error("item_3", "Connection failed")
        result.finish()
        
        summary = result.summary()
        
        assert "test-run" in summary
        assert "test-dataset" in summary
        assert "Total Items: 3" in summary
        assert "Success Rate: 66.7%" in summary
        assert "exact_match:" in summary
        assert "Errors: 1 items failed" in summary
    
    def test_to_dict(self):
        """Test conversion to dictionary format."""
        result = EvaluationResult("test-dataset", "test-run", ["exact_match"])
        
        result.add_result("item_1", {
            "scores": {"exact_match": 1.0},
            "success": True
        })
        result.add_error("item_2", "Error message")
        result.finish()
        
        data = result.to_dict()
        
        assert data["dataset_name"] == "test-dataset"
        assert data["run_name"] == "test-run"
        assert data["metrics"] == ["exact_match"]
        assert data["total_items"] == 2
        assert data["success_rate"] == 0.5
        assert "results" in data
        assert "errors" in data
        assert "metric_stats" in data
        assert "exact_match" in data["metric_stats"]
    
    def test_failed_items(self):
        """Test getting list of failed item IDs."""
        result = EvaluationResult("test-dataset", "test-run", ["exact_match"])
        
        result.add_result("item_1", {"success": True})
        result.add_error("item_2", "Error 1")
        result.add_error("item_3", "Error 2")
        
        failed = result.failed_items()
        
        assert len(failed) == 2
        assert "item_2" in failed
        assert "item_3" in failed
    
    def test_successful_items(self):
        """Test getting list of successful item IDs."""
        result = EvaluationResult("test-dataset", "test-run", ["exact_match"])
        
        result.add_result("item_1", {"success": True})
        result.add_result("item_2", {"success": True})
        result.add_error("item_3", "Error")
        
        successful = result.successful_items()
        
        assert len(successful) == 2
        assert "item_1" in successful
        assert "item_2" in successful
    
    def test_save_json(self, temp_dir):
        """Test saving results to JSON file."""
        result = EvaluationResult("test-dataset", "test-run", ["exact_match"])
        
        result.add_result("item_1", {
            "scores": {"exact_match": 1.0},
            "success": True
        })
        result.finish()
        
        filepath = temp_dir / "test_results.json"
        saved_path = result.save_json(str(filepath))
        
        assert saved_path == str(filepath)
        assert filepath.exists()
        
        # Verify file contents
        with open(filepath) as f:
            data = json.load(f)
        
        assert data["dataset_name"] == "test-dataset"
        assert data["run_name"] == "test-run"
        assert "item_1" in data["results"]
    
    def test_save_json_auto_filename(self, temp_dir):
        """Test saving JSON with auto-generated filename."""
        result = EvaluationResult("test-dataset", "test-run", ["exact_match"])
        result.finish()
        
        # Change to temp directory for auto-generated file
        import os
        original_cwd = os.getcwd()
        os.chdir(temp_dir)
        
        try:
            saved_path = result.save_json()
            
            assert saved_path.startswith("eval_results_test-dataset_")
            assert saved_path.endswith(".json")
            assert Path(saved_path).exists()
        finally:
            os.chdir(original_cwd)
    
    def test_save_csv(self, temp_dir):
        """Test saving results to CSV file."""
        result = EvaluationResult("test-dataset", "test-run", ["exact_match", "contains"])
        
        result.add_result("item_1", {
            "output": "Test output 1",
            "scores": {"exact_match": 1.0, "contains": 0.8},
            "success": True,
            "time": 0.5
        })
        result.add_result("item_2", {
            "output": "Test output 2",
            "scores": {"exact_match": 0.0, "contains": {"error": "Failed"}},
            "success": True,
            "time": 0.3
        })
        result.add_error("item_3", "Connection failed")
        
        filepath = temp_dir / "test_results.csv"
        saved_path = result.save_csv(str(filepath))
        
        assert saved_path == str(filepath)
        assert filepath.exists()
        
        # Verify file contents
        with open(filepath, newline='') as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        
        assert len(rows) == 3
        
        # Check successful item
        assert rows[0]["item_id"] == "item_1"
        assert rows[0]["success"] == "True"
        assert rows[0]["metric_exact_match"] == "1.0"
        assert rows[0]["metric_contains"] == "0.8"
        
        # Check item with metric error
        assert rows[1]["item_id"] == "item_2"
        assert rows[1]["metric_exact_match"] == "0.0"
        assert rows[1]["metric_contains"] == "ERROR"
        assert "Failed" in rows[1]["metric_contains_error"]
        
        # Check failed item
        assert rows[2]["item_id"] == "item_3"
        assert rows[2]["success"] == "False"
        assert "ERROR: Connection failed" in rows[2]["output"]
    
    def test_save_format_json(self, temp_dir):
        """Test save method with JSON format."""
        result = EvaluationResult("test-dataset", "test-run", ["exact_match"])
        result.finish()
        
        filepath = temp_dir / "test_results.json"
        saved_path = result.save(format="json", filepath=str(filepath))
        
        assert saved_path == str(filepath)
        assert filepath.exists()
    
    def test_save_format_csv(self, temp_dir):
        """Test save method with CSV format."""
        result = EvaluationResult("test-dataset", "test-run", ["exact_match"])
        result.finish()
        
        filepath = temp_dir / "test_results.csv"
        saved_path = result.save(format="csv", filepath=str(filepath))
        
        assert saved_path == str(filepath)
        assert filepath.exists()
    
    def test_save_invalid_format(self, temp_dir):
        """Test save method with invalid format."""
        result = EvaluationResult("test-dataset", "test-run", ["exact_match"])
        
        filepath = temp_dir / "test_results.txt"
        
        with pytest.raises(ValueError) as exc_info:
            result.save(format="txt", filepath=str(filepath))
        
        assert "Unsupported format: txt" in str(exc_info.value)