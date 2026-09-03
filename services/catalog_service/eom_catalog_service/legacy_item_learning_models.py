"""Pointer-only persistence for legacy-item editorial compatibility analysis."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from eom_orchestrator.models import Base
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


class LegacyItemEditorialCompatibilityPolicyRecord(Base):
    __tablename__ = "legacy_item_editorial_compatibility_policy_revisions"
    __table_args__ = (
        CheckConstraint(
            "state = 'RELEASED'",
            name="ck_legacy_editorial_compatibility_policy_state",
        ),
        CheckConstraint(
            "content_sha256 ~ '^sha256:[0-9a-f]{64}$'",
            name="ck_legacy_editorial_compatibility_policy_hash",
        ),
    )

    compatibility_policy_revision_id: Mapped[str] = mapped_column(String(57), primary_key=True)
    schema_version: Mapped[str] = mapped_column(String(80), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(71), nullable=False, unique=True)
    canonical_document: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    released_by: Mapped[str] = mapped_column(String(128), nullable=False)
    released_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class LegacyItemEditorialCompatibilityRunRecord(Base):
    __tablename__ = "legacy_item_editorial_compatibility_runs"
    __table_args__ = (
        CheckConstraint(
            "state IN ('REQUESTED','RESOLVED','QUEUED','RUNNING','VALIDATING',"
            "'OPEN','CLOSED','FAILED','CANCELLED')",
            name="ck_legacy_editorial_compatibility_run_state",
        ),
        CheckConstraint(
            "result_status IS NULL OR result_status IN ('COMPATIBLE','NEEDS_ADAPTATION','BLOCKED')",
            name="ck_legacy_editorial_compatibility_result_status",
        ),
        CheckConstraint(
            "request_sha256 ~ '^sha256:[0-9a-f]{64}$' "
            "AND submission_sha256 ~ '^sha256:[0-9a-f]{64}$' "
            "AND compatibility_key_sha256 ~ '^sha256:[0-9a-f]{64}$' "
            "AND item_manifest_sha256 ~ '^sha256:[0-9a-f]{64}$' "
            "AND item_content_sha256 ~ '^sha256:[0-9a-f]{64}$' "
            "AND extraction_acceptance_sha256 ~ '^sha256:[0-9a-f]{64}$' "
            "AND item_origin_profile_sha256 ~ '^sha256:[0-9a-f]{64}$' "
            "AND authoring_prompt_sha256 ~ '^sha256:[0-9a-f]{64}$' "
            "AND hwpx_profile_sha256 ~ '^sha256:[0-9a-f]{64}$' "
            "AND renderer_profile_archive_sha256 ~ '^sha256:[0-9a-f]{64}$' "
            "AND renderer_profile_sha256 ~ '^sha256:[0-9a-f]{64}$' "
            "AND compatibility_policy_sha256 ~ '^sha256:[0-9a-f]{64}$'",
            name="ck_legacy_editorial_compatibility_dependency_hashes",
        ),
        CheckConstraint(
            "(proposal_artifact_id IS NULL AND proposal_artifact_revision_id IS NULL "
            "AND proposal_sha256 IS NULL) OR "
            "(proposal_artifact_id IS NOT NULL AND proposal_artifact_revision_id IS NOT NULL "
            "AND proposal_sha256 ~ '^sha256:[0-9a-f]{64}$')",
            name="ck_legacy_editorial_compatibility_proposal_pointer_complete",
        ),
        CheckConstraint(
            "(result_artifact_id IS NULL AND result_artifact_revision_id IS NULL "
            "AND result_sha256 IS NULL AND result_status IS NULL "
            "AND lossless_projection IS NULL AND issue_count IS NULL) OR "
            "(result_artifact_id IS NOT NULL AND result_artifact_revision_id IS NOT NULL "
            "AND result_sha256 ~ '^sha256:[0-9a-f]{64}$' "
            "AND result_status IS NOT NULL AND lossless_projection IS NOT NULL "
            "AND issue_count IS NOT NULL AND issue_count >= 0)",
            name="ck_legacy_editorial_compatibility_result_pointer_complete",
        ),
        CheckConstraint(
            "(state = 'CLOSED' AND result_status = 'COMPATIBLE' "
            "AND lossless_projection IS TRUE AND issue_count = 0) OR state <> 'CLOSED'",
            name="ck_legacy_editorial_compatibility_closed_result",
        ),
        CheckConstraint(
            "(state = 'OPEN' AND result_status IN ('NEEDS_ADAPTATION','BLOCKED') "
            "AND issue_count > 0) OR state <> 'OPEN'",
            name="ck_legacy_editorial_compatibility_open_result",
        ),
        CheckConstraint(
            "state IN ('OPEN','CLOSED') OR result_artifact_revision_id IS NULL",
            name="ck_legacy_editorial_compatibility_result_terminal_only",
        ),
        CheckConstraint(
            "lock_version >= 1",
            name="ck_legacy_editorial_compatibility_lock_version",
        ),
        ForeignKeyConstraint(
            ("item_id", "item_revision_id"),
            ("item_revisions.item_id", "item_revisions.item_revision_id"),
            name="fk_legacy_editorial_compatibility_item_revision_identity",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ("item_content_artifact_id", "item_content_artifact_revision_id"),
            ("artifact_revisions.logical_artifact_id", "artifact_revisions.revision_id"),
            name="fk_legacy_editorial_compatibility_item_content_identity",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ("authoring_prompt_artifact_id", "authoring_prompt_artifact_revision_id"),
            ("artifact_revisions.logical_artifact_id", "artifact_revisions.revision_id"),
            name="fk_legacy_editorial_compatibility_prompt_identity",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ("hwpx_profile_artifact_id", "hwpx_profile_artifact_revision_id"),
            ("artifact_revisions.logical_artifact_id", "artifact_revisions.revision_id"),
            name="fk_legacy_editorial_compatibility_hwpx_identity",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ("renderer_profile_artifact_id", "renderer_profile_artifact_revision_id"),
            ("artifact_revisions.logical_artifact_id", "artifact_revisions.revision_id"),
            name="fk_legacy_editorial_compatibility_renderer_identity",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ("proposal_artifact_id", "proposal_artifact_revision_id"),
            ("artifact_revisions.logical_artifact_id", "artifact_revisions.revision_id"),
            name="fk_legacy_editorial_compatibility_proposal_identity",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ("result_artifact_id", "result_artifact_revision_id"),
            ("artifact_revisions.logical_artifact_id", "artifact_revisions.revision_id"),
            name="fk_legacy_editorial_compatibility_result_identity",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "compatibility_request_id",
            name="uq_legacy_editorial_compatibility_request",
        ),
        UniqueConstraint(
            "idempotency_key",
            name="uq_legacy_editorial_compatibility_idempotency",
        ),
        UniqueConstraint(
            "predecessor_compatibility_run_id",
            name="uq_legacy_editorial_compatibility_predecessor",
        ),
        UniqueConstraint(
            "workflow_id",
            name="uq_legacy_editorial_compatibility_workflow",
        ),
        Index(
            "ix_legacy_editorial_compatibility_item_history",
            "item_revision_id",
            text("created_at DESC"),
            text("compatibility_run_id DESC"),
        ),
        Index(
            "ix_legacy_editorial_compatibility_authorities",
            "authoring_prompt_artifact_revision_id",
            "hwpx_profile_artifact_revision_id",
            "renderer_profile_artifact_revision_id",
            text("created_at DESC"),
        ),
        Index(
            "uq_legacy_editorial_compatibility_terminal_tuple",
            "compatibility_key_sha256",
            unique=True,
            postgresql_where=text("state IN ('OPEN','CLOSED')"),
        ),
        Index(
            "uq_legacy_editorial_compatibility_active_tuple",
            "compatibility_key_sha256",
            unique=True,
            postgresql_where=text(
                "state IN ('REQUESTED','RESOLVED','QUEUED','RUNNING','VALIDATING')"
            ),
        ),
        Index(
            "ix_legacy_editorial_compatibility_open_work",
            "state",
            "created_at",
            "compatibility_run_id",
            postgresql_where=text(
                "state IN ('REQUESTED','RESOLVED','QUEUED','RUNNING','VALIDATING','OPEN')"
            ),
        ),
    )

    compatibility_run_id: Mapped[str] = mapped_column(String(52), primary_key=True)
    predecessor_compatibility_run_id: Mapped[str | None] = mapped_column(
        ForeignKey(
            "legacy_item_editorial_compatibility_runs.compatibility_run_id",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )
    compatibility_request_id: Mapped[str] = mapped_column(String(51), nullable=False)
    request_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    submission_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    compatibility_key_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    canonical_request: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    item_id: Mapped[str] = mapped_column(String(37), nullable=False)
    item_revision_id: Mapped[str] = mapped_column(String(40), nullable=False)
    item_manifest_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    item_content_artifact_id: Mapped[str] = mapped_column(String(41), nullable=False)
    item_content_artifact_revision_id: Mapped[str] = mapped_column(String(36), nullable=False)
    item_content_member_path: Mapped[str] = mapped_column(String(512), nullable=False)
    item_content_schema_ref: Mapped[str] = mapped_column(String(256), nullable=False)
    item_content_media_type: Mapped[str] = mapped_column(String(128), nullable=False)
    item_content_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    extraction_acceptance_id: Mapped[str] = mapped_column(
        ForeignKey("legacy_item_extraction_acceptances.acceptance_id", ondelete="RESTRICT"),
        nullable=False,
    )
    extraction_acceptance_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    item_origin_profile_id: Mapped[str] = mapped_column(
        ForeignKey("item_origin_profiles.item_origin_profile_id", ondelete="RESTRICT"),
        nullable=False,
    )
    item_origin_profile_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    authoring_prompt_artifact_id: Mapped[str] = mapped_column(String(41), nullable=False)
    authoring_prompt_artifact_revision_id: Mapped[str] = mapped_column(String(36), nullable=False)
    authoring_prompt_member_path: Mapped[str] = mapped_column(String(512), nullable=False)
    authoring_prompt_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    hwpx_profile_artifact_id: Mapped[str] = mapped_column(String(41), nullable=False)
    hwpx_profile_artifact_revision_id: Mapped[str] = mapped_column(String(36), nullable=False)
    hwpx_profile_member_path: Mapped[str] = mapped_column(String(512), nullable=False)
    hwpx_profile_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    renderer_profile_artifact_id: Mapped[str] = mapped_column(String(41), nullable=False)
    renderer_profile_artifact_revision_id: Mapped[str] = mapped_column(String(36), nullable=False)
    renderer_profile_archive_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    renderer_profile_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    compatibility_policy_revision_id: Mapped[str] = mapped_column(
        ForeignKey(
            "legacy_item_editorial_compatibility_policy_revisions.compatibility_policy_revision_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    compatibility_policy_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    workflow_id: Mapped[str | None] = mapped_column(
        ForeignKey("workflow_instances.workflow_id", ondelete="RESTRICT"),
        nullable=True,
    )
    plan_id: Mapped[str | None] = mapped_column(
        ForeignKey("resolved_execution_plans.plan_id", ondelete="RESTRICT"),
        nullable=True,
    )
    platform_job_id: Mapped[str | None] = mapped_column(
        ForeignKey("jobs.job_id", ondelete="RESTRICT"),
        nullable=True,
    )
    proposal_artifact_id: Mapped[str | None] = mapped_column(String(41), nullable=True)
    proposal_artifact_revision_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    proposal_sha256: Mapped[str | None] = mapped_column(String(71), nullable=True)
    result_artifact_id: Mapped[str | None] = mapped_column(String(41), nullable=True)
    result_artifact_revision_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    result_sha256: Mapped[str | None] = mapped_column(String(71), nullable=True)
    result_status: Mapped[str | None] = mapped_column(String(24), nullable=True)
    lossless_projection: Mapped[bool | None] = mapped_column(nullable=True)
    issue_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    state: Mapped[str] = mapped_column(String(24), nullable=False)
    lock_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    requested_by_operator_id: Mapped[str] = mapped_column(
        ForeignKey("operators.operator_id", ondelete="RESTRICT"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(96), nullable=True)
    error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)


class LegacyItemEditorialCompatibilityEventRecord(Base):
    __tablename__ = "legacy_item_editorial_compatibility_events"
    __table_args__ = (
        UniqueConstraint(
            "compatibility_run_id",
            "sequence",
            name="uq_legacy_editorial_compatibility_event_sequence",
        ),
        CheckConstraint(
            "sequence >= 1",
            name="ck_legacy_editorial_compatibility_event_sequence",
        ),
        Index("ix_legacy_editorial_events_run", "compatibility_run_id"),
    )

    event_id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    compatibility_run_id: Mapped[str] = mapped_column(
        ForeignKey(
            "legacy_item_editorial_compatibility_runs.compatibility_run_id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    prior_state: Mapped[str | None] = mapped_column(String(24), nullable=True)
    new_state: Mapped[str] = mapped_column(String(24), nullable=False)
    actor_type: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(128), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
