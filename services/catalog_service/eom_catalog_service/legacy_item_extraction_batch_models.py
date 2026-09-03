"""Pointer-only persistence for durable legacy item extraction batches."""

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
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column


class LegacyItemExtractionBatchRecord(Base):
    """One immutable corpus manifest and its derived lifecycle."""

    __tablename__ = "legacy_item_extraction_batches"
    __table_args__ = (
        CheckConstraint(
            "state IN ('QUEUED','RUNNING','AWAITING_REVIEW','SUCCEEDED',"
            "'COMPLETED_WITH_GAPS','CANCELLED')",
            name="ck_legacy_item_extraction_batch_state",
        ),
        CheckConstraint(
            "schema_version = 'legacy-item-extraction-batch/1.1'",
            name="ck_legacy_item_extraction_batch_schema",
        ),
        CheckConstraint(
            "failure_policy = 'CONTINUE_AND_COLLECT'",
            name="ck_legacy_item_extraction_batch_failure_policy",
        ),
        CheckConstraint(
            "manifest_sha256 ~ '^sha256:[0-9a-f]{64}$' "
            "AND inventory_sha256 ~ '^sha256:[0-9a-f]{64}$' "
            "AND manifest_artifact_sha256 ~ '^sha256:[0-9a-f]{64}$'",
            name="ck_legacy_item_extraction_batch_hashes",
        ),
        CheckConstraint(
            "total_work_unit_count BETWEEN 1 AND 10000",
            name="ck_legacy_item_extraction_batch_count",
        ),
        CheckConstraint("resource_version >= 1", name="ck_legacy_item_extraction_batch_version"),
        ForeignKeyConstraint(
            ("manifest_artifact_id", "manifest_artifact_revision_id"),
            ("artifact_revisions.logical_artifact_id", "artifact_revisions.revision_id"),
            name="fk_legacy_item_extraction_batch_manifest_identity",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("idempotency_key", name="uq_legacy_item_extraction_batch_idempotency"),
        UniqueConstraint("manifest_sha256", name="uq_legacy_item_extraction_batch_manifest"),
        Index(
            "ix_legacy_item_extraction_batch_state_created",
            "state",
            text("created_at DESC"),
            "extraction_batch_id",
        ),
    )

    extraction_batch_id: Mapped[str] = mapped_column(String(44), primary_key=True)
    schema_version: Mapped[str] = mapped_column(String(48), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    manifest_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    inventory_id: Mapped[str] = mapped_column(String(48), nullable=False)
    inventory_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    manifest_artifact_id: Mapped[str] = mapped_column(String(41), nullable=False)
    manifest_artifact_revision_id: Mapped[str] = mapped_column(String(36), nullable=False)
    manifest_artifact_member_path: Mapped[str] = mapped_column(String(512), nullable=False)
    manifest_artifact_schema_ref: Mapped[str] = mapped_column(String(256), nullable=False)
    manifest_artifact_media_type: Mapped[str] = mapped_column(String(128), nullable=False)
    manifest_artifact_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    failure_policy: Mapped[str] = mapped_column(String(32), nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    total_work_unit_count: Mapped[int] = mapped_column(Integer, nullable=False)
    requested_by_operator_id: Mapped[str] = mapped_column(
        ForeignKey("operators.operator_id", ondelete="RESTRICT"), nullable=False
    )
    resource_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class LegacyItemExtractionBatchWorkUnitRecord(Base):
    """One ordered request pointer and its single-attempt coordination state."""

    __tablename__ = "legacy_item_extraction_batch_work_units"
    __table_args__ = (
        CheckConstraint(
            "state IN ('PENDING','CLAIMED','SUBMITTED','AWAITING_REVIEW',"
            "'ACCEPTED','FAILED','CANCELLED')",
            name="ck_legacy_item_extraction_batch_work_unit_state",
        ),
        CheckConstraint(
            "execution_mode IN ('EXECUTE','REUSE_ACCEPTED')",
            name="ck_legacy_item_extraction_batch_work_unit_mode",
        ),
        CheckConstraint(
            "ordinal BETWEEN 0 AND 999999 AND submission_attempts BETWEEN 0 AND 1",
            name="ck_legacy_item_extraction_batch_work_unit_bounds",
        ),
        CheckConstraint(
            "request_sha256 ~ '^sha256:[0-9a-f]{64}$' "
            "AND bundle_manifest_sha256 ~ '^sha256:[0-9a-f]{64}$' "
            "AND expected_item_numbers_sha256 ~ '^sha256:[0-9a-f]{64}$' "
            "AND corpus_source_bindings_sha256 ~ '^sha256:[0-9a-f]{64}$'",
            name="ck_legacy_item_extraction_batch_work_unit_hashes",
        ),
        CheckConstraint(
            "(state = 'CLAIMED' AND lease_owner IS NOT NULL AND lease_expires_at IS NOT NULL) OR "
            "(state <> 'CLAIMED' AND lease_owner IS NULL AND lease_expires_at IS NULL)",
            name="ck_legacy_item_extraction_batch_work_unit_lease",
        ),
        CheckConstraint(
            "(execution_mode = 'REUSE_ACCEPTED' AND state = 'ACCEPTED' "
            "AND submission_attempts = 0 AND workflow_id IS NULL "
            "AND acceptance_id IS NOT NULL) OR execution_mode = 'EXECUTE'",
            name="ck_legacy_item_extraction_batch_work_unit_reuse",
        ),
        CheckConstraint(
            "(receipt_artifact_id IS NULL AND receipt_artifact_revision_id IS NULL "
            "AND receipt_artifact_sha256 IS NULL AND extraction_result_id IS NULL "
            "AND result_sha256 IS NULL) OR "
            "(receipt_artifact_id IS NOT NULL AND receipt_artifact_revision_id IS NOT NULL "
            "AND receipt_artifact_sha256 ~ '^sha256:[0-9a-f]{64}$' "
            "AND extraction_result_id IS NOT NULL "
            "AND result_sha256 ~ '^sha256:[0-9a-f]{64}$')",
            name="ck_legacy_item_extraction_batch_work_unit_result_pointer",
        ),
        CheckConstraint(
            "state NOT IN ('AWAITING_REVIEW','ACCEPTED') OR extraction_result_id IS NOT NULL",
            name="ck_legacy_item_extraction_batch_work_unit_result_state",
        ),
        CheckConstraint(
            "state <> 'ACCEPTED' OR acceptance_id IS NOT NULL",
            name="ck_legacy_item_extraction_batch_work_unit_acceptance_state",
        ),
        CheckConstraint(
            "(acceptance_id IS NULL AND acceptance_sha256 IS NULL) OR "
            "(acceptance_id IS NOT NULL AND acceptance_sha256 ~ '^sha256:[0-9a-f]{64}$')",
            name="ck_legacy_item_extraction_batch_work_unit_acceptance_pointer",
        ),
        CheckConstraint(
            "(state = 'FAILED' AND error_code IS NOT NULL) OR "
            "(state <> 'FAILED' AND error_code IS NULL)",
            name="ck_legacy_item_extraction_batch_work_unit_error",
        ),
        CheckConstraint(
            "resource_version >= 1", name="ck_legacy_item_extraction_work_unit_version"
        ),
        ForeignKeyConstraint(
            ("receipt_artifact_id", "receipt_artifact_revision_id"),
            ("artifact_revisions.logical_artifact_id", "artifact_revisions.revision_id"),
            name="fk_legacy_item_extraction_batch_receipt_identity",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "extraction_batch_id",
            "ordinal",
            name="uq_legacy_item_extraction_batch_work_unit_ordinal",
        ),
        UniqueConstraint(
            "extraction_batch_id",
            "work_unit_id",
            name="uq_legacy_item_extraction_batch_work_unit_identity",
        ),
        UniqueConstraint(
            "extraction_batch_id",
            "assessment_source_bundle_revision_id",
            "ordinal",
            "expected_item_numbers_sha256",
            name="uq_legacy_item_extraction_batch_work_unit_source",
        ),
        Index(
            "ix_legacy_item_extraction_batch_work_unit_claim",
            "state",
            "next_action_at",
            "extraction_batch_id",
            "ordinal",
            postgresql_where=text("state IN ('PENDING','CLAIMED','SUBMITTED')"),
        ),
        Index(
            "uq_legacy_item_extraction_batch_work_unit_workflow",
            "workflow_id",
            unique=True,
            postgresql_where=text("workflow_id IS NOT NULL"),
        ),
    )

    work_unit_id: Mapped[str] = mapped_column(String(47), primary_key=True)
    extraction_batch_id: Mapped[str] = mapped_column(
        ForeignKey("legacy_item_extraction_batches.extraction_batch_id", ondelete="CASCADE"),
        nullable=False,
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    extraction_request_id: Mapped[str] = mapped_column(String(47), nullable=False, unique=True)
    request_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    assessment_source_bundle_id: Mapped[str] = mapped_column(String(45), nullable=False)
    assessment_source_bundle_revision_id: Mapped[str] = mapped_column(String(48), nullable=False)
    bundle_manifest_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    expected_item_numbers_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    corpus_source_bindings_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    execution_mode: Mapped[str] = mapped_column(String(24), nullable=False)
    state: Mapped[str] = mapped_column(String(24), nullable=False)
    submission_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    lease_owner: Mapped[str | None] = mapped_column(String(128))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_action_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    workflow_id: Mapped[str | None] = mapped_column(
        ForeignKey("workflow_instances.workflow_id", ondelete="RESTRICT")
    )
    platform_job_id: Mapped[str | None] = mapped_column(
        ForeignKey("jobs.job_id", ondelete="RESTRICT")
    )
    receipt_artifact_id: Mapped[str | None] = mapped_column(String(41))
    receipt_artifact_revision_id: Mapped[str | None] = mapped_column(String(36))
    receipt_artifact_sha256: Mapped[str | None] = mapped_column(String(71))
    extraction_result_id: Mapped[str | None] = mapped_column(String(50))
    result_sha256: Mapped[str | None] = mapped_column(String(71))
    acceptance_id: Mapped[str | None] = mapped_column(
        ForeignKey("legacy_item_extraction_acceptances.acceptance_id", ondelete="RESTRICT")
    )
    acceptance_sha256: Mapped[str | None] = mapped_column(String(71))
    error_code: Mapped[str | None] = mapped_column(String(96))
    resource_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class LegacyItemExtractionBatchEventRecord(Base):
    """Append-only transition evidence for one extraction batch."""

    __tablename__ = "legacy_item_extraction_batch_events"
    __table_args__ = (
        CheckConstraint("sequence >= 1", name="ck_legacy_item_extraction_batch_event_sequence"),
        ForeignKeyConstraint(
            ("extraction_batch_id", "work_unit_id"),
            (
                "legacy_item_extraction_batch_work_units.extraction_batch_id",
                "legacy_item_extraction_batch_work_units.work_unit_id",
            ),
            name="fk_legacy_item_extraction_batch_event_work_unit",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "extraction_batch_id",
            "sequence",
            name="uq_legacy_item_extraction_batch_event_sequence",
        ),
        Index("ix_legacy_item_extraction_batch_event_work_unit", "work_unit_id", "event_id"),
    )

    event_id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    extraction_batch_id: Mapped[str] = mapped_column(
        ForeignKey("legacy_item_extraction_batches.extraction_batch_id", ondelete="CASCADE"),
        nullable=False,
    )
    work_unit_id: Mapped[str | None] = mapped_column(String(47))
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    prior_state: Mapped[str | None] = mapped_column(String(32))
    new_state: Mapped[str] = mapped_column(String(32), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
