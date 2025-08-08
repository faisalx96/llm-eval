"""Pydantic models for API request/response validation.

This module defines the data models used for API serialization,
validation, and documentation. These models ensure type safety
and provide clear API contracts for the frontend.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional, Union
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, validator

# Base response models


class APIResponse(BaseModel):
    """Base API response model."""

    success: bool = True
    message: Optional[str] = None


class PaginatedResponse(BaseModel):
    """Base paginated response model."""

    items: List[Any]
    total: int
    page: int = Field(ge=1)
    per_page: int = Field(ge=1, le=100)
    total_pages: int


# Evaluation Run Models


class RunSummary(BaseModel):
    """Summary view of an evaluation run for list endpoints."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    description: Optional[str] = None
    status: str
    dataset_name: str
    model_name: Optional[str] = None
    task_type: Optional[str] = None
    created_at: datetime
    completed_at: Optional[datetime] = None
    duration_seconds: Optional[float] = None
    total_items: int = 0
    successful_items: int = 0
    success_rate: Optional[float] = None
    tags: Optional[List[str]] = None


class RunDetail(BaseModel):
    """Detailed view of an evaluation run."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    description: Optional[str] = None
    status: str
    dataset_name: str
    model_name: Optional[str] = None
    model_version: Optional[str] = None
    task_type: Optional[str] = None
    metrics_used: List[str]
    metric_configs: Optional[Dict[str, Any]] = None
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    duration_seconds: Optional[float] = None
    total_items: int = 0
    successful_items: int = 0
    failed_items: int = 0
    success_rate: Optional[float] = None
    avg_response_time: Optional[float] = None
    min_response_time: Optional[float] = None
    max_response_time: Optional[float] = None
    config: Optional[Dict[str, Any]] = None
    environment: Optional[Dict[str, Any]] = None
    tags: Optional[List[str]] = None
    created_by: Optional[str] = None
    project_id: Optional[str] = None


class CreateRunRequest(BaseModel):
    """Request model for creating a new evaluation run."""

    name: str = Field(min_length=1, max_length=255)
    description: Optional[str] = None
    dataset_name: str = Field(min_length=1, max_length=255)
    model_name: Optional[str] = Field(None, max_length=255)
    model_version: Optional[str] = Field(None, max_length=100)
    task_type: Optional[str] = Field(None, max_length=50)
    metrics_used: List[str] = Field(min_items=1)
    metric_configs: Optional[Dict[str, Any]] = None
    config: Optional[Dict[str, Any]] = None
    environment: Optional[Dict[str, Any]] = None
    tags: Optional[List[str]] = None
    created_by: Optional[str] = Field(None, max_length=255)
    project_id: Optional[str] = Field(None, max_length=255)
    status: Optional[str] = Field(
        "running", pattern="^(running|completed|failed|cancelled)$"
    )


class UpdateRunRequest(BaseModel):
    """Request model for updating an evaluation run."""

    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    status: Optional[str] = Field(
        None, pattern="^(running|completed|failed|cancelled)$"
    )
    model_version: Optional[str] = Field(None, max_length=100)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    duration_seconds: Optional[float] = Field(None, ge=0)
    total_items: Optional[int] = Field(None, ge=0)
    successful_items: Optional[int] = Field(None, ge=0)
    failed_items: Optional[int] = Field(None, ge=0)
    success_rate: Optional[float] = Field(None, ge=0, le=1)
    avg_response_time: Optional[float] = Field(None, ge=0)
    min_response_time: Optional[float] = Field(None, ge=0)
    max_response_time: Optional[float] = Field(None, ge=0)
    config: Optional[Dict[str, Any]] = None
    environment: Optional[Dict[str, Any]] = None
    tags: Optional[List[str]] = None


# Run Metrics Models


class RunMetricSummary(BaseModel):
    """Summary of run metrics."""

    model_config = ConfigDict(from_attributes=True)

    metric_name: str
    metric_type: Optional[str] = None
    mean_score: Optional[float] = None
    median_score: Optional[float] = None
    std_dev: Optional[float] = None
    min_score: Optional[float] = None
    max_score: Optional[float] = None
    success_rate: Optional[float] = None
    total_evaluated: int = 0


class RunMetricDetail(RunMetricSummary):
    """Detailed run metrics with distribution data."""

    successful_evaluations: int = 0
    failed_evaluations: int = 0
    score_distribution: Optional[Dict[str, Any]] = None
    percentiles: Optional[Dict[str, float]] = None
    computed_at: datetime


# Query and Filter Models


class RunFilters(BaseModel):
    """Query filters for listing runs."""

    project_id: Optional[str] = None
    dataset_name: Optional[str] = None
    model_name: Optional[str] = None
    status: Optional[str] = Field(
        None, pattern="^(running|completed|failed|cancelled)$"
    )
    created_by: Optional[str] = None
    tags: Optional[List[str]] = None
    min_success_rate: Optional[float] = Field(None, ge=0, le=1)
    max_duration: Optional[float] = Field(None, gt=0)
    created_after: Optional[datetime] = None
    created_before: Optional[datetime] = None
    search: Optional[str] = Field(None, min_length=1)


class RunSorting(BaseModel):
    """Sorting options for run queries."""

    order_by: str = Field(
        default="created_at",
        pattern="^(created_at|name|status|success_rate|duration_seconds)$",
    )
    descending: bool = True


class PaginationParams(BaseModel):
    """Pagination parameters."""

    page: int = Field(default=1, ge=1)
    per_page: int = Field(default=20, ge=1, le=100)

    @property
    def offset(self) -> int:
        """Calculate offset for database queries."""
        return (self.page - 1) * self.per_page


# Comparison Models


class CompareRunsRequest(BaseModel):
    """Request model for comparing evaluation runs."""

    run_ids: List[str] = Field(min_items=2, max_items=10)
    metrics: Optional[List[str]] = None  # If None, compare all common metrics
    comparison_type: str = Field(
        default="full", pattern="^(full|metrics_only|summary)$"
    )

    @validator("run_ids")
    def validate_unique_run_ids(cls, v):
        if len(v) != len(set(v)):
            raise ValueError("Run IDs must be unique")
        return v


class MetricComparison(BaseModel):
    """Comparison data for a specific metric across runs."""

    metric_name: str
    runs: Dict[str, Dict[str, Any]]  # run_id -> metric data
    statistical_tests: Optional[Dict[str, Any]] = None
    summary: Optional[str] = None


class RunComparison(BaseModel):
    """Complete comparison between multiple runs."""

    run_ids: List[str]
    comparison_type: str
    created_at: datetime
    metric_comparisons: List[MetricComparison]
    summary: Dict[str, Any]
    performance_differences: Optional[Dict[str, Any]] = None


# Response Models


class CreateRunResponse(APIResponse):
    """Response for run creation."""

    run: RunDetail


class GetRunResponse(APIResponse):
    """Response for single run retrieval."""

    run: RunDetail
    metrics: List[RunMetricDetail]


class ListRunsResponse(PaginatedResponse):
    """Response for run listing."""

    items: List[RunSummary]


class CompareRunsResponse(APIResponse):
    """Response for run comparison."""

    comparison: RunComparison


class RunMetricsResponse(APIResponse):
    """Response for run metrics."""

    metrics: List[RunMetricDetail]


# Health Check Models


class DatabaseHealth(BaseModel):
    """Database health check response."""

    status: str
    connection_test: bool
    statistics: Dict[str, Any]


class HealthCheckResponse(BaseModel):
    """Complete health check response."""

    status: str
    timestamp: datetime
    database: DatabaseHealth
    version: str


# Error Models


class ErrorDetail(BaseModel):
    """Detailed error information."""

    error: str
    message: str
    type: str
    details: Optional[Dict[str, Any]] = None


class ValidationErrorDetail(BaseModel):
    """Validation error details."""

    loc: List[Union[str, int]]
    msg: str
    type: str
