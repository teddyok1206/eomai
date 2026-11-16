"""Admitted private rooms and immutable student mappings; no conversation bodies."""

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


class KakaoRoomRecord(Base):
    __tablename__ = "kakao_rooms"
    __table_args__ = (
        CheckConstraint("room_id ~ '^kakaoroom_[0-9a-f]{32}$'", name="ck_kakao_room_id"),
        CheckConstraint("state IN ('ACTIVE','RETIRED')", name="ck_kakao_room_state"),
        CheckConstraint("resource_version BETWEEN 1 AND 2147483647", name="ck_kakao_room_version"),
        CheckConstraint(
            "identity_level IN ('SOURCE_VERIFIED','MANUAL_CONFIRMED')",
            name="ck_kakao_room_identity_level",
        ),
        CheckConstraint(
            "source_identity_sha256 ~ '^sha256:[0-9a-f]{64}$' "
            "AND evidence_sha256 ~ '^sha256:[0-9a-f]{64}$'",
            name="ck_kakao_room_hashes",
        ),
        CheckConstraint(
            "length(btrim(display_name)) > 0 AND display_name !~ '[[:cntrl:]]'",
            name="ck_kakao_room_name",
        ),
        UniqueConstraint(
            "owner_operator_id", "source_binding_id", "room_id", name="uq_kakao_room_owner"
        ),
        UniqueConstraint(
            "source_binding_id",
            "identity_level",
            "source_identity_sha256",
            name="uq_kakao_room_source_identity",
        ),
        ForeignKeyConstraint(
            ["owner_operator_id", "source_binding_id"],
            [
                "kakao_channel_bindings.owner_operator_id",
                "kakao_channel_bindings.source_binding_id",
            ],
            name="fk_kakao_room_binding_owner",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["room_id", "current_mapping_revision_id"],
            [
                "kakao_room_mapping_revisions.room_id",
                "kakao_room_mapping_revisions.mapping_revision_id",
            ],
            name="fk_kakao_room_current_mapping",
            ondelete="RESTRICT",
            use_alter=True,
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["evidence_artifact_id", "evidence_artifact_revision_id"],
            ["artifact_revisions.logical_artifact_id", "artifact_revisions.revision_id"],
            name="fk_kakao_room_evidence",
            ondelete="RESTRICT",
        ),
    )
    room_id: Mapped[str] = mapped_column(String(42), primary_key=True)
    owner_operator_id: Mapped[str] = mapped_column(String(41), nullable=False)
    source_binding_id: Mapped[str] = mapped_column(String(45), nullable=False)
    identity_level: Mapped[str] = mapped_column(String(24), nullable=False)
    source_identity_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    resource_version: Mapped[int] = mapped_column(Integer, nullable=False)
    current_mapping_revision_id: Mapped[str] = mapped_column(String(48), nullable=False)
    evidence_artifact_id: Mapped[str] = mapped_column(String(41), nullable=False)
    evidence_artifact_revision_id: Mapped[str] = mapped_column(String(36), nullable=False)
    evidence_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class KakaoRoomMappingRevisionRecord(Base):
    __tablename__ = "kakao_room_mapping_revisions"
    __table_args__ = (
        CheckConstraint(
            "mapping_revision_id ~ '^kakaomappingrev_[0-9a-f]{32}$'", name="ck_kakao_mapping_id"
        ),
        CheckConstraint(
            "(revision_number = 1 AND previous_revision_id IS NULL "
            "AND idempotency_key IS NULL AND request_sha256 IS NULL) OR "
            "(revision_number > 1 AND previous_revision_id IS NOT NULL "
            "AND previous_revision_id <> mapping_revision_id "
            "AND idempotency_key IS NOT NULL AND request_sha256 IS NOT NULL)",
            name="ck_kakao_mapping_lineage",
        ),
        CheckConstraint(
            "(state = 'MAPPED' AND student_id IS NOT NULL "
            "AND student_display_revision_id IS NOT NULL) OR "
            "(state = 'UNMAPPED' AND student_id IS NULL AND student_display_revision_id IS NULL)",
            name="ck_kakao_mapping_state",
        ),
        CheckConstraint(
            "sha256 ~ '^sha256:[0-9a-f]{64}$' "
            "AND (request_sha256 IS NULL OR request_sha256 ~ '^sha256:[0-9a-f]{64}$') "
            "AND (idempotency_key IS NULL OR idempotency_key ~ '^[!-~]{16,128}$')",
            name="ck_kakao_mapping_hashes",
        ),
        CheckConstraint(
            "length(btrim(reason)) > 0 AND reason !~ '[[:cntrl:]]'", name="ck_kakao_mapping_reason"
        ),
        UniqueConstraint("room_id", "mapping_revision_id", name="uq_kakao_mapping_room"),
        UniqueConstraint("room_id", "revision_number", name="uq_kakao_mapping_number"),
        UniqueConstraint(
            "owner_operator_id", "room_id", "idempotency_key", name="uq_kakao_mapping_replay"
        ),
        ForeignKeyConstraint(
            ["owner_operator_id", "source_binding_id", "room_id"],
            [
                "kakao_rooms.owner_operator_id",
                "kakao_rooms.source_binding_id",
                "kakao_rooms.room_id",
            ],
            name="fk_kakao_mapping_room_owner",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["room_id", "previous_revision_id"],
            [
                "kakao_room_mapping_revisions.room_id",
                "kakao_room_mapping_revisions.mapping_revision_id",
            ],
            name="fk_kakao_mapping_previous",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["owner_operator_id", "student_id"],
            ["kakao_students.owner_operator_id", "kakao_students.student_id"],
            name="fk_kakao_mapping_student_owner",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["student_id", "student_display_revision_id"],
            [
                "kakao_student_display_revisions.student_id",
                "kakao_student_display_revisions.display_revision_id",
            ],
            name="fk_kakao_mapping_student_display",
            ondelete="RESTRICT",
        ),
    )
    mapping_revision_id: Mapped[str] = mapped_column(String(48), primary_key=True)
    room_id: Mapped[str] = mapped_column(String(42), nullable=False)
    owner_operator_id: Mapped[str] = mapped_column(String(41), nullable=False)
    source_binding_id: Mapped[str] = mapped_column(String(45), nullable=False)
    previous_revision_id: Mapped[str | None] = mapped_column(String(48))
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    student_id: Mapped[str | None] = mapped_column(String(45))
    student_display_revision_id: Mapped[str | None] = mapped_column(String(48))
    reason: Mapped[str] = mapped_column(String(1000), nullable=False)
    sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(128))
    request_sha256: Mapped[str | None] = mapped_column(String(71))
    created_by: Mapped[str] = mapped_column(
        String(41), ForeignKey("operators.operator_id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class KakaoRoomAdmissionRecord(Base):
    __tablename__ = "kakao_room_admissions"
    __table_args__ = (
        CheckConstraint(
            "command_id ~ '^kakaocommand_[0-9a-f]{32}$'", name="ck_kakao_room_admission_id"
        ),
        CheckConstraint(
            "request_sha256 ~ '^sha256:[0-9a-f]{64}$' "
            "AND evidence_sha256 ~ '^sha256:[0-9a-f]{64}$' "
            "AND idempotency_key ~ '^[!-~]{16,128}$'",
            name="ck_kakao_room_admission_hashes",
        ),
        UniqueConstraint(
            "owner_operator_id",
            "source_binding_id",
            "idempotency_key",
            name="uq_kakao_room_admission_replay",
        ),
        ForeignKeyConstraint(
            ["owner_operator_id", "source_binding_id", "room_id"],
            [
                "kakao_rooms.owner_operator_id",
                "kakao_rooms.source_binding_id",
                "kakao_rooms.room_id",
            ],
            name="fk_kakao_room_admission_owner",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["room_id", "result_mapping_revision_id"],
            [
                "kakao_room_mapping_revisions.room_id",
                "kakao_room_mapping_revisions.mapping_revision_id",
            ],
            name="fk_kakao_room_admission_mapping",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["evidence_artifact_id", "evidence_artifact_revision_id"],
            ["artifact_revisions.logical_artifact_id", "artifact_revisions.revision_id"],
            name="fk_kakao_room_admission_evidence",
            ondelete="RESTRICT",
        ),
    )
    command_id: Mapped[str] = mapped_column(String(45), primary_key=True)
    owner_operator_id: Mapped[str] = mapped_column(String(41), nullable=False)
    source_binding_id: Mapped[str] = mapped_column(String(45), nullable=False)
    room_id: Mapped[str] = mapped_column(String(42), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    evidence_artifact_id: Mapped[str] = mapped_column(String(41), nullable=False)
    evidence_artifact_revision_id: Mapped[str] = mapped_column(String(36), nullable=False)
    evidence_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    result_mapping_revision_id: Mapped[str] = mapped_column(String(48), nullable=False)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
