"""Persistence records for immutable Product/Form/Assembly/Publication usage intake."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from eom_orchestrator.models import Base
from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column


class AssessmentFormRecord(Base):
    __tablename__ = "assessment_forms"
    __table_args__ = (
        UniqueConstraint("deliverable_id", "form_key", name="uq_assessment_form_product_key"),
        CheckConstraint(
            "lifecycle_state IN ('ACTIVE','RETIRED')", name="ck_assessment_forms_state"
        ),
    )

    assessment_form_id: Mapped[str] = mapped_column(String(37), primary_key=True)
    deliverable_id: Mapped[str] = mapped_column(
        ForeignKey("deliverables.deliverable_id"), nullable=False, index=True
    )
    form_key: Mapped[str] = mapped_column(String(128), nullable=False)
    current_revision_id: Mapped[str | None] = mapped_column(
        ForeignKey(
            "assessment_form_revisions.assessment_form_revision_id",
            name="fk_assessment_form_current_revision",
            use_alter=True,
        )
    )
    lifecycle_state: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_by: Mapped[str] = mapped_column(String(128), nullable=False)


class AssessmentFormRevisionRecord(Base):
    __tablename__ = "assessment_form_revisions"
    __table_args__ = (
        UniqueConstraint(
            "assessment_form_id", "revision_number", name="uq_assessment_form_revision_number"
        ),
        CheckConstraint("revision_number > 0", name="ck_assessment_form_revision_number"),
        CheckConstraint("ordinal > 0", name="ck_assessment_form_revision_ordinal"),
        CheckConstraint(
            "revision_state IN ('DRAFT','RELEASED','SUPERSEDED','WITHDRAWN')",
            name="ck_assessment_form_revision_state",
        ),
        Index("ix_assessment_form_revisions_form", "assessment_form_id"),
        Index("ix_assessment_form_revisions_product", "deliverable_revision_id"),
    )

    assessment_form_revision_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    assessment_form_id: Mapped[str] = mapped_column(
        ForeignKey("assessment_forms.assessment_form_id"), nullable=False
    )
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    previous_revision_id: Mapped[str | None] = mapped_column(
        ForeignKey("assessment_form_revisions.assessment_form_revision_id")
    )
    deliverable_revision_id: Mapped[str] = mapped_column(
        ForeignKey("deliverable_revisions.deliverable_revision_id"), nullable=False
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    display_label: Mapped[str] = mapped_column(String(128), nullable=False)
    assessment_assembly_revision_id: Mapped[str | None] = mapped_column(
        ForeignKey(
            "assessment_assembly_revisions.assessment_assembly_revision_id",
            name="fk_assessment_form_revision_assembly",
            use_alter=True,
        )
    )
    revision_state: Mapped[str] = mapped_column(String(16), nullable=False)
    revision_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_by: Mapped[str] = mapped_column(String(128), nullable=False)
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AssessmentAssemblyRecord(Base):
    __tablename__ = "assessment_assemblies"

    assessment_assembly_id: Mapped[str] = mapped_column(String(41), primary_key=True)
    assessment_form_id: Mapped[str] = mapped_column(
        ForeignKey("assessment_forms.assessment_form_id"), nullable=False, unique=True
    )
    current_revision_id: Mapped[str | None] = mapped_column(
        ForeignKey(
            "assessment_assembly_revisions.assessment_assembly_revision_id",
            name="fk_assessment_assembly_current_revision",
            use_alter=True,
        )
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_by: Mapped[str] = mapped_column(String(128), nullable=False)


class AssessmentAssemblyRevisionRecord(Base):
    __tablename__ = "assessment_assembly_revisions"
    __table_args__ = (
        UniqueConstraint(
            "assessment_assembly_id",
            "revision_number",
            name="uq_assessment_assembly_revision_number",
        ),
        CheckConstraint("revision_number > 0", name="ck_assessment_assembly_revision_number"),
        CheckConstraint(
            "total_points_milli >= 0", name="ck_assessment_assembly_revision_total_points"
        ),
        CheckConstraint(
            "revision_state IN ('RELEASED','SUPERSEDED','WITHDRAWN')",
            name="ck_assessment_assembly_revision_state",
        ),
        Index("ix_assessment_assembly_revisions_assembly", "assessment_assembly_id"),
        Index("ix_assessment_assembly_revisions_form", "assessment_form_id"),
    )

    assessment_assembly_revision_id: Mapped[str] = mapped_column(String(44), primary_key=True)
    assessment_assembly_id: Mapped[str] = mapped_column(
        ForeignKey("assessment_assemblies.assessment_assembly_id"), nullable=False
    )
    assessment_form_id: Mapped[str] = mapped_column(
        ForeignKey("assessment_forms.assessment_form_id"), nullable=False
    )
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    previous_revision_id: Mapped[str | None] = mapped_column(
        ForeignKey("assessment_assembly_revisions.assessment_assembly_revision_id")
    )
    revision_state: Mapped[str] = mapped_column(String(16), nullable=False)
    total_points_milli: Mapped[int] = mapped_column(Integer, nullable=False)
    manifest_sha256: Mapped[str] = mapped_column(String(71), nullable=False, unique=True)
    canonical_document: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_by: Mapped[str] = mapped_column(String(128), nullable=False)
    released_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AssessmentItemPlacementRecord(Base):
    __tablename__ = "assessment_item_placements"
    __table_args__ = (
        UniqueConstraint(
            "assessment_assembly_revision_id",
            "section_key",
            "position",
            name="uq_assessment_placement_position",
        ),
        CheckConstraint("section_ordinal > 0", name="ck_assessment_placement_section_ordinal"),
        CheckConstraint("position > 0", name="ck_assessment_placement_position"),
        CheckConstraint("points_milli >= 0", name="ck_assessment_placement_points"),
        CheckConstraint(
            "usage_role IN ('PRIMARY','PRACTICE','REVIEW','EXAMPLE','OTHER_REVIEWED')",
            name="ck_assessment_placement_usage_role",
        ),
        Index("ix_assessment_item_placements_assembly", "assessment_assembly_revision_id"),
        Index("ix_assessment_item_placements_item_revision", "item_revision_id"),
    )

    placement_id: Mapped[str] = mapped_column(String(42), primary_key=True)
    assessment_assembly_revision_id: Mapped[str] = mapped_column(
        ForeignKey("assessment_assembly_revisions.assessment_assembly_revision_id"),
        nullable=False,
    )
    section_key: Mapped[str] = mapped_column(String(128), nullable=False)
    section_ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    display_number: Mapped[str] = mapped_column(String(32), nullable=False)
    item_id: Mapped[str] = mapped_column(ForeignKey("items.item_id"), nullable=False)
    item_revision_id: Mapped[str] = mapped_column(
        ForeignKey("item_revisions.item_revision_id"), nullable=False
    )
    item_manifest_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    points_milli: Mapped[int] = mapped_column(Integer, nullable=False)
    usage_role: Mapped[str] = mapped_column(String(32), nullable=False)
    source_usage_plan_id: Mapped[str | None] = mapped_column(
        ForeignKey("usage_plans.usage_plan_id"), unique=True
    )


class PublicationRecord(Base):
    __tablename__ = "publications"
    __table_args__ = (
        UniqueConstraint("assessment_form_id", "publication_key", name="uq_publication_form_key"),
        CheckConstraint("lifecycle_state IN ('ACTIVE','RETIRED')", name="ck_publications_state"),
        Index("ix_publications_form", "assessment_form_id"),
    )

    publication_id: Mapped[str] = mapped_column(String(44), primary_key=True)
    assessment_form_id: Mapped[str] = mapped_column(
        ForeignKey("assessment_forms.assessment_form_id"), nullable=False
    )
    publication_key: Mapped[str] = mapped_column(String(128), nullable=False)
    current_revision_id: Mapped[str | None] = mapped_column(
        ForeignKey(
            "publication_revisions.publication_revision_id",
            name="fk_publication_current_revision",
            use_alter=True,
        )
    )
    lifecycle_state: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_by: Mapped[str] = mapped_column(String(128), nullable=False)


class PublicationRevisionRecord(Base):
    __tablename__ = "publication_revisions"
    __table_args__ = (
        UniqueConstraint(
            "publication_id", "revision_number", name="uq_publication_revision_number"
        ),
        CheckConstraint("revision_number > 0", name="ck_publication_revision_number"),
        CheckConstraint(
            "revision_state IN ('RELEASED','WITHDRAWN')", name="ck_publication_revision_state"
        ),
        CheckConstraint(
            "source_kind IN ('LEGACY_WORKBOOK','RENDERED_OUTPUT')",
            name="ck_publication_revision_source_kind",
        ),
        Index("ix_publication_revisions_publication", "publication_id"),
        Index("ix_publication_revisions_product", "deliverable_revision_id"),
        Index("ix_publication_revisions_form", "assessment_form_revision_id"),
    )

    publication_revision_id: Mapped[str] = mapped_column(String(47), primary_key=True)
    publication_id: Mapped[str] = mapped_column(
        ForeignKey("publications.publication_id"), nullable=False
    )
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    deliverable_revision_id: Mapped[str] = mapped_column(
        ForeignKey("deliverable_revisions.deliverable_revision_id"), nullable=False
    )
    assessment_form_revision_id: Mapped[str] = mapped_column(
        ForeignKey("assessment_form_revisions.assessment_form_revision_id"),
        nullable=False,
    )
    assessment_assembly_revision_id: Mapped[str] = mapped_column(
        ForeignKey("assessment_assembly_revisions.assessment_assembly_revision_id"),
        nullable=False,
    )
    assembly_manifest_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    publication_date: Mapped[date] = mapped_column(Date, nullable=False)
    revision_state: Mapped[str] = mapped_column(String(16), nullable=False)
    publication_sha256: Mapped[str] = mapped_column(String(71), nullable=False, unique=True)
    source_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    source_artifact_id: Mapped[str] = mapped_column(
        ForeignKey("artifacts.logical_artifact_id"), nullable=False
    )
    source_artifact_revision_id: Mapped[str] = mapped_column(
        ForeignKey("artifact_revisions.revision_id"), nullable=False
    )
    source_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_by: Mapped[str] = mapped_column(String(128), nullable=False)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class UsageRecordV1Record(Base):
    __tablename__ = "usage_records_v1"
    __table_args__ = (
        UniqueConstraint(
            "publication_revision_id", "placement_id", name="uq_usage_v1_publication_placement"
        ),
        UniqueConstraint("source_kind", "source_key", name="uq_usage_v1_source_key"),
        UniqueConstraint("legacy_usage_row_id", name="uq_usage_v1_legacy_row"),
        CheckConstraint("contract_version = 'usage-record/1.0'", name="ck_usage_v1_contract"),
        CheckConstraint("points_milli >= 0", name="ck_usage_v1_points"),
        CheckConstraint("section_ordinal > 0", name="ck_usage_v1_section_ordinal"),
        CheckConstraint("position > 0", name="ck_usage_v1_position"),
        CheckConstraint(
            "usage_role IN ('PRIMARY','PRACTICE','REVIEW','EXAMPLE','OTHER_REVIEWED')",
            name="ck_usage_v1_role",
        ),
        CheckConstraint(
            "source_kind IN ('LEGACY_WORKBOOK','PLANNED_FULFILLMENT','MANUAL_REVIEWED')",
            name="ck_usage_v1_source_kind",
        ),
        Index("ix_usage_v1_item_reverse", "item_revision_id", "recorded_at"),
        Index("ix_usage_v1_product_revision", "deliverable_revision_id"),
        Index("ix_usage_v1_form_revision", "assessment_form_revision_id"),
        Index("ix_usage_v1_publication", "publication_revision_id"),
        Index("ix_usage_v1_import", "legacy_usage_import_id"),
    )

    usage_record_id: Mapped[str] = mapped_column(String(44), primary_key=True)
    contract_version: Mapped[str] = mapped_column(String(32), nullable=False)
    legacy_usage_import_id: Mapped[str] = mapped_column(
        ForeignKey("legacy_usage_imports.legacy_usage_import_id"), nullable=False
    )
    legacy_usage_row_id: Mapped[str] = mapped_column(
        ForeignKey("legacy_usage_row_proposals.legacy_usage_row_id"),
        nullable=False,
        unique=True,
    )
    item_id: Mapped[str] = mapped_column(ForeignKey("items.item_id"), nullable=False)
    item_revision_id: Mapped[str] = mapped_column(
        ForeignKey("item_revisions.item_revision_id"), nullable=False
    )
    deliverable_id: Mapped[str] = mapped_column(
        ForeignKey("deliverables.deliverable_id"), nullable=False
    )
    deliverable_revision_id: Mapped[str] = mapped_column(
        ForeignKey("deliverable_revisions.deliverable_revision_id"), nullable=False
    )
    assessment_form_id: Mapped[str] = mapped_column(
        ForeignKey("assessment_forms.assessment_form_id"), nullable=False
    )
    assessment_form_revision_id: Mapped[str] = mapped_column(
        ForeignKey("assessment_form_revisions.assessment_form_revision_id"),
        nullable=False,
    )
    assessment_assembly_revision_id: Mapped[str] = mapped_column(
        ForeignKey("assessment_assembly_revisions.assessment_assembly_revision_id"),
        nullable=False,
    )
    placement_id: Mapped[str] = mapped_column(
        ForeignKey("assessment_item_placements.placement_id"), nullable=False
    )
    publication_revision_id: Mapped[str] = mapped_column(
        ForeignKey("publication_revisions.publication_revision_id"), nullable=False
    )
    section_key: Mapped[str] = mapped_column(String(128), nullable=False)
    section_ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    points_milli: Mapped[int] = mapped_column(Integer, nullable=False)
    usage_role: Mapped[str] = mapped_column(String(32), nullable=False)
    source_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    source_key: Mapped[str] = mapped_column(String(200), nullable=False)
    source_hash: Mapped[str] = mapped_column(String(71), nullable=False)
    detail_sha256: Mapped[str] = mapped_column(String(71), nullable=False, unique=True)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    recorded_by: Mapped[str] = mapped_column(String(128), nullable=False)


class LegacyUsageMappingContractRecord(Base):
    __tablename__ = "legacy_usage_mapping_contracts"

    mapping_contract_id: Mapped[str] = mapped_column(String(42), primary_key=True)
    mapping_key: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    current_revision_id: Mapped[str | None] = mapped_column(
        ForeignKey(
            "legacy_usage_mapping_contract_revisions.mapping_contract_revision_id",
            name="fk_legacy_mapping_current_revision",
            use_alter=True,
        )
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_by: Mapped[str] = mapped_column(String(128), nullable=False)


class LegacyUsageMappingContractRevisionRecord(Base):
    __tablename__ = "legacy_usage_mapping_contract_revisions"
    __table_args__ = (
        UniqueConstraint(
            "mapping_contract_id", "revision_number", name="uq_legacy_mapping_revision_number"
        ),
        CheckConstraint("revision_number > 0", name="ck_legacy_mapping_revision_number"),
        CheckConstraint("state = 'RELEASED'", name="ck_legacy_mapping_revision_state"),
        Index("ix_legacy_mapping_revisions_contract", "mapping_contract_id"),
    )

    mapping_contract_revision_id: Mapped[str] = mapped_column(String(45), primary_key=True)
    mapping_contract_id: Mapped[str] = mapped_column(
        ForeignKey("legacy_usage_mapping_contracts.mapping_contract_id"), nullable=False
    )
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    contract_sha256: Mapped[str] = mapped_column(String(71), nullable=False, unique=True)
    canonical_document: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    released_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    released_by: Mapped[str] = mapped_column(String(128), nullable=False)


class LegacyUsageImportRecord(Base):
    __tablename__ = "legacy_usage_imports"
    __table_args__ = (
        UniqueConstraint(
            "source_file_id",
            "source_artifact_revision_id",
            "mapping_contract_revision_id",
            name="uq_legacy_import_source_mapping",
        ),
        CheckConstraint(
            "state IN ('PROPOSED','REVIEWED','COMMITTED','FAILED')",
            name="ck_legacy_import_state",
        ),
        CheckConstraint(
            "source_schema_ref = 'eom://schemas/legacy-usage/workbook/1.0'",
            name="ck_legacy_import_source_schema",
        ),
        CheckConstraint(
            "source_media_type = "
            "'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'",
            name="ck_legacy_import_source_media",
        ),
        CheckConstraint(
            "row_count >= 0 AND resolved_count >= 0 AND unresolved_count >= 0 "
            "AND conflict_count >= 0 AND rejected_count >= 0",
            name="ck_legacy_import_counts_nonnegative",
        ),
        CheckConstraint(
            "row_count = resolved_count + unresolved_count + conflict_count + rejected_count",
            name="ck_legacy_import_counts_sum",
        ),
        CheckConstraint(
            "(state = 'COMMITTED' AND commit_sha256 IS NOT NULL AND committed_at IS NOT NULL "
            "AND committed_by IS NOT NULL) OR "
            "(state <> 'COMMITTED' AND commit_sha256 IS NULL AND committed_at IS NULL "
            "AND committed_by IS NULL)",
            name="ck_legacy_import_commit_provenance",
        ),
        Index("ix_legacy_usage_imports_batch", "intake_batch_id"),
    )

    legacy_usage_import_id: Mapped[str] = mapped_column(String(45), primary_key=True)
    intake_batch_id: Mapped[str] = mapped_column(
        ForeignKey("content_intake_batches.intake_batch_id"), nullable=False
    )
    source_file_id: Mapped[str] = mapped_column(
        ForeignKey("content_intake_source_files.source_file_id"), nullable=False
    )
    source_artifact_id: Mapped[str] = mapped_column(
        ForeignKey("artifacts.logical_artifact_id"), nullable=False
    )
    source_artifact_revision_id: Mapped[str] = mapped_column(
        ForeignKey("artifact_revisions.revision_id"), nullable=False
    )
    source_member_path: Mapped[str] = mapped_column(String(512), nullable=False)
    source_schema_ref: Mapped[str] = mapped_column(String(256), nullable=False)
    source_media_type: Mapped[str] = mapped_column(String(128), nullable=False)
    source_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    mapping_contract_revision_id: Mapped[str] = mapped_column(
        ForeignKey("legacy_usage_mapping_contract_revisions.mapping_contract_revision_id"),
        nullable=False,
    )
    mapping_contract_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    request_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False)
    resolved_count: Mapped[int] = mapped_column(Integer, nullable=False)
    unresolved_count: Mapped[int] = mapped_column(Integer, nullable=False)
    conflict_count: Mapped[int] = mapped_column(Integer, nullable=False)
    rejected_count: Mapped[int] = mapped_column(Integer, nullable=False)
    commit_sha256: Mapped[str | None] = mapped_column(String(71))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_by: Mapped[str] = mapped_column(String(128), nullable=False)
    committed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    committed_by: Mapped[str | None] = mapped_column(String(128))
    lock_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class LegacyUsageRowProposalRecord(Base):
    __tablename__ = "legacy_usage_row_proposals"
    __table_args__ = (
        UniqueConstraint(
            "legacy_usage_import_id",
            "source_row_number",
            name="uq_legacy_usage_source_row_number",
        ),
        CheckConstraint(
            "proposal_state IN ('RESOLVED','UNRESOLVED','CONFLICT','REJECTED')",
            name="ck_legacy_usage_row_state",
        ),
        Index("ix_legacy_usage_rows_import_state", "legacy_usage_import_id", "proposal_state"),
        Index(
            "ix_legacy_usage_rows_import_source_key",
            "legacy_usage_import_id",
            "source_row_key",
        ),
    )

    legacy_usage_row_id: Mapped[str] = mapped_column(String(42), primary_key=True)
    legacy_usage_import_id: Mapped[str] = mapped_column(
        ForeignKey("legacy_usage_imports.legacy_usage_import_id"), nullable=False
    )
    source_row_key: Mapped[str] = mapped_column(String(128), nullable=False)
    source_row_number: Mapped[int] = mapped_column(Integer, nullable=False)
    normalized_row_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    proposal_state: Mapped[str] = mapped_column(String(16), nullable=False)
    canonical_document: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class LegacyUsageRowReviewRecord(Base):
    __tablename__ = "legacy_usage_row_reviews"
    __table_args__ = (
        CheckConstraint("decision IN ('APPROVE','REJECT')", name="ck_legacy_usage_review_decision"),
    )

    legacy_usage_review_id: Mapped[str] = mapped_column(String(45), primary_key=True)
    legacy_usage_row_id: Mapped[str] = mapped_column(
        ForeignKey("legacy_usage_row_proposals.legacy_usage_row_id"), nullable=False, unique=True
    )
    decision: Mapped[str] = mapped_column(String(16), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    decision_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    reviewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reviewed_by: Mapped[str] = mapped_column(String(128), nullable=False)


class ProductUsageProjectionRecord(Base):
    __tablename__ = "product_usage_projections"

    product_usage_projection_id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True
    )
    legacy_usage_import_id: Mapped[str] = mapped_column(
        ForeignKey("legacy_usage_imports.legacy_usage_import_id"), nullable=False, unique=True
    )
    projection_sha256: Mapped[str] = mapped_column(String(71), nullable=False, unique=True)
    canonical_document: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
