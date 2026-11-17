"""Disposable source/question/Artifact ownership; no live Graph scope or model execution."""

import importlib.util
import io
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Barrier
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from eom_catalog_contracts.kakao_archive_binding import KakaoBindingRetire
from eom_catalog_contracts.kakao_concept_tasks import KakaoConceptCreate
from eom_catalog_service import kakao_concept_publication as publication
from eom_catalog_service.kakao_archive_authorization import KakaoArchiveError
from eom_catalog_service.kakao_archive_service import KakaoArchiveService
from eom_catalog_service.kakao_concept_models import KakaoConceptPhaseRecord, KakaoConceptTaskRecord
from eom_catalog_service.kakao_concept_task_service import KakaoConceptTaskService
from eom_catalog_service.kakao_concept_workflow_submission import submit_kakao_concept_phase
from eom_catalog_service.kakao_question_service import KakaoQuestionService
from eom_identity_service.models import ApiSessionRecord, OperatorRecord
from eom_orchestrator.models import ArtifactRevisionRecord
from eom_protocol.general_chat_rag_knowledge import ChatRagScope
from eom_workflow.compiler import compile_definition
from eom_workflow.control_plane import ExecutionPresetRevision
from eom_workflow.kakao_concept_plan import KakaoConceptExecutionPlan
from eom_workflow.kakao_concept_request import validate_kakao_concept_request_bytes
from eom_workflow_runner import kakao_concept_start
from eom_workflow_runner.models import WorkflowCommandRecord, WorkflowInstanceRecord
from eom_workflow_runner.repository import import_workflow_definition
from PIL import Image
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from tests.integration.test_kakao_archive_storage import make_actor
from tests.integration.test_kakao_question_storage import change_command, create_question
from tests.integration.test_kakao_question_storage import question_store as question_store
from tests.integration.test_kakao_source_storage import source_store as source_store
from tests.unit.test_external_item_learning_execution_resolver import _published_preset
from tests.unit.test_kakao_concept_contracts import ROOT
from tests.unit.test_kakao_concept_tasks import scope_value
from tests.unit.test_kakao_concept_workflow_contracts import plan_value, rehash

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]


@pytest.fixture
def concept_store(question_store):
    engine, actor, questions, _, sources, artifacts, binding = question_store
    created, _ = create_question(question_store)
    command = KakaoConceptCreate(
        source_binding_id=binding.source_binding_id,
        room_id=created.question.room_id,
        question_id=created.question.question_id,
        question_revision_id=created.question.question_revision_id,
        expected_question_version=created.question.resource_version,
        base_study_revision_id=None,
        additional_instructions="synthetic concept instruction",
    )
    # This scope port does not claim that the actual Graph/policy exists or was retrieved.
    service = KakaoConceptTaskService(
        engine,
        artifacts=artifacts,
        questions=questions,
        sources=sources,
        scope_provider=lambda *_: ChatRagScope.model_validate(scope_value()),
    )
    return service, actor, command, question_store


def prepared(store, *, key=None):
    service, actor, command, _ = store
    mutation = service.create_task(
        actor, command, idempotency_key=key or "concept-request-" + uuid4().hex
    )
    work = service.prepare_plan(actor, command.source_binding_id, mutation.task.task_id)
    return mutation, work


def test_real_question_intent_and_plan_survive_reconstruction_and_remain_pointer_only(
    concept_store,
):
    service, actor, command, store = concept_store
    key = "concept-reconstruction-" + uuid4().hex
    mutation, work = prepared(concept_store, key=key)
    _, intent = service.get_intent(actor, command.source_binding_id, mutation.task.task_id)
    assert intent.question_manifest == work.question_manifest
    engine, _, _, _, sources, artifacts, _ = store
    replacement = KakaoConceptTaskService(
        engine,
        artifacts=artifacts,
        questions=KakaoQuestionService(engine, artifacts=artifacts, sources=sources),
        sources=sources,
        scope_provider=lambda *_: pytest.fail("replay must not select latest Graph"),
    )
    replay = replacement.create_task(actor, command, idempotency_key=key)
    assert replay.replayed and replay.task == mutation.task
    assert replacement.prepare_plan(actor, command.source_binding_id, mutation.task.task_id) == work
    assert (
        replacement.get_intent(actor, command.source_binding_id, mutation.task.task_id)[1] == intent
    )
    with Session(engine) as session:
        authority = replacement.source_authority(
            actor, command.source_binding_id, mutation.task.task_id
        )
        assert authority.reauthorize(session, operator_id=actor.operator_id, work=work) == work
        task = session.get(KakaoConceptTaskRecord, work.task_id)
        phase = session.get(KakaoConceptPhaseRecord, (work.task_id, "PLAN"))
        for row in (task, phase):
            encoded = json.dumps(
                {column.name: getattr(row, column.name) for column in row.__table__.columns},
                default=str,
            )
            assert (
                "private question" not in encoded and "synthetic concept instruction" not in encoded
            )
            assert not any(
                isinstance(getattr(row, column.name), bytes) for column in row.__table__.columns
            )
        assert set(phase.work_input) == set(work.model_dump())


@pytest.mark.parametrize("phase", [False, True])
def test_concurrent_replay_has_one_task_request_and_one_plan(concept_store, phase):
    service, actor, command, store = concept_store
    key, barrier = "concept-same-" + uuid4().hex, Barrier(2)
    if phase:
        task = service.create_task(actor, command, idempotency_key=key).task

    def run():
        barrier.wait(timeout=20)
        return (
            service.prepare_plan(actor, command.source_binding_id, task.task_id)
            if phase
            else service.create_task(actor, command, idempotency_key=key)
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = tuple(pool.map(lambda _: run(), range(2)))
    assert results[0] == results[1] if phase else results[0].task == results[1].task
    with Session(store[0]) as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(KakaoConceptTaskRecord)
                .where(KakaoConceptTaskRecord.idempotency_key == key)
            )
            == 1
        )
        if phase:
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(KakaoConceptPhaseRecord)
                    .where(KakaoConceptPhaseRecord.task_id == task.task_id)
                )
                == 1
            )


def test_same_key_conflict_and_wrong_owner_cannot_read_or_admit(concept_store):
    service, actor, command, store = concept_store
    key = "concept-conflict-" + uuid4().hex
    task = service.create_task(actor, command, idempotency_key=key).task
    with pytest.raises(KakaoArchiveError, match="IDEMPOTENCY_CONFLICT"):
        service.create_task(
            actor,
            command.model_copy(update={"additional_instructions": "changed"}),
            idempotency_key=key,
        )
    other = make_actor(store[0])
    with pytest.raises(KakaoArchiveError):
        service.get_task(other, command.source_binding_id, task.task_id)
    with pytest.raises(KakaoArchiveError):
        service.create_task(other, command, idempotency_key="other-concept-" + uuid4().hex)


@pytest.mark.parametrize("case", ["operator", "binding", "wrong-work", "wrong-owner"])
def test_actual_source_authority_detects_revocation_without_impersonating_an_actor(
    concept_store, case
):
    service, actor, command, store = concept_store
    mutation, work = prepared(concept_store)
    authority = service.source_authority(actor, command.source_binding_id, mutation.task.task_id)
    if case == "operator":
        with Session(store[0]) as session, session.begin():
            session.execute(
                update(OperatorRecord)
                .where(OperatorRecord.operator_id == actor.operator_id)
                .values(status="DISABLED")
            )
    elif case == "binding":
        bindings = KakaoArchiveService(store[0])
        current = bindings.get_binding(actor, command.source_binding_id)
        bindings.command_binding(
            actor,
            command.source_binding_id,
            KakaoBindingRetire(
                parent_policy_revision_id=current.policy_revision.policy_revision_id,
                expected_resource_version=current.resource_version,
            ),
            idempotency_key="concept-retire-" + uuid4().hex,
        )
    elif case == "wrong-work":
        work = work.model_copy(update={"request_bytes": work.request_bytes + 1})
    with Session(store[0]) as session, pytest.raises(KakaoArchiveError):
        authority.reauthorize(
            session,
            operator_id="operator_" + "0" * 32 if case == "wrong-owner" else actor.operator_id,
            work=work,
        )


def test_new_question_edit_never_retargets_an_old_recommendation(concept_store):
    service, actor, command, store = concept_store
    task, work = prepared(concept_store)
    old = (
        store[2]
        .get_question(
            actor,
            command.source_binding_id,
            command.room_id,
            command.question_id,
            revision_id=command.question_revision_id,
        )
        .stored
    )
    changed = store[2].change_question(
        actor, change_command(old), idempotency_key="concept-review-" + uuid4().hex
    )
    assert changed.question.question_revision_id != command.question_revision_id
    assert service.prepare_plan(actor, command.source_binding_id, task.task.task_id) == work
    with pytest.raises(KakaoArchiveError, match="PRECONDITION"):
        service.create_task(actor, command, idempotency_key="stale-concept-" + uuid4().hex)


def test_http_logout_does_not_cancel_exact_accepted_background_work_or_allow_public_reads(
    concept_store,
):
    service, actor, command, store = concept_store
    mutation, work = prepared(concept_store)
    authority = service.source_authority(actor, command.source_binding_id, mutation.task.task_id)
    with Session(store[0]) as session, session.begin():
        session.execute(
            update(ApiSessionRecord)
            .where(ApiSessionRecord.api_session_id == actor.session_id)
            .values(revoked_at=datetime.now(UTC))
        )
    with Session(store[0]) as session:
        assert authority.reauthorize(session, operator_id=actor.operator_id, work=work) == work
        with pytest.raises(KakaoArchiveError):
            authority.reauthorize(
                session,
                operator_id=actor.operator_id,
                work=work.model_copy(update={"task_id": "kakaoconcepttask_" + uuid4().hex}),
            )
    restored = KakaoConceptTaskService(
        store[0],
        artifacts=service.artifacts,
        questions=service.questions,
        sources=service.sources,
    ).accepted_source_authority(task_id=work.task_id, operator_id=actor.operator_id)
    with Session(store[0]) as session:
        assert restored.reauthorize(session, operator_id=actor.operator_id, work=work) == work
    with pytest.raises(KakaoArchiveError):
        service.accepted_source_authority(task_id=work.task_id, operator_id="operator_" + "0" * 32)
    with pytest.raises(KakaoArchiveError):
        service.get_task(actor, command.source_binding_id, work.task_id)


def test_immutable_rows_and_phase_request_pins_are_enforced_by_postgresql(concept_store):
    _, _, _, store = concept_store
    mutation, work = prepared(concept_store)
    for cls, values in [
        (KakaoConceptTaskRecord, dict(request_sha256="sha256:" + "0" * 64)),
        (KakaoConceptPhaseRecord, dict(work_input={"task_id": work.task_id})),
    ]:
        with Session(store[0]) as session, pytest.raises(DBAPIError):
            session.execute(
                update(cls).where(cls.task_id == mutation.task.task_id).values(**values)
            )
            session.commit()


def test_actual_source_owner_submits_the_existing_workflow_and_replays_one_command(
    concept_store, monkeypatch
):
    service, actor, _, store = concept_store
    _, work = prepared(concept_store)
    compiled = compile_definition(ROOT / "config/workflows/kakao-concepts.v1.yaml", {"support"})
    with Session(store[0], expire_on_commit=False) as session, session.begin():
        definition, _ = import_workflow_definition(session, compiled)
        session.expunge(definition)

    def plan_port(_session, **kwargs):
        value = plan_value()
        value.update(
            workflow_id=kwargs["workflow_id"],
            workflow_definition_sha256=kwargs["workflow_definition_sha256"],
            work_input=kwargs["work"].model_dump(mode="json"),
        )
        return KakaoConceptExecutionPlan.model_validate(rehash(value))

    monkeypatch.setattr(kakao_concept_start, "resolve_kakao_concept_plan", plan_port)
    _, preset = _published_preset()
    args = dict(
        actor=actor,
        work=work,
        definition=definition,
        expected_preset=ExecutionPresetRevision.model_validate(preset.canonical_document),
    )
    first = submit_kakao_concept_phase(service, **args)
    second = submit_kakao_concept_phase(service, **args)
    assert first.workflow_id == second.workflow_id and first.command_id == second.command_id
    with Session(store[0]) as session:
        assert (
            session.get(KakaoConceptPhaseRecord, (work.task_id, "PLAN")).workflow_id
            == first.workflow_id
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(WorkflowCommandRecord)
                .where(WorkflowCommandRecord.workflow_id == first.workflow_id)
            )
            == 1
        )
        assert (
            session.get(WorkflowInstanceRecord, first.workflow_id).created_actor_id
            == actor.operator_id
        )


@pytest.fixture
def concept_execution_store(concept_store):
    """Actual source/Workflow/plan owners; capability observations remain synthetic."""
    from copy import deepcopy
    from types import SimpleNamespace

    from eom_catalog_contracts.kakao_concept_authorization import KakaoConceptAuthorizationRequest
    from eom_identifiers import content_sha256
    from eom_orchestrator.control_models import (
        ExecutionPresetRecord,
        ExecutionPresetRevisionRecord,
        ResolvedExecutionPlanRecord,
    )
    from eom_orchestrator.control_service import (
        publish_capacity_policy_revision,
        publish_execution_preset_revision,
        record_capacity_policy_revision,
        record_execution_preset_revision,
    )
    from eom_orchestrator.repository import ensure_protocol_version, submit_structured_job
    from eom_orchestrator.state_machine import JobState, transition_job
    from eom_workflow.control_plane import WorkerRole
    from eom_workflow.models import RoleWorkerInput
    from eom_workflow.schemas import role_schema_bundle_hash
    from eom_workflow.shared_worker_capacity import SharedWorkerCapacityPolicy
    from eom_workflow_runner.repository import create_step_run
    from eom_workflow_runner.role_execution_binding import bind_platform_role_job
    from eom_workflow_runner.state_machine import StepState, transition_step

    from tests.integration import test_control_plane_persistence as controls
    from tests.unit.test_shared_worker_capacity import capacity_value

    service, actor, _, store = concept_store
    _, work = prepared(concept_store)
    engine, identity = store[0], uuid4().hex
    compiled = compile_definition(ROOT / "config/workflows/kakao-concepts.v1.yaml", {"support"})
    with Session(engine, expire_on_commit=False) as session, session.begin():
        original, _, _ = controls._complete_control_plane(session, roles=tuple(WorkerRole))
        capacity = capacity_value()
        capacity.update(
            capacity_policy_id="capacity_" + identity,
            capacity_policy_revision_id="capacityrev_" + identity,
        )
        capacity = SharedWorkerCapacityPolicy.model_validate(capacity).model_dump(mode="json")
        capacity["content_sha256"] = content_sha256(
            {k: v for k, v in capacity.items() if k != "content_sha256"}
        )
        capacity_row = record_capacity_policy_revision(
            session,
            policy_key="concept-test-" + identity,
            document=capacity,
            created_by="disposable-test",
        )
        publish_capacity_policy_revision(
            session,
            capacity_policy_id=capacity_row.capacity_policy_id,
            capacity_policy_revision_id=capacity_row.capacity_policy_revision_id,
        )
        base_plan = session.get(ResolvedExecutionPlanRecord, original)
        base = session.get(ExecutionPresetRevisionRecord, base_plan.preset_revision_id)
        preset = deepcopy(base.canonical_document)
        old = session.scalar(
            select(ExecutionPresetRecord).where(
                ExecutionPresetRecord.preset_key == "kakao-concepts"
            )
        )
        last = (
            session.get(ExecutionPresetRevisionRecord, old.current_revision_id)
            if old is not None
            else None
        )
        support = next(entry for entry in preset["role_policies"] if entry["role"] == "support")
        support["reference_bundle"] = None
        preset.update(
            preset_id=old.preset_id if old is not None else "execpreset_" + identity,
            preset_revision_id="execpresetrev_" + identity,
            revision_number=last.revision_number + 1 if last else 1,
            role_policies=[support],
            capacity_policy_revision_id=capacity_row.capacity_policy_revision_id,
            general_knowledge_policy="DENY",
            compatible_workflow_protocols=["workflow-role/1.41.0"],
        )
        preset["content_sha256"] = content_sha256(
            {k: v for k, v in preset.items() if k != "content_sha256"}
        )
        ensure_protocol_version(
            session, "workflow-role/1.41.0", role_schema_bundle_hash("workflow-role/1.41.0")
        )
        preset_row = record_execution_preset_revision(
            session, preset_key="kakao-concepts", document=preset, created_by="disposable-test"
        )
        publish_execution_preset_revision(
            session,
            preset_id=preset_row.preset_id,
            preset_revision_id=preset_row.preset_revision_id,
        )
        definition, _ = import_workflow_definition(session, compiled)
        session.expunge(definition)
    submitted = submit_kakao_concept_phase(
        service,
        actor=actor,
        work=work,
        definition=definition,
        expected_preset=ExecutionPresetRevision.model_validate(preset),
    )
    with Session(engine, expire_on_commit=False) as session, session.begin():
        row = session.scalar(
            select(ResolvedExecutionPlanRecord).where(
                ResolvedExecutionPlanRecord.workflow_id == submitted.workflow_id
            )
        )
        pinned = KakaoConceptExecutionPlan.model_validate(row.canonical_document)
        step = create_step_run(
            session,
            workflow_id=submitted.workflow_id,
            step_key="assist",
            step_type="agent",
            worker_role="support",
            result_schema="kakao-concepts-result@1.0",
            input_pointer_manifest={},
            max_attempts=1,
        )
        ensure_protocol_version(
            session, "workflow-role/1.41.0", role_schema_bundle_hash("workflow-role/1.41.0")
        )
        worker = RoleWorkerInput(
            protocol_version="workflow-role/1.41.0",
            job_id="job_" + uuid4().hex,
            workflow_id=submitted.workflow_id,
            step_run_id=step.step_run_id,
            attempt=1,
            role="support",
            request=dict(
                request_name="KAKAO_CONCEPT_REQUEST", work_input=work.model_dump(mode="json")
            ),
            upstream_artifacts=(),
            artifact=dict(
                logical_artifact_id="artifact_" + uuid4().hex, revision_id="rev_" + uuid4().hex
            ),
        )
        job, _ = submit_structured_job(
            session,
            job_id=worker.job_id,
            protocol_version=worker.protocol_version,
            idempotency_key="concept-job-" + identity,
            task_type="workflow_support",
            request=worker.model_dump(mode="json"),
            logical_artifact_id=worker.artifact.logical_artifact_id,
            revision_id=worker.artifact.revision_id,
        )
        transition_job(session, job.job_id, JobState.VALIDATED, "REQUEST_VALIDATED")
        transition_job(session, job.job_id, JobState.QUEUED, "JOB_QUEUED")
        transition_step(step, StepState.RUNNING)
        bind_platform_role_job(
            session,
            workflow_id=submitted.workflow_id,
            step_run_id=step.step_run_id,
            step_key="assist",
            attempt=1,
            worker_role="support",
            job_id=job.job_id,
        )
        selection = KakaoConceptAuthorizationRequest(
            workflow_id=submitted.workflow_id,
            step_run_id=step.step_run_id,
            plan_id=pinned.plan_id,
            plan_sha256=pinned.plan_sha256,
            work_sha256=content_sha256(work),
        )
    return SimpleNamespace(
        service=service,
        actor=actor,
        store=store,
        work=work,
        engine=engine,
        pinned=pinned,
        worker=worker,
        selection=selection,
        now=controls.NOW,
        submitted=submitted,
    )


def test_actual_concept_authorization_plan_and_concurrent_shared_claim(concept_execution_store):
    """Actual source/Workflow/plan/lease owners; capability data remains synthetic, no process."""
    from datetime import timedelta

    from eom_catalog_service.kakao_concept_authorization import (
        CatalogKakaoConceptAuthorizationService,
    )
    from eom_orchestrator.control_service import acquire_worker_lease, terminalize_worker_lease

    value = concept_execution_store
    service, actor, selection = value.service, value.actor, value.selection
    engine, pinned, worker = value.engine, value.pinned, value.worker
    authorizer = CatalogKakaoConceptAuthorizationService(service)
    assert authorizer.authorize(selection).status == "SUCCESS"
    barrier = Barrier(2)

    def claim(_index):
        barrier.wait(timeout=15)
        with Session(engine) as session, session.begin():
            lease = acquire_worker_lease(
                session,
                plan_id=pinned.plan_id,
                step_key="assist",
                job_id=worker.job_id,
                attempt=1,
                workload_class="KNOWLEDGE_ANALYSIS",
                acquired_at=value.now + timedelta(minutes=1),
                ttl=timedelta(minutes=30),
            )
            return lease.lease_id, lease.worker_slot_id

    with ThreadPoolExecutor(max_workers=2) as executor:
        leases = tuple(executor.map(claim, range(2)))
    assert leases[0] == leases[1] and leases[0][1] in {"01", "02", "03", "04", "05"}
    with Session(engine) as session, session.begin():
        terminalize_worker_lease(
            session,
            lease_id=leases[0][0],
            terminal_state="RELEASED",
            reason_code="TEST_COMPLETED_NO_PROCESS",
            released_at=value.now + timedelta(minutes=2),
        )
        session.execute(
            update(ApiSessionRecord)
            .where(ApiSessionRecord.api_session_id == actor.session_id)
            .values(revoked_at=datetime.now(UTC))
        )
    assert authorizer.authorize(selection).status == "SUCCESS"
    with Session(engine) as session, session.begin():
        session.execute(
            update(OperatorRecord)
            .where(OperatorRecord.operator_id == actor.operator_id)
            .values(status="DISABLED")
        )
    with pytest.raises(KakaoArchiveError):
        authorizer.authorize(selection)


def _complete_synthetic_concept_plan(value, *, output=None):
    """New deterministic test-double output, not reinterpretation of a failed/model execution."""
    import tempfile
    from pathlib import Path

    from eom_orchestrator.artifacts import commit_artifact
    from eom_orchestrator.kakao_concept_artifact import stage_kakao_concept_artifact
    from eom_orchestrator.models import JobRecord
    from eom_orchestrator.repository import create_artifact_records
    from eom_orchestrator.state_machine import JobState, transition_job
    from eom_workflow.kakao_concept_result import KakaoConceptRoleResult
    from eom_workflow.models import KakaoConceptRoleResultHeader
    from eom_workflow_runner.models import WorkflowStepRunRecord
    from eom_workflow_runner.state_machine import (
        StepState,
        WorkflowState,
        transition_step,
        transition_workflow,
    )

    from tests.unit.test_kakao_concept_contracts import plan

    pointer = value.work.request_member
    raw = value.service.artifacts.read_member(
        artifact_id=pointer.artifact_id,
        revision_id=pointer.artifact_revision_id,
        member_path=pointer.member_path,
        sha256=pointer.sha256,
        schema_ref=pointer.schema_ref,
        media_type=pointer.media_type,
        max_bytes=value.work.request_bytes,
    )
    request = validate_kakao_concept_request_bytes(value.work, raw)
    body = {
        key: field
        for key, field in value.worker.model_dump(mode="json").items()
        if key
        in {
            "schema_version",
            "protocol_version",
            "job_id",
            "workflow_id",
            "step_run_id",
            "role",
            "artifact",
        }
    }
    body.update(
        status="ok",
        completed_at=datetime.now(UTC).isoformat(),
        output=dict(
            schema_version="kakao-concept-assistance-result/1.0",
            task_id=request.task_id,
            request_sha256=pointer.sha256,
            output=plan() if output is None else output,
        ),
    )
    result = KakaoConceptRoleResult.model_validate(body)
    settings = value.service.artifacts.settings
    with tempfile.TemporaryDirectory(
        prefix="concept-fake-worker.", dir=settings.staging_root
    ) as directory:
        staged = stage_kakao_concept_artifact(
            result=result,
            staging=Path(directory),
            worker_slot="05",
        )
        final = commit_artifact(staged, settings.nas_artifact_root)
        with Session(value.engine) as session, session.begin():
            job = session.get(JobRecord, value.worker.job_id)
            job.worker_slot_id = "05"
            for state in (
                JobState.CLAIMED,
                JobState.RUNNING,
                JobState.VALIDATING_RESULT,
                JobState.COMMITTING,
            ):
                transition_job(session, job.job_id, state, "SYNTHETIC_WORKER_TEST")
            create_artifact_records(
                session,
                job=job,
                content_hash=staged.content_hash,
                manifest_hash=staged.manifest_hash,
                content_bytes=staged.manifest.content_bytes,
                nas_path=str(final),
                manifest=staged.manifest.model_dump(mode="json"),
                result=KakaoConceptRoleResultHeader.model_validate(
                    result.model_dump(exclude={"output"})
                ).model_dump(mode="json"),
            )
            transition_job(session, job.job_id, JobState.SUCCEEDED, "SYNTHETIC_RESULT_COMMITTED")
            step = session.get(WorkflowStepRunRecord, value.selection.step_run_id)
            transition_step(step, StepState.SUCCEEDED)
            for state in (WorkflowState.RUNNING, WorkflowState.COMPLETED):
                transition_workflow(
                    session,
                    value.submitted.workflow_id,
                    state,
                    "SYNTHETIC_WORKER_TEST",
                    actor_type="human",
                    actor_id=value.actor.operator_id,
                    command_id=None,
                )


@pytest.fixture
def concept_composition_store(concept_execution_store):
    """Real DB/Artifact chain and PNG decode; Graph ports and PLAN content are synthetic."""
    import tempfile
    from dataclasses import replace
    from pathlib import Path
    from unittest.mock import Mock

    from eom_catalog_service.kakao_concept_knowledge import KakaoConceptKnowledgeReader
    from eom_catalog_service.kakao_concept_pages import prepare_kakao_concept_pages
    from eom_catalog_service.kakao_concept_phase_results import read_kakao_concept_phase_result

    from tests.unit.test_kakao_concept_pages import knowledge

    value = concept_execution_store
    _complete_synthetic_concept_plan(value)
    authority = value.service.source_authority(
        value.actor, value.work.source_binding_id, value.work.task_id
    )
    completed = read_kakao_concept_phase_result(authority, "PLAN")
    assert completed.pin.job_id == value.worker.job_id
    textbook, png_bytes = knowledge()
    material = textbook.materials[0]
    original = next(
        member
        for member in material.analysis.source.materialization_members
        if member.member_kind == "PAGE_IMAGE"
    )
    artifacts = value.service.artifacts
    with tempfile.TemporaryDirectory(
        prefix="concept-book-fixture.", dir=artifacts.settings.staging_root
    ) as directory:
        source_path = Path(directory) / "page.png"
        source_path.write_bytes(png_bytes)
        publication = artifacts.commit_file_set(
            files={original.member_path: source_path},
            primary_file=original.member_path,
            artifact_type="synthetic-textbook-page",
            idempotency_key="concept-book-page-" + uuid4().hex,
            request={"sha256": original.sha256},
            result={},
            file_metadata={
                original.member_path: dict(
                    schema_ref=original.schema_ref, media_type=original.media_type
                )
            },
        )
    replacement = original.model_copy(
        update=dict(
            artifact_id=publication.artifact_id, artifact_revision_id=publication.revision_id
        )
    )
    source = material.analysis.source.model_copy(
        update=dict(
            chunk_manifests=(
                *material.analysis.source.chunk_manifests,
                material.analysis.source.chunk_manifests[0].model_copy(
                    update=dict(
                        artifact_id=publication.artifact_id,
                        artifact_revision_id=publication.revision_id,
                    )
                ),
            ),
            materialization_members=tuple(
                replacement if member == original else member
                for member in material.analysis.source.materialization_members
            ),
        )
    )
    material = replace(material, analysis=replace(material.analysis, source=source))
    textbook = replace(
        textbook,
        scope=authority.intent.scope,
        materials=(material,),
        snapshot=textbook.snapshot.model_copy(
            update=dict(
                graph_snapshot_revision_id=authority.intent.scope.snapshot.graph_snapshot_revision_id
            )
        ),
    )
    reader = Mock(spec=KakaoConceptKnowledgeReader)
    reader.retrieve.return_value = textbook
    reader.restore.return_value = textbook
    reader.prepare_pages.side_effect = (
        lambda _principal, _binding, knowledge, *, source_root, reauthorize_question: (
            prepare_kakao_concept_pages(
                artifacts,
                knowledge=knowledge,
                source_root=source_root,
                authorize=reauthorize_question,
            )
        )
    )
    value.service.knowledge_reader = reader
    return value, reader, replacement


def test_actual_phase_result_to_persisted_composition_and_restart_replay(
    concept_composition_store,
):
    from eom_protocol.artifact_members import ArtifactMemberPointer

    value, reader, replacement = concept_composition_store
    artifacts = value.service.artifacts
    work = value.service.prepare_compose(
        value.actor, value.work.source_binding_id, value.work.task_id
    )
    assert work.phase == "COMPOSE" and len(work.files) == 1
    expected = ArtifactMemberPointer.model_validate(
        replacement.model_dump(include=set(ArtifactMemberPointer.model_fields))
    )
    assert work.files[0].source == expected
    knowledge_pointer = artifacts.published_member_pointer(
        artifact_id=work.request_member.artifact_id,
        revision_id=work.request_member.artifact_revision_id,
        member_path="knowledge.json",
        schema_ref="eom://schemas/kakao-archive/concept-knowledge/1.0",
        media_type="application/json",
        max_bytes=2 * 1024 * 1024,
    )
    assert knowledge_pointer.artifact_revision_id == work.request_member.artifact_revision_id
    with Session(value.engine) as session:
        before = session.scalar(select(func.count()).select_from(ArtifactRevisionRecord))
    restored = KakaoConceptTaskService(
        value.engine,
        artifacts=artifacts,
        questions=value.service.questions,
        sources=value.service.sources,
        knowledge_reader=reader,
    )
    for _ in range(2):
        assert restored.prepare_compose(value.actor, work.source_binding_id, work.task_id) == work
    with Session(value.engine) as session:
        assert session.scalar(select(func.count()).select_from(ArtifactRevisionRecord)) == before
    reader.retrieve.assert_called_once()
    reader.prepare_pages.assert_called_once()
    with Session(value.engine) as session, session.begin():
        session.execute(
            update(ApiSessionRecord)
            .where(ApiSessionRecord.api_session_id == value.actor.session_id)
            .values(revoked_at=datetime.now(UTC))
        )
    background = restored.accepted_source_authority(
        task_id=work.task_id, operator_id=value.actor.operator_id
    )
    assert restored.prepare_accepted_compose(background) == work
    with pytest.raises(KakaoArchiveError):
        restored.get_task(value.actor, work.source_binding_id, work.task_id)
    from eom_catalog_service.kakao_concept_workflow_submission import (
        submit_accepted_kakao_concept_phase,
    )
    from eom_orchestrator.control_models import ExecutionPresetRevisionRecord
    from eom_workflow_runner.models import WorkflowDefinitionRecord

    with Session(value.engine, expire_on_commit=False) as session:
        plan_workflow = session.get(WorkflowInstanceRecord, value.submitted.workflow_id)
        definition = session.get(WorkflowDefinitionRecord, plan_workflow.definition_id)
        preset = ExecutionPresetRevision.model_validate(
            session.get(
                ExecutionPresetRevisionRecord, value.pinned.preset_revision_id
            ).canonical_document
        )
        session.expunge(definition)
    first = submit_accepted_kakao_concept_phase(
        background, work=work, definition=definition, expected_preset=preset
    )
    replay = submit_accepted_kakao_concept_phase(
        background, work=work, definition=definition, expected_preset=preset
    )
    assert first.workflow_id == replay.workflow_id and first.command_id == replay.command_id
    assert first.workflow_id != value.submitted.workflow_id
    reader.retrieve.assert_called_once()


@pytest.fixture
def concept_continuation_store(concept_composition_store, monkeypatch):
    from eom_catalog_service import kakao_concept_continuation as module

    value, *_ = concept_composition_store
    original = module.ready_kakao_concept_continuations
    # The guarded DB retains earlier synthetic histories. Limit this run to its fixture;
    # source authority, actual phase adoption and Workflow/command claims remain real.
    monkeypatch.setattr(
        module,
        "ready_kakao_concept_continuations",
        lambda *, after=None: original(after=after).where(
            KakaoConceptTaskRecord.task_id == value.work.task_id
        ),
    )
    return concept_composition_store


def test_automatic_continuation_survives_logout_and_restart_without_repeating_models(
    concept_continuation_store,
):
    from eom_catalog_service.kakao_concept_continuation import KakaoConceptCoordinator

    value, reader, _original = concept_continuation_store
    with Session(value.engine) as session, session.begin():
        session.execute(
            update(ApiSessionRecord)
            .where(ApiSessionRecord.api_session_id == value.actor.session_id)
            .values(revoked_at=datetime.now(UTC))
        )
    coordinator = KakaoConceptCoordinator(value.service)
    result = coordinator.advance_once()
    assert result.state == "SUBMITTED", result
    assert (
        result.task_id == value.work.task_id and result.workflow_id != value.submitted.workflow_id
    )
    assert coordinator.advance_once().state == "IDLE"
    assert KakaoConceptCoordinator(value.service).advance_once().state == "IDLE"
    reader.retrieve.assert_called_once()
    reader.prepare_pages.assert_called_once()
    with Session(value.engine) as session:
        parent = session.get(WorkflowInstanceRecord, value.submitted.workflow_id)
        child = session.get(WorkflowInstanceRecord, result.workflow_id)
        phase = session.get(KakaoConceptPhaseRecord, (value.work.task_id, "COMPOSE"))
        assert parent.state == "COMPLETED" and child.state == "REQUESTED"
        assert phase.workflow_id == child.workflow_id
        assert child.created_actor_id == value.actor.operator_id
        assert (
            session.scalar(
                select(func.count())
                .select_from(WorkflowCommandRecord)
                .where(WorkflowCommandRecord.workflow_id == child.workflow_id)
            )
            == 1
        )


def test_two_continuation_processes_submit_one_child_and_one_command(
    concept_continuation_store,
    monkeypatch,
):
    from eom_catalog_service import kakao_concept_continuation as module

    value, _reader, _original = concept_continuation_store
    original = module.read_kakao_concept_phase_result
    barrier = Barrier(2)

    def both_selected(*args):
        barrier.wait(timeout=10)
        return original(*args)

    monkeypatch.setattr(module, "read_kakao_concept_phase_result", both_selected)
    coordinators = [module.KakaoConceptCoordinator(value.service) for _ in range(2)]
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = tuple(pool.map(lambda coordinator: coordinator.advance_once(), coordinators))
    assert all(result.state == "SUBMITTED" for result in results), results
    assert results[0].workflow_id == results[1].workflow_id
    with Session(value.engine) as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(WorkflowCommandRecord)
                .where(WorkflowCommandRecord.workflow_id == results[0].workflow_id)
            )
            == 1
        )


def test_inactive_owner_does_not_advance_and_keeps_original_completed_plan(
    concept_continuation_store,
):
    from eom_catalog_service.kakao_concept_continuation import KakaoConceptCoordinator

    value, reader, _original = concept_continuation_store
    with Session(value.engine) as session, session.begin():
        session.execute(
            update(OperatorRecord)
            .where(OperatorRecord.operator_id == value.actor.operator_id)
            .values(status="DISABLED")
        )
    result = KakaoConceptCoordinator(value.service).advance_once()
    assert result.state == "ERROR" and result.error_code == "KAKAO_ARCHIVE_PERMISSION_DENIED"
    reader.retrieve.assert_not_called()
    with Session(value.engine) as session:
        assert session.get(KakaoConceptPhaseRecord, (value.work.task_id, "COMPOSE")) is None
        assert session.get(WorkflowInstanceRecord, value.submitted.workflow_id).state == "COMPLETED"


def publish_concept_successor(value):
    from eom_identifiers import content_sha256
    from eom_orchestrator.control_models import ExecutionPresetRevisionRecord
    from eom_orchestrator.control_service import (
        publish_execution_preset_revision,
        record_execution_preset_revision,
    )

    with Session(value.engine) as session, session.begin():
        previous = session.get(ExecutionPresetRevisionRecord, value.pinned.preset_revision_id)
        document = dict(previous.canonical_document)
        document.update(
            preset_revision_id="execpresetrev_" + uuid4().hex,
            revision_number=previous.revision_number + 1,
            description="Synthetic administrator update during accepted work",
        )
        document["content_sha256"] = content_sha256(
            {k: v for k, v in document.items() if k != "content_sha256"}
        )
        row = record_execution_preset_revision(
            session, preset_key="kakao-concepts", document=document, created_by="disposable-test"
        )
        publish_execution_preset_revision(
            session, preset_id=row.preset_id, preset_revision_id=row.preset_revision_id
        )


def test_start_replay_keeps_original_preset_and_workflow_after_admin_update(
    concept_execution_store,
):
    from eom_catalog_service.kakao_concept_workflow_submission import start_kakao_concept_task

    value = concept_execution_store
    with Session(value.engine) as session:
        row = session.get(KakaoConceptTaskRecord, value.work.task_id)
        key = row.idempotency_key
    _, intent = value.service.get_intent(
        value.actor, value.work.source_binding_id, value.work.task_id
    )
    initial, first = start_kakao_concept_task(
        value.service, actor=value.actor, command=intent.request, idempotency_key=key
    )
    assert initial.replayed and first.workflow_id == value.submitted.workflow_id
    publish_concept_successor(value)
    repeated, replay = start_kakao_concept_task(
        value.service, actor=value.actor, command=intent.request, idempotency_key=key
    )
    assert (
        repeated.replayed
        and replay.workflow_id == first.workflow_id
        and replay.command_id == first.command_id
    )
    assert not replay.workflow_created
    with Session(value.engine) as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(WorkflowCommandRecord)
                .where(WorkflowCommandRecord.workflow_id == first.workflow_id)
            )
            == 1
        )


def test_start_use_case_submits_a_new_plan_once_via_existing_owners(concept_execution_store):
    from eom_catalog_service.kakao_concept_workflow_submission import start_kakao_concept_task

    value = concept_execution_store
    _, intent = value.service.get_intent(
        value.actor, value.work.source_binding_id, value.work.task_id
    )
    key = "concept-start-new-" + uuid4().hex
    first, submitted = start_kakao_concept_task(
        value.service, actor=value.actor, command=intent.request, idempotency_key=key
    )
    replay, repeated = start_kakao_concept_task(
        value.service, actor=value.actor, command=intent.request, idempotency_key=key
    )
    assert not first.replayed and replay.replayed
    assert first.task.task_id == replay.task.task_id and first.task.task_id != value.work.task_id
    assert submitted.workflow_created and not repeated.workflow_created
    assert (
        submitted.workflow_id == repeated.workflow_id
        and submitted.command_id == repeated.command_id
    )
    with Session(value.engine) as session:
        phase = session.get(KakaoConceptPhaseRecord, (first.task.task_id, "PLAN"))
        assert phase.workflow_id == submitted.workflow_id


def test_current_change_refuses_auto_compose_without_latest_substitution(
    concept_continuation_store,
):
    from eom_catalog_service.kakao_concept_continuation import KakaoConceptCoordinator

    value, reader, _ = concept_continuation_store
    publish_concept_successor(value)
    result = KakaoConceptCoordinator(value.service).advance_once()
    assert result.state == "ERROR" and result.error_code == "CONTROL_PRESET_POINTER_STALE"
    reader.retrieve.assert_not_called()
    with Session(value.engine) as session:
        assert session.get(KakaoConceptPhaseRecord, (value.work.task_id, "COMPOSE")) is None
        assert session.get(WorkflowInstanceRecord, value.submitted.workflow_id).state == "COMPLETED"


def test_continuation_query_is_bounded_index_capable_and_waits_for_plan(concept_execution_store):
    from eom_catalog_service.kakao_concept_continuation import ready_kakao_concept_continuations

    value = concept_execution_store
    query = ready_kakao_concept_continuations().where(
        KakaoConceptTaskRecord.task_id == value.work.task_id
    )
    with Session(value.engine) as session, session.begin():
        assert session.execute(query).first() is None
        # Demonstrate the existing indexed path, not production throughput or planner preference.
        session.execute(text("SET LOCAL enable_seqscan = off"))
        compiled = str(
            query.compile(dialect=value.engine.dialect, compile_kwargs={"literal_binds": True})
        )
        explain = session.execute(text("EXPLAIN (FORMAT JSON) " + compiled)).scalar_one()[0]["Plan"]
        assert explain["Node Type"] == "Limit" and explain["Plan Rows"] <= 1
        pending = [explain]
        indexes = []
        while pending:
            node = pending.pop()
            if "Index Name" in node:
                indexes.append(node["Index Name"])
            pending.extend(node.get("Plans", ()))
        assert any("kakao_concept" in index for index in indexes)


@pytest.mark.parametrize("phase", ["intent", "plan"])
def test_stop_after_publication_recovers_same_identity_without_rewriting_history(
    concept_store, monkeypatch, phase
):
    service, actor, command, store = concept_store
    key = "concept-interrupted-" + uuid4().hex
    original = (
        publication.publish_kakao_concept_input
        if phase == "intent"
        else publication.prepare_kakao_concept_plan
    )
    saved = []

    def stopped(*args, **kwargs):
        saved.append(original(*args, **kwargs))
        raise RuntimeError("stopped after publication")

    name = "publish_kakao_concept_input" if phase == "intent" else "prepare_kakao_concept_plan"
    if phase == "plan":
        task = service.create_task(actor, command, idempotency_key=key).task
    monkeypatch.setattr(publication, name, stopped)
    with pytest.raises(RuntimeError, match="stopped after publication"):
        if phase == "intent":
            service.create_task(actor, command, idempotency_key=key)
        else:
            service.prepare_plan(actor, command.source_binding_id, task.task_id)
    monkeypatch.setattr(publication, name, original)
    if phase == "intent":
        repaired = service.create_task(actor, command, idempotency_key=key)
        assert repaired.replayed and repaired.task.intent == saved[0]
    else:
        repaired = service.prepare_plan(actor, command.source_binding_id, task.task_id)
        assert repaired == saved[0]
    pointer = saved[0] if phase == "intent" else saved[0].request_member
    with Session(store[0]) as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(ArtifactRevisionRecord)
                .where(ArtifactRevisionRecord.content_hash == pointer.sha256)
            )
            == 1
        )


def test_student_and_staff_photo_occurrences_share_original_binary_but_not_message_identity(
    question_store, source_store
):
    engine, actor, questions, initial, sources, artifacts, binding = question_store
    previous = sources.get_source(
        actor,
        initial.source_binding_id,
        initial.room_id,
        source_revision_id=initial.source_revision_id,
    ).resolution
    image = io.BytesIO()
    Image.new("RGB", (400, 300), "white").save(image, format="PNG")
    photo = image.getvalue()
    admission, _ = source_store[-1](
        previous=previous,
        texts=("photo question", "extra photo", "staff original answer"),
        roles=("student", "student", "staff"),
        photos={row: (photo, 400, 300) for row in (1, 2, 3)},
    )
    accepted = sources.admit_source(
        actor, admission, idempotency_key="concept-photo-source-" + uuid4().hex
    )
    created = questions.create_question(
        actor,
        initial.model_copy(update={"source_revision_id": accepted.resolution.source_revision_id}),
        idempotency_key="concept-photo-question-" + uuid4().hex,
    ).question
    service = KakaoConceptTaskService(
        engine,
        artifacts=artifacts,
        questions=questions,
        sources=sources,
        scope_provider=lambda *_: ChatRagScope.model_validate(scope_value()),
    )
    command = KakaoConceptCreate(
        source_binding_id=binding.source_binding_id,
        room_id=created.room_id,
        question_id=created.question_id,
        question_revision_id=created.question_revision_id,
        expected_question_version=created.resource_version,
        base_study_revision_id=None,
        additional_instructions="",
    )
    mutation = service.create_task(
        actor, command, idempotency_key="concept-photo-task-" + uuid4().hex
    )
    work = service.prepare_plan(actor, binding.source_binding_id, mutation.task.task_id)
    assert len(work.files) == 1
    pointer = work.request_member
    opened = artifacts.open_verified_member(
        artifact_id=pointer.artifact_id,
        revision_id=pointer.artifact_revision_id,
        member_path=pointer.member_path,
        sha256=pointer.sha256,
        schema_ref=pointer.schema_ref,
        media_type=pointer.media_type,
        max_bytes=262144,
    )
    with opened.stream as stream:
        request = validate_kakao_concept_request_bytes(work, stream.read())
    assert len(request.question.student.images) == 2
    assert len(request.question.staff.images) == 1
    assert (
        len(
            {
                image.source_occurrence_id
                for image in (*request.question.student.images, *request.question.staff.images)
            }
        )
        == 3
    )
    assert {
        image.value.member.relative_path
        for image in (*request.question.student.images, *request.question.staff.images)
    } == {work.files[0].relative_path}


def test_new_schema_roundtrip_is_empty_only_and_does_not_touch_existing_history(
    concept_store, monkeypatch
):
    service, actor, command, store = concept_store
    task = service.create_task(
        actor, command, idempotency_key="migration-proof-" + uuid4().hex
    ).task
    schema = "test_kakao_concept_" + uuid4().hex
    path = ROOT / "migrations/versions/20261117_0094_kakao_concept_tasks.py"
    spec = importlib.util.spec_from_file_location("concept_task_migration_test", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with store[0].connect() as connection:
        transaction = connection.begin()
        try:
            head = connection.scalar(text("SELECT version_num FROM app.alembic_version"))
            connection.execute(text(f"CREATE SCHEMA {schema}"))
            connection.execute(text(f"SET LOCAL search_path TO {schema}, app"))
            monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
            migration.upgrade()
            migration.downgrade()
            assert (
                connection.scalar(
                    text("SELECT to_regclass(:name)"), {"name": schema + ".kakao_concept_tasks"}
                )
                is None
            )
            migration.upgrade()
            # Only synthetic metadata is cloned into this rollback-only schema, not app history.
            columns = (
                "task_id,owner_operator_id,identity_session_id,source_binding_id,room_id,"
                "question_id,question_revision_id,question_version,idempotency_key,"
                "request_sha256,scope,created_at"
            )
            connection.execute(
                text(
                    f"INSERT INTO {schema}.kakao_concept_tasks ({columns}) "
                    f"SELECT {columns} FROM app.kakao_concept_tasks WHERE task_id = :task"
                ),
                {"task": task.task_id},
            )
            with (
                pytest.raises(DBAPIError, match="HISTORY_REQUIRES_REVIEW"),
                connection.begin_nested(),
            ):
                migration.downgrade()
            assert connection.scalar(text("SELECT version_num FROM app.alembic_version")) == head
            assert (
                connection.scalar(
                    text("SELECT count(*) FROM app.kakao_concept_tasks WHERE task_id = :task"),
                    {"task": task.task_id},
                )
                == 1
            )
        finally:
            transaction.rollback()
