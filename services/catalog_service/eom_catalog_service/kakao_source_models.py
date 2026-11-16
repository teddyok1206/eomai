"""Three small source records; bodies and occurrence maps remain immutable Artifacts."""

from datetime import datetime

from eom_orchestrator.models import Base
from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column


class KakaoSourceHeadRecord(Base):
    __tablename__ = "kakao_source_heads"
    __table_args__ = (
        ForeignKeyConstraint(
            ["owner_operator_id", "source_binding_id", "room_id"],
            [
                "kakao_rooms.owner_operator_id",
                "kakao_rooms.source_binding_id",
                "kakao_rooms.room_id",
            ],
            name="fk_kakao_source_head_room",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["room_id", "current_source_revision_id"],
            ["kakao_source_revisions.room_id", "kakao_source_revisions.source_revision_id"],
            name="fk_kakao_source_head_current",
            ondelete="RESTRICT",
            use_alter=True,
            deferrable=True,
            initially="DEFERRED",
        ),
        CheckConstraint(
            "(resource_version = 0 AND current_source_revision_id IS NULL) OR "
            "(resource_version BETWEEN 1 AND 2147483647 "
            "AND current_source_revision_id IS NOT NULL)",
            name="ck_kakao_source_head_version",
        ),
    )
    room_id: Mapped[str] = mapped_column(String(42), primary_key=True)
    owner_operator_id: Mapped[str] = mapped_column(String(41), nullable=False)
    source_binding_id: Mapped[str] = mapped_column(String(45), nullable=False)
    current_source_revision_id: Mapped[str | None] = mapped_column(String(47))
    resource_version: Mapped[int] = mapped_column(Integer, nullable=False)


class KakaoSourceCommandRecord(Base):
    __tablename__ = "kakao_source_commands"
    __table_args__ = (
        UniqueConstraint(
            "owner_operator_id", "room_id", "idempotency_key", name="uq_kakao_source_command_replay"
        ),
        UniqueConstraint("source_binding_id", "capture_attempt_id", name="uq_kakao_source_attempt"),
        UniqueConstraint(
            "command_id", "room_id", "source_revision_id", name="uq_kakao_source_command_result"
        ),
        ForeignKeyConstraint(
            ["owner_operator_id", "source_binding_id", "room_id"],
            [
                "kakao_rooms.owner_operator_id",
                "kakao_rooms.source_binding_id",
                "kakao_rooms.room_id",
            ],
            name="fk_kakao_source_command_room",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["room_id", "previous_revision_id"],
            ["kakao_source_revisions.room_id", "kakao_source_revisions.source_revision_id"],
            name="fk_kakao_source_command_previous",
            ondelete="RESTRICT",
            use_alter=True,
        ),
        CheckConstraint(
            "command_id ~ '^kakaocommand_[0-9a-f]{32}$' "
            "AND source_revision_id ~ '^kakaosourcerev_[0-9a-f]{32}$'",
            name="ck_kakao_source_command_ids",
        ),
        CheckConstraint(
            "capture_attempt_id ~ '^kakaoattempt_[0-9a-f]{32}$'",
            name="ck_kakao_source_command_attempt",
        ),
        CheckConstraint(
            "request_sha256 ~ '^sha256:[0-9a-f]{64}$' AND idempotency_key ~ '^[!-~]{16,128}$'",
            name="ck_kakao_source_command_request",
        ),
        CheckConstraint(
            "(expected_resource_version = 0 AND previous_revision_id IS NULL) OR "
            "(expected_resource_version BETWEEN 1 AND 2147483646 "
            "AND previous_revision_id IS NOT NULL)",
            name="ck_kakao_source_command_previous",
        ),
        CheckConstraint(
            "(state = 'RESERVED' AND completed_at IS NULL) OR "
            "(state = 'COMPLETED' AND completed_at IS NOT NULL AND completed_at >= reserved_at)",
            name="ck_kakao_source_command_state",
        ),
    )
    command_id: Mapped[str] = mapped_column(String(45), primary_key=True)
    owner_operator_id: Mapped[str] = mapped_column(String(41), nullable=False)
    source_binding_id: Mapped[str] = mapped_column(String(45), nullable=False)
    room_id: Mapped[str] = mapped_column(String(42), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    capture_attempt_id: Mapped[str] = mapped_column(String(45), nullable=False)
    source_revision_id: Mapped[str] = mapped_column(String(47), nullable=False)
    previous_revision_id: Mapped[str | None] = mapped_column(String(47))
    expected_resource_version: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    reserved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class KakaoSourceRevisionRecord(Base):
    __tablename__ = "kakao_source_revisions"
    __table_args__ = (
        UniqueConstraint("room_id", "source_revision_id", name="uq_kakao_source_room_revision"),
        UniqueConstraint("room_id", "resource_version", name="uq_kakao_source_version"),
        UniqueConstraint(
            "source_binding_id", "normalization_revision_id", name="uq_kakao_source_normalization"
        ),
        ForeignKeyConstraint(
            ["owner_operator_id", "source_binding_id", "room_id"],
            [
                "kakao_rooms.owner_operator_id",
                "kakao_rooms.source_binding_id",
                "kakao_rooms.room_id",
            ],
            name="fk_kakao_source_room",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["command_id", "room_id", "source_revision_id"],
            [
                "kakao_source_commands.command_id",
                "kakao_source_commands.room_id",
                "kakao_source_commands.source_revision_id",
            ],
            name="fk_kakao_source_command",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["room_id", "previous_revision_id"],
            ["kakao_source_revisions.room_id", "kakao_source_revisions.source_revision_id"],
            name="fk_kakao_source_previous",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["manifest_artifact_id", "manifest_artifact_revision_id"],
            ["artifact_revisions.logical_artifact_id", "artifact_revisions.revision_id"],
            name="fk_kakao_source_manifest",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "source_revision_id ~ '^kakaosourcerev_[0-9a-f]{32}$' "
            "AND snapshot_revision_id ~ '^kakaosnapshotrev_[0-9a-f]{32}$' "
            "AND normalization_revision_id ~ '^kakaonormalizationrev_[0-9a-f]{32}$'",
            name="ck_kakao_source_ids",
        ),
        CheckConstraint("manifest_sha256 ~ '^sha256:[0-9a-f]{64}$'", name="ck_kakao_source_hash"),
        CheckConstraint(
            "(resource_version = 1 AND previous_revision_id IS NULL) OR "
            "(resource_version BETWEEN 2 AND 2147483647 AND previous_revision_id IS NOT NULL "
            "AND previous_revision_id <> source_revision_id)",
            name="ck_kakao_source_lineage",
        ),
        CheckConstraint(
            "row_count BETWEEN 0 AND 100000 AND observed_at <= created_at",
            name="ck_kakao_source_bounds",
        ),
    )
    source_revision_id: Mapped[str] = mapped_column(String(47), primary_key=True)
    owner_operator_id: Mapped[str] = mapped_column(String(41), nullable=False)
    source_binding_id: Mapped[str] = mapped_column(String(45), nullable=False)
    room_id: Mapped[str] = mapped_column(String(42), nullable=False)
    command_id: Mapped[str] = mapped_column(String(45), nullable=False)
    previous_revision_id: Mapped[str | None] = mapped_column(String(47))
    resource_version: Mapped[int] = mapped_column(Integer, nullable=False)
    snapshot_revision_id: Mapped[str] = mapped_column(String(49), nullable=False)
    normalization_revision_id: Mapped[str] = mapped_column(String(54), nullable=False)
    manifest_artifact_id: Mapped[str] = mapped_column(String(41), nullable=False)
    manifest_artifact_revision_id: Mapped[str] = mapped_column(String(36), nullable=False)
    manifest_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    publication_job_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("jobs.job_id", ondelete="RESTRICT"), nullable=False
    )
    row_count: Mapped[int] = mapped_column(Integer, nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
