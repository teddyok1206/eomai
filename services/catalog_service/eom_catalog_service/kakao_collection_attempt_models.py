"""Collection execution metadata; canonical command/results stay in Artifact storage."""

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
from sqlalchemy.orm import Mapped, mapped_column


class KakaoCollectionAttemptRecord(Base):
    __tablename__ = "kakao_collection_attempts"
    __table_args__ = (
        UniqueConstraint("task_id", name="uq_kakao_collection_first_attempt"),
        UniqueConstraint("command_id", name="uq_kakao_collection_command"),
        ForeignKeyConstraint(
            ["task_id"],
            ["kakao_collection_tasks.task_id"],
            name="fk_kakao_collection_attempt_task",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["run_id", "browser_run_id"],
            ["kakao_collection_browsers.run_id", "kakao_collection_browsers.browser_run_id"],
            name="fk_kakao_collection_attempt_browser",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["command_artifact_id", "command_artifact_revision_id"],
            ["artifact_revisions.logical_artifact_id", "artifact_revisions.revision_id"],
            name="fk_kakao_collection_attempt_command",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["result_artifact_id", "result_artifact_revision_id"],
            ["artifact_revisions.logical_artifact_id", "artifact_revisions.revision_id"],
            name="fk_kakao_collection_attempt_result",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "attempt_id ~ '^kakaoattempt_[0-9a-f]{32}$' AND "
            "command_id ~ '^kakaocommand_[0-9a-f]{32}$' AND "
            "snapshot_revision_id ~ '^kakaosnapshotrev_[0-9a-f]{32}$' AND "
            "normalization_revision_id ~ '^kakaonormalizationrev_[0-9a-f]{32}$' AND "
            "attempt_number = 1 AND fence BETWEEN 1 AND 2147483647 AND "
            "resource_version BETWEEN 1 AND 2147483647 AND updated_at >= created_at",
            name="ck_kakao_collection_attempt_values",
        ),
        CheckConstraint(
            "state IN ('RESERVED','COMMAND_READY','RESULT_ACCEPTED')",
            name="ck_kakao_collection_attempt_state",
        ),
        CheckConstraint(
            "(state = 'RESERVED' AND command_artifact_id IS NULL AND "
            "command_artifact_revision_id IS NULL AND command_sha256 IS NULL AND "
            "capability_sha256 IS NULL) OR (state <> 'RESERVED' AND "
            "command_artifact_id IS NOT NULL AND command_artifact_revision_id IS NOT NULL AND "
            "command_sha256 IS NOT NULL AND command_sha256 ~ '^sha256:[0-9a-f]{64}$' AND "
            "capability_sha256 IS NOT NULL AND capability_sha256 ~ '^sha256:[0-9a-f]{64}$')",
            name="ck_kakao_collection_attempt_command",
        ),
        CheckConstraint(
            "(state <> 'RESULT_ACCEPTED' AND result_artifact_id IS NULL AND "
            "result_artifact_revision_id IS NULL AND result_sha256 IS NULL AND "
            "result_status IS NULL AND report_sha256 IS NULL AND error_code IS NULL) OR "
            "(state = 'RESULT_ACCEPTED' AND result_artifact_id IS NOT NULL AND "
            "result_artifact_revision_id IS NOT NULL AND result_sha256 IS NOT NULL AND "
            "result_sha256 ~ '^sha256:[0-9a-f]{64}$' AND result_status IS NOT NULL AND "
            "result_status IN ('COMPLETED','PARTIAL','FAILED','PAUSED','CANCELLED') AND "
            "((result_status IN ('COMPLETED','PARTIAL') AND report_sha256 IS NOT NULL AND "
            "report_sha256 ~ '^sha256:[0-9a-f]{64}$') OR "
            "(result_status NOT IN ('COMPLETED','PARTIAL') AND report_sha256 IS NULL)) AND "
            "((result_status = 'FAILED' AND error_code IS NOT NULL) OR "
            "(result_status <> 'FAILED' AND error_code IS NULL)))",
            name="ck_kakao_collection_attempt_result",
        ),
        CheckConstraint(
            "error_code IS NULL OR error_code IN ('NETWORK_TRANSIENT','RATE_LIMITED',"
            "'AUTH_REQUIRED','ACCESS_DENIED','UI_CHANGED','ENUMERATION_STALLED','HASH_MISMATCH',"
            "'DISK_FULL','TIMEOUT','PUBLICATION_UNAVAILABLE','INVALID_INPUT')",
            name="ck_kakao_collection_attempt_error",
        ),
    )
    attempt_id: Mapped[str] = mapped_column(String(45), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(41), nullable=False)
    task_id: Mapped[str] = mapped_column(String(42), nullable=False)
    command_id: Mapped[str] = mapped_column(String(45), nullable=False)
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    source_binding_id: Mapped[str] = mapped_column(String(45), nullable=False)
    room_id: Mapped[str] = mapped_column(String(42), nullable=False)
    profile_id: Mapped[str] = mapped_column(String(45), nullable=False)
    browser_run_id: Mapped[str] = mapped_column(String(48), nullable=False)
    fence: Mapped[int] = mapped_column(Integer, nullable=False)
    snapshot_revision_id: Mapped[str] = mapped_column(String(49), nullable=False)
    normalization_revision_id: Mapped[str] = mapped_column(String(54), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    resource_version: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    command_artifact_id: Mapped[str | None] = mapped_column(String(41))
    command_artifact_revision_id: Mapped[str | None] = mapped_column(String(36))
    command_sha256: Mapped[str | None] = mapped_column(String(71))
    capability_sha256: Mapped[str | None] = mapped_column(String(71))
    result_artifact_id: Mapped[str | None] = mapped_column(String(41))
    result_artifact_revision_id: Mapped[str | None] = mapped_column(String(36))
    result_sha256: Mapped[str | None] = mapped_column(String(71))
    result_status: Mapped[str | None] = mapped_column(String(16))
    report_sha256: Mapped[str | None] = mapped_column(String(71))
    error_code: Mapped[str | None] = mapped_column(String(32))
