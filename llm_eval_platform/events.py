from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Literal, Optional, Union
from uuid import UUID

from pydantic import BaseModel, Field


RunEventType = Literal[
    "run_started",
    "item_started",
    "metric_scored",
    "item_completed",
    "item_failed",
    "run_completed",
]


class RunStartedPayload(BaseModel):
    external_run_id: Optional[str] = None
    task: str
    dataset: str
    model: Optional[str] = None
    metrics: list[str] = Field(default_factory=list)
    run_metadata: Dict[str, Any] = Field(default_factory=dict)
    run_config: Dict[str, Any] = Field(default_factory=dict)
    started_at: datetime


class ItemStartedPayload(BaseModel):
    item_id: str
    index: int = Field(ge=0)
    input: Any
    expected: Any = None
    item_metadata: Dict[str, Any] = Field(default_factory=dict)


class MetricScoredPayload(BaseModel):
    item_id: str
    metric_name: str
    score_numeric: Optional[float] = None
    score_raw: Any = None
    meta: Dict[str, Any] = Field(default_factory=dict)


class ItemCompletedPayload(BaseModel):
    item_id: str
    output: Any
    latency_ms: float = Field(ge=0)
    trace_id: Optional[str] = None
    trace_url: Optional[str] = None


class ItemFailedPayload(BaseModel):
    item_id: str
    error: str
    trace_id: Optional[str] = None
    trace_url: Optional[str] = None


class RunCompletedPayload(BaseModel):
    ended_at: datetime
    summary: Dict[str, Any] = Field(default_factory=dict)
    final_status: Literal["COMPLETED", "FAILED"] = "COMPLETED"


RunEventPayload = Union[
    RunStartedPayload,
    ItemStartedPayload,
    MetricScoredPayload,
    ItemCompletedPayload,
    ItemFailedPayload,
    RunCompletedPayload,
]


class RunEventV1(BaseModel):
    schema_version: Literal[1] = 1
    event_id: UUID
    sequence: int = Field(ge=1)
    sent_at: datetime
    type: RunEventType
    run_id: UUID
    payload: RunEventPayload


