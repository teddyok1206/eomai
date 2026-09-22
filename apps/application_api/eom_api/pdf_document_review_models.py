"""Small API-owned persistence records for PDF review upload coordination."""

from __future__ import annotations

from datetime import datetime

from eom_orchestrator.models import Base
from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
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
