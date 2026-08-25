"""SQLAlchemy records for manual intake and immutable content pack releases."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from eom_orchestrator.models import Base
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column


class ContentIntakeBatchRecord(Base):
    __tablename__ = "content_intake_batches"
    __table_args__ = (
        CheckConstraint(
            "state IN ('RECEIVED','HASHED','ANALYSIS_PENDING','ANALYSIS_ATTACHED',"
            "'VALIDATING','NEEDS_DECISION','ACCEPTED','REJECTED','SUPERSEDED','IMPORTED','FAILED')",
            name="ck_content_intake_batches_state",
        ),
    )

    intake_batch_id: Mapped[str] = mapped_column(String(39), primary_key=True)
    batch_name: Mapped[str] = mapped_column(String(128), nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    purpose: Mapped[str] = mapped_column(String(500), nullable=False)
    received_by: Mapped[str] = mapped_column(String(128), nullable=False)
    source_owner_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_owner_reference: Mapped[str] = mapped_column(String(128), nullable=False)
    source_manifest_artifact_id: Mapped[str | None] = mapped_column(
        ForeignKey("artifacts.logical_artifact_id"), nullable=True
    )
    source_manifest_artifact_revision_id: Mapped[str | None] = mapped_column(
        ForeignKey("artifact_revisions.revision_id"), nullable=True
    )
    source_manifest_sha256: Mapped[str | None] = mapped_column(String(71), nullable=True)
    source_fingerprint: Mapped[str] = mapped_column(String(71), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lock_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class ContentIntakeSourceFileRecord(Base):
    __tablename__ = "content_intake_source_files"
    __table_args__ = (
        UniqueConstraint("intake_batch_id", "relative_path", name="uq_intake_source_path"),
        UniqueConstraint(
            "intake_batch_id", "sha256", "declared_role", name="uq_intake_source_hash_role"
        ),
    )

    source_file_id: Mapped[str] = mapped_column(String(43), primary_key=True)
    intake_batch_id: Mapped[str] = mapped_column(
        ForeignKey("content_intake_batches.intake_batch_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    normalized_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    relative_path: Mapped[str] = mapped_column(Text, nullable=False)
    media_type: Mapped[str] = mapped_column(String(128), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    artifact_id: Mapped[str] = mapped_column(
        ForeignKey("artifacts.logical_artifact_id"), nullable=False
    )
    artifact_revision_id: Mapped[str] = mapped_column(
        ForeignKey("artifact_revisions.revision_id"), nullable=False
    )
    declared_role: Mapped[str] = mapped_column(String(32), nullable=False)
    declared_description: Mapped[str] = mapped_column(String(500), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ContentIntakeAnalysisRecord(Base):
    __tablename__ = "content_intake_analyses"

    analysis_id: Mapped[str] = mapped_column(String(41), primary_key=True)
    intake_batch_id: Mapped[str] = mapped_column(
        ForeignKey("content_intake_batches.intake_batch_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    proposal_key: Mapped[str] = mapped_column(String(128), nullable=False)
    analysis_source_type: Mapped[str] = mapped_column(String(40), nullable=False)
    analysis_report_artifact_id: Mapped[str] = mapped_column(
        ForeignKey("artifacts.logical_artifact_id"), nullable=False
    )
    analysis_report_artifact_revision_id: Mapped[str] = mapped_column(
        ForeignKey("artifact_revisions.revision_id"), nullable=False
    )
    analysis_report_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    mapping_proposal_artifact_id: Mapped[str] = mapped_column(
        ForeignKey("artifacts.logical_artifact_id"), nullable=False
    )
    mapping_proposal_artifact_revision_id: Mapped[str] = mapped_column(
        ForeignKey("artifact_revisions.revision_id"), nullable=False
    )
    mapping_proposal_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    uncertainties_artifact_id: Mapped[str] = mapped_column(
        ForeignKey("artifacts.logical_artifact_id"), nullable=False
    )
    uncertainties_artifact_revision_id: Mapped[str] = mapped_column(
        ForeignKey("artifact_revisions.revision_id"), nullable=False
    )
    uncertainties_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    created_by: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    immutable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class ContentIntakeDecisionRecord(Base):
    __tablename__ = "content_intake_decisions"

    decision_id: Mapped[str] = mapped_column(String(41), primary_key=True)
    intake_batch_id: Mapped[str] = mapped_column(
        ForeignKey("content_intake_batches.intake_batch_id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    analysis_id: Mapped[str] = mapped_column(
        ForeignKey("content_intake_analyses.analysis_id"), nullable=False
    )
    decision: Mapped[str] = mapped_column(String(32), nullable=False)
    decision_artifact_id: Mapped[str] = mapped_column(
        ForeignKey("artifacts.logical_artifact_id"), nullable=False
    )
    decision_artifact_revision_id: Mapped[str] = mapped_column(
        ForeignKey("artifact_revisions.revision_id"), nullable=False
    )
    decision_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    decided_by: Mapped[str] = mapped_column(String(128), nullable=False)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    notes: Mapped[str] = mapped_column(Text, nullable=False)
    immutable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class ContentIntakeEventRecord(Base):
    __tablename__ = "content_intake_events"
    __table_args__ = (
        UniqueConstraint("intake_batch_id", "sequence", name="uq_intake_event_sequence"),
    )

    event_id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    intake_batch_id: Mapped[str] = mapped_column(
        ForeignKey("content_intake_batches.intake_batch_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    prior_state: Mapped[str | None] = mapped_column(String(32), nullable=True)
    new_state: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(128), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class EducationalDocumentRecord(Base):
    __tablename__ = "educational_documents"
    __table_args__ = (
        CheckConstraint(
            "lifecycle_state IN ('ACTIVE','RETIRED')",
            name="ck_educational_documents_lifecycle",
        ),
    )

    document_id: Mapped[str] = mapped_column(String(39), primary_key=True)
    document_key: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    document_kind: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    lifecycle_state: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    current_revision_id: Mapped[str | None] = mapped_column(
        ForeignKey(
            "educational_document_revisions.document_revision_id",
            name="fk_educational_documents_current_revision",
            use_alter=True,
        ),
        nullable=True,
        unique=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_by: Mapped[str] = mapped_column(String(128), nullable=False)
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    retirement_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    lock_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class EducationalDocumentRevisionRecord(Base):
    __tablename__ = "educational_document_revisions"
    __table_args__ = (
        UniqueConstraint(
            "document_id",
            "revision_number",
            name="uq_educational_document_revision_number",
        ),
        UniqueConstraint("registration_key", name="uq_educational_document_registration_key"),
        UniqueConstraint(
            "registration_request_sha256",
            name="uq_educational_document_registration_request_sha",
        ),
        CheckConstraint(
            "revision_number > 0", name="ck_educational_document_revision_number_positive"
        ),
        CheckConstraint(
            "revision_state = 'APPROVED'", name="ck_educational_document_revision_state"
        ),
        Index(
            "ix_educational_document_revision_publisher_volume",
            "publisher_key",
            "curriculum_volume",
            "document_revision_id",
        ),
        Index(
            "ix_educational_document_revision_source_sha",
            "source_sha256",
            "document_revision_id",
        ),
    )

    document_revision_id: Mapped[str] = mapped_column(String(42), primary_key=True)
    document_id: Mapped[str] = mapped_column(
        ForeignKey("educational_documents.document_id"), nullable=False, index=True
    )
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    previous_revision_id: Mapped[str | None] = mapped_column(
        ForeignKey("educational_document_revisions.document_revision_id"), nullable=True
    )
    revision_state: Mapped[str] = mapped_column(String(16), nullable=False)
    registration_key: Mapped[str] = mapped_column(String(200), nullable=False)
    registration_request_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    publisher_key: Mapped[str] = mapped_column(String(64), nullable=False)
    publisher_label: Mapped[str] = mapped_column(String(100), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    curriculum_volume: Mapped[str | None] = mapped_column(String(8), nullable=True)
    edition_label: Mapped[str] = mapped_column(String(100), nullable=False)
    language: Mapped[str] = mapped_column(String(16), nullable=False)
    source_artifact_id: Mapped[str] = mapped_column(
        ForeignKey("artifacts.logical_artifact_id"), nullable=False
    )
    source_artifact_revision_id: Mapped[str] = mapped_column(
        ForeignKey("artifact_revisions.revision_id"), nullable=False
    )
    source_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    source_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    source_page_count: Mapped[int] = mapped_column(Integer, nullable=False)
    analysis_artifact_id: Mapped[str] = mapped_column(
        ForeignKey("artifacts.logical_artifact_id"), nullable=False
    )
    analysis_artifact_revision_id: Mapped[str] = mapped_column(
        ForeignKey("artifact_revisions.revision_id"), nullable=False
    )
    analysis_manifest_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    rights_artifact_id: Mapped[str] = mapped_column(
        ForeignKey("artifacts.logical_artifact_id"), nullable=False
    )
    rights_artifact_revision_id: Mapped[str] = mapped_column(
        ForeignKey("artifact_revisions.revision_id"), nullable=False
    )
    rights_attestation_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    revision_manifest_artifact_id: Mapped[str] = mapped_column(
        ForeignKey("artifacts.logical_artifact_id"), nullable=False
    )
    revision_manifest_artifact_revision_id: Mapped[str] = mapped_column(
        ForeignKey("artifact_revisions.revision_id"), nullable=False
    )
    revision_manifest_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_by: Mapped[str] = mapped_column(String(128), nullable=False)


class EducationalDocumentRegistrationRecord(Base):
    __tablename__ = "educational_document_registrations"
    __table_args__ = (
        UniqueConstraint(
            "document_id",
            "revision_number",
            name="uq_educational_document_registration_revision_number",
        ),
        CheckConstraint(
            "state IN ('PREPARED','COMMITTED','FAILED')",
            name="ck_educational_document_registrations_state",
        ),
        CheckConstraint(
            "revision_number > 0",
            name="ck_educational_document_registration_revision_positive",
        ),
    )

    document_registration_id: Mapped[str] = mapped_column(String(42), primary_key=True)
    registration_key: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    registration_request_sha256: Mapped[str] = mapped_column(
        String(71), unique=True, nullable=False
    )
    document_id: Mapped[str] = mapped_column(
        ForeignKey("educational_documents.document_id"), nullable=False, index=True
    )
    document_revision_id: Mapped[str] = mapped_column(String(42), unique=True, nullable=False)
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    previous_revision_id: Mapped[str | None] = mapped_column(String(42), nullable=True)
    state: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    failure_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lock_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class ContentPackRecord(Base):
    __tablename__ = "content_packs"

    content_pack_id: Mapped[str] = mapped_column(String(44), primary_key=True)
    pack_key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    locale: Mapped[str] = mapped_column(String(16), nullable=False)
    domain_key: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ContentPackReleaseRecord(Base):
    __tablename__ = "content_pack_releases"
    __table_args__ = (
        UniqueConstraint("content_pack_id", "version", name="uq_content_pack_version"),
        CheckConstraint(
            "state IN ('DRAFT','VALIDATED','RELEASED','DEPRECATED','RETIRED','REJECTED')",
            name="ck_content_pack_release_state",
        ),
    )

    content_pack_release_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    content_pack_id: Mapped[str] = mapped_column(
        ForeignKey("content_packs.content_pack_id"), nullable=False, index=True
    )
    version: Mapped[str] = mapped_column(String(32), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(16), nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    source_tree_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    bundle_sha256: Mapped[str] = mapped_column(String(71), nullable=False, unique=True)
    manifest_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    bundle_artifact_id: Mapped[str] = mapped_column(
        ForeignKey("artifacts.logical_artifact_id"), nullable=False
    )
    bundle_artifact_revision_id: Mapped[str] = mapped_column(
        ForeignKey("artifact_revisions.revision_id"), nullable=False
    )
    canonical_manifest_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    compatibility_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    validated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deprecated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    released_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    lock_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class ContentPackFileRecord(Base):
    __tablename__ = "content_pack_files"
    __table_args__ = (
        UniqueConstraint("content_pack_release_id", "relative_path", name="uq_pack_file_path"),
    )

    content_pack_file_id: Mapped[str] = mapped_column(String(41), primary_key=True)
    content_pack_release_id: Mapped[str] = mapped_column(
        ForeignKey("content_pack_releases.content_pack_release_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    relative_path: Mapped[str] = mapped_column(Text, nullable=False)
    media_type: Mapped[str] = mapped_column(String(128), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    logical_role: Mapped[str] = mapped_column(String(64), nullable=False)
    schema_ref: Mapped[str | None] = mapped_column(String(256), nullable=True)


class ContentPackProfileRecord(Base):
    __tablename__ = "content_pack_profiles"
    __table_args__ = (
        UniqueConstraint(
            "content_pack_release_id", "profile_type", "profile_key", name="uq_pack_profile"
        ),
    )

    content_pack_profile_id: Mapped[str] = mapped_column(String(44), primary_key=True)
    content_pack_release_id: Mapped[str] = mapped_column(
        ForeignKey("content_pack_releases.content_pack_release_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    profile_type: Mapped[str] = mapped_column(String(32), nullable=False)
    profile_key: Mapped[str] = mapped_column(String(128), nullable=False)
    profile_version: Mapped[str] = mapped_column(String(32), nullable=False)
    profile_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    template_relative_path: Mapped[str] = mapped_column(Text, nullable=False)
    input_schema_ref: Mapped[str] = mapped_column(String(256), nullable=False)
    output_schema_ref: Mapped[str] = mapped_column(String(256), nullable=False)
    compiled_profile_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)


class ContentPackActivationRecord(Base):
    __tablename__ = "content_pack_activations"
    __table_args__ = (
        Index(
            "uq_active_pack_environment",
            "environment",
            "pack_key",
            unique=True,
            postgresql_where=text("active = true"),
        ),
    )

    activation_id: Mapped[str] = mapped_column(String(43), primary_key=True)
    environment: Mapped[str] = mapped_column(String(32), nullable=False)
    pack_key: Mapped[str] = mapped_column(String(64), nullable=False)
    content_pack_release_id: Mapped[str] = mapped_column(
        ForeignKey("content_pack_releases.content_pack_release_id"), nullable=False
    )
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    activated_by: Mapped[str] = mapped_column(String(128), nullable=False)
    activated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    deactivated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    lock_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class ContentPackEventRecord(Base):
    __tablename__ = "content_pack_events"
    __table_args__ = (
        UniqueConstraint(
            "content_pack_release_id", "sequence", name="uq_content_pack_event_sequence"
        ),
    )

    event_id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    content_pack_release_id: Mapped[str] = mapped_column(
        ForeignKey("content_pack_releases.content_pack_release_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    prior_state: Mapped[str | None] = mapped_column(String(32), nullable=True)
    new_state: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(128), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ItemRecord(Base):
    __tablename__ = "items"
    __table_args__ = (
        CheckConstraint(
            "lifecycle_state IN ('DRAFT','ACTIVE','RETIRED','DELETED_SOFT')",
            name="ck_items_lifecycle_state",
        ),
        Index("ix_items_keyset", "created_at", "item_id"),
    )

    item_id: Mapped[str] = mapped_column(String(37), primary_key=True)
    human_reference_code: Mapped[str | None] = mapped_column(String(128), unique=True)
    lifecycle_state: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    current_revision_id: Mapped[str | None] = mapped_column(
        ForeignKey(
            "item_revisions.item_revision_id",
            name="fk_items_current_revision",
            use_alter=True,
        ),
        unique=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_by: Mapped[str] = mapped_column(String(128), nullable=False)
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retirement_reason: Mapped[str | None] = mapped_column(Text)
    lock_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class ItemRevisionRecord(Base):
    __tablename__ = "item_revisions"
    __table_args__ = (
        UniqueConstraint("item_id", "revision_number", name="uq_item_revision_number"),
        UniqueConstraint("registration_key", name="uq_item_registration_key"),
        CheckConstraint("revision_number > 0", name="ck_item_revision_number_positive"),
        CheckConstraint(
            "revision_state IN ('DRAFT','IN_REVIEW','APPROVED','REJECTED','SUPERSEDED','RETIRED')",
            name="ck_item_revisions_state",
        ),
    )

    item_revision_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    item_id: Mapped[str] = mapped_column(ForeignKey("items.item_id"), nullable=False, index=True)
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    revision_state: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    registration_key: Mapped[str] = mapped_column(String(200), nullable=False)
    content_pack_release_id: Mapped[str] = mapped_column(
        ForeignKey("content_pack_releases.content_pack_release_id"), nullable=False, index=True
    )
    workflow_id: Mapped[str] = mapped_column(
        ForeignKey("workflow_instances.workflow_id"), nullable=False, index=True
    )
    workflow_definition_version: Mapped[str] = mapped_column(String(32), nullable=False)
    source_workflow_step_run_id: Mapped[str] = mapped_column(
        ForeignKey("workflow_step_runs.step_run_id"), nullable=False
    )
    manifest_artifact_id: Mapped[str] = mapped_column(
        ForeignKey("artifacts.logical_artifact_id"), nullable=False
    )
    manifest_artifact_revision_id: Mapped[str] = mapped_column(
        ForeignKey("artifact_revisions.revision_id"), nullable=False
    )
    manifest_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    item_type_key: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    primary_taxonomy_ref: Mapped[str | None] = mapped_column(String(256), index=True)
    difficulty_band: Mapped[str | None] = mapped_column(String(64), index=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    metadata_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )
    created_by: Mapped[str] = mapped_column(String(128), nullable=False)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_by: Mapped[str | None] = mapped_column(String(128))
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    superseded_by_revision_id: Mapped[str | None] = mapped_column(
        ForeignKey("item_revisions.item_revision_id")
    )
    lock_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class ItemComponentRecord(Base):
    __tablename__ = "item_components"
    __table_args__ = (
        UniqueConstraint(
            "item_revision_id", "component_type", "ordinal", name="uq_item_component_position"
        ),
        CheckConstraint("ordinal >= 0", name="ck_item_component_ordinal_nonnegative"),
    )

    item_component_id: Mapped[str] = mapped_column(String(46), primary_key=True)
    item_revision_id: Mapped[str] = mapped_column(
        ForeignKey("item_revisions.item_revision_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    component_type: Mapped[str] = mapped_column(String(64), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    schema_ref: Mapped[str] = mapped_column(String(256), nullable=False)
    media_type: Mapped[str] = mapped_column(String(128), nullable=False)
    artifact_id: Mapped[str] = mapped_column(
        ForeignKey("artifacts.logical_artifact_id"), nullable=False
    )
    artifact_revision_id: Mapped[str] = mapped_column(
        ForeignKey("artifact_revisions.revision_id"), nullable=False
    )
    sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    logical_name: Mapped[str] = mapped_column(String(128), nullable=False)
    required: Mapped[bool] = mapped_column(Boolean, nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)


class ItemMetadataSnapshotRecord(Base):
    __tablename__ = "item_metadata_snapshots"

    item_metadata_snapshot_id: Mapped[str] = mapped_column(String(41), primary_key=True)
    item_revision_id: Mapped[str] = mapped_column(
        ForeignKey("item_revisions.item_revision_id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    schema_ref: Mapped[str] = mapped_column(String(256), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(32), nullable=False)
    taxonomy_refs: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    tag_keys: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    difficulty_band: Mapped[str] = mapped_column(String(64), nullable=False)
    item_type_key: Mapped[str] = mapped_column(String(128), nullable=False)
    estimated_time_seconds: Mapped[int | None] = mapped_column(Integer)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    metadata_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ItemProvenanceRecord(Base):
    __tablename__ = "item_provenance"

    item_provenance_id: Mapped[str] = mapped_column(String(43), primary_key=True)
    item_revision_id: Mapped[str] = mapped_column(
        ForeignKey("item_revisions.item_revision_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    provenance_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_key: Mapped[str] = mapped_column(String(128), nullable=False)
    source_reference: Mapped[str] = mapped_column(String(256), nullable=False)
    source_intake_batch_id: Mapped[str | None] = mapped_column(
        ForeignKey("content_intake_batches.intake_batch_id")
    )
    source_file_id: Mapped[str | None] = mapped_column(
        ForeignKey("content_intake_source_files.source_file_id")
    )
    source_artifact_id: Mapped[str | None] = mapped_column(
        ForeignKey("artifacts.logical_artifact_id")
    )
    source_artifact_revision_id: Mapped[str | None] = mapped_column(
        ForeignKey("artifact_revisions.revision_id")
    )
    source_sha256: Mapped[str | None] = mapped_column(String(71))
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ItemRelationshipRecord(Base):
    __tablename__ = "item_relationships"
    __table_args__ = (
        UniqueConstraint(
            "source_item_id", "target_item_id", "relationship_type", name="uq_item_relationship"
        ),
        CheckConstraint("source_item_id <> target_item_id", name="ck_item_relationship_not_self"),
    )

    item_relationship_id: Mapped[str] = mapped_column(String(45), primary_key=True)
    source_item_id: Mapped[str] = mapped_column(ForeignKey("items.item_id"), nullable=False)
    target_item_id: Mapped[str] = mapped_column(ForeignKey("items.item_id"), nullable=False)
    relationship_type: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ItemReviewRecord(Base):
    __tablename__ = "item_review_records"

    item_review_record_id: Mapped[str] = mapped_column(String(43), primary_key=True)
    item_revision_id: Mapped[str] = mapped_column(
        ForeignKey("item_revisions.item_revision_id"), nullable=False, index=True
    )
    workflow_id: Mapped[str] = mapped_column(
        ForeignKey("workflow_instances.workflow_id"), nullable=False
    )
    review_artifact_id: Mapped[str] = mapped_column(
        ForeignKey("artifacts.logical_artifact_id"), nullable=False
    )
    review_artifact_revision_id: Mapped[str] = mapped_column(
        ForeignKey("artifact_revisions.revision_id"), nullable=False
    )
    review_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    decision: Mapped[str] = mapped_column(String(32), nullable=False)
    severity_summary: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    reviewer_actor_id: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ItemEventRecord(Base):
    __tablename__ = "item_events"
    __table_args__ = (UniqueConstraint("item_id", "sequence", name="uq_item_event_sequence"),)

    event_id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    item_id: Mapped[str] = mapped_column(
        ForeignKey("items.item_id", ondelete="CASCADE"), nullable=False, index=True
    )
    item_revision_id: Mapped[str | None] = mapped_column(
        ForeignKey("item_revisions.item_revision_id")
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    prior_state: Mapped[str | None] = mapped_column(String(32))
    new_state: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(128), nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    command_id: Mapped[str | None] = mapped_column(String(64))
    idempotency_key: Mapped[str | None] = mapped_column(String(200))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class DeliverableRecord(Base):
    __tablename__ = "deliverables"
    __table_args__ = (
        CheckConstraint(
            "deliverable_type IN ('MOCK_EXAM','TEXTBOOK','WEEKLY','OTHER')",
            name="ck_deliverables_type",
        ),
        CheckConstraint(
            "lifecycle_state IN ('PLANNED','IN_PRODUCTION','RELEASED','CANCELLED','ARCHIVED')",
            name="ck_deliverables_state",
        ),
    )

    deliverable_id: Mapped[str] = mapped_column(String(44), primary_key=True)
    deliverable_key: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    deliverable_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    edition: Mapped[str] = mapped_column(String(64), nullable=False)
    lifecycle_state: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_by: Mapped[str] = mapped_column(String(128), nullable=False)


class DeliverableRevisionRecord(Base):
    __tablename__ = "deliverable_revisions"
    __table_args__ = (
        UniqueConstraint(
            "deliverable_id", "revision_number", name="uq_deliverable_revision_number"
        ),
        CheckConstraint("revision_number > 0", name="ck_deliverable_revision_number_positive"),
    )

    deliverable_revision_id: Mapped[str] = mapped_column(String(41), primary_key=True)
    deliverable_id: Mapped[str] = mapped_column(
        ForeignKey("deliverables.deliverable_id"), nullable=False, index=True
    )
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    metadata_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class UsagePlanRecord(Base):
    __tablename__ = "usage_plans"
    __table_args__ = (
        UniqueConstraint(
            "deliverable_id", "planned_section", "planned_sequence", name="uq_usage_plan_placement"
        ),
        CheckConstraint("planned_sequence > 0", name="ck_usage_plan_sequence_positive"),
        CheckConstraint(
            "status IN ('PLANNED','RESERVED','CANCELLED','FULFILLED')",
            name="ck_usage_plans_status",
        ),
    )

    usage_plan_id: Mapped[str] = mapped_column(String(42), primary_key=True)
    item_id: Mapped[str] = mapped_column(ForeignKey("items.item_id"), nullable=False, index=True)
    preferred_item_revision_id: Mapped[str | None] = mapped_column(
        ForeignKey("item_revisions.item_revision_id")
    )
    deliverable_id: Mapped[str] = mapped_column(
        ForeignKey("deliverables.deliverable_id"), nullable=False, index=True
    )
    deliverable_revision_id: Mapped[str | None] = mapped_column(
        ForeignKey("deliverable_revisions.deliverable_revision_id")
    )
    planned_section: Mapped[str] = mapped_column(String(128), nullable=False)
    planned_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    planned_points: Mapped[str | None] = mapped_column(String(16))
    planned_role: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    reserved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fulfilled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    notes: Mapped[str | None] = mapped_column(Text)
    lock_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class UsageRecord(Base):
    __tablename__ = "usage_records"
    __table_args__ = (
        UniqueConstraint(
            "deliverable_revision_id", "section", "sequence", name="uq_usage_record_placement"
        ),
        CheckConstraint("sequence > 0", name="ck_usage_record_sequence_positive"),
    )

    usage_record_id: Mapped[str] = mapped_column(String(44), primary_key=True)
    item_id: Mapped[str] = mapped_column(ForeignKey("items.item_id"), nullable=False, index=True)
    item_revision_id: Mapped[str] = mapped_column(
        ForeignKey("item_revisions.item_revision_id"), nullable=False, index=True
    )
    deliverable_id: Mapped[str] = mapped_column(
        ForeignKey("deliverables.deliverable_id"), nullable=False
    )
    deliverable_revision_id: Mapped[str] = mapped_column(
        ForeignKey("deliverable_revisions.deliverable_revision_id"), nullable=False
    )
    section: Mapped[str] = mapped_column(String(128), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    page: Mapped[int | None] = mapped_column(Integer)
    points: Mapped[str | None] = mapped_column(String(16))
    usage_role: Mapped[str] = mapped_column(String(64), nullable=False)
    source_usage_plan_id: Mapped[str | None] = mapped_column(
        ForeignKey("usage_plans.usage_plan_id"), unique=True
    )
    recorded_by: Mapped[str] = mapped_column(String(128), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)


class DeliverableEventRecord(Base):
    __tablename__ = "deliverable_events"
    __table_args__ = (
        UniqueConstraint("deliverable_id", "sequence", name="uq_deliverable_event_sequence"),
    )

    event_id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    deliverable_id: Mapped[str] = mapped_column(
        ForeignKey("deliverables.deliverable_id", ondelete="CASCADE"), nullable=False, index=True
    )
    deliverable_revision_id: Mapped[str | None] = mapped_column(
        ForeignKey("deliverable_revisions.deliverable_revision_id")
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    prior_state: Mapped[str | None] = mapped_column(String(32))
    new_state: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(128), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
