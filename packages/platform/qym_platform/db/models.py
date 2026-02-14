from __future__ import annotations

import enum
from datetime import datetime
from typing import Any, Optional
from uuid import uuid4

from sqlalchemy import (
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
from sqlalchemy.orm import Mapped, mapped_column, relationship

from qym_platform.db.base import Base


class UserRole(str, enum.Enum):
    EMPLOYEE = "EMPLOYEE"
    MANAGER = "MANAGER"
    GM = "GM"
    VP = "VP"
    ADMIN = "ADMIN"


class OrgUnitType(str, enum.Enum):
    TEAM = "TEAM"
    DEPARTMENT = "DEPARTMENT"
    SECTOR = "SECTOR"


class RunWorkflowStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class ApprovalDecision(str, enum.Enum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(200), default="")
    title: Mapped[str] = mapped_column(String(200), default="")
    role: Mapped[UserRole] = mapped_column(Enum(UserRole), default=UserRole.EMPLOYEE)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Each user belongs to exactly one TEAM org unit (nullable during bootstrap/migration)
    team_unit_id: Mapped[Optional[str]] = mapped_column(ForeignKey("org_units.id"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    api_keys: Mapped[list["ApiKey"]] = relationship(back_populates="user")


class UserIdentity(Base):
    __tablename__ = "user_identities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    provider: Mapped[str] = mapped_column(String(50))  # oidc|saml|proxy_headers|local
    subject: Mapped[str] = mapped_column(String(512))
    email: Mapped[Optional[str]] = mapped_column(String(320), nullable=True)
    raw_claims: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    __table_args__ = (UniqueConstraint("provider", "subject", name="uq_identity_provider_subject"),)


class OrgEdge(Base):
    __tablename__ = "org_edges"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    manager_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    employee_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    effective_from: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    effective_to: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    __table_args__ = (UniqueConstraint("manager_id", "employee_id", "effective_from", name="uq_org_edge"),)


class OrgClosure(Base):
    """Ancestor/descendant closure for fast subtree authorization (legacy, user-based)."""

    __tablename__ = "org_closure"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ancestor_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    descendant_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    depth: Mapped[int] = mapped_column(Integer)  # 0=self

    __table_args__ = (UniqueConstraint("ancestor_id", "descendant_id", name="uq_org_closure"),)


class OrgUnit(Base):
    """Org unit: SECTOR → DEPARTMENT → TEAM hierarchy."""

    __tablename__ = "org_units"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    type: Mapped[OrgUnitType] = mapped_column(Enum(OrgUnitType), nullable=False, index=True)
    parent_id: Mapped[Optional[str]] = mapped_column(ForeignKey("org_units.id"), nullable=True, index=True)
    # Only TEAM units have a manager; nullable for DEPARTMENT/SECTOR
    manager_user_id: Mapped[Optional[str]] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("name", "type", "parent_id", name="uq_org_unit_name_type_parent"),
    )


class OrgUnitClosure(Base):
    """Ancestor/descendant closure for OrgUnit hierarchy (fast subtree queries)."""

    __tablename__ = "org_unit_closure"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ancestor_id: Mapped[str] = mapped_column(ForeignKey("org_units.id"), index=True)
    descendant_id: Mapped[str] = mapped_column(ForeignKey("org_units.id"), index=True)
    depth: Mapped[int] = mapped_column(Integer)  # 0=self

    __table_args__ = (UniqueConstraint("ancestor_id", "descendant_id", name="uq_org_unit_closure"),)


class PlatformSetting(Base):
    """Platform-wide settings/policy toggles (key-value store)."""

    __tablename__ = "platform_settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    prefix: Mapped[str] = mapped_column(String(16), index=True)
    key_hash: Mapped[bytes] = mapped_column(LargeBinary)  # store hash only
    scopes: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    user: Mapped["User"] = relationship(back_populates="api_keys")

    __table_args__ = (Index("ix_api_key_prefix_active", "prefix", "revoked_at"),)


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
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

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


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
    trace_id: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    trace_url: Mapped[Optional[str]] = mapped_column(String(2000), nullable=True)

    __table_args__ = (
        UniqueConstraint("run_id", "item_id", name="uq_run_item"),
        Index("ix_run_item_run_index", "run_id", "index"),
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


