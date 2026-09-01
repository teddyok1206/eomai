"""SQLAlchemy persistence model for the first platform slice."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

JOB_STATES = (
    "CREATED",
    "VALIDATED",
    "QUEUED",
    "CLAIMED",
    "RUNNING",
    "VALIDATING_RESULT",
    "COMMITTING",
    "SUCCEEDED",
    "FAILED",
    "CANCELLED",
)


class Base(DeclarativeBase):
    pass


class ProtocolVersionRecord(Base):
    __tablename__ = "protocol_versions"

    version: Mapped[str] = mapped_column(String(32), primary_key=True)
    schema_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class WorkerSlotRecord(Base):
    __tablename__ = "worker_slots"

    slot_id: Mapped[str] = mapped_column(String(2), primary_key=True)
    linux_user: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    role: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    gpu: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class JobRecord(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('CREATED','VALIDATED','QUEUED','CLAIMED','RUNNING',"
            "'VALIDATING_RESULT','COMMITTING','SUCCEEDED','FAILED','CANCELLED')",
            name="ck_jobs_status",
        ),
    )

    job_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    protocol_version: Mapped[str] = mapped_column(
        ForeignKey("protocol_versions.version"), nullable=False
    )
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    request_hash: Mapped[str] = mapped_column(String(71), nullable=False)
    task_type: Mapped[str] = mapped_column(String(64), nullable=False)
    request: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    logical_artifact_id: Mapped[str] = mapped_column(String(41), unique=True, nullable=False)
    revision_id: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    worker_slot_id: Mapped[str | None] = mapped_column(
        ForeignKey("worker_slots.slot_id"), nullable=True
    )
    worker_exit_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    worker_stdout_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    worker_stderr_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    events: Mapped[list[JobEventRecord]] = relationship(
        back_populates="job", order_by="JobEventRecord.sequence", cascade="all, delete-orphan"
    )


class JobEventRecord(Base):
    __tablename__ = "job_events"
    __table_args__ = (UniqueConstraint("job_id", "sequence", name="uq_job_events_sequence"),)

    event_id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    job_id: Mapped[str] = mapped_column(
        ForeignKey("jobs.job_id", ondelete="CASCADE"), nullable=False, index=True
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    from_state: Mapped[str | None] = mapped_column(String(32), nullable=True)
    to_state: Mapped[str] = mapped_column(String(32), nullable=False)
    event: Mapped[str] = mapped_column(String(64), nullable=False)
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    job: Mapped[JobRecord] = relationship(back_populates="events")


class ArtifactRecord(Base):
    __tablename__ = "artifacts"

    logical_artifact_id: Mapped[str] = mapped_column(String(41), primary_key=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.job_id"), unique=True, nullable=False)
    artifact_type: Mapped[str] = mapped_column(String(64), nullable=False)
    approved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    revisions: Mapped[list[ArtifactRevisionRecord]] = relationship(back_populates="artifact")


class ArtifactRevisionRecord(Base):
    __tablename__ = "artifact_revisions"
    __table_args__ = (
        UniqueConstraint("logical_artifact_id", "content_hash", name="uq_artifact_content_hash"),
        UniqueConstraint(
            "logical_artifact_id", "revision_id", name="uq_artifact_revision_identity"
        ),
    )

    revision_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    logical_artifact_id: Mapped[str] = mapped_column(
        ForeignKey("artifacts.logical_artifact_id"), nullable=False, index=True
    )
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.job_id"), unique=True, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(71), nullable=False)
    manifest_hash: Mapped[str] = mapped_column(String(71), nullable=False)
    content_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    nas_path: Mapped[str] = mapped_column(Text, nullable=False)
    manifest: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    result: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    approved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    artifact: Mapped[ArtifactRecord] = relationship(back_populates="revisions")
