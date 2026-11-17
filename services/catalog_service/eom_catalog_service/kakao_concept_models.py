"""Private concept intents and two exact phase links; not an execution queue."""

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
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column


class KakaoConceptTaskRecord(Base):
    __tablename__ = "kakao_concept_tasks"
    __table_args__ = (
        UniqueConstraint("owner_operator_id", "idempotency_key", name="uq_kakao_concept_request"),
        ForeignKeyConstraint(
            ["owner_operator_id", "source_binding_id", "room_id"],
            [
                "kakao_rooms.owner_operator_id",
                "kakao_rooms.source_binding_id",
                "kakao_rooms.room_id",
            ],
            name="fk_kakao_concept_room",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["question_id", "room_id"],
            ["kakao_questions.question_id", "kakao_questions.room_id"],
            name="fk_kakao_concept_question",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["question_id", "question_revision_id"],
            [
                "kakao_question_revisions.question_id",
                "kakao_question_revisions.question_revision_id",
            ],
            name="fk_kakao_concept_revision",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["intent_artifact_id", "intent_artifact_revision_id"],
            ["artifact_revisions.logical_artifact_id", "artifact_revisions.revision_id"],
            name="fk_kakao_concept_intent",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "task_id ~ '^kakaoconcepttask_[0-9a-f]{32}$' "
            "AND request_sha256 ~ '^sha256:[0-9a-f]{64}$' "
            "AND idempotency_key ~ '^[!-~]{16,128}$' "
            "AND question_version BETWEEN 1 AND 2147483647",
            name="ck_kakao_concept_values",
        ),
        CheckConstraint(
            "jsonb_typeof(scope) = 'object' AND pg_column_size(scope) <= 2048",
            name="ck_kakao_concept_scope",
        ),
        CheckConstraint(
            "(intent_artifact_id IS NULL AND intent_artifact_revision_id IS NULL "
            "AND intent_sha256 IS NULL AND prepared_at IS NULL) OR "
            "(intent_artifact_id IS NOT NULL AND intent_artifact_revision_id IS NOT NULL "
            "AND intent_sha256 IS NOT NULL AND intent_sha256 ~ '^sha256:[0-9a-f]{64}$' "
            "AND prepared_at IS NOT NULL AND prepared_at >= created_at)",
            name="ck_kakao_concept_prepared",
        ),
        Index("ix_kakao_concept_history", "owner_operator_id", "source_binding_id", "task_id"),
    )
    task_id: Mapped[str] = mapped_column(String(49), primary_key=True)
    owner_operator_id: Mapped[str] = mapped_column(String(41), nullable=False)
    identity_session_id: Mapped[str] = mapped_column(String(64), nullable=False)
    source_binding_id: Mapped[str] = mapped_column(String(45), nullable=False)
    room_id: Mapped[str] = mapped_column(String(42), nullable=False)
    question_id: Mapped[str] = mapped_column(String(46), nullable=False)
    question_revision_id: Mapped[str] = mapped_column(String(49), nullable=False)
    question_version: Mapped[int] = mapped_column(Integer, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    scope: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    prepared_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    intent_artifact_id: Mapped[str | None] = mapped_column(String(41))
    intent_artifact_revision_id: Mapped[str | None] = mapped_column(String(36))
    intent_sha256: Mapped[str | None] = mapped_column(String(71))


class KakaoConceptPhaseRecord(Base):
    __tablename__ = "kakao_concept_phases"
    __table_args__ = (
        UniqueConstraint("workflow_id", name="uq_kakao_concept_phase_workflow"),
        CheckConstraint(
            "phase IN ('PLAN','COMPOSE') AND work_sha256 ~ '^sha256:[0-9a-f]{64}$'",
            name="ck_kakao_concept_phase_values",
        ),
        CheckConstraint(
            "jsonb_typeof(work_input) = 'object' AND pg_column_size(work_input) <= 65536 "
            "AND work_input ?& ARRAY['task_id','phase','request_member'] "
            "AND work_input->>'task_id' = task_id AND work_input->>'phase' = phase",
            name="ck_kakao_concept_phase_work",
        ),
        ForeignKeyConstraint(
            ["request_artifact_id", "request_artifact_revision_id"],
            ["artifact_revisions.logical_artifact_id", "artifact_revisions.revision_id"],
            name="fk_kakao_concept_phase_request",
            ondelete="RESTRICT",
        ),
    )
    task_id: Mapped[str] = mapped_column(
        String(49), ForeignKey("kakao_concept_tasks.task_id", ondelete="RESTRICT"), primary_key=True
    )
    phase: Mapped[str] = mapped_column(String(7), primary_key=True)
    work_input: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    work_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    request_artifact_id: Mapped[str] = mapped_column(String(41), nullable=False)
    request_artifact_revision_id: Mapped[str] = mapped_column(String(36), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    workflow_id: Mapped[str | None] = mapped_column(
        String(41), ForeignKey("workflow_instances.workflow_id", ondelete="RESTRICT")
    )
