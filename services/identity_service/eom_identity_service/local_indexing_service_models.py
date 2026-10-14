"""Identity-owned small service metadata; no operator, credential or source grant."""

from __future__ import annotations

from datetime import datetime

from eom_orchestrator.models import Base
from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column


class LocalIndexingServiceRecord(Base):
    __tablename__ = "local_indexing_services"
    __table_args__ = (
        CheckConstraint("service_id ~ '^localindexservice_[0-9a-f]{32}$'", name="ck_lis_id"),
        CheckConstraint(
            "state IN ('ACTIVE','DISABLED') AND (state <> 'ACTIVE' OR "
            "current_revision_id IS NOT NULL)",
            name="ck_lis_state",
        ),
        CheckConstraint(
            "resource_version >= 1 AND updated_at >= created_at", name="ck_lis_version"
        ),
        ForeignKeyConstraint(
            ("service_id", "latest_revision_id"),
            (
                "local_indexing_service_revisions.service_id",
                "local_indexing_service_revisions.service_revision_id",
            ),
            name="fk_lis_latest",
            use_alter=True,
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ("service_id", "current_revision_id"),
            (
                "local_indexing_service_revisions.service_id",
                "local_indexing_service_revisions.service_revision_id",
            ),
            name="fk_lis_current",
            use_alter=True,
            deferrable=True,
            initially="DEFERRED",
        ),
    )

    service_id: Mapped[str] = mapped_column(String(50), primary_key=True)
    latest_revision_id: Mapped[str] = mapped_column(String(53), nullable=False)
    current_revision_id: Mapped[str | None] = mapped_column(String(53), nullable=True)
    state: Mapped[str] = mapped_column(String(8), nullable=False)
    resource_version: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class LocalIndexingServiceRevisionRecord(Base):
    __tablename__ = "local_indexing_service_revisions"
    __table_args__ = (
        CheckConstraint(
            "schema_version = 'local-indexing-service-identity/1.0' AND "
            "service_revision_id ~ '^localindexservicerev_[0-9a-f]{32}$' AND "
            "content_sha256 ~ '^sha256:[0-9a-f]{64}$'",
            name="ck_lis_revision_identity",
        ),
        CheckConstraint(
            "(revision_number = 1 AND previous_service_revision_id IS NULL) OR "
            "(revision_number > 1 AND previous_service_revision_id IS NOT NULL AND "
            "previous_service_revision_id <> service_revision_id)",
            name="ck_lis_revision_chain",
        ),
        CheckConstraint(
            "purpose = 'LOCAL_EMBEDDING_INDEX' AND runtime_user = 'eom-workflow-runner' AND "
            "database_role ~ '^[a-z][a-z0-9_]{0,62}$' AND database_role !~ '[[:space:]]' AND "
            "runtime_source_commit ~ '^[0-9a-f]{40}$'",
            name="ck_lis_revision_runtime",
        ),
        UniqueConstraint("service_id", "service_revision_id", name="uq_lis_revision_identity"),
        UniqueConstraint("service_id", "revision_number", name="uq_lis_revision_number"),
        UniqueConstraint("service_id", "previous_service_revision_id", name="uq_lis_successor"),
        ForeignKeyConstraint(
            ("service_id", "previous_service_revision_id"),
            (
                "local_indexing_service_revisions.service_id",
                "local_indexing_service_revisions.service_revision_id",
            ),
            name="fk_lis_predecessor",
            ondelete="RESTRICT",
        ),
    )

    service_revision_id: Mapped[str] = mapped_column(String(53), primary_key=True)
    service_id: Mapped[str] = mapped_column(
        ForeignKey("local_indexing_services.service_id", ondelete="RESTRICT"), nullable=False
    )
    schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    previous_service_revision_id: Mapped[str | None] = mapped_column(String(53), nullable=True)
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    purpose: Mapped[str] = mapped_column(String(32), nullable=False)
    runtime_user: Mapped[str] = mapped_column(String(64), nullable=False)
    database_role: Mapped[str] = mapped_column(String(63), nullable=False)
    runtime_source_commit: Mapped[str] = mapped_column(String(40), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(71), nullable=False)


class LocalIndexingServiceEventRecord(Base):
    __tablename__ = "local_indexing_service_events"
    __table_args__ = (
        UniqueConstraint("operation_key", name="uq_lis_operation_key"),
        CheckConstraint("sequence >= 1", name="ck_lis_event_sequence"),
        CheckConstraint(
            "request_sha256 ~ '^sha256:[0-9a-f]{64}$' AND "
            "event_type IN ('REGISTER','ACTIVATE','DISABLE') AND "
            "state_after IN ('ACTIVE','DISABLED') AND "
            "(previous_state IS NULL OR previous_state IN ('ACTIVE','DISABLED')) AND "
            "(state_after <> 'ACTIVE' OR current_revision_id IS NOT NULL)",
            name="ck_lis_event_shape",
        ),
        CheckConstraint(
            "(event_type = 'REGISTER' AND target_revision_id IS NOT NULL AND "
            "expected_resource_version IS NULL) OR "
            "(event_type = 'ACTIVATE' AND target_revision_id IS NOT NULL AND "
            "expected_resource_version IS NOT NULL AND "
            "expected_resource_version = sequence - 1 AND expected_resource_version >= 1) OR "
            "(event_type = 'DISABLE' AND target_revision_id IS NULL AND "
            "expected_resource_version IS NOT NULL AND "
            "expected_resource_version = sequence - 1 AND expected_resource_version >= 1)",
            name="ck_lis_event_operation",
        ),
        *(
            ForeignKeyConstraint(
                ("service_id", name),
                (
                    "local_indexing_service_revisions.service_id",
                    "local_indexing_service_revisions.service_revision_id",
                ),
                name="fk_lis_event_" + name.removesuffix("_revision_id"),
                ondelete="RESTRICT",
            )
            for name in (
                "target_revision_id",
                "latest_revision_id",
                "current_revision_id",
                "previous_latest_revision_id",
                "previous_current_revision_id",
            )
        ),
    )

    service_id: Mapped[str] = mapped_column(
        ForeignKey("local_indexing_services.service_id", ondelete="RESTRICT"), primary_key=True
    )
    sequence: Mapped[int] = mapped_column(Integer, primary_key=True)
    operation_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    event_type: Mapped[str] = mapped_column(String(8), nullable=False)
    actor_database_principal: Mapped[str] = mapped_column(String(63), nullable=False)
    target_revision_id: Mapped[str | None] = mapped_column(String(53), nullable=True)
    expected_resource_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    previous_state: Mapped[str | None] = mapped_column(String(8), nullable=True)
    previous_latest_revision_id: Mapped[str | None] = mapped_column(String(53), nullable=True)
    previous_current_revision_id: Mapped[str | None] = mapped_column(String(53), nullable=True)
    state_after: Mapped[str] = mapped_column(String(8), nullable=False)
    latest_revision_id: Mapped[str] = mapped_column(String(53), nullable=False)
    current_revision_id: Mapped[str | None] = mapped_column(String(53), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
