"""Append-only print facts and normalized exact Form scopes; no publication guesses."""

from __future__ import annotations

from datetime import datetime
from typing import Any

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
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column


class ContentPrintRecord(Base):
    __tablename__ = "content_print_records"
    __table_args__ = (
        UniqueConstraint("print_record_id", "edition_id", name="uq_content_print_edition"),
        ForeignKeyConstraint(
            ["edition_id", "deliverable_revision_id"],
            [
                "content_edition_revisions.edition_id",
                "content_edition_revisions.deliverable_revision_id",
            ],
            name="fk_content_print_revision",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["predecessor_print_record_id", "edition_id"],
            ["content_print_records.print_record_id", "content_print_records.edition_id"],
            name="fk_content_print_predecessor",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "(intent = 'INITIAL' AND predecessor_print_record_id IS NULL) OR "
            "(intent IN ('REPRINT','CORRECTION') AND predecessor_print_record_id IS NOT NULL "
            "AND predecessor_print_record_id <> print_record_id)",
            name="ck_content_print_intent",
        ),
        CheckConstraint(
            "scope_sha256 ~ '^sha256:[0-9a-f]{64}$' AND record_sha256 ~ '^sha256:[0-9a-f]{64}$'",
            name="ck_content_print_hashes",
        ),
        CheckConstraint("jsonb_typeof(canonical_record) = 'object'", name="ck_content_print_shape"),
        Index(
            "uq_content_print_initial",
            "edition_id",
            "scope_sha256",
            unique=True,
            postgresql_where=text("intent = 'INITIAL'"),
        ),
        Index(
            "ix_content_print_edition_recent",
            "edition_id",
            text("recorded_at DESC"),
            "print_record_id",
        ),
        Index("ix_content_print_revision", "deliverable_revision_id"),
    )

    print_record_id: Mapped[str] = mapped_column(String(38), primary_key=True)
    edition_id: Mapped[str] = mapped_column(String(40), nullable=False)
    deliverable_revision_id: Mapped[str] = mapped_column(String(41), nullable=False)
    scope_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    intent: Mapped[str] = mapped_column(String(16), nullable=False)
    predecessor_print_record_id: Mapped[str | None] = mapped_column(String(38))
    canonical_record: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    record_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    recorded_by: Mapped[str] = mapped_column(
        ForeignKey("operators.operator_id", ondelete="RESTRICT"), nullable=False
    )
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ContentPrintScopeRecord(Base):
    __tablename__ = "content_print_scopes"
    __table_args__ = (
        UniqueConstraint("print_record_id", "scope_order", name="uq_content_print_scope_order"),
        UniqueConstraint("print_record_id", "section_id", name="uq_content_print_scope_section"),
        ForeignKeyConstraint(
            ["print_record_id", "edition_id"],
            ["content_print_records.print_record_id", "content_print_records.edition_id"],
            name="fk_content_print_scope_owner",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["edition_id", "section_id", "assessment_form_revision_id"],
            [
                "content_form_revision_compositions.edition_id",
                "content_form_revision_compositions.section_id",
                "content_form_revision_compositions.assessment_form_revision_id",
            ],
            name="fk_content_print_scope_form",
            ondelete="RESTRICT",
        ),
        CheckConstraint("scope_order BETWEEN 1 AND 10000", name="ck_content_print_scope_order"),
        Index("ix_content_print_scope_form", "assessment_form_revision_id", "print_record_id"),
    )

    print_record_id: Mapped[str] = mapped_column(String(38), primary_key=True)
    assessment_form_revision_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    edition_id: Mapped[str] = mapped_column(String(40), nullable=False)
    section_id: Mapped[str] = mapped_column(String(40), nullable=False)
    scope_order: Mapped[int] = mapped_column(Integer, nullable=False)


class ContentPrintEventRecord(Base):
    __tablename__ = "content_print_events"
    __table_args__ = (
        UniqueConstraint("print_record_id", name="uq_content_print_terminal_event"),
        CheckConstraint("sequence > 0", name="ck_content_print_event_sequence"),
        CheckConstraint(
            "(event_kind = 'VOID_RECORD' AND replacement_print_record_id IS NULL) OR "
            "(event_kind = 'CORRECT_RECORD' AND replacement_print_record_id IS NOT NULL "
            "AND replacement_print_record_id <> print_record_id)",
            name="ck_content_print_event_kind",
        ),
        CheckConstraint("length(reason) BETWEEN 1 AND 2000", name="ck_content_print_event_reason"),
    )

    print_record_id: Mapped[str] = mapped_column(
        ForeignKey("content_print_records.print_record_id", ondelete="RESTRICT"), primary_key=True
    )
    sequence: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    replacement_print_record_id: Mapped[str | None] = mapped_column(
        ForeignKey("content_print_records.print_record_id", ondelete="RESTRICT")
    )
    reason: Mapped[str] = mapped_column(String(2000), nullable=False)
    actor_id: Mapped[str] = mapped_column(
        ForeignKey("operators.operator_id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
