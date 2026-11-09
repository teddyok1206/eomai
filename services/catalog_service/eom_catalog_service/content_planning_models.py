"""Indexed Edition/Form ownership over existing Deliverable and curated identities."""

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
    Sequence,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

# The legacy Product table has one integer revision namespace per Product.
# Edition display sequences remain independent; allocating the storage ordinal
# from a sequence avoids serializing edits to different editions of one Product.
CONTENT_PRODUCT_REVISION_SEQUENCE = Sequence(
    "content_product_revision_number_seq", metadata=Base.metadata
)


class ContentEditionRecord(Base):
    __tablename__ = "content_editions"
    __table_args__ = (
        UniqueConstraint("edition_id", "deliverable_id", name="uq_content_edition_owner"),
        UniqueConstraint("deliverable_id", "edition_key", name="uq_content_edition_key"),
        ForeignKeyConstraint(
            ["edition_id", "deliverable_id", "current_revision_id"],
            [
                "content_edition_revisions.edition_id",
                "content_edition_revisions.deliverable_id",
                "content_edition_revisions.deliverable_revision_id",
            ],
            name="fk_content_edition_current_revision",
            use_alter=True,
            ondelete="RESTRICT",
        ),
        CheckConstraint("lock_version > 0", name="ck_content_edition_lock"),
        CheckConstraint(
            "lifecycle_state IN ('ACTIVE','ARCHIVED')", name="ck_content_edition_state"
        ),
        Index("ix_content_edition_product", "deliverable_id", "edition_id"),
    )

    edition_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    deliverable_id: Mapped[str] = mapped_column(
        ForeignKey("deliverables.deliverable_id", ondelete="RESTRICT"), nullable=False
    )
    edition_key: Mapped[str] = mapped_column(String(128), nullable=False)
    current_revision_id: Mapped[str | None] = mapped_column(String(41))
    lock_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    lifecycle_state: Mapped[str] = mapped_column(String(16), nullable=False)
    created_by: Mapped[str] = mapped_column(
        ForeignKey("operators.operator_id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ContentEditionRevisionRecord(Base):
    """Typed membership/index of an immutable Deliverable revision's metadata."""

    __tablename__ = "content_edition_revisions"
    __table_args__ = (
        UniqueConstraint(
            "edition_id", "revision_number", name="uq_content_edition_revision_number"
        ),
        UniqueConstraint(
            "edition_id",
            "deliverable_id",
            "deliverable_revision_id",
            name="uq_content_edition_revision_owner",
        ),
        UniqueConstraint(
            "edition_id", "deliverable_revision_id", name="uq_content_edition_revision_member"
        ),
        ForeignKeyConstraint(
            ["edition_id", "deliverable_id"],
            ["content_editions.edition_id", "content_editions.deliverable_id"],
            name="fk_content_revision_edition",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["deliverable_revision_id", "deliverable_id"],
            [
                "deliverable_revisions.deliverable_revision_id",
                "deliverable_revisions.deliverable_id",
            ],
            name="fk_content_revision_product",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["edition_id", "previous_revision_id"],
            [
                "content_edition_revisions.edition_id",
                "content_edition_revisions.deliverable_revision_id",
            ],
            name="fk_content_revision_predecessor",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "revision_number > 0 AND ((revision_number = 1) = (previous_revision_id IS NULL))",
            name="ck_content_revision_chain",
        ),
        CheckConstraint(
            "academic_year IS NULL OR academic_year BETWEEN 1900 AND 3000",
            name="ck_content_revision_year",
        ),
        CheckConstraint(
            "composition_sha256 ~ '^sha256:[0-9a-f]{64}$'", name="ck_content_revision_hash"
        ),
        Index("ix_content_revision_year", "academic_year", "deliverable_revision_id"),
    )

    deliverable_revision_id: Mapped[str] = mapped_column(String(41), primary_key=True)
    deliverable_id: Mapped[str] = mapped_column(String(44), nullable=False)
    edition_id: Mapped[str] = mapped_column(String(40), nullable=False)
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    previous_revision_id: Mapped[str | None] = mapped_column(String(41))
    academic_year: Mapped[int | None] = mapped_column(Integer)
    composition_sha256: Mapped[str] = mapped_column(String(71), nullable=False)


class ContentFormMembershipRecord(Base):
    __tablename__ = "content_form_memberships"
    __table_args__ = (
        UniqueConstraint("assessment_form_id", "edition_id", name="uq_content_form_edition"),
        UniqueConstraint("assembly_id", name="uq_content_form_curated_assembly"),
        UniqueConstraint(
            "assessment_form_id", "assembly_id", name="uq_content_form_assembly_owner"
        ),
        ForeignKeyConstraint(
            ["assessment_form_id", "deliverable_id"],
            ["assessment_forms.assessment_form_id", "assessment_forms.deliverable_id"],
            name="fk_content_form_product",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["edition_id", "deliverable_id"],
            ["content_editions.edition_id", "content_editions.deliverable_id"],
            name="fk_content_form_edition",
            ondelete="RESTRICT",
        ),
        Index("ix_content_form_edition", "edition_id", "assessment_form_id"),
    )

    assessment_form_id: Mapped[str] = mapped_column(String(37), primary_key=True)
    deliverable_id: Mapped[str] = mapped_column(String(44), nullable=False)
    edition_id: Mapped[str] = mapped_column(String(40), nullable=False)
    assembly_id: Mapped[str] = mapped_column(
        ForeignKey("curated_document_assemblies.assembly_id", ondelete="RESTRICT"), nullable=False
    )


class ContentFormRevisionCompositionRecord(Base):
    __tablename__ = "content_form_revision_compositions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["assessment_form_id", "assembly_id"],
            ["content_form_memberships.assessment_form_id", "content_form_memberships.assembly_id"],
            name="fk_content_form_revision_assembly_owner",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "edition_id",
            "section_id",
            "assessment_form_revision_id",
            name="uq_content_form_revision_scope",
        ),
        ForeignKeyConstraint(
            ["assessment_form_revision_id", "assessment_form_id"],
            [
                "assessment_form_revisions.assessment_form_revision_id",
                "assessment_form_revisions.assessment_form_id",
            ],
            name="fk_content_form_revision_identity",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["assessment_form_id", "edition_id"],
            ["content_form_memberships.assessment_form_id", "content_form_memberships.edition_id"],
            name="fk_content_form_revision_edition",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["assembly_id", "assembly_revision_id", "manifest_sha256"],
            [
                "curated_document_assembly_revisions.assembly_id",
                "curated_document_assembly_revisions.assembly_revision_id",
                "curated_document_assembly_revisions.manifest_sha256",
            ],
            name="fk_content_form_revision_assembly",
            ondelete="RESTRICT",
        ),
        CheckConstraint("placement_count BETWEEN 0 AND 100000", name="ck_content_form_slot_count"),
        Index("ix_content_form_revision_assembly", "assembly_revision_id"),
    )

    assessment_form_revision_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    assessment_form_id: Mapped[str] = mapped_column(String(37), nullable=False)
    edition_id: Mapped[str] = mapped_column(String(40), nullable=False)
    section_id: Mapped[str] = mapped_column(String(40), nullable=False)
    assembly_id: Mapped[str] = mapped_column(String(41), nullable=False)
    assembly_revision_id: Mapped[str] = mapped_column(String(44), nullable=False)
    manifest_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    placement_count: Mapped[int] = mapped_column(Integer, nullable=False)


class ContentEditionRevisionFormRecord(Base):
    __tablename__ = "content_edition_revision_forms"
    __table_args__ = (
        UniqueConstraint(
            "deliverable_revision_id", "leaf_order", name="uq_content_revision_leaf_order"
        ),
        UniqueConstraint(
            "deliverable_revision_id",
            "assessment_form_revision_id",
            name="uq_content_revision_leaf_form",
        ),
        ForeignKeyConstraint(
            ["edition_id", "deliverable_revision_id"],
            [
                "content_edition_revisions.edition_id",
                "content_edition_revisions.deliverable_revision_id",
            ],
            name="fk_content_leaf_edition_revision",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["edition_id", "section_id", "assessment_form_revision_id"],
            [
                "content_form_revision_compositions.edition_id",
                "content_form_revision_compositions.section_id",
                "content_form_revision_compositions.assessment_form_revision_id",
            ],
            name="fk_content_leaf_form_scope",
            ondelete="RESTRICT",
        ),
        CheckConstraint("leaf_order BETWEEN 1 AND 10000", name="ck_content_leaf_order"),
        Index(
            "ix_content_leaf_form_revision",
            "assessment_form_revision_id",
            "deliverable_revision_id",
        ),
    )

    deliverable_revision_id: Mapped[str] = mapped_column(String(41), primary_key=True)
    section_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    edition_id: Mapped[str] = mapped_column(String(40), nullable=False)
    assessment_form_revision_id: Mapped[str] = mapped_column(String(40), nullable=False)
    leaf_order: Mapped[int] = mapped_column(Integer, nullable=False)


class ContentPlanningEventRecord(Base):
    __tablename__ = "content_planning_events"
    __table_args__ = (
        CheckConstraint("sequence > 0", name="ck_content_event_sequence"),
        ForeignKeyConstraint(
            ["edition_id", "before_revision_id"],
            [
                "content_edition_revisions.edition_id",
                "content_edition_revisions.deliverable_revision_id",
            ],
            name="fk_content_event_before",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["edition_id", "after_revision_id"],
            [
                "content_edition_revisions.edition_id",
                "content_edition_revisions.deliverable_revision_id",
            ],
            name="fk_content_event_after",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "jsonb_typeof(change_summary) = 'object' "
            "AND octet_length(change_summary::text) <= 1048576",
            name="ck_content_event_small_metadata",
        ),
    )

    edition_id: Mapped[str] = mapped_column(
        ForeignKey("content_editions.edition_id", ondelete="RESTRICT"), primary_key=True
    )
    sequence: Mapped[int] = mapped_column(Integer, primary_key=True)
    command_kind: Mapped[str] = mapped_column(String(64), nullable=False)
    before_revision_id: Mapped[str | None] = mapped_column(String(41))
    after_revision_id: Mapped[str] = mapped_column(String(41), nullable=False)
    change_summary: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    actor_id: Mapped[str] = mapped_column(
        ForeignKey("operators.operator_id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ContentPlanningCommandReceiptRecord(Base):
    __tablename__ = "content_planning_command_receipts"
    __table_args__ = (
        CheckConstraint("idempotency_key ~ '^[!-~]{16,128}$'", name="ck_content_command_key"),
        CheckConstraint("request_sha256 ~ '^sha256:[0-9a-f]{64}$'", name="ck_content_command_hash"),
        CheckConstraint(
            "jsonb_typeof(result_pointer) = 'object' "
            "AND octet_length(result_pointer::text) <= 16384",
            name="ck_content_command_small_pointer",
        ),
    )

    actor_id: Mapped[str] = mapped_column(
        ForeignKey("operators.operator_id", ondelete="RESTRICT"), primary_key=True
    )
    command_kind: Mapped[str] = mapped_column(String(64), primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), primary_key=True)
    request_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    result_pointer: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
