"""SQLAlchemy records for immutable HWPX templates, builds, and validation history."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from eom_orchestrator.models import Base
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship


class HwpxTemplateRecord(Base):
    __tablename__ = "hwpx_templates"

    template_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    logical_name: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    revisions: Mapped[list[HwpxTemplateRevisionRecord]] = relationship(back_populates="template")


class HwpxTemplateRevisionRecord(Base):
    __tablename__ = "hwpx_template_revisions"

    template_revision_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    template_id: Mapped[str] = mapped_column(
        ForeignKey("hwpx_templates.template_id"), nullable=False, index=True
    )
    source_artifact_id: Mapped[str] = mapped_column(
        ForeignKey("artifacts.logical_artifact_id"), nullable=False
    )
    source_artifact_revision_id: Mapped[str] = mapped_column(
        ForeignKey("artifact_revisions.revision_id"), nullable=False
    )
    source_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    binding_manifest_artifact_id: Mapped[str] = mapped_column(
        ForeignKey("artifacts.logical_artifact_id"), nullable=False
    )
    binding_manifest_revision_id: Mapped[str] = mapped_column(
        ForeignKey("artifact_revisions.revision_id"), nullable=False
    )
    binding_manifest_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    owpml_version: Mapped[str] = mapped_column(String(128), nullable=False)
    hancom_version_declared: Mapped[str] = mapped_column(String(128), nullable=False)
    package_profile: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    analysis_summary: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    immutable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    template: Mapped[HwpxTemplateRecord] = relationship(back_populates="revisions")
    builds: Mapped[list[HwpxBuildRecord]] = relationship(back_populates="template_revision")


class HwpxBuildRecord(Base):
    __tablename__ = "hwpx_builds"
    __table_args__ = (
        CheckConstraint(
            "status IN ('CREATED','VALIDATING_INPUT','STAGING','RENDERING','PACKAGING',"
            "'VALIDATING_OUTPUT','COMMITTING','SUCCEEDED','FAILED','PENDING_MANUAL_VALIDATION')",
            name="ck_hwpx_builds_status",
        ),
    )

    build_id: Mapped[str] = mapped_column(String(42), primary_key=True)
    template_revision_id: Mapped[str] = mapped_column(
        ForeignKey("hwpx_template_revisions.template_revision_id"), nullable=False, index=True
    )
    platform_job_id: Mapped[str] = mapped_column(
        ForeignKey("jobs.job_id"), unique=True, nullable=False
    )
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    input_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    input_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    renderer_version: Mapped[str] = mapped_column(String(32), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(160), unique=True, nullable=False)
    workspace_id: Mapped[str] = mapped_column(String(128), nullable=False)
    output_artifact_id: Mapped[str | None] = mapped_column(
        ForeignKey("artifacts.logical_artifact_id"), nullable=True
    )
    output_artifact_revision_id: Mapped[str | None] = mapped_column(
        ForeignKey("artifact_revisions.revision_id"), nullable=True
    )
    output_sha256: Mapped[str | None] = mapped_column(String(71), nullable=True)
    structural_report_artifact_id: Mapped[str | None] = mapped_column(String(41), nullable=True)
    semantic_report_artifact_id: Mapped[str | None] = mapped_column(String(41), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failure_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    sanitized_failure_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    manual_validation_status: Mapped[str] = mapped_column(
        String(40), nullable=False, default="PENDING_MANUAL_ACTION"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    template_revision: Mapped[HwpxTemplateRevisionRecord] = relationship(back_populates="builds")
    validations: Mapped[list[HwpxValidationRunRecord]] = relationship(back_populates="build")


class HwpxValidationRunRecord(Base):
    __tablename__ = "hwpx_validation_runs"
    __table_args__ = (
        CheckConstraint(
            "validation_type IN ('STRUCTURAL','SEMANTIC','MANUAL_HANCOM_OPEN',"
            "'MANUAL_HANCOM_SAVE','RESAVED_SEMANTIC_COMPARE')",
            name="ck_hwpx_validation_type",
        ),
        UniqueConstraint("build_id", "validation_type", name="uq_hwpx_validation_type"),
    )

    validation_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    build_id: Mapped[str] = mapped_column(
        ForeignKey("hwpx_builds.build_id", ondelete="CASCADE"), nullable=False, index=True
    )
    validation_type: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    validator_version: Mapped[str] = mapped_column(String(32), nullable=False)
    report_artifact_id: Mapped[str | None] = mapped_column(
        ForeignKey("artifacts.logical_artifact_id"), nullable=True
    )
    report_artifact_revision_id: Mapped[str | None] = mapped_column(
        ForeignKey("artifact_revisions.revision_id"), nullable=True
    )
    hancom_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    windows_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    performed_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    performed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    build: Mapped[HwpxBuildRecord] = relationship(back_populates="validations")


class HwpxApplicationBuildRecord(Base):
    """Application-facing build metadata containing only immutable artifact pointers."""

    __tablename__ = "hwpx_application_builds"
    __table_args__ = (
        CheckConstraint(
            "state IN ('REQUESTED','RUNNING','VALIDATING','SUCCEEDED','FAILED')",
            name="ck_hwpx_application_builds_state",
        ),
        CheckConstraint(
            "validation_state IN ('PENDING','PASS','FAIL')",
            name="ck_hwpx_application_builds_validation_state",
        ),
        CheckConstraint(
            "(state IN ('REQUESTED','RUNNING','VALIDATING') AND validation_state = 'PENDING') "
            "OR (state = 'SUCCEEDED' AND validation_state = 'PASS' "
            "AND native_equation_count IS NOT NULL AND native_table_count IS NOT NULL "
            "AND output_artifact_id IS NOT NULL AND output_artifact_revision_id IS NOT NULL "
            "AND output_sha256 IS NOT NULL AND output_filename IS NOT NULL) "
            "OR (state = 'FAILED' AND validation_state = 'FAIL' AND failure_code IS NOT NULL)",
            name="ck_hwpx_application_builds_terminal_evidence",
        ),
        UniqueConstraint(
            "created_by_operator_id",
            "idempotency_key",
            name="uq_hwpx_application_builds_operator_idempotency",
        ),
        Index(
            "ix_hwpx_application_builds_item_revision_history",
            "item_revision_id",
            "created_at",
            "build_id",
        ),
        Index("ix_hwpx_application_builds_created", "created_at", "build_id"),
    )

    build_id: Mapped[str] = mapped_column(String(42), primary_key=True)
    item_id: Mapped[str] = mapped_column(ForeignKey("items.item_id"), nullable=False, index=True)
    item_revision_id: Mapped[str] = mapped_column(
        ForeignKey("item_revisions.item_revision_id"), nullable=False
    )
    source_artifact_id: Mapped[str] = mapped_column(
        ForeignKey("artifacts.logical_artifact_id"), nullable=False
    )
    source_artifact_revision_id: Mapped[str] = mapped_column(
        ForeignKey("artifact_revisions.revision_id"), nullable=False
    )
    source_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    source_schema_ref: Mapped[str] = mapped_column(String(256), nullable=False)
    source_media_type: Mapped[str] = mapped_column(String(128), nullable=False)
    renderer: Mapped[str] = mapped_column(String(32), nullable=False)
    renderer_version: Mapped[str] = mapped_column(String(32), nullable=False)
    options: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    request_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)
    created_by_operator_id: Mapped[str] = mapped_column(
        ForeignKey("operators.operator_id"), nullable=False, index=True
    )
    state: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    validation_state: Mapped[str] = mapped_column(String(32), nullable=False)
    native_equation_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    native_table_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    platform_job_id: Mapped[str | None] = mapped_column(
        ForeignKey("jobs.job_id"), nullable=True, unique=True
    )
    output_artifact_id: Mapped[str | None] = mapped_column(
        ForeignKey("artifacts.logical_artifact_id"), nullable=True
    )
    output_artifact_revision_id: Mapped[str | None] = mapped_column(
        ForeignKey("artifact_revisions.revision_id"), nullable=True
    )
    output_sha256: Mapped[str | None] = mapped_column(String(71), nullable=True)
    output_filename: Mapped[str | None] = mapped_column(String(160), nullable=True)
    failure_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    failure_detail_sanitized: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resource_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
