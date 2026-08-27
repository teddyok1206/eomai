from __future__ import annotations

from datetime import UTC, datetime

import pytest
from alembic.runtime.migration import MigrationContext
from eom_identifiers import new_job_id, new_logical_artifact_id, new_revision_id
from eom_orchestrator.migration import CURRENT_MIGRATION_REVISION
from eom_orchestrator.models import ArtifactRevisionRecord, JobEventRecord, ProtocolVersionRecord
from eom_orchestrator.protocol import protocol_schema_hash
from eom_orchestrator.repository import (
    create_artifact_records,
    ensure_protocol_version,
    submit_job,
    upsert_worker_slot,
)
from eom_orchestrator.state_machine import JobState, transition_job
from eom_protocol import ArtifactSpec, JobRequest, SmokePayload
from eom_workflow.schemas import role_schema_bundle_hash
from sqlalchemy import Engine, select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

pytestmark = pytest.mark.integration


def _request(idempotency_key: str) -> JobRequest:
    return JobRequest(
        job_id=new_job_id(),
        idempotency_key=idempotency_key,
        payload=SmokePayload(message="EOM_PLATFORM_SMOKE_TEST"),
        artifact=ArtifactSpec(
            logical_artifact_id=new_logical_artifact_id(), revision_id=new_revision_id()
        ),
        submitted_at=datetime.now(UTC),
    )


def test_migration_revision(integration_engine: Engine) -> None:
    with integration_engine.connect() as connection:
        assert MigrationContext.configure(connection).get_current_revision() == (
            CURRENT_MIGRATION_REVISION
        )


def test_role_protocol_versions_coexist_without_reinterpreting_history(
    db_session: Session,
) -> None:
    old_hash = role_schema_bundle_hash("workflow-role/1.2.0")
    new_hash = role_schema_bundle_hash("workflow-role/1.3.0")
    analysis_old_hash = role_schema_bundle_hash("workflow-role/1.5.0")
    analysis_new_hash = role_schema_bundle_hash("workflow-role/1.6.0")
    analysis_integrity_hash = role_schema_bundle_hash("workflow-role/1.7.0")
    analysis_multimodal_hash = role_schema_bundle_hash("workflow-role/1.8.0")
    analysis_schema_closed_hash = role_schema_bundle_hash("workflow-role/1.9.0")
    analysis_typed_identity_hash = role_schema_bundle_hash("workflow-role/1.10.0")
    analysis_stable_identity_hash = role_schema_bundle_hash("workflow-role/1.11.0")
    ensure_protocol_version(db_session, "workflow-role/1.2.0", old_hash)
    ensure_protocol_version(db_session, "workflow-role/1.3.0", new_hash)
    ensure_protocol_version(db_session, "workflow-role/1.5.0", analysis_old_hash)
    ensure_protocol_version(db_session, "workflow-role/1.6.0", analysis_new_hash)
    ensure_protocol_version(db_session, "workflow-role/1.6.0", analysis_new_hash)
    ensure_protocol_version(db_session, "workflow-role/1.7.0", analysis_integrity_hash)
    ensure_protocol_version(db_session, "workflow-role/1.7.0", analysis_integrity_hash)
    ensure_protocol_version(db_session, "workflow-role/1.8.0", analysis_multimodal_hash)
    ensure_protocol_version(db_session, "workflow-role/1.8.0", analysis_multimodal_hash)
    ensure_protocol_version(db_session, "workflow-role/1.9.0", analysis_schema_closed_hash)
    ensure_protocol_version(db_session, "workflow-role/1.9.0", analysis_schema_closed_hash)
    ensure_protocol_version(db_session, "workflow-role/1.10.0", analysis_typed_identity_hash)
    ensure_protocol_version(db_session, "workflow-role/1.10.0", analysis_typed_identity_hash)
    ensure_protocol_version(db_session, "workflow-role/1.11.0", analysis_stable_identity_hash)
    ensure_protocol_version(db_session, "workflow-role/1.11.0", analysis_stable_identity_hash)
    ensure_protocol_version(db_session, "workflow-role/1.3.0", new_hash)
    db_session.flush()

    old_record = db_session.get(ProtocolVersionRecord, "workflow-role/1.2.0")
    new_record = db_session.get(ProtocolVersionRecord, "workflow-role/1.3.0")
    analysis_old_record = db_session.get(ProtocolVersionRecord, "workflow-role/1.5.0")
    analysis_new_record = db_session.get(ProtocolVersionRecord, "workflow-role/1.6.0")
    analysis_integrity_record = db_session.get(ProtocolVersionRecord, "workflow-role/1.7.0")
    analysis_multimodal_record = db_session.get(ProtocolVersionRecord, "workflow-role/1.8.0")
    analysis_schema_closed_record = db_session.get(ProtocolVersionRecord, "workflow-role/1.9.0")
    analysis_typed_identity_record = db_session.get(ProtocolVersionRecord, "workflow-role/1.10.0")
    analysis_stable_identity_record = db_session.get(ProtocolVersionRecord, "workflow-role/1.11.0")
    assert old_record is not None and old_record.schema_sha256 == old_hash
    assert new_record is not None and new_record.schema_sha256 == new_hash
    assert (
        analysis_old_record is not None and analysis_old_record.schema_sha256 == analysis_old_hash
    )
    assert (
        analysis_new_record is not None and analysis_new_record.schema_sha256 == analysis_new_hash
    )
    assert analysis_integrity_record is not None
    assert analysis_integrity_record.schema_sha256 == analysis_integrity_hash
    assert analysis_multimodal_record is not None
    assert analysis_multimodal_record.schema_sha256 == analysis_multimodal_hash
    assert analysis_schema_closed_record is not None
    assert analysis_schema_closed_record.schema_sha256 == analysis_schema_closed_hash
    assert analysis_typed_identity_record is not None
    assert analysis_typed_identity_record.schema_sha256 == analysis_typed_identity_hash
    assert analysis_stable_identity_record is not None
    assert analysis_stable_identity_record.schema_sha256 == analysis_stable_identity_hash
    with pytest.raises(RuntimeError, match="schema hash mismatch"):
        ensure_protocol_version(db_session, "workflow-role/1.6.0", analysis_integrity_hash)
    with pytest.raises(RuntimeError, match="schema hash mismatch"):
        ensure_protocol_version(db_session, "workflow-role/1.2.0", new_hash)
    with pytest.raises(RuntimeError, match="schema hash mismatch"):
        ensure_protocol_version(db_session, "workflow-role/1.9.0", analysis_multimodal_hash)
    with pytest.raises(RuntimeError, match="schema hash mismatch"):
        ensure_protocol_version(db_session, "workflow-role/1.10.0", analysis_schema_closed_hash)
    with pytest.raises(RuntimeError, match="schema hash mismatch"):
        ensure_protocol_version(db_session, "workflow-role/1.11.0", analysis_typed_identity_hash)


def test_job_events_idempotency_and_immutable_artifact(db_session: Session) -> None:
    request = _request("integration-idempotency-key")
    ensure_protocol_version(db_session, request.protocol_version, protocol_schema_hash())
    upsert_worker_slot(
        db_session,
        slot_id="01",
        linux_user="eom-cdx-01",
        role="authoring",
        enabled=True,
        gpu=False,
    )
    job, created = submit_job(db_session, request)
    assert created
    duplicate, duplicate_created = submit_job(db_session, _request("integration-idempotency-key"))
    assert not duplicate_created
    assert duplicate.job_id == job.job_id

    for target, event in (
        (JobState.VALIDATED, "REQUEST_VALIDATED"),
        (JobState.QUEUED, "JOB_QUEUED"),
        (JobState.CLAIMED, "WORKER_CLAIMED"),
        (JobState.RUNNING, "WORKER_STARTED"),
        (JobState.VALIDATING_RESULT, "WORKER_RESULT_RECEIVED"),
        (JobState.COMMITTING, "ARTIFACT_COMMIT_STARTED"),
    ):
        transition_job(db_session, job.job_id, target, event)
        db_session.flush()

    manifest = {
        "protocol_version": "1.0.1",
        "manifest_version": "1.0.0",
        "job_id": job.job_id,
        "logical_artifact_id": job.logical_artifact_id,
        "revision_id": job.revision_id,
        "content_hash": "sha256:" + "a" * 64,
        "content_bytes": 10,
        "file_name": "result.json",
        "media_type": "application/json",
        "worker_slot": "01",
        "created_at": "2026-08-15T00:00:00Z",
    }
    result = {
        "protocol_version": "1.0.1",
        "job_id": job.job_id,
        "status": "ok",
        "message": "EOM_PLATFORM_SMOKE_TEST_OK",
    }
    create_artifact_records(
        db_session,
        job=job,
        content_hash="sha256:" + "a" * 64,
        manifest_hash="sha256:" + "b" * 64,
        content_bytes=10,
        nas_path=f"/tmp/{job.logical_artifact_id}/{job.revision_id}",
        manifest=manifest,
        result=result,
    )
    transition_job(db_session, job.job_id, JobState.SUCCEEDED, "ARTIFACT_COMMITTED")
    db_session.flush()

    events = list(
        db_session.scalars(
            select(JobEventRecord)
            .where(JobEventRecord.job_id == job.job_id)
            .order_by(JobEventRecord.sequence)
        )
    )
    assert [event.sequence for event in events] == list(range(1, 9))
    assert [event.to_state for event in events][-1] == "SUCCEEDED"

    revision = db_session.get(ArtifactRevisionRecord, job.revision_id)
    assert revision is not None
    with pytest.raises(DBAPIError, match="immutable"), db_session.begin_nested():
        revision.content_hash = "sha256:" + "c" * 64
        db_session.flush()
