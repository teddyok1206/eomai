"""Pointer-only immutable embedding registrations and the mutable index head."""

from __future__ import annotations

from datetime import datetime

from eom_orchestrator.models import Base
from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column


class EmbeddingEncodingRecord(Base):
    __tablename__ = "embedding_encodings"
    __table_args__ = (
        CheckConstraint(
            "encoding_sha256 ~ '^sha256:[0-9a-f]{64}$' AND "
            "space_sha256 ~ '^sha256:[0-9a-f]{64}$' AND "
            "input_text_sha256 ~ '^sha256:[0-9a-f]{64}$' AND "
            "shard_sha256 ~ '^sha256:[0-9a-f]{64}$'",
            name="ck_embedding_encoding_hashes",
        ),
        CheckConstraint(
            "storage_partition ~ '^[a-z0-9][a-z0-9._-]{0,63}$'",
            name="ck_embedding_encoding_partition",
        ),
        CheckConstraint("row_index >= 0 AND row_index < 1024", name="ck_embedding_encoding_row"),
        CheckConstraint(
            "shard_member_path = 'shard.json' AND "
            "shard_schema_ref = 'eom://schemas/knowledge/embedding-vector-shard/1.0' AND "
            "shard_media_type = 'application/json'",
            name="ck_embedding_encoding_member",
        ),
        ForeignKeyConstraint(
            ("shard_artifact_id", "shard_artifact_revision_id"),
            ("artifact_revisions.logical_artifact_id", "artifact_revisions.revision_id"),
            name="fk_embedding_encoding_shard_revision",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "storage_partition",
            "space_sha256",
            "input_text_sha256",
            name="uq_embedding_encoding_input",
        ),
        UniqueConstraint(
            "shard_artifact_revision_id",
            "shard_member_path",
            "row_index",
            name="uq_embedding_encoding_row",
        ),
        Index("ix_embedding_encoding_shard", "shard_artifact_id", "shard_artifact_revision_id"),
    )

    encoding_sha256: Mapped[str] = mapped_column(String(71), primary_key=True)
    storage_partition: Mapped[str] = mapped_column(String(64), nullable=False)
    space_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    input_text_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    shard_artifact_id: Mapped[str] = mapped_column(String(41), nullable=False)
    shard_artifact_revision_id: Mapped[str] = mapped_column(String(36), nullable=False)
    shard_member_path: Mapped[str] = mapped_column(String(512), nullable=False)
    shard_schema_ref: Mapped[str] = mapped_column(String(256), nullable=False)
    shard_media_type: Mapped[str] = mapped_column(String(128), nullable=False)
    shard_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    row_index: Mapped[int] = mapped_column(Integer, nullable=False)
    registered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class EmbeddingSourceBindingRecord(Base):
    __tablename__ = "embedding_source_bindings"
    __table_args__ = (
        CheckConstraint(
            "binding_sha256 ~ '^sha256:[0-9a-f]{64}$' AND "
            "source_sha256 ~ '^sha256:[0-9a-f]{64}$' AND "
            "(solution_pointer_sha256 IS NULL OR "
            "solution_pointer_sha256 ~ '^sha256:[0-9a-f]{64}$') AND "
            "(review_evidence_sha256 IS NULL OR "
            "review_evidence_sha256 ~ '^sha256:[0-9a-f]{64}$') AND "
            "profile_sha256 ~ '^sha256:[0-9a-f]{64}$' AND "
            "policy_sha256 ~ '^sha256:[0-9a-f]{64}$' AND "
            "recipe_sha256 ~ '^sha256:[0-9a-f]{64}$' AND "
            "binding_manifest_sha256 ~ '^sha256:[0-9a-f]{64}$'",
            name="ck_embedding_binding_hashes",
        ),
        CheckConstraint(
            "source_class IN ('PAST_EXAM','APPROVED_ITEM')", name="ck_embedding_binding_source"
        ),
        CheckConstraint(
            "view IN ('CONTENT_ONLY','CONCRETE_FACETS','METADATA_ONLY')",
            name="ck_embedding_binding_view",
        ),
        CheckConstraint(
            "projection_version IN ('accepted-solution-comparison/1.0',"
            "'registered-item-review-comparison/1.0','public-solution-text/1.0')",
            name="ck_embedding_binding_projection",
        ),
        CheckConstraint(
            "solution_analysis_run_id IS NULL OR base_analysis_run_id <> solution_analysis_run_id",
            name="ck_embedding_binding_runs",
        ),
        CheckConstraint(
            "(evidence_kind = 'ACCEPTED_SOLUTION_ANALYSIS' AND "
            "solution_analysis_run_id IS NOT NULL AND solution_pointer_sha256 IS NOT NULL AND "
            "review_job_id IS NULL AND review_evidence_sha256 IS NULL AND "
            "projection_version = 'accepted-solution-comparison/1.0' AND "
            "base_analysis_run_id <> solution_analysis_run_id) OR "
            "(evidence_kind = 'REGISTERED_ITEM_REVIEW_SOLUTION' AND "
            "solution_analysis_run_id IS NULL AND solution_pointer_sha256 IS NULL AND "
            "review_job_id IS NOT NULL AND review_evidence_sha256 IS NOT NULL AND "
            "source_class = 'APPROVED_ITEM' AND "
            "projection_version = 'registered-item-review-comparison/1.0') OR "
            "(evidence_kind = 'PUBLIC_SOLUTION_REPORT' AND "
            "solution_pointer_sha256 IS NOT NULL AND "
            "review_job_id IS NULL AND review_evidence_sha256 IS NULL AND "
            "view = 'CONCRETE_FACETS' AND projection_version = 'public-solution-text/1.0' AND "
            "((source_class = 'PAST_EXAM' AND solution_analysis_run_id IS NOT NULL AND "
            "base_analysis_run_id <> solution_analysis_run_id) OR "
            "source_class = 'APPROVED_ITEM'))",
            name="ck_embedding_binding_evidence",
        ),
        CheckConstraint(
            "profile_id ~ '^inferenceprofile_[0-9a-f]{32}$' AND "
            "profile_revision_id ~ '^inferenceprofilerev_[0-9a-f]{32}$'",
            name="ck_embedding_binding_profile",
        ),
        CheckConstraint(
            "binding_manifest_member_path = 'index.json' AND "
            "binding_manifest_schema_ref IN "
            "('eom://schemas/knowledge/embedding-index-manifest/1.0',"
            "'eom://schemas/knowledge/embedding-index-manifest/2.0',"
            "'eom://schemas/knowledge/embedding-index-manifest/3.0') AND "
            "binding_manifest_media_type = 'application/json' AND "
            "((evidence_kind = 'ACCEPTED_SOLUTION_ANALYSIS' AND "
            "binding_manifest_schema_ref IN "
            "('eom://schemas/knowledge/embedding-index-manifest/1.0',"
            "'eom://schemas/knowledge/embedding-index-manifest/2.0')) OR "
            "(evidence_kind = 'REGISTERED_ITEM_REVIEW_SOLUTION' AND "
            "binding_manifest_schema_ref = 'eom://schemas/knowledge/embedding-index-manifest/2.0') "
            "OR (evidence_kind = 'PUBLIC_SOLUTION_REPORT' AND "
            "binding_manifest_schema_ref = 'eom://schemas/knowledge/embedding-index-manifest/3.0'))",
            name="ck_embedding_binding_member",
        ),
        ForeignKeyConstraint(
            ("item_id", "item_revision_id"),
            ("item_revisions.item_id", "item_revisions.item_revision_id"),
            name="fk_embedding_binding_item_revision",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ("binding_manifest_artifact_id", "binding_manifest_artifact_revision_id"),
            ("artifact_revisions.logical_artifact_id", "artifact_revisions.revision_id"),
            name="fk_embedding_binding_manifest_revision",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "item_revision_id",
            "graph_snapshot_revision_id",
            "policy_revision_id",
            "recipe_sha256",
            "view",
            "projection_version",
            "base_analysis_run_id",
            "profile_revision_id",
            "solution_analysis_run_id",
            "encoding_sha256",
            name="uq_embedding_binding_association",
        ),
        Index(
            "ix_embedding_binding_delta",
            "graph_snapshot_revision_id",
            "policy_revision_id",
            "recipe_sha256",
            "view",
            "projection_version",
            "item_revision_id",
            "base_analysis_run_id",
            "solution_analysis_run_id",
        ),
        Index("ix_embedding_binding_encoding", "encoding_sha256"),
        Index("ix_embedding_binding_source", "item_id", "item_revision_id"),
        Index(
            "uq_embedding_binding_registered_review",
            "item_revision_id",
            "graph_snapshot_revision_id",
            "policy_revision_id",
            "recipe_sha256",
            "view",
            "projection_version",
            "base_analysis_run_id",
            "profile_revision_id",
            "encoding_sha256",
            "review_job_id",
            "review_evidence_sha256",
            unique=True,
            postgresql_where=text("evidence_kind = 'REGISTERED_ITEM_REVIEW_SOLUTION'"),
        ),
        Index(
            "ix_embedding_binding_review_delta",
            "graph_snapshot_revision_id",
            "policy_revision_id",
            "recipe_sha256",
            "view",
            "projection_version",
            "item_revision_id",
            "base_analysis_run_id",
            "review_job_id",
            "review_evidence_sha256",
            postgresql_where=text("evidence_kind = 'REGISTERED_ITEM_REVIEW_SOLUTION'"),
        ),
        Index(
            "uq_embedding_binding_public_solution",
            "item_revision_id",
            "graph_snapshot_revision_id",
            "policy_revision_id",
            "recipe_sha256",
            "view",
            "projection_version",
            "base_analysis_run_id",
            "profile_revision_id",
            "encoding_sha256",
            "solution_pointer_sha256",
            unique=True,
            postgresql_where=text("evidence_kind = 'PUBLIC_SOLUTION_REPORT'"),
        ),
        Index(
            "ix_embedding_binding_public_solution_delta",
            "graph_snapshot_revision_id",
            "policy_revision_id",
            "recipe_sha256",
            "view",
            "projection_version",
            "item_revision_id",
            "base_analysis_run_id",
            "solution_pointer_sha256",
            postgresql_where=text("evidence_kind = 'PUBLIC_SOLUTION_REPORT'"),
        ),
    )

    binding_sha256: Mapped[str] = mapped_column(String(71), primary_key=True)
    encoding_sha256: Mapped[str] = mapped_column(
        ForeignKey("embedding_encodings.encoding_sha256", ondelete="RESTRICT"), nullable=False
    )
    item_id: Mapped[str] = mapped_column(String(37), nullable=False)
    item_revision_id: Mapped[str] = mapped_column(String(40), nullable=False)
    source_class: Mapped[str] = mapped_column(String(16), nullable=False)
    source_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    evidence_kind: Mapped[str] = mapped_column(
        String(40), nullable=False, server_default="ACCEPTED_SOLUTION_ANALYSIS"
    )
    base_analysis_run_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_analysis_runs.analysis_run_id", ondelete="RESTRICT"), nullable=False
    )
    solution_analysis_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("knowledge_analysis_runs.analysis_run_id", ondelete="RESTRICT"), nullable=True
    )
    solution_pointer_sha256: Mapped[str | None] = mapped_column(String(71), nullable=True)
    review_job_id: Mapped[str | None] = mapped_column(
        ForeignKey("jobs.job_id", name="fk_embedding_binding_review_job", ondelete="RESTRICT"),
        nullable=True,
    )
    review_evidence_sha256: Mapped[str | None] = mapped_column(String(71), nullable=True)
    profile_id: Mapped[str] = mapped_column(String(49), nullable=False)
    profile_revision_id: Mapped[str] = mapped_column(String(52), nullable=False)
    profile_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    graph_snapshot_revision_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_graph_snapshots.graph_snapshot_revision_id", ondelete="RESTRICT"),
        nullable=False,
    )
    policy_revision_id: Mapped[str] = mapped_column(
        ForeignKey(
            "education_retrieval_access_policy_revisions.access_policy_revision_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    policy_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    view: Mapped[str] = mapped_column(String(16), nullable=False)
    recipe_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    projection_version: Mapped[str] = mapped_column(String(64), nullable=False)
    binding_manifest_artifact_id: Mapped[str] = mapped_column(String(41), nullable=False)
    binding_manifest_artifact_revision_id: Mapped[str] = mapped_column(String(36), nullable=False)
    binding_manifest_member_path: Mapped[str] = mapped_column(String(512), nullable=False)
    binding_manifest_schema_ref: Mapped[str] = mapped_column(String(256), nullable=False)
    binding_manifest_media_type: Mapped[str] = mapped_column(String(128), nullable=False)
    binding_manifest_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    registered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class EmbeddingIndexRecord(Base):
    __tablename__ = "embedding_indexes"
    __table_args__ = (
        CheckConstraint("index_id ~ '^embeddingindex_[0-9a-f]{32}$'", name="ck_embedding_index_id"),
        CheckConstraint(
            "storage_partition ~ '^[a-z0-9][a-z0-9._-]{0,63}$' AND "
            "space_sha256 ~ '^sha256:[0-9a-f]{64}$' AND "
            "recipe_sha256 ~ '^sha256:[0-9a-f]{64}$'",
            name="ck_embedding_index_namespace_hashes",
        ),
        CheckConstraint(
            "view IN ('CONTENT_ONLY','CONCRETE_FACETS','METADATA_ONLY') AND "
            "((projection_version = 'accepted-solution-comparison/1.0' AND "
            "population_scope IN ('ALL_ADMITTED_GRAPH_ITEMS','OCCURRENCE_BACKED_PAST_EXAM')) OR "
            "(projection_version = 'mixed-solution-comparison/2.0' AND "
            "population_scope = 'ALL_ADMITTED_GRAPH_ITEMS') OR "
            "(projection_version = 'public-solution-text/1.0' AND "
            "view = 'CONCRETE_FACETS' AND population_scope = 'ALL_ADMITTED_GRAPH_ITEMS'))",
            name="ck_embedding_index_namespace",
        ),
        CheckConstraint(
            "(current_index_revision_id IS NULL AND lock_version = 1) OR "
            "(current_index_revision_id IS NOT NULL AND lock_version >= 2)",
            name="ck_embedding_index_current_version",
        ),
        UniqueConstraint(
            "corpus_id",
            "storage_partition",
            "space_sha256",
            "view",
            "recipe_sha256",
            "projection_version",
            "population_scope",
            name="uq_embedding_index_namespace",
        ),
        ForeignKeyConstraint(
            ("index_id", "current_index_revision_id"),
            ("embedding_index_revisions.index_id", "embedding_index_revisions.index_revision_id"),
            name="fk_embedding_index_current_revision",
            ondelete="RESTRICT",
            use_alter=True,
        ),
    )

    index_id: Mapped[str] = mapped_column(String(47), primary_key=True)
    corpus_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_corpora.corpus_id", ondelete="RESTRICT"), nullable=False
    )
    storage_partition: Mapped[str] = mapped_column(String(64), nullable=False)
    space_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    view: Mapped[str] = mapped_column(String(16), nullable=False)
    recipe_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    projection_version: Mapped[str] = mapped_column(String(64), nullable=False)
    population_scope: Mapped[str] = mapped_column(String(64), nullable=False)
    current_index_revision_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    lock_version: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class EmbeddingIndexRevisionRecord(Base):
    __tablename__ = "embedding_index_revisions"
    __table_args__ = (
        CheckConstraint(
            "index_revision_id ~ '^embeddingindexrev_[0-9a-f]{32}$'",
            name="ck_embedding_index_revision_id",
        ),
        CheckConstraint(
            "(revision_number = 1 AND previous_index_revision_id IS NULL) OR "
            "(revision_number > 1 AND previous_index_revision_id IS NOT NULL AND "
            "previous_index_revision_id <> index_revision_id)",
            name="ck_embedding_index_revision_predecessor",
        ),
        CheckConstraint(
            "policy_sha256 ~ '^sha256:[0-9a-f]{64}$' AND "
            "manifest_sha256 ~ '^sha256:[0-9a-f]{64}$' AND "
            "index_sha256 ~ '^sha256:[0-9a-f]{64}$' AND "
            "source_set_sha256 ~ '^sha256:[0-9a-f]{64}$' AND "
            "binding_set_sha256 ~ '^sha256:[0-9a-f]{64}$' AND "
            "registration_request_sha256 ~ '^sha256:[0-9a-f]{64}$'",
            name="ck_embedding_index_revision_hashes",
        ),
        CheckConstraint(
            "binding_count >= 1 AND eligible_source_count >= binding_count AND "
            "eligible_source_count <= CASE WHEN "
            "manifest_schema_ref = 'eom://schemas/knowledge/embedding-index-manifest/3.0' "
            "THEN 16384 ELSE 1024 END",
            name="ck_embedding_index_revision_coverage",
        ),
        CheckConstraint(
            "manifest_member_path = 'index.json' AND "
            "manifest_schema_ref IN ('eom://schemas/knowledge/embedding-index-manifest/1.0',"
            "'eom://schemas/knowledge/embedding-index-manifest/2.0',"
            "'eom://schemas/knowledge/embedding-index-manifest/3.0') AND "
            "manifest_media_type = 'application/json'",
            name="ck_embedding_index_revision_member",
        ),
        CheckConstraint(
            "operation_key ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'",
            name="ck_embedding_index_registration_key",
        ),
        ForeignKeyConstraint(
            ("index_id", "previous_index_revision_id"),
            ("embedding_index_revisions.index_id", "embedding_index_revisions.index_revision_id"),
            name="fk_embedding_index_previous_revision",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ("manifest_artifact_id", "manifest_artifact_revision_id"),
            ("artifact_revisions.logical_artifact_id", "artifact_revisions.revision_id"),
            name="fk_embedding_index_manifest_revision",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("index_id", "revision_number", name="uq_embedding_index_revision_number"),
        UniqueConstraint(
            "index_id", "index_revision_id", name="uq_embedding_index_revision_identity"
        ),
        UniqueConstraint("operation_key", name="uq_embedding_index_registration"),
        UniqueConstraint(
            "manifest_artifact_id",
            "manifest_artifact_revision_id",
            "manifest_member_path",
            name="uq_embedding_index_manifest",
        ),
        Index(
            "ix_embedding_index_revision_graph",
            "graph_snapshot_revision_id",
            "index_id",
            "revision_number",
        ),
    )

    index_revision_id: Mapped[str] = mapped_column(String(50), primary_key=True)
    index_id: Mapped[str] = mapped_column(
        ForeignKey("embedding_indexes.index_id", ondelete="RESTRICT"), nullable=False
    )
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    previous_index_revision_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    graph_snapshot_revision_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_graph_snapshots.graph_snapshot_revision_id", ondelete="RESTRICT"),
        nullable=False,
    )
    policy_revision_id: Mapped[str] = mapped_column(
        ForeignKey(
            "education_retrieval_access_policy_revisions.access_policy_revision_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    policy_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    manifest_artifact_id: Mapped[str] = mapped_column(String(41), nullable=False)
    manifest_artifact_revision_id: Mapped[str] = mapped_column(String(36), nullable=False)
    manifest_member_path: Mapped[str] = mapped_column(String(512), nullable=False)
    manifest_schema_ref: Mapped[str] = mapped_column(String(256), nullable=False)
    manifest_media_type: Mapped[str] = mapped_column(String(128), nullable=False)
    manifest_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    index_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    source_set_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    binding_set_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    eligible_source_count: Mapped[int] = mapped_column(BigInteger, nullable=False)
    binding_count: Mapped[int] = mapped_column(BigInteger, nullable=False)
    operation_key: Mapped[str] = mapped_column(String(128), nullable=False)
    registration_request_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
