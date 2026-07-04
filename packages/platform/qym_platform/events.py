from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Literal, Optional, Union
from uuid import UUID

from pydantic import BaseModel, Field


RunEventType = Literal[
    "run_started",
    "item_started",
    "item_attempt_started",
    "item_attempt_finished",
    "metric_scored",
    "item_completed",
    "item_failed",
    "pass_completed",
    "run_completed",
    "run_heartbeat",
    "metadata_update",
    "span_completed",
]


class RunStartedPayload(BaseModel):
    external_run_id: Optional[str] = None
    task: str
    dataset: str
    model: Optional[str] = None
    metrics: list[str] = Field(default_factory=list)
    dataset_id: Optional[str] = None
    dataset_version_id: Optional[str] = None
    dataset_alias: Optional[str] = None
    # Optional hint to enable progress % in list views.
    total_items: Optional[int] = Field(default=None, ge=0)
    run_metadata: Dict[str, Any] = Field(default_factory=dict)
    run_config: Dict[str, Any] = Field(default_factory=dict)
    started_at: datetime


class ItemStartedPayload(BaseModel):
    item_id: str
    index: int = Field(ge=0)
    # Repeat runs (samples=k): 1-based pass index; old SDKs omit it (=1).
    pass_number: int = Field(default=1, ge=1)
    input: Any
    expected: Any = None
    item_metadata: Dict[str, Any] = Field(default_factory=dict)
    dataset_item_pk: Optional[int] = None


class MetricScoredPayload(BaseModel):
    item_id: str
    pass_number: int = Field(default=1, ge=1)
    metric_name: str
    score_numeric: Optional[float] = None
    score_raw: Any = None
    meta: Dict[str, Any] = Field(default_factory=dict)
    label: Optional[str] = None
    explanation: Optional[str] = None


class ItemAttemptStartedPayload(BaseModel):
    item_id: str
    index: Optional[int] = None
    pass_number: int = Field(default=1, ge=1)
    attempt_number: int = Field(ge=1)
    trace_id: Optional[str] = None
    trace_url: Optional[str] = None
    task_started_at_ms: Optional[int] = None


class ItemAttemptFinishedPayload(BaseModel):
    item_id: str
    index: Optional[int] = None
    pass_number: int = Field(default=1, ge=1)
    attempt_number: int = Field(ge=1)
    status: Literal["completed", "failed"]
    trace_id: Optional[str] = None
    trace_url: Optional[str] = None
    latency_ms: Optional[float] = Field(default=None, ge=0)
    task_started_at_ms: Optional[int] = None
    error: Optional[str] = None
    is_last_attempt: bool = False


class ItemCompletedPayload(BaseModel):
    item_id: str
    index: Optional[int] = None  # Item index for fallback when item_started was missed
    pass_number: int = Field(default=1, ge=1)
    is_final_pass: bool = True
    output: Any
    item_metadata: Dict[str, Any] = Field(default_factory=dict)
    task_metadata: Dict[str, Any] = Field(default_factory=dict)
    latency_ms: float = Field(ge=0)
    trace_id: Optional[str] = None
    trace_url: Optional[str] = None
    task_started_at_ms: Optional[int] = None  # Epoch ms when the task execution began
    retry_count: int = 0  # Number of retries before success (0 = first attempt)


class ItemFailedPayload(BaseModel):
    item_id: str
    index: Optional[int] = None  # Item index for fallback when item_started was missed
    pass_number: int = Field(default=1, ge=1)
    error: str
    latency_ms: Optional[float] = Field(default=None, ge=0)
    trace_id: Optional[str] = None
    trace_url: Optional[str] = None
    task_started_at_ms: Optional[int] = None
    retry_count: int = 0


class PassCompletedPayload(BaseModel):
    """Repeat runs: a pass barrier finished; its slice metrics are final."""

    pass_number: int = Field(ge=1)
    samples: int = Field(ge=1)
    metrics: Dict[str, Any] = Field(default_factory=dict)


class RunCompletedPayload(BaseModel):
    ended_at: datetime
    summary: Dict[str, Any] = Field(default_factory=dict)
    final_status: Literal["COMPLETED", "FAILED", "STOPPED"] = "COMPLETED"


class RunHeartbeatPayload(BaseModel):
    heartbeat_at: datetime


class MetadataUpdatePayload(BaseModel):
    """Update run metadata mid-flight (e.g., langfuse_url once available)."""
    langfuse_url: Optional[str] = None
    langfuse_dataset_id: Optional[str] = None
    langfuse_run_id: Optional[str] = None
    # Generic key-value pairs to merge into run_metadata
    extra: Dict[str, Any] = Field(default_factory=dict)


class SpanCompletedPayload(BaseModel):
    """OTEL span data for local DB storage."""
    trace_id: str
    span_id: str
    parent_span_id: Optional[str] = None
    name: str
    kind: str = "INTERNAL"
    start_time_ns: Optional[int] = None
    end_time_ns: Optional[int] = None
    duration_ms: Optional[float] = None
    status: str = "UNSET"
    attributes: Dict[str, Any] = Field(default_factory=dict)
    events: list[Dict[str, Any]] = Field(default_factory=list)
    links: list[Dict[str, Any]] = Field(default_factory=list)


RunEventPayload = Union[
    RunStartedPayload,
    ItemStartedPayload,
    ItemAttemptStartedPayload,
    ItemAttemptFinishedPayload,
    MetricScoredPayload,
    ItemCompletedPayload,
    ItemFailedPayload,
    PassCompletedPayload,
    RunCompletedPayload,
    RunHeartbeatPayload,
    MetadataUpdatePayload,
    SpanCompletedPayload,
]


class RunEventV1(BaseModel):
    schema_version: Literal[1] = 1
    event_id: UUID
    sequence: int = Field(ge=1)
    sent_at: datetime
    type: RunEventType
    run_id: UUID
    payload: RunEventPayload
