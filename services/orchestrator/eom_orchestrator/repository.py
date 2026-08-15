"""Transactional job and artifact persistence operations."""

from __future__ import annotations

from typing import Any

from eom_identifiers import content_sha256
from eom_protocol import JobRequest
from sqlalchemy import select
from sqlalchemy.orm import Session

from eom_orchestrator.models import (
    ArtifactRecord,
    ArtifactRevisionRecord,
    JobEventRecord,
    JobRecord,
    ProtocolVersionRecord,
    WorkerSlotRecord,
)
from eom_orchestrator.state_machine import JobState, record_initial_event


class IdempotencyConflict(RuntimeError):
    pass


def ensure_protocol_version(session: Session, version: str, schema_sha256: str) -> None:
    record = session.get(ProtocolVersionRecord, version)
    if record is None:
        session.add(ProtocolVersionRecord(version=version, schema_sha256=schema_sha256))
    elif record.schema_sha256 != schema_sha256:
        raise RuntimeError(f"protocol version {version} schema hash mismatch")


def submit_job(session: Session, request: JobRequest) -> tuple[JobRecord, bool]:
    serialized = request.model_dump(mode="json")
    request_hash = content_sha256(
        {
            "protocol_version": request.protocol_version,
            "task_type": request.task_type,
            "payload": request.payload.model_dump(mode="json"),
        }
    )
    existing = session.scalar(
        select(JobRecord).where(JobRecord.idempotency_key == request.idempotency_key)
    )
    if existing is not None:
        if existing.request_hash != request_hash:
            raise IdempotencyConflict("idempotency key was already used for a different request")
        return existing, False

    job = JobRecord(
        job_id=request.job_id,
        protocol_version=request.protocol_version,
        idempotency_key=request.idempotency_key,
        request_hash=request_hash,
        task_type=request.task_type,
        request=serialized,
        status=JobState.CREATED.value,
        logical_artifact_id=request.artifact.logical_artifact_id,
        revision_id=request.artifact.revision_id,
    )
    session.add(job)
    session.flush()
    record_initial_event(session, job)
    return job, True


def submit_structured_job(
    session: Session,
    *,
    job_id: str,
    protocol_version: str,
    idempotency_key: str,
    task_type: str,
    request: dict[str, Any],
    logical_artifact_id: str,
    revision_id: str,
) -> tuple[JobRecord, bool]:
    request_hash = content_sha256(
        {
            "protocol_version": protocol_version,
            "task_type": task_type,
            "request": request,
        }
    )
    existing = session.scalar(select(JobRecord).where(JobRecord.idempotency_key == idempotency_key))
    if existing is not None:
        if existing.request_hash != request_hash:
            raise IdempotencyConflict("idempotency key was already used for a different request")
        return existing, False
    job = JobRecord(
        job_id=job_id,
        protocol_version=protocol_version,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        task_type=task_type,
        request=request,
        status=JobState.CREATED.value,
        logical_artifact_id=logical_artifact_id,
        revision_id=revision_id,
    )
    session.add(job)
    session.flush()
    record_initial_event(session, job)
    return job, True


def upsert_worker_slot(
    session: Session, *, slot_id: str, linux_user: str, role: str, enabled: bool, gpu: bool
) -> None:
    slot = session.get(WorkerSlotRecord, slot_id)
    if slot is None:
        session.add(
            WorkerSlotRecord(
                slot_id=slot_id,
                linux_user=linux_user,
                role=role,
                enabled=enabled,
                gpu=gpu,
            )
        )
        return
    slot.linux_user = linux_user
    slot.role = role
    slot.enabled = enabled
    slot.gpu = gpu


def create_artifact_records(
    session: Session,
    *,
    job: JobRecord,
    content_hash: str,
    manifest_hash: str,
    content_bytes: int,
    nas_path: str,
    manifest: dict[str, Any],
    result: dict[str, Any],
) -> None:
    if session.get(ArtifactRecord, job.logical_artifact_id) is not None:
        raise IdempotencyConflict(f"artifact already exists: {job.logical_artifact_id}")
    session.add(
        ArtifactRecord(
            logical_artifact_id=job.logical_artifact_id,
            job_id=job.job_id,
            artifact_type=job.task_type,
            approved=True,
        )
    )
    session.flush()
    session.add(
        ArtifactRevisionRecord(
            revision_id=job.revision_id,
            logical_artifact_id=job.logical_artifact_id,
            job_id=job.job_id,
            content_hash=content_hash,
            manifest_hash=manifest_hash,
            content_bytes=content_bytes,
            nas_path=nas_path,
            manifest=manifest,
            result=result,
            approved=True,
        )
    )


def list_job_events(session: Session, job_id: str) -> list[JobEventRecord]:
    return list(
        session.scalars(
            select(JobEventRecord)
            .where(JobEventRecord.job_id == job_id)
            .order_by(JobEventRecord.sequence)
        )
    )
