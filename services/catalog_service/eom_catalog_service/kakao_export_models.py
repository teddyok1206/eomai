"""Private PDF build identity, request aliases and terminal-preserving attempts."""

from datetime import datetime

from eom_orchestrator.models import Base
from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column


class KakaoExportRecord(Base):
    __tablename__ = "kakao_exports"
    __table_args__ = (
        ForeignKeyConstraint(
            ["owner_operator_id", "source_binding_id", "packet_id"],
            [
                "kakao_packets.owner_operator_id",
                "kakao_packets.source_binding_id",
                "kakao_packets.packet_id",
            ],
            ondelete="RESTRICT",
            name="fk_kakao_export_packet_owner",
        ),
        ForeignKeyConstraint(
            ["packet_id", "packet_revision_id"],
            ["kakao_packet_revisions.packet_id", "kakao_packet_revisions.packet_revision_id"],
            ondelete="RESTRICT",
            name="fk_kakao_export_packet_revision",
        ),
        ForeignKeyConstraint(
            ["student_id"],
            ["kakao_students.student_id"],
            ondelete="RESTRICT",
            name="fk_kakao_export_student",
        ),
        ForeignKeyConstraint(
            ["export_id", "current_attempt_id", "attempt_number"],
            [
                "kakao_export_attempts.export_id",
                "kakao_export_attempts.attempt_id",
                "kakao_export_attempts.attempt_number",
            ],
            ondelete="RESTRICT",
            name="fk_kakao_export_current_attempt",
            use_alter=True,
            deferrable=True,
            initially="DEFERRED",
        ),
        UniqueConstraint(
            "owner_operator_id", "source_binding_id", "export_id", name="uq_kakao_export_owner"
        ),
        UniqueConstraint("owner_operator_id", "build_sha256", name="uq_kakao_export_build"),
        CheckConstraint(
            "export_id ~ '^kakaoexport_[0-9a-f]{32}$' "
            "AND build_sha256 ~ '^sha256:[0-9a-f]{64}$' "
            "AND subset_sha256 ~ '^sha256:[0-9a-f]{64}$'",
            name="ck_kakao_export_ids",
        ),
        CheckConstraint(
            "mode IN ('DRAFT','FINAL') AND question_count BETWEEN 1 AND 200 "
            "AND jsonb_typeof(profile) = 'object' AND octet_length(profile::text) <= 2048",
            name="ck_kakao_export_input",
        ),
        CheckConstraint(
            "(attempt_number = 0 AND current_attempt_id IS NULL) OR "
            "(attempt_number BETWEEN 1 AND 2147483647 AND current_attempt_id IS NOT NULL)",
            name="ck_kakao_export_attempt_pointer",
        ),
    )
    export_id: Mapped[str] = mapped_column(String(44), primary_key=True)
    owner_operator_id: Mapped[str] = mapped_column(String(41), nullable=False)
    source_binding_id: Mapped[str] = mapped_column(String(45), nullable=False)
    packet_id: Mapped[str] = mapped_column(String(44), nullable=False)
    packet_revision_id: Mapped[str] = mapped_column(String(47), nullable=False)
    student_id: Mapped[str] = mapped_column(String(45), nullable=False)
    build_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    subset_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    profile: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    mode: Mapped[str] = mapped_column(String(8), nullable=False)
    question_count: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    current_attempt_id: Mapped[str | None] = mapped_column(String(45))
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)


class KakaoExportRequestRecord(Base):
    __tablename__ = "kakao_export_requests"
    __table_args__ = (
        ForeignKeyConstraint(
            ["owner_operator_id", "source_binding_id", "export_id"],
            [
                "kakao_exports.owner_operator_id",
                "kakao_exports.source_binding_id",
                "kakao_exports.export_id",
            ],
            name="fk_kakao_export_request_owner",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "request_sha256 ~ '^sha256:[0-9a-f]{64}$' AND idempotency_key ~ '^[!-~]{16,128}$'",
            name="ck_kakao_export_request",
        ),
    )
    owner_operator_id: Mapped[str] = mapped_column(String(41), primary_key=True)
    source_binding_id: Mapped[str] = mapped_column(String(45), primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), primary_key=True)
    request_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    export_id: Mapped[str] = mapped_column(String(44), nullable=False)


class KakaoExportAttemptRecord(Base):
    __tablename__ = "kakao_export_attempts"
    __table_args__ = (
        ForeignKeyConstraint(
            ["export_id"],
            ["kakao_exports.export_id"],
            name="fk_kakao_export_attempt_parent",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["export_id", "previous_attempt_id"],
            ["kakao_export_attempts.export_id", "kakao_export_attempts.attempt_id"],
            name="fk_kakao_export_attempt_previous",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["artifact_id", "artifact_revision_id"],
            ["artifact_revisions.logical_artifact_id", "artifact_revisions.revision_id"],
            name="fk_kakao_export_output",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["publication_job_id"],
            ["jobs.job_id"],
            name="fk_kakao_export_publication",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("export_id", "attempt_id", name="uq_kakao_export_attempt"),
        UniqueConstraint("export_id", "attempt_number", name="uq_kakao_export_attempt_number"),
        UniqueConstraint(
            "export_id", "attempt_id", "attempt_number", name="uq_kakao_export_attempt_current"
        ),
        UniqueConstraint("export_revision_id", name="uq_kakao_export_output_revision"),
        CheckConstraint(
            "attempt_id ~ '^kakaoattempt_[0-9a-f]{32}$' "
            "AND command_id ~ '^kakaocommand_[0-9a-f]{32}$' "
            "AND task_id ~ '^kakaotask_[0-9a-f]{32}$'",
            name="ck_kakao_export_attempt_ids",
        ),
        CheckConstraint(
            "(attempt_number = 1 AND previous_attempt_id IS NULL) OR "
            "(attempt_number BETWEEN 2 AND 2147483647 AND previous_attempt_id IS NOT NULL "
            "AND previous_attempt_id <> attempt_id)",
            name="ck_kakao_export_attempt_lineage",
        ),
        CheckConstraint(
            "command IS NULL OR (jsonb_typeof(command) = 'object' "
            "AND octet_length(command::text) <= 8192)",
            name="ck_kakao_export_attempt_command",
        ),
        CheckConstraint(
            "(state = 'RUNNING' AND completed_at IS NULL AND error_code IS NULL) OR "
            "(state = 'COMPLETED' AND completed_at IS NOT NULL AND completed_at >= started_at "
            "AND command IS NOT NULL AND error_code IS NULL) OR "
            "(state IN ('FAILED','NEEDS_LAYOUT_REVIEW') AND completed_at IS NOT NULL "
            "AND completed_at >= started_at AND error_code IS NOT NULL "
            "AND error_code ~ '^[A-Z][A-Z0-9_]{2,79}$')",
            name="ck_kakao_export_attempt_state",
        ),
        CheckConstraint(
            "(state = 'COMPLETED' AND export_revision_id IS NOT NULL AND artifact_id IS NOT NULL "
            "AND artifact_revision_id IS NOT NULL AND pdf_sha256 IS NOT NULL "
            "AND layout_sha256 IS NOT NULL AND publication_job_id IS NOT NULL "
            "AND page_count BETWEEN 1 AND 200) OR (state <> 'COMPLETED' "
            "AND export_revision_id IS NULL AND artifact_id IS NULL "
            "AND artifact_revision_id IS NULL AND pdf_sha256 IS NULL AND layout_sha256 IS NULL "
            "AND publication_job_id IS NULL AND page_count = 0)",
            name="ck_kakao_export_attempt_output",
        ),
        CheckConstraint(
            "(export_revision_id IS NULL OR export_revision_id ~ '^kakaoexportrev_[0-9a-f]{32}$') "
            "AND (pdf_sha256 IS NULL OR pdf_sha256 ~ '^sha256:[0-9a-f]{64}$') "
            "AND (layout_sha256 IS NULL OR layout_sha256 ~ '^sha256:[0-9a-f]{64}$')",
            name="ck_kakao_export_output_ids",
        ),
    )
    attempt_id: Mapped[str] = mapped_column(String(45), primary_key=True)
    export_id: Mapped[str] = mapped_column(String(44), nullable=False)
    previous_attempt_id: Mapped[str | None] = mapped_column(String(45))
    command_id: Mapped[str] = mapped_column(String(45), nullable=False)
    task_id: Mapped[str] = mapped_column(String(42), nullable=False)
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    command: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    state: Mapped[str] = mapped_column(String(24), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(80))
    export_revision_id: Mapped[str | None] = mapped_column(String(47))
    artifact_id: Mapped[str | None] = mapped_column(String(41))
    artifact_revision_id: Mapped[str | None] = mapped_column(String(36))
    pdf_sha256: Mapped[str | None] = mapped_column(String(71))
    layout_sha256: Mapped[str | None] = mapped_column(String(71))
    publication_job_id: Mapped[str | None] = mapped_column(String(36))
    page_count: Mapped[int] = mapped_column(Integer, nullable=False)
