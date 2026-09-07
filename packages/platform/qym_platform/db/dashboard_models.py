"""Durable numeric dashboard projections and their transactional outbox."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from uuid import uuid4

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base

# PostgreSQL sequences must survive high-volume lifetimes; SQLite requires the
# exact INTEGER spelling for its rowid allocator.
VERSION = BigInteger().with_variant(Integer(), "sqlite")


class NumericContribution:
    observed: Mapped[int] = mapped_column(Integer, default=0)
    terminal: Mapped[int] = mapped_column(Integer, default=0)
    success: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[int] = mapped_column(Integer, default=0)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    started_at_ms: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    is_last: Mapped[bool] = mapped_column(Boolean, default=False)


class DashboardChangeEvent(NumericContribution, Base):
    __tablename__ = "dashboard_change_events"
    # Database allocation is the source version; gaps from rolled-back writes
    # are valid. The UUID is the independent redelivery identity.
    source_version: Mapped[int] = mapped_column(
        VERSION, primary_key=True, autoincrement=True
    )
    event_id: Mapped[str] = mapped_column(
        String(36), unique=True, default=lambda: str(uuid4())
    )
    project_key: Mapped[str] = mapped_column(String(36), index=True)
    partition_key: Mapped[str] = mapped_column(String(36), index=True)
    record_key: Mapped[str] = mapped_column(String(260))
    metric_key: Mapped[str] = mapped_column(String(240), default="")
    record_kind: Mapped[str] = mapped_column(String(20))
    pass_number: Mapped[int] = mapped_column(Integer, default=0)
    operation: Mapped[str] = mapped_column(String(10), default="UPSERT")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    __table_args__ = (
        Index(
            "ix_dashboard_event_pending_partition",
            "partition_key",
            "published_at",
            "source_version",
        ),
        Index(
            "ix_dashboard_event_retention",
            "created_at",
            "published_at",
            "source_version",
        ),
        {"sqlite_autoincrement": True},
    )


class DashboardEventCause(Base):
    __tablename__ = "dashboard_event_causes"
    source_version: Mapped[int] = mapped_column(VERSION, primary_key=True)
    cause_key: Mapped[str] = mapped_column(String(64), primary_key=True)


class DashboardRecordState(NumericContribution, Base):
    __tablename__ = "dashboard_record_state"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_key: Mapped[str] = mapped_column(String(36))
    run_key: Mapped[str] = mapped_column(String(36), index=True)
    record_key: Mapped[str] = mapped_column(String(260))
    metric_key: Mapped[str] = mapped_column(String(240), default="")
    record_kind: Mapped[str] = mapped_column(String(20))
    pass_number: Mapped[int] = mapped_column(Integer, default=0)
    bucket_key: Mapped[int] = mapped_column(Integer, default=0)
    applied_source_version: Mapped[int] = mapped_column(VERSION, default=0)
    present: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    __table_args__ = (
        UniqueConstraint(
            "project_key",
            "record_key",
            "metric_key",
            "record_kind",
            "pass_number",
            name="uq_dashboard_record_identity",
        ),
        Index("ix_dashboard_record_retention", "present", "updated_at", "id"),
        Index(
            "ix_dashboard_record_latency",
            "run_key",
            "record_kind",
            "present",
            "latency_ms",
        ),
        Index(
            "ix_dashboard_record_score",
            "run_key",
            "record_kind",
            "present",
            "metric_key",
            "score",
        ),
        Index(
            "ix_dashboard_record_bucket",
            "project_key",
            "bucket_key",
            "present",
            "latency_ms",
        ),
        Index(
            "ix_dashboard_record_bucket_score",
            "project_key",
            "bucket_key",
            "present",
            "score",
        ),
    )


class DashboardRecordCause(Base):
    __tablename__ = "dashboard_record_causes"
    record_state_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cause_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_key: Mapped[str] = mapped_column(String(36), index=True)
    pass_number: Mapped[int] = mapped_column(Integer, default=0)


class DashboardRunDimension(Base):
    __tablename__ = "dashboard_run_dimensions"
    run_key: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_key: Mapped[str] = mapped_column(String(36), index=True)
    task: Mapped[str] = mapped_column(String(200), index=True)
    model: Mapped[str] = mapped_column(String(240), index=True)
    dataset: Mapped[str] = mapped_column(String(400), index=True)
    version: Mapped[str] = mapped_column(String(400), default="", index=True)
    owner: Mapped[str] = mapped_column(String(36), index=True)
    status: Mapped[str] = mapped_column(String(40), index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    present: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    # Labels and small display descriptors only. No item/score/span payloads.
    descriptor: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class RollupNumbers:
    count: Mapped[int] = mapped_column(Integer, default=0)
    terminal_count: Mapped[int] = mapped_column(Integer, default=0)
    success_count: Mapped[int] = mapped_column(Integer, default=0)
    error_count: Mapped[int] = mapped_column(Integer, default=0)
    retry_sum: Mapped[int] = mapped_column(Integer, default=0)
    latency_count: Mapped[int] = mapped_column(Integer, default=0)
    latency_sum: Mapped[float] = mapped_column(Float, default=0.0)
    latency_sum_squares: Mapped[float] = mapped_column(Float, default=0.0)
    score_count: Mapped[int] = mapped_column(Integer, default=0)
    score_sum: Mapped[float] = mapped_column(Float, default=0.0)
    score_sum_squares: Mapped[float] = mapped_column(Float, default=0.0)
    latency_min: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    latency_max: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    score_min: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    score_max: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    extrema_state: Mapped[str] = mapped_column(String(20), default="unknown")
    extrema_verified_version: Mapped[int] = mapped_column(VERSION, default=0)
    dirty_since_version: Mapped[Optional[int]] = mapped_column(VERSION, nullable=True)
    applied_source_version: Mapped[int] = mapped_column(VERSION, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class DashboardRunSummary(RollupNumbers, Base):
    __tablename__ = "dashboard_run_summaries"
    projection_revision: Mapped[int] = mapped_column(VERSION, default=0)
    run_key: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_key: Mapped[str] = mapped_column(String(36), index=True)
    # Small numeric metric/pass dictionaries; never source item/trace content.
    data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    median_latency_ms: Mapped[float] = mapped_column(Float, default=0.0)
    avg_latency_ms: Mapped[float] = mapped_column(Float, default=0.0)
    success_rate: Mapped[float] = mapped_column(Float, default=0.0)
    completed_success_rate: Mapped[float] = mapped_column(Float, default=-1.0)


class DashboardBucketRollup(RollupNumbers, Base):
    __tablename__ = "dashboard_bucket_rollups"
    project_key: Mapped[str] = mapped_column(String(36), primary_key=True)
    slice_key: Mapped[str] = mapped_column(String(260), primary_key=True, default="all")
    bucket_key: Mapped[int] = mapped_column(Integer, primary_key=True)
    granularity: Mapped[str] = mapped_column(String(8), primary_key=True)


class DashboardHistogram(Base):
    __tablename__ = "dashboard_histograms"
    project_key: Mapped[str] = mapped_column(String(36), primary_key=True)
    slice_key: Mapped[str] = mapped_column(String(260), primary_key=True)
    bucket_key: Mapped[int] = mapped_column(Integer, primary_key=True)
    granularity: Mapped[str] = mapped_column(String(8), primary_key=True)
    definition_version: Mapped[int] = mapped_column(
        Integer, primary_key=True, default=1
    )
    value_kind: Mapped[str] = mapped_column(String(12), primary_key=True)
    bucket_index: Mapped[int] = mapped_column(Integer, primary_key=True)
    count: Mapped[int] = mapped_column(Integer, default=0)


class DashboardPartitionState(Base):
    __tablename__ = "dashboard_partition_state"
    partition_key: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_key: Mapped[str] = mapped_column(String(36), index=True)
    last_enqueued_version: Mapped[int] = mapped_column(VERSION, default=0)
    last_applied_version: Mapped[int] = mapped_column(VERSION, default=0)
    oldest_pending_event: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True
    )
    queue_state: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    lease_owner: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    lease_until: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    backfill_kind: Mapped[str] = mapped_column(String(20), default="item")
    backfill_cursor: Mapped[int] = mapped_column(Integer, default=0)
    backfill_source_version: Mapped[int] = mapped_column(VERSION, default=0)
    backfill_complete: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class DashboardDeadLetter(Base):
    __tablename__ = "dashboard_dead_letters"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(String(36), unique=True)
    project_key: Mapped[str] = mapped_column(String(36), index=True)
    partition_key: Mapped[str] = mapped_column(String(36), index=True)
    source_version: Mapped[int] = mapped_column(VERSION)
    error: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
