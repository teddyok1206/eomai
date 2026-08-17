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


class ContentPackRecord(Base):
    __tablename__ = "content_packs"

    content_pack_id: Mapped[str] = mapped_column(String(41), primary_key=True)
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
        UniqueConstraint("bundle_sha256", name="uq_content_pack_bundle_hash"),
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
    bundle_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
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
