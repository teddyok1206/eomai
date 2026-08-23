"""SQLAlchemy records owned by the domain-neutral workflow runner."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from eom_orchestrator.models import Base
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

WORKFLOW_STATES = (
    "REQUESTED",
    "RUNNING",
    "AWAITING_HUMAN_APPROVAL",
    "REWORK_REQUESTED",
    "APPROVED",
    "REGISTERING",
    "COMPLETED",
    "FAILED",
    "CANCELLED",
)
WORKFLOW_STAGES = (
    "AUTHORING",
    "IMAGE_REQUIRED",
    "IMAGE_SKIPPED",
    "REVIEWING",
    "AWAITING_HUMAN_APPROVAL",
    "REGISTERING",
    "COMPLETED",
    "FAILED",
    "CANCELLED",
)
STEP_STATES = (
    "PENDING",
    "READY",
    "RUNNING",
    "SUCCEEDED",
    "SKIPPED",
    "WAITING_FOR_HUMAN",
    "FAILED",
    "CANCELLED",
    "SUPERSEDED",
)
COMMAND_STATES = ("PENDING", "LEASED", "PROCESSING", "SUCCEEDED", "FAILED", "CANCELLED")
APPROVAL_STATES = ("PENDING", "APPROVED", "REWORK_REQUESTED", "CANCELLED", "SUPERSEDED")


class WorkflowDefinitionRecord(Base):
    __tablename__ = "workflow_definitions"
    __table_args__ = (
        UniqueConstraint(
            "definition_key", "definition_version", name="uq_workflow_definition_key_version"
        ),
    )

    definition_id: Mapped[str] = mapped_column(String(38), primary_key=True)
    definition_key: Mapped[str] = mapped_column(String(64), nullable=False)
    definition_version: Mapped[str] = mapped_column(String(32), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(16), nullable=False)
    canonical_definition: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    definition_hash: Mapped[str] = mapped_column(String(71), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    source_path: Mapped[str] = mapped_column(Text, nullable=False)
    imported_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class WorkflowInstanceRecord(Base):
    __tablename__ = "workflow_instances"
    __table_args__ = (
        CheckConstraint(
            "state IN ('REQUESTED','RUNNING','AWAITING_HUMAN_APPROVAL','REWORK_REQUESTED',"
            "'APPROVED','REGISTERING','COMPLETED','FAILED','CANCELLED')",
            name="ck_workflow_instances_state",
        ),
        CheckConstraint(
            "stage IN ('AUTHORING','IMAGE_REQUIRED','IMAGE_SKIPPED','REVIEWING',"
            "'AWAITING_HUMAN_APPROVAL','REGISTERING','COMPLETED','FAILED','CANCELLED')",
            name="ck_workflow_instances_stage",
        ),
        Index("ix_workflow_instances_request_hash", "request_hash"),
        Index(
            "uq_workflow_active_request_hash",
            "request_hash",
            unique=True,
            postgresql_where=text(
                "state IN ('REQUESTED','RUNNING','AWAITING_HUMAN_APPROVAL',"
                "'REWORK_REQUESTED','APPROVED','REGISTERING')"
            ),
        ),
    )

    workflow_id: Mapped[str] = mapped_column(String(41), primary_key=True)
    definition_id: Mapped[str] = mapped_column(
        ForeignKey("workflow_definitions.definition_id"), nullable=False
    )
    definition_key: Mapped[str] = mapped_column(String(64), nullable=False)
    definition_version: Mapped[str] = mapped_column(String(32), nullable=False)
    definition_hash: Mapped[str] = mapped_column(String(71), nullable=False)
    protocol_version: Mapped[str] = mapped_column(String(32), nullable=False)
    role_schema_version: Mapped[str] = mapped_column(String(32), nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    stage: Mapped[str] = mapped_column(String(32), nullable=False)
    current_step_key: Mapped[str] = mapped_column(String(64), nullable=False)
    request_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    initial_request: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    runtime_context: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    request_hash: Mapped[str] = mapped_column(String(71), nullable=False)
    lock_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    rework_cycle_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_actor_type: Mapped[str] = mapped_column(String(32), nullable=False)
    created_actor_id: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failure_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    failure_summary: Mapped[str | None] = mapped_column(Text, nullable=True)


class WorkflowStepRunRecord(Base):
    __tablename__ = "workflow_step_runs"
    __table_args__ = (
        UniqueConstraint("workflow_id", "step_key", "attempt", name="uq_workflow_step_attempt"),
        CheckConstraint(
            "state IN ('PENDING','READY','RUNNING','SUCCEEDED','SKIPPED',"
            "'WAITING_FOR_HUMAN','FAILED','CANCELLED','SUPERSEDED')",
            name="ck_workflow_step_runs_state",
        ),
    )

    step_run_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    workflow_id: Mapped[str] = mapped_column(
        ForeignKey("workflow_instances.workflow_id", ondelete="CASCADE"), nullable=False, index=True
    )
    step_key: Mapped[str] = mapped_column(String(64), nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False)
    step_type: Mapped[str] = mapped_column(String(32), nullable=False)
    worker_role: Mapped[str | None] = mapped_column(String(64), nullable=True)
    result_schema: Mapped[str | None] = mapped_column(String(128), nullable=True)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    platform_job_id: Mapped[str | None] = mapped_column(
        ForeignKey("jobs.job_id"), nullable=True, index=True
    )
    input_pointer_manifest: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    output_pointer_manifest: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    superseded_by_step_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("workflow_step_runs.step_run_id"), nullable=True
    )


class WorkflowEventRecord(Base):
    __tablename__ = "workflow_events"
    __table_args__ = (
        UniqueConstraint("workflow_id", "sequence", name="uq_workflow_events_sequence"),
    )

    event_id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    workflow_id: Mapped[str] = mapped_column(
        ForeignKey("workflow_instances.workflow_id", ondelete="CASCADE"), nullable=False, index=True
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    prior_state: Mapped[str | None] = mapped_column(String(32), nullable=True)
    new_state: Mapped[str] = mapped_column(String(32), nullable=False)
    step_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    actor_type: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(128), nullable=False)
    command_id: Mapped[str | None] = mapped_column(String(38), nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class WorkflowCommandRecord(Base):
    __tablename__ = "workflow_commands"
    __table_args__ = (
        CheckConstraint(
            "state IN ('PENDING','LEASED','PROCESSING','SUCCEEDED','FAILED','CANCELLED')",
            name="ck_workflow_commands_state",
        ),
        CheckConstraint(
            "command_type IN ('START_WORKFLOW','ADVANCE_WORKFLOW','APPROVE_WORKFLOW',"
            "'REQUEST_REWORK','CANCEL_WORKFLOW','RETRY_STEP','RECONCILE_WORKFLOW')",
            name="ck_workflow_commands_type",
        ),
        Index(
            "ix_workflow_commands_claimable",
            "state",
            "available_at",
            "created_at",
            "command_id",
        ),
    )

    command_id: Mapped[str] = mapped_column(String(38), primary_key=True)
    workflow_id: Mapped[str] = mapped_column(
        ForeignKey("workflow_instances.workflow_id", ondelete="CASCADE"), nullable=False, index=True
    )
    command_type: Mapped[str] = mapped_column(String(32), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    actor_type: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(128), nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(160), unique=True, nullable=False)
    request_hash: Mapped[str] = mapped_column(String(71), nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    lease_owner: Mapped[str | None] = mapped_column(String(128), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)


class ApprovalRequestRecord(Base):
    __tablename__ = "approval_requests"
    __table_args__ = (
        CheckConstraint(
            "status IN ('PENDING','APPROVED','REWORK_REQUESTED','CANCELLED','SUPERSEDED')",
            name="ck_approval_requests_status",
        ),
        Index(
            "uq_active_approval_per_workflow",
            "workflow_id",
            unique=True,
            postgresql_where=text("status = 'PENDING'"),
        ),
    )

    approval_request_id: Mapped[str] = mapped_column(String(41), primary_key=True)
    workflow_id: Mapped[str] = mapped_column(
        ForeignKey("workflow_instances.workflow_id", ondelete="CASCADE"), nullable=False, index=True
    )
    step_run_id: Mapped[str] = mapped_column(
        ForeignKey("workflow_step_runs.step_run_id"), nullable=False, unique=True
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    lock_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    allowed_roles: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    allowed_rework_targets: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_actor_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    resolved_actor_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    decision: Mapped[str | None] = mapped_column(String(32), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    rework_target_step: Mapped[str | None] = mapped_column(String(64), nullable=True)
