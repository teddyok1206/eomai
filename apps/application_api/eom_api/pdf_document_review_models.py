"""Small API-owned persistence records for document-review coordination."""

from __future__ import annotations

from datetime import datetime

from eom_orchestrator.models import Base
from sqlalchemy import (
    JSON,
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column


class PdfDocumentReviewUploadIntentRecord(Base):
    """Durable coordination state; PDF and page bytes are deliberately absent."""

    __tablename__ = "pdf_document_review_upload_intents"
    __table_args__ = (
        CheckConstraint(
            "state IN ('AWAITING_UPLOAD','PROCESSING','STARTED','FAILED_RETRYABLE','FAILED_FINAL')",
            name="ck_pdf_review_upload_intents_state",
        ),
        CheckConstraint(
            "content_length BETWEEN 8 AND 268435456 AND attempts >= 0 "
            "AND lock_version >= 1 AND (page_count BETWEEN 1 AND 2000 OR page_count IS NULL)",
            name="ck_pdf_review_upload_intents_bounds",
        ),
        CheckConstraint(
            "preset_key IN ('PROBLEM_SET','WEEKLY_WORKBOOK','MOCK_EXAM')",
            name="ck_pdf_review_upload_intents_preset",
        ),
        CheckConstraint(
            "(source_format = 'PDF' AND source_media_type = 'application/pdf') OR "
            "(source_format = 'HWP' AND source_media_type = 'application/vnd.hancom.hwp') OR "
            "(source_format = 'HWPX' AND source_media_type = 'application/vnd.hancom.hwpx')",
            name="ck_pdf_review_upload_intents_source_format",
        ),
        CheckConstraint(
            "(additional_guidance IS NULL AND additional_guidance_sha256 IS NULL) OR "
            "(additional_guidance IS NOT NULL AND additional_guidance_sha256 IS NOT NULL)",
            name="ck_pdf_review_upload_intents_guidance",
        ),
        CheckConstraint(
            "(lease_owner IS NULL AND lease_expires_at IS NULL) OR "
            "(lease_owner IS NOT NULL AND lease_expires_at IS NOT NULL)",
            name="ck_pdf_review_upload_intents_lease",
        ),
        CheckConstraint(
            "(document_id IS NULL AND document_revision_id IS NULL "
            "AND source_artifact_id IS NULL AND source_artifact_revision_id IS NULL "
            "AND source_sha256 IS NULL AND page_count IS NULL) OR "
            "(document_id IS NOT NULL AND document_revision_id IS NOT NULL "
            "AND source_artifact_id IS NOT NULL AND source_artifact_revision_id IS NOT NULL "
            "AND source_sha256 IS NOT NULL AND page_count IS NOT NULL)",
            name="ck_pdf_review_upload_intents_document",
        ),
        CheckConstraint(
            "(state = 'AWAITING_UPLOAD' AND upload_sha256 IS NULL AND workflow_id IS NULL "
            "AND workflow_command_id IS NULL AND failure_code IS NULL AND lease_owner IS NULL "
            "AND attempts = 0) OR "
            "(state = 'PROCESSING' AND upload_sha256 IS NOT NULL AND workflow_id IS NULL "
            "AND workflow_command_id IS NULL AND failure_code IS NULL AND lease_owner IS NOT NULL "
            "AND attempts >= 1) OR "
            "(state = 'STARTED' AND upload_sha256 IS NOT NULL AND workflow_id IS NOT NULL "
            "AND workflow_command_id IS NOT NULL AND failure_code IS NULL AND lease_owner IS NULL "
            "AND document_id IS NOT NULL AND attempts >= 1) OR "
            "(state IN ('FAILED_RETRYABLE','FAILED_FINAL') AND upload_sha256 IS NOT NULL "
            "AND workflow_id IS NULL AND workflow_command_id IS NULL AND failure_code IS NOT NULL "
            "AND lease_owner IS NULL AND attempts >= 1)",
            name="ck_pdf_review_upload_intents_payload",
        ),
        Index(
            "ix_pdf_review_upload_intent_owner",
            "operator_id",
            text("created_at DESC"),
            "upload_intent_id",
        ),
        Index(
            "ix_pdf_review_upload_intent_lease",
            "lease_expires_at",
            postgresql_where=text("state = 'PROCESSING'"),
        ),
    )

    upload_intent_id: Mapped[str] = mapped_column(String(48), primary_key=True)
    operator_id: Mapped[str] = mapped_column(
        ForeignKey("operators.operator_id", ondelete="RESTRICT"), nullable=False
    )
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(240), nullable=False)
    content_length: Mapped[int] = mapped_column(BigInteger, nullable=False)
    preset_key: Mapped[str] = mapped_column(String(32), nullable=False)
    additional_guidance: Mapped[str | None] = mapped_column(Text, nullable=True)
    additional_guidance_sha256: Mapped[str | None] = mapped_column(String(71), nullable=True)
    upload_sha256: Mapped[str | None] = mapped_column(String(71), nullable=True)
    workflow_id: Mapped[str | None] = mapped_column(
        ForeignKey("workflow_instances.workflow_id", ondelete="RESTRICT"),
        nullable=True,
        unique=True,
    )
    workflow_command_id: Mapped[str | None] = mapped_column(String(38), nullable=True)
    document_id: Mapped[str | None] = mapped_column(String(41), nullable=True)
    document_revision_id: Mapped[str | None] = mapped_column(String(44), nullable=True)
    source_artifact_id: Mapped[str | None] = mapped_column(String(41), nullable=True)
    source_artifact_revision_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    source_sha256: Mapped[str | None] = mapped_column(String(71), nullable=True)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    failure_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    lease_owner: Mapped[str | None] = mapped_column(String(128), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    lock_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Migration 0040 adds these fields to the released 0039 table. Keep the authoritative
    # metadata order aligned with PostgreSQL's append-only ADD COLUMN result so disposable
    # migration verification catches real drift rather than declaring an impossible insertion.
    source_format: Mapped[str] = mapped_column(String(8), nullable=False, default="PDF")
    source_media_type: Mapped[str] = mapped_column(
        String(64), nullable=False, default="application/pdf"
    )


class DocumentReviewSetRecord(Base):
    """Small owner/state aggregate for one immutable question/solution pair."""

    __tablename__ = "document_review_sets"
    __table_args__ = (
        CheckConstraint(
            "state IN ('AWAITING_UPLOADS','STARTING','STARTED','FAILED_RETRYABLE','FAILED_FINAL')",
            name="ck_document_review_sets_state",
        ),
        CheckConstraint(
            "preset_key IN ('PROBLEM_SET','WEEKLY_WORKBOOK','MOCK_EXAM') "
            "AND attempts >= 0 AND lock_version >= 1",
            name="ck_document_review_sets_bounds",
        ),
        CheckConstraint(
            "(additional_guidance IS NULL AND additional_guidance_sha256 IS NULL) OR "
            "(additional_guidance IS NOT NULL AND additional_guidance_sha256 IS NOT NULL)",
            name="ck_document_review_sets_guidance",
        ),
        CheckConstraint(
            "(lease_owner IS NULL AND lease_expires_at IS NULL) OR "
            "(lease_owner IS NOT NULL AND lease_expires_at IS NOT NULL)",
            name="ck_document_review_sets_lease",
        ),
        CheckConstraint(
            "(state = 'AWAITING_UPLOADS' AND workflow_id IS NULL AND workflow_command_id IS NULL "
            "AND failure_code IS NULL AND lease_owner IS NULL) OR "
            "(state = 'STARTING' AND workflow_id IS NULL AND workflow_command_id IS NULL "
            "AND failure_code IS NULL AND lease_owner IS NOT NULL AND attempts >= 1) OR "
            "(state = 'STARTED' AND workflow_id IS NOT NULL AND workflow_command_id IS NOT NULL "
            "AND failure_code IS NULL AND lease_owner IS NULL AND attempts >= 1) OR "
            "(state IN ('FAILED_RETRYABLE','FAILED_FINAL') AND workflow_id IS NULL "
            "AND workflow_command_id IS NULL AND failure_code IS NOT NULL "
            "AND lease_owner IS NULL AND attempts >= 1)",
            name="ck_document_review_sets_payload",
        ),
        Index(
            "ix_document_review_set_owner",
            "operator_id",
            text("created_at DESC"),
            "review_set_id",
        ),
        Index(
            "ix_document_review_set_lease",
            "lease_expires_at",
            postgresql_where=text("state = 'STARTING'"),
        ),
    )

    review_set_id: Mapped[str] = mapped_column(String(45), primary_key=True)
    operator_id: Mapped[str] = mapped_column(
        ForeignKey("operators.operator_id", ondelete="RESTRICT"), nullable=False
    )
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    preset_key: Mapped[str] = mapped_column(String(32), nullable=False)
    additional_guidance: Mapped[str | None] = mapped_column(Text, nullable=True)
    additional_guidance_sha256: Mapped[str | None] = mapped_column(String(71), nullable=True)
    workflow_id: Mapped[str | None] = mapped_column(
        ForeignKey("workflow_instances.workflow_id", ondelete="RESTRICT"),
        nullable=True,
        unique=True,
    )
    workflow_command_id: Mapped[str | None] = mapped_column(String(38), nullable=True)
    failure_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    lease_owner: Mapped[str | None] = mapped_column(String(128), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    lock_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class DocumentReviewSetMemberRecord(Base):
    """Bounded pointer cache; source bytes remain only in Catalog Artifact storage."""

    __tablename__ = "document_review_set_members"
    __table_args__ = (
        CheckConstraint(
            "document_role IN ('QUESTION','SOLUTION')",
            name="ck_document_review_set_members_role",
        ),
        CheckConstraint(
            "state IN ('AWAITING_UPLOAD','PROCESSING','COMMITTED','FAILED_RETRYABLE',"
            "'FAILED_FINAL')",
            name="ck_document_review_set_members_state",
        ),
        CheckConstraint(
            "content_length BETWEEN 8 AND 268435456 AND attempts >= 0 AND lock_version >= 1",
            name="ck_document_review_set_members_bounds",
        ),
        CheckConstraint(
            "(source_format = 'PDF' AND source_media_type = 'application/pdf') OR "
            "(source_format = 'HWP' AND source_media_type = 'application/vnd.hancom.hwp') OR "
            "(source_format = 'HWPX' AND source_media_type = 'application/vnd.hancom.hwpx')",
            name="ck_document_review_set_members_source_format",
        ),
        CheckConstraint(
            "(lease_owner IS NULL AND lease_expires_at IS NULL) OR "
            "(lease_owner IS NOT NULL AND lease_expires_at IS NOT NULL)",
            name="ck_document_review_set_members_lease",
        ),
        CheckConstraint(
            "(document_id IS NULL AND document_revision_id IS NULL "
            "AND source_artifact_id IS NULL AND source_artifact_revision_id IS NULL "
            "AND source_pdf_sha256 IS NULL AND page_count IS NULL "
            "AND review_document_pointer IS NULL) OR "
            "(document_id IS NOT NULL AND document_revision_id IS NOT NULL "
            "AND source_artifact_id IS NOT NULL AND source_artifact_revision_id IS NOT NULL "
            "AND source_pdf_sha256 IS NOT NULL AND page_count IS NOT NULL "
            "AND review_document_pointer IS NOT NULL)",
            name="ck_document_review_set_members_document",
        ),
        CheckConstraint(
            "(state = 'AWAITING_UPLOAD' AND upload_sha256 IS NULL AND failure_code IS NULL "
            "AND lease_owner IS NULL AND attempts = 0 AND document_id IS NULL) OR "
            "(state = 'PROCESSING' AND upload_sha256 IS NOT NULL AND failure_code IS NULL "
            "AND lease_owner IS NOT NULL AND attempts >= 1 AND document_id IS NULL) OR "
            "(state = 'COMMITTED' AND upload_sha256 IS NOT NULL AND failure_code IS NULL "
            "AND lease_owner IS NULL AND attempts >= 1 AND document_id IS NOT NULL) OR "
            "(state IN ('FAILED_RETRYABLE','FAILED_FINAL') AND upload_sha256 IS NOT NULL "
            "AND failure_code IS NOT NULL "
            "AND lease_owner IS NULL AND attempts >= 1)",
            name="ck_document_review_set_members_payload",
        ),
        Index(
            "ix_document_review_set_member_lease",
            "lease_expires_at",
            postgresql_where=text("state = 'PROCESSING'"),
        ),
    )

    review_set_id: Mapped[str] = mapped_column(
        ForeignKey("document_review_sets.review_set_id", ondelete="RESTRICT"),
        primary_key=True,
    )
    document_role: Mapped[str] = mapped_column(String(16), primary_key=True)
    state: Mapped[str] = mapped_column(String(24), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(240), nullable=False)
    source_format: Mapped[str] = mapped_column(String(8), nullable=False)
    source_media_type: Mapped[str] = mapped_column(String(64), nullable=False)
    content_length: Mapped[int] = mapped_column(BigInteger, nullable=False)
    upload_sha256: Mapped[str | None] = mapped_column(String(71), nullable=True)
    document_id: Mapped[str | None] = mapped_column(String(41), nullable=True)
    document_revision_id: Mapped[str | None] = mapped_column(String(44), nullable=True)
    source_artifact_id: Mapped[str | None] = mapped_column(String(41), nullable=True)
    source_artifact_revision_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    source_pdf_sha256: Mapped[str | None] = mapped_column(String(71), nullable=True)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    review_document_pointer: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    failure_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    lease_owner: Mapped[str | None] = mapped_column(String(128), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    lock_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class DocumentReviewHwpxCorrectionRecord(Base):
    """API authorization pointer to one immutable Catalog-owned corrected HWPX."""

    __tablename__ = "document_review_hwpx_corrections"
    __table_args__ = (
        CheckConstraint(
            "output_content_length BETWEEN 1 AND 268435456 AND lock_version >= 1",
            name="ck_document_review_hwpx_corrections_bounds",
        ),
        CheckConstraint(
            "output_member_path = 'corrected/document-review-redline.hwpx' AND "
            "output_media_type = 'application/vnd.hancom.hwpx' AND "
            "output_schema_ref = 'eom://schemas/document-review/corrected-hwpx/1.0'",
            name="ck_document_review_hwpx_corrections_output_contract",
        ),
        Index(
            "ix_document_review_hwpx_correction_owner",
            "operator_id",
            text("created_at DESC"),
            "correction_id",
        ),
        Index(
            "ix_document_review_hwpx_correction_workflow",
            "workflow_id",
            text("created_at DESC"),
            "correction_id",
        ),
    )

    correction_id: Mapped[str] = mapped_column(String(46), primary_key=True)
    operator_id: Mapped[str] = mapped_column(
        ForeignKey("operators.operator_id", ondelete="RESTRICT"), nullable=False
    )
    workflow_id: Mapped[str] = mapped_column(
        ForeignKey("workflow_instances.workflow_id", ondelete="RESTRICT"), nullable=False
    )
    applied_finding_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    finding_set_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    review_result_artifact_id: Mapped[str] = mapped_column(String(41), nullable=False)
    review_result_artifact_revision_id: Mapped[str] = mapped_column(String(36), nullable=False)
    review_result_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    base_hwpx_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    output_artifact_id: Mapped[str] = mapped_column(String(41), nullable=False)
    output_artifact_revision_id: Mapped[str] = mapped_column(String(36), nullable=False)
    output_member_path: Mapped[str] = mapped_column(String(240), nullable=False)
    output_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    output_content_length: Mapped[int] = mapped_column(BigInteger, nullable=False)
    output_media_type: Mapped[str] = mapped_column(String(64), nullable=False)
    output_schema_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    lock_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class DocumentReviewPdfAnnotationRecord(Base):
    """API-owned authorization metadata for one immutable annotated-PDF Artifact."""

    __tablename__ = "document_review_pdf_annotations"
    __table_args__ = (
        UniqueConstraint(
            "operator_id",
            "workflow_id",
            "request_sha256",
            name="uq_document_review_pdf_annotations_request",
        ),
        CheckConstraint(
            "lock_version >= 1",
            name="ck_document_review_pdf_annotations_bounds",
        ),
        Index(
            "ix_document_review_pdf_annotation_owner",
            "operator_id",
            text("created_at DESC"),
            "annotation_id",
        ),
        Index(
            "ix_document_review_pdf_annotation_workflow",
            "workflow_id",
            text("created_at DESC"),
            "annotation_id",
        ),
    )

    annotation_id: Mapped[str] = mapped_column(String(46), primary_key=True)
    operator_id: Mapped[str] = mapped_column(
        ForeignKey("operators.operator_id", ondelete="RESTRICT"), nullable=False
    )
    workflow_id: Mapped[str] = mapped_column(
        ForeignKey("workflow_instances.workflow_id", ondelete="RESTRICT"), nullable=False
    )
    request_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    review_result_artifact_id: Mapped[str] = mapped_column(String(41), nullable=False)
    review_result_artifact_revision_id: Mapped[str] = mapped_column(String(36), nullable=False)
    review_result_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    annotation_set_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    manifest_artifact_id: Mapped[str] = mapped_column(String(41), nullable=False)
    manifest_artifact_revision_id: Mapped[str] = mapped_column(String(36), nullable=False)
    manifest_member_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    manifest_self_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    lock_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class DocumentReviewPdfAnnotationOutputRecord(Base):
    """One role-addressable immutable PDF pointer for an annotation result."""

    __tablename__ = "document_review_pdf_annotation_outputs"
    __table_args__ = (
        CheckConstraint(
            "document_role IN ('DOCUMENT','QUESTION','SOLUTION')",
            name="ck_document_review_pdf_annotation_outputs_role",
        ),
        CheckConstraint(
            "content_length BETWEEN 1 AND 536870912 AND media_type = 'application/pdf' "
            "AND schema_ref = 'eom://schemas/document-review/annotated-pdf/1.0'",
            name="ck_document_review_pdf_annotation_outputs_contract",
        ),
    )

    annotation_id: Mapped[str] = mapped_column(
        ForeignKey("document_review_pdf_annotations.annotation_id", ondelete="RESTRICT"),
        primary_key=True,
    )
    document_role: Mapped[str] = mapped_column(String(16), primary_key=True)
    artifact_id: Mapped[str] = mapped_column(String(41), nullable=False)
    artifact_revision_id: Mapped[str] = mapped_column(String(36), nullable=False)
    member_path: Mapped[str] = mapped_column(String(240), nullable=False)
    sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    content_length: Mapped[int] = mapped_column(BigInteger, nullable=False)
    media_type: Mapped[str] = mapped_column(String(64), nullable=False)
    schema_ref: Mapped[str] = mapped_column(String(160), nullable=False)
