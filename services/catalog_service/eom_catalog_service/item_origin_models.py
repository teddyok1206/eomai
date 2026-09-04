"""Persistence records for immutable Organization, Occurrence, and Item Origin revisions."""

from __future__ import annotations

from datetime import date, datetime

from eom_orchestrator.models import Base
from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
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


class OrganizationRecord(Base):
    __tablename__ = "organizations"
    __table_args__ = (
        CheckConstraint("lifecycle_state IN ('ACTIVE','RETIRED')", name="ck_organizations_state"),
        CheckConstraint("lock_version > 0", name="ck_organizations_lock_version"),
    )

    organization_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    organization_key: Mapped[str] = mapped_column(String(160), nullable=False, unique=True)
    current_revision_id: Mapped[str | None] = mapped_column(
        ForeignKey(
            "organization_revisions.organization_revision_id",
            name="fk_organization_current_revision",
            use_alter=True,
        )
    )
    lifecycle_state: Mapped[str] = mapped_column(String(16), nullable=False)
    lock_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_by: Mapped[str] = mapped_column(String(128), nullable=False)


class OrganizationRevisionRecord(Base):
    __tablename__ = "organization_revisions"
    __table_args__ = (
        UniqueConstraint(
            "organization_id", "revision_number", name="uq_organization_revision_number"
        ),
        UniqueConstraint(
            "organization_id",
            "organization_revision_id",
            name="uq_organization_revision_identity",
        ),
        CheckConstraint("revision_number > 0", name="ck_organization_revision_number"),
        CheckConstraint(
            "revision_state IN ('REVIEWED','SUPERSEDED','RETIRED')",
            name="ck_organization_revision_state",
        ),
        CheckConstraint(
            "organization_class IN ('EOM_INTERNAL','NATIONAL_ASSESSMENT_AGENCY',"
            "'EDUCATION_AUTHORITY','SCHOOL','UNIVERSITY','PUBLISHER',"
            "'PRIVATE_EDUCATION_PROVIDER','OTHER_REVIEWED')",
            name="ck_organization_revision_class",
        ),
        CheckConstraint(
            "(organization_class = 'OTHER_REVIEWED') = (class_detail IS NOT NULL)",
            name="ck_organization_revision_class_detail",
        ),
        CheckConstraint(
            "jurisdiction_level IN ('NATIONAL','PROVINCE','METROPOLITAN','CITY',"
            "'COUNTY','DISTRICT','INSTITUTION','OTHER')",
            name="ck_organization_revision_jurisdiction",
        ),
        CheckConstraint(
            "effective_from IS NULL OR effective_to IS NULL OR effective_from <= effective_to",
            name="ck_organization_revision_effective_interval",
        ),
        Index("ix_organization_revisions_organization", "organization_id"),
        Index("ix_organization_revisions_class", "organization_class"),
    )

    organization_revision_id: Mapped[str] = mapped_column(String(39), primary_key=True)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.organization_id"), nullable=False
    )
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    previous_revision_id: Mapped[str | None] = mapped_column(
        ForeignKey("organization_revisions.organization_revision_id")
    )
    revision_state: Mapped[str] = mapped_column(String(16), nullable=False)
    organization_class: Mapped[str] = mapped_column(String(40), nullable=False)
    class_detail: Mapped[str | None] = mapped_column(String(256))
    display_name: Mapped[str] = mapped_column(String(256), nullable=False)
    locale: Mapped[str] = mapped_column(String(16), nullable=False)
    country_code: Mapped[str] = mapped_column(String(2), nullable=False)
    jurisdiction_level: Mapped[str] = mapped_column(String(16), nullable=False)
    jurisdiction_code: Mapped[str | None] = mapped_column(String(64))
    effective_from: Mapped[date | None] = mapped_column(Date)
    effective_to: Mapped[date | None] = mapped_column(Date)
    rights_policy_id: Mapped[str] = mapped_column(String(45), nullable=False)
    rights_policy_revision_id: Mapped[str] = mapped_column(String(48), nullable=False)
    rights_policy_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    revision_sha256: Mapped[str] = mapped_column(String(71), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_by: Mapped[str] = mapped_column(String(128), nullable=False)


class OrganizationAliasRecord(Base):
    __tablename__ = "organization_aliases"
    __table_args__ = (
        UniqueConstraint(
            "organization_revision_id",
            "locale",
            "normalized_value",
            name="uq_organization_alias_revision_value",
        ),
        CheckConstraint(
            "alias_kind IN ('OFFICIAL','ABBREVIATION','FORMER','LEGACY_SOURCE')",
            name="ck_organization_alias_kind",
        ),
        Index(
            "ix_organization_alias_lookup",
            "normalized_value",
            "locale",
            "organization_revision_id",
        ),
    )

    organization_alias_id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    organization_revision_id: Mapped[str] = mapped_column(
        ForeignKey("organization_revisions.organization_revision_id", ondelete="CASCADE"),
        nullable=False,
    )
    alias_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    locale: Mapped[str] = mapped_column(String(16), nullable=False)
    display_value: Mapped[str] = mapped_column(String(256), nullable=False)
    normalized_value: Mapped[str] = mapped_column(String(256), nullable=False)


class OrganizationSourceEvidenceRecord(Base):
    __tablename__ = "organization_source_evidence"
    __table_args__ = (
        UniqueConstraint(
            "organization_revision_id",
            "artifact_revision_id",
            "member_path",
            name="uq_organization_source_evidence",
        ),
        ForeignKeyConstraint(
            ["artifact_id", "artifact_revision_id"],
            [
                "artifact_revisions.logical_artifact_id",
                "artifact_revisions.revision_id",
            ],
            name="fk_organization_source_evidence_artifact_revision_identity",
        ),
        Index("ix_organization_source_evidence_owner", "organization_revision_id"),
    )

    organization_source_evidence_id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True
    )
    organization_revision_id: Mapped[str] = mapped_column(
        ForeignKey("organization_revisions.organization_revision_id", ondelete="CASCADE"),
        nullable=False,
    )
    artifact_id: Mapped[str] = mapped_column(String(41), nullable=False)
    artifact_revision_id: Mapped[str] = mapped_column(String(36), nullable=False)
    member_path: Mapped[str] = mapped_column(String(512), nullable=False)
    schema_ref: Mapped[str] = mapped_column(String(256), nullable=False)
    media_type: Mapped[str] = mapped_column(String(128), nullable=False)
    sha256: Mapped[str] = mapped_column(String(71), nullable=False)


class AssessmentOccurrenceRecord(Base):
    __tablename__ = "assessment_occurrences"
    __table_args__ = (
        CheckConstraint(
            "lifecycle_state IN ('ACTIVE','RETIRED')",
            name="ck_assessment_occurrences_state",
        ),
        CheckConstraint("lock_version > 0", name="ck_assessment_occurrences_lock_version"),
    )

    assessment_occurrence_id: Mapped[str] = mapped_column(String(43), primary_key=True)
    occurrence_key: Mapped[str] = mapped_column(String(160), nullable=False, unique=True)
    current_revision_id: Mapped[str | None] = mapped_column(
        ForeignKey(
            "assessment_occurrence_revisions.assessment_occurrence_revision_id",
            name="fk_assessment_occurrence_current_revision",
            use_alter=True,
        )
    )
    lifecycle_state: Mapped[str] = mapped_column(String(16), nullable=False)
    lock_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_by: Mapped[str] = mapped_column(String(128), nullable=False)


class AssessmentOccurrenceRevisionRecord(Base):
    __tablename__ = "assessment_occurrence_revisions"
    __table_args__ = (
        UniqueConstraint(
            "assessment_occurrence_id",
            "revision_number",
            name="uq_assessment_occurrence_revision_number",
        ),
        UniqueConstraint(
            "assessment_occurrence_id",
            "assessment_occurrence_revision_id",
            name="uq_assessment_occurrence_revision_identity",
        ),
        UniqueConstraint(
            "issuing_organization_id",
            "exam_family_key",
            "administration_year",
            "administration_date",
            "session_key",
            "subject_key",
            "form_key",
            "region_key",
            name="uq_assessment_occurrence_reviewed_identity",
            postgresql_nulls_not_distinct=True,
        ),
        CheckConstraint("revision_number > 0", name="ck_assessment_occurrence_revision_number"),
        CheckConstraint(
            "revision_state IN ('REVIEWED','SUPERSEDED','WITHDRAWN')",
            name="ck_assessment_occurrence_revision_state",
        ),
        CheckConstraint(
            "occurrence_kind IN ('NATIONAL_ENTRANCE','NATIONAL_ACHIEVEMENT',"
            "'EDUCATION_AUTHORITY_EXAM','SCHOOL_EXAM','INSTITUTIONAL_EXAM','OTHER_REVIEWED')",
            name="ck_assessment_occurrence_revision_kind",
        ),
        ForeignKeyConstraint(
            ["issuing_organization_id", "issuing_organization_revision_id"],
            [
                "organization_revisions.organization_id",
                "organization_revisions.organization_revision_id",
            ],
            name="fk_assessment_occurrence_organization_revision_identity",
        ),
        Index(
            "ix_assessment_occurrence_lookup",
            "exam_family_key",
            "administration_year",
            "subject_key",
        ),
        Index(
            "ix_assessment_occurrence_organization",
            "issuing_organization_revision_id",
        ),
    )

    assessment_occurrence_revision_id: Mapped[str] = mapped_column(String(41), primary_key=True)
    assessment_occurrence_id: Mapped[str] = mapped_column(
        ForeignKey("assessment_occurrences.assessment_occurrence_id"), nullable=False
    )
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    previous_revision_id: Mapped[str | None] = mapped_column(
        ForeignKey("assessment_occurrence_revisions.assessment_occurrence_revision_id")
    )
    revision_state: Mapped[str] = mapped_column(String(16), nullable=False)
    issuing_organization_id: Mapped[str] = mapped_column(String(36), nullable=False)
    issuing_organization_revision_id: Mapped[str] = mapped_column(String(39), nullable=False)
    issuing_organization_revision_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    occurrence_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    exam_family_key: Mapped[str] = mapped_column(String(160), nullable=False)
    administration_year: Mapped[int] = mapped_column(Integer, nullable=False)
    administration_date: Mapped[date | None] = mapped_column(Date)
    session_key: Mapped[str | None] = mapped_column(String(160))
    subject_key: Mapped[str] = mapped_column(String(160), nullable=False)
    form_key: Mapped[str | None] = mapped_column(String(160))
    region_key: Mapped[str | None] = mapped_column(String(160))
    display_label: Mapped[str] = mapped_column(String(512), nullable=False)
    rights_policy_id: Mapped[str] = mapped_column(String(45), nullable=False)
    rights_policy_revision_id: Mapped[str] = mapped_column(String(48), nullable=False)
    rights_policy_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    revision_sha256: Mapped[str] = mapped_column(String(71), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_by: Mapped[str] = mapped_column(String(128), nullable=False)


class AssessmentOccurrenceSourceEvidenceRecord(Base):
    __tablename__ = "assessment_occurrence_source_evidence"
    __table_args__ = (
        UniqueConstraint(
            "assessment_occurrence_revision_id",
            "artifact_revision_id",
            "member_path",
            name="uq_assessment_occurrence_source_evidence",
        ),
        ForeignKeyConstraint(
            ["artifact_id", "artifact_revision_id"],
            [
                "artifact_revisions.logical_artifact_id",
                "artifact_revisions.revision_id",
            ],
            name="fk_assessment_occ_source_evidence_artifact_revision_identity",
        ),
        Index(
            "ix_assessment_occurrence_source_evidence_owner",
            "assessment_occurrence_revision_id",
        ),
    )

    assessment_occurrence_source_evidence_id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True
    )
    assessment_occurrence_revision_id: Mapped[str] = mapped_column(
        ForeignKey(
            "assessment_occurrence_revisions.assessment_occurrence_revision_id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    artifact_id: Mapped[str] = mapped_column(String(41), nullable=False)
    artifact_revision_id: Mapped[str] = mapped_column(String(36), nullable=False)
    member_path: Mapped[str] = mapped_column(String(512), nullable=False)
    schema_ref: Mapped[str] = mapped_column(String(256), nullable=False)
    media_type: Mapped[str] = mapped_column(String(128), nullable=False)
    sha256: Mapped[str] = mapped_column(String(71), nullable=False)


class ItemOriginProfileRecord(Base):
    __tablename__ = "item_origin_profiles"
    __table_args__ = (
        CheckConstraint(
            "source_domain IN ('INTERNAL_EOM','EXTERNAL_INSTITUTION',"
            "'EXTERNAL_INDIVIDUAL','LEGACY_UNKNOWN')",
            name="ck_item_origin_profile_domain",
        ),
        CheckConstraint(
            "creation_method IN ('HUMAN_AUTHORED','AI_ASSISTED','AI_GENERATED',"
            "'IMPORTED','ADAPTED','UNKNOWN')",
            name="ck_item_origin_profile_method",
        ),
        CheckConstraint(
            "((source_organization_id IS NULL) = (source_organization_revision_id IS NULL))"
            " AND ((source_organization_id IS NULL) = "
            "(source_organization_revision_sha256 IS NULL))",
            name="ck_item_origin_profile_organization_pointer",
        ),
        CheckConstraint(
            "source_domain NOT IN ('INTERNAL_EOM','EXTERNAL_INSTITUTION')"
            " OR source_organization_revision_id IS NOT NULL",
            name="ck_item_origin_profile_institutional_organization",
        ),
        ForeignKeyConstraint(
            ["source_organization_id", "source_organization_revision_id"],
            [
                "organization_revisions.organization_id",
                "organization_revisions.organization_revision_id",
            ],
            name="fk_item_origin_profile_organization_revision_identity",
        ),
        ForeignKeyConstraint(
            ["item_id", "item_revision_id"],
            ["item_revisions.item_id", "item_revisions.item_revision_id"],
            name="fk_item_origin_profile_item_revision_identity",
        ),
        Index("ix_item_origin_profiles_domain_method", "source_domain", "creation_method"),
        Index("ix_item_origin_profiles_organization", "source_organization_revision_id"),
        Index("ix_item_origin_profiles_item", "item_id"),
    )

    item_origin_profile_id: Mapped[str] = mapped_column(String(46), primary_key=True)
    item_id: Mapped[str] = mapped_column(String(37), nullable=False)
    item_revision_id: Mapped[str] = mapped_column(String(40), nullable=False, unique=True)
    item_manifest_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    source_domain: Mapped[str] = mapped_column(String(32), nullable=False)
    creation_method: Mapped[str] = mapped_column(String(24), nullable=False)
    source_organization_id: Mapped[str | None] = mapped_column(String(36))
    source_organization_revision_id: Mapped[str | None] = mapped_column(String(39))
    source_organization_revision_sha256: Mapped[str | None] = mapped_column(String(71))
    rights_policy_id: Mapped[str] = mapped_column(String(45), nullable=False)
    rights_policy_revision_id: Mapped[str] = mapped_column(String(48), nullable=False)
    rights_policy_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    profile_sha256: Mapped[str] = mapped_column(String(71), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_by: Mapped[str] = mapped_column(String(128), nullable=False)


class ItemOriginOccurrenceRecord(Base):
    __tablename__ = "item_origin_occurrences"
    __table_args__ = (
        UniqueConstraint(
            "item_origin_profile_id",
            "assessment_occurrence_revision_id",
            name="uq_item_origin_occurrence",
        ),
        ForeignKeyConstraint(
            ["assessment_occurrence_id", "assessment_occurrence_revision_id"],
            [
                "assessment_occurrence_revisions.assessment_occurrence_id",
                "assessment_occurrence_revisions.assessment_occurrence_revision_id",
            ],
            name="fk_item_origin_occurrence_revision_identity",
        ),
        Index("ix_item_origin_occurrences_reverse", "assessment_occurrence_revision_id"),
    )

    item_origin_occurrence_id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    item_origin_profile_id: Mapped[str] = mapped_column(
        ForeignKey("item_origin_profiles.item_origin_profile_id", ondelete="CASCADE"),
        nullable=False,
    )
    assessment_occurrence_id: Mapped[str] = mapped_column(String(43), nullable=False)
    assessment_occurrence_revision_id: Mapped[str] = mapped_column(String(41), nullable=False)
    occurrence_revision_sha256: Mapped[str] = mapped_column(String(71), nullable=False)


class ItemOriginDerivationRecord(Base):
    __tablename__ = "item_origin_derivations"
    __table_args__ = (
        UniqueConstraint(
            "item_origin_profile_id",
            "source_kind",
            "logical_id",
            "revision_id",
            name="uq_item_origin_derivation",
        ),
        CheckConstraint(
            "source_kind IN ('ITEM_REVISION','DOCUMENT_REVISION',"
            "'ASSESSMENT_SOURCE_BUNDLE_REVISION')",
            name="ck_item_origin_derivation_kind",
        ),
        CheckConstraint(
            "relation IN ('DERIVED_FROM','TRANSLATED_FROM','DIGITIZED_FROM','RECONSTRUCTED_FROM')",
            name="ck_item_origin_derivation_relation",
        ),
        CheckConstraint(
            "(source_kind = 'ITEM_REVISION' AND logical_id ~ '^item_[0-9a-f]{32}$' "
            "AND revision_id ~ '^itemrev_[0-9a-f]{32}$') OR "
            "(source_kind = 'DOCUMENT_REVISION' AND logical_id ~ '^edudoc_[0-9a-f]{32}$' "
            "AND revision_id ~ '^edudocrev_[0-9a-f]{32}$') OR "
            "(source_kind = 'ASSESSMENT_SOURCE_BUNDLE_REVISION' "
            "AND logical_id ~ '^assessbundle_[0-9a-f]{32}$' "
            "AND revision_id ~ '^assessbundlerev_[0-9a-f]{32}$')",
            name="ck_item_origin_derivation_typed_pointer",
        ),
        Index("ix_item_origin_derivations_reverse", "source_kind", "revision_id"),
    )

    item_origin_derivation_id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    item_origin_profile_id: Mapped[str] = mapped_column(
        ForeignKey("item_origin_profiles.item_origin_profile_id", ondelete="CASCADE"),
        nullable=False,
    )
    source_kind: Mapped[str] = mapped_column(String(48), nullable=False)
    logical_id: Mapped[str] = mapped_column(String(64), nullable=False)
    revision_id: Mapped[str] = mapped_column(String(64), nullable=False)
    manifest_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    relation: Mapped[str] = mapped_column(String(32), nullable=False)


class ItemOriginProvenanceRecord(Base):
    __tablename__ = "item_origin_provenance"
    __table_args__ = (
        UniqueConstraint(
            "item_origin_profile_id",
            "provenance_kind",
            "logical_id",
            "revision_id",
            name="uq_item_origin_provenance",
            postgresql_nulls_not_distinct=True,
        ),
        CheckConstraint(
            "provenance_kind IN ('WORKFLOW','CONTENT_INTAKE','ITEM_PROVENANCE',"
            "'MANUAL_REVIEW','EXTRACTION_ACCEPTANCE')",
            name="ck_item_origin_provenance_kind",
        ),
        CheckConstraint(
            "(provenance_kind = 'WORKFLOW' AND logical_id ~ '^workflow_[0-9a-f]{32}$' "
            "AND revision_id ~ '^execplan_[0-9a-f]{32}$') OR "
            "(provenance_kind = 'CONTENT_INTAKE' AND logical_id ~ '^intake_[0-9a-f]{32}$' "
            "AND revision_id ~ '^rev_[0-9a-f]{32}$') OR "
            "(provenance_kind = 'ITEM_PROVENANCE' "
            "AND logical_id ~ '^provenance_[0-9a-f]{32}$' AND revision_id IS NULL) OR "
            "(provenance_kind = 'MANUAL_REVIEW' "
            "AND logical_id ~ '^itemacceptance_[0-9a-f]{32}$' "
            "AND revision_id ~ '^rev_[0-9a-f]{32}$') OR "
            "(provenance_kind = 'EXTRACTION_ACCEPTANCE' "
            "AND logical_id ~ '^itemacceptance_[0-9a-f]{32}$' "
            "AND revision_id ~ '^rev_[0-9a-f]{32}$')",
            name="ck_item_origin_provenance_typed_pointer",
        ),
        Index("ix_item_origin_provenance_reverse", "provenance_kind", "logical_id"),
    )

    item_origin_provenance_id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    item_origin_profile_id: Mapped[str] = mapped_column(
        ForeignKey("item_origin_profiles.item_origin_profile_id", ondelete="CASCADE"),
        nullable=False,
    )
    provenance_kind: Mapped[str] = mapped_column(String(24), nullable=False)
    logical_id: Mapped[str] = mapped_column(String(128), nullable=False)
    revision_id: Mapped[str | None] = mapped_column(String(128))
    evidence_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
