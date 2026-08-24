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
            "source_kind IN ('CONTENT_INTAKE_FILE','APPROVED_ITEM_REVISION')",
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
        CheckConstraint(
            "excerpt_sha256 ~ '^sha256:[0-9a-f]{64}$' AND source_sha256 ~ '^sha256:[0-9a-f]{64}$'",
            name="ck_knowledge_node_source_hash",
        ),
        UniqueConstraint(
            "graph_snapshot_revision_id",
            "node_id",
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
        CheckConstraint(
            "excerpt_sha256 ~ '^sha256:[0-9a-f]{64}$' AND source_sha256 ~ '^sha256:[0-9a-f]{64}$'",
            name="ck_knowledge_edge_source_hash",
        ),
        UniqueConstraint(
            "graph_snapshot_revision_id",
            "edge_id",
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
