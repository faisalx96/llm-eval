from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class UserRef(BaseModel):
    id: str
    email: str
    display_name: str


class VersionInfo(BaseModel):
    branch: Optional[str] = None
    commit: Optional[str] = None


class RunSummary(BaseModel):
    id: str
    name: str
    task: str
    dataset: str
    model: Optional[str] = None
    status: str
    created_at: Optional[str] = None
    started_at: Optional[str] = None
    ended_at: Optional[str] = None
    duration_ms: Optional[float] = None
    owner: Optional[UserRef] = None
    total_items: int = 0
    completed_items: int = 0
    error_items: int = 0
    progress_pct: Optional[float] = None
    metric_averages: Dict[str, float] = Field(default_factory=dict)
    version: Optional[VersionInfo] = None
    group_key: str = ""


class RunListResponse(BaseModel):
    runs: List[RunSummary]
    total: int
    limit: int
    offset: int


class ApprovalContext(BaseModel):
    status: str  # PENDING|APPROVED|REJECTED
    submitted_by: Optional[UserRef] = None
    submitted_at: Optional[str] = None
    decided_by: Optional[UserRef] = None
    decided_at: Optional[str] = None
    comment: str = ""


class MetricDistributionBucket(BaseModel):
    label: str
    count: int


class MetricStats(BaseModel):
    name: str
    avg: float = 0.0
    pass_count: int = 0
    fail_count: int = 0
    distribution: List[MetricDistributionBucket] = Field(default_factory=list)


class ErrorSummary(BaseModel):
    task_errors: int = 0
    types: Dict[str, int] = Field(default_factory=dict)


class RunDetail(RunSummary):
    run_config: Dict[str, Any] = Field(default_factory=dict)
    run_metadata: Dict[str, Any] = Field(default_factory=dict)
    metrics: List[str] = Field(default_factory=list)
    metric_stats: List[MetricStats] = Field(default_factory=list)
    trace_stats: Optional[Dict[str, Any]] = None
    approval: Optional[ApprovalContext] = None
    error_summary: ErrorSummary = Field(default_factory=ErrorSummary)


class RunItemSlim(BaseModel):
    item_id: str
    index: int
    status: str  # completed|failed
    input_preview: str = ""
    output_preview: str = ""
    expected_preview: str = ""
    latency_ms: Optional[float] = None
    retry_count: int = 0
    metric_values: Dict[str, Any] = Field(default_factory=dict)
    has_trace: bool = False
    root_cause: Optional[str] = None
    root_cause_source: Optional[str] = None
    review_correction_status: Optional[str] = None


class RunItemsResponse(BaseModel):
    items: List[RunItemSlim]
    total: int
    limit: int
    offset: int


class ItemTraceSummary(BaseModel):
    has_trace: bool = False
    trace_id: str = ""
    trace_url: str = ""


class RunItemDetail(BaseModel):
    item_id: str
    index: int
    status: str  # completed|failed
    input: Any = None
    output: Any = None
    expected: Any = None
    error: Optional[str] = None
    latency_ms: Optional[float] = None
    retry_count: int = 0
    item_metadata: Dict[str, Any] = Field(default_factory=dict)
    metric_values: Dict[str, Any] = Field(default_factory=dict)
    metric_meta: Dict[str, Any] = Field(default_factory=dict)
    trace: ItemTraceSummary = Field(default_factory=ItemTraceSummary)
    review_correction_status: Optional[str] = None


class RunRenameRequest(BaseModel):
    display_name: str = Field(min_length=1, max_length=200)


class RunRenameResponse(BaseModel):
    id: str
    name: str


class ProjectOverviewStats(BaseModel):
    project_id: str
    total_runs: int = 0
    by_status: Dict[str, int] = Field(default_factory=dict)
    models: List[str] = Field(default_factory=list)
    total_items: int = 0
    metric_averages: Dict[str, float] = Field(default_factory=dict)
    last_run_at: Optional[str] = None


class TrendPoint(BaseModel):
    run_id: str
    date: Optional[str] = None
    value: float = 0.0
    n_items: int = 0


class TrendSeries(BaseModel):
    group: str
    metric: str
    points: List[TrendPoint] = Field(default_factory=list)


class TrendsResponse(BaseModel):
    task: str
    dataset: Optional[str] = None
    group_by: str
    window_days: int
    series: List[TrendSeries] = Field(default_factory=list)


class ReviewQueueEntry(BaseModel):
    run: RunSummary
    baseline_run_id: Optional[str] = None
    baseline_delta: Dict[str, float] = Field(default_factory=dict)


class ReviewQueueResponse(BaseModel):
    entries: List[ReviewQueueEntry]
    total: int
