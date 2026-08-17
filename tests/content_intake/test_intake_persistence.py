from __future__ import annotations

from datetime import UTC, datetime

import pytest
from eom_catalog_service.intake_evidence import IntakeEvidenceResolver
from eom_catalog_service.intake_repository import append_intake_event, transition_intake
from eom_catalog_service.models import (
    ContentIntakeAnalysisRecord,
    ContentIntakeBatchRecord,
    ContentIntakeDecisionRecord,
    ContentIntakeEventRecord,
    ContentIntakeSourceFileRecord,
)
from eom_content_intake import IntakeError, IntakeState
from eom_identifiers import new_job_id, new_logical_artifact_id, new_revision_id
from eom_orchestrator.models import ArtifactRevisionRecord, JobRecord
from eom_orchestrator.repository import (
    create_artifact_records,
    ensure_protocol_version,
    submit_structured_job,
)
from eom_orchestrator.state_machine import JobState, transition_job
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

pytestmark = pytest.mark.integration


def _artifact(session: Session, key: str) -> JobRecord:
    ensure_protocol_version(session, "catalog-test/1.0", "sha256:" + "f" * 64)
    job, _ = submit_structured_job(
        session,
        job_id=new_job_id(),
        protocol_version="catalog-test/1.0",
        idempotency_key=key,
        task_type="catalog-test",
        request={"placeholder": True},
        logical_artifact_id=new_logical_artifact_id(),
        revision_id=new_revision_id(),
    )
    for state in (
        JobState.VALIDATED,
        JobState.QUEUED,
        JobState.CLAIMED,
        JobState.RUNNING,
        JobState.VALIDATING_RESULT,
        JobState.COMMITTING,
    ):
        transition_job(session, job.job_id, state, f"TEST_{state.value}")
    create_artifact_records(
        session,
        job=job,
        content_hash="sha256:" + "a" * 64,
        manifest_hash="sha256:" + "b" * 64,
        content_bytes=10,
        nas_path=f"/tmp/{job.logical_artifact_id}/{job.revision_id}",
        manifest={"placeholder": True},
        result={"placeholder": True},
    )
    transition_job(session, job.job_id, JobState.SUCCEEDED, "TEST_COMMITTED")
    session.flush()
    return job


def _batch(session: Session, suffix: str = "1") -> ContentIntakeBatchRecord:
    batch = ContentIntakeBatchRecord(
        intake_batch_id="intake_" + suffix * 32,
        batch_name="PLACEHOLDER_BATCH",
        state=IntakeState.RECEIVED.value,
        purpose="PLACEHOLDER_PURPOSE",
        received_by="operator_01",
        source_owner_type="internal_team_member",
        source_owner_reference="team_lead_placeholder",
        source_fingerprint="sha256:" + suffix * 64,
        lock_version=1,
    )
    session.add(batch)
    session.flush()
    append_intake_event(
        session,
        batch,
        event_type="CONTENT_INTAKE_RECEIVED",
        prior_state=None,
        new_state=IntakeState.RECEIVED.value,
        actor_id="operator_01",
    )
    return batch


def test_intake_event_sequence_lifecycle_and_idempotency_constraint(db_session: Session) -> None:
    batch = _batch(db_session)
    for target in (
        IntakeState.HASHED,
        IntakeState.ANALYSIS_PENDING,
        IntakeState.ANALYSIS_ATTACHED,
        IntakeState.VALIDATING,
        IntakeState.NEEDS_DECISION,
        IntakeState.ACCEPTED,
        IntakeState.IMPORTED,
    ):
        transition_intake(
            db_session,
            batch,
            target,
            event_type=f"TEST_{target.value}",
            actor_id="operator_01",
        )
    events = list(
        db_session.scalars(
            select(ContentIntakeEventRecord)
            .where(ContentIntakeEventRecord.intake_batch_id == batch.intake_batch_id)
            .order_by(ContentIntakeEventRecord.sequence)
        )
    )
    assert [event.sequence for event in events] == list(range(1, 9))
    duplicate = ContentIntakeBatchRecord(
        intake_batch_id="intake_" + "2" * 32,
        batch_name="PLACEHOLDER_DUPLICATE",
        state=IntakeState.RECEIVED.value,
        purpose="PLACEHOLDER_PURPOSE",
        received_by="operator_01",
        source_owner_type="internal_team_member",
        source_owner_reference="team_lead_placeholder",
        source_fingerprint=batch.source_fingerprint,
        lock_version=1,
    )
    with pytest.raises(IntegrityError), db_session.begin_nested():
        db_session.add(duplicate)
        db_session.flush()


def test_intake_source_analysis_decision_and_terminal_batch_are_db_immutable(
    db_session: Session,
) -> None:
    artifact = _artifact(db_session, "catalog-intake-evidence")
    batch = _batch(db_session, "3")
    source = ContentIntakeSourceFileRecord(
        source_file_id="sourcefile_" + "4" * 32,
        intake_batch_id=batch.intake_batch_id,
        original_filename="PLACEHOLDER.txt",
        normalized_filename="PLACEHOLDER.txt",
        relative_path="source/PLACEHOLDER.txt",
        media_type="text/plain",
        size_bytes=10,
        sha256="sha256:" + "a" * 64,
        artifact_id=artifact.logical_artifact_id,
        artifact_revision_id=artifact.revision_id,
        declared_role="REFERENCE",
        declared_description="PLACEHOLDER_DESCRIPTION",
    )
    db_session.add(source)
    analysis = ContentIntakeAnalysisRecord(
        analysis_id="analysis_" + "5" * 32,
        intake_batch_id=batch.intake_batch_id,
        proposal_key="proposal_placeholder_001",
        analysis_source_type="MANUAL_EXTERNAL_ANALYSIS",
        analysis_report_artifact_id=artifact.logical_artifact_id,
        analysis_report_artifact_revision_id=artifact.revision_id,
        analysis_report_sha256="sha256:" + "c" * 64,
        mapping_proposal_artifact_id=artifact.logical_artifact_id,
        mapping_proposal_artifact_revision_id=artifact.revision_id,
        mapping_proposal_sha256="sha256:" + "d" * 64,
        uncertainties_artifact_id=artifact.logical_artifact_id,
        uncertainties_artifact_revision_id=artifact.revision_id,
        uncertainties_sha256="sha256:" + "e" * 64,
        created_by="operator_01",
        immutable=True,
    )
    db_session.add(analysis)
    decision = ContentIntakeDecisionRecord(
        decision_id="decision_" + "6" * 32,
        intake_batch_id=batch.intake_batch_id,
        analysis_id=analysis.analysis_id,
        decision="REJECT",
        decision_artifact_id=artifact.logical_artifact_id,
        decision_artifact_revision_id=artifact.revision_id,
        decision_sha256="sha256:" + "f" * 64,
        decided_by="operator_01",
        decided_at=datetime.now(UTC),
        notes="PLACEHOLDER_DECISION_NOTES",
        immutable=True,
    )
    db_session.add(decision)
    db_session.flush()
    for record, field, value in (
        (source, "declared_description", "CHANGED"),
        (analysis, "created_by", "changed"),
        (decision, "notes", "CHANGED"),
    ):
        with pytest.raises(DBAPIError, match="immutable"), db_session.begin_nested():
            setattr(record, field, value)
            db_session.flush()
        db_session.refresh(record)

    for target in (
        IntakeState.HASHED,
        IntakeState.ANALYSIS_PENDING,
        IntakeState.ANALYSIS_ATTACHED,
        IntakeState.VALIDATING,
        IntakeState.NEEDS_DECISION,
        IntakeState.REJECTED,
    ):
        transition_intake(
            db_session,
            batch,
            target,
            event_type=f"TEST_{target.value}",
            actor_id="operator_01",
        )
    db_session.flush()
    with pytest.raises(DBAPIError, match="terminal"), db_session.begin_nested():
        batch.batch_name = "CHANGED"
        db_session.flush()


def test_intake_evidence_rejects_missing_and_wrong_schema_pointer(
    db_session: Session,
) -> None:
    resolver = IntakeEvidenceResolver()
    batch = ContentIntakeBatchRecord(
        intake_batch_id="intake_" + "7" * 32,
        batch_name="PLACEHOLDER_BATCH",
        state=IntakeState.ANALYSIS_ATTACHED.value,
        purpose="PLACEHOLDER_PURPOSE",
        received_by="operator_01",
        source_owner_type="internal_team_member",
        source_owner_reference="team_lead_placeholder",
        source_fingerprint="sha256:" + "7" * 64,
        source_manifest_artifact_id="artifact_" + "8" * 32,
        source_manifest_artifact_revision_id="rev_" + "9" * 32,
        source_manifest_sha256="sha256:" + "a" * 64,
        lock_version=1,
    )
    with pytest.raises(IntakeError, match="does not resolve"):
        resolver.verify_source_manifest(db_session, batch)

    artifact = _artifact(db_session, "catalog-intake-pointer-check")
    revision = db_session.get(ArtifactRevisionRecord, artifact.revision_id)
    assert revision is not None
    batch.source_manifest_artifact_id = artifact.logical_artifact_id
    batch.source_manifest_artifact_revision_id = artifact.revision_id
    batch.source_manifest_sha256 = revision.content_hash
    with pytest.raises(IntakeError, match="does not resolve"):
        resolver.verify_source_manifest(db_session, batch)


def test_accepted_intake_payload_is_immutable_but_import_transition_is_allowed(
    db_session: Session,
) -> None:
    batch = _batch(db_session, "a")
    for target in (
        IntakeState.HASHED,
        IntakeState.ANALYSIS_PENDING,
        IntakeState.ANALYSIS_ATTACHED,
        IntakeState.VALIDATING,
        IntakeState.NEEDS_DECISION,
        IntakeState.ACCEPTED,
    ):
        transition_intake(
            db_session,
            batch,
            target,
            event_type=f"TEST_{target.value}",
            actor_id="operator_01",
        )
    db_session.flush()
    with pytest.raises(DBAPIError, match=r"accepted.*immutable"), db_session.begin_nested():
        batch.batch_name = "CHANGED"
        db_session.flush()
    db_session.refresh(batch)
    transition_intake(
        db_session,
        batch,
        IntakeState.IMPORTED,
        event_type="TEST_IMPORTED",
        actor_id="catalog_service",
    )
    db_session.flush()
