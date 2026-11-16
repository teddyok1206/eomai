"""Private packet identity/revision/intent; selected questions remain Artifact refs."""

from datetime import date, datetime

from eom_orchestrator.models import Base
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column


class KakaoPacketRecord(Base):
    __tablename__ = "kakao_packets"
    __table_args__ = (
        ForeignKeyConstraint(
            ["owner_operator_id", "source_binding_id"],
            [
                "kakao_channel_bindings.owner_operator_id",
                "kakao_channel_bindings.source_binding_id",
            ],
            name="fk_kakao_packet_binding",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["packet_id", "current_revision_id", "resource_version"],
            [
                "kakao_packet_revisions.packet_id",
                "kakao_packet_revisions.packet_revision_id",
                "kakao_packet_revisions.resource_version",
            ],
            name="fk_kakao_packet_current",
            ondelete="RESTRICT",
            use_alter=True,
            deferrable=True,
            initially="DEFERRED",
        ),
        UniqueConstraint(
            "owner_operator_id", "source_binding_id", "packet_id", name="uq_kakao_packet_owner"
        ),
        CheckConstraint(
            "packet_id ~ '^kakaopacket_[0-9a-f]{32}$' "
            "AND resource_version BETWEEN 1 AND 2147483647",
            name="ck_kakao_packet_id_version",
        ),
        Index("ix_kakao_packet_page", "owner_operator_id", "source_binding_id", "packet_id"),
    )
    packet_id: Mapped[str] = mapped_column(String(44), primary_key=True)
    owner_operator_id: Mapped[str] = mapped_column(String(41), nullable=False)
    source_binding_id: Mapped[str] = mapped_column(String(45), nullable=False)
    current_revision_id: Mapped[str] = mapped_column(String(47), nullable=False)
    resource_version: Mapped[int] = mapped_column(Integer, nullable=False)


class KakaoPacketCommandRecord(Base):
    __tablename__ = "kakao_packet_commands"
    __table_args__ = (
        ForeignKeyConstraint(
            ["owner_operator_id", "source_binding_id"],
            [
                "kakao_channel_bindings.owner_operator_id",
                "kakao_channel_bindings.source_binding_id",
            ],
            name="fk_kakao_packet_command_binding",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "owner_operator_id",
            "idempotency_scope",
            "idempotency_key",
            name="uq_kakao_packet_command_replay",
        ),
        UniqueConstraint(
            "command_id", "packet_id", "packet_revision_id", name="uq_kakao_packet_command_result"
        ),
        CheckConstraint(
            "command_id ~ '^kakaocommand_[0-9a-f]{32}$' "
            "AND packet_id ~ '^kakaopacket_[0-9a-f]{32}$' "
            "AND packet_revision_id ~ '^kakaopacketrev_[0-9a-f]{32}$'",
            name="ck_kakao_packet_command_ids",
        ),
        CheckConstraint(
            "request_sha256 ~ '^sha256:[0-9a-f]{64}$' AND idempotency_key ~ '^[!-~]{16,128}$'",
            name="ck_kakao_packet_command_request",
        ),
        CheckConstraint(
            "(expected_version = 0 AND previous_revision_id IS NULL) OR "
            "(expected_version BETWEEN 1 AND 2147483646 AND previous_revision_id IS NOT NULL)",
            name="ck_kakao_packet_command_parent",
        ),
        CheckConstraint(
            "(state = 'RESERVED' AND completed_at IS NULL) OR (state = 'COMPLETED' "
            "AND completed_at IS NOT NULL AND completed_at >= reserved_at)",
            name="ck_kakao_packet_command_state",
        ),
    )
    command_id: Mapped[str] = mapped_column(String(45), primary_key=True)
    owner_operator_id: Mapped[str] = mapped_column(String(41), nullable=False)
    source_binding_id: Mapped[str] = mapped_column(String(45), nullable=False)
    idempotency_scope: Mapped[str] = mapped_column(String(96), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    packet_id: Mapped[str] = mapped_column(String(44), nullable=False)
    packet_revision_id: Mapped[str] = mapped_column(String(47), nullable=False)
    previous_revision_id: Mapped[str | None] = mapped_column(String(47))
    expected_version: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    reserved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class KakaoPacketRevisionRecord(Base):
    __tablename__ = "kakao_packet_revisions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["owner_operator_id", "source_binding_id", "packet_id"],
            [
                "kakao_packets.owner_operator_id",
                "kakao_packets.source_binding_id",
                "kakao_packets.packet_id",
            ],
            name="fk_kakao_packet_revision_parent",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["command_id", "packet_id", "packet_revision_id"],
            [
                "kakao_packet_commands.command_id",
                "kakao_packet_commands.packet_id",
                "kakao_packet_commands.packet_revision_id",
            ],
            name="fk_kakao_packet_revision_command",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["packet_id", "previous_revision_id"],
            ["kakao_packet_revisions.packet_id", "kakao_packet_revisions.packet_revision_id"],
            name="fk_kakao_packet_previous",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["manifest_artifact_id", "manifest_artifact_revision_id"],
            ["artifact_revisions.logical_artifact_id", "artifact_revisions.revision_id"],
            name="fk_kakao_packet_manifest",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("packet_id", "packet_revision_id", name="uq_kakao_packet_revision"),
        UniqueConstraint("packet_id", "resource_version", name="uq_kakao_packet_version"),
        UniqueConstraint(
            "packet_id",
            "packet_revision_id",
            "resource_version",
            name="uq_kakao_packet_current_version",
        ),
        CheckConstraint(
            "packet_revision_id ~ '^kakaopacketrev_[0-9a-f]{32}$' "
            "AND manifest_sha256 ~ '^sha256:[0-9a-f]{64}$'",
            name="ck_kakao_packet_revision_ids",
        ),
        CheckConstraint(
            "(resource_version = 1 AND previous_revision_id IS NULL) OR "
            "(resource_version BETWEEN 2 AND 2147483647 AND previous_revision_id IS NOT NULL "
            "AND previous_revision_id <> packet_revision_id)",
            name="ck_kakao_packet_lineage",
        ),
        CheckConstraint(
            "mode IN ('DRAFT','FINAL') AND question_count BETWEEN 1 AND 200 "
            "AND student_count BETWEEN 1 AND question_count "
            "AND display_end_date_inclusive >= display_start_date",
            name="ck_kakao_packet_selection",
        ),
        CheckConstraint(
            "length(btrim(title)) BETWEEN 1 AND 128 AND title !~ '[[:cntrl:]]'",
            name="ck_kakao_packet_title",
        ),
    )
    packet_revision_id: Mapped[str] = mapped_column(String(47), primary_key=True)
    packet_id: Mapped[str] = mapped_column(String(44), nullable=False)
    owner_operator_id: Mapped[str] = mapped_column(String(41), nullable=False)
    source_binding_id: Mapped[str] = mapped_column(String(45), nullable=False)
    command_id: Mapped[str] = mapped_column(String(45), nullable=False)
    previous_revision_id: Mapped[str | None] = mapped_column(String(47))
    resource_version: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(128), nullable=False)
    mode: Mapped[str] = mapped_column(String(8), nullable=False)
    include_replies: Mapped[bool] = mapped_column(Boolean, nullable=False)
    display_start_date: Mapped[date] = mapped_column(Date, nullable=False)
    display_end_date_inclusive: Mapped[date] = mapped_column(Date, nullable=False)
    question_count: Mapped[int] = mapped_column(Integer, nullable=False)
    student_count: Mapped[int] = mapped_column(Integer, nullable=False)
    manifest_artifact_id: Mapped[str] = mapped_column(String(41), nullable=False)
    manifest_artifact_revision_id: Mapped[str] = mapped_column(String(36), nullable=False)
    manifest_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    publication_job_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("jobs.job_id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
