"""Persistence records for durable, pointer-only Knowledge Analysis batches."""

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
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column


class KnowledgeAnalysisBatchRecord(Base):
    """One fresh-authorized immutable batch manifest and its lifecycle."""

    __tablename__ = "knowledge_analysis_batches"
    __table_args__ = (
        CheckConstraint(
            "state IN ('QUEUED','RUNNING','BLOCKED','SUCCEEDED','CANCELLED')",
            name="ck_knowledge_analysis_batch_state",
        ),
        CheckConstraint(
            "request_sha256 ~ '^sha256:[0-9a-f]{64}$' "
            "AND preset_sha256 ~ '^sha256:[0-9a-f]{64}$' "
            "AND risk_policy_sha256 ~ '^sha256:[0-9a-f]{64}$'",
            name="ck_knowledge_analysis_batch_hashes",
        ),
        CheckConstraint(
            "general_knowledge_mode = 'AUXILIARY_UNATTRIBUTED'",
            name="ck_knowledge_analysis_batch_general_knowledge",
        ),
        CheckConstraint(
            "review_policy = 'PREAUTHORIZED_APPROVE_VALIDATED'",
            name="ck_knowledge_analysis_batch_review_policy",
        ),
        CheckConstraint(
            "range_failure_policy IN ('STOP_ON_FIRST_FAILURE','CONTINUE_AND_COLLECT')",
            name="ck_knowledge_analysis_batch_range_failure_policy",
        ),
        CheckConstraint(
            "(scheduling_mode = 'SERIAL' AND max_in_flight = 1) OR "
            "(scheduling_mode = 'BOUNDED_PARALLEL' AND max_in_flight = 2 "
            "AND range_failure_policy = 'CONTINUE_AND_COLLECT')",
            name="ck_knowledge_analysis_batch_scheduling",
        ),
        CheckConstraint(
            "total_range_count BETWEEN 1 AND 1000",
            name="ck_knowledge_analysis_batch_range_count",
        ),
        CheckConstraint("resource_version >= 1", name="ck_knowledge_analysis_batch_version"),
        UniqueConstraint("idempotency_key", name="uq_knowledge_analysis_batch_idempotency"),
        Index(
            "ix_knowledge_analysis_batch_state_created",
            "state",
            text("created_at DESC"),
            "batch_id",
        ),
    )

    batch_id: Mapped[str] = mapped_column(String(46), primary_key=True)
    request_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    preset_id: Mapped[str] = mapped_column(
        ForeignKey("execution_presets.preset_id", ondelete="RESTRICT"), nullable=False
    )
    preset_revision_id: Mapped[str] = mapped_column(
        ForeignKey("execution_preset_revisions.preset_revision_id", ondelete="RESTRICT"),
        nullable=False,
    )
    preset_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    risk_policy_revision_id: Mapped[str] = mapped_column(
        ForeignKey(
            "knowledge_analysis_risk_policy_revisions.risk_policy_revision_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    risk_policy_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    general_knowledge_mode: Mapped[str] = mapped_column(String(32), nullable=False)
    review_policy: Mapped[str] = mapped_column(String(48), nullable=False)
    range_failure_policy: Mapped[str] = mapped_column(
        String(32), nullable=False, default="STOP_ON_FIRST_FAILURE"
    )
    scheduling_mode: Mapped[str] = mapped_column(String(24), nullable=False, default="SERIAL")
    max_in_flight: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    authorized_by_operator_id: Mapped[str] = mapped_column(
        ForeignKey("operators.operator_id", ondelete="RESTRICT"), nullable=False
    )
    authorized_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    total_range_count: Mapped[int] = mapped_column(Integer, nullable=False)
    failure_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    resource_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class KnowledgeAnalysisBatchRangeRecord(Base):
    """One ordered range with exact source dependencies and one analysis pointer."""

    __tablename__ = "knowledge_analysis_batch_ranges"
    __table_args__ = (
        CheckConstraint(
            "state IN ('PENDING','CLAIMED','SUBMITTED','ACCEPTED','FAILED','CANCELLED')",
            name="ck_knowledge_analysis_batch_range_state",
        ),
        CheckConstraint(
            "execution_mode IN ('EXECUTE','REUSE_ACCEPTED')",
            name="ck_knowledge_analysis_batch_range_mode",
        ),
        CheckConstraint(
            "ordinal BETWEEN 0 AND 999 AND first_physical_page >= 1 "
            "AND last_physical_page >= first_physical_page "
            "AND last_physical_page - first_physical_page + 1 <= 32",
            name="ck_knowledge_analysis_batch_range_bounds",
        ),
        CheckConstraint(
            "source_sha256 ~ '^sha256:[0-9a-f]{64}$' "
            "AND analysis_manifest_sha256 ~ '^sha256:[0-9a-f]{64}$' "
            "AND rights_attestation_sha256 ~ '^sha256:[0-9a-f]{64}$'",
            name="ck_knowledge_analysis_batch_range_hashes",
        ),
        CheckConstraint(
            "source_media_type = 'application/pdf' AND "
            "source_schema_ref = 'eom://schemas/educational-document/pdf-source/1.0' AND "
            "analysis_media_type = 'application/json' AND "
            "analysis_schema_ref IN ("
            "'eom://schemas/legacy-knowledge/textbook-analysis-bundle-manifest/1.0',"
            "'eom://schemas/legacy-knowledge/textbook-analysis-bundle-manifest/2.0') AND "
            "rights_media_type = 'application/json' AND "
            "rights_schema_ref = "
            "'eom://schemas/educational-document/rights-attestation/1.0'",
            name="ck_knowledge_analysis_batch_range_pointer_contract",
        ),
        CheckConstraint(
            "(execution_mode = 'EXECUTE' AND reuse_accepted_analysis_run_id IS NULL) OR "
            "(execution_mode = 'REUSE_ACCEPTED' "
            "AND predecessor_analysis_run_id IS NULL "
            "AND reuse_accepted_analysis_run_id IS NOT NULL "
            "AND analysis_run_id = reuse_accepted_analysis_run_id "
            "AND state = 'ACCEPTED' AND submission_attempts = 0)",
            name="ck_knowledge_analysis_batch_range_execution",
        ),
        CheckConstraint(
            "(state = 'CLAIMED' AND lease_owner IS NOT NULL AND lease_expires_at IS NOT NULL) "
            "OR (state <> 'CLAIMED' AND lease_owner IS NULL AND lease_expires_at IS NULL)",
            name="ck_knowledge_analysis_batch_range_lease",
        ),
        CheckConstraint(
            "state NOT IN ('SUBMITTED','ACCEPTED') OR analysis_run_id IS NOT NULL",
            name="ck_knowledge_analysis_batch_range_run_pointer",
        ),
        CheckConstraint(
            "submission_attempts BETWEEN 0 AND 1",
            name="ck_knowledge_analysis_batch_range_attempts",
        ),
        CheckConstraint("resource_version >= 1", name="ck_knowledge_analysis_batch_range_version"),
        ForeignKeyConstraint(
            ("document_id", "document_revision_id"),
            (
                "educational_document_revisions.document_id",
                "educational_document_revisions.document_revision_id",
            ),
            name="fk_knowledge_analysis_batch_range_document_revision",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("batch_id", "ordinal", name="uq_knowledge_analysis_batch_range_ordinal"),
        UniqueConstraint("batch_id", "range_id", name="uq_knowledge_analysis_batch_range_identity"),
        Index(
            "ix_knowledge_analysis_batch_active_range",
            "batch_id",
            "state",
            "ordinal",
            postgresql_where=text("state IN ('CLAIMED','SUBMITTED')"),
        ),
        Index(
            "uq_knowledge_analysis_batch_analysis_run",
            "batch_id",
            "analysis_run_id",
            unique=True,
            postgresql_where=text("analysis_run_id IS NOT NULL"),
        ),
        Index(
            "ix_knowledge_analysis_batch_range_claim",
            "state",
            "next_action_at",
            "batch_id",
            "ordinal",
            postgresql_where=text("state IN ('PENDING','CLAIMED','SUBMITTED')"),
        ),
        Index(
            "ix_knowledge_analysis_batch_range_document_pages",
            "document_revision_id",
            "first_physical_page",
            "last_physical_page",
        ),
    )

    range_id: Mapped[str] = mapped_column(String(46), primary_key=True)
    batch_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_analysis_batches.batch_id", ondelete="CASCADE"), nullable=False
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    document_id: Mapped[str] = mapped_column(
        ForeignKey("educational_documents.document_id", ondelete="RESTRICT"), nullable=False
    )
    document_revision_id: Mapped[str] = mapped_column(String(42), nullable=False)
    first_physical_page: Mapped[int] = mapped_column(Integer, nullable=False)
    last_physical_page: Mapped[int] = mapped_column(Integer, nullable=False)
    curriculum_unit_keys: Mapped[list[str]] = mapped_column(ARRAY(String(16)), nullable=False)
    source_artifact_id: Mapped[str] = mapped_column(
        ForeignKey("artifacts.logical_artifact_id", ondelete="RESTRICT"), nullable=False
    )
    source_artifact_revision_id: Mapped[str] = mapped_column(
        ForeignKey("artifact_revisions.revision_id", ondelete="RESTRICT"), nullable=False
    )
    source_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    source_media_type: Mapped[str] = mapped_column(String(64), nullable=False)
    source_schema_ref: Mapped[str] = mapped_column(String(256), nullable=False)
    analysis_artifact_id: Mapped[str] = mapped_column(
        ForeignKey("artifacts.logical_artifact_id", ondelete="RESTRICT"), nullable=False
    )
    analysis_artifact_revision_id: Mapped[str] = mapped_column(
        ForeignKey("artifact_revisions.revision_id", ondelete="RESTRICT"), nullable=False
    )
    analysis_manifest_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    analysis_media_type: Mapped[str] = mapped_column(String(64), nullable=False)
    analysis_schema_ref: Mapped[str] = mapped_column(String(256), nullable=False)
    rights_artifact_id: Mapped[str] = mapped_column(
        ForeignKey("artifacts.logical_artifact_id", ondelete="RESTRICT"), nullable=False
    )
    rights_artifact_revision_id: Mapped[str] = mapped_column(
        ForeignKey("artifact_revisions.revision_id", ondelete="RESTRICT"), nullable=False
    )
    rights_attestation_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    rights_media_type: Mapped[str] = mapped_column(String(64), nullable=False)
    rights_schema_ref: Mapped[str] = mapped_column(String(256), nullable=False)
    execution_mode: Mapped[str] = mapped_column(String(24), nullable=False)
    predecessor_analysis_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("knowledge_analysis_runs.analysis_run_id", ondelete="RESTRICT"), nullable=True
    )
    reuse_accepted_analysis_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("knowledge_analysis_runs.analysis_run_id", ondelete="RESTRICT"), nullable=True
    )
    analysis_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("knowledge_analysis_runs.analysis_run_id", ondelete="RESTRICT"), nullable=True
    )
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    submission_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    lease_owner: Mapped[str | None] = mapped_column(String(128), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    next_action_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    resource_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class KnowledgeAnalysisBatchEventRecord(Base):
    """Append-only bounded state evidence for a batch aggregate."""

    __tablename__ = "knowledge_analysis_batch_events"
    __table_args__ = (
        CheckConstraint("sequence >= 1", name="ck_knowledge_analysis_batch_event_sequence"),
        ForeignKeyConstraint(
            ("batch_id", "range_id"),
            (
                "knowledge_analysis_batch_ranges.batch_id",
                "knowledge_analysis_batch_ranges.range_id",
            ),
            name="fk_knowledge_analysis_batch_event_range",
            ondelete="CASCADE",
        ),
        UniqueConstraint("batch_id", "sequence", name="uq_knowledge_analysis_batch_event_sequence"),
        Index("ix_knowledge_analysis_batch_event_range", "range_id", "event_id"),
    )

    event_id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    batch_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_analysis_batches.batch_id", ondelete="CASCADE"), nullable=False
    )
    range_id: Mapped[str | None] = mapped_column(String(46), nullable=True)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    prior_state: Mapped[str | None] = mapped_column(String(16), nullable=True)
    new_state: Mapped[str] = mapped_column(String(16), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
