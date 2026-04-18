from __future__ import annotations

import enum
from datetime import datetime
from typing import Any, Optional
from uuid import uuid4

from sqlalchemy import (
    BigInteger,
    JSON,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, Session, mapped_column, relationship

from qym_platform.db.base import Base


class UserRole(str, enum.Enum):
    MEMBER = "MEMBER"
    ADMIN = "ADMIN"


class ProjectRole(str, enum.Enum):
    MEMBER = "MEMBER"
    MANAGER = "MANAGER"


class RunWorkflowStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    STOPPED = "STOPPED"
    PENDING = "PENDING"


class ApprovalDecision(str, enum.Enum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(200), default="")
    title: Mapped[str] = mapped_column(String(200), default="")
    role: Mapped[UserRole] = mapped_column(Enum(UserRole), default=UserRole.MEMBER)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    llm_config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    api_keys: Mapped[list["ApiKey"]] = relationship(back_populates="user")


class UserIdentity(Base):
    __tablename__ = "user_identities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    provider: Mapped[str] = mapped_column(String(50))
    subject: Mapped[str] = mapped_column(String(512))
    email: Mapped[Optional[str]] = mapped_column(String(320), nullable=True)
    raw_claims: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    __table_args__ = (UniqueConstraint("provider", "subject", name="uq_identity_provider_subject"),)


class LocalAuthCredential(Base):
    __tablename__ = "local_auth_credentials"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    password_hash: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(200), nullable=False, unique=True, index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_by_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ProjectMembership(Base):
    __tablename__ = "project_memberships"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    role: Mapped[ProjectRole] = mapped_column(Enum(ProjectRole), default=ProjectRole.MEMBER, index=True)
    added_by_user_id: Mapped[Optional[str]] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("project_id", "user_id", name="uq_project_membership_project_user"),
        Index("ix_project_memberships_project_role", "project_id", "role"),
    )


class PlatformSetting(Base):
    __tablename__ = "platform_settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    prefix: Mapped[str] = mapped_column(String(16), index=True)
    key_hash: Mapped[bytes] = mapped_column(LargeBinary)
    scopes: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    user: Mapped["User"] = relationship(back_populates="api_keys")

    __table_args__ = (Index("ix_api_key_prefix_active", "prefix", "revoked_at"),)


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    external_run_id: Mapped[Optional[str]] = mapped_column(String(200), nullable=True, index=True)
    created_by_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    owner_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)

    task: Mapped[str] = mapped_column(String(200), index=True)
    dataset: Mapped[str] = mapped_column(String(200), index=True)
    model: Mapped[Optional[str]] = mapped_column(String(200), nullable=True, index=True)
    metrics: Mapped[list[str]] = mapped_column(JSON, default=list)
    run_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    run_config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    status: Mapped[RunWorkflowStatus] = mapped_column(Enum(RunWorkflowStatus), default=RunWorkflowStatus.DRAFT, index=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    last_event_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, index=True)
    status_reason: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, default=None, index=True)
    deleted_by_user_id: Mapped[Optional[str]] = mapped_column(ForeignKey("users.id"), nullable=True)

    items: Mapped[list["RunItem"]] = relationship("RunItem", lazy="noload", foreign_keys="RunItem.run_id")
    scores: Mapped[list["RunItemScore"]] = relationship("RunItemScore", lazy="noload", foreign_keys="RunItemScore.run_id")
    approval_rel: Mapped[Optional["Approval"]] = relationship("Approval", uselist=False, lazy="noload", foreign_keys="Approval.run_id")
    owner_user: Mapped[Optional["User"]] = relationship("User", foreign_keys=[owner_user_id], lazy="noload")

    @classmethod
    def active(cls, db: Session):
        return db.query(cls).filter(cls.deleted_at.is_(None))

    def audit_snapshot(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "task": self.task,
            "dataset": self.dataset,
            "model": self.model,
            "status": self.status.value if self.status else None,
            "owner_user_id": self.owner_user_id,
            "created_by_user_id": self.created_by_user_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "external_run_id": self.external_run_id,
        }


class RunItem(Base):
    __tablename__ = "run_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), index=True)
    item_id: Mapped[str] = mapped_column(String(200))
    index: Mapped[int] = mapped_column(Integer, default=0)

    input: Mapped[Any] = mapped_column(JSON)
    expected: Mapped[Any] = mapped_column(JSON, nullable=True)
    output: Mapped[Any] = mapped_column(JSON, nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    item_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    latency_ms: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    trace_id: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    trace_url: Mapped[Optional[str]] = mapped_column(String(2000), nullable=True)

    __table_args__ = (
        UniqueConstraint("run_id", "item_id", name="uq_run_item"),
        Index("ix_run_item_run_index", "run_id", "index"),
    )


class RunItemAttempt(Base):
    __tablename__ = "run_item_attempts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), index=True)
    item_id: Mapped[str] = mapped_column(String(200), index=True)
    attempt_number: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="FAILED")
    latency_ms: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    task_started_at_ms: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    trace_id: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    trace_url: Mapped[Optional[str]] = mapped_column(String(2000), nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_last_attempt: Mapped[bool] = mapped_column(Boolean, default=False)

    __table_args__ = (
        UniqueConstraint("run_id", "item_id", "attempt_number", name="uq_run_item_attempt"),
        Index("ix_run_item_attempt_run_item", "run_id", "item_id"),
    )


class RunItemScore(Base):
    __tablename__ = "run_item_scores"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), index=True)
    item_id: Mapped[str] = mapped_column(String(200), index=True)
    metric_name: Mapped[str] = mapped_column(String(200), index=True)
    score_numeric: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    score_raw: Mapped[Any] = mapped_column(JSON, nullable=True)
    meta: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    label: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    explanation: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    __table_args__ = (UniqueConstraint("run_id", "item_id", "metric_name", name="uq_run_item_metric"),)


class Approval(Base):
    __tablename__ = "approvals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), unique=True, index=True)
    submitted_by_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    submitted_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    decision_by_user_id: Mapped[Optional[str]] = mapped_column(ForeignKey("users.id"), nullable=True)
    decision_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    decision: Mapped[Optional[ApprovalDecision]] = mapped_column(Enum(ApprovalDecision), nullable=True)
    comment: Mapped[str] = mapped_column(Text, default="")


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    actor_user_id: Mapped[Optional[str]] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(200), index=True)
    entity_type: Mapped[str] = mapped_column(String(200), index=True)
    entity_id: Mapped[str] = mapped_column(String(200), index=True)
    before: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    after: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class RunEvent(Base):
    __tablename__ = "run_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), index=True)
    event_id: Mapped[str] = mapped_column(String(36), index=True)
    sequence: Mapped[int] = mapped_column(Integer)
    type: Mapped[str] = mapped_column(String(50))
    sent_at: Mapped[datetime] = mapped_column(DateTime)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    __table_args__ = (
        UniqueConstraint("run_id", "event_id", name="uq_run_event_event_id"),
        UniqueConstraint("run_id", "sequence", name="uq_run_event_sequence"),
    )


class Span(Base):
    __tablename__ = "spans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), index=True)
    trace_id: Mapped[str] = mapped_column(String(64))
    span_id: Mapped[str] = mapped_column(String(32))
    parent_span_id: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    name: Mapped[str] = mapped_column(String(500))
    kind: Mapped[str] = mapped_column(String(20), default="INTERNAL")
    start_time_ns: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    end_time_ns: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    duration_ms: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="UNSET")
    attributes: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    events: Mapped[list] = mapped_column(JSON, default=list)
    links: Mapped[list] = mapped_column(JSON, default=list)

    __table_args__ = (
        Index("ix_span_run_trace", "run_id", "trace_id"),
        UniqueConstraint("run_id", "span_id", name="uq_span"),
    )


class RunTraceAggregate(Base):
    __tablename__ = "run_trace_aggregates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), index=True)
    trace_id: Mapped[str] = mapped_column(String(64))
    span_count: Mapped[int] = mapped_column(Integer, default=0)
    tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost: Mapped[float] = mapped_column(Float, default=0.0)
    llm_calls: Mapped[int] = mapped_column(Integer, default=0)
    tool_calls: Mapped[int] = mapped_column(Integer, default=0)
    tool_errors: Mapped[int] = mapped_column(Integer, default=0)
    malformed_tool_calls: Mapped[int] = mapped_column(Integer, default=0)
    noisy_reasoning: Mapped[int] = mapped_column(Integer, default=0)
    provider_errors: Mapped[int] = mapped_column(Integer, default=0)
    has_reasoning: Mapped[bool] = mapped_column(Boolean, default=False)
    has_reasoning_tokens: Mapped[bool] = mapped_column(Boolean, default=False)
    reasoning_tokens: Mapped[int] = mapped_column(Integer, default=0)

    __table_args__ = (
        Index("ix_run_trace_aggregate_run_trace", "run_id", "trace_id"),
        UniqueConstraint("run_id", "trace_id", name="uq_run_trace_aggregate"),
    )


class CorrectionStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"
    WITHDRAWN = "withdrawn"


class RootCauseRevision(Base):
    __tablename__ = "root_cause_revisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), index=True)
    item_id: Mapped[str] = mapped_column(String(200), index=True)
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    actor_user_id: Mapped[Optional[str]] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    actor_source: Mapped[str] = mapped_column(String(20), nullable=False, default="human")
    before_state: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    after_state: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    backfilled_from_legacy: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("run_id", "item_id", "revision_number", name="uq_root_cause_revision_number"),
        Index("ix_root_cause_revisions_run_item_created", "run_id", "item_id", "created_at"),
    )


class ReviewCorrection(Base):
    __tablename__ = "review_corrections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), index=True)
    item_id: Mapped[str] = mapped_column(String(200), index=True)
    task: Mapped[str] = mapped_column(String(200), index=True)

    input_snapshot: Mapped[Any] = mapped_column(JSON, nullable=True)
    expected_snapshot: Mapped[Any] = mapped_column(JSON, nullable=True)
    output_snapshot: Mapped[Any] = mapped_column(JSON, nullable=True)
    scores_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    ai_root_cause: Mapped[str] = mapped_column(String(200))
    ai_root_cause_detail: Mapped[str] = mapped_column(String(200), default="")
    ai_root_cause_note: Mapped[str] = mapped_column(Text, default="")
    ai_confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    ai_solution: Mapped[str] = mapped_column(String(200), default="")
    ai_solution_note: Mapped[str] = mapped_column(Text, default="")

    human_root_cause: Mapped[str] = mapped_column(String(200))
    human_root_cause_detail: Mapped[str] = mapped_column(String(200), default="")
    human_root_cause_note: Mapped[str] = mapped_column(Text, default="")
    human_solution: Mapped[str] = mapped_column(String(200), default="")
    human_solution_note: Mapped[str] = mapped_column(Text, default="")

    corrected_by_user_id: Mapped[Optional[str]] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    revision_id: Mapped[Optional[int]] = mapped_column(ForeignKey("root_cause_revisions.id"), nullable=True, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    status: Mapped[CorrectionStatus] = mapped_column(
        Enum(CorrectionStatus, values_callable=lambda e: [x.value for x in e]),
        default=CorrectionStatus.PENDING,
        index=True,
    )
    reviewed_by_user_id: Mapped[Optional[str]] = mapped_column(ForeignKey("users.id"), nullable=True)
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    review_comment: Mapped[str] = mapped_column(Text, default="")

    __table_args__ = (
        Index("ix_review_corrections_task_created", "task", "created_at"),
        Index("ix_review_corrections_run_item_active", "run_id", "item_id", "is_active"),
    )
