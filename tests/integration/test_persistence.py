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
from sqlalchemy import Engine, select, text
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
    vector_item_hash = role_schema_bundle_hash("workflow-role/1.12.0")
    legacy_extraction_hash = role_schema_bundle_hash("workflow-role/1.14.0")
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
    ensure_protocol_version(db_session, "workflow-role/1.12.0", vector_item_hash)
    ensure_protocol_version(db_session, "workflow-role/1.12.0", vector_item_hash)
    ensure_protocol_version(db_session, "workflow-role/1.14.0", legacy_extraction_hash)
    ensure_protocol_version(db_session, "workflow-role/1.14.0", legacy_extraction_hash)
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
    vector_item_record = db_session.get(ProtocolVersionRecord, "workflow-role/1.12.0")
    legacy_extraction_record = db_session.get(ProtocolVersionRecord, "workflow-role/1.14.0")
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
    assert vector_item_record is not None and vector_item_record.schema_sha256 == vector_item_hash
    assert legacy_extraction_record is not None
    assert legacy_extraction_record.schema_sha256 == legacy_extraction_hash
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
    with pytest.raises(RuntimeError, match="schema hash mismatch"):
        ensure_protocol_version(db_session, "workflow-role/1.12.0", analysis_stable_identity_hash)
    with pytest.raises(RuntimeError, match="schema hash mismatch"):
        ensure_protocol_version(db_session, "workflow-role/1.14.0", vector_item_hash)


def test_item_origin_and_legacy_assessment_migrations_install_fail_closed_guards(
    db_session: Session,
) -> None:
    required_tables = {
        "organizations",
        "organization_revisions",
        "assessment_occurrences",
        "assessment_occurrence_revisions",
        "item_origin_profiles",
        "assessment_source_bundles",
        "assessment_source_bundle_revisions",
        "assessment_source_bundle_members",
        "assessment_layout_observations",
        "legacy_item_extraction_acceptances",
        "legacy_item_corpus_coverages",
    }
    actual_tables = set(
        db_session.scalars(
            text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'app' AND table_name = ANY(:names)"
            ),
            {"names": sorted(required_tables)},
        )
    )
    assert actual_tables == required_tables

    required_constraints = {
        "fk_organization_current_revision",
        "fk_assessment_occurrence_organization_revision_identity",
        "fk_item_origin_profile_item_revision_identity",
        "fk_assessment_source_bundle_inventory_artifact_revision_identity",
        "fk_assessment_source_bundle_member_artifact_revision_identity",
        "fk_assessment_layout_bundle_revision_identity",
        "fk_legacy_item_acceptance_result_artifact_revision_identity",
    }
    actual_constraints = set(
        db_session.scalars(
            text(
                "SELECT conname FROM pg_constraint "
                "WHERE connamespace = 'app'::regnamespace AND conname = ANY(:names)"
            ),
            {"names": sorted(required_constraints)},
        )
    )
    assert actual_constraints == required_constraints

    required_triggers = {
        "trg_organizations_controlled_update",
        "trg_organization_revisions_immutable",
        "trg_assessment_source_bundles_controlled_update",
        "trg_assessment_source_bundle_revisions_immutable",
        "trg_legacy_item_extraction_acceptances_immutable",
    }
    actual_triggers = set(
        db_session.scalars(
            text(
                "SELECT trigger_name FROM information_schema.triggers "
                "WHERE event_object_schema = 'app' AND trigger_name = ANY(:names)"
            ),
            {"names": sorted(required_triggers)},
        )
    )
    assert actual_triggers == required_triggers

    organization_id = "org_" + "9" * 32
    organization_revision_id = "orgrev_" + "9" * 32
    db_session.execute(
        text(
            "INSERT INTO organizations "
            "(organization_id, organization_key, current_revision_id, lifecycle_state, "
            " lock_version, created_by) "
            "VALUES (:organization_id, :organization_key, NULL, 'ACTIVE', 1, 'integration')"
        ),
        {
            "organization_id": organization_id,
            "organization_key": "organization.integration-guard",
        },
    )
    db_session.execute(
        text(
            "INSERT INTO organization_revisions "
            "(organization_revision_id, organization_id, revision_number, previous_revision_id, "
            " revision_state, organization_class, class_detail, display_name, locale, "
            " country_code, jurisdiction_level, jurisdiction_code, effective_from, effective_to, "
            " rights_policy_id, rights_policy_revision_id, rights_policy_sha256, revision_sha256, "
            " created_at, created_by) "
            "VALUES (:revision_id, :organization_id, 1, NULL, 'REVIEWED', 'OTHER_REVIEWED', "
            " 'integration', 'Integration Guard', 'ko-KR', 'KR', 'OTHER', NULL, NULL, NULL, "
            " :policy_id, :policy_revision_id, :sha256, :revision_sha256, now(), 'integration')"
        ),
        {
            "revision_id": organization_revision_id,
            "organization_id": organization_id,
            "policy_id": "rightspolicy_" + "8" * 32,
            "policy_revision_id": "rightspolicyrev_" + "8" * 32,
            "sha256": "sha256:" + "8" * 64,
            "revision_sha256": "sha256:" + "9" * 64,
        },
    )
    db_session.execute(
        text(
            "UPDATE organizations SET current_revision_id = :revision_id, lock_version = 2 "
            "WHERE organization_id = :organization_id"
        ),
        {
            "revision_id": organization_revision_id,
            "organization_id": organization_id,
        },
    )
    db_session.flush()

    with pytest.raises(DBAPIError, match="immutable"), db_session.begin_nested():
        db_session.execute(
            text(
                "UPDATE organization_revisions SET display_name = 'mutated' "
                "WHERE organization_revision_id = :revision_id"
            ),
            {"revision_id": organization_revision_id},
        )
    with pytest.raises(DBAPIError, match="immutable identity"), db_session.begin_nested():
        db_session.execute(
            text(
                "UPDATE organizations SET organization_key = 'organization.changed', "
                "lifecycle_state = 'RETIRED', lock_version = 3 "
                "WHERE organization_id = :organization_id"
            ),
            {"organization_id": organization_id},
        )


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
