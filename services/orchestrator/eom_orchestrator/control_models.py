"""SQLAlchemy records for the Codex execution control plane."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
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

from eom_orchestrator.models import Base

REVISION_STATES = ("DRAFT", "RELEASED", "DEPRECATED")
AUTH_HEALTH_STATES = ("READY", "STALE", "AUTH_REQUIRED", "DEGRADED", "DRAINING", "DISABLED")
LEASE_STATES = ("ACTIVE", "RELEASED", "EXPIRED", "RECONCILING")
HELD_LEASE_PREDICATE = text("state IN ('ACTIVE','RECONCILING')")


class ExecutionBundleRecord(Base):
    __tablename__ = "execution_bundles"
    __table_args__ = (
        CheckConstraint("bundle_kind IN ('INSTRUCTION','REFERENCE')", name="ck_bundle_kind"),
        CheckConstraint("state IN ('ACTIVE','RETIRED')", name="ck_execution_bundles_state"),
        UniqueConstraint("bundle_kind", "bundle_key", name="uq_execution_bundle_kind_key"),
        UniqueConstraint("bundle_id", "bundle_kind", name="uq_execution_bundle_id_kind"),
        ForeignKeyConstraint(
            ["current_revision_id", "bundle_id"],
            [
                "execution_bundle_revisions.bundle_revision_id",
                "execution_bundle_revisions.bundle_id",
            ],
            name="fk_execution_bundles_current_revision_owner",
            use_alter=True,
            ondelete="RESTRICT",
        ),
    )

    bundle_id: Mapped[str] = mapped_column(String(44), primary_key=True)
    bundle_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    bundle_key: Mapped[str] = mapped_column(String(128), nullable=False)
    current_revision_id: Mapped[str | None] = mapped_column(String(41), nullable=True)
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="ACTIVE")
    created_by: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class ExecutionBundleRevisionRecord(Base):
    __tablename__ = "execution_bundle_revisions"
    __table_args__ = (
        CheckConstraint(
            "state IN ('DRAFT','RELEASED','DEPRECATED')",
            name="ck_execution_bundle_revisions_state",
        ),
        CheckConstraint(
            "(bundle_kind = 'INSTRUCTION' AND bundle_revision_id LIKE 'instrrev_%') OR "
            "(bundle_kind = 'REFERENCE' AND bundle_revision_id LIKE 'refrev_%')",
            name="ck_execution_bundle_revision_id_kind",
        ),
        CheckConstraint("revision_number >= 1", name="ck_execution_bundle_revision_number"),
        CheckConstraint(
            "manifest_sha256 ~ '^sha256:[0-9a-f]{64}$' "
            "AND content_sha256 ~ '^sha256:[0-9a-f]{64}$'",
            name="ck_execution_bundle_revision_hashes",
        ),
        ForeignKeyConstraint(
            ["bundle_id", "bundle_kind"],
            ["execution_bundles.bundle_id", "execution_bundles.bundle_kind"],
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "bundle_id", "revision_number", name="uq_execution_bundle_revision_number"
        ),
        UniqueConstraint(
            "bundle_revision_id", "bundle_id", name="uq_execution_bundle_revision_owner"
        ),
    )

    bundle_revision_id: Mapped[str] = mapped_column(String(41), primary_key=True)
    bundle_id: Mapped[str] = mapped_column(String(44), nullable=False, index=True)
    bundle_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    manifest_artifact_id: Mapped[str] = mapped_column(
        ForeignKey("artifacts.logical_artifact_id"), nullable=False
    )
    manifest_artifact_revision_id: Mapped[str] = mapped_column(
        ForeignKey("artifact_revisions.revision_id"), nullable=False, unique=True
    )
    manifest_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    canonical_document: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_by: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class WorkerCapacityPolicyRecord(Base):
    __tablename__ = "worker_capacity_policies"
    __table_args__ = (
        CheckConstraint("state IN ('ACTIVE','RETIRED')", name="ck_capacity_policies_state"),
        UniqueConstraint("policy_key", name="uq_worker_capacity_policy_key"),
        ForeignKeyConstraint(
            ["current_revision_id", "capacity_policy_id"],
            [
                "worker_capacity_policy_revisions.capacity_policy_revision_id",
                "worker_capacity_policy_revisions.capacity_policy_id",
            ],
            name="fk_capacity_policies_current_revision_owner",
            use_alter=True,
            ondelete="RESTRICT",
        ),
    )

    capacity_policy_id: Mapped[str] = mapped_column(String(41), primary_key=True)
    policy_key: Mapped[str] = mapped_column(String(128), nullable=False)
    current_revision_id: Mapped[str | None] = mapped_column(String(44), nullable=True)
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="ACTIVE")
    created_by: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class WorkerCapacityPolicyRevisionRecord(Base):
    __tablename__ = "worker_capacity_policy_revisions"
    __table_args__ = (
        CheckConstraint(
            "state IN ('DRAFT','RELEASED','DEPRECATED')",
            name="ck_capacity_policy_revisions_state",
        ),
        CheckConstraint(
            "max_configured_slots BETWEEN 1 AND 5 AND max_active_codex BETWEEN 1 AND 3 "
            "AND max_active_codex <= max_configured_slots AND max_active_per_slot = 1 "
            "AND max_active_gpu = 1 AND max_active_knowledge_analysis = 1",
            name="ck_capacity_policy_host_limits",
        ),
        CheckConstraint("revision_number >= 1", name="ck_capacity_policy_revision_number_value"),
        CheckConstraint(
            "content_sha256 ~ '^sha256:[0-9a-f]{64}$'",
            name="ck_capacity_policy_revision_hash",
        ),
        UniqueConstraint(
            "capacity_policy_id", "revision_number", name="uq_capacity_policy_revision_number"
        ),
        UniqueConstraint(
            "capacity_policy_revision_id",
            "capacity_policy_id",
            name="uq_capacity_policy_revision_owner",
        ),
    )

    capacity_policy_revision_id: Mapped[str] = mapped_column(String(44), primary_key=True)
    capacity_policy_id: Mapped[str] = mapped_column(
        ForeignKey("worker_capacity_policies.capacity_policy_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    max_configured_slots: Mapped[int] = mapped_column(Integer, nullable=False)
    max_active_codex: Mapped[int] = mapped_column(Integer, nullable=False)
    max_active_per_slot: Mapped[int] = mapped_column(Integer, nullable=False)
    max_active_gpu: Mapped[int] = mapped_column(Integer, nullable=False)
    max_active_knowledge_analysis: Mapped[int] = mapped_column(Integer, nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    canonical_document: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_by: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class WorkerCapacityPoolRecord(Base):
    __tablename__ = "worker_capacity_pools"
    __table_args__ = (
        CheckConstraint("max_active BETWEEN 1 AND 3", name="ck_worker_capacity_pool_limit"),
    )

    capacity_policy_revision_id: Mapped[str] = mapped_column(
        ForeignKey(
            "worker_capacity_policy_revisions.capacity_policy_revision_id", ondelete="CASCADE"
        ),
        primary_key=True,
    )
    pool_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    max_active: Mapped[int] = mapped_column(Integer, nullable=False)


class WorkerCapacityPoolRoleRecord(Base):
    __tablename__ = "worker_capacity_pool_roles"
    __table_args__ = (
        ForeignKeyConstraint(
            ["capacity_policy_revision_id", "pool_key"],
            ["worker_capacity_pools.capacity_policy_revision_id", "worker_capacity_pools.pool_key"],
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "role IN ('authoring','image','review','item_management','support')",
            name="ck_worker_capacity_pool_role",
        ),
    )

    capacity_policy_revision_id: Mapped[str] = mapped_column(String(44), primary_key=True)
    pool_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    role: Mapped[str] = mapped_column(String(64), primary_key=True)


class WorkerCapacityPoolSlotRecord(Base):
    __tablename__ = "worker_capacity_pool_slots"
    __table_args__ = (
        ForeignKeyConstraint(
            ["capacity_policy_revision_id", "pool_key"],
            ["worker_capacity_pools.capacity_policy_revision_id", "worker_capacity_pools.pool_key"],
            ondelete="CASCADE",
        ),
    )

    capacity_policy_revision_id: Mapped[str] = mapped_column(String(44), primary_key=True)
    pool_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    slot_id: Mapped[str] = mapped_column(
        ForeignKey("worker_slots.slot_id", ondelete="RESTRICT"), primary_key=True
    )


class ExecutionPresetRecord(Base):
    __tablename__ = "execution_presets"
    __table_args__ = (
        CheckConstraint("state IN ('ACTIVE','RETIRED')", name="ck_execution_presets_state"),
        UniqueConstraint("preset_key", name="uq_execution_preset_key"),
        ForeignKeyConstraint(
            ["current_revision_id", "preset_id"],
            [
                "execution_preset_revisions.preset_revision_id",
                "execution_preset_revisions.preset_id",
            ],
            name="fk_execution_presets_current_revision_owner",
            use_alter=True,
            ondelete="RESTRICT",
        ),
    )

    preset_id: Mapped[str] = mapped_column(String(43), primary_key=True)
    preset_key: Mapped[str] = mapped_column(String(128), nullable=False)
    current_revision_id: Mapped[str | None] = mapped_column(String(46), nullable=True)
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="ACTIVE")
    created_by: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class ExecutionPresetRevisionRecord(Base):
    __tablename__ = "execution_preset_revisions"
    __table_args__ = (
        CheckConstraint(
            "state IN ('DRAFT','RELEASED','DEPRECATED')",
            name="ck_execution_preset_revisions_state",
        ),
        CheckConstraint(
            "general_knowledge_policy IN ('DENY','ALLOW_WITH_PROVENANCE')",
            name="ck_execution_preset_general_knowledge",
        ),
        CheckConstraint("revision_number >= 1", name="ck_execution_preset_revision_number_value"),
        CheckConstraint(
            "content_sha256 ~ '^sha256:[0-9a-f]{64}$'",
            name="ck_execution_preset_revision_hash",
        ),
        UniqueConstraint(
            "preset_id", "revision_number", name="uq_execution_preset_revision_number"
        ),
        UniqueConstraint(
            "preset_revision_id", "preset_id", name="uq_execution_preset_revision_owner"
        ),
    )

    preset_revision_id: Mapped[str] = mapped_column(String(46), primary_key=True)
    preset_id: Mapped[str] = mapped_column(
        ForeignKey("execution_presets.preset_id", ondelete="RESTRICT"), nullable=False, index=True
    )
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    capacity_policy_revision_id: Mapped[str] = mapped_column(
        ForeignKey("worker_capacity_policy_revisions.capacity_policy_revision_id"), nullable=False
    )
    general_knowledge_policy: Mapped[str] = mapped_column(String(32), nullable=False)
    compatible_workflow_protocols: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    canonical_document: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_by: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ExecutionPresetRolePolicyRecord(Base):
    __tablename__ = "execution_preset_role_policies"
    __table_args__ = (
        CheckConstraint(
            "role IN ('authoring','image','review','item_management','support')",
            name="ck_execution_preset_role",
        ),
        CheckConstraint("timeout_seconds BETWEEN 30 AND 7200", name="ck_preset_role_timeout"),
    )

    preset_revision_id: Mapped[str] = mapped_column(
        ForeignKey("execution_preset_revisions.preset_revision_id", ondelete="CASCADE"),
        primary_key=True,
    )
    role: Mapped[str] = mapped_column(String(64), primary_key=True)
    model_candidates: Mapped[list[dict[str, str]]] = mapped_column(JSONB, nullable=False)
    instruction_bundle_revision_id: Mapped[str] = mapped_column(
        ForeignKey("execution_bundle_revisions.bundle_revision_id"), nullable=False
    )
    reference_bundle_revision_id: Mapped[str | None] = mapped_column(
        ForeignKey("execution_bundle_revisions.bundle_revision_id"), nullable=True
    )
    worker_pool_key: Mapped[str] = mapped_column(String(64), nullable=False)
    timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    sandbox: Mapped[str] = mapped_column(String(16), nullable=False)
    network: Mapped[str] = mapped_column(String(16), nullable=False)


class ExecutionPresetEvaluationRecord(Base):
    __tablename__ = "execution_preset_evaluations"
    __table_args__ = (
        CheckConstraint(
            "scope IN ('STATIC','NON_LIVE','LIVE_ONE_SHOT')",
            name="ck_execution_preset_evaluation_scope",
        ),
        CheckConstraint(
            "outcome IN ('PASS','FAIL')", name="ck_execution_preset_evaluation_outcome"
        ),
        CheckConstraint(
            "evaluated_policy_sha256 ~ '^sha256:[0-9a-f]{64}$' "
            "AND report_document_sha256 ~ '^sha256:[0-9a-f]{64}$' "
            "AND report_content_sha256 ~ '^sha256:[0-9a-f]{64}$'",
            name="ck_execution_preset_evaluation_hashes",
        ),
        CheckConstraint(
            "cases_total BETWEEN 1 AND 10000 AND cases_passed BETWEEN 0 AND cases_total",
            name="ck_execution_preset_evaluation_cases",
        ),
        CheckConstraint(
            "quality_score_permille IS NULL OR quality_score_permille BETWEEN 0 AND 1000",
            name="ck_execution_preset_evaluation_quality",
        ),
        UniqueConstraint(
            "report_artifact_revision_id", name="uq_execution_preset_evaluation_report_revision"
        ),
        Index(
            "ix_execution_preset_evaluation_policy",
            "preset_id",
            "evaluated_policy_sha256",
            "completed_at",
        ),
    )

    evaluation_id: Mapped[str] = mapped_column(String(43), primary_key=True)
    preset_id: Mapped[str] = mapped_column(
        ForeignKey("execution_presets.preset_id", ondelete="RESTRICT"), nullable=False
    )
    evaluated_preset_revision_id: Mapped[str] = mapped_column(
        ForeignKey("execution_preset_revisions.preset_revision_id", ondelete="RESTRICT"),
        nullable=False,
    )
    evaluated_policy_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    scope: Mapped[str] = mapped_column(String(24), nullable=False)
    outcome: Mapped[str] = mapped_column(String(16), nullable=False)
    summary_code: Mapped[str] = mapped_column(String(64), nullable=False)
    cases_total: Mapped[int] = mapped_column(Integer, nullable=False)
    cases_passed: Mapped[int] = mapped_column(Integer, nullable=False)
    quality_score_permille: Mapped[int | None] = mapped_column(Integer, nullable=True)
    report_artifact_id: Mapped[str] = mapped_column(
        ForeignKey("artifacts.logical_artifact_id", ondelete="RESTRICT"), nullable=False
    )
    report_artifact_revision_id: Mapped[str] = mapped_column(
        ForeignKey("artifact_revisions.revision_id", ondelete="RESTRICT"), nullable=False
    )
    report_document_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    report_content_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_by: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ResolvedExecutionPlanRecord(Base):
    __tablename__ = "resolved_execution_plans"
    __table_args__ = (
        CheckConstraint(
            "(evidence_bundle_revision_id IS NULL) OR (graph_snapshot_revision_id IS NOT NULL)",
            name="ck_execution_plan_evidence_snapshot",
        ),
        CheckConstraint("plan_sha256 ~ '^sha256:[0-9a-f]{64}$'", name="ck_execution_plan_hash"),
        UniqueConstraint("workflow_id", name="uq_execution_plan_workflow"),
    )

    plan_id: Mapped[str] = mapped_column(String(41), primary_key=True)
    workflow_id: Mapped[str] = mapped_column(
        ForeignKey("workflow_instances.workflow_id", ondelete="RESTRICT"), nullable=False
    )
    preset_id: Mapped[str] = mapped_column(
        ForeignKey("execution_presets.preset_id"), nullable=False
    )
    preset_revision_id: Mapped[str] = mapped_column(
        ForeignKey("execution_preset_revisions.preset_revision_id"), nullable=False
    )
    capacity_policy_revision_id: Mapped[str] = mapped_column(
        ForeignKey("worker_capacity_policy_revisions.capacity_policy_revision_id"), nullable=False
    )
    graph_snapshot_revision_id: Mapped[str | None] = mapped_column(String(41), nullable=True)
    evidence_bundle_revision_id: Mapped[str | None] = mapped_column(String(44), nullable=True)
    plan_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    resolver_version: Mapped[str] = mapped_column(String(32), nullable=False)
    canonical_document: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    resolved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ResolvedExecutionPlanStepRecord(Base):
    __tablename__ = "resolved_execution_plan_steps"
    __table_args__ = (
        CheckConstraint(
            "role IN ('authoring','image','review','item_management','support')",
            name="ck_resolved_execution_plan_step_role",
        ),
        CheckConstraint(
            "reasoning_effort IN ('minimal','low','medium','high','xhigh')",
            name="ck_resolved_execution_plan_step_effort",
        ),
        CheckConstraint(
            "general_knowledge_mode IN ('DENIED','ALLOWED_WITH_PROVENANCE')",
            name="ck_resolved_execution_plan_step_knowledge",
        ),
        CheckConstraint("timeout_seconds BETWEEN 30 AND 7200", name="ck_plan_step_timeout"),
    )

    plan_id: Mapped[str] = mapped_column(
        ForeignKey("resolved_execution_plans.plan_id", ondelete="CASCADE"), primary_key=True
    )
    step_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    role: Mapped[str] = mapped_column(String(64), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    reasoning_effort: Mapped[str] = mapped_column(String(16), nullable=False)
    instruction_bundle_revision_id: Mapped[str] = mapped_column(
        ForeignKey("execution_bundle_revisions.bundle_revision_id"), nullable=False
    )
    reference_bundle_revision_id: Mapped[str | None] = mapped_column(
        ForeignKey("execution_bundle_revisions.bundle_revision_id"), nullable=True
    )
    worker_pool_key: Mapped[str] = mapped_column(String(64), nullable=False)
    timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    sandbox: Mapped[str] = mapped_column(String(16), nullable=False)
    network: Mapped[str] = mapped_column(String(16), nullable=False)
    general_knowledge_mode: Mapped[str] = mapped_column(String(32), nullable=False)


class CodexAuthBindingRecord(Base):
    __tablename__ = "codex_auth_bindings"
    __table_args__ = (
        CheckConstraint(
            "state IN ('READY','STALE','AUTH_REQUIRED','DEGRADED','DRAINING','DISABLED')",
            name="ck_codex_auth_binding_state",
        ),
        CheckConstraint(
            "(state = 'READY' AND reason_code IS NULL AND observed_at IS NOT NULL "
            "AND valid_until IS NOT NULL AND valid_until > observed_at) OR "
            "(state <> 'READY' AND reason_code IS NOT NULL)",
            name="ck_codex_auth_binding_health_evidence",
        ),
        CheckConstraint("resource_version >= 1", name="ck_codex_auth_binding_version"),
        UniqueConstraint("worker_slot_id", name="uq_codex_auth_binding_slot"),
        ForeignKeyConstraint(
            ["current_assignment_revision_id", "binding_id"],
            [
                "codex_auth_assignment_revisions.assignment_revision_id",
                "codex_auth_assignment_revisions.binding_id",
            ],
            name="fk_codex_auth_binding_current_assignment_owner",
            use_alter=True,
            ondelete="RESTRICT",
        ),
    )

    binding_id: Mapped[str] = mapped_column(String(44), primary_key=True)
    worker_slot_id: Mapped[str] = mapped_column(
        ForeignKey("worker_slots.slot_id", ondelete="RESTRICT"), nullable=False
    )
    account_label: Mapped[str] = mapped_column(String(64), nullable=False)
    current_assignment_revision_id: Mapped[str | None] = mapped_column(String(46), nullable=True)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    reason_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    codex_cli_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resource_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class CodexAuthAssignmentRevisionRecord(Base):
    """Immutable non-secret account-label assignment history for one fixed binding."""

    __tablename__ = "codex_auth_assignment_revisions"
    __table_args__ = (
        CheckConstraint("revision_number >= 1", name="ck_codex_auth_assignment_revision_number"),
        CheckConstraint(
            "assignment_sha256 ~ '^sha256:[0-9a-f]{64}$'",
            name="ck_codex_auth_assignment_revision_hash",
        ),
        CheckConstraint(
            "login_method = 'CHATGPT_DEVICE_CODE'",
            name="ck_codex_auth_assignment_login_method",
        ),
        UniqueConstraint(
            "binding_id", "revision_number", name="uq_codex_auth_assignment_revision_number"
        ),
        UniqueConstraint(
            "assignment_revision_id",
            "binding_id",
            name="uq_codex_auth_assignment_revision_owner",
        ),
        UniqueConstraint("enrollment_id", name="uq_codex_auth_assignment_enrollment"),
        ForeignKeyConstraint(
            ["enrollment_id"],
            ["codex_auth_enrollments.enrollment_id"],
            name="fk_codex_auth_assignment_enrollment",
            use_alter=True,
            ondelete="RESTRICT",
        ),
    )

    assignment_revision_id: Mapped[str] = mapped_column(String(46), primary_key=True)
    binding_id: Mapped[str] = mapped_column(
        ForeignKey("codex_auth_bindings.binding_id", ondelete="RESTRICT"), nullable=False
    )
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    enrollment_id: Mapped[str] = mapped_column(String(41), nullable=False)
    account_label: Mapped[str] = mapped_column(String(64), nullable=False)
    login_method: Mapped[str] = mapped_column(String(32), nullable=False)
    codex_cli_version: Mapped[str] = mapped_column(String(32), nullable=False)
    assigned_by_operator_id: Mapped[str] = mapped_column(
        ForeignKey("operators.operator_id", ondelete="RESTRICT"), nullable=False
    )
    assignment_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class CodexAuthEnrollmentRecord(Base):
    """Durable, credential-free state for one GUI-coordinated device-login attempt."""

    __tablename__ = "codex_auth_enrollments"
    __table_args__ = (
        CheckConstraint(
            "state IN ('REQUESTED','DRAINING','READY_FOR_LOGIN','WAITING_FOR_USER',"
            "'VERIFYING','SUCCEEDED','FAILED','CANCELLED','EXPIRED')",
            name="ck_codex_auth_enrollment_state",
        ),
        CheckConstraint("resource_version >= 1", name="ck_codex_auth_enrollment_version"),
        CheckConstraint(
            "request_sha256 ~ '^sha256:[0-9a-f]{64}$'",
            name="ck_codex_auth_enrollment_hash",
        ),
        CheckConstraint(
            "expires_at > requested_at AND expires_at <= requested_at + interval '15 minutes'",
            name="ck_codex_auth_enrollment_window",
        ),
        CheckConstraint(
            "login_unit_started_at IS NULL OR "
            "(login_unit_started_at >= requested_at AND login_unit_started_at < expires_at)",
            name="ck_codex_auth_enrollment_login_start_window",
        ),
        CheckConstraint(
            "(lease_owner IS NULL AND lease_expires_at IS NULL) OR "
            "(lease_owner IS NOT NULL AND lease_expires_at IS NOT NULL)",
            name="ck_codex_auth_enrollment_lease_pair",
        ),
        CheckConstraint(
            "(state = 'SUCCEEDED' AND completed_at IS NOT NULL "
            "AND assignment_revision_id IS NOT NULL AND error_code IS NULL "
            "AND next_action_at IS NULL AND lease_owner IS NULL) OR "
            "(state IN ('FAILED','CANCELLED','EXPIRED') AND completed_at IS NOT NULL "
            "AND assignment_revision_id IS NULL AND error_code IS NOT NULL "
            "AND next_action_at IS NULL AND lease_owner IS NULL) OR "
            "(state IN ('REQUESTED','DRAINING','READY_FOR_LOGIN','WAITING_FOR_USER','VERIFYING') "
            "AND completed_at IS NULL AND assignment_revision_id IS NULL AND error_code IS NULL "
            "AND next_action_at IS NOT NULL)",
            name="ck_codex_auth_enrollment_lifecycle",
        ),
        UniqueConstraint("idempotency_key", name="uq_codex_auth_enrollment_idempotency"),
        ForeignKeyConstraint(
            ["assignment_revision_id", "binding_id"],
            [
                "codex_auth_assignment_revisions.assignment_revision_id",
                "codex_auth_assignment_revisions.binding_id",
            ],
            name="fk_codex_auth_enrollment_assignment_owner",
            use_alter=True,
            ondelete="RESTRICT",
        ),
        Index(
            "uq_codex_auth_enrollment_active_binding",
            "binding_id",
            unique=True,
            postgresql_where=text(
                "state IN ('REQUESTED','DRAINING','READY_FOR_LOGIN','WAITING_FOR_USER','VERIFYING')"
            ),
        ),
        Index(
            "ix_codex_auth_enrollment_claim",
            "state",
            "next_action_at",
            "lease_expires_at",
            "requested_at",
            "enrollment_id",
            postgresql_where=text(
                "state IN ('REQUESTED','DRAINING','READY_FOR_LOGIN','WAITING_FOR_USER','VERIFYING')"
            ),
        ),
    )

    enrollment_id: Mapped[str] = mapped_column(String(41), primary_key=True)
    binding_id: Mapped[str] = mapped_column(
        ForeignKey("codex_auth_bindings.binding_id", ondelete="RESTRICT"), nullable=False
    )
    expected_binding_resource_version: Mapped[int] = mapped_column(Integer, nullable=False)
    requested_account_label: Mapped[str] = mapped_column(String(64), nullable=False)
    requested_by_operator_id: Mapped[str] = mapped_column(
        ForeignKey("operators.operator_id", ondelete="RESTRICT"), nullable=False
    )
    requested_by_api_session_id: Mapped[str] = mapped_column(
        ForeignKey("api_sessions.api_session_id", ondelete="RESTRICT"), nullable=False
    )
    idempotency_key: Mapped[str] = mapped_column(String(96), nullable=False)
    request_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    canonical_document: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    lease_owner: Mapped[str | None] = mapped_column(String(128), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    next_action_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    challenge_revealed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    login_unit_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    assignment_revision_id: Mapped[str | None] = mapped_column(String(46), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resource_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class CodexAuthHealthEventRecord(Base):
    __tablename__ = "codex_auth_health_events"
    __table_args__ = (
        UniqueConstraint("binding_id", "sequence", name="uq_codex_auth_health_event_sequence"),
        CheckConstraint("sequence >= 1", name="ck_codex_auth_health_event_sequence"),
        CheckConstraint("valid_until > observed_at", name="ck_codex_auth_health_event_window"),
    )

    event_id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    binding_id: Mapped[str] = mapped_column(
        ForeignKey("codex_auth_bindings.binding_id", ondelete="CASCADE"), nullable=False, index=True
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    reason_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    codex_cli_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class CodexCapabilitySnapshotRecord(Base):
    __tablename__ = "codex_capability_snapshots"
    __table_args__ = (
        CheckConstraint(
            "source IN ('LOCAL_OBSERVATION','OPERATOR_ASSERTED')",
            name="ck_codex_capability_snapshot_source",
        ),
        UniqueConstraint("binding_id", "snapshot_sha256", name="uq_codex_capability_binding_hash"),
        CheckConstraint("valid_until > observed_at", name="ck_codex_capability_snapshot_window"),
        CheckConstraint(
            "snapshot_sha256 ~ '^sha256:[0-9a-f]{64}$'",
            name="ck_codex_capability_snapshot_hash",
        ),
        Index("ix_codex_capability_binding_valid", "binding_id", "valid_until"),
    )

    capability_snapshot_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    binding_id: Mapped[str] = mapped_column(
        ForeignKey("codex_auth_bindings.binding_id", ondelete="CASCADE"), nullable=False
    )
    codex_cli_version: Mapped[str] = mapped_column(String(32), nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    snapshot_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    canonical_document: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class CodexCapabilityEntryRecord(Base):
    __tablename__ = "codex_capability_entries"
    __table_args__ = (
        CheckConstraint(
            "reasoning_effort IN ('minimal','low','medium','high','xhigh')",
            name="ck_codex_capability_effort",
        ),
        CheckConstraint(
            "state IN ('AVAILABLE','UNAVAILABLE','UNKNOWN')",
            name="ck_codex_capability_state",
        ),
    )

    capability_snapshot_id: Mapped[str] = mapped_column(
        ForeignKey("codex_capability_snapshots.capability_snapshot_id", ondelete="CASCADE"),
        primary_key=True,
    )
    model: Mapped[str] = mapped_column(String(128), primary_key=True)
    reasoning_effort: Mapped[str] = mapped_column(String(16), primary_key=True)
    state: Mapped[str] = mapped_column(String(16), nullable=False)


class CodexControlCommandRecord(Base):
    __tablename__ = "codex_control_commands"
    __table_args__ = (
        CheckConstraint(
            "command_type IN ('OBSERVE','ENABLE','DRAIN','DISABLE')",
            name="ck_codex_control_command_type",
        ),
        CheckConstraint(
            "state IN ('PENDING','PROCESSING','SUCCEEDED','FAILED')",
            name="ck_codex_control_command_state",
        ),
        CheckConstraint("attempts BETWEEN 0 AND 3", name="ck_codex_control_command_attempts"),
        CheckConstraint(
            "expected_resource_version >= 1",
            name="ck_codex_control_command_expected_version",
        ),
        CheckConstraint(
            "request_sha256 ~ '^sha256:[0-9a-f]{64}$'",
            name="ck_codex_control_command_hash",
        ),
        CheckConstraint(
            "(state = 'PENDING' AND attempts = 0 AND lease_owner IS NULL "
            "AND lease_expires_at IS NULL AND result_resource_version IS NULL "
            "AND result_document IS NULL AND error_code IS NULL AND processed_at IS NULL) OR "
            "(state = 'PROCESSING' AND attempts BETWEEN 1 AND 3 AND lease_owner IS NOT NULL "
            "AND lease_expires_at IS NOT NULL AND result_resource_version IS NULL "
            "AND result_document IS NULL AND error_code IS NULL AND processed_at IS NULL) OR "
            "(state = 'SUCCEEDED' AND attempts BETWEEN 1 AND 3 AND lease_owner IS NULL "
            "AND lease_expires_at IS NULL AND result_resource_version IS NOT NULL "
            "AND result_document IS NOT NULL AND error_code IS NULL AND processed_at IS NOT NULL) "
            "OR (state = 'FAILED' AND attempts BETWEEN 1 AND 3 AND lease_owner IS NULL "
            "AND lease_expires_at IS NULL AND error_code IS NOT NULL AND processed_at IS NOT NULL)",
            name="ck_codex_control_command_lifecycle",
        ),
        UniqueConstraint("idempotency_key", name="uq_codex_control_command_idempotency"),
        Index(
            "ix_codex_control_command_claim",
            "state",
            "lease_expires_at",
            "requested_at",
            "command_id",
        ),
    )

    command_id: Mapped[str] = mapped_column(String(41), primary_key=True)
    command_type: Mapped[str] = mapped_column(String(16), nullable=False)
    binding_id: Mapped[str] = mapped_column(
        ForeignKey("codex_auth_bindings.binding_id", ondelete="RESTRICT"), nullable=False
    )
    expected_resource_version: Mapped[int] = mapped_column(Integer, nullable=False)
    requested_by_operator_id: Mapped[str] = mapped_column(
        ForeignKey("operators.operator_id", ondelete="RESTRICT"), nullable=False
    )
    idempotency_key: Mapped[str] = mapped_column(String(96), nullable=False)
    request_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    canonical_document: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    lease_owner: Mapped[str | None] = mapped_column(String(128), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    result_resource_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    result_document: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB(none_as_null=True), nullable=True
    )
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class WorkerLeaseRecord(Base):
    __tablename__ = "worker_leases"
    __table_args__ = (
        ForeignKeyConstraint(
            ["capacity_policy_revision_id", "pool_key"],
            ["worker_capacity_pools.capacity_policy_revision_id", "worker_capacity_pools.pool_key"],
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "state IN ('ACTIVE','RELEASED','EXPIRED','RECONCILING')",
            name="ck_worker_lease_state",
        ),
        CheckConstraint(
            "workload_class IN ('CODEX','KNOWLEDGE_ANALYSIS')",
            name="ck_worker_lease_workload_class",
        ),
        CheckConstraint("attempt BETWEEN 1 AND 10", name="ck_worker_lease_attempt"),
        CheckConstraint(
            "expires_at > acquired_at AND ((state IN ('ACTIVE','RECONCILING') "
            "AND released_at IS NULL AND release_reason IS NULL) OR "
            "(state IN ('RELEASED','EXPIRED') AND released_at IS NOT NULL "
            "AND release_reason IS NOT NULL AND released_at >= acquired_at))",
            name="ck_worker_lease_lifecycle",
        ),
        Index(
            "uq_worker_lease_held_slot",
            "worker_slot_id",
            unique=True,
            postgresql_where=HELD_LEASE_PREDICATE,
        ),
        Index(
            "uq_worker_lease_held_job",
            "job_id",
            unique=True,
            postgresql_where=HELD_LEASE_PREDICATE,
        ),
        Index(
            "ix_worker_lease_policy_pool_state",
            "capacity_policy_revision_id",
            "pool_key",
            "state",
        ),
        Index(
            "ix_worker_lease_reconciliation",
            "expires_at",
            "lease_id",
            postgresql_where=HELD_LEASE_PREDICATE,
        ),
    )

    lease_id: Mapped[str] = mapped_column(String(44), primary_key=True)
    capacity_policy_revision_id: Mapped[str] = mapped_column(String(44), nullable=False)
    pool_key: Mapped[str] = mapped_column(String(64), nullable=False)
    worker_slot_id: Mapped[str] = mapped_column(
        ForeignKey("worker_slots.slot_id", ondelete="RESTRICT"), nullable=False
    )
    binding_id: Mapped[str] = mapped_column(
        ForeignKey("codex_auth_bindings.binding_id", ondelete="RESTRICT"), nullable=False
    )
    workflow_id: Mapped[str] = mapped_column(
        ForeignKey("workflow_instances.workflow_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    job_id: Mapped[str] = mapped_column(
        ForeignKey("jobs.job_id", ondelete="RESTRICT"), nullable=False
    )
    attempt: Mapped[int] = mapped_column(Integer, nullable=False)
    workload_class: Mapped[str] = mapped_column(String(32), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    acquired_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    release_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)


class WorkerLeaseEventRecord(Base):
    __tablename__ = "worker_lease_events"
    __table_args__ = (
        UniqueConstraint("lease_id", "sequence", name="uq_worker_lease_event_sequence"),
        CheckConstraint("sequence >= 1", name="ck_worker_lease_event_sequence"),
    )

    event_id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    lease_id: Mapped[str] = mapped_column(
        ForeignKey("worker_leases.lease_id", ondelete="CASCADE"), nullable=False, index=True
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    prior_state: Mapped[str | None] = mapped_column(String(16), nullable=True)
    new_state: Mapped[str] = mapped_column(String(16), nullable=False)
    reason_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
