"""Indexed lineage from an immutable selected scope to a derived curated input."""

from datetime import datetime
from typing import Any

from eom_orchestrator.models import Base
from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column


class ContentDeliveryScopeRecord(Base):
    __tablename__ = "content_delivery_scopes"
    __table_args__ = (
        ForeignKeyConstraint(
            ["edition_id", "deliverable_revision_id"],
            [
                "content_edition_revisions.edition_id",
                "content_edition_revisions.deliverable_revision_id",
            ],
            name="fk_content_delivery_edition_revision",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["assembly_id", "assembly_revision_id"],
            [
                "curated_document_assembly_revisions.assembly_id",
                "curated_document_assembly_revisions.assembly_revision_id",
            ],
            name="fk_content_delivery_assembly_revision",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "deliverable_revision_id", "scope_sha256", name="uq_content_delivery_scope"
        ),
        UniqueConstraint("assembly_id", name="uq_content_delivery_assembly"),
        CheckConstraint(
            "scope_sha256 ~ '^sha256:[0-9a-f]{64}$'", name="ck_content_delivery_scope_hash"
        ),
        CheckConstraint(
            "jsonb_typeof(canonical_scope) = 'object' AND "
            "octet_length(canonical_scope::text) <= 4194304",
            name="ck_content_delivery_scope_budget",
        ),
        Index("ix_content_delivery_edition", "edition_id", "created_at", "assembly_revision_id"),
    )
    assembly_revision_id: Mapped[str] = mapped_column(String(44), primary_key=True)
    assembly_id: Mapped[str] = mapped_column(String(41), nullable=False)
    edition_id: Mapped[str] = mapped_column(String(40), nullable=False)
    deliverable_revision_id: Mapped[str] = mapped_column(String(41), nullable=False)
    scope_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    canonical_scope: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
