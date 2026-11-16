"""Small ordered reservations for atomic split/merge; no message, selection or image blobs."""

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


class KakaoQuestionCompositionRecord(Base):
    __tablename__ = "kakao_question_compositions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["owner_operator_id", "source_binding_id", "room_id"],
            [
                "kakao_rooms.owner_operator_id",
                "kakao_rooms.source_binding_id",
                "kakao_rooms.room_id",
            ],
            name="fk_kakao_composition_room",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["room_id", "mapping_revision_id"],
            [
                "kakao_room_mapping_revisions.room_id",
                "kakao_room_mapping_revisions.mapping_revision_id",
            ],
            name="fk_kakao_composition_mapping",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "owner_operator_id", "idempotency_key", name="uq_kakao_composition_replay"
        ),
        UniqueConstraint("composition_id", "room_id", name="uq_kakao_composition_room"),
        CheckConstraint(
            "composition_id ~ '^kakaocomposition_[0-9a-f]{32}$'", name="ck_kakao_composition_id"
        ),
        CheckConstraint("operation IN ('SPLIT','MERGE')", name="ck_kakao_composition_operation"),
        CheckConstraint(
            "request_sha256 ~ '^sha256:[0-9a-f]{64}$' AND idempotency_key ~ '^[!-~]{16,128}$'",
            name="ck_kakao_composition_request",
        ),
        CheckConstraint(
            "(state = 'RESERVED' AND completed_at IS NULL) OR (state = 'COMPLETED' "
            "AND completed_at IS NOT NULL AND completed_at >= reserved_at)",
            name="ck_kakao_composition_state",
        ),
    )
    composition_id: Mapped[str] = mapped_column(String(49), primary_key=True)
    owner_operator_id: Mapped[str] = mapped_column(String(41), nullable=False)
    source_binding_id: Mapped[str] = mapped_column(String(45), nullable=False)
    room_id: Mapped[str] = mapped_column(String(42), nullable=False)
    mapping_revision_id: Mapped[str] = mapped_column(String(48), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    operation: Mapped[str] = mapped_column(String(16), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    reserved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class KakaoQuestionCompositionInputRecord(Base):
    __tablename__ = "kakao_question_composition_inputs"
    __table_args__ = (
        ForeignKeyConstraint(
            ["composition_id", "room_id"],
            ["kakao_question_compositions.composition_id", "kakao_question_compositions.room_id"],
            name="fk_kakao_composition_input_command",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["question_id", "room_id"],
            ["kakao_questions.question_id", "kakao_questions.room_id"],
            name="fk_kakao_composition_input_room",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["question_id", "question_revision_id", "resource_version"],
            [
                "kakao_question_revisions.question_id",
                "kakao_question_revisions.question_revision_id",
                "kakao_question_revisions.resource_version",
            ],
            name="fk_kakao_composition_input_revision",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "composition_id", "question_id", name="uq_kakao_composition_input_question"
        ),
        CheckConstraint("ordinal BETWEEN 1 AND 100", name="ck_kakao_composition_input_ordinal"),
    )
    composition_id: Mapped[str] = mapped_column(String(49), primary_key=True)
    ordinal: Mapped[int] = mapped_column(Integer, primary_key=True)
    room_id: Mapped[str] = mapped_column(String(42), nullable=False)
    question_id: Mapped[str] = mapped_column(String(46), nullable=False)
    question_revision_id: Mapped[str] = mapped_column(String(49), nullable=False)
    resource_version: Mapped[int] = mapped_column(Integer, nullable=False)


class KakaoQuestionCompositionOutputRecord(Base):
    __tablename__ = "kakao_question_composition_outputs"
    __table_args__ = (
        UniqueConstraint("question_id", name="uq_kakao_composition_output_identity"),
        UniqueConstraint("question_revision_id", name="uq_kakao_composition_output_revision"),
        UniqueConstraint(
            "composition_id", "question_id", name="uq_kakao_composition_output_question"
        ),
        UniqueConstraint(
            "composition_id",
            "question_id",
            "question_revision_id",
            name="uq_kakao_composition_output_exact",
        ),
        CheckConstraint("ordinal BETWEEN 1 AND 100", name="ck_kakao_composition_output_ordinal"),
        CheckConstraint(
            "question_id ~ '^kakaoquestion_[0-9a-f]{32}$' "
            "AND question_revision_id ~ '^kakaoquestionrev_[0-9a-f]{32}$'",
            name="ck_kakao_composition_output_ids",
        ),
    )
    composition_id: Mapped[str] = mapped_column(
        String(49),
        ForeignKey("kakao_question_compositions.composition_id", ondelete="RESTRICT"),
        primary_key=True,
    )
    ordinal: Mapped[int] = mapped_column(Integer, primary_key=True)
    question_id: Mapped[str] = mapped_column(String(46), nullable=False)
    question_revision_id: Mapped[str] = mapped_column(String(49), nullable=False)
