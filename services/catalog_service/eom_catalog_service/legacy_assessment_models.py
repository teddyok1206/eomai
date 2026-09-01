"""Pointer-only persistence for reviewed legacy assessment source bundles."""

from __future__ import annotations

from datetime import datetime

from eom_orchestrator.models import Base
from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Identity,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column


class AssessmentSourceBundleRecord(Base):
    __tablename__ = "assessment_source_bundles"
    __table_args__ = (
        CheckConstraint(
            "lifecycle_state IN ('ACTIVE','RETIRED')",
            name="ck_assessment_source_bundles_state",
        ),
        CheckConstraint("lock_version > 0", name="ck_assessment_source_bundles_lock_version"),
    )

    assessment_source_bundle_id: Mapped[str] = mapped_column(String(45), primary_key=True)
    bundle_key: Mapped[str] = mapped_column(String(160), nullable=False, unique=True)
    current_revision_id: Mapped[str | None] = mapped_column(
        ForeignKey(
            "assessment_source_bundle_revisions.assessment_source_bundle_revision_id",
            name="fk_assessment_source_bundle_current_revision",
            use_alter=True,
        )
    )
    lifecycle_state: Mapped[str] = mapped_column(String(16), nullable=False)
    lock_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_by: Mapped[str] = mapped_column(String(128), nullable=False)


class AssessmentSourceBundleRevisionRecord(Base):
    __tablename__ = "assessment_source_bundle_revisions"
    __table_args__ = (
        UniqueConstraint(
            "assessment_source_bundle_id",
            "revision_number",
            name="uq_assessment_source_bundle_revision_number",
        ),
        UniqueConstraint(
            "assessment_source_bundle_id",
            "assessment_source_bundle_revision_id",
            name="uq_assessment_source_bundle_revision_identity",
        ),
        CheckConstraint("revision_number > 0", name="ck_assessment_source_bundle_revision_number"),
        CheckConstraint(
            "state IN ('REVIEWED','SUPERSEDED','WITHDRAWN')",
            name="ck_assessment_source_bundle_revision_state",
        ),
        ForeignKeyConstraint(
            ["assessment_occurrence_id", "assessment_occurrence_revision_id"],
            [
                "assessment_occurrence_revisions.assessment_occurrence_id",
                "assessment_occurrence_revisions.assessment_occurrence_revision_id",
            ],
            name="fk_assessment_source_bundle_occurrence_revision_identity",
        ),
        ForeignKeyConstraint(
            ["inventory_artifact_id", "inventory_artifact_revision_id"],
            [
                "artifact_revisions.logical_artifact_id",
                "artifact_revisions.revision_id",
            ],
            name="fk_assessment_source_bundle_inventory_artifact_revision_identity",
        ),
        Index(
            "ix_assessment_source_bundle_revisions_occurrence",
            "assessment_occurrence_revision_id",
        ),
        Index(
            "ix_assessment_source_bundle_revisions_inventory",
            "inventory_id",
            "inventory_sha256",
        ),
    )

    assessment_source_bundle_revision_id: Mapped[str] = mapped_column(String(48), primary_key=True)
    assessment_source_bundle_id: Mapped[str] = mapped_column(
        ForeignKey("assessment_source_bundles.assessment_source_bundle_id"), nullable=False
    )
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    previous_revision_id: Mapped[str | None] = mapped_column(
        ForeignKey("assessment_source_bundle_revisions.assessment_source_bundle_revision_id")
    )
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    inventory_id: Mapped[str] = mapped_column(String(48), nullable=False)
    inventory_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    inventory_artifact_id: Mapped[str] = mapped_column(String(41), nullable=False)
    inventory_artifact_revision_id: Mapped[str] = mapped_column(String(36), nullable=False)
    inventory_artifact_member_path: Mapped[str] = mapped_column(String(512), nullable=False)
    inventory_artifact_schema_ref: Mapped[str] = mapped_column(String(256), nullable=False)
    inventory_artifact_media_type: Mapped[str] = mapped_column(String(128), nullable=False)
    inventory_artifact_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    assessment_occurrence_id: Mapped[str] = mapped_column(String(43), nullable=False)
    assessment_occurrence_revision_id: Mapped[str] = mapped_column(String(41), nullable=False)
    occurrence_revision_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    rights_policy_id: Mapped[str] = mapped_column(String(45), nullable=False)
    rights_policy_revision_id: Mapped[str] = mapped_column(String(48), nullable=False)
    rights_policy_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    bundle_manifest_sha256: Mapped[str] = mapped_column(String(71), nullable=False, unique=True)
    reviewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reviewed_by: Mapped[str] = mapped_column(String(128), nullable=False)


class AssessmentSourceBundleMemberRecord(Base):
    __tablename__ = "assessment_source_bundle_members"
    __table_args__ = (
        UniqueConstraint(
            "assessment_source_bundle_revision_id",
            "ordinal",
            name="uq_assessment_source_bundle_member_ordinal",
        ),
        UniqueConstraint(
            "assessment_source_bundle_revision_id",
            "source_artifact_revision_id",
            "source_member_path",
            name="uq_assessment_source_bundle_member_source",
        ),
        UniqueConstraint(
            "assessment_source_bundle_revision_id",
            "inventory_entry_key",
            name="uq_assessment_source_bundle_member_inventory_entry",
        ),
        CheckConstraint("ordinal >= 0", name="ck_assessment_source_bundle_member_ordinal"),
        CheckConstraint(
            "role IN ('PROBLEM_DOCUMENT','ANSWER_EXPLANATION_DOCUMENT',"
            "'STRUCTURED_RECONSTRUCTION','ITEM_CLASSIFICATION_WORKBOOK',"
            "'TYPE_CODE_REFERENCE','OTHER_REVIEWED_EVIDENCE')",
            name="ck_assessment_source_bundle_member_role",
        ),
        ForeignKeyConstraint(
            ["source_artifact_id", "source_artifact_revision_id"],
            [
                "artifact_revisions.logical_artifact_id",
                "artifact_revisions.revision_id",
            ],
            name="fk_assessment_source_bundle_member_artifact_revision_identity",
        ),
        Index(
            "ix_assessment_source_bundle_members_artifact",
            "source_artifact_revision_id",
        ),
        Index(
            "ix_assessment_source_bundle_members_inventory",
            "inventory_id",
            "inventory_entry_key",
        ),
    )

    assessment_source_bundle_member_id: Mapped[str] = mapped_column(String(51), primary_key=True)
    assessment_source_bundle_revision_id: Mapped[str] = mapped_column(
        ForeignKey(
            "assessment_source_bundle_revisions.assessment_source_bundle_revision_id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    role: Mapped[str] = mapped_column(String(40), nullable=False)
    source_artifact_id: Mapped[str] = mapped_column(String(41), nullable=False)
    source_artifact_revision_id: Mapped[str] = mapped_column(String(36), nullable=False)
    source_member_path: Mapped[str] = mapped_column(String(512), nullable=False)
    source_schema_ref: Mapped[str] = mapped_column(String(256), nullable=False)
    source_media_type: Mapped[str] = mapped_column(String(128), nullable=False)
    source_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    inventory_id: Mapped[str] = mapped_column(String(48), nullable=False)
    inventory_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    inventory_entry_key: Mapped[str] = mapped_column(String(44), nullable=False)
    inventory_content_sha256: Mapped[str] = mapped_column(String(71), nullable=False)


class AssessmentLayoutObservationRecord(Base):
    __tablename__ = "assessment_layout_observations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["assessment_source_bundle_id", "assessment_source_bundle_revision_id"],
            [
                "assessment_source_bundle_revisions.assessment_source_bundle_id",
                "assessment_source_bundle_revisions.assessment_source_bundle_revision_id",
            ],
            name="fk_assessment_layout_bundle_revision_identity",
        ),
        ForeignKeyConstraint(
            ["artifact_id", "artifact_revision_id"],
            [
                "artifact_revisions.logical_artifact_id",
                "artifact_revisions.revision_id",
            ],
            name="fk_assessment_layout_artifact_revision_identity",
        ),
        UniqueConstraint(
            "artifact_revision_id",
            "artifact_member_path",
            name="uq_assessment_layout_artifact_member",
        ),
        CheckConstraint("expected_item_count > 0", name="ck_assessment_layout_expected_item_count"),
        Index(
            "ix_assessment_layout_observations_bundle",
            "assessment_source_bundle_revision_id",
        ),
    )

    assessment_layout_observation_id: Mapped[str] = mapped_column(String(49), primary_key=True)
    assessment_source_bundle_id: Mapped[str] = mapped_column(String(45), nullable=False)
    assessment_source_bundle_revision_id: Mapped[str] = mapped_column(String(48), nullable=False)
    bundle_manifest_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    artifact_id: Mapped[str] = mapped_column(String(41), nullable=False)
    artifact_revision_id: Mapped[str] = mapped_column(String(36), nullable=False)
    artifact_member_path: Mapped[str] = mapped_column(String(512), nullable=False)
    artifact_schema_ref: Mapped[str] = mapped_column(String(256), nullable=False)
    artifact_media_type: Mapped[str] = mapped_column(String(128), nullable=False)
    artifact_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    expected_item_count: Mapped[int] = mapped_column(Integer, nullable=False)
    observation_sha256: Mapped[str] = mapped_column(String(71), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class LegacyItemExtractionAcceptanceRecord(Base):
    __tablename__ = "legacy_item_extraction_acceptances"
    __table_args__ = (
        CheckConstraint(
            "state IN ('ACCEPTED','ACCEPTED_WITH_CORRECTIONS','REJECTED')",
            name="ck_legacy_item_extraction_acceptance_state",
        ),
        CheckConstraint(
            "coverage_state IN ('COMPLETE','INCOMPLETE','CONFLICT')",
            name="ck_legacy_item_extraction_acceptance_coverage",
        ),
        ForeignKeyConstraint(
            ["result_artifact_id", "result_artifact_revision_id"],
            [
                "artifact_revisions.logical_artifact_id",
                "artifact_revisions.revision_id",
            ],
            name="fk_legacy_item_acceptance_result_artifact_revision_identity",
        ),
        ForeignKeyConstraint(
            ["acceptance_artifact_id", "acceptance_artifact_revision_id"],
            [
                "artifact_revisions.logical_artifact_id",
                "artifact_revisions.revision_id",
            ],
            name="fk_legacy_item_acceptance_artifact_revision_identity",
        ),
        Index(
            "ix_legacy_item_extraction_acceptances_result",
            "extraction_result_id",
        ),
    )

    acceptance_id: Mapped[str] = mapped_column(String(47), primary_key=True)
    extraction_result_id: Mapped[str] = mapped_column(String(50), nullable=False)
    result_artifact_id: Mapped[str] = mapped_column(String(41), nullable=False)
    result_artifact_revision_id: Mapped[str] = mapped_column(String(36), nullable=False)
    result_artifact_member_path: Mapped[str] = mapped_column(String(512), nullable=False)
    result_artifact_schema_ref: Mapped[str] = mapped_column(String(256), nullable=False)
    result_artifact_media_type: Mapped[str] = mapped_column(String(128), nullable=False)
    result_artifact_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    result_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    acceptance_artifact_id: Mapped[str] = mapped_column(String(41), nullable=False)
    acceptance_artifact_revision_id: Mapped[str] = mapped_column(String(36), nullable=False)
    acceptance_artifact_member_path: Mapped[str] = mapped_column(String(512), nullable=False)
    acceptance_artifact_schema_ref: Mapped[str] = mapped_column(String(256), nullable=False)
    acceptance_artifact_media_type: Mapped[str] = mapped_column(String(128), nullable=False)
    acceptance_artifact_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    coverage_state: Mapped[str] = mapped_column(String(16), nullable=False)
    reviewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reviewed_by: Mapped[str] = mapped_column(String(128), nullable=False)
    acceptance_sha256: Mapped[str] = mapped_column(String(71), nullable=False, unique=True)


class LegacyItemExtractionDecisionRecord(Base):
    __tablename__ = "legacy_item_extraction_decisions"
    __table_args__ = (
        UniqueConstraint(
            "acceptance_id", "item_number", name="uq_legacy_item_acceptance_item_number"
        ),
        UniqueConstraint(
            "acceptance_id",
            "item_proposal_id",
            name="uq_legacy_item_acceptance_item_proposal",
        ),
        CheckConstraint("item_number > 0", name="ck_legacy_item_acceptance_item_number"),
        CheckConstraint(
            "decision IN ('ACCEPT','CORRECT_AND_ACCEPT','REJECT')",
            name="ck_legacy_item_acceptance_item_decision",
        ),
    )

    decision_id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    acceptance_id: Mapped[str] = mapped_column(
        ForeignKey("legacy_item_extraction_acceptances.acceptance_id", ondelete="CASCADE"),
        nullable=False,
    )
    item_proposal_id: Mapped[str] = mapped_column(String(45), nullable=False)
    item_number: Mapped[int] = mapped_column(Integer, nullable=False)
    decision: Mapped[str] = mapped_column(String(24), nullable=False)


class LegacyItemCorpusCoverageRecord(Base):
    """Pointer to one immutable, exact corpus-coverage document."""

    __tablename__ = "legacy_item_corpus_coverages"
    __table_args__ = (
        CheckConstraint(
            "state IN ('COMPLETE','INCOMPLETE','CONFLICT')",
            name="ck_legacy_item_corpus_coverage_state",
        ),
        CheckConstraint(
            "expected_item_count >= 0 AND accepted_item_count >= 0 "
            "AND missing_item_count >= 0 AND conflict_item_count >= 0",
            name="ck_legacy_item_corpus_coverage_counts_nonnegative",
        ),
        CheckConstraint(
            "expected_item_count = accepted_item_count + missing_item_count + conflict_item_count",
            name="ck_legacy_item_corpus_coverage_exact_partition",
        ),
        ForeignKeyConstraint(
            ["artifact_id", "artifact_revision_id"],
            [
                "artifact_revisions.logical_artifact_id",
                "artifact_revisions.revision_id",
            ],
            name="fk_legacy_item_corpus_coverage_artifact_revision_identity",
        ),
        Index(
            "ix_legacy_item_corpus_coverages_inventory",
            "inventory_id",
            "created_at",
            "coverage_id",
        ),
    )

    coverage_id: Mapped[str] = mapped_column(String(45), primary_key=True)
    inventory_id: Mapped[str] = mapped_column(String(48), nullable=False)
    inventory_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    artifact_id: Mapped[str] = mapped_column(String(41), nullable=False)
    artifact_revision_id: Mapped[str] = mapped_column(String(36), nullable=False)
    artifact_member_path: Mapped[str] = mapped_column(String(512), nullable=False)
    artifact_schema_ref: Mapped[str] = mapped_column(String(256), nullable=False)
    artifact_media_type: Mapped[str] = mapped_column(String(128), nullable=False)
    artifact_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    expected_item_count: Mapped[int] = mapped_column(Integer, nullable=False)
    accepted_item_count: Mapped[int] = mapped_column(Integer, nullable=False)
    missing_item_count: Mapped[int] = mapped_column(Integer, nullable=False)
    conflict_item_count: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    coverage_sha256: Mapped[str] = mapped_column(String(71), nullable=False, unique=True)


class LegacyItemCorpusBundleCoverageRecord(Base):
    """Small query projection for one bundle partition in a coverage snapshot."""

    __tablename__ = "legacy_item_corpus_bundle_coverages"
    __table_args__ = (
        UniqueConstraint(
            "coverage_id",
            "assessment_source_bundle_revision_id",
            name="uq_legacy_item_corpus_bundle_coverage",
        ),
        CheckConstraint(
            "expected_item_count > 0 AND accepted_item_count >= 0 "
            "AND missing_item_count >= 0 AND conflict_item_count >= 0",
            name="ck_legacy_item_corpus_bundle_coverage_counts",
        ),
        CheckConstraint(
            "expected_item_count = accepted_item_count + missing_item_count + conflict_item_count",
            name="ck_legacy_item_corpus_bundle_coverage_exact_partition",
        ),
        ForeignKeyConstraint(
            ["assessment_source_bundle_id", "assessment_source_bundle_revision_id"],
            [
                "assessment_source_bundle_revisions.assessment_source_bundle_id",
                "assessment_source_bundle_revisions.assessment_source_bundle_revision_id",
            ],
            name="fk_legacy_item_corpus_coverage_bundle_revision_identity",
        ),
        Index(
            "ix_legacy_item_corpus_bundle_coverages_bundle",
            "assessment_source_bundle_revision_id",
            "coverage_id",
        ),
    )

    bundle_coverage_id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    coverage_id: Mapped[str] = mapped_column(
        ForeignKey("legacy_item_corpus_coverages.coverage_id", ondelete="CASCADE"),
        nullable=False,
    )
    assessment_source_bundle_id: Mapped[str] = mapped_column(String(45), nullable=False)
    assessment_source_bundle_revision_id: Mapped[str] = mapped_column(String(48), nullable=False)
    bundle_manifest_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    expected_item_count: Mapped[int] = mapped_column(Integer, nullable=False)
    accepted_item_count: Mapped[int] = mapped_column(Integer, nullable=False)
    missing_item_count: Mapped[int] = mapped_column(Integer, nullable=False)
    conflict_item_count: Mapped[int] = mapped_column(Integer, nullable=False)
