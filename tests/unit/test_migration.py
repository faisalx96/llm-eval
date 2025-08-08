"""Comprehensive unit tests for migration utility functions.

This module tests the migration of EvaluationResult to database storage,
including all helper functions and edge cases.
"""

import json
import tempfile
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from llm_eval.core.results import EvaluationResult
from llm_eval.models.run_models import Base, EvaluationItem, EvaluationRun, RunMetric
from llm_eval.storage.migration import (
    _compute_percentiles,
    _compute_score_distribution,
    _convert_evaluation_result_to_run_data,
    _determine_metric_type,
    _get_environment_info,
    _infer_task_type,
    _store_evaluation_items,
    _store_run_metrics,
    migrate_from_evaluation_result,
    migrate_json_export,
)


@pytest.fixture
def in_memory_db():
    """Create in-memory SQLite database for testing."""
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    return engine, SessionLocal


@pytest.fixture
def test_session(in_memory_db):
    """Create test database session."""
    engine, SessionLocal = in_memory_db
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture
def mock_evaluation_result():
    """Create mock EvaluationResult for testing."""
    mock_result = Mock(spec=EvaluationResult)
    mock_result.run_name = "Test Evaluation Run"
    mock_result.dataset_name = "test_dataset"
    mock_result.metrics = ["exact_match", "answer_relevancy"]
    mock_result.start_time = datetime(2023, 1, 1, 12, 0, 0)
    mock_result.end_time = datetime(2023, 1, 1, 12, 10, 0)
    mock_result.duration = 600.0
    mock_result.total_items = 10
    mock_result.success_rate = 0.8

    mock_result.results = {
        "item_1": {
            "input": "What is the capital of France?",
            "expected": "Paris",
            "output": "Paris is the capital of France.",
            "scores": {"exact_match": 1.0, "answer_relevancy": 0.95},
            "time": 2.5,
            "tokens": 25,
            "cost": 0.001,
            "trace_id": "trace_1",
            "observation_id": "obs_1",
        },
        "item_2": {
            "input": "What is 2+2?",
            "expected": "4",
            "output": "4",
            "scores": {"exact_match": 1.0, "answer_relevancy": 1.0},
            "time": 1.8,
            "tokens": 15,
            "cost": 0.0008,
        },
        "item_3": {
            "input": "What color is grass?",
            "expected": "Green",
            "output": "Green",
            "scores": {"exact_match": 1.0, "answer_relevancy": 0.9},
            "time": 2.1,
            "success": True,
        },
    }

    mock_result.errors = {
        "item_4": "API timeout error",
        "item_5": "Rate limit exceeded",
    }

    mock_result.get_timing_stats.return_value = {
        "mean": 2.13,
        "min": 1.8,
        "max": 2.5,
        "std": 0.35,
    }

    mock_result.get_metric_stats.side_effect = lambda metric: {
        "exact_match": {
            "mean": 1.0,
            "min": 1.0,
            "max": 1.0,
            "std": 0.0,
            "success_rate": 1.0,
        },
        "answer_relevancy": {
            "mean": 0.95,
            "min": 0.9,
            "max": 1.0,
            "std": 0.05,
            "success_rate": 1.0,
        },
    }[metric]

    return mock_result


class TestMigrateFromEvaluationResult:
    """Test the main migration function."""

    @patch("llm_eval.storage.migration.RunRepository")
    @patch("llm_eval.storage.migration._store_evaluation_items")
    @patch("llm_eval.storage.migration._store_run_metrics")
    def test_migrate_success(
        self,
        mock_store_metrics,
        mock_store_items,
        mock_repo_class,
        mock_evaluation_result,
    ):
        """Test successful migration of EvaluationResult."""
        # Setup mocks
        mock_repo = Mock()
        mock_run = Mock()
        mock_run.id = uuid.uuid4()
        mock_repo.create_run.return_value = mock_run
        mock_repo_class.return_value = mock_repo

        # Execute migration
        run_id = migrate_from_evaluation_result(
            mock_evaluation_result,
            project_id="test_project",
            created_by="test_user",
            tags=["test", "migration"],
        )

        # Verify results
        assert run_id == str(mock_run.id)
        mock_repo.create_run.assert_called_once()
        mock_store_items.assert_called_once_with(
            mock_evaluation_result, str(mock_run.id), mock_repo
        )
        mock_store_metrics.assert_called_once_with(
            mock_evaluation_result, str(mock_run.id), mock_repo
        )

        # Verify run data structure
        call_args = mock_repo.create_run.call_args[0][0]
        assert call_args["name"] == "Test Evaluation Run"
        assert call_args["dataset_name"] == "test_dataset"
        assert call_args["project_id"] == "test_project"
        assert call_args["created_by"] == "test_user"
        assert call_args["tags"] == ["test", "migration"]

    @patch("llm_eval.storage.migration.RunRepository")
    def test_migrate_without_individual_items(
        self, mock_repo_class, mock_evaluation_result
    ):
        """Test migration without storing individual items."""
        mock_repo = Mock()
        mock_run = Mock()
        mock_run.id = uuid.uuid4()
        mock_repo.create_run.return_value = mock_run
        mock_repo_class.return_value = mock_repo

        with patch(
            "llm_eval.storage.migration._store_evaluation_items"
        ) as mock_store_items, patch(
            "llm_eval.storage.migration._store_run_metrics"
        ) as mock_store_metrics:

            migrate_from_evaluation_result(
                mock_evaluation_result, store_individual_items=False
            )

            mock_store_items.assert_not_called()
            mock_store_metrics.assert_called_once()

    @patch("llm_eval.storage.migration.RunRepository")
    def test_migrate_error_handling(self, mock_repo_class, mock_evaluation_result):
        """Test error handling in migration."""
        mock_repo = Mock()
        mock_repo.create_run.side_effect = Exception("Database error")
        mock_repo_class.return_value = mock_repo

        with pytest.raises(Exception, match="Database error"):
            migrate_from_evaluation_result(mock_evaluation_result)

    def test_migrate_with_defaults(self, mock_evaluation_result):
        """Test migration with default parameters."""
        with patch(
            "llm_eval.storage.migration.RunRepository"
        ) as mock_repo_class, patch(
            "llm_eval.storage.migration._store_evaluation_items"
        ), patch(
            "llm_eval.storage.migration._store_run_metrics"
        ):

            mock_repo = Mock()
            mock_run = Mock()
            mock_run.id = uuid.uuid4()
            mock_repo.create_run.return_value = mock_run
            mock_repo_class.return_value = mock_repo

            run_id = migrate_from_evaluation_result(mock_evaluation_result)

            assert run_id == str(mock_run.id)

            # Verify default parameters in run data
            call_args = mock_repo.create_run.call_args[0][0]
            assert call_args["project_id"] is None
            assert call_args["created_by"] is None
            assert call_args["tags"] == []


class TestConvertEvaluationResultToRunData:
    """Test conversion of EvaluationResult to run data dictionary."""

    def test_convert_basic_data(self, mock_evaluation_result):
        """Test basic data conversion."""
        run_data = _convert_evaluation_result_to_run_data(mock_evaluation_result)

        assert run_data["name"] == "Test Evaluation Run"
        assert run_data["dataset_name"] == "test_dataset"
        assert run_data["status"] == "completed"
        assert run_data["metrics_used"] == ["exact_match", "answer_relevancy"]
        assert run_data["created_at"] == datetime(2023, 1, 1, 12, 0, 0)
        assert run_data["completed_at"] == datetime(2023, 1, 1, 12, 10, 0)
        assert run_data["duration_seconds"] == 600.0
        assert run_data["total_items"] == 10
        assert run_data["success_rate"] == 0.8

    def test_convert_with_parameters(self, mock_evaluation_result):
        """Test conversion with additional parameters."""
        run_data = _convert_evaluation_result_to_run_data(
            mock_evaluation_result,
            project_id="test_project",
            created_by="test_user",
            tags=["tag1", "tag2"],
        )

        assert run_data["project_id"] == "test_project"
        assert run_data["created_by"] == "test_user"
        assert run_data["tags"] == ["tag1", "tag2"]

    def test_convert_timing_stats(self, mock_evaluation_result):
        """Test timing statistics conversion."""
        run_data = _convert_evaluation_result_to_run_data(mock_evaluation_result)

        assert run_data["avg_response_time"] == 2.13
        assert run_data["min_response_time"] == 1.8
        assert run_data["max_response_time"] == 2.5

    def test_convert_success_counts(self, mock_evaluation_result):
        """Test success/failure count calculation."""
        run_data = _convert_evaluation_result_to_run_data(mock_evaluation_result)

        assert run_data["successful_items"] == 3  # len(results)
        assert run_data["failed_items"] == 2  # len(errors)

    @patch("llm_eval.storage.migration._infer_task_type")
    @patch("llm_eval.storage.migration._get_environment_info")
    def test_convert_calls_helpers(
        self, mock_env_info, mock_task_type, mock_evaluation_result
    ):
        """Test that helper functions are called."""
        mock_task_type.return_value = "qa"
        mock_env_info.return_value = {"test": "env"}

        run_data = _convert_evaluation_result_to_run_data(mock_evaluation_result)

        mock_task_type.assert_called_once_with(["exact_match", "answer_relevancy"])
        mock_env_info.assert_called_once()
        assert run_data["task_type"] == "qa"
        assert run_data["environment"] == {"test": "env"}


class TestInferTaskType:
    """Test task type inference from metrics."""

    def test_infer_qa_task(self):
        """Test QA task type inference."""
        assert _infer_task_type(["exact_match", "f1"]) == "qa"
        assert _infer_task_type(["exact_match"]) == "qa"
        assert _infer_task_type(["f1", "other_metric"]) == "qa"

    def test_infer_classification_task(self):
        """Test classification task type inference."""
        assert _infer_task_type(["accuracy", "precision"]) == "classification"
        assert _infer_task_type(["precision", "recall"]) == "classification"

    def test_infer_summarization_task(self):
        """Test summarization task type inference."""
        assert _infer_task_type(["rouge", "bleu"]) == "summarization"
        assert _infer_task_type(["rouge_l", "rouge_1"]) == "summarization"

    def test_infer_rag_task(self):
        """Test RAG task type inference."""
        assert _infer_task_type(["faithfulness", "answer_relevancy"]) == "rag"
        assert _infer_task_type(["answer_relevancy"]) == "rag"

    def test_infer_general_task(self):
        """Test general task type for unknown metrics."""
        assert _infer_task_type(["custom_metric", "unknown"]) == "general"
        assert _infer_task_type([]) == "general"

    def test_infer_case_insensitive(self):
        """Test case-insensitive metric matching."""
        assert _infer_task_type(["EXACT_MATCH", "F1"]) == "qa"
        assert _infer_task_type(["Accuracy"]) == "classification"


class TestGetEnvironmentInfo:
    """Test environment information gathering."""

    @patch("platform.platform")
    @patch("sys.version")
    def test_get_environment_info(self, mock_sys_version, mock_platform):
        """Test environment information collection."""
        mock_sys_version = "3.9.0"
        mock_platform.return_value = "Linux-5.4.0-x86_64"

        env_info = _get_environment_info()

        assert "python_version" in env_info
        assert "platform" in env_info
        assert "migration_timestamp" in env_info
        assert env_info["migration_source"] == "EvaluationResult"

        # Verify timestamp is ISO format
        timestamp = env_info["migration_timestamp"]
        datetime.fromisoformat(timestamp)  # Should not raise


class TestStoreEvaluationItems:
    """Test storing individual evaluation items."""

    @patch("llm_eval.storage.migration.get_database_manager")
    def test_store_evaluation_items_success(
        self, mock_db_manager, mock_evaluation_result, test_session
    ):
        """Test successful storage of evaluation items."""
        mock_db_manager.return_value.get_session.return_value.__enter__ = Mock(
            return_value=test_session
        )
        mock_db_manager.return_value.get_session.return_value.__exit__ = Mock(
            return_value=None
        )

        mock_repo = Mock()
        run_id = str(uuid.uuid4())

        _store_evaluation_items(mock_evaluation_result, run_id, mock_repo)

        # Verify items were added to session
        items = test_session.query(EvaluationItem).all()
        assert len(items) == 5  # 3 successful + 2 failed

        # Check successful items
        successful_items = [item for item in items if item.status == "completed"]
        assert len(successful_items) == 3

        item1 = next(item for item in successful_items if item.item_id == "item_1")
        assert item1.input_data == "What is the capital of France?"
        assert item1.expected_output == "Paris"
        assert item1.actual_output == "Paris is the capital of France."
        assert item1.response_time == 2.5
        assert item1.tokens_used == 25
        assert item1.cost == 0.001
        assert item1.scores == {"exact_match": 1.0, "answer_relevancy": 0.95}
        assert item1.langfuse_trace_id == "trace_1"
        assert item1.langfuse_observation_id == "obs_1"

        # Check failed items
        failed_items = [item for item in items if item.status == "failed"]
        assert len(failed_items) == 2

        failed_item = next(item for item in failed_items if item.item_id == "item_4")
        assert failed_item.error_message == "API timeout error"
        assert failed_item.error_type == "evaluation_error"

    def test_store_evaluation_items_sequence_numbers(self, mock_evaluation_result):
        """Test that sequence numbers are assigned correctly."""
        with patch(
            "llm_eval.storage.migration.get_database_manager"
        ) as mock_db_manager:
            mock_session = Mock()
            mock_db_manager.return_value.get_session.return_value.__enter__ = Mock(
                return_value=mock_session
            )
            mock_db_manager.return_value.get_session.return_value.__exit__ = Mock(
                return_value=None
            )

            mock_repo = Mock()
            run_id = str(uuid.uuid4())

            _store_evaluation_items(mock_evaluation_result, run_id, mock_repo)

            # Verify sequence numbers
            add_calls = mock_session.add.call_args_list
            sequence_numbers = [call[0][0].sequence_number for call in add_calls]

            # Should be sequential starting from 1
            assert sequence_numbers == [1, 2, 3, 4, 5]

    def test_store_evaluation_items_uuid_handling(self, mock_evaluation_result):
        """Test proper UUID handling for run_id."""
        with patch(
            "llm_eval.storage.migration.get_database_manager"
        ) as mock_db_manager:
            mock_session = Mock()
            mock_db_manager.return_value.get_session.return_value.__enter__ = Mock(
                return_value=mock_session
            )
            mock_db_manager.return_value.get_session.return_value.__exit__ = Mock(
                return_value=None
            )

            mock_repo = Mock()

            # Test with string UUID
            string_uuid = str(uuid.uuid4())
            _store_evaluation_items(mock_evaluation_result, string_uuid, mock_repo)

            # Verify UUID conversion
            add_calls = mock_session.add.call_args_list
            for call in add_calls:
                item = call[0][0]
                assert isinstance(item.run_id, uuid.UUID)


class TestStoreRunMetrics:
    """Test storing run metrics."""

    @patch("llm_eval.storage.migration.get_database_manager")
    @patch("llm_eval.storage.migration._compute_score_distribution")
    @patch("llm_eval.storage.migration._compute_percentiles")
    @patch("llm_eval.storage.migration._determine_metric_type")
    def test_store_run_metrics_success(
        self,
        mock_metric_type,
        mock_percentiles,
        mock_distribution,
        mock_db_manager,
        mock_evaluation_result,
        test_session,
    ):
        """Test successful storage of run metrics."""
        # Setup mocks
        mock_db_manager.return_value.get_session.return_value.__enter__ = Mock(
            return_value=test_session
        )
        mock_db_manager.return_value.get_session.return_value.__exit__ = Mock(
            return_value=None
        )

        mock_distribution.return_value = {"buckets": [0, 1], "counts": [1, 2]}
        mock_percentiles.return_value = {"p50": 0.95, "p90": 0.98}
        mock_metric_type.return_value = "numeric"

        mock_repo = Mock()
        run_id = str(uuid.uuid4())

        _store_run_metrics(mock_evaluation_result, run_id, mock_repo)

        # Verify metrics were added
        metrics = test_session.query(RunMetric).all()
        assert len(metrics) == 2  # exact_match and answer_relevancy

        # Check exact_match metric
        exact_match_metric = next(m for m in metrics if m.metric_name == "exact_match")
        assert exact_match_metric.metric_type == "numeric"
        assert exact_match_metric.mean_score == 1.0
        assert exact_match_metric.min_score == 1.0
        assert exact_match_metric.max_score == 1.0
        assert exact_match_metric.std_dev == 0.0
        assert exact_match_metric.total_evaluated == 3
        assert exact_match_metric.successful_evaluations == 3  # All have scores
        assert exact_match_metric.failed_evaluations == 2
        assert exact_match_metric.success_rate == 1.0

        # Verify helper functions were called
        assert mock_distribution.call_count == 2
        assert mock_percentiles.call_count == 2
        assert mock_metric_type.call_count == 2

    def test_store_run_metrics_successful_evaluations_count(
        self, mock_evaluation_result
    ):
        """Test calculation of successful evaluations count."""
        with patch(
            "llm_eval.storage.migration.get_database_manager"
        ) as mock_db_manager, patch(
            "llm_eval.storage.migration._compute_score_distribution"
        ), patch(
            "llm_eval.storage.migration._compute_percentiles"
        ), patch(
            "llm_eval.storage.migration._determine_metric_type"
        ):

            mock_session = Mock()
            mock_db_manager.return_value.get_session.return_value.__enter__ = Mock(
                return_value=mock_session
            )
            mock_db_manager.return_value.get_session.return_value.__exit__ = Mock(
                return_value=None
            )

            # Modify mock to have some items without scores for answer_relevancy
            mock_evaluation_result.results["item_2"]["scores"] = {
                "exact_match": 1.0
            }  # Missing answer_relevancy

            mock_repo = Mock()
            run_id = str(uuid.uuid4())

            _store_run_metrics(mock_evaluation_result, run_id, mock_repo)

            # Check successful evaluations count
            add_calls = mock_session.add.call_args_list
            metrics_data = [call[0][0] for call in add_calls]

            exact_match_metric = next(
                m for m in metrics_data if m.metric_name == "exact_match"
            )
            assert (
                exact_match_metric.successful_evaluations == 3
            )  # All items have exact_match

            relevancy_metric = next(
                m for m in metrics_data if m.metric_name == "answer_relevancy"
            )
            assert (
                relevancy_metric.successful_evaluations == 2
            )  # Only 2 items have answer_relevancy


class TestComputeScoreDistribution:
    """Test score distribution computation."""

    def test_compute_score_distribution_numeric(self, mock_evaluation_result):
        """Test distribution computation for numeric scores."""
        distribution = _compute_score_distribution(
            mock_evaluation_result, "answer_relevancy", num_buckets=5
        )

        assert "buckets" in distribution
        assert "counts" in distribution
        assert "total_scores" in distribution
        assert distribution["total_scores"] == 3
        assert len(distribution["buckets"]) == 6  # num_buckets + 1
        assert len(distribution["counts"]) == 5
        assert sum(distribution["counts"]) == 3

    def test_compute_score_distribution_boolean(self, mock_evaluation_result):
        """Test distribution computation for boolean scores."""
        # Modify mock to have boolean scores
        for item_result in mock_evaluation_result.results.values():
            item_result["scores"]["boolean_metric"] = True
        mock_evaluation_result.results["item_1"]["scores"]["boolean_metric"] = False

        distribution = _compute_score_distribution(
            mock_evaluation_result, "boolean_metric"
        )

        assert distribution["total_scores"] == 3
        # Should convert booleans to 0.0/1.0
        assert sum(distribution["counts"]) == 3

    def test_compute_score_distribution_no_scores(self, mock_evaluation_result):
        """Test distribution computation when no scores exist."""
        distribution = _compute_score_distribution(
            mock_evaluation_result, "nonexistent_metric"
        )

        assert distribution == {"buckets": [], "counts": []}

    def test_compute_score_distribution_single_value(self, mock_evaluation_result):
        """Test distribution computation with all identical scores."""
        # Set all scores to same value
        for item_result in mock_evaluation_result.results.values():
            item_result["scores"]["constant_metric"] = 0.5

        distribution = _compute_score_distribution(
            mock_evaluation_result, "constant_metric"
        )

        assert len(distribution["buckets"]) == 1
        assert len(distribution["counts"]) == 1
        assert distribution["counts"][0] == 3


class TestComputePercentiles:
    """Test percentile computation."""

    def test_compute_percentiles_normal(self):
        """Test percentile computation with normal data."""
        mock_result = Mock()
        mock_result.results = {
            f"item_{i}": {"scores": {"test_metric": i * 0.1}}
            for i in range(11)  # 0.0 to 1.0 in 0.1 increments
        }

        percentiles = _compute_percentiles(mock_result, "test_metric")

        assert "p25" in percentiles
        assert "p50" in percentiles  # median
        assert "p75" in percentiles
        assert "p90" in percentiles
        assert "p95" in percentiles
        assert "p99" in percentiles

        # Basic sanity checks
        assert percentiles["p25"] <= percentiles["p50"]
        assert percentiles["p50"] <= percentiles["p75"]
        assert percentiles["p75"] <= percentiles["p90"]

    def test_compute_percentiles_boolean(self):
        """Test percentile computation with boolean values."""
        mock_result = Mock()
        mock_result.results = {
            "item_1": {"scores": {"bool_metric": True}},
            "item_2": {"scores": {"bool_metric": False}},
            "item_3": {"scores": {"bool_metric": True}},
        }

        percentiles = _compute_percentiles(mock_result, "bool_metric")

        # Should convert booleans to 0.0/1.0
        assert 0.0 <= percentiles["p50"] <= 1.0
        assert len(percentiles) == 6

    def test_compute_percentiles_no_scores(self):
        """Test percentile computation with no scores."""
        mock_result = Mock()
        mock_result.results = {"item_1": {"scores": {}}}

        percentiles = _compute_percentiles(mock_result, "nonexistent")
        assert percentiles == {}

    def test_compute_percentiles_single_value(self):
        """Test percentile computation with single value."""
        mock_result = Mock()
        mock_result.results = {"item_1": {"scores": {"single_metric": 0.75}}}

        percentiles = _compute_percentiles(mock_result, "single_metric")

        # All percentiles should be the same value
        for key, value in percentiles.items():
            assert value == 0.75


class TestDetermineMetricType:
    """Test metric type determination."""

    def test_determine_metric_type_boolean(self):
        """Test boolean metric type detection."""
        mock_result = Mock()
        mock_result.results = {"item_1": {"scores": {"bool_metric": True}}}

        metric_type = _determine_metric_type(mock_result, "bool_metric")
        assert metric_type == "boolean"

    def test_determine_metric_type_numeric_int(self):
        """Test numeric metric type detection with integers."""
        mock_result = Mock()
        mock_result.results = {"item_1": {"scores": {"int_metric": 5}}}

        metric_type = _determine_metric_type(mock_result, "int_metric")
        assert metric_type == "numeric"

    def test_determine_metric_type_numeric_float(self):
        """Test numeric metric type detection with floats."""
        mock_result = Mock()
        mock_result.results = {"item_1": {"scores": {"float_metric": 0.85}}}

        metric_type = _determine_metric_type(mock_result, "float_metric")
        assert metric_type == "numeric"

    def test_determine_metric_type_custom(self):
        """Test custom metric type detection."""
        mock_result = Mock()
        mock_result.results = {"item_1": {"scores": {"custom_metric": "custom_value"}}}

        metric_type = _determine_metric_type(mock_result, "custom_metric")
        assert metric_type == "custom"

    def test_determine_metric_type_unknown(self):
        """Test unknown metric type when no scores found."""
        mock_result = Mock()
        mock_result.results = {"item_1": {"scores": {}}}

        metric_type = _determine_metric_type(mock_result, "nonexistent")
        assert metric_type == "unknown"


class TestMigrateJsonExport:
    """Test migration from JSON export files."""

    def test_migrate_json_export_success(self, tmp_path):
        """Test successful JSON export migration."""
        # Create test JSON file
        json_data = {
            "dataset_name": "test_dataset",
            "run_name": "JSON Export Test",
            "metrics": ["exact_match", "similarity"],
            "start_time": "2023-01-01T12:00:00",
            "end_time": "2023-01-01T12:05:00",
            "results": {
                "item_1": {
                    "output": "Test output",
                    "scores": {"exact_match": 1.0},
                    "time": 2.0,
                }
            },
            "errors": {"item_2": "Test error"},
        }

        json_file = tmp_path / "test_export.json"
        with open(json_file, "w") as f:
            json.dump(json_data, f)

        # Mock the migration function
        with patch(
            "llm_eval.storage.migration.migrate_from_evaluation_result"
        ) as mock_migrate:
            mock_migrate.return_value = "test_run_id"

            run_id = migrate_json_export(
                str(json_file),
                project_id="test_project",
                created_by="test_user",
                tags=["json", "import"],
            )

            assert run_id == "test_run_id"
            mock_migrate.assert_called_once()

            # Verify EvaluationResult was reconstructed correctly
            call_args = mock_migrate.call_args
            eval_result = call_args[0][0]
            assert eval_result.dataset_name == "test_dataset"
            assert eval_result.run_name == "JSON Export Test"
            assert eval_result.metrics == ["exact_match", "similarity"]
            assert eval_result.results == json_data["results"]
            assert eval_result.errors == json_data["errors"]

    def test_migrate_json_export_file_not_found(self):
        """Test error handling for missing file."""
        with pytest.raises(FileNotFoundError):
            migrate_json_export("nonexistent_file.json")

    def test_migrate_json_export_invalid_json(self, tmp_path):
        """Test error handling for invalid JSON."""
        invalid_json_file = tmp_path / "invalid.json"
        with open(invalid_json_file, "w") as f:
            f.write("invalid json content")

        with pytest.raises(json.JSONDecodeError):
            migrate_json_export(str(invalid_json_file))

    def test_migrate_json_export_missing_fields(self, tmp_path):
        """Test handling of JSON with missing fields."""
        minimal_json = {
            "dataset_name": "test_dataset",
            "run_name": "Minimal Test",
            "metrics": ["exact_match"],
            "start_time": "2023-01-01T12:00:00",
            "end_time": None,
            "results": {},
            "errors": {},
        }

        json_file = tmp_path / "minimal.json"
        with open(json_file, "w") as f:
            json.dump(minimal_json, f)

        with patch(
            "llm_eval.storage.migration.migrate_from_evaluation_result"
        ) as mock_migrate:
            mock_migrate.return_value = "minimal_run_id"

            run_id = migrate_json_export(str(json_file))

            assert run_id == "minimal_run_id"

            # Verify EvaluationResult handling of None end_time
            call_args = mock_migrate.call_args
            eval_result = call_args[0][0]
            assert eval_result.end_time is None


class TestMigrationEdgeCases:
    """Test edge cases and error conditions in migration."""

    def test_migration_with_empty_results(self):
        """Test migration with empty results and errors."""
        mock_result = Mock()
        mock_result.run_name = "Empty Test"
        mock_result.dataset_name = "empty_dataset"
        mock_result.metrics = ["exact_match"]
        mock_result.start_time = datetime.utcnow()
        mock_result.end_time = datetime.utcnow()
        mock_result.duration = 0.0
        mock_result.total_items = 0
        mock_result.success_rate = 0.0
        mock_result.results = {}
        mock_result.errors = {}
        mock_result.get_timing_stats.return_value = {}
        mock_result.get_metric_stats.return_value = {}

        with patch(
            "llm_eval.storage.migration.RunRepository"
        ) as mock_repo_class, patch(
            "llm_eval.storage.migration._store_evaluation_items"
        ) as mock_store_items, patch(
            "llm_eval.storage.migration._store_run_metrics"
        ) as mock_store_metrics:

            mock_repo = Mock()
            mock_run = Mock()
            mock_run.id = uuid.uuid4()
            mock_repo.create_run.return_value = mock_run
            mock_repo_class.return_value = mock_repo

            run_id = migrate_from_evaluation_result(mock_result)

            assert run_id == str(mock_run.id)
            mock_store_items.assert_called_once()
            mock_store_metrics.assert_called_once()

    def test_migration_with_malformed_results(self):
        """Test migration with malformed results data."""
        mock_result = Mock()
        mock_result.run_name = "Malformed Test"
        mock_result.dataset_name = "test"
        mock_result.metrics = ["exact_match"]
        mock_result.start_time = datetime.utcnow()
        mock_result.end_time = datetime.utcnow()
        mock_result.duration = 1.0
        mock_result.total_items = 2
        mock_result.success_rate = 0.5

        # Malformed results - missing expected keys
        mock_result.results = {
            "item_1": {"incomplete": "data"},  # Missing scores, output, etc.
            "item_2": None,  # Completely invalid
        }
        mock_result.errors = {}
        mock_result.get_timing_stats.return_value = {}
        mock_result.get_metric_stats.return_value = {}

        with patch("llm_eval.storage.migration.RunRepository") as mock_repo_class:
            mock_repo = Mock()
            mock_run = Mock()
            mock_run.id = uuid.uuid4()
            mock_repo.create_run.return_value = mock_run
            mock_repo_class.return_value = mock_repo

            # Should not crash, but handle gracefully
            with patch("llm_eval.storage.migration._store_evaluation_items"), patch(
                "llm_eval.storage.migration._store_run_metrics"
            ):

                run_id = migrate_from_evaluation_result(mock_result)
                assert run_id == str(mock_run.id)

    def test_score_distribution_edge_cases(self):
        """Test score distribution computation edge cases."""
        mock_result = Mock()

        # Test with mixed data types
        mock_result.results = {
            "item_1": {"scores": {"mixed_metric": 0.5}},
            "item_2": {"scores": {"mixed_metric": True}},
            "item_3": {"scores": {"mixed_metric": "invalid"}},  # Should be ignored
            "item_4": {"scores": {}},  # Missing metric
        }

        distribution = _compute_score_distribution(mock_result, "mixed_metric")

        # Should only count valid numeric/boolean values
        assert distribution["total_scores"] == 2
        assert len(distribution["buckets"]) > 0
        assert len(distribution["counts"]) > 0

    def test_percentiles_edge_cases(self):
        """Test percentile computation edge cases."""
        # Test with very small dataset
        mock_result = Mock()
        mock_result.results = {"item_1": {"scores": {"single_metric": 0.5}}}

        percentiles = _compute_percentiles(mock_result, "single_metric")

        # All percentiles should be the same for single value
        unique_values = set(percentiles.values())
        assert len(unique_values) == 1
        assert list(unique_values)[0] == 0.5
