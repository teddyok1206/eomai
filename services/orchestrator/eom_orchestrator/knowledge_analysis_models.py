"""Persistence records for knowledge-analysis execution and immutable review provenance."""

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


class KnowledgeAnalysisRiskPolicyRevisionRecord(Base):
    __tablename__ = "knowledge_analysis_risk_policy_revisions"
    __table_args__ = (
        CheckConstraint("state = 'RELEASED'", name="ck_knowledge_analysis_risk_policy_state"),
        CheckConstraint(
            "content_sha256 ~ '^sha256:[0-9a-f]{64}$'",
            name="ck_knowledge_analysis_risk_policy_hash",
        ),
    )

    risk_policy_revision_id: Mapped[str] = mapped_column(String(48), primary_key=True)
    schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(71), nullable=False, unique=True)
    canonical_document: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_by: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class KnowledgeAnalysisRunRecord(Base):
    __tablename__ = "knowledge_analysis_runs"
    __table_args__ = (
        CheckConstraint(
            "state IN ('REQUESTED','RESOLVED','QUEUED','RUNNING','VALIDATING',"
            "'NEEDS_REVIEW','ACCEPTED','REJECTED','FAILED','CANCELLED')",
            name="ck_knowledge_analysis_run_state",
        ),
        CheckConstraint(
            "source_kind IN ('CONTENT_INTAKE_FILE','APPROVED_ITEM_REVISION','DOCUMENT_REVISION')",
            name="ck_knowledge_analysis_source_kind",
        ),
        CheckConstraint(
            "request_sha256 ~ '^sha256:[0-9a-f]{64}$'",
            name="ck_knowledge_analysis_request_hash",
        ),
        CheckConstraint(
            "submission_sha256 ~ '^sha256:[0-9a-f]{64}$'",
            name="ck_knowledge_analysis_submission_hash",
        ),
        CheckConstraint(
            "source_sha256 ~ '^sha256:[0-9a-f]{64}$' "
            "AND risk_policy_sha256 ~ '^sha256:[0-9a-f]{64}$'",
            name="ck_knowledge_analysis_dependency_hashes",
        ),
        CheckConstraint(
            "(source_kind = 'CONTENT_INTAKE_FILE' AND source_file_id IS NOT NULL "
            "AND item_id IS NULL AND item_revision_id IS NULL "
            "AND educational_document_id IS NULL AND educational_document_revision_id IS NULL) OR "
            "(source_kind = 'APPROVED_ITEM_REVISION' AND source_file_id IS NULL "
            "AND item_id IS NOT NULL AND item_revision_id IS NOT NULL "
            "AND educational_document_id IS NULL AND educational_document_revision_id IS NULL) OR "
            "(source_kind = 'DOCUMENT_REVISION' AND source_file_id IS NULL "
            "AND item_id IS NULL AND item_revision_id IS NULL "
            "AND educational_document_id IS NOT NULL "
            "AND educational_document_revision_id IS NOT NULL)",
            name="ck_knowledge_analysis_source_pointer_family",
        ),
        ForeignKeyConstraint(
            ("educational_document_id", "educational_document_revision_id"),
            (
                "educational_document_revisions.document_id",
                "educational_document_revisions.document_revision_id",
            ),
            name="fk_knowledge_analysis_educational_document_revision_identity",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "(proposal_artifact_id IS NULL AND proposal_artifact_revision_id IS NULL "
            "AND proposal_content_set_sha256 IS NULL) OR "
            "(proposal_artifact_id IS NOT NULL AND proposal_artifact_revision_id IS NOT NULL "
            "AND proposal_content_set_sha256 ~ '^sha256:[0-9a-f]{64}$')",
            name="ck_knowledge_analysis_proposal_pointer_complete",
        ),
        CheckConstraint(
            "(accepted_result_artifact_id IS NULL "
            "AND accepted_result_artifact_revision_id IS NULL AND accepted_result_sha256 IS NULL) "
            "OR (accepted_result_artifact_id IS NOT NULL "
            "AND accepted_result_artifact_revision_id IS NOT NULL "
            "AND accepted_result_sha256 ~ '^sha256:[0-9a-f]{64}$')",
            name="ck_knowledge_analysis_result_pointer_complete",
        ),
        CheckConstraint(
            "state <> 'ACCEPTED' OR accepted_result_artifact_revision_id IS NOT NULL",
            name="ck_knowledge_analysis_accepted_has_result",
        ),
        CheckConstraint(
            "state = 'ACCEPTED' OR accepted_result_artifact_revision_id IS NULL",
            name="ck_knowledge_analysis_result_only_when_accepted",
        ),
        CheckConstraint("lock_version >= 1", name="ck_knowledge_analysis_lock_version"),
        CheckConstraint(
            "predecessor_analysis_run_id IS NULL OR predecessor_analysis_run_id <> analysis_run_id",
            name="ck_knowledge_analysis_predecessor_not_self",
        ),
        UniqueConstraint("analysis_request_id", name="uq_knowledge_analysis_request"),
        UniqueConstraint("idempotency_key", name="uq_knowledge_analysis_idempotency"),
        UniqueConstraint("workflow_id", name="uq_knowledge_analysis_workflow"),
        Index(
            "ix_knowledge_analysis_source_history",
            "source_kind",
            "source_revision_id",
            text("created_at DESC"),
        ),
        Index(
            "ix_knowledge_analysis_intake_file",
            "source_file_id",
            "created_at",
            postgresql_where=text("source_file_id IS NOT NULL"),
        ),
        Index(
            "ix_knowledge_analysis_document_revision",
            "educational_document_revision_id",
            "created_at",
            postgresql_where=text("educational_document_revision_id IS NOT NULL"),
        ),
        Index(
            "ix_knowledge_analysis_runnable",
            "state",
            "created_at",
            "analysis_run_id",
            postgresql_where=text(
                "state IN ('REQUESTED','RESOLVED','QUEUED','RUNNING','VALIDATING')"
            ),
        ),
        Index(
            "ix_knowledge_analysis_created",
            text("created_at DESC"),
            text("analysis_run_id DESC"),
        ),
        Index(
            "ix_knowledge_analysis_state_history",
            "state",
            text("created_at DESC"),
            text("analysis_run_id DESC"),
        ),
    )

    analysis_run_id: Mapped[str] = mapped_column(String(44), primary_key=True)
    analysis_request_id: Mapped[str] = mapped_column(String(50), nullable=False)
    predecessor_analysis_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("knowledge_analysis_runs.analysis_run_id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    request_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    submission_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    canonical_request: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    source_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    source_revision_id: Mapped[str] = mapped_column(String(43), nullable=False)
    source_file_id: Mapped[str | None] = mapped_column(
        ForeignKey("content_intake_source_files.source_file_id", ondelete="RESTRICT"),
        nullable=True,
    )
    item_id: Mapped[str | None] = mapped_column(
        ForeignKey("items.item_id", ondelete="RESTRICT"), nullable=True
    )
    item_revision_id: Mapped[str | None] = mapped_column(
        ForeignKey("item_revisions.item_revision_id", ondelete="RESTRICT"), nullable=True
    )
    educational_document_id: Mapped[str | None] = mapped_column(
        ForeignKey("educational_documents.document_id", ondelete="RESTRICT"), nullable=True
    )
    educational_document_revision_id: Mapped[str | None] = mapped_column(String(42), nullable=True)
    source_artifact_id: Mapped[str] = mapped_column(
        ForeignKey("artifacts.logical_artifact_id", ondelete="RESTRICT"), nullable=False
    )
    source_artifact_revision_id: Mapped[str] = mapped_column(
        ForeignKey("artifact_revisions.revision_id", ondelete="RESTRICT"), nullable=False
    )
    source_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    workflow_id: Mapped[str] = mapped_column(
        ForeignKey("workflow_instances.workflow_id", ondelete="RESTRICT"), nullable=False
    )
    plan_id: Mapped[str] = mapped_column(
        ForeignKey("resolved_execution_plans.plan_id", ondelete="RESTRICT"), nullable=False
    )
    platform_job_id: Mapped[str | None] = mapped_column(
        ForeignKey("jobs.job_id", ondelete="RESTRICT"), nullable=True, index=True
    )
    preset_id: Mapped[str] = mapped_column(
        ForeignKey("execution_presets.preset_id", ondelete="RESTRICT"), nullable=False
    )
    preset_revision_id: Mapped[str] = mapped_column(
        ForeignKey("execution_preset_revisions.preset_revision_id", ondelete="RESTRICT"),
        nullable=False,
    )
    risk_policy_revision_id: Mapped[str] = mapped_column(
        ForeignKey(
            "knowledge_analysis_risk_policy_revisions.risk_policy_revision_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    risk_policy_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    proposal_artifact_id: Mapped[str | None] = mapped_column(
        ForeignKey("artifacts.logical_artifact_id", ondelete="RESTRICT"), nullable=True
    )
    proposal_artifact_revision_id: Mapped[str | None] = mapped_column(
        ForeignKey("artifact_revisions.revision_id", ondelete="RESTRICT"), nullable=True
    )
    proposal_content_set_sha256: Mapped[str | None] = mapped_column(String(71), nullable=True)
    accepted_result_artifact_id: Mapped[str | None] = mapped_column(
        ForeignKey("artifacts.logical_artifact_id", ondelete="RESTRICT"), nullable=True
    )
    accepted_result_artifact_revision_id: Mapped[str | None] = mapped_column(
        ForeignKey("artifact_revisions.revision_id", ondelete="RESTRICT"), nullable=True
    )
    accepted_result_sha256: Mapped[str | None] = mapped_column(String(71), nullable=True)
    state: Mapped[str] = mapped_column(String(24), nullable=False)
    anchor_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    node_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    edge_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    claim_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    component_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ambiguity_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    lock_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_by_operator_id: Mapped[str] = mapped_column(
        ForeignKey("operators.operator_id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)


class KnowledgeAnalysisEventRecord(Base):
    __tablename__ = "knowledge_analysis_events"
    __table_args__ = (
        UniqueConstraint(
            "analysis_run_id", "sequence", name="uq_knowledge_analysis_event_sequence"
        ),
        CheckConstraint("sequence >= 1", name="ck_knowledge_analysis_event_sequence"),
    )

    event_id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    analysis_run_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_analysis_runs.analysis_run_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
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


class KnowledgeAnalysisReviewRecord(Base):
    __tablename__ = "knowledge_analysis_reviews"
    __table_args__ = (
        CheckConstraint(
            "decision IN ('APPROVE','REJECT')", name="ck_knowledge_analysis_review_decision"
        ),
        UniqueConstraint("analysis_run_id", name="uq_knowledge_analysis_review_run"),
        UniqueConstraint(
            "decision_artifact_revision_id", name="uq_knowledge_analysis_review_artifact"
        ),
        UniqueConstraint("idempotency_key", name="uq_knowledge_analysis_review_idempotency"),
        CheckConstraint(
            "submission_sha256 ~ '^sha256:[0-9a-f]{64}$' "
            "AND decision_sha256 ~ '^sha256:[0-9a-f]{64}$' "
            "AND risk_policy_sha256 ~ '^sha256:[0-9a-f]{64}$'",
            name="ck_knowledge_analysis_review_hashes",
        ),
    )

    decision_id: Mapped[str] = mapped_column(String(49), primary_key=True)
    analysis_run_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_analysis_runs.analysis_run_id", ondelete="RESTRICT"),
        nullable=False,
    )
    decision: Mapped[str] = mapped_column(String(16), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    submission_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    decided_by_operator_id: Mapped[str] = mapped_column(
        ForeignKey("operators.operator_id", ondelete="RESTRICT"), nullable=False
    )
    risk_policy_revision_id: Mapped[str] = mapped_column(
        ForeignKey(
            "knowledge_analysis_risk_policy_revisions.risk_policy_revision_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    risk_policy_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    decision_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    decision_artifact_id: Mapped[str] = mapped_column(
        ForeignKey("artifacts.logical_artifact_id", ondelete="RESTRICT"), nullable=False
    )
    decision_artifact_revision_id: Mapped[str] = mapped_column(
        ForeignKey("artifact_revisions.revision_id", ondelete="RESTRICT"), nullable=False
    )
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
