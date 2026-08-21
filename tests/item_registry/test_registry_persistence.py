from __future__ import annotations

from datetime import UTC, datetime

import pytest
from eom_catalog_service.models import (
    ContentPackRecord,
    ContentPackReleaseRecord,
    DeliverableRecord,
    DeliverableRevisionRecord,
    ItemComponentRecord,
    ItemRecord,
    ItemRevisionRecord,
    UsagePlanRecord,
    UsageRecord,
)
from eom_hwpx_manager.models import HwpxApplicationBuildRecord
from eom_identifiers import new_job_id, new_logical_artifact_id, new_revision_id
from eom_identity_service.models import OperatorRecord
from eom_orchestrator.models import JobRecord
from eom_orchestrator.repository import (
    create_artifact_records,
    ensure_protocol_version,
    submit_structured_job,
)
from eom_orchestrator.state_machine import JobState, transition_job
from eom_workflow_runner.models import (
    WorkflowDefinitionRecord,
    WorkflowInstanceRecord,
    WorkflowStepRunRecord,
)
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

pytestmark = pytest.mark.integration


def _artifact(session: Session) -> JobRecord:
    ensure_protocol_version(session, "registry-test/1.0", "sha256:" + "1" * 64)
    job, _ = submit_structured_job(
        session,
        job_id=new_job_id(),
        protocol_version="registry-test/1.0",
        idempotency_key="registry-test-" + new_job_id(),
        task_type="registry-test",
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
        content_hash="sha256:" + "2" * 64,
        manifest_hash="sha256:" + "3" * 64,
        content_bytes=1,
        nas_path="/tmp/registry-test",
        manifest={"manifest_version": "test/1.0"},
        result={"status": "ok"},
    )
    transition_job(session, job.job_id, JobState.SUCCEEDED, "TEST_COMMITTED")
    return job


def _prerequisites(
    session: Session,
) -> tuple[JobRecord, WorkflowInstanceRecord, WorkflowStepRunRecord, ContentPackReleaseRecord]:
    artifact = _artifact(session)
    definition = WorkflowDefinitionRecord(
        definition_id="wfdef_" + "1" * 32,
        definition_key="registry-test",
        definition_version="1.1.0",
        schema_version="1.0",
        canonical_definition={"placeholder": True},
        definition_hash="sha256:" + "4" * 64,
        active=True,
        source_path="registry-test.yaml",
    )
    workflow = WorkflowInstanceRecord(
        workflow_id="workflow_" + "2" * 32,
        definition_id=definition.definition_id,
        definition_key=definition.definition_key,
        definition_version=definition.definition_version,
        definition_hash=definition.definition_hash,
        protocol_version="1.0.1",
        role_schema_version="1.0",
        state="COMPLETED",
        stage="COMPLETED",
        current_step_key="complete",
        request_payload={"request_name": "PLACEHOLDER_REQUEST", "image_mode": "skip"},
        initial_request={"request_name": "PLACEHOLDER_REQUEST", "image_mode": "skip"},
        runtime_context={},
        idempotency_key="registry-workflow-test",
        request_hash="sha256:" + "5" * 64,
        lock_version=1,
        rework_cycle_count=0,
        created_actor_type="human",
        created_actor_id="operator_01",
    )
    step = WorkflowStepRunRecord(
        step_run_id="steprun_" + "3" * 32,
        workflow_id=workflow.workflow_id,
        step_key="registration",
        attempt=1,
        step_type="agent",
        worker_role="item_management",
        result_schema="registration-result@1.0",
        state="SUCCEEDED",
        platform_job_id=artifact.job_id,
        input_pointer_manifest={},
        output_pointer_manifest={},
    )
    pack = ContentPackRecord(
        content_pack_id="contentpack_" + "4" * 32,
        pack_key="registry-test-pack",
        display_name="Registry Test Pack",
        description="PLACEHOLDER_CONTENT",
        locale="ko-KR",
        domain_key="PLACEHOLDER_DOMAIN",
    )
    release = ContentPackReleaseRecord(
        content_pack_release_id="packrel_" + "5" * 32,
        content_pack_id=pack.content_pack_id,
        version="0.1.0",
        schema_version="1.0",
        state="RELEASED",
        source_tree_sha256="sha256:" + "6" * 64,
        bundle_sha256="sha256:" + "7" * 64,
        manifest_sha256="sha256:" + "8" * 64,
        bundle_artifact_id=artifact.logical_artifact_id,
        bundle_artifact_revision_id=artifact.revision_id,
        canonical_manifest_json={"files": []},
        compatibility_json={},
        lock_version=1,
    )
    session.add_all((definition, workflow, step, pack, release))
    session.flush()
    return artifact, workflow, step, release


def _approved_revision(session: Session) -> tuple[ItemRecord, ItemRevisionRecord, JobRecord]:
    artifact, workflow, step, release = _prerequisites(session)
    item = ItemRecord(
        item_id="item_" + "6" * 32,
        lifecycle_state="ACTIVE",
        created_by="operator_01",
        lock_version=1,
    )
    session.add(item)
    session.flush()
    revision = ItemRevisionRecord(
        item_revision_id="itemrev_" + "7" * 32,
        item_id=item.item_id,
        revision_number=1,
        revision_state="APPROVED",
        registration_key="registry-test-registration",
        content_pack_release_id=release.content_pack_release_id,
        workflow_id=workflow.workflow_id,
        workflow_definition_version="1.1.0",
        source_workflow_step_run_id=step.step_run_id,
        manifest_artifact_id=artifact.logical_artifact_id,
        manifest_artifact_revision_id=artifact.revision_id,
        manifest_sha256="sha256:" + "2" * 64,
        item_type_key="generic-multiple-choice",
        primary_taxonomy_ref="PLACEHOLDER_TAXONOMY",
        difficulty_band="PLACEHOLDER_DIFFICULTY",
        metadata_json={"placeholder": True},
        metadata_sha256="sha256:" + "9" * 64,
        created_by="operator_01",
        approved_at=datetime.now(UTC),
        approved_by="operator_01",
        lock_version=1,
    )
    session.add(revision)
    session.flush()
    item.current_revision_id = revision.item_revision_id
    session.flush()
    return item, revision, artifact


def test_approved_revision_and_children_are_immutable(db_session: Session) -> None:
    item, revision, artifact = _approved_revision(db_session)
    component = ItemComponentRecord(
        item_component_id="itemcomponent_" + "8" * 32,
        item_revision_id=revision.item_revision_id,
        component_type="UPPER_STEM",
        ordinal=0,
        schema_ref="eom://component/placeholder@1.0",
        media_type="application/json",
        artifact_id=artifact.logical_artifact_id,
        artifact_revision_id=artifact.revision_id,
        sha256="sha256:" + "2" * 64,
        logical_name="PLACEHOLDER_CONTENT",
        required=True,
        metadata_json={},
    )
    db_session.add(component)
    db_session.flush()
    with pytest.raises(DBAPIError, match="immutable"), db_session.begin_nested():
        revision.metadata_json = {"changed": True}
        db_session.flush()
    db_session.refresh(revision)
    with pytest.raises(DBAPIError, match="immutable"), db_session.begin_nested():
        component.logical_name = "CHANGED"
        db_session.flush()
    assert item.current_revision_id == revision.item_revision_id


def test_component_position_and_usage_placement_are_unique(db_session: Session) -> None:
    item, revision, artifact = _approved_revision(db_session)
    base = {
        "item_revision_id": revision.item_revision_id,
        "component_type": "CHOICES",
        "ordinal": 0,
        "schema_ref": "eom://component/placeholder@1.0",
        "media_type": "application/json",
        "artifact_id": artifact.logical_artifact_id,
        "artifact_revision_id": artifact.revision_id,
        "sha256": "sha256:" + "2" * 64,
        "logical_name": "PLACEHOLDER_CONTENT",
        "required": True,
        "metadata_json": {},
    }
    db_session.add(ItemComponentRecord(item_component_id="itemcomponent_" + "a" * 32, **base))
    db_session.flush()
    with pytest.raises(IntegrityError), db_session.begin_nested():
        db_session.add(ItemComponentRecord(item_component_id="itemcomponent_" + "b" * 32, **base))
        db_session.flush()
    assert item.item_id == revision.item_id


def test_hwpx_application_build_pins_revision_and_enforces_idempotency(
    db_session: Session,
) -> None:
    item, revision, artifact = _approved_revision(db_session)
    operator = OperatorRecord(
        operator_id="operator_" + "c" * 32,
        username="hwpx-test-operator",
        normalized_username="hwpx-test-operator",
        display_name="HWPX Test Operator",
        status="ACTIVE",
        must_change_password=False,
        role_version=1,
        created_by="test-suite",
        lock_version=1,
    )
    db_session.add(operator)
    db_session.flush()
    source_hash = "sha256:" + "2" * 64
    first = HwpxApplicationBuildRecord(
        build_id="hwpxbuild_" + "d" * 32,
        item_id=item.item_id,
        item_revision_id=revision.item_revision_id,
        source_artifact_id=artifact.logical_artifact_id,
        source_artifact_revision_id=artifact.revision_id,
        source_sha256=source_hash,
        source_schema_ref="eom.hwpx.markdown-document/1.0",
        source_media_type="text/markdown",
        renderer="kordoc",
        renderer_version="4.9.0",
        options={"require_native_equations": True},
        request_sha256="sha256:" + "e" * 64,
        idempotency_key="test-hwpx-application-key",
        created_by_operator_id=operator.operator_id,
        state="REQUESTED",
        validation_state="PENDING",
        resource_version=1,
    )
    db_session.add(first)
    db_session.flush()

    assert first.item_revision_id == revision.item_revision_id
    assert first.source_artifact_revision_id == artifact.revision_id
    assert first.source_sha256 == source_hash
    assert not any(column.type.__class__.__name__ == "LargeBinary" for column in first.__table__.c)

    with pytest.raises(IntegrityError), db_session.begin_nested():
        db_session.add(
            HwpxApplicationBuildRecord(
                build_id="hwpxbuild_" + "f" * 32,
                item_id=item.item_id,
                item_revision_id=revision.item_revision_id,
                source_artifact_id=artifact.logical_artifact_id,
                source_artifact_revision_id=artifact.revision_id,
                source_sha256=source_hash,
                source_schema_ref="eom.hwpx.markdown-document/1.0",
                source_media_type="text/markdown",
                renderer="kordoc",
                renderer_version="4.9.0",
                options={"require_native_equations": False},
                request_sha256="sha256:" + "0" * 64,
                idempotency_key="test-hwpx-application-key",
                created_by_operator_id=operator.operator_id,
                state="REQUESTED",
                validation_state="PENDING",
                resource_version=1,
            )
        )
        db_session.flush()


def test_usage_record_requires_approved_revision_and_is_immutable(db_session: Session) -> None:
    item, revision, _ = _approved_revision(db_session)
    deliverable = DeliverableRecord(
        deliverable_id="deliverable_" + "c" * 32,
        deliverable_key="placeholder-deliverable",
        deliverable_type="OTHER",
        title="PLACEHOLDER_CONTENT",
        edition="0.1",
        lifecycle_state="PLANNED",
        created_by="operator_01",
    )
    deliverable_revision = DeliverableRevisionRecord(
        deliverable_revision_id="delivrev_" + "d" * 32,
        deliverable_id=deliverable.deliverable_id,
        revision_number=1,
        state="PLANNED",
        metadata_json={},
        metadata_sha256="sha256:" + "e" * 64,
    )
    plan = UsagePlanRecord(
        usage_plan_id="usageplan_" + "f" * 32,
        item_id=item.item_id,
        preferred_item_revision_id=revision.item_revision_id,
        deliverable_id=deliverable.deliverable_id,
        deliverable_revision_id=deliverable_revision.deliverable_revision_id,
        planned_section="PLACEHOLDER_SECTION",
        planned_sequence=1,
        status="RESERVED",
        created_by="operator_01",
        lock_version=1,
    )
    db_session.add_all((deliverable, deliverable_revision, plan))
    db_session.flush()
    usage = UsageRecord(
        usage_record_id="usagerecord_" + "1" * 32,
        item_id=item.item_id,
        item_revision_id=revision.item_revision_id,
        deliverable_id=deliverable.deliverable_id,
        deliverable_revision_id=deliverable_revision.deliverable_revision_id,
        section="PLACEHOLDER_SECTION",
        sequence=1,
        page=None,
        points="2",
        usage_role="PLACEHOLDER_ROLE",
        source_usage_plan_id=plan.usage_plan_id,
        recorded_by="operator_01",
        metadata_json={},
    )
    db_session.add(usage)
    db_session.flush()
    with pytest.raises(DBAPIError, match="immutable"), db_session.begin_nested():
        usage.page = 2
        db_session.flush()


def test_item_keyset_query_has_composite_index(db_session: Session) -> None:
    definition = db_session.execute(
        text(
            "SELECT indexdef FROM pg_indexes "
            "WHERE schemaname = current_schema() AND indexname = 'ix_items_keyset'"
        )
    ).scalar_one()
    assert "(created_at, item_id)" in definition
