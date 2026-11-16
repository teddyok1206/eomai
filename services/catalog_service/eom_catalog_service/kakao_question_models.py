"""Question identity, immutable manifest revisions and bounded command reservations."""

from datetime import datetime

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
)
from sqlalchemy.orm import Mapped, mapped_column

from eom_catalog_service import kakao_question_composition_models  # noqa: F401


class KakaoQuestionRecord(Base):
    __tablename__ = "kakao_questions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["owner_operator_id", "source_binding_id", "room_id"],
            [
                "kakao_rooms.owner_operator_id",
                "kakao_rooms.source_binding_id",
                "kakao_rooms.room_id",
            ],
            name="fk_kakao_question_room",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["room_id", "origin_source_revision_id"],
            ["kakao_source_revisions.room_id", "kakao_source_revisions.source_revision_id"],
            name="fk_kakao_question_origin_source",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["question_id", "current_revision_id", "resource_version"],
            [
                "kakao_question_revisions.question_id",
                "kakao_question_revisions.question_revision_id",
                "kakao_question_revisions.resource_version",
            ],
            name="fk_kakao_question_current",
            ondelete="RESTRICT",
            use_alter=True,
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["origin_composition_id", "question_id"],
            [
                "kakao_question_composition_outputs.composition_id",
                "kakao_question_composition_outputs.question_id",
            ],
            name="fk_kakao_question_composed_origin",
            ondelete="RESTRICT",
            use_alter=True,
        ),
        ForeignKeyConstraint(
            ["superseded_by_composition_id", "question_id"],
            [
                "kakao_question_composition_inputs.composition_id",
                "kakao_question_composition_inputs.question_id",
            ],
            name="fk_kakao_question_supersession",
            ondelete="RESTRICT",
            use_alter=True,
        ),
        CheckConstraint(
            "(origin_composition_id IS NULL AND origin_source_revision_id IS NOT NULL "
            "AND origin_candidate_ordinal IS NOT NULL AND origin_occurrence_id IS NOT NULL) OR "
            "(origin_composition_id IS NOT NULL AND origin_source_revision_id IS NULL "
            "AND origin_candidate_ordinal IS NULL AND origin_occurrence_id IS NULL)",
            name="ck_kakao_question_origin_kind",
        ),
        UniqueConstraint("room_id", "origin_occurrence_id", name="uq_kakao_question_origin"),
        UniqueConstraint("owner_operator_id", "question_id", name="uq_kakao_question_owner"),
        UniqueConstraint("question_id", "room_id", name="uq_kakao_question_room"),
        Index(
            "ix_kakao_question_page",
            "owner_operator_id",
            "source_binding_id",
            "room_id",
            "question_id",
        ),
        Index(
            "ix_kakao_question_binding_page",
            "owner_operator_id",
            "source_binding_id",
            "question_id",
        ),
        CheckConstraint(
            "question_id ~ '^kakaoquestion_[0-9a-f]{32}$'", name="ck_kakao_question_id"
        ),
        CheckConstraint(
            "origin_occurrence_id ~ '^kakaomessage_[0-9a-f]{32}$'", name="ck_kakao_question_origin"
        ),
        CheckConstraint(
            "(origin_candidate_ordinal IS NULL OR origin_candidate_ordinal BETWEEN 1 AND 100000) "
            "AND resource_version BETWEEN 1 AND 2147483647",
            name="ck_kakao_question_bounds",
        ),
    )
    question_id: Mapped[str] = mapped_column(String(46), primary_key=True)
    owner_operator_id: Mapped[str] = mapped_column(String(41), nullable=False)
    source_binding_id: Mapped[str] = mapped_column(String(45), nullable=False)
    room_id: Mapped[str] = mapped_column(String(42), nullable=False)
    origin_source_revision_id: Mapped[str | None] = mapped_column(String(47))
    origin_candidate_ordinal: Mapped[int | None] = mapped_column(Integer)
    origin_occurrence_id: Mapped[str | None] = mapped_column(String(45))
    origin_composition_id: Mapped[str | None] = mapped_column(String(49))
    superseded_by_composition_id: Mapped[str | None] = mapped_column(String(49))
    current_revision_id: Mapped[str] = mapped_column(String(49), nullable=False)
    resource_version: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class KakaoQuestionCommandRecord(Base):
    __tablename__ = "kakao_question_commands"
    __table_args__ = (
        ForeignKeyConstraint(
            ["owner_operator_id", "source_binding_id", "room_id"],
            [
                "kakao_rooms.owner_operator_id",
                "kakao_rooms.source_binding_id",
                "kakao_rooms.room_id",
            ],
            name="fk_kakao_question_command_room",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["room_id", "mapping_revision_id"],
            [
                "kakao_room_mapping_revisions.room_id",
                "kakao_room_mapping_revisions.mapping_revision_id",
            ],
            name="fk_kakao_question_command_mapping",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "owner_operator_id",
            "idempotency_scope",
            "idempotency_key",
            name="uq_kakao_question_command_replay",
        ),
        UniqueConstraint(
            "command_id",
            "question_id",
            "question_revision_id",
            name="uq_kakao_question_command_result",
        ),
        CheckConstraint(
            "command_id ~ '^kakaocommand_[0-9a-f]{32}$' "
            "AND question_id ~ '^kakaoquestion_[0-9a-f]{32}$' "
            "AND question_revision_id ~ '^kakaoquestionrev_[0-9a-f]{32}$'",
            name="ck_kakao_question_command_ids",
        ),
        CheckConstraint(
            "request_sha256 ~ '^sha256:[0-9a-f]{64}$' AND idempotency_key ~ '^[!-~]{16,128}$'",
            name="ck_kakao_question_command_request",
        ),
        CheckConstraint(
            "(action = 'CREATE' AND expected_version = 0 AND previous_revision_id IS NULL) "
            "OR (action = 'EDIT' AND expected_version BETWEEN 1 AND 2147483646 "
            "AND previous_revision_id IS NOT NULL)",
            name="ck_kakao_question_command_parent",
        ),
        CheckConstraint(
            "(state = 'RESERVED' AND completed_at IS NULL) OR (state = 'COMPLETED' "
            "AND completed_at IS NOT NULL AND completed_at >= reserved_at)",
            name="ck_kakao_question_command_state",
        ),
    )
    command_id: Mapped[str] = mapped_column(String(45), primary_key=True)
    owner_operator_id: Mapped[str] = mapped_column(String(41), nullable=False)
    source_binding_id: Mapped[str] = mapped_column(String(45), nullable=False)
    room_id: Mapped[str] = mapped_column(String(42), nullable=False)
    idempotency_scope: Mapped[str] = mapped_column(String(96), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    action: Mapped[str] = mapped_column(String(16), nullable=False)
    question_id: Mapped[str] = mapped_column(String(46), nullable=False)
    question_revision_id: Mapped[str] = mapped_column(String(49), nullable=False)
    previous_revision_id: Mapped[str | None] = mapped_column(String(49))
    expected_version: Mapped[int] = mapped_column(Integer, nullable=False)
    mapping_revision_id: Mapped[str] = mapped_column(String(48), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    reserved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class KakaoQuestionRevisionRecord(Base):
    __tablename__ = "kakao_question_revisions"
    __table_args__ = (
        UniqueConstraint("question_id", "question_revision_id", name="uq_kakao_question_revision"),
        UniqueConstraint("question_id", "resource_version", name="uq_kakao_question_version"),
        UniqueConstraint(
            "question_id",
            "question_revision_id",
            "resource_version",
            name="uq_kakao_question_current_version",
        ),
        ForeignKeyConstraint(
            ["question_id", "room_id"],
            ["kakao_questions.question_id", "kakao_questions.room_id"],
            name="fk_kakao_question_revision_parent",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["question_id", "previous_revision_id"],
            [
                "kakao_question_revisions.question_id",
                "kakao_question_revisions.question_revision_id",
            ],
            name="fk_kakao_question_previous",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["command_id", "question_id", "question_revision_id"],
            [
                "kakao_question_commands.command_id",
                "kakao_question_commands.question_id",
                "kakao_question_commands.question_revision_id",
            ],
            name="fk_kakao_question_revision_command",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["composition_id", "question_id", "question_revision_id"],
            [
                "kakao_question_composition_outputs.composition_id",
                "kakao_question_composition_outputs.question_id",
                "kakao_question_composition_outputs.question_revision_id",
            ],
            name="fk_kakao_question_revision_composition",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "(command_id IS NOT NULL AND composition_id IS NULL) OR "
            "(command_id IS NULL AND composition_id IS NOT NULL AND resource_version = 1)",
            name="ck_kakao_question_revision_authority",
        ),
        ForeignKeyConstraint(
            ["room_id", "mapping_revision_id"],
            [
                "kakao_room_mapping_revisions.room_id",
                "kakao_room_mapping_revisions.mapping_revision_id",
            ],
            name="fk_kakao_question_revision_mapping",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["manifest_artifact_id", "manifest_artifact_revision_id"],
            ["artifact_revisions.logical_artifact_id", "artifact_revisions.revision_id"],
            name="fk_kakao_question_manifest",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "question_revision_id ~ '^kakaoquestionrev_[0-9a-f]{32}$' "
            "AND manifest_sha256 ~ '^sha256:[0-9a-f]{64}$'",
            name="ck_kakao_question_revision_ids",
        ),
        CheckConstraint(
            "(resource_version = 1 AND previous_revision_id IS NULL) OR "
            "(resource_version BETWEEN 2 AND 2147483647 AND previous_revision_id IS NOT NULL "
            "AND previous_revision_id <> question_revision_id)",
            name="ck_kakao_question_lineage",
        ),
        CheckConstraint(
            "review_state IN ('UNREVIEWED','CONFIRMED','EXCLUDED')", name="ck_kakao_question_review"
        ),
    )
    question_revision_id: Mapped[str] = mapped_column(String(49), primary_key=True)
    question_id: Mapped[str] = mapped_column(String(46), nullable=False)
    room_id: Mapped[str] = mapped_column(String(42), nullable=False)
    command_id: Mapped[str | None] = mapped_column(String(45))
    composition_id: Mapped[str | None] = mapped_column(String(49))
    previous_revision_id: Mapped[str | None] = mapped_column(String(49))
    resource_version: Mapped[int] = mapped_column(Integer, nullable=False)
    mapping_revision_id: Mapped[str] = mapped_column(String(48), nullable=False)
    review_state: Mapped[str] = mapped_column(String(16), nullable=False)
    first_student_at_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    manifest_artifact_id: Mapped[str] = mapped_column(String(41), nullable=False)
    manifest_artifact_revision_id: Mapped[str] = mapped_column(String(36), nullable=False)
    manifest_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    publication_job_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("jobs.job_id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
