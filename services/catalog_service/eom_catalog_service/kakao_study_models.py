"""Small saved-study heads, immutable manifest pointers and replay reservations."""

from datetime import datetime

from eom_orchestrator.models import Base
from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column


class KakaoStudyRecord(Base):
    __tablename__ = "kakao_studies"
    __table_args__ = (
        ForeignKeyConstraint(
            ["owner_operator_id", "source_binding_id", "packet_id"],
            [
                "kakao_packets.owner_operator_id",
                "kakao_packets.source_binding_id",
                "kakao_packets.packet_id",
            ],
            name="fk_kakao_study_packet",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["packet_id", "packet_revision_id"],
            ["kakao_packet_revisions.packet_id", "kakao_packet_revisions.packet_revision_id"],
            name="fk_kakao_study_packet_revision",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["student_id"],
            ["kakao_students.student_id"],
            name="fk_kakao_study_student",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["study_id", "current_revision_id", "resource_version"],
            [
                "kakao_study_revisions.study_id",
                "kakao_study_revisions.study_revision_id",
                "kakao_study_revisions.resource_version",
            ],
            name="fk_kakao_study_current",
            ondelete="RESTRICT",
            use_alter=True,
            deferrable=True,
            initially="DEFERRED",
        ),
        UniqueConstraint(
            "owner_operator_id", "source_binding_id", "study_id", name="uq_kakao_study_owner"
        ),
        CheckConstraint(
            "study_id ~ '^kakaostudy_[0-9a-f]{32}$' AND resource_version BETWEEN 1 AND 2147483647",
            name="ck_kakao_study_head",
        ),
        Index("ix_kakao_study_page", "owner_operator_id", "source_binding_id", "study_id"),
    )
    study_id: Mapped[str] = mapped_column(String(43), primary_key=True)
    owner_operator_id: Mapped[str] = mapped_column(String(41), nullable=False)
    source_binding_id: Mapped[str] = mapped_column(String(45), nullable=False)
    packet_id: Mapped[str] = mapped_column(String(44), nullable=False)
    packet_revision_id: Mapped[str] = mapped_column(String(47), nullable=False)
    student_id: Mapped[str] = mapped_column(String(45), nullable=False)
    current_revision_id: Mapped[str] = mapped_column(String(46), nullable=False)
    resource_version: Mapped[int] = mapped_column(Integer, nullable=False)


class KakaoStudyCommandRecord(Base):
    __tablename__ = "kakao_study_commands"
    __table_args__ = (
        ForeignKeyConstraint(
            ["owner_operator_id", "source_binding_id"],
            [
                "kakao_channel_bindings.owner_operator_id",
                "kakao_channel_bindings.source_binding_id",
            ],
            name="fk_kakao_study_command_binding",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("owner_operator_id", "idempotency_key", name="uq_kakao_study_replay"),
        UniqueConstraint(
            "command_id", "study_id", "study_revision_id", name="uq_kakao_study_command_result"
        ),
        CheckConstraint(
            "command_id ~ '^kakaocommand_[0-9a-f]{32}$' "
            "AND study_id ~ '^kakaostudy_[0-9a-f]{32}$' "
            "AND study_revision_id ~ '^kakaostudyrev_[0-9a-f]{32}$'",
            name="ck_kakao_study_command_ids",
        ),
        CheckConstraint(
            "request_sha256 ~ '^sha256:[0-9a-f]{64}$' AND idempotency_key ~ '^[!-~]{16,128}$'",
            name="ck_kakao_study_command_hash",
        ),
        CheckConstraint(
            "(expected_version = 0 AND previous_revision_id IS NULL) OR "
            "(expected_version BETWEEN 1 AND 2147483646 AND previous_revision_id IS NOT NULL)",
            name="ck_kakao_study_command_parent",
        ),
        CheckConstraint(
            "(state = 'RESERVED' AND completed_at IS NULL) OR "
            "(state = 'COMPLETED' AND completed_at IS NOT NULL AND completed_at >= reserved_at)",
            name="ck_kakao_study_command_state",
        ),
    )
    command_id: Mapped[str] = mapped_column(String(45), primary_key=True)
    owner_operator_id: Mapped[str] = mapped_column(String(41), nullable=False)
    source_binding_id: Mapped[str] = mapped_column(String(45), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    study_id: Mapped[str] = mapped_column(String(43), nullable=False)
    study_revision_id: Mapped[str] = mapped_column(String(46), nullable=False)
    previous_revision_id: Mapped[str | None] = mapped_column(String(46))
    expected_version: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    reserved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class KakaoStudyRevisionRecord(Base):
    __tablename__ = "kakao_study_revisions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["owner_operator_id", "source_binding_id", "study_id"],
            [
                "kakao_studies.owner_operator_id",
                "kakao_studies.source_binding_id",
                "kakao_studies.study_id",
            ],
            name="fk_kakao_study_revision_owner",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["command_id", "study_id", "study_revision_id"],
            [
                "kakao_study_commands.command_id",
                "kakao_study_commands.study_id",
                "kakao_study_commands.study_revision_id",
            ],
            name="fk_kakao_study_revision_command",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["study_id", "previous_revision_id"],
            ["kakao_study_revisions.study_id", "kakao_study_revisions.study_revision_id"],
            name="fk_kakao_study_previous",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["manifest_artifact_id", "manifest_artifact_revision_id"],
            ["artifact_revisions.logical_artifact_id", "artifact_revisions.revision_id"],
            name="fk_kakao_study_manifest",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("study_id", "study_revision_id", name="uq_kakao_study_revision"),
        UniqueConstraint("study_id", "resource_version", name="uq_kakao_study_version"),
        UniqueConstraint(
            "study_id",
            "study_revision_id",
            "resource_version",
            name="uq_kakao_study_current_version",
        ),
        CheckConstraint(
            "study_revision_id ~ '^kakaostudyrev_[0-9a-f]{32}$' "
            "AND manifest_sha256 ~ '^sha256:[0-9a-f]{64}$'",
            name="ck_kakao_study_revision_ids",
        ),
        CheckConstraint(
            "(resource_version = 1 AND previous_revision_id IS NULL) OR "
            "(resource_version BETWEEN 2 AND 2147483647 AND previous_revision_id IS NOT NULL "
            "AND previous_revision_id <> study_revision_id)",
            name="ck_kakao_study_revision_parent",
        ),
        CheckConstraint(
            "question_count BETWEEN 1 AND 200 AND length(btrim(title)) BETWEEN 1 AND 128 "
            "AND title !~ '[[:cntrl:]]'",
            name="ck_kakao_study_revision_summary",
        ),
    )
    study_revision_id: Mapped[str] = mapped_column(String(46), primary_key=True)
    study_id: Mapped[str] = mapped_column(String(43), nullable=False)
    owner_operator_id: Mapped[str] = mapped_column(String(41), nullable=False)
    source_binding_id: Mapped[str] = mapped_column(String(45), nullable=False)
    command_id: Mapped[str] = mapped_column(String(45), nullable=False)
    previous_revision_id: Mapped[str | None] = mapped_column(String(46))
    resource_version: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(128), nullable=False)
    question_count: Mapped[int] = mapped_column(Integer, nullable=False)
    manifest_artifact_id: Mapped[str] = mapped_column(String(41), nullable=False)
    manifest_artifact_revision_id: Mapped[str] = mapped_column(String(36), nullable=False)
    manifest_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
