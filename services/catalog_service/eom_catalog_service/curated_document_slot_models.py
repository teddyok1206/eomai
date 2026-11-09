"""V2 occurrence index of the existing curated Assembly aggregate."""

from __future__ import annotations

from typing import Any

from eom_orchestrator.models import Base
from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column


class CuratedDocumentAssemblySlotRecord(Base):
    __tablename__ = "curated_document_assembly_slots_v2"
    __table_args__ = (
        UniqueConstraint("assembly_revision_id", "position", name="uq_curated_slot_position"),
        ForeignKeyConstraint(
            ["assembly_revision_id", "manifest_schema_version"],
            [
                "curated_document_assembly_revisions.assembly_revision_id",
                "curated_document_assembly_revisions.manifest_schema_version",
            ],
            name="fk_curated_slot_v2_profile",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "manifest_schema_version = 'curated-document-assembly-manifest/2.0'",
            name="ck_curated_slot_v2_profile",
        ),
        CheckConstraint(
            "placement_id ~ '^placement_[0-9a-f]{32}$'", name="ck_curated_slot_identity"
        ),
        CheckConstraint("position BETWEEN 1 AND 100000", name="ck_curated_slot_position"),
        CheckConstraint(
            "(placement_kind = 'EMPTY' AND source_id IS NULL AND source_revision_id IS NULL "
            "AND item_id IS NULL AND item_revision_id IS NULL "
            "AND graph_snapshot_revision_id IS NULL) OR "
            "(placement_kind = 'EXTERNAL_SOURCE_DOCUMENT' AND source_id IS NOT NULL "
            "AND source_revision_id IS NOT NULL AND item_id IS NULL AND item_revision_id IS NULL "
            "AND graph_snapshot_revision_id IS NULL) OR (placement_kind IN "
            "('REGISTERED_ITEM_REVISION','PAST_EXAM_ITEM_REVISION') AND source_id IS NULL "
            "AND source_revision_id IS NULL AND item_id IS NOT NULL "
            "AND item_revision_id IS NOT NULL "
            "AND graph_snapshot_revision_id IS NOT NULL)",
            name="ck_curated_slot_target",
        ),
        CheckConstraint(
            "jsonb_typeof(canonical_slot) = 'object' "
            "AND octet_length(canonical_slot::text) <= 16384 "
            "AND canonical_slot ?& ARRAY['placement_id','position','target'] "
            "AND canonical_slot->'target' ? 'placement_kind' "
            "AND canonical_slot->>'placement_id' = placement_id "
            "AND (canonical_slot->>'position')::integer = position "
            "AND canonical_slot->'target'->>'placement_kind' = placement_kind "
            "AND (canonical_slot->'target'->>'item_id') IS NOT DISTINCT FROM item_id "
            "AND (canonical_slot->'target'->>'item_revision_id') "
            "IS NOT DISTINCT FROM item_revision_id "
            "AND (canonical_slot->'target'->>'source_id') IS NOT DISTINCT FROM source_id "
            "AND (canonical_slot->'target'->>'source_revision_id') "
            "IS NOT DISTINCT FROM source_revision_id "
            "AND (canonical_slot->'target'->>'graph_snapshot_revision_id') "
            "IS NOT DISTINCT FROM graph_snapshot_revision_id",
            name="ck_curated_slot_small_pointer",
        ),
        Index(
            "ix_curated_slot_item",
            "item_id",
            "assembly_revision_id",
            "placement_id",
            postgresql_where=text("item_id IS NOT NULL"),
        ),
        Index(
            "ix_curated_slot_source",
            "source_id",
            "assembly_revision_id",
            "placement_id",
            postgresql_where=text("source_id IS NOT NULL"),
        ),
        Index(
            "ix_curated_slot_item_revision",
            "item_revision_id",
            "assembly_revision_id",
            postgresql_where=text("item_revision_id IS NOT NULL"),
        ),
        Index(
            "ix_curated_slot_source_revision",
            "source_revision_id",
            "assembly_revision_id",
            postgresql_where=text("source_revision_id IS NOT NULL"),
        ),
    )

    assembly_revision_id: Mapped[str] = mapped_column(String(44), primary_key=True)
    placement_id: Mapped[str] = mapped_column(String(42), primary_key=True)
    manifest_schema_version: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=text("'curated-document-assembly-manifest/2.0'")
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    placement_kind: Mapped[str] = mapped_column(String(40), nullable=False)
    source_id: Mapped[str | None] = mapped_column(
        ForeignKey("external_item_sources.source_id", ondelete="RESTRICT")
    )
    source_revision_id: Mapped[str | None] = mapped_column(
        ForeignKey("external_item_source_revisions.revision_id", ondelete="RESTRICT")
    )
    item_id: Mapped[str | None] = mapped_column(ForeignKey("items.item_id", ondelete="RESTRICT"))
    item_revision_id: Mapped[str | None] = mapped_column(
        ForeignKey("item_revisions.item_revision_id", ondelete="RESTRICT")
    )
    graph_snapshot_revision_id: Mapped[str | None] = mapped_column(
        ForeignKey("knowledge_graph_snapshots.graph_snapshot_revision_id", ondelete="RESTRICT")
    )
    canonical_slot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
