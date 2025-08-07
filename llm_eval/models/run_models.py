"""Database models for evaluation run storage.

This module defines the SQLAlchemy models for storing evaluation runs,
results, and metadata to support the UI-first evaluation platform.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import json

from sqlalchemy import (
    Column, Integer, String, DateTime, Float, Boolean, Text, JSON,
    ForeignKey, Index, UniqueConstraint, CheckConstraint
)
from sqlalchemy.orm import declarative_base
from sqlalchemy.orm import relationship, sessionmaker
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
import uuid


Base = declarative_base()


class EvaluationRun(Base):
    """Main evaluation run metadata table.
    
    Stores high-level information about each evaluation run including
    dataset, model information, metrics used, and timing data.
    """
    __tablename__ = 'evaluation_runs'
    
    # Primary key
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    
    # Basic run information
    name = Column(String(255), nullable=False, doc="User-friendly run name")
    description = Column(Text, nullable=True, doc="Optional run description")
    status = Column(
        String(20), 
        nullable=False, 
        default="running",
        doc="Run status: running, completed, failed, cancelled"
    )
    
    # Dataset and model information
    dataset_name = Column(String(255), nullable=False, doc="Name of Langfuse dataset")
    model_name = Column(String(255), nullable=True, doc="LLM model used")
    model_version = Column(String(100), nullable=True, doc="Model version/config")
    task_type = Column(String(50), nullable=True, doc="Type of task (qa, classification, etc.)")
    
    # Metrics configuration
    metrics_used = Column(JSON, nullable=False, doc="List of metric names used")
    metric_configs = Column(JSON, nullable=True, doc="Metric-specific configurations")
    
    # Timing information
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    started_at = Column(DateTime, nullable=True, doc="When evaluation actually started")
    completed_at = Column(DateTime, nullable=True, doc="When evaluation finished")
    duration_seconds = Column(Float, nullable=True, doc="Total evaluation duration")
    
    # Aggregate statistics
    total_items = Column(Integer, nullable=False, default=0)
    successful_items = Column(Integer, nullable=False, default=0)
    failed_items = Column(Integer, nullable=False, default=0)
    success_rate = Column(Float, nullable=True, doc="Percentage of successful evaluations")
    
    # Performance metrics
    avg_response_time = Column(Float, nullable=True, doc="Average response time in seconds")
    min_response_time = Column(Float, nullable=True)
    max_response_time = Column(Float, nullable=True)
    
    # Configuration and metadata
    config = Column(JSON, nullable=True, doc="Full evaluation configuration")
    environment = Column(JSON, nullable=True, doc="Runtime environment info")
    tags = Column(JSON, nullable=True, doc="User-defined tags for organization")
    
    # User information
    created_by = Column(String(255), nullable=True, doc="User who created the run")
    project_id = Column(String(255), nullable=True, doc="Project/workspace identifier")
    
    # Relationships
    results = relationship("EvaluationItem", back_populates="run", cascade="all, delete-orphan")
    metrics = relationship("RunMetric", back_populates="run", cascade="all, delete-orphan")
    
    # Constraints
    __table_args__ = (
        CheckConstraint('status IN ("running", "completed", "failed", "cancelled")', name='valid_status'),
        CheckConstraint('success_rate >= 0.0 AND success_rate <= 1.0', name='valid_success_rate'),
        CheckConstraint('total_items >= 0', name='non_negative_total_items'),
        CheckConstraint('successful_items >= 0', name='non_negative_successful_items'),
        CheckConstraint('failed_items >= 0', name='non_negative_failed_items'),
        # Indexes for common queries
        Index('idx_runs_created_at', 'created_at'),
        Index('idx_runs_dataset_name', 'dataset_name'),
        Index('idx_runs_status', 'status'),
        Index('idx_runs_model_name', 'model_name'),
        Index('idx_runs_task_type', 'task_type'),
        Index('idx_runs_created_by', 'created_by'),
        Index('idx_runs_project_id', 'project_id'),
        Index('idx_runs_tags', 'tags'),  # GIN index for JSON queries
        Index('idx_runs_success_rate', 'success_rate'),
        Index('idx_runs_duration', 'duration_seconds'),
        # Composite indexes for common filtering patterns
        Index('idx_runs_dataset_status', 'dataset_name', 'status'),
        Index('idx_runs_model_created', 'model_name', 'created_at'),
        Index('idx_runs_project_created', 'project_id', 'created_at'),
    )
    
    def __repr__(self):
        return f"<EvaluationRun(id={self.id}, name='{self.name}', status='{self.status}')>"
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert run to dictionary format."""
        return {
            'id': str(self.id),
            'name': self.name,
            'description': self.description,
            'status': self.status,
            'dataset_name': self.dataset_name,
            'model_name': self.model_name,
            'model_version': self.model_version,
            'task_type': self.task_type,
            'metrics_used': self.metrics_used,
            'metric_configs': self.metric_configs,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'started_at': self.started_at.isoformat() if self.started_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
            'duration_seconds': self.duration_seconds,
            'total_items': self.total_items,
            'successful_items': self.successful_items,
            'failed_items': self.failed_items,
            'success_rate': self.success_rate,
            'avg_response_time': self.avg_response_time,
            'min_response_time': self.min_response_time,
            'max_response_time': self.max_response_time,
            'config': self.config,
            'environment': self.environment,
            'tags': self.tags,
            'created_by': self.created_by,
            'project_id': self.project_id
        }


class EvaluationItem(Base):
    """Individual evaluation item results.
    
    Stores detailed results for each item in the evaluation dataset.
    """
    __tablename__ = 'evaluation_items'
    
    # Primary key
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    
    # Foreign key to evaluation run
    run_id = Column(UUID(as_uuid=True), ForeignKey('evaluation_runs.id'), nullable=False)
    
    # Item identification
    item_id = Column(String(255), nullable=False, doc="Original dataset item ID")
    sequence_number = Column(Integer, nullable=False, doc="Order of evaluation")
    
    # Input and output
    input_data = Column(JSON, nullable=True, doc="Input data for this item")
    expected_output = Column(Text, nullable=True, doc="Expected/ground truth output")
    actual_output = Column(Text, nullable=True, doc="Model's actual output")
    
    # Execution details
    status = Column(
        String(20), 
        nullable=False, 
        default="pending",
        doc="Item status: pending, completed, failed, skipped"
    )
    error_message = Column(Text, nullable=True, doc="Error message if failed")
    error_type = Column(String(100), nullable=True, doc="Type/category of error")
    
    # Timing
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    response_time = Column(Float, nullable=True, doc="Response time in seconds")
    
    # Model interaction metadata
    tokens_used = Column(Integer, nullable=True, doc="Total tokens consumed")
    cost = Column(Float, nullable=True, doc="Cost for this evaluation")
    
    # Raw scores storage (denormalized for performance)
    scores = Column(JSON, nullable=True, doc="All metric scores for this item")
    
    # Langfuse integration
    langfuse_trace_id = Column(String(255), nullable=True, doc="Langfuse trace ID")
    langfuse_observation_id = Column(String(255), nullable=True, doc="Langfuse observation ID")
    
    # Relationships
    run = relationship("EvaluationRun", back_populates="results")
    
    # Constraints
    __table_args__ = (
        UniqueConstraint('run_id', 'item_id', name='unique_run_item'),
        CheckConstraint('status IN ("pending", "completed", "failed", "skipped")', name='valid_item_status'),
        CheckConstraint('response_time >= 0', name='non_negative_response_time'),
        CheckConstraint('tokens_used >= 0', name='non_negative_tokens'),
        CheckConstraint('cost >= 0', name='non_negative_cost'),
        # Indexes for performance
        Index('idx_items_run_id', 'run_id'),
        Index('idx_items_item_id', 'item_id'),
        Index('idx_items_status', 'status'),
        Index('idx_items_response_time', 'response_time'),
        Index('idx_items_sequence', 'run_id', 'sequence_number'),
        Index('idx_items_langfuse_trace', 'langfuse_trace_id'),
        # Composite indexes
        Index('idx_items_run_status', 'run_id', 'status'),
        Index('idx_items_run_sequence', 'run_id', 'sequence_number'),
    )
    
    def __repr__(self):
        return f"<EvaluationItem(id={self.id}, run_id={self.run_id}, item_id='{self.item_id}', status='{self.status}')>"
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert item to dictionary format."""
        return {
            'id': str(self.id),
            'run_id': str(self.run_id),
            'item_id': self.item_id,
            'sequence_number': self.sequence_number,
            'input_data': self.input_data,
            'expected_output': self.expected_output,
            'actual_output': self.actual_output,
            'status': self.status,
            'error_message': self.error_message,
            'error_type': self.error_type,
            'started_at': self.started_at.isoformat() if self.started_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
            'response_time': self.response_time,
            'tokens_used': self.tokens_used,
            'cost': self.cost,
            'scores': self.scores,
            'langfuse_trace_id': self.langfuse_trace_id,
            'langfuse_observation_id': self.langfuse_observation_id
        }


class RunMetric(Base):
    """Aggregate metric statistics for each run.
    
    Stores computed statistics for each metric used in a run.
    This enables fast metric-based queries without recomputing.
    """
    __tablename__ = 'run_metrics'
    
    # Primary key
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    
    # Foreign key to evaluation run
    run_id = Column(UUID(as_uuid=True), ForeignKey('evaluation_runs.id'), nullable=False)
    
    # Metric identification
    metric_name = Column(String(100), nullable=False)
    metric_type = Column(String(50), nullable=True, doc="Type of metric (numeric, boolean, custom)")
    
    # Aggregate statistics
    mean_score = Column(Float, nullable=True)
    median_score = Column(Float, nullable=True)
    std_dev = Column(Float, nullable=True)
    min_score = Column(Float, nullable=True)
    max_score = Column(Float, nullable=True)
    
    # Success metrics
    total_evaluated = Column(Integer, nullable=False, default=0)
    successful_evaluations = Column(Integer, nullable=False, default=0)
    failed_evaluations = Column(Integer, nullable=False, default=0)
    success_rate = Column(Float, nullable=True)
    
    # Distribution data (for histograms/charts)
    score_distribution = Column(JSON, nullable=True, doc="Score buckets for distribution charts")
    percentiles = Column(JSON, nullable=True, doc="Common percentiles (25th, 75th, 95th, etc.)")
    
    # Metadata
    computed_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    
    # Relationships
    run = relationship("EvaluationRun", back_populates="metrics")
    
    # Constraints
    __table_args__ = (
        UniqueConstraint('run_id', 'metric_name', name='unique_run_metric'),
        CheckConstraint('success_rate >= 0.0 AND success_rate <= 1.0', name='valid_metric_success_rate'),
        CheckConstraint('total_evaluated >= 0', name='non_negative_total_evaluated'),
        CheckConstraint('successful_evaluations >= 0', name='non_negative_successful_evaluations'),
        CheckConstraint('failed_evaluations >= 0', name='non_negative_failed_evaluations'),
        # Indexes for metric-based queries
        Index('idx_metrics_run_id', 'run_id'),
        Index('idx_metrics_name', 'metric_name'),
        Index('idx_metrics_type', 'metric_type'),
        Index('idx_metrics_mean_score', 'mean_score'),
        Index('idx_metrics_success_rate', 'success_rate'),
        # Composite indexes for filtering
        Index('idx_metrics_name_mean', 'metric_name', 'mean_score'),
        Index('idx_metrics_run_name', 'run_id', 'metric_name'),
    )
    
    def __repr__(self):
        return f"<RunMetric(run_id={self.run_id}, metric='{self.metric_name}', mean={self.mean_score})>"
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert metric to dictionary format."""
        return {
            'id': str(self.id),
            'run_id': str(self.run_id),
            'metric_name': self.metric_name,
            'metric_type': self.metric_type,
            'mean_score': self.mean_score,
            'median_score': self.median_score,
            'std_dev': self.std_dev,
            'min_score': self.min_score,
            'max_score': self.max_score,
            'total_evaluated': self.total_evaluated,
            'successful_evaluations': self.successful_evaluations,
            'failed_evaluations': self.failed_evaluations,
            'success_rate': self.success_rate,
            'score_distribution': self.score_distribution,
            'percentiles': self.percentiles,
            'computed_at': self.computed_at.isoformat() if self.computed_at else None
        }


class RunComparison(Base):
    """Stored comparisons between evaluation runs.
    
    Enables fast retrieval of previously computed run comparisons
    without recomputing metrics every time.
    """
    __tablename__ = 'run_comparisons'
    
    # Primary key
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    
    # Runs being compared
    run1_id = Column(UUID(as_uuid=True), ForeignKey('evaluation_runs.id'), nullable=False)
    run2_id = Column(UUID(as_uuid=True), ForeignKey('evaluation_runs.id'), nullable=False)
    
    # Comparison metadata
    comparison_type = Column(String(50), nullable=False, default="full", doc="Type of comparison performed")
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    created_by = Column(String(255), nullable=True)
    
    # Comparison results
    summary = Column(JSON, nullable=True, doc="High-level comparison summary")
    metric_comparisons = Column(JSON, nullable=True, doc="Detailed metric-by-metric comparisons")
    statistical_tests = Column(JSON, nullable=True, doc="Statistical significance tests")
    
    # Performance differences
    performance_delta = Column(JSON, nullable=True, doc="Performance differences between runs")
    
    # Constraints
    __table_args__ = (
        CheckConstraint('run1_id != run2_id', name='different_runs'),
        # Indexes for fast comparison retrieval
        Index('idx_comparisons_runs', 'run1_id', 'run2_id'),
        Index('idx_comparisons_created', 'created_at'),
        Index('idx_comparisons_type', 'comparison_type'),
    )
    
    def __repr__(self):
        return f"<RunComparison(id={self.id}, run1={self.run1_id}, run2={self.run2_id})>"


class Project(Base):
    """Project/workspace organization for runs.
    
    Optional table for organizing runs into projects or workspaces.
    """
    __tablename__ = 'projects'
    
    # Primary key
    id = Column(String(255), primary_key=True)  # User-defined project ID
    
    # Project metadata
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    
    # Access control
    created_by = Column(String(255), nullable=True)
    team_members = Column(JSON, nullable=True, doc="List of team member IDs with access")
    
    # Project settings
    settings = Column(JSON, nullable=True, doc="Project-specific settings and preferences")
    
    # Constraints
    __table_args__ = (
        Index('idx_projects_created_by', 'created_by'),
        Index('idx_projects_updated', 'updated_at'),
    )
    
    def __repr__(self):
        return f"<Project(id='{self.id}', name='{self.name}')>"


# Utility functions for database operations

def create_tables(engine):
    """Create all tables in the database."""
    Base.metadata.create_all(engine)


def drop_tables(engine):
    """Drop all tables from the database."""
    Base.metadata.drop_all(engine)


def get_session_factory(database_url: str):
    """Create a session factory for database operations."""
    from sqlalchemy import create_engine
    engine = create_engine(database_url)
    return sessionmaker(bind=engine), engine