"""Indexed delivery state for saved mixed-source assemblies, never Item payloads."""

from datetime import datetime
from typing import Any

from eom_orchestrator.models import Base
from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column


class HwpxCuratedBuildRecord(Base):
    __tablename__ = "hwpx_curated_builds"
    __table_args__ = (
        ForeignKeyConstraint(
            ["assembly_id", "assembly_revision_id"],
            [
                "curated_document_assembly_revisions.assembly_id",
                "curated_document_assembly_revisions.assembly_revision_id",
            ],
            name="fk_hwpx_curated_assembly_revision",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "created_by_operator_id", "idempotency_key", name="uq_hwpx_curated_operator_key"
        ),
        CheckConstraint(
            "state IN ('REQUESTED','RUNNING','VALIDATING','SUCCEEDED','FAILED')",
            name="ck_hwpx_curated_state",
        ),
        CheckConstraint(
            "validation_state IN ('PENDING','PASS','FAIL')", name="ck_hwpx_curated_validation"
        ),
        CheckConstraint(
            "placement_count BETWEEN 1 AND 200 AND resource_version > 0",
            name="ck_hwpx_curated_count",
        ),
        CheckConstraint(
            "assembly_manifest_sha256 ~ '^sha256:[0-9a-f]{64}$' AND "
            "request_sha256 ~ '^sha256:[0-9a-f]{64}$' AND "
            "input_plan_sha256 ~ '^sha256:[0-9a-f]{64}$'",
            name="ck_hwpx_curated_input_hashes",
        ),
        CheckConstraint(
            "jsonb_typeof(input_plan) = 'object' AND "
            "octet_length(input_plan::text) <= 524288 AND "
            "jsonb_typeof(initiator_context) = 'object' AND "
            "octet_length(initiator_context::text) <= 4096",
            name="ck_hwpx_curated_metadata_budget",
        ),
        CheckConstraint(
            "((state IN ('REQUESTED','RUNNING','VALIDATING') AND validation_state='PENDING' "
            "AND completed_at IS NULL AND output_artifact_id IS NULL "
            "AND output_artifact_revision_id IS NULL AND output_sha256 IS NULL "
            "AND failure_code IS NULL) OR "
            "(state='SUCCEEDED' AND validation_state='PASS' AND completed_at IS NOT NULL "
            "AND started_at IS NOT NULL AND platform_job_id IS NOT NULL "
            "AND section_count >= placement_count AND binary_count >= 0 "
            "AND native_table_count >= 0 AND native_equation_count >= 0 "
            "AND output_artifact_id=planned_artifact_id "
            "AND output_artifact_revision_id=planned_artifact_revision_id "
            "AND output_sha256 ~ '^sha256:[0-9a-f]{64}$' "
            "AND output_size_bytes BETWEEN 1 AND 268435456 AND failure_code IS NULL) OR "
            "(state='FAILED' AND validation_state='FAIL' AND completed_at IS NOT NULL "
            "AND failure_code IS NOT NULL AND output_artifact_id IS NULL "
            "AND output_artifact_revision_id IS NULL AND output_sha256 IS NULL)) IS TRUE",
            name="ck_hwpx_curated_terminal_evidence",
        ),
        Index("ix_hwpx_curated_revision_history", "assembly_revision_id", "created_at", "build_id"),
        Index("ix_hwpx_curated_owner_recent", "created_by_operator_id", "created_at", "build_id"),
        Index(
            "ix_hwpx_curated_requested_fifo",
            "created_at",
            "build_id",
            postgresql_where=text("state = 'REQUESTED'"),
        ),
        Index(
            "ix_hwpx_curated_recovery",
            "started_at",
            "build_id",
            postgresql_where=text("state IN ('RUNNING','VALIDATING')"),
        ),
    )

    build_id: Mapped[str] = mapped_column(String(42), primary_key=True)
    assembly_id: Mapped[str] = mapped_column(String(41), nullable=False)
    assembly_revision_id: Mapped[str] = mapped_column(String(44), nullable=False)
    assembly_manifest_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    input_plan: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    initiator_context: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    input_plan_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    request_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    created_by_operator_id: Mapped[str] = mapped_column(
        ForeignKey("operators.operator_id", ondelete="RESTRICT"),
        nullable=False,
    )
    # Planned identities are persisted before dispatch, but are not dangling FKs:
    # the actual output FKs are populated only after the Artifact owner commits.
    planned_artifact_id: Mapped[str] = mapped_column(String(41), nullable=False, unique=True)
    planned_artifact_revision_id: Mapped[str] = mapped_column(
        String(36), nullable=False, unique=True
    )
    planned_job_id: Mapped[str] = mapped_column(String(37), nullable=False, unique=True)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    validation_state: Mapped[str] = mapped_column(String(8), nullable=False)
    placement_count: Mapped[int] = mapped_column(Integer, nullable=False)
    section_count: Mapped[int | None] = mapped_column(Integer)
    binary_count: Mapped[int | None] = mapped_column(Integer)
    native_table_count: Mapped[int | None] = mapped_column(Integer)
    native_equation_count: Mapped[int | None] = mapped_column(Integer)
    platform_job_id: Mapped[str | None] = mapped_column(ForeignKey("jobs.job_id"), unique=True)
    output_artifact_id: Mapped[str | None] = mapped_column(
        ForeignKey("artifacts.logical_artifact_id")
    )
    output_artifact_revision_id: Mapped[str | None] = mapped_column(
        ForeignKey("artifact_revisions.revision_id")
    )
    output_sha256: Mapped[str | None] = mapped_column(String(71))
    output_size_bytes: Mapped[int | None] = mapped_column(Integer)
    output_filename: Mapped[str] = mapped_column(String(160), nullable=False)
    failure_code: Mapped[str | None] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resource_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
