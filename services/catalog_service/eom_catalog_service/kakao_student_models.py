"""Private student directory: small identity/display revisions, no message content."""

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


class KakaoStudentRecord(Base):
    __tablename__ = "kakao_students"
    __table_args__ = (
        CheckConstraint("student_id ~ '^kakaostudent_[0-9a-f]{32}$'", name="ck_kakao_student_id"),
        CheckConstraint("resource_version >= 1", name="ck_kakao_student_version"),
        CheckConstraint("state IN ('ACTIVE','RETIRED')", name="ck_kakao_student_state"),
        UniqueConstraint("owner_operator_id", "student_id", name="uq_kakao_student_owner"),
        ForeignKeyConstraint(
            ["student_id", "current_display_revision_id"],
            [
                "kakao_student_display_revisions.student_id",
                "kakao_student_display_revisions.display_revision_id",
            ],
            name="fk_kakao_student_current",
            ondelete="RESTRICT",
            use_alter=True,
            deferrable=True,
            initially="DEFERRED",
        ),
    )
    student_id: Mapped[str] = mapped_column(String(45), primary_key=True)
    owner_operator_id: Mapped[str] = mapped_column(
        String(41), ForeignKey("operators.operator_id", ondelete="RESTRICT"), nullable=False
    )
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    resource_version: Mapped[int] = mapped_column(Integer, nullable=False)
    current_display_revision_id: Mapped[str] = mapped_column(String(48), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class KakaoStudentDisplayRevisionRecord(Base):
    __tablename__ = "kakao_student_display_revisions"
    __table_args__ = (
        CheckConstraint(
            "display_revision_id ~ '^kakaostudentrev_[0-9a-f]{32}$'",
            name="ck_kakao_student_display_id",
        ),
        CheckConstraint("sha256 ~ '^sha256:[0-9a-f]{64}$'", name="ck_kakao_student_display_hash"),
        CheckConstraint("state IN ('ACTIVE','RETIRED')", name="ck_kakao_student_display_state"),
        CheckConstraint(
            "length(btrim(display_name)) > 0 AND display_name !~ '[[:cntrl:]]'",
            name="ck_kakao_student_display_name",
        ),
        CheckConstraint(
            "(revision_number = 1 AND previous_revision_id IS NULL) OR "
            "(revision_number > 1 AND previous_revision_id IS NOT NULL "
            "AND previous_revision_id <> display_revision_id)",
            name="ck_kakao_student_display_lineage",
        ),
        UniqueConstraint(
            "student_id", "display_revision_id", name="uq_kakao_student_display_parent"
        ),
        UniqueConstraint("student_id", "revision_number", name="uq_kakao_student_display_number"),
        ForeignKeyConstraint(
            ["student_id", "previous_revision_id"],
            [
                "kakao_student_display_revisions.student_id",
                "kakao_student_display_revisions.display_revision_id",
            ],
            name="fk_kakao_student_display_previous",
            ondelete="RESTRICT",
        ),
    )
    display_revision_id: Mapped[str] = mapped_column(String(48), primary_key=True)
    student_id: Mapped[str] = mapped_column(
        String(45), ForeignKey("kakao_students.student_id", ondelete="RESTRICT"), nullable=False
    )
    previous_revision_id: Mapped[str | None] = mapped_column(String(48))
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_by: Mapped[str] = mapped_column(
        String(41), ForeignKey("operators.operator_id", ondelete="RESTRICT"), nullable=False
    )


class KakaoStudentCommandRecord(Base):
    __tablename__ = "kakao_student_commands"
    __table_args__ = (
        CheckConstraint(
            "command_id ~ '^kakaocommand_[0-9a-f]{32}$'", name="ck_kakao_student_command_id"
        ),
        CheckConstraint(
            "action IN ('CREATE','RENAME','RETIRE')", name="ck_kakao_student_command_action"
        ),
        CheckConstraint(
            "request_sha256 ~ '^sha256:[0-9a-f]{64}$' AND idempotency_key ~ '^[!-~]{16,128}$'",
            name="ck_kakao_student_command_request",
        ),
        UniqueConstraint(
            "owner_operator_id",
            "idempotency_scope",
            "idempotency_key",
            name="uq_kakao_student_command_replay",
        ),
        UniqueConstraint(
            "student_id", "result_display_revision_id", name="uq_kakao_student_command_result"
        ),
        ForeignKeyConstraint(
            ["owner_operator_id", "student_id"],
            ["kakao_students.owner_operator_id", "kakao_students.student_id"],
            name="fk_kakao_student_command_owner",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["student_id", "result_display_revision_id"],
            [
                "kakao_student_display_revisions.student_id",
                "kakao_student_display_revisions.display_revision_id",
            ],
            name="fk_kakao_student_command_result",
            ondelete="RESTRICT",
        ),
    )
    command_id: Mapped[str] = mapped_column(String(45), primary_key=True)
    owner_operator_id: Mapped[str] = mapped_column(String(41), nullable=False)
    student_id: Mapped[str] = mapped_column(String(45), nullable=False)
    idempotency_scope: Mapped[str] = mapped_column(String(96), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    request_id: Mapped[str] = mapped_column(String(128), nullable=False)
    action: Mapped[str] = mapped_column(String(16), nullable=False)
    result_display_revision_id: Mapped[str] = mapped_column(String(48), nullable=False)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
