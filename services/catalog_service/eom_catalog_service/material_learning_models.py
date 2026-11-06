"""Small Catalog-owned pointers/checkpoints; all document/worker bytes stay in Artifacts."""

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
    text,
)
from sqlalchemy.orm import Mapped, mapped_column


class LearningMaterialRecord(Base):
    __tablename__ = "learning_materials"
    __table_args__ = (
        CheckConstraint(
            "lifecycle_state IN ('ACTIVE','RETIRED')", name="ck_learning_material_lifecycle"
        ),
        ForeignKeyConstraint(
            ("material_id", "current_revision_id"),
            (
                "learning_material_revisions.material_id",
                "learning_material_revisions.material_revision_id",
            ),
            name="fk_learning_material_current_revision",
            use_alter=True,
            ondelete="RESTRICT",
        ),
        Index(
            "ix_learning_material_owner_recent",
            "created_by",
            text("created_at DESC"),
            "material_id",
        ),
    )

    material_id: Mapped[str] = mapped_column(String(41), primary_key=True)
    current_revision_id: Mapped[str | None] = mapped_column(String(44))
    lifecycle_state: Mapped[str] = mapped_column(String(16), nullable=False)
    created_by: Mapped[str] = mapped_column(
        ForeignKey("operators.operator_id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class LearningMaterialRevisionRecord(Base):
    __tablename__ = "learning_material_revisions"
    __table_args__ = (
        UniqueConstraint(
            "material_id", "revision_number", name="uq_learning_material_revision_number"
        ),
        UniqueConstraint(
            "material_id", "material_revision_id", name="uq_learning_material_revision_owner"
        ),
        UniqueConstraint(
            "created_by", "idempotency_key", name="uq_learning_material_revision_replay"
        ),
        CheckConstraint("revision_number > 0", name="ck_learning_material_revision_number"),
        CheckConstraint(
            "material_kind IN ('TEXTBOOK','REFERENCE_BOOK','WORKBOOK','MOCK_EXAM','OTHER')",
            name="ck_learning_material_kind",
        ),
        CheckConstraint(
            "request_sha256 ~ '^sha256:[0-9a-f]{64}$' AND "
            "manifest_sha256 ~ '^sha256:[0-9a-f]{64}$'",
            name="ck_learning_material_revision_hashes",
        ),
        ForeignKeyConstraint(
            ("manifest_artifact_id", "manifest_artifact_revision_id"),
            ("artifact_revisions.logical_artifact_id", "artifact_revisions.revision_id"),
            name="fk_learning_material_revision_manifest",
            ondelete="RESTRICT",
        ),
    )

    material_revision_id: Mapped[str] = mapped_column(String(44), primary_key=True)
    material_id: Mapped[str] = mapped_column(
        ForeignKey("learning_materials.material_id", ondelete="RESTRICT"), nullable=False
    )
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    previous_revision_id: Mapped[str | None] = mapped_column(
        ForeignKey("learning_material_revisions.material_revision_id", ondelete="RESTRICT")
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    material_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    request_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    manifest_artifact_id: Mapped[str] = mapped_column(String(41), nullable=False)
    manifest_artifact_revision_id: Mapped[str] = mapped_column(String(36), nullable=False)
    manifest_member_path: Mapped[str] = mapped_column(String(512), nullable=False)
    manifest_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    created_by: Mapped[str] = mapped_column(
        ForeignKey("operators.operator_id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class MaterialLearningRunRecord(Base):
    __tablename__ = "material_learning_runs"
    __table_args__ = (
        UniqueConstraint(
            "material_revision_id", "attempt", name="uq_material_learning_run_attempt"
        ),
        CheckConstraint(
            "attempt > 0 AND next_event_sequence > 0", name="ck_material_learning_run_counters"
        ),
        CheckConstraint(
            "state IN ('RECEIVED','PREPARING','DISCOVERING','PROCESSING',"
            "'WAITING_FOR_CAPACITY','PAUSED','COMPLETED','COMPLETED_WITH_EXCEPTIONS',"
            "'FAILED','CANCELLED')",
            name="ck_material_learning_run_state",
        ),
        CheckConstraint(
            "(lease_owner IS NULL AND lease_token IS NULL AND lease_expires_at IS NULL) OR "
            "(lease_owner IS NOT NULL AND lease_token IS NOT NULL "
            "AND lease_expires_at IS NOT NULL)",
            name="ck_material_learning_run_lease",
        ),
        CheckConstraint(
            "(prepared_artifact_id IS NULL AND prepared_artifact_revision_id IS NULL "
            "AND prepared_sha256 IS NULL) OR (prepared_artifact_id IS NOT NULL "
            "AND prepared_artifact_revision_id IS NOT NULL AND prepared_sha256 IS NOT NULL "
            "AND prepared_sha256 ~ '^sha256:[0-9a-f]{64}$')",
            name="ck_material_learning_prepared_pointer",
        ),
        ForeignKeyConstraint(
            ("prepared_artifact_id", "prepared_artifact_revision_id"),
            ("artifact_revisions.logical_artifact_id", "artifact_revisions.revision_id"),
            name="fk_material_learning_run_prepared",
            ondelete="RESTRICT",
        ),
        Index(
            "uq_material_learning_live_revision",
            "material_revision_id",
            unique=True,
            postgresql_where=text(
                "state NOT IN ('COMPLETED','COMPLETED_WITH_EXCEPTIONS','FAILED','CANCELLED')"
            ),
        ),
        Index("ix_material_learning_next_run", "state", "lease_expires_at", "created_at", "run_id"),
    )

    run_id: Mapped[str] = mapped_column(String(44), primary_key=True)
    material_revision_id: Mapped[str] = mapped_column(
        ForeignKey("learning_material_revisions.material_revision_id", ondelete="RESTRICT"),
        nullable=False,
    )
    attempt: Mapped[int] = mapped_column(Integer, nullable=False)
    predecessor_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("material_learning_runs.run_id", ondelete="RESTRICT")
    )
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    phase_before_wait: Mapped[str | None] = mapped_column(String(32))
    next_event_sequence: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("1")
    )
    lease_owner: Mapped[str | None] = mapped_column(String(128))
    lease_token: Mapped[str | None] = mapped_column(String(32))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    prepared_artifact_id: Mapped[str | None] = mapped_column(String(41))
    prepared_artifact_revision_id: Mapped[str | None] = mapped_column(String(36))
    prepared_sha256: Mapped[str | None] = mapped_column(String(71))
    error_code: Mapped[str | None] = mapped_column(String(128))
    created_by: Mapped[str] = mapped_column(
        ForeignKey("operators.operator_id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class MaterialLearningTaskRecord(Base):
    __tablename__ = "material_learning_tasks"
    __table_args__ = (
        UniqueConstraint("run_id", "unit_key", "attempt", name="uq_material_learning_task_attempt"),
        UniqueConstraint("run_id", "task_id", name="uq_material_learning_task_owner"),
        UniqueConstraint("run_id", "ordinal", name="uq_material_learning_task_ordinal"),
        CheckConstraint("ordinal > 0 AND attempt > 0", name="ck_material_learning_task_counters"),
        CheckConstraint(
            "task_kind IN ('PREPARE','DISCOVER','EXPLANATION','QUESTION')",
            name="ck_material_learning_task_kind",
        ),
        CheckConstraint(
            "state IN ('PENDING','PREPARING','READY','RUNNING','RESULT_READY','REGISTERED',"
            "'ANALYZING','PUBLISHING','GRAPH_READY','COMPLETED','EXCEPTION','FAILED','CANCELLED')",
            name="ck_material_learning_task_state",
        ),
        CheckConstraint(
            "execution_lane = 'MATERIAL_LEARNING'", name="ck_material_learning_task_lane"
        ),
        CheckConstraint(
            "(input_artifact_id IS NULL AND input_artifact_revision_id IS NULL "
            "AND input_sha256 IS NULL) OR (input_artifact_id IS NOT NULL "
            "AND input_artifact_revision_id IS NOT NULL AND input_sha256 IS NOT NULL "
            "AND input_sha256 ~ '^sha256:[0-9a-f]{64}$')",
            name="ck_material_learning_task_input",
        ),
        CheckConstraint(
            "(output_artifact_id IS NULL AND output_artifact_revision_id IS NULL "
            "AND output_sha256 IS NULL) OR (output_artifact_id IS NOT NULL "
            "AND output_artifact_revision_id IS NOT NULL AND output_sha256 IS NOT NULL "
            "AND output_sha256 ~ '^sha256:[0-9a-f]{64}$')",
            name="ck_material_learning_task_output",
        ),
        ForeignKeyConstraint(
            ("input_artifact_id", "input_artifact_revision_id"),
            ("artifact_revisions.logical_artifact_id", "artifact_revisions.revision_id"),
            name="fk_material_learning_task_input",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ("output_artifact_id", "output_artifact_revision_id"),
            ("artifact_revisions.logical_artifact_id", "artifact_revisions.revision_id"),
            name="fk_material_learning_task_output",
            ondelete="RESTRICT",
        ),
        Index(
            "uq_material_learning_one_ai",
            "execution_lane",
            unique=True,
            postgresql_where=text("state IN ('RUNNING','ANALYZING')"),
        ),
        Index("ix_material_learning_next_task", "run_id", "state", "ordinal", "attempt"),
        Index("ix_material_learning_registered_item", "item_revision_id"),
        Index(
            "uq_material_learning_child_workflow",
            "workflow_id",
            unique=True,
            postgresql_where=text("workflow_id IS NOT NULL"),
        ),
        Index(
            "uq_material_learning_child_analysis",
            "analysis_run_id",
            unique=True,
            postgresql_where=text("analysis_run_id IS NOT NULL"),
        ),
        Index(
            "uq_material_learning_child_solution",
            "solution_analysis_run_id",
            unique=True,
            postgresql_where=text("solution_analysis_run_id IS NOT NULL"),
        ),
    )

    task_id: Mapped[str] = mapped_column(String(45), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("material_learning_runs.run_id", ondelete="RESTRICT"), nullable=False
    )
    task_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    unit_key: Mapped[str] = mapped_column(String(128), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False)
    predecessor_task_id: Mapped[str | None] = mapped_column(
        ForeignKey("material_learning_tasks.task_id", ondelete="RESTRICT")
    )
    state: Mapped[str] = mapped_column(String(24), nullable=False)
    execution_lane: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'MATERIAL_LEARNING'")
    )
    input_artifact_id: Mapped[str | None] = mapped_column(String(41))
    input_artifact_revision_id: Mapped[str | None] = mapped_column(String(36))
    input_sha256: Mapped[str | None] = mapped_column(String(71))
    workflow_id: Mapped[str | None] = mapped_column(
        ForeignKey("workflow_instances.workflow_id", ondelete="RESTRICT")
    )
    output_artifact_id: Mapped[str | None] = mapped_column(String(41))
    output_artifact_revision_id: Mapped[str | None] = mapped_column(String(36))
    output_sha256: Mapped[str | None] = mapped_column(String(71))
    item_revision_id: Mapped[str | None] = mapped_column(
        ForeignKey("item_revisions.item_revision_id", ondelete="RESTRICT")
    )
    analysis_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("knowledge_analysis_runs.analysis_run_id", ondelete="RESTRICT")
    )
    solution_analysis_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("knowledge_analysis_runs.analysis_run_id", ondelete="RESTRICT")
    )
    graph_snapshot_revision_id: Mapped[str | None] = mapped_column(
        ForeignKey("knowledge_graph_snapshots.graph_snapshot_revision_id", ondelete="RESTRICT")
    )
    error_code: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class MaterialLearningEventRecord(Base):
    __tablename__ = "material_learning_events"
    __table_args__ = (
        UniqueConstraint("run_id", "sequence", name="uq_material_learning_event_sequence"),
        CheckConstraint("sequence > 0", name="ck_material_learning_event_sequence"),
        ForeignKeyConstraint(
            ("run_id", "task_id"),
            ("material_learning_tasks.run_id", "material_learning_tasks.task_id"),
            name="fk_material_learning_event_task",
            ondelete="RESTRICT",
        ),
    )

    event_id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("material_learning_runs.run_id", ondelete="RESTRICT"), nullable=False
    )
    task_id: Mapped[str | None] = mapped_column(String(45))
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    prior_state: Mapped[str | None] = mapped_column(String(32))
    new_state: Mapped[str] = mapped_column(String(32), nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
