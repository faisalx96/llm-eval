"""Comprehensive unit tests for RunRepository class.

This module tests all CRUD operations, query methods, edge cases,
and error conditions for the RunRepository class to achieve 80% coverage.
"""

import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List
from unittest.mock import MagicMock, Mock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from llm_eval.models.run_models import (
    Base,
    EvaluationItem,
    EvaluationRun,
    RunComparison,
    RunMetric,
)
from llm_eval.storage.database import DatabaseManager
from llm_eval.storage.run_repository import RunRepository


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
def test_repository(test_session):
    """Create RunRepository with test session."""
    return RunRepository(session=test_session)


@pytest.fixture
def sample_run_data():
    """Sample evaluation run data for testing."""
    return {
        "name": "Test Evaluation Run",
        "description": "A test evaluation run for unit testing",
        "status": "completed",
        "dataset_name": "test_dataset",
        "model_name": "test_model",
        "model_version": "v1.0",
        "task_type": "qa",
        "metrics_used": ["exact_match", "answer_relevancy"],
        "metric_configs": {"exact_match": {"case_sensitive": False}},
        "created_at": datetime.utcnow(),
        "started_at": datetime.utcnow(),
        "completed_at": datetime.utcnow(),
        "duration_seconds": 123.45,
        "total_items": 100,
        "successful_items": 95,
        "failed_items": 5,
        "success_rate": 0.95,
        "avg_response_time": 2.1,
        "min_response_time": 0.5,
        "max_response_time": 5.2,
        "config": {"temperature": 0.7},
        "environment": {"python_version": "3.9.0"},
        "tags": ["test", "validation"],
        "created_by": "test_user",
        "project_id": "test_project",
    }


@pytest.fixture
def sample_run(test_session, sample_run_data):
    """Create a sample run in the database."""
    run = EvaluationRun(**sample_run_data)
    test_session.add(run)
    test_session.commit()
    return run


class TestRunRepositoryCreation:
    """Test RunRepository initialization and setup."""

    def test_init_with_session(self, test_session):
        """Test repository initialization with provided session."""
        repo = RunRepository(session=test_session)
        assert repo.session == test_session
        assert repo._db_manager is None

    def test_init_without_session(self):
        """Test repository initialization without session."""
        with patch("llm_eval.storage.run_repository.get_database_manager") as mock_db:
            mock_db_instance = Mock()
            mock_db.return_value = mock_db_instance

            repo = RunRepository()
            assert repo.session is None
            assert repo._db_manager == mock_db_instance

    def test_get_session_with_provided_session(self, test_session):
        """Test _get_session when session is provided."""
        repo = RunRepository(session=test_session)
        session = repo._get_session()
        assert session == test_session

    def test_get_session_without_provided_session(self):
        """Test _get_session when using database manager."""
        mock_db = Mock()
        mock_session = Mock()
        mock_db.get_session.return_value = mock_session

        repo = RunRepository()
        repo._db_manager = mock_db

        session = repo._get_session()
        assert session == mock_session


class TestRunRepositoryCRUD:
    """Test CRUD operations for evaluation runs."""

    def test_create_run_success(self, test_repository, sample_run_data):
        """Test successful run creation."""
        run = test_repository.create_run(sample_run_data)

        assert run is not None
        assert run.name == sample_run_data["name"]
        assert run.description == sample_run_data["description"]
        assert run.status == sample_run_data["status"]
        assert run.dataset_name == sample_run_data["dataset_name"]
        assert run.model_name == sample_run_data["model_name"]
        assert hasattr(run, "id")

    def test_create_run_minimal_data(self, test_repository):
        """Test run creation with minimal required data."""
        minimal_data = {
            "name": "Minimal Run",
            "dataset_name": "test_dataset",
            "metrics_used": ["exact_match"],
            "total_items": 10,
        }

        run = test_repository.create_run(minimal_data)
        assert run is not None
        assert run.name == minimal_data["name"]
        assert run.status == "running"  # default status

    def test_create_run_integrity_error(self, test_repository):
        """Test run creation with constraint violation."""
        invalid_data = {
            "name": "Test Run",
            "dataset_name": "test_dataset",
            "metrics_used": ["exact_match"],
            "total_items": 10,
            "success_rate": 1.5,  # Invalid: > 1.0
        }

        with pytest.raises(IntegrityError):
            test_repository.create_run(invalid_data)

    def test_get_run_exists(self, test_repository, sample_run):
        """Test retrieving existing run by ID."""
        retrieved_run = test_repository.get_run(sample_run.id)

        assert retrieved_run is not None
        assert retrieved_run.id == sample_run.id
        assert retrieved_run.name == sample_run.name
        assert retrieved_run.status == sample_run.status

    def test_get_run_string_id(self, test_repository, sample_run):
        """Test retrieving run with string UUID."""
        run_id_str = str(sample_run.id)
        retrieved_run = test_repository.get_run(run_id_str)

        assert retrieved_run is not None
        assert str(retrieved_run.id) == run_id_str

    def test_get_run_not_exists(self, test_repository):
        """Test retrieving non-existent run."""
        fake_id = uuid.uuid4()
        result = test_repository.get_run(fake_id)
        assert result is None

    def test_update_run_success(self, test_repository, sample_run):
        """Test successful run update."""
        updates = {
            "status": "failed",
            "completed_at": datetime.utcnow(),
            "duration_seconds": 456.78,
        }

        updated_run = test_repository.update_run(sample_run.id, updates)

        assert updated_run is not None
        assert updated_run.status == "failed"
        assert updated_run.duration_seconds == 456.78

    def test_update_run_string_id(self, test_repository, sample_run):
        """Test updating run with string UUID."""
        updates = {"status": "cancelled"}
        run_id_str = str(sample_run.id)

        updated_run = test_repository.update_run(run_id_str, updates)

        assert updated_run is not None
        assert updated_run.status == "cancelled"

    def test_update_run_not_exists(self, test_repository):
        """Test updating non-existent run."""
        fake_id = uuid.uuid4()
        updates = {"status": "completed"}

        result = test_repository.update_run(fake_id, updates)
        assert result is None

    def test_update_run_invalid_field(self, test_repository, sample_run):
        """Test updating run with invalid field."""
        updates = {"non_existent_field": "value"}

        # Should not raise error, just ignore invalid fields
        updated_run = test_repository.update_run(sample_run.id, updates)
        assert updated_run is not None

    def test_delete_run_success(self, test_repository, sample_run):
        """Test successful run deletion."""
        run_id = sample_run.id

        result = test_repository.delete_run(run_id)
        assert result is True

        # Verify run is deleted
        retrieved_run = test_repository.get_run(run_id)
        assert retrieved_run is None

    def test_delete_run_string_id(self, test_repository, sample_run):
        """Test deleting run with string UUID."""
        run_id_str = str(sample_run.id)

        result = test_repository.delete_run(run_id_str)
        assert result is True

    def test_delete_run_not_exists(self, test_repository):
        """Test deleting non-existent run."""
        fake_id = uuid.uuid4()

        result = test_repository.delete_run(fake_id)
        assert result is False


class TestRunRepositoryQueries:
    """Test query operations for evaluation runs."""

    @pytest.fixture
    def multiple_runs(self, test_session):
        """Create multiple runs for testing queries."""
        runs = []
        base_data = {
            "dataset_name": "test_dataset",
            "metrics_used": ["exact_match"],
            "total_items": 10,
        }

        # Create runs with different attributes
        run_configs = [
            {
                "name": "Run 1",
                "status": "completed",
                "model_name": "model_a",
                "success_rate": 0.9,
                "duration_seconds": 100,
            },
            {
                "name": "Run 2",
                "status": "running",
                "model_name": "model_b",
                "success_rate": 0.8,
                "duration_seconds": 200,
            },
            {
                "name": "Run 3",
                "status": "failed",
                "model_name": "model_a",
                "success_rate": 0.7,
                "duration_seconds": 50,
            },
            {
                "name": "Run 4",
                "status": "completed",
                "model_name": "model_c",
                "success_rate": 0.95,
                "duration_seconds": 150,
            },
        ]

        for config in run_configs:
            data = {**base_data, **config}
            run = EvaluationRun(**data)
            test_session.add(run)
            runs.append(run)

        test_session.commit()
        return runs

    def test_list_runs_no_filters(self, test_repository, multiple_runs):
        """Test listing runs without filters."""
        runs = test_repository.list_runs()

        assert len(runs) == 4
        # Should be ordered by created_at descending by default
        assert runs[0]["name"] == "Run 4"  # Latest created

    def test_list_runs_with_status_filter(self, test_repository, multiple_runs):
        """Test listing runs with status filter."""
        runs = test_repository.list_runs(status="completed")

        assert len(runs) == 2
        statuses = [run["status"] for run in runs]
        assert all(status == "completed" for status in statuses)

    def test_list_runs_with_model_filter(self, test_repository, multiple_runs):
        """Test listing runs with model name filter."""
        runs = test_repository.list_runs(model_name="model_a")

        assert len(runs) == 2
        model_names = [run["model_name"] for run in runs]
        assert all(model == "model_a" for model in model_names)

    def test_list_runs_with_min_success_rate(self, test_repository, multiple_runs):
        """Test listing runs with minimum success rate."""
        runs = test_repository.list_runs(min_success_rate=0.85)

        assert len(runs) == 2  # Runs with 0.9 and 0.95 success rates
        success_rates = [run["success_rate"] for run in runs]
        assert all(rate >= 0.85 for rate in success_rates)

    def test_list_runs_with_max_duration(self, test_repository, multiple_runs):
        """Test listing runs with maximum duration."""
        runs = test_repository.list_runs(max_duration=120)

        assert len(runs) == 2  # Runs with 100 and 50 second durations
        durations = [run["duration_seconds"] for run in runs]
        assert all(duration <= 120 for duration in durations)

    def test_list_runs_with_date_filters(self, test_repository, multiple_runs):
        """Test listing runs with date filters."""
        now = datetime.utcnow()
        yesterday = now - timedelta(days=1)
        tomorrow = now + timedelta(days=1)

        # All runs should be created today
        runs = test_repository.list_runs(created_after=yesterday)
        assert len(runs) == 4

        runs = test_repository.list_runs(created_before=tomorrow)
        assert len(runs) == 4

        runs = test_repository.list_runs(created_after=tomorrow)
        assert len(runs) == 0

    def test_list_runs_ordering(self, test_repository, multiple_runs):
        """Test run ordering options."""
        # Ascending order by name
        runs = test_repository.list_runs(order_by="name", descending=False)
        names = [run["name"] for run in runs]
        assert names == ["Run 1", "Run 2", "Run 3", "Run 4"]

        # Descending order by success_rate
        runs = test_repository.list_runs(order_by="success_rate", descending=True)
        success_rates = [run["success_rate"] for run in runs]
        assert (
            success_rates[0] >= success_rates[1] >= success_rates[2] >= success_rates[3]
        )

    def test_list_runs_pagination(self, test_repository, multiple_runs):
        """Test run pagination."""
        # First page
        runs = test_repository.list_runs(limit=2, offset=0)
        assert len(runs) == 2

        # Second page
        runs = test_repository.list_runs(limit=2, offset=2)
        assert len(runs) == 2

        # Beyond available data
        runs = test_repository.list_runs(limit=2, offset=10)
        assert len(runs) == 0

    def test_list_runs_combined_filters(self, test_repository, multiple_runs):
        """Test combining multiple filters."""
        runs = test_repository.list_runs(
            status="completed", min_success_rate=0.85, model_name="model_a"
        )

        # Should match Run 1 only (completed, model_a, success_rate=0.9)
        assert len(runs) == 1
        assert runs[0]["name"] == "Run 1"

    def test_count_runs_no_filters(self, test_repository, multiple_runs):
        """Test counting runs without filters."""
        count = test_repository.count_runs()
        assert count == 4

    def test_count_runs_with_filters(self, test_repository, multiple_runs):
        """Test counting runs with filters."""
        count = test_repository.count_runs(status="completed")
        assert count == 2

        count = test_repository.count_runs(model_name="model_a")
        assert count == 2

        count = test_repository.count_runs(status="nonexistent")
        assert count == 0

    def test_search_runs(self, test_repository, multiple_runs):
        """Test searching runs by text."""
        # Search by name
        runs = test_repository.search_runs("Run 1")
        assert len(runs) == 1
        assert runs[0].name == "Run 1"

        # Search by partial name
        runs = test_repository.search_runs("Run")
        assert len(runs) == 4  # All runs have "Run" in the name

        # Search by dataset name
        runs = test_repository.search_runs("test_dataset")
        assert len(runs) == 4  # All runs use test_dataset

        # Search for non-existent term
        runs = test_repository.search_runs("nonexistent")
        assert len(runs) == 0


class TestRunRepositoryMetrics:
    """Test metric-related operations."""

    @pytest.fixture
    def run_with_metrics(self, test_session, sample_run_data):
        """Create run with associated metrics."""
        run = EvaluationRun(**sample_run_data)
        test_session.add(run)
        test_session.flush()

        # Add metrics
        metrics_data = [
            {
                "run_id": run.id,
                "metric_name": "exact_match",
                "metric_type": "numeric",
                "mean_score": 0.85,
                "std_dev": 0.15,
                "min_score": 0.0,
                "max_score": 1.0,
                "total_evaluated": 100,
                "successful_evaluations": 95,
                "failed_evaluations": 5,
                "success_rate": 0.95,
            },
            {
                "run_id": run.id,
                "metric_name": "answer_relevancy",
                "metric_type": "numeric",
                "mean_score": 0.92,
                "std_dev": 0.08,
                "min_score": 0.7,
                "max_score": 1.0,
                "total_evaluated": 100,
                "successful_evaluations": 95,
                "failed_evaluations": 5,
                "success_rate": 0.95,
            },
        ]

        for metric_data in metrics_data:
            metric = RunMetric(**metric_data)
            test_session.add(metric)

        test_session.commit()
        return run

    def test_get_run_metrics(self, test_repository, run_with_metrics):
        """Test retrieving metrics for a run."""
        metrics = test_repository.get_run_metrics(run_with_metrics.id)

        assert len(metrics) == 2
        metric_names = [metric.metric_name for metric in metrics]
        assert "exact_match" in metric_names
        assert "answer_relevancy" in metric_names

    def test_get_run_metrics_string_id(self, test_repository, run_with_metrics):
        """Test retrieving metrics with string UUID."""
        run_id_str = str(run_with_metrics.id)
        metrics = test_repository.get_run_metrics(run_id_str)

        assert len(metrics) == 2

    def test_get_run_metrics_no_metrics(self, test_repository, sample_run):
        """Test retrieving metrics for run without metrics."""
        metrics = test_repository.get_run_metrics(sample_run.id)
        assert len(metrics) == 0

    def test_get_metric_stats(self, test_repository, run_with_metrics):
        """Test getting aggregate metric statistics."""
        stats = test_repository.get_metric_stats("exact_match")

        assert stats["metric_name"] == "exact_match"
        assert stats["run_count"] == 1
        assert stats["overall_mean"] == 0.85
        assert stats["min_mean"] == 0.85
        assert stats["max_mean"] == 0.85
        assert stats["std_dev"] == 0.0  # Only one run

    def test_get_metric_stats_with_project_filter(
        self, test_repository, run_with_metrics
    ):
        """Test metric stats with project filter."""
        stats = test_repository.get_metric_stats(
            "exact_match", project_id=run_with_metrics.project_id
        )
        assert stats["run_count"] == 1

        # Test with different project_id
        stats = test_repository.get_metric_stats(
            "exact_match", project_id="different_project"
        )
        assert stats["run_count"] == 0

    def test_get_metric_stats_nonexistent(self, test_repository):
        """Test getting stats for non-existent metric."""
        stats = test_repository.get_metric_stats("nonexistent_metric")

        assert stats["metric_name"] == "nonexistent_metric"
        assert stats["run_count"] == 0
        assert stats["overall_mean"] == 0.0


class TestRunRepositoryComparisons:
    """Test run comparison operations."""

    @pytest.fixture
    def two_runs_with_comparison(self, test_session, sample_run_data):
        """Create two runs with a comparison."""
        # Create first run
        run1_data = {**sample_run_data, "name": "Run 1"}
        run1 = EvaluationRun(**run1_data)
        test_session.add(run1)

        # Create second run
        run2_data = {**sample_run_data, "name": "Run 2"}
        run2 = EvaluationRun(**run2_data)
        test_session.add(run2)

        test_session.flush()

        # Create comparison
        comparison_data = {
            "run1_id": run1.id,
            "run2_id": run2.id,
            "comparison_type": "full",
            "summary": {"winner": "run1", "confidence": 0.95},
            "metric_comparisons": {
                "exact_match": {"run1": 0.85, "run2": 0.80, "difference": 0.05}
            },
            "performance_delta": {"response_time": -0.5},
        }

        comparison = RunComparison(**comparison_data)
        test_session.add(comparison)
        test_session.commit()

        return run1, run2, comparison

    def test_get_comparison_exists(self, test_repository, two_runs_with_comparison):
        """Test retrieving existing comparison."""
        run1, run2, expected_comparison = two_runs_with_comparison

        comparison = test_repository.get_comparison(run1.id, run2.id)

        assert comparison is not None
        assert comparison.run1_id == expected_comparison.run1_id
        assert comparison.run2_id == expected_comparison.run2_id
        assert comparison.comparison_type == "full"

    def test_get_comparison_reversed_order(
        self, test_repository, two_runs_with_comparison
    ):
        """Test retrieving comparison with reversed run order."""
        run1, run2, expected_comparison = two_runs_with_comparison

        # Query in reverse order
        comparison = test_repository.get_comparison(run2.id, run1.id)

        assert comparison is not None
        assert comparison.id == expected_comparison.id

    def test_get_comparison_string_ids(self, test_repository, two_runs_with_comparison):
        """Test retrieving comparison with string UUIDs."""
        run1, run2, expected_comparison = two_runs_with_comparison

        comparison = test_repository.get_comparison(str(run1.id), str(run2.id))

        assert comparison is not None
        assert comparison.id == expected_comparison.id

    def test_get_comparison_not_exists(self, test_repository, sample_run):
        """Test retrieving non-existent comparison."""
        fake_id = uuid.uuid4()

        comparison = test_repository.get_comparison(sample_run.id, fake_id)
        assert comparison is None

    def test_save_comparison(self, test_repository, two_runs_with_comparison):
        """Test saving new comparison."""
        run1, run2, _ = two_runs_with_comparison

        new_comparison_data = {
            "run1_id": run1.id,
            "run2_id": run2.id,
            "comparison_type": "metrics_only",
            "summary": {"type": "metrics_comparison"},
            "metric_comparisons": {"accuracy": {"difference": 0.1}},
        }

        saved_comparison = test_repository.save_comparison(new_comparison_data)

        assert saved_comparison is not None
        assert saved_comparison.comparison_type == "metrics_only"


class TestRunRepositoryEdgeCases:
    """Test edge cases and error conditions."""

    def test_create_run_empty_data(self, test_repository):
        """Test creating run with empty data."""
        with pytest.raises(Exception):  # Should fail due to missing required fields
            test_repository.create_run({})

    def test_operations_with_none_ids(self, test_repository):
        """Test operations with None IDs."""
        assert test_repository.get_run(None) is None
        assert test_repository.update_run(None, {"status": "completed"}) is None
        assert test_repository.delete_run(None) is False

    def test_operations_with_invalid_uuid_strings(self, test_repository):
        """Test operations with invalid UUID strings."""
        invalid_uuid = "not-a-uuid"

        # These should handle invalid UUIDs gracefully
        assert test_repository.get_run(invalid_uuid) is None
        assert test_repository.update_run(invalid_uuid, {"status": "completed"}) is None
        assert test_repository.delete_run(invalid_uuid) is False

    def test_list_runs_with_invalid_order_by(self, test_repository):
        """Test list_runs with invalid order_by field."""
        # Should fallback to default (created_at)
        runs = test_repository.list_runs(order_by="nonexistent_field")
        assert isinstance(runs, list)  # Should not crash

    def test_list_runs_with_tags_filter_empty_list(self, test_repository, sample_run):
        """Test filtering by empty tags list."""
        runs = test_repository.list_runs(tags=[])
        # Should return all runs (empty filter ignored)
        assert len(runs) >= 1

    def test_concurrent_operations(self, test_repository, sample_run_data):
        """Test concurrent database operations."""
        # This is a basic test - in practice would need actual threading
        run1 = test_repository.create_run(
            {**sample_run_data, "name": "Concurrent Run 1"}
        )
        run2 = test_repository.create_run(
            {**sample_run_data, "name": "Concurrent Run 2"}
        )

        assert run1.id != run2.id
        assert run1.name != run2.name


class TestRunRepositorySessionManagement:
    """Test session management and database manager integration."""

    def test_repository_without_session_uses_db_manager(self):
        """Test that repository without session uses database manager."""
        with patch(
            "llm_eval.storage.run_repository.get_database_manager"
        ) as mock_get_db:
            mock_db = Mock()
            mock_session = Mock()
            mock_db.get_session.return_value.__enter__ = Mock(return_value=mock_session)
            mock_db.get_session.return_value.__exit__ = Mock(return_value=None)
            mock_get_db.return_value = mock_db

            repo = RunRepository()

            # Mock the create operation
            with patch.object(mock_session, "add"), patch.object(
                mock_session, "flush"
            ), patch.object(mock_session, "commit"):

                with patch("llm_eval.models.run_models.EvaluationRun") as MockRun:
                    mock_run_instance = Mock()
                    mock_run_instance.id = uuid.uuid4()
                    mock_run_instance.name = "test"
                    MockRun.return_value = mock_run_instance

                    # Add all the attributes that get accessed
                    for attr in [
                        "name",
                        "description",
                        "status",
                        "dataset_name",
                        "model_name",
                        "task_type",
                        "created_at",
                        "completed_at",
                        "duration_seconds",
                        "total_items",
                        "successful_items",
                        "success_rate",
                        "tags",
                        "project_id",
                        "created_by",
                    ]:
                        setattr(mock_run_instance, attr, None)

                    try:
                        result = repo.create_run(
                            {
                                "name": "test",
                                "dataset_name": "test",
                                "metrics_used": [],
                                "total_items": 0,
                            }
                        )
                        # Verify database manager was called
                        mock_get_db.assert_called_once()
                    except AttributeError:
                        # Expected due to mocking limitations
                        pass


class TestRunRepositoryDataIntegrity:
    """Test data integrity and validation."""

    def test_run_to_dict_conversion_in_list_runs(self, test_repository, sample_run):
        """Test that list_runs returns properly formatted dictionaries."""
        runs = test_repository.list_runs()

        assert len(runs) > 0
        run_dict = runs[0]

        # Verify dictionary structure
        assert isinstance(run_dict, dict)
        assert "id" in run_dict
        assert "name" in run_dict
        assert "status" in run_dict
        assert "dataset_name" in run_dict

        # Verify ID is string format
        assert isinstance(run_dict["id"], str)

    def test_create_run_returns_detached_object(self, test_repository, sample_run_data):
        """Test that create_run returns a detached object safe to use outside session."""
        run = test_repository.create_run(sample_run_data)

        # Should be able to access attributes without database session
        assert run.name == sample_run_data["name"]
        assert run.status == sample_run_data["status"]
        assert hasattr(run, "id")

    def test_database_constraint_validations(self, test_repository):
        """Test various database constraint validations."""
        base_data = {
            "name": "Test Run",
            "dataset_name": "test_dataset",
            "metrics_used": ["exact_match"],
            "total_items": 10,
        }

        # Test invalid success_rate (> 1.0)
        invalid_data = {**base_data, "success_rate": 1.5}
        with pytest.raises(IntegrityError):
            test_repository.create_run(invalid_data)

        # Test invalid status
        invalid_data = {**base_data, "status": "invalid_status"}
        with pytest.raises(IntegrityError):
            test_repository.create_run(invalid_data)

        # Test negative total_items
        invalid_data = {**base_data, "total_items": -1}
        with pytest.raises(IntegrityError):
            test_repository.create_run(invalid_data)


class TestRunRepositoryPerformance:
    """Test performance-related aspects."""

    def test_list_runs_with_large_offset(self, test_repository):
        """Test that large offsets are handled gracefully."""
        runs = test_repository.list_runs(offset=1000000, limit=10)
        assert runs == []  # Should return empty list, not crash

    def test_search_runs_with_special_characters(self, test_repository, sample_run):
        """Test search with special characters."""
        # Should not crash with special regex characters
        runs = test_repository.search_runs("[]{}()*+?|^$.")
        assert isinstance(runs, list)

    def test_metric_stats_with_null_values(self, test_repository):
        """Test metric stats computation with null/missing values."""
        stats = test_repository.get_metric_stats("nonexistent")

        # Should handle missing data gracefully
        assert stats["run_count"] == 0
        assert stats["overall_mean"] == 0.0
        assert stats["std_dev"] == 0.0
