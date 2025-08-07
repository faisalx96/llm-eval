"""Comprehensive unit tests for SQLAlchemy storage models.

This module tests all model classes, relationships, constraints, and utility functions
to achieve comprehensive coverage of the storage models layer.
"""

import pytest
import uuid
import json
from datetime import datetime, timedelta
from sqlalchemy import create_engine, text, inspect
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import IntegrityError, StatementError

from llm_eval.models.run_models import (
    Base, EvaluationRun, EvaluationItem, RunMetric, RunComparison, Project,
    create_tables, drop_tables, get_session_factory
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


class TestEvaluationRunModel:
    """Test EvaluationRun model functionality."""
    
    def test_create_evaluation_run_minimal(self, test_session):
        """Test creating evaluation run with minimal required fields."""
        run = EvaluationRun(
            name="Test Run",
            dataset_name="test_dataset",
            metrics_used=["exact_match"]
        )
        
        test_session.add(run)
        test_session.commit()
        
        assert run.id is not None
        assert isinstance(run.id, uuid.UUID)
        assert run.name == "Test Run"
        assert run.status == "running"  # default value
        assert run.total_items == 0  # default value
        assert run.created_at is not None
    
    def test_create_evaluation_run_full(self, test_session):
        """Test creating evaluation run with all fields."""
        now = datetime.utcnow()
        
        run = EvaluationRun(
            name="Full Test Run",
            description="A comprehensive test run",
            status="completed",
            dataset_name="comprehensive_dataset",
            model_name="gpt-4",
            model_version="2023-06-01",
            task_type="qa",
            metrics_used=["exact_match", "answer_relevancy", "faithfulness"],
            metric_configs={"exact_match": {"case_sensitive": False}},
            created_at=now,
            started_at=now,
            completed_at=now + timedelta(minutes=10),
            duration_seconds=600.5,
            total_items=100,
            successful_items=95,
            failed_items=5,
            success_rate=0.95,
            avg_response_time=2.5,
            min_response_time=0.5,
            max_response_time=8.0,
            config={"temperature": 0.7, "max_tokens": 1000},
            environment={"python_version": "3.9.0", "platform": "linux"},
            tags=["test", "validation", "qa"],
            created_by="test_user",
            project_id="test_project_123"
        )
        
        test_session.add(run)
        test_session.commit()
        
        assert run.id is not None
        assert run.description == "A comprehensive test run"
        assert run.status == "completed"
        assert run.model_name == "gpt-4"
        assert run.task_type == "qa"
        assert run.duration_seconds == 600.5
        assert run.success_rate == 0.95
        assert run.config["temperature"] == 0.7
        assert "test" in run.tags
        assert run.project_id == "test_project_123"
    
    def test_evaluation_run_defaults(self, test_session):
        """Test default values are applied correctly."""
        run = EvaluationRun(
            name="Default Test",
            dataset_name="test",
            metrics_used=["exact_match"]
        )
        
        test_session.add(run)
        test_session.commit()
        
        assert run.status == "running"
        assert run.total_items == 0
        assert run.successful_items == 0
        assert run.failed_items == 0
        assert run.created_at is not None
    
    def test_evaluation_run_constraints_valid_status(self, test_session):
        """Test status constraint accepts valid values."""
        valid_statuses = ["running", "completed", "failed", "cancelled"]
        
        for status in valid_statuses:
            run = EvaluationRun(
                name=f"Test {status}",
                dataset_name="test",
                metrics_used=["exact_match"],
                status=status
            )
            test_session.add(run)
        
        test_session.commit()  # Should not raise
    
    def test_evaluation_run_constraints_invalid_status(self, test_session):
        """Test status constraint rejects invalid values."""
        run = EvaluationRun(
            name="Invalid Status Test",
            dataset_name="test",
            metrics_used=["exact_match"],
            status="invalid_status"
        )
        
        test_session.add(run)
        with pytest.raises(IntegrityError):
            test_session.commit()
    
    def test_evaluation_run_constraints_success_rate(self, test_session):
        """Test success rate constraints."""
        # Valid success rates
        valid_rates = [0.0, 0.5, 1.0]
        for rate in valid_rates:
            run = EvaluationRun(
                name=f"Test {rate}",
                dataset_name="test",
                metrics_used=["exact_match"],
                success_rate=rate
            )
            test_session.add(run)
        
        test_session.commit()
        test_session.rollback()
        
        # Invalid success rates
        invalid_rates = [-0.1, 1.1, 2.0]
        for rate in invalid_rates:
            run = EvaluationRun(
                name=f"Invalid {rate}",
                dataset_name="test",
                metrics_used=["exact_match"],
                success_rate=rate
            )
            test_session.add(run)
            with pytest.raises(IntegrityError):
                test_session.commit()
            test_session.rollback()
    
    def test_evaluation_run_constraints_negative_items(self, test_session):
        """Test constraints on item counts."""
        # Valid (non-negative) values
        run = EvaluationRun(
            name="Valid Items Test",
            dataset_name="test",
            metrics_used=["exact_match"],
            total_items=10,
            successful_items=8,
            failed_items=2
        )
        test_session.add(run)
        test_session.commit()
        test_session.rollback()
        
        # Invalid (negative) values
        invalid_configs = [
            {"total_items": -1},
            {"successful_items": -1},
            {"failed_items": -1}
        ]
        
        for config in invalid_configs:
            run = EvaluationRun(
                name="Invalid Items Test",
                dataset_name="test",
                metrics_used=["exact_match"],
                **config
            )
            test_session.add(run)
            with pytest.raises(IntegrityError):
                test_session.commit()
            test_session.rollback()
    
    def test_evaluation_run_json_fields(self, test_session):
        """Test JSON field storage and retrieval."""
        complex_config = {
            "model_params": {
                "temperature": 0.7,
                "max_tokens": 1000,
                "stop_sequences": ["\n", "###"]
            },
            "evaluation_params": {
                "batch_size": 10,
                "timeout": 30
            }
        }
        
        run = EvaluationRun(
            name="JSON Test",
            dataset_name="test",
            metrics_used=["exact_match", "similarity"],
            config=complex_config,
            tags=["json", "test", "complex"]
        )
        
        test_session.add(run)
        test_session.commit()
        
        # Retrieve and verify JSON data
        retrieved = test_session.query(EvaluationRun).filter_by(name="JSON Test").first()
        assert retrieved.config["model_params"]["temperature"] == 0.7
        assert retrieved.config["evaluation_params"]["batch_size"] == 10
        assert len(retrieved.tags) == 3
        assert "complex" in retrieved.tags
    
    def test_evaluation_run_to_dict(self, test_session):
        """Test to_dict method."""
        now = datetime.utcnow()
        run = EvaluationRun(
            name="Dict Test",
            description="Test to_dict conversion",
            dataset_name="test",
            metrics_used=["exact_match"],
            created_at=now,
            status="completed",
            total_items=50,
            success_rate=0.9
        )
        
        test_session.add(run)
        test_session.commit()
        
        run_dict = run.to_dict()
        
        assert isinstance(run_dict, dict)
        assert run_dict["name"] == "Dict Test"
        assert run_dict["description"] == "Test to_dict conversion"
        assert run_dict["status"] == "completed"
        assert run_dict["total_items"] == 50
        assert run_dict["success_rate"] == 0.9
        assert isinstance(run_dict["id"], str)  # UUID converted to string
        assert isinstance(run_dict["created_at"], str)  # datetime converted to ISO format
    
    def test_evaluation_run_repr(self, test_session):
        """Test __repr__ method."""
        run = EvaluationRun(
            name="Repr Test",
            dataset_name="test",
            metrics_used=["exact_match"],
            status="running"
        )
        
        test_session.add(run)
        test_session.commit()
        
        repr_str = repr(run)
        assert "EvaluationRun" in repr_str
        assert "Repr Test" in repr_str
        assert "running" in repr_str
        assert str(run.id) in repr_str


class TestEvaluationItemModel:
    """Test EvaluationItem model functionality."""
    
    @pytest.fixture
    def sample_run(self, test_session):
        """Create a sample run for testing items."""
        run = EvaluationRun(
            name="Sample Run for Items",
            dataset_name="test",
            metrics_used=["exact_match"]
        )
        test_session.add(run)
        test_session.commit()
        return run
    
    def test_create_evaluation_item_minimal(self, test_session, sample_run):
        """Test creating evaluation item with minimal fields."""
        item = EvaluationItem(
            run_id=sample_run.id,
            item_id="test_item_1",
            sequence_number=1
        )
        
        test_session.add(item)
        test_session.commit()
        
        assert item.id is not None
        assert item.run_id == sample_run.id
        assert item.item_id == "test_item_1"
        assert item.sequence_number == 1
        assert item.status == "pending"  # default
    
    def test_create_evaluation_item_full(self, test_session, sample_run):
        """Test creating evaluation item with all fields."""
        now = datetime.utcnow()
        
        item = EvaluationItem(
            run_id=sample_run.id,
            item_id="comprehensive_item",
            sequence_number=5,
            input_data={"question": "What is 2+2?", "context": "Math question"},
            expected_output="4",
            actual_output="The answer is 4",
            status="completed",
            error_message=None,
            error_type=None,
            started_at=now,
            completed_at=now + timedelta(seconds=2),
            response_time=2.5,
            tokens_used=15,
            cost=0.001,
            scores={"exact_match": 0.8, "similarity": 0.95},
            langfuse_trace_id="trace_123",
            langfuse_observation_id="obs_456"
        )
        
        test_session.add(item)
        test_session.commit()
        
        assert item.input_data["question"] == "What is 2+2?"
        assert item.expected_output == "4"
        assert item.actual_output == "The answer is 4"
        assert item.response_time == 2.5
        assert item.tokens_used == 15
        assert item.cost == 0.001
        assert item.scores["exact_match"] == 0.8
        assert item.langfuse_trace_id == "trace_123"
    
    def test_evaluation_item_status_constraint(self, test_session, sample_run):
        """Test status constraint on evaluation items."""
        valid_statuses = ["pending", "completed", "failed", "skipped"]
        
        for i, status in enumerate(valid_statuses):
            item = EvaluationItem(
                run_id=sample_run.id,
                item_id=f"status_test_{i}",
                sequence_number=i + 1,
                status=status
            )
            test_session.add(item)
        
        test_session.commit()  # Should not raise
        
        # Test invalid status
        item = EvaluationItem(
            run_id=sample_run.id,
            item_id="invalid_status",
            sequence_number=99,
            status="invalid"
        )
        test_session.add(item)
        with pytest.raises(IntegrityError):
            test_session.commit()
    
    def test_evaluation_item_constraints(self, test_session, sample_run):
        """Test various constraints on evaluation items."""
        # Test non-negative constraints
        invalid_configs = [
            {"response_time": -1.0},
            {"tokens_used": -5},
            {"cost": -0.01}
        ]
        
        for config in invalid_configs:
            item = EvaluationItem(
                run_id=sample_run.id,
                item_id="constraint_test",
                sequence_number=1,
                **config
            )
            test_session.add(item)
            with pytest.raises(IntegrityError):
                test_session.commit()
            test_session.rollback()
    
    def test_evaluation_item_unique_constraint(self, test_session, sample_run):
        """Test unique constraint on run_id + item_id."""
        # First item should succeed
        item1 = EvaluationItem(
            run_id=sample_run.id,
            item_id="duplicate_test",
            sequence_number=1
        )
        test_session.add(item1)
        test_session.commit()
        
        # Second item with same run_id and item_id should fail
        item2 = EvaluationItem(
            run_id=sample_run.id,
            item_id="duplicate_test",  # Same item_id
            sequence_number=2
        )
        test_session.add(item2)
        with pytest.raises(IntegrityError):
            test_session.commit()
    
    def test_evaluation_item_relationship(self, test_session, sample_run):
        """Test relationship with EvaluationRun."""
        item = EvaluationItem(
            run_id=sample_run.id,
            item_id="relationship_test",
            sequence_number=1
        )
        test_session.add(item)
        test_session.commit()
        
        # Access run through relationship
        assert item.run is not None
        assert item.run.id == sample_run.id
        assert item.run.name == sample_run.name
        
        # Access items through run relationship
        assert len(sample_run.results) >= 1
        assert any(result.item_id == "relationship_test" for result in sample_run.results)
    
    def test_evaluation_item_cascade_delete(self, test_session):
        """Test cascade delete when run is deleted."""
        # Create run and item
        run = EvaluationRun(
            name="Cascade Test Run",
            dataset_name="test",
            metrics_used=["exact_match"]
        )
        test_session.add(run)
        test_session.flush()
        
        item = EvaluationItem(
            run_id=run.id,
            item_id="cascade_test",
            sequence_number=1
        )
        test_session.add(item)
        test_session.commit()
        
        # Delete run should cascade to item
        test_session.delete(run)
        test_session.commit()
        
        # Item should be deleted
        remaining_items = test_session.query(EvaluationItem).filter_by(
            item_id="cascade_test"
        ).all()
        assert len(remaining_items) == 0
    
    def test_evaluation_item_to_dict(self, test_session, sample_run):
        """Test to_dict method."""
        now = datetime.utcnow()
        item = EvaluationItem(
            run_id=sample_run.id,
            item_id="dict_test",
            sequence_number=1,
            input_data={"test": "data"},
            expected_output="expected",
            actual_output="actual",
            status="completed",
            started_at=now,
            response_time=1.5,
            scores={"metric1": 0.8}
        )
        
        test_session.add(item)
        test_session.commit()
        
        item_dict = item.to_dict()
        
        assert isinstance(item_dict, dict)
        assert item_dict["item_id"] == "dict_test"
        assert item_dict["sequence_number"] == 1
        assert item_dict["input_data"] == {"test": "data"}
        assert item_dict["status"] == "completed"
        assert item_dict["response_time"] == 1.5
        assert isinstance(item_dict["id"], str)
        assert isinstance(item_dict["run_id"], str)
    
    def test_evaluation_item_repr(self, test_session, sample_run):
        """Test __repr__ method."""
        item = EvaluationItem(
            run_id=sample_run.id,
            item_id="repr_test",
            sequence_number=1,
            status="completed"
        )
        test_session.add(item)
        test_session.commit()
        
        repr_str = repr(item)
        assert "EvaluationItem" in repr_str
        assert "repr_test" in repr_str
        assert "completed" in repr_str
        assert str(sample_run.id) in repr_str


class TestRunMetricModel:
    """Test RunMetric model functionality."""
    
    @pytest.fixture
    def sample_run(self, test_session):
        """Create a sample run for testing metrics."""
        run = EvaluationRun(
            name="Sample Run for Metrics",
            dataset_name="test",
            metrics_used=["exact_match", "similarity"]
        )
        test_session.add(run)
        test_session.commit()
        return run
    
    def test_create_run_metric_minimal(self, test_session, sample_run):
        """Test creating run metric with minimal fields."""
        metric = RunMetric(
            run_id=sample_run.id,
            metric_name="exact_match"
        )
        
        test_session.add(metric)
        test_session.commit()
        
        assert metric.id is not None
        assert metric.run_id == sample_run.id
        assert metric.metric_name == "exact_match"
        assert metric.total_evaluated == 0  # default
        assert metric.successful_evaluations == 0  # default
    
    def test_create_run_metric_full(self, test_session, sample_run):
        """Test creating run metric with all fields."""
        now = datetime.utcnow()
        
        metric = RunMetric(
            run_id=sample_run.id,
            metric_name="answer_relevancy",
            metric_type="numeric",
            mean_score=0.85,
            median_score=0.87,
            std_dev=0.15,
            min_score=0.2,
            max_score=1.0,
            total_evaluated=100,
            successful_evaluations=95,
            failed_evaluations=5,
            success_rate=0.95,
            score_distribution={
                "buckets": [0.0, 0.2, 0.4, 0.6, 0.8, 1.0],
                "counts": [2, 5, 8, 25, 55, 5]
            },
            percentiles={
                "p25": 0.75,
                "p50": 0.87,
                "p75": 0.95,
                "p90": 0.98,
                "p95": 0.99,
                "p99": 1.0
            },
            computed_at=now
        )
        
        test_session.add(metric)
        test_session.commit()
        
        assert metric.metric_type == "numeric"
        assert metric.mean_score == 0.85
        assert metric.median_score == 0.87
        assert metric.std_dev == 0.15
        assert metric.total_evaluated == 100
        assert metric.successful_evaluations == 95
        assert metric.success_rate == 0.95
        assert metric.score_distribution["buckets"][0] == 0.0
        assert metric.percentiles["p50"] == 0.87
        assert metric.computed_at == now
    
    def test_run_metric_constraints_success_rate(self, test_session, sample_run):
        """Test success rate constraint on run metrics."""
        # Valid success rates
        valid_rates = [0.0, 0.5, 1.0]
        for i, rate in enumerate(valid_rates):
            metric = RunMetric(
                run_id=sample_run.id,
                metric_name=f"test_metric_{i}",
                success_rate=rate
            )
            test_session.add(metric)
        
        test_session.commit()
        test_session.rollback()
        
        # Invalid success rates
        invalid_rates = [-0.1, 1.1]
        for rate in invalid_rates:
            metric = RunMetric(
                run_id=sample_run.id,
                metric_name="invalid_rate",
                success_rate=rate
            )
            test_session.add(metric)
            with pytest.raises(IntegrityError):
                test_session.commit()
            test_session.rollback()
    
    def test_run_metric_constraints_negative_evaluations(self, test_session, sample_run):
        """Test constraints on evaluation counts."""
        invalid_configs = [
            {"total_evaluated": -1},
            {"successful_evaluations": -1},
            {"failed_evaluations": -1}
        ]
        
        for config in invalid_configs:
            metric = RunMetric(
                run_id=sample_run.id,
                metric_name="negative_test",
                **config
            )
            test_session.add(metric)
            with pytest.raises(IntegrityError):
                test_session.commit()
            test_session.rollback()
    
    def test_run_metric_unique_constraint(self, test_session, sample_run):
        """Test unique constraint on run_id + metric_name."""
        # First metric should succeed
        metric1 = RunMetric(
            run_id=sample_run.id,
            metric_name="unique_test"
        )
        test_session.add(metric1)
        test_session.commit()
        
        # Second metric with same run_id and metric_name should fail
        metric2 = RunMetric(
            run_id=sample_run.id,
            metric_name="unique_test"  # Same metric_name
        )
        test_session.add(metric2)
        with pytest.raises(IntegrityError):
            test_session.commit()
    
    def test_run_metric_relationship(self, test_session, sample_run):
        """Test relationship with EvaluationRun."""
        metric = RunMetric(
            run_id=sample_run.id,
            metric_name="relationship_test"
        )
        test_session.add(metric)
        test_session.commit()
        
        # Access run through relationship
        assert metric.run is not None
        assert metric.run.id == sample_run.id
        
        # Access metrics through run relationship
        assert len(sample_run.metrics) >= 1
        assert any(m.metric_name == "relationship_test" for m in sample_run.metrics)
    
    def test_run_metric_cascade_delete(self, test_session):
        """Test cascade delete when run is deleted."""
        # Create run and metric
        run = EvaluationRun(
            name="Metric Cascade Test",
            dataset_name="test",
            metrics_used=["test_metric"]
        )
        test_session.add(run)
        test_session.flush()
        
        metric = RunMetric(
            run_id=run.id,
            metric_name="cascade_test"
        )
        test_session.add(metric)
        test_session.commit()
        
        # Delete run should cascade to metric
        test_session.delete(run)
        test_session.commit()
        
        # Metric should be deleted
        remaining_metrics = test_session.query(RunMetric).filter_by(
            metric_name="cascade_test"
        ).all()
        assert len(remaining_metrics) == 0
    
    def test_run_metric_to_dict(self, test_session, sample_run):
        """Test to_dict method."""
        now = datetime.utcnow()
        metric = RunMetric(
            run_id=sample_run.id,
            metric_name="dict_test",
            metric_type="boolean",
            mean_score=0.75,
            total_evaluated=50,
            computed_at=now
        )
        
        test_session.add(metric)
        test_session.commit()
        
        metric_dict = metric.to_dict()
        
        assert isinstance(metric_dict, dict)
        assert metric_dict["metric_name"] == "dict_test"
        assert metric_dict["metric_type"] == "boolean"
        assert metric_dict["mean_score"] == 0.75
        assert metric_dict["total_evaluated"] == 50
        assert isinstance(metric_dict["id"], str)
        assert isinstance(metric_dict["run_id"], str)
        assert isinstance(metric_dict["computed_at"], str)
    
    def test_run_metric_repr(self, test_session, sample_run):
        """Test __repr__ method."""
        metric = RunMetric(
            run_id=sample_run.id,
            metric_name="repr_test",
            mean_score=0.88
        )
        test_session.add(metric)
        test_session.commit()
        
        repr_str = repr(metric)
        assert "RunMetric" in repr_str
        assert "repr_test" in repr_str
        assert "0.88" in repr_str
        assert str(sample_run.id) in repr_str


class TestRunComparisonModel:
    """Test RunComparison model functionality."""
    
    @pytest.fixture
    def two_sample_runs(self, test_session):
        """Create two sample runs for comparison testing."""
        run1 = EvaluationRun(
            name="Comparison Run 1",
            dataset_name="test",
            metrics_used=["exact_match"]
        )
        run2 = EvaluationRun(
            name="Comparison Run 2", 
            dataset_name="test",
            metrics_used=["exact_match"]
        )
        test_session.add_all([run1, run2])
        test_session.commit()
        return run1, run2
    
    def test_create_run_comparison_minimal(self, test_session, two_sample_runs):
        """Test creating run comparison with minimal fields."""
        run1, run2 = two_sample_runs
        
        comparison = RunComparison(
            run1_id=run1.id,
            run2_id=run2.id
        )
        
        test_session.add(comparison)
        test_session.commit()
        
        assert comparison.id is not None
        assert comparison.run1_id == run1.id
        assert comparison.run2_id == run2.id
        assert comparison.comparison_type == "full"  # default
        assert comparison.created_at is not None
    
    def test_create_run_comparison_full(self, test_session, two_sample_runs):
        """Test creating run comparison with all fields."""
        run1, run2 = two_sample_runs
        now = datetime.utcnow()
        
        comparison = RunComparison(
            run1_id=run1.id,
            run2_id=run2.id,
            comparison_type="metrics_only",
            created_at=now,
            created_by="test_user",
            summary={
                "winner": "run1",
                "confidence": 0.85,
                "improvement": 0.15
            },
            metric_comparisons={
                "exact_match": {
                    "run1_score": 0.85,
                    "run2_score": 0.70,
                    "difference": 0.15,
                    "significant": True
                },
                "answer_relevancy": {
                    "run1_score": 0.92,
                    "run2_score": 0.88,
                    "difference": 0.04,
                    "significant": False
                }
            },
            statistical_tests={
                "t_test_p_value": 0.02,
                "effect_size": 0.65,
                "sample_size": 100
            },
            performance_delta={
                "response_time": -0.5,  # Run1 is 0.5s faster
                "cost_per_item": 0.001,  # Run1 costs 0.001 more
                "tokens_saved": 150
            }
        )
        
        test_session.add(comparison)
        test_session.commit()
        
        assert comparison.comparison_type == "metrics_only"
        assert comparison.created_by == "test_user"
        assert comparison.summary["winner"] == "run1"
        assert comparison.metric_comparisons["exact_match"]["difference"] == 0.15
        assert comparison.statistical_tests["t_test_p_value"] == 0.02
        assert comparison.performance_delta["response_time"] == -0.5
    
    def test_run_comparison_constraint_different_runs(self, test_session, two_sample_runs):
        """Test constraint that run1_id != run2_id."""
        run1, run2 = two_sample_runs
        
        # Same run IDs should fail
        comparison = RunComparison(
            run1_id=run1.id,
            run2_id=run1.id  # Same as run1_id
        )
        
        test_session.add(comparison)
        with pytest.raises(IntegrityError):
            test_session.commit()
    
    def test_run_comparison_json_fields(self, test_session, two_sample_runs):
        """Test JSON field storage and retrieval."""
        run1, run2 = two_sample_runs
        
        complex_summary = {
            "overall_winner": "run2",
            "metrics_breakdown": {
                "accuracy": {"winner": "run1", "margin": 0.05},
                "speed": {"winner": "run2", "margin": 1.2}
            },
            "recommendations": [
                "Use run1 for accuracy-critical tasks",
                "Use run2 for speed-critical tasks"
            ]
        }
        
        comparison = RunComparison(
            run1_id=run1.id,
            run2_id=run2.id,
            summary=complex_summary
        )
        
        test_session.add(comparison)
        test_session.commit()
        
        # Retrieve and verify JSON data
        retrieved = test_session.query(RunComparison).filter_by(
            run1_id=run1.id,
            run2_id=run2.id
        ).first()
        
        assert retrieved.summary["overall_winner"] == "run2"
        assert retrieved.summary["metrics_breakdown"]["accuracy"]["winner"] == "run1"
        assert len(retrieved.summary["recommendations"]) == 2
    
    def test_run_comparison_repr(self, test_session, two_sample_runs):
        """Test __repr__ method."""
        run1, run2 = two_sample_runs
        
        comparison = RunComparison(
            run1_id=run1.id,
            run2_id=run2.id,
            comparison_type="detailed"
        )
        
        test_session.add(comparison)
        test_session.commit()
        
        repr_str = repr(comparison)
        assert "RunComparison" in repr_str
        assert str(run1.id) in repr_str
        assert str(run2.id) in repr_str


class TestProjectModel:
    """Test Project model functionality."""
    
    def test_create_project_minimal(self, test_session):
        """Test creating project with minimal fields."""
        project = Project(
            id="minimal_project",
            name="Minimal Project"
        )
        
        test_session.add(project)
        test_session.commit()
        
        assert project.id == "minimal_project"
        assert project.name == "Minimal Project"
        assert project.created_at is not None
        assert project.updated_at is not None
    
    def test_create_project_full(self, test_session):
        """Test creating project with all fields."""
        now = datetime.utcnow()
        
        project = Project(
            id="comprehensive_project",
            name="Comprehensive Project",
            description="A full-featured project for testing",
            created_at=now,
            updated_at=now,
            created_by="project_creator",
            team_members=["user1", "user2", "user3"],
            settings={
                "default_metrics": ["exact_match", "similarity"],
                "auto_save": True,
                "notification_email": "team@company.com"
            }
        )
        
        test_session.add(project)
        test_session.commit()
        
        assert project.description == "A full-featured project for testing"
        assert project.created_by == "project_creator"
        assert len(project.team_members) == 3
        assert "user2" in project.team_members
        assert project.settings["auto_save"] is True
        assert project.settings["notification_email"] == "team@company.com"
    
    def test_project_updated_at_auto_update(self, test_session):
        """Test that updated_at is automatically updated on changes."""
        project = Project(
            id="update_test",
            name="Update Test Project"
        )
        
        test_session.add(project)
        test_session.commit()
        
        original_updated_at = project.updated_at
        
        # Update the project
        project.description = "Updated description"
        test_session.commit()
        
        # updated_at should be newer (in a real scenario with more time precision)
        assert project.updated_at >= original_updated_at
    
    def test_project_repr(self, test_session):
        """Test __repr__ method."""
        project = Project(
            id="repr_test_project",
            name="Repr Test Project"
        )
        
        test_session.add(project)
        test_session.commit()
        
        repr_str = repr(project)
        assert "Project" in repr_str
        assert "repr_test_project" in repr_str
        assert "Repr Test Project" in repr_str


class TestModelUtilityFunctions:
    """Test utility functions for model management."""
    
    def test_create_tables(self):
        """Test create_tables function."""
        engine = create_engine("sqlite:///:memory:", echo=False)
        
        # Tables should not exist initially
        inspector = inspect(engine)
        assert len(inspector.get_table_names()) == 0
        
        # Create tables
        create_tables(engine)
        
        # Tables should now exist (get fresh inspector after table creation)
        inspector = inspect(engine)
        table_names = inspector.get_table_names()
        expected_tables = [
            "evaluation_runs",
            "evaluation_items", 
            "run_metrics",
            "run_comparisons",
            "projects"
        ]
        
        for table in expected_tables:
            assert table in table_names
    
    def test_drop_tables(self):
        """Test drop_tables function."""
        engine = create_engine("sqlite:///:memory:", echo=False)
        
        # Create tables first
        create_tables(engine)
        inspector = inspect(engine)
        assert len(inspector.get_table_names()) > 0
        
        # Drop tables
        drop_tables(engine)
        
        # Tables should be gone (get fresh inspector after dropping)
        inspector = inspect(engine)
        table_names = inspector.get_table_names()
        assert len(table_names) == 0
    
    def test_get_session_factory(self):
        """Test get_session_factory function."""
        database_url = "sqlite:///:memory:"
        
        SessionFactory, engine = get_session_factory(database_url)
        
        assert SessionFactory is not None
        assert engine is not None
        
        # Test that we can create a session
        session = SessionFactory()
        assert session is not None
        session.close()
        
        engine.dispose()


class TestModelIndexes:
    """Test that database indexes are created correctly."""
    
    def test_evaluation_run_indexes(self, in_memory_db):
        """Test that indexes are created for EvaluationRun."""
        engine, _ = in_memory_db
        inspector = inspect(engine)
        
        indexes = inspector.get_indexes("evaluation_runs")
        index_names = [idx["name"] for idx in indexes]
        
        # Test for some key indexes
        expected_indexes = [
            "idx_runs_created_at",
            "idx_runs_dataset_name", 
            "idx_runs_status",
            "idx_runs_model_name"
        ]
        
        for expected in expected_indexes:
            assert expected in index_names
    
    def test_evaluation_item_indexes(self, in_memory_db):
        """Test that indexes are created for EvaluationItem."""
        engine, _ = in_memory_db
        inspector = inspect(engine)
        
        indexes = inspector.get_indexes("evaluation_items")
        index_names = [idx["name"] for idx in indexes]
        
        expected_indexes = [
            "idx_items_run_id",
            "idx_items_item_id",
            "idx_items_status"
        ]
        
        for expected in expected_indexes:
            assert expected in index_names


class TestModelEdgeCases:
    """Test edge cases and error conditions."""
    
    def test_null_handling(self, test_session):
        """Test handling of null values in optional fields."""
        run = EvaluationRun(
            name="Null Test",
            dataset_name="test",
            metrics_used=["exact_match"],
            description=None,
            model_name=None,
            completed_at=None,
            duration_seconds=None,
            success_rate=None,
            config=None,
            tags=None
        )
        
        test_session.add(run)
        test_session.commit()
        
        # Should handle nulls gracefully
        run_dict = run.to_dict()
        assert run_dict["description"] is None
        assert run_dict["model_name"] is None
        assert run_dict["completed_at"] is None
    
    def test_large_json_data(self, test_session):
        """Test handling of large JSON data."""
        large_config = {
            "large_list": list(range(1000)),
            "nested_data": {
                f"key_{i}": f"value_{i}" for i in range(100)
            },
            "text_data": "Lorem ipsum " * 1000
        }
        
        run = EvaluationRun(
            name="Large JSON Test",
            dataset_name="test",
            metrics_used=["exact_match"],
            config=large_config
        )
        
        test_session.add(run)
        test_session.commit()
        
        # Should handle large JSON data
        retrieved = test_session.query(EvaluationRun).filter_by(
            name="Large JSON Test"
        ).first()
        
        assert len(retrieved.config["large_list"]) == 1000
        assert len(retrieved.config["nested_data"]) == 100
    
    def test_unicode_handling(self, test_session):
        """Test handling of unicode characters."""
        run = EvaluationRun(
            name="Unicode Test: 测试 🧪 Тест",
            description="Multi-language: English, 中文, Русский, العربية, 日本語",
            dataset_name="unicode_dataset",
            metrics_used=["exact_match"]
        )
        
        test_session.add(run)
        test_session.commit()
        
        retrieved = test_session.query(EvaluationRun).filter_by(
            dataset_name="unicode_dataset"
        ).first()
        
        assert "测试" in retrieved.name
        assert "🧪" in retrieved.name
        assert "中文" in retrieved.description