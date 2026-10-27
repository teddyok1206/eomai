"""Immutable Catalog identity and indexed placements for mixed-source assemblies."""

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


class CuratedDocumentAssemblyRecord(Base):
    __tablename__ = "curated_document_assemblies"
    __table_args__ = (
        Index(
            "ix_curated_document_owner_recent",
            "created_by",
            text("created_at DESC"),
            text("assembly_id DESC"),
        ),
        ForeignKeyConstraint(
            ["assembly_id", "current_revision_id"],
            [
                "curated_document_assembly_revisions.assembly_id",
                "curated_document_assembly_revisions.assembly_revision_id",
            ],
            name="fk_curated_document_assembly_current_revision",
            use_alter=True,
        ),
    )

    assembly_id: Mapped[str] = mapped_column(String(41), primary_key=True)
    current_revision_id: Mapped[str | None] = mapped_column(String(44))
    created_by: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class CuratedDocumentAssemblyRevisionRecord(Base):
    __tablename__ = "curated_document_assembly_revisions"
    __table_args__ = (
        UniqueConstraint(
            "assembly_id", "revision_number", name="uq_curated_document_assembly_revision"
        ),
        UniqueConstraint(
            "assembly_id",
            "assembly_revision_id",
            name="uq_curated_document_assembly_revision_owner",
        ),
        UniqueConstraint(
            "created_by", "idempotency_key", name="uq_curated_document_assembly_replay"
        ),
        CheckConstraint("revision_number > 0", name="ck_curated_document_revision_number"),
        CheckConstraint("revision_state = 'INPUT_PINNED'", name="ck_curated_document_state"),
        CheckConstraint(
            "selection_sha256 ~ '^sha256:[0-9a-f]{64}$' AND "
            "request_sha256 ~ '^sha256:[0-9a-f]{64}$' AND "
            "manifest_sha256 ~ '^sha256:[0-9a-f]{64}$'",
            name="ck_curated_document_hashes",
        ),
        CheckConstraint(
            "jsonb_typeof(canonical_document) = 'object'",
            name="ck_curated_document_manifest_shape",
        ),
        Index("ix_curated_document_revision_assembly", "assembly_id", "revision_number"),
    )

    assembly_revision_id: Mapped[str] = mapped_column(String(44), primary_key=True)
    assembly_id: Mapped[str] = mapped_column(
        ForeignKey("curated_document_assemblies.assembly_id", ondelete="RESTRICT"), nullable=False
    )
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    previous_revision_id: Mapped[str | None] = mapped_column(
        ForeignKey("curated_document_assembly_revisions.assembly_revision_id", ondelete="RESTRICT")
    )
    revision_state: Mapped[str] = mapped_column(String(16), nullable=False)
    selection_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    request_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    manifest_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    canonical_document: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    created_by: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CuratedDocumentAssemblyPlacementRecord(Base):
    __tablename__ = "curated_document_assembly_placements"
    __table_args__ = (
        CheckConstraint("position BETWEEN 1 AND 200", name="ck_curated_placement_position"),
        CheckConstraint(
            "placement_kind IN ('EXTERNAL_SOURCE_DOCUMENT','REGISTERED_ITEM_REVISION',"
            "'PAST_EXAM_ITEM_REVISION')",
            name="ck_curated_placement_kind",
        ),
        CheckConstraint(
            "(placement_kind = 'EXTERNAL_SOURCE_DOCUMENT' AND source_id IS NOT NULL "
            "AND source_revision_id IS NOT NULL AND source_file_id IS NOT NULL "
            "AND item_id IS NULL AND item_revision_id IS NULL "
            "AND graph_snapshot_revision_id IS NULL) OR "
            "(placement_kind <> 'EXTERNAL_SOURCE_DOCUMENT' AND source_id IS NULL "
            "AND source_revision_id IS NULL AND source_file_id IS NULL "
            "AND item_id IS NOT NULL AND item_revision_id IS NOT NULL "
            "AND graph_snapshot_revision_id IS NOT NULL)",
            name="ck_curated_placement_pointer_shape",
        ),
        Index(
            "uq_curated_placement_external",
            "assembly_revision_id",
            "source_id",
            unique=True,
            postgresql_where=text("placement_kind = 'EXTERNAL_SOURCE_DOCUMENT'"),
        ),
        Index(
            "uq_curated_placement_item",
            "assembly_revision_id",
            "item_revision_id",
            unique=True,
            postgresql_where=text("placement_kind <> 'EXTERNAL_SOURCE_DOCUMENT'"),
        ),
        Index("ix_curated_placement_source_revision", "source_revision_id"),
        Index("ix_curated_placement_item_revision", "item_revision_id"),
    )

    assembly_revision_id: Mapped[str] = mapped_column(
        ForeignKey("curated_document_assembly_revisions.assembly_revision_id", ondelete="RESTRICT"),
        primary_key=True,
    )
    position: Mapped[int] = mapped_column(Integer, primary_key=True)
    placement_kind: Mapped[str] = mapped_column(String(40), nullable=False)
    source_id: Mapped[str | None] = mapped_column(
        ForeignKey("external_item_sources.source_id", ondelete="RESTRICT")
    )
    source_revision_id: Mapped[str | None] = mapped_column(
        ForeignKey("external_item_source_revisions.revision_id", ondelete="RESTRICT")
    )
    source_file_id: Mapped[str | None] = mapped_column(
        ForeignKey("content_intake_source_files.source_file_id", ondelete="RESTRICT")
    )
    item_id: Mapped[str | None] = mapped_column(ForeignKey("items.item_id", ondelete="RESTRICT"))
    item_revision_id: Mapped[str | None] = mapped_column(
        ForeignKey("item_revisions.item_revision_id", ondelete="RESTRICT")
    )
    graph_snapshot_revision_id: Mapped[str | None] = mapped_column(
        ForeignKey("knowledge_graph_snapshots.graph_snapshot_revision_id", ondelete="RESTRICT")
    )
