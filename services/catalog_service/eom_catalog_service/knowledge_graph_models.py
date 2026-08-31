"""Persistence records for immutable Education Knowledge Graph snapshots."""

from __future__ import annotations

from datetime import datetime

from eom_orchestrator.models import Base
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column


class KnowledgeCorpusRecord(Base):
    __tablename__ = "knowledge_corpora"
    __table_args__ = (
        CheckConstraint(
            "lifecycle_state IN ('ACTIVE','RETIRED')", name="ck_knowledge_corpus_state"
        ),
        CheckConstraint("lock_version >= 1", name="ck_knowledge_corpus_lock_version"),
    )

    corpus_id: Mapped[str] = mapped_column(String(39), primary_key=True)
    corpus_key: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    graph_id: Mapped[str] = mapped_column(String(38), nullable=False, unique=True)
    current_corpus_revision_id: Mapped[str | None] = mapped_column(
        ForeignKey(
            "knowledge_corpus_revisions.corpus_revision_id",
            name="fk_knowledge_corpus_current_revision",
            ondelete="RESTRICT",
            use_alter=True,
        ),
        nullable=True,
    )
    current_graph_snapshot_revision_id: Mapped[str | None] = mapped_column(
        ForeignKey(
            "knowledge_graph_snapshots.graph_snapshot_revision_id",
            name="fk_knowledge_corpus_current_snapshot",
            ondelete="RESTRICT",
            use_alter=True,
        ),
        nullable=True,
    )
    lifecycle_state: Mapped[str] = mapped_column(String(16), nullable=False, default="ACTIVE")
    lock_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_by_operator_id: Mapped[str] = mapped_column(
        ForeignKey("operators.operator_id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class KnowledgeCorpusRevisionRecord(Base):
    __tablename__ = "knowledge_corpus_revisions"
    __table_args__ = (
        CheckConstraint("revision_number >= 1", name="ck_knowledge_corpus_revision_number"),
        CheckConstraint("state = 'PUBLISHED'", name="ck_knowledge_corpus_revision_state"),
        CheckConstraint(
            "source_set_sha256 ~ '^sha256:[0-9a-f]{64}$'",
            name="ck_knowledge_corpus_revision_hash",
        ),
        UniqueConstraint("corpus_id", "revision_number", name="uq_knowledge_corpus_revision"),
    )

    corpus_revision_id: Mapped[str] = mapped_column(String(42), primary_key=True)
    corpus_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_corpora.corpus_id", ondelete="RESTRICT"), nullable=False, index=True
    )
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    previous_corpus_revision_id: Mapped[str | None] = mapped_column(
        ForeignKey("knowledge_corpus_revisions.corpus_revision_id", ondelete="RESTRICT"),
        nullable=True,
    )
    source_set_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    created_by_operator_id: Mapped[str] = mapped_column(
        ForeignKey("operators.operator_id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class KnowledgeGraphSnapshotRecord(Base):
    __tablename__ = "knowledge_graph_snapshots"
    __table_args__ = (
        CheckConstraint("revision_number >= 1", name="ck_knowledge_graph_revision_number"),
        CheckConstraint("state = 'PUBLISHED'", name="ck_knowledge_graph_snapshot_state"),
        CheckConstraint(
            "snapshot_sha256 ~ '^sha256:[0-9a-f]{64}$' "
            "AND manifest_sha256 ~ '^sha256:[0-9a-f]{64}$'",
            name="ck_knowledge_graph_snapshot_hashes",
        ),
        CheckConstraint(
            "source_count >= 1 AND node_count >= 1 AND edge_count >= 0 AND anchor_count >= 1",
            name="ck_knowledge_graph_snapshot_counts",
        ),
        UniqueConstraint("graph_id", "revision_number", name="uq_knowledge_graph_revision"),
        UniqueConstraint("corpus_revision_id", name="uq_knowledge_graph_corpus_revision"),
        Index("ix_knowledge_graph_snapshot_created", text("created_at DESC")),
    )

    graph_snapshot_revision_id: Mapped[str] = mapped_column(String(41), primary_key=True)
    graph_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_corpora.graph_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    corpus_revision_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_corpus_revisions.corpus_revision_id", ondelete="RESTRICT"),
        nullable=False,
    )
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    previous_graph_snapshot_revision_id: Mapped[str | None] = mapped_column(
        ForeignKey("knowledge_graph_snapshots.graph_snapshot_revision_id", ondelete="RESTRICT"),
        nullable=True,
    )
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    ontology_version: Mapped[str] = mapped_column(String(64), nullable=False)
    publisher_version: Mapped[str] = mapped_column(String(32), nullable=False)
    manifest_artifact_id: Mapped[str] = mapped_column(
        ForeignKey("artifacts.logical_artifact_id", ondelete="RESTRICT"), nullable=False
    )
    manifest_artifact_revision_id: Mapped[str] = mapped_column(
        ForeignKey("artifact_revisions.revision_id", ondelete="RESTRICT"), nullable=False
    )
    projection_artifact_id: Mapped[str] = mapped_column(
        ForeignKey("artifacts.logical_artifact_id", ondelete="RESTRICT"), nullable=False
    )
    projection_artifact_revision_id: Mapped[str] = mapped_column(
        ForeignKey("artifact_revisions.revision_id", ondelete="RESTRICT"), nullable=False
    )
    manifest_sha256: Mapped[str] = mapped_column(String(71), nullable=False, unique=True)
    snapshot_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    source_count: Mapped[int] = mapped_column(Integer, nullable=False)
    node_count: Mapped[int] = mapped_column(Integer, nullable=False)
    edge_count: Mapped[int] = mapped_column(Integer, nullable=False)
    anchor_count: Mapped[int] = mapped_column(Integer, nullable=False)
    created_by_operator_id: Mapped[str] = mapped_column(
        ForeignKey("operators.operator_id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class KnowledgeGraphPublicationRecord(Base):
    __tablename__ = "knowledge_graph_publications"
    __table_args__ = (
        CheckConstraint(
            "request_sha256 ~ '^sha256:[0-9a-f]{64}$'",
            name="ck_knowledge_graph_publication_hash",
        ),
        UniqueConstraint("idempotency_key", name="uq_knowledge_graph_publication_idempotency"),
        UniqueConstraint(
            "graph_snapshot_revision_id", name="uq_knowledge_graph_publication_snapshot"
        ),
    )

    publication_id: Mapped[str] = mapped_column(String(41), primary_key=True)
    corpus_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_corpora.corpus_id", ondelete="RESTRICT"), nullable=False, index=True
    )
    graph_snapshot_revision_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_graph_snapshots.graph_snapshot_revision_id", ondelete="RESTRICT"),
        nullable=False,
    )
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    published_by_operator_id: Mapped[str] = mapped_column(
        ForeignKey("operators.operator_id", ondelete="RESTRICT"), nullable=False
    )
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class KnowledgeSnapshotAnalysisRecord(Base):
    __tablename__ = "knowledge_snapshot_analyses"
    __table_args__ = (
        CheckConstraint(
            "accepted_result_sha256 ~ '^sha256:[0-9a-f]{64}$' "
            "AND source_sha256 ~ '^sha256:[0-9a-f]{64}$'",
            name="ck_knowledge_snapshot_analysis_hashes",
        ),
        CheckConstraint(
            "source_kind IN ('CONTENT_INTAKE_FILE','APPROVED_ITEM_REVISION','DOCUMENT_REVISION')",
            name="ck_knowledge_snapshot_analysis_source_kind",
        ),
        UniqueConstraint(
            "graph_snapshot_revision_id",
            "analysis_run_id",
            name="uq_knowledge_snapshot_analysis",
        ),
        Index(
            "ix_knowledge_snapshot_source_revision",
            "source_kind",
            "source_revision_id",
        ),
    )

    snapshot_analysis_id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True
    )
    graph_snapshot_revision_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_graph_snapshots.graph_snapshot_revision_id", ondelete="CASCADE"),
        nullable=False,
    )
    analysis_run_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_analysis_runs.analysis_run_id", ondelete="RESTRICT"), nullable=False
    )
    source_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    source_revision_id: Mapped[str] = mapped_column(String(50), nullable=False)
    source_artifact_revision_id: Mapped[str] = mapped_column(
        ForeignKey("artifact_revisions.revision_id", ondelete="RESTRICT"), nullable=False
    )
    source_artifact_id: Mapped[str] = mapped_column(
        ForeignKey("artifacts.logical_artifact_id", ondelete="RESTRICT"), nullable=False
    )
    source_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    accepted_result_artifact_id: Mapped[str] = mapped_column(
        ForeignKey("artifacts.logical_artifact_id", ondelete="RESTRICT"), nullable=False
    )
    accepted_result_artifact_revision_id: Mapped[str] = mapped_column(
        ForeignKey("artifact_revisions.revision_id", ondelete="RESTRICT"), nullable=False
    )
    accepted_result_sha256: Mapped[str] = mapped_column(String(71), nullable=False)


class KnowledgeNodeRecord(Base):
    __tablename__ = "knowledge_nodes"
    __table_args__ = (
        UniqueConstraint(
            "graph_snapshot_revision_id", "stable_key", name="uq_knowledge_node_stable_key"
        ),
        Index(
            "ix_knowledge_node_type",
            "graph_snapshot_revision_id",
            "node_type",
        ),
    )

    graph_snapshot_revision_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_graph_snapshots.graph_snapshot_revision_id", ondelete="CASCADE"),
        primary_key=True,
    )
    node_id: Mapped[str] = mapped_column(String(72), primary_key=True)
    node_type: Mapped[str] = mapped_column(String(48), nullable=False)
    stable_key: Mapped[str] = mapped_column(String(192), nullable=False)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    answer_bearing: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class KnowledgeNodeTermRecord(Base):
    """Immutable snapshot-local lexical lookup cache derived from node labels and stable keys."""

    __tablename__ = "knowledge_node_terms"
    __table_args__ = (
        ForeignKeyConstraint(
            ["graph_snapshot_revision_id", "node_id"],
            ["knowledge_nodes.graph_snapshot_revision_id", "knowledge_nodes.node_id"],
            ondelete="CASCADE",
        ),
        Index(
            "ix_knowledge_node_term_lookup",
            "graph_snapshot_revision_id",
            "term",
            "node_id",
        ),
        Index(
            "ix_knowledge_node_term_reverse",
            "graph_snapshot_revision_id",
            "node_id",
            "term",
        ),
    )

    graph_snapshot_revision_id: Mapped[str] = mapped_column(String(41), primary_key=True)
    term: Mapped[str] = mapped_column(String(128), primary_key=True)
    node_id: Mapped[str] = mapped_column(String(72), primary_key=True)


class EducationRetrievalAccessPolicyRevisionRecord(Base):
    __tablename__ = "education_retrieval_access_policy_revisions"
    __table_args__ = (
        CheckConstraint("state = 'RELEASED'", name="ck_education_retrieval_policy_state"),
        CheckConstraint(
            "content_sha256 ~ '^sha256:[0-9a-f]{64}$'",
            name="ck_education_retrieval_policy_hash",
        ),
    )

    access_policy_revision_id: Mapped[str] = mapped_column(String(42), primary_key=True)
    schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(71), nullable=False, unique=True)
    canonical_document: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    created_by: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class EducationRetrievalRequestRecord(Base):
    __tablename__ = "education_retrieval_requests"
    __table_args__ = (
        CheckConstraint("state = 'PUBLISHED'", name="ck_education_retrieval_request_state"),
        CheckConstraint(
            "submission_sha256 ~ '^sha256:[0-9a-f]{64}$' "
            "AND request_sha256 ~ '^sha256:[0-9a-f]{64}$' "
            "AND requester_permissions_sha256 ~ '^sha256:[0-9a-f]{64}$'",
            name="ck_education_retrieval_request_hashes",
        ),
        CheckConstraint(
            "query_kind IN ('CURRICULUM_COMPONENTS','APPROVED_ITEM_STRUCTURE','ITEM_PREPARATION')",
            name="ck_education_retrieval_query_kind",
        ),
        CheckConstraint(
            "requester_role IN ('ADMIN','EDITOR','REVIEWER','WORKER')",
            name="ck_education_retrieval_requester_role",
        ),
        Index(
            "ix_education_retrieval_snapshot_created",
            "graph_snapshot_revision_id",
            text("requested_at DESC"),
        ),
    )

    retrieval_request_id: Mapped[str] = mapped_column(String(42), primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    submission_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    request_sha256: Mapped[str] = mapped_column(String(71), nullable=False, unique=True)
    canonical_request: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    graph_snapshot_revision_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_graph_snapshots.graph_snapshot_revision_id", ondelete="RESTRICT"),
        nullable=False,
    )
    access_policy_revision_id: Mapped[str] = mapped_column(
        ForeignKey(
            "education_retrieval_access_policy_revisions.access_policy_revision_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    query_kind: Mapped[str] = mapped_column(String(40), nullable=False)
    requester_role: Mapped[str] = mapped_column(String(16), nullable=False)
    requester_operator_id: Mapped[str] = mapped_column(
        ForeignKey("operators.operator_id", ondelete="RESTRICT"), nullable=False
    )
    requester_permissions_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class EvidenceBundleRecord(Base):
    __tablename__ = "evidence_bundles"

    evidence_bundle_id: Mapped[str] = mapped_column(String(41), primary_key=True)
    retrieval_request_id: Mapped[str] = mapped_column(
        ForeignKey("education_retrieval_requests.retrieval_request_id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    )
    current_revision_id: Mapped[str | None] = mapped_column(
        ForeignKey(
            "evidence_bundle_revisions.evidence_bundle_revision_id",
            name="fk_evidence_bundle_current_revision",
            ondelete="RESTRICT",
            use_alter=True,
        ),
        nullable=True,
    )
    created_by_operator_id: Mapped[str] = mapped_column(
        ForeignKey("operators.operator_id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class EvidenceBundleRevisionRecord(Base):
    __tablename__ = "evidence_bundle_revisions"
    __table_args__ = (
        CheckConstraint("revision_number >= 1", name="ck_evidence_bundle_revision_number"),
        CheckConstraint("state = 'PUBLISHED'", name="ck_evidence_bundle_revision_state"),
        CheckConstraint(
            "context_sha256 ~ '^sha256:[0-9a-f]{64}$' "
            "AND manifest_sha256 ~ '^sha256:[0-9a-f]{64}$' "
            "AND requester_permissions_sha256 ~ '^sha256:[0-9a-f]{64}$'",
            name="ck_evidence_bundle_revision_hashes",
        ),
        CheckConstraint(
            "document_count >= 0 AND item_revision_count >= 0 "
            "AND graph_node_count >= 1 AND claim_count >= 0 "
            "AND estimated_context_tokens >= 1",
            name="ck_evidence_bundle_revision_counts",
        ),
        UniqueConstraint(
            "evidence_bundle_id", "revision_number", name="uq_evidence_bundle_revision"
        ),
        UniqueConstraint("retrieval_request_id", name="uq_evidence_bundle_request"),
        Index("ix_evidence_bundle_snapshot", "graph_snapshot_revision_id", "created_at"),
    )

    evidence_bundle_revision_id: Mapped[str] = mapped_column(String(44), primary_key=True)
    evidence_bundle_id: Mapped[str] = mapped_column(
        ForeignKey("evidence_bundles.evidence_bundle_id", ondelete="RESTRICT"), nullable=False
    )
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    retrieval_request_id: Mapped[str] = mapped_column(
        ForeignKey("education_retrieval_requests.retrieval_request_id", ondelete="RESTRICT"),
        nullable=False,
    )
    graph_snapshot_revision_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_graph_snapshots.graph_snapshot_revision_id", ondelete="RESTRICT"),
        nullable=False,
    )
    access_policy_revision_id: Mapped[str] = mapped_column(
        ForeignKey(
            "education_retrieval_access_policy_revisions.access_policy_revision_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    requester_permissions_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    context_artifact_id: Mapped[str] = mapped_column(
        ForeignKey("artifacts.logical_artifact_id", ondelete="RESTRICT"), nullable=False
    )
    context_artifact_revision_id: Mapped[str] = mapped_column(
        ForeignKey("artifact_revisions.revision_id", ondelete="RESTRICT"), nullable=False
    )
    context_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    manifest_artifact_id: Mapped[str] = mapped_column(
        ForeignKey("artifacts.logical_artifact_id", ondelete="RESTRICT"), nullable=False
    )
    manifest_artifact_revision_id: Mapped[str] = mapped_column(
        ForeignKey("artifact_revisions.revision_id", ondelete="RESTRICT"), nullable=False
    )
    manifest_sha256: Mapped[str] = mapped_column(String(71), nullable=False, unique=True)
    document_count: Mapped[int] = mapped_column(Integer, nullable=False)
    item_revision_count: Mapped[int] = mapped_column(Integer, nullable=False)
    graph_node_count: Mapped[int] = mapped_column(Integer, nullable=False)
    claim_count: Mapped[int] = mapped_column(Integer, nullable=False)
    estimated_context_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    created_by_operator_id: Mapped[str] = mapped_column(
        ForeignKey("operators.operator_id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class EvidenceBundleEntryRecord(Base):
    __tablename__ = "evidence_bundle_entries"
    __table_args__ = (
        CheckConstraint(
            "evidence_kind IN ('DOCUMENT','ITEM_REVISION','CLAIM','TABLE','FIGURE','EQUATION')",
            name="ck_evidence_bundle_entry_kind",
        ),
        CheckConstraint(
            "evidence_use IN ('GROUNDING','REFERENCE_PATTERN','AVOID_COPY')",
            name="ck_evidence_bundle_entry_use",
        ),
        CheckConstraint(
            "source_kind IN ('CONTENT_INTAKE_FILE','APPROVED_ITEM_REVISION','DOCUMENT_REVISION')",
            name="ck_evidence_bundle_entry_source_kind",
        ),
        CheckConstraint(
            "relevance_milli >= 0 AND relevance_milli <= 1000",
            name="ck_evidence_bundle_entry_relevance",
        ),
        CheckConstraint(
            "source_sha256 ~ '^sha256:[0-9a-f]{64}$' AND source_bytes >= 1",
            name="ck_evidence_bundle_entry_source_metadata",
        ),
        CheckConstraint(
            "(source_kind = 'CONTENT_INTAKE_FILE' AND intake_batch_id IS NOT NULL "
            "AND source_file_id IS NOT NULL AND item_id IS NULL AND item_revision_id IS NULL "
            "AND educational_document_id IS NULL AND educational_document_revision_id IS NULL) "
            "OR (source_kind = 'APPROVED_ITEM_REVISION' AND intake_batch_id IS NULL "
            "AND source_file_id IS NULL AND item_id IS NOT NULL AND item_revision_id IS NOT NULL "
            "AND educational_document_id IS NULL AND educational_document_revision_id IS NULL) "
            "OR (source_kind = 'DOCUMENT_REVISION' AND intake_batch_id IS NULL "
            "AND source_file_id IS NULL AND item_id IS NULL AND item_revision_id IS NULL "
            "AND educational_document_id IS NOT NULL "
            "AND educational_document_revision_id IS NOT NULL)",
            name="ck_evidence_bundle_entry_source_family",
        ),
        ForeignKeyConstraint(
            ("educational_document_id", "educational_document_revision_id"),
            (
                "educational_document_revisions.document_id",
                "educational_document_revisions.document_revision_id",
            ),
            name="fk_evidence_entry_educational_document_revision_identity",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "cardinality(graph_node_ids) >= 1 AND cardinality(graph_node_ids) <= 16 "
            "AND cardinality(anchor_ids) >= 1 AND cardinality(anchor_ids) <= 32",
            name="ck_evidence_bundle_entry_pointer_counts",
        ),
        UniqueConstraint(
            "evidence_bundle_revision_id",
            "source_artifact_revision_id",
            "source_member_path",
            "evidence_use",
            name="uq_evidence_bundle_entry_source_use",
        ),
        Index(
            "ix_evidence_bundle_entry_source",
            "source_kind",
            "source_artifact_revision_id",
        ),
        Index(
            "ix_evidence_bundle_entry_document_revision",
            "educational_document_revision_id",
            postgresql_where=text("educational_document_revision_id IS NOT NULL"),
        ),
        Index("ix_evidence_bundle_entry_nodes", "graph_node_ids", postgresql_using="gin"),
        Index("ix_evidence_bundle_entry_anchors", "anchor_ids", postgresql_using="gin"),
    )

    evidence_bundle_revision_id: Mapped[str] = mapped_column(
        ForeignKey("evidence_bundle_revisions.evidence_bundle_revision_id", ondelete="CASCADE"),
        primary_key=True,
    )
    evidence_id: Mapped[str] = mapped_column(String(45), primary_key=True)
    evidence_kind: Mapped[str] = mapped_column(String(24), nullable=False)
    evidence_use: Mapped[str] = mapped_column(String(24), nullable=False)
    source_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    source_class: Mapped[str] = mapped_column(String(32), nullable=False)
    intake_batch_id: Mapped[str | None] = mapped_column(String(39), nullable=True)
    source_file_id: Mapped[str | None] = mapped_column(String(43), nullable=True)
    item_id: Mapped[str | None] = mapped_column(String(37), nullable=True)
    item_revision_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    educational_document_id: Mapped[str | None] = mapped_column(
        ForeignKey("educational_documents.document_id", ondelete="RESTRICT"), nullable=True
    )
    educational_document_revision_id: Mapped[str | None] = mapped_column(String(42), nullable=True)
    source_artifact_id: Mapped[str] = mapped_column(
        ForeignKey("artifacts.logical_artifact_id", ondelete="RESTRICT"), nullable=False
    )
    source_artifact_revision_id: Mapped[str] = mapped_column(
        ForeignKey("artifact_revisions.revision_id", ondelete="RESTRICT"), nullable=False
    )
    source_member_path: Mapped[str] = mapped_column(Text, nullable=False)
    source_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    source_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    source_schema_ref: Mapped[str | None] = mapped_column(String(256), nullable=True)
    source_media_type: Mapped[str] = mapped_column(String(128), nullable=False)
    source_logical_name: Mapped[str] = mapped_column(String(256), nullable=False)
    graph_node_ids: Mapped[list[str]] = mapped_column(ARRAY(String(72)), nullable=False)
    anchor_ids: Mapped[list[str]] = mapped_column(ARRAY(String(71)), nullable=False)
    relevance_milli: Mapped[int] = mapped_column(Integer, nullable=False)
    answer_bearing: Mapped[bool] = mapped_column(Boolean, nullable=False)


class KnowledgeEdgeRecord(Base):
    __tablename__ = "knowledge_edges"
    __table_args__ = (
        ForeignKeyConstraint(
            ["graph_snapshot_revision_id", "from_node_id"],
            ["knowledge_nodes.graph_snapshot_revision_id", "knowledge_nodes.node_id"],
            name="fk_knowledge_edge_from_node",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["graph_snapshot_revision_id", "to_node_id"],
            ["knowledge_nodes.graph_snapshot_revision_id", "knowledge_nodes.node_id"],
            name="fk_knowledge_edge_to_node",
            ondelete="CASCADE",
        ),
        CheckConstraint("from_node_id <> to_node_id", name="ck_knowledge_edge_not_self"),
        CheckConstraint(
            "confidence_milli >= 0 AND confidence_milli <= 1000",
            name="ck_knowledge_edge_confidence",
        ),
        Index(
            "ix_knowledge_edge_outbound",
            "graph_snapshot_revision_id",
            "from_node_id",
            "edge_type",
        ),
        Index(
            "ix_knowledge_edge_inbound",
            "graph_snapshot_revision_id",
            "to_node_id",
            "edge_type",
        ),
    )

    graph_snapshot_revision_id: Mapped[str] = mapped_column(String(41), primary_key=True)
    edge_id: Mapped[str] = mapped_column(String(72), primary_key=True)
    edge_type: Mapped[str] = mapped_column(String(48), nullable=False)
    from_node_id: Mapped[str] = mapped_column(String(72), nullable=False)
    to_node_id: Mapped[str] = mapped_column(String(72), nullable=False)
    confidence_milli: Mapped[int] = mapped_column(Integer, nullable=False)
    answer_bearing: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class KnowledgeNodeSourcePointerRecord(Base):
    __tablename__ = "knowledge_node_source_pointers"
    __table_args__ = (
        ForeignKeyConstraint(
            ["graph_snapshot_revision_id", "node_id"],
            ["knowledge_nodes.graph_snapshot_revision_id", "knowledge_nodes.node_id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["graph_snapshot_revision_id", "analysis_run_id"],
            [
                "knowledge_snapshot_analyses.graph_snapshot_revision_id",
                "knowledge_snapshot_analyses.analysis_run_id",
            ],
            name="fk_knowledge_node_source_analysis",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "excerpt_sha256 ~ '^sha256:[0-9a-f]{64}$' AND source_sha256 ~ '^sha256:[0-9a-f]{64}$'",
            name="ck_knowledge_node_source_hash",
        ),
        UniqueConstraint(
            "graph_snapshot_revision_id",
            "node_id",
            "analysis_run_id",
            "source_revision_id",
            "artifact_revision_id",
            "member_path",
            "anchor_id",
            name="uq_knowledge_node_source_pointer",
        ),
        Index(
            "ix_knowledge_node_source_artifact",
            "artifact_revision_id",
            "source_revision_id",
        ),
        Index(
            "ix_knowledge_node_source_class",
            "graph_snapshot_revision_id",
            "source_class",
            "source_revision_id",
        ),
    )

    pointer_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    graph_snapshot_revision_id: Mapped[str] = mapped_column(String(41), nullable=False)
    node_id: Mapped[str] = mapped_column(String(72), nullable=False)
    analysis_run_id: Mapped[str] = mapped_column(String(44), nullable=False)
    source_revision_id: Mapped[str] = mapped_column(String(50), nullable=False)
    source_class: Mapped[str] = mapped_column(String(32), nullable=False)
    source_artifact_id: Mapped[str] = mapped_column(
        ForeignKey("artifacts.logical_artifact_id", ondelete="RESTRICT"), nullable=False
    )
    artifact_revision_id: Mapped[str] = mapped_column(
        ForeignKey("artifact_revisions.revision_id", ondelete="RESTRICT"), nullable=False
    )
    source_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    member_path: Mapped[str] = mapped_column(Text, nullable=False)
    anchor_id: Mapped[str] = mapped_column(String(71), nullable=False)
    excerpt_sha256: Mapped[str] = mapped_column(String(71), nullable=False)


class KnowledgeEdgeSourcePointerRecord(Base):
    __tablename__ = "knowledge_edge_source_pointers"
    __table_args__ = (
        ForeignKeyConstraint(
            ["graph_snapshot_revision_id", "edge_id"],
            ["knowledge_edges.graph_snapshot_revision_id", "knowledge_edges.edge_id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["graph_snapshot_revision_id", "analysis_run_id"],
            [
                "knowledge_snapshot_analyses.graph_snapshot_revision_id",
                "knowledge_snapshot_analyses.analysis_run_id",
            ],
            name="fk_knowledge_edge_source_analysis",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "excerpt_sha256 ~ '^sha256:[0-9a-f]{64}$' AND source_sha256 ~ '^sha256:[0-9a-f]{64}$'",
            name="ck_knowledge_edge_source_hash",
        ),
        UniqueConstraint(
            "graph_snapshot_revision_id",
            "edge_id",
            "analysis_run_id",
            "source_revision_id",
            "artifact_revision_id",
            "member_path",
            "anchor_id",
            name="uq_knowledge_edge_source_pointer",
        ),
        Index(
            "ix_knowledge_edge_source_artifact",
            "artifact_revision_id",
            "source_revision_id",
        ),
        Index(
            "ix_knowledge_edge_source_class",
            "graph_snapshot_revision_id",
            "source_class",
            "source_revision_id",
        ),
    )

    pointer_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    graph_snapshot_revision_id: Mapped[str] = mapped_column(String(41), nullable=False)
    edge_id: Mapped[str] = mapped_column(String(72), nullable=False)
    analysis_run_id: Mapped[str] = mapped_column(String(44), nullable=False)
    source_revision_id: Mapped[str] = mapped_column(String(50), nullable=False)
    source_class: Mapped[str] = mapped_column(String(32), nullable=False)
    source_artifact_id: Mapped[str] = mapped_column(
        ForeignKey("artifacts.logical_artifact_id", ondelete="RESTRICT"), nullable=False
    )
    artifact_revision_id: Mapped[str] = mapped_column(
        ForeignKey("artifact_revisions.revision_id", ondelete="RESTRICT"), nullable=False
    )
    source_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    member_path: Mapped[str] = mapped_column(Text, nullable=False)
    anchor_id: Mapped[str] = mapped_column(String(71), nullable=False)
    excerpt_sha256: Mapped[str] = mapped_column(String(71), nullable=False)


class CurriculumUnitRecord(Base):
    __tablename__ = "curriculum_units"
    __table_args__ = (
        ForeignKeyConstraint(
            ["graph_snapshot_revision_id", "node_id"],
            ["knowledge_nodes.graph_snapshot_revision_id", "knowledge_nodes.node_id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["graph_snapshot_revision_id", "parent_unit_id"],
            ["curriculum_units.graph_snapshot_revision_id", "curriculum_units.curriculum_unit_id"],
            name="fk_curriculum_unit_parent",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "unit_level IN ('MAJOR','MIDDLE','MINOR','ACHIEVEMENT_STANDARD')",
            name="ck_curriculum_unit_level",
        ),
        CheckConstraint("ordinal >= 1", name="ck_curriculum_unit_ordinal"),
        UniqueConstraint("graph_snapshot_revision_id", "node_id", name="uq_curriculum_unit_node"),
        Index(
            "uq_curriculum_root_ordinal",
            "graph_snapshot_revision_id",
            "framework_revision_id",
            "ordinal",
            unique=True,
            postgresql_where=text("parent_unit_id IS NULL"),
        ),
        Index(
            "uq_curriculum_child_ordinal",
            "graph_snapshot_revision_id",
            "framework_revision_id",
            "parent_unit_id",
            "ordinal",
            unique=True,
            postgresql_where=text("parent_unit_id IS NOT NULL"),
        ),
        Index(
            "ix_curriculum_unit_framework_level",
            "graph_snapshot_revision_id",
            "framework_revision_id",
            "unit_level",
        ),
    )

    graph_snapshot_revision_id: Mapped[str] = mapped_column(String(41), primary_key=True)
    curriculum_unit_id: Mapped[str] = mapped_column(String(41), primary_key=True)
    node_id: Mapped[str] = mapped_column(String(72), nullable=False)
    framework_revision_id: Mapped[str] = mapped_column(String(46), nullable=False)
    parent_unit_id: Mapped[str | None] = mapped_column(String(41), nullable=True)
    unit_level: Mapped[str] = mapped_column(String(32), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)


class CurriculumUnitClosureRecord(Base):
    __tablename__ = "curriculum_unit_closure"
    __table_args__ = (
        ForeignKeyConstraint(
            ["graph_snapshot_revision_id", "ancestor_unit_id"],
            ["curriculum_units.graph_snapshot_revision_id", "curriculum_units.curriculum_unit_id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["graph_snapshot_revision_id", "descendant_unit_id"],
            ["curriculum_units.graph_snapshot_revision_id", "curriculum_units.curriculum_unit_id"],
            ondelete="CASCADE",
        ),
        CheckConstraint("depth >= 0", name="ck_curriculum_closure_depth"),
        Index(
            "ix_curriculum_closure_descendants",
            "graph_snapshot_revision_id",
            "framework_revision_id",
            "ancestor_unit_id",
            "depth",
        ),
        Index(
            "ix_curriculum_closure_ancestors",
            "graph_snapshot_revision_id",
            "framework_revision_id",
            "descendant_unit_id",
            "depth",
        ),
    )

    graph_snapshot_revision_id: Mapped[str] = mapped_column(String(41), primary_key=True)
    framework_revision_id: Mapped[str] = mapped_column(String(46), primary_key=True)
    ancestor_unit_id: Mapped[str] = mapped_column(String(41), primary_key=True)
    descendant_unit_id: Mapped[str] = mapped_column(String(41), primary_key=True)
    depth: Mapped[int] = mapped_column(Integer, nullable=False)


class ItemElementReferenceRecord(Base):
    __tablename__ = "item_element_refs"
    __table_args__ = (
        ForeignKeyConstraint(
            ["graph_snapshot_revision_id", "node_id"],
            ["knowledge_nodes.graph_snapshot_revision_id", "knowledge_nodes.node_id"],
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "element_kind IN ('paragraph','table','image','equation',"
            "'statement_set','statement','choice')",
            name="ck_item_element_kind",
        ),
        CheckConstraint(
            "item_content_sha256 ~ '^sha256:[0-9a-f]{64}$'",
            name="ck_item_element_content_hash",
        ),
        UniqueConstraint("graph_snapshot_revision_id", "node_id", name="uq_item_element_node"),
        Index(
            "ix_item_element_revision_kind",
            "graph_snapshot_revision_id",
            "item_revision_id",
            "element_kind",
        ),
        Index(
            "ix_item_element_reverse",
            "item_revision_id",
            "element_kind",
            "graph_snapshot_revision_id",
        ),
    )

    graph_snapshot_revision_id: Mapped[str] = mapped_column(String(41), primary_key=True)
    item_revision_id: Mapped[str] = mapped_column(
        ForeignKey("item_revisions.item_revision_id", ondelete="RESTRICT"), primary_key=True
    )
    element_kind: Mapped[str] = mapped_column(String(24), primary_key=True)
    element_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    node_id: Mapped[str] = mapped_column(String(72), nullable=False)
    item_id: Mapped[str] = mapped_column(
        ForeignKey("items.item_id", ondelete="RESTRICT"), nullable=False
    )
    item_content_artifact_revision_id: Mapped[str] = mapped_column(
        ForeignKey("artifact_revisions.revision_id", ondelete="RESTRICT"), nullable=False
    )
    item_content_artifact_id: Mapped[str] = mapped_column(
        ForeignKey("artifacts.logical_artifact_id", ondelete="RESTRICT"), nullable=False
    )
    item_content_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    schema_ref: Mapped[str] = mapped_column(String(256), nullable=False)
    answer_bearing: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
