"""Catalog-owned immutable external Item source revisions and import identity."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from eom_orchestrator.models import Base
from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

USABLE_EXTERNAL_ITEM_INTAKE_STATES = frozenset(
    {
        "ANALYSIS_PENDING",
        "ANALYSIS_ATTACHED",
        "VALIDATING",
        "NEEDS_DECISION",
        "ACCEPTED",
        "IMPORTED",
    }
)


class ExternalItemImportRecord(Base):
    __tablename__ = "external_item_imports"
    __table_args__ = (
        CheckConstraint(
            "state IN ('PREPARED','IMPORTING','PARTIAL','COMPLETED','FAILED')",
            name="ck_external_item_import_state",
        ),
        CheckConstraint("row_count >= 0", name="ck_external_item_import_row_count"),
        CheckConstraint(
            "jsonb_typeof(mapping_document) = 'object'",
            name="ck_external_item_import_mapping_shape",
        ),
        CheckConstraint(
            "request_sha256 ~ '^sha256:[0-9a-f]{64}$' AND "
            "workbook_sha256 ~ '^sha256:[0-9a-f]{64}$' AND "
            "archive_sha256 ~ '^sha256:[0-9a-f]{64}$' AND "
            "mapping_sha256 ~ '^sha256:[0-9a-f]{64}$'",
            name="ck_external_item_import_hashes",
        ),
        UniqueConstraint("request_sha256", name="uq_external_item_import_request"),
        Index("ix_external_item_import_namespace_created", "source_namespace", "created_at"),
    )

    import_id: Mapped[str] = mapped_column(String(42), primary_key=True)
    source_namespace: Mapped[str] = mapped_column(String(128), nullable=False)
    request_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    workbook_artifact_id: Mapped[str] = mapped_column(
        ForeignKey("artifacts.logical_artifact_id"), nullable=False
    )
    workbook_source_file_id: Mapped[str] = mapped_column(
        ForeignKey("content_intake_source_files.source_file_id"), nullable=False
    )
    workbook_artifact_revision_id: Mapped[str] = mapped_column(
        ForeignKey("artifact_revisions.revision_id"), nullable=False
    )
    workbook_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    archive_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    mapping_revision_id: Mapped[str] = mapped_column(String(46), nullable=False)
    mapping_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    mapping_document: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False)
    created_by: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class ExternalItemSourceRecord(Base):
    __tablename__ = "external_item_sources"
    __table_args__ = (
        UniqueConstraint(
            "source_namespace", "external_number", name="uq_external_item_source_number"
        ),
        CheckConstraint("external_number ~ '^[0-9]{5}$'", name="ck_external_item_source_number"),
        Index("ix_external_item_source_current", "current_revision_id"),
    )

    source_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    source_namespace: Mapped[str] = mapped_column(String(128), nullable=False)
    external_number: Mapped[str] = mapped_column(String(5), nullable=False)
    current_revision_id: Mapped[str | None] = mapped_column(
        ForeignKey(
            "external_item_source_revisions.revision_id",
            name="fk_external_item_source_current_revision",
            use_alter=True,
        ),
        nullable=True,
    )
    created_by: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ExternalItemSourceRevisionRecord(Base):
    __tablename__ = "external_item_source_revisions"
    __table_args__ = (
        UniqueConstraint("source_id", "revision_number", name="uq_external_item_source_revision"),
        UniqueConstraint("import_id", "row_number", name="uq_external_item_import_row"),
        UniqueConstraint("import_id", "external_number", name="uq_external_item_import_number"),
        CheckConstraint("revision_number > 0", name="ck_external_item_revision_number"),
        CheckConstraint("row_number >= 2", name="ck_external_item_row_number"),
        CheckConstraint(
            "jsonb_typeof(cells) = 'array' AND jsonb_array_length(cells) = 32",
            name="ck_external_item_cells_shape",
        ),
        CheckConstraint(
            "external_number ~ '^[0-9]{5}$'",
            name="ck_external_item_revision_external_number",
        ),
        CheckConstraint(
            "observation_sha256 ~ '^sha256:[0-9a-f]{64}$'",
            name="ck_external_item_observation_hash",
        ),
        CheckConstraint(
            "match_status IN ('MATCHED','MATCHED_DETECTED_HWPX','MATCHED_IDENTICAL_COPIES',"
            "'REJECTED','REJECTION_AMBIGUOUS','DRAFT_ONLY','LINK_UNSUPPORTED',"
            "'DOCUMENT_MISSING','NAME_MISMATCH','CONTENT_CONFLICT','FORMAT_MISMATCH')",
            name="ck_external_item_match_status",
        ),
        CheckConstraint(
            "(match_status IN ('MATCHED','MATCHED_DETECTED_HWPX',"
            "'MATCHED_IDENTICAL_COPIES') AND selected_source_file_id IS NOT NULL) "
            "OR (match_status NOT IN ('MATCHED','MATCHED_DETECTED_HWPX',"
            "'MATCHED_IDENTICAL_COPIES') AND selected_source_file_id IS NULL)",
            name="ck_external_item_selected_file_state",
        ),
        Index("ix_external_item_revision_status", "match_status", "source_id"),
        Index("ix_external_item_revision_major_unit", "unit_major", "source_id"),
        Index("ix_external_item_revision_field", "field_label", "source_id"),
    )

    revision_id: Mapped[str] = mapped_column(String(43), primary_key=True)
    source_id: Mapped[str] = mapped_column(
        ForeignKey("external_item_sources.source_id"), nullable=False
    )
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    previous_revision_id: Mapped[str | None] = mapped_column(
        ForeignKey("external_item_source_revisions.revision_id"), nullable=True
    )
    import_id: Mapped[str] = mapped_column(
        ForeignKey("external_item_imports.import_id"), nullable=False, index=True
    )
    external_number: Mapped[str] = mapped_column(String(5), nullable=False)
    worksheet_name: Mapped[str] = mapped_column(String(128), nullable=False)
    row_number: Mapped[int] = mapped_column(Integer, nullable=False)
    observation_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    cells: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    match_status: Mapped[str] = mapped_column(String(32), nullable=False)
    selected_source_file_id: Mapped[str | None] = mapped_column(
        String(43), ForeignKey("content_intake_source_files.source_file_id"), nullable=True
    )
    unit_major: Mapped[str | None] = mapped_column(String(255), nullable=True)
    unit_minor: Mapped[str | None] = mapped_column(String(255), nullable=True)
    field_label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    grade_label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    author_label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_by: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ExternalItemEditionDocumentRecord(Base):
    """Pinned original 1/2/3교 file link, including unresolved source observations."""

    __tablename__ = "external_item_edition_documents"
    __table_args__ = (
        UniqueConstraint("source_revision_id", "edition", name="uq_external_item_edition"),
        CheckConstraint("edition BETWEEN 1 AND 3", name="ck_external_item_edition_number"),
        CheckConstraint(
            "match_status IN ('MATCHED','MATCHED_DETECTED_HWPX','MATCHED_IDENTICAL_COPIES',"
            "'LINK_UNSUPPORTED','DOCUMENT_MISSING','NAME_MISMATCH','CONTENT_CONFLICT',"
            "'FORMAT_MISMATCH')",
            name="ck_external_item_edition_status",
        ),
        CheckConstraint(
            "(match_status IN ('MATCHED','MATCHED_DETECTED_HWPX',"
            "'MATCHED_IDENTICAL_COPIES') AND source_file_id IS NOT NULL AND "
            "document_sha256 IS NOT NULL) OR "
            "(match_status NOT IN ('MATCHED','MATCHED_DETECTED_HWPX',"
            "'MATCHED_IDENTICAL_COPIES') AND source_file_id IS NULL AND "
            "document_sha256 IS NULL)",
            name="ck_external_item_edition_file_state",
        ),
        CheckConstraint(
            "document_sha256 IS NULL OR document_sha256 ~ '^sha256:[0-9a-f]{64}$'",
            name="ck_external_item_edition_hash",
        ),
        Index("ix_external_item_edition_source_file", "source_file_id"),
    )

    edition_document_id: Mapped[str] = mapped_column(String(43), primary_key=True)
    source_revision_id: Mapped[str] = mapped_column(
        ForeignKey("external_item_source_revisions.revision_id"), nullable=False
    )
    edition: Mapped[int] = mapped_column(Integer, nullable=False)
    match_status: Mapped[str] = mapped_column(String(32), nullable=False)
    source_file_id: Mapped[str | None] = mapped_column(
        ForeignKey("content_intake_source_files.source_file_id"), nullable=True
    )
    document_sha256: Mapped[str | None] = mapped_column(String(71), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
