from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from eom_api.services.mock_exam_production_coordinator import (
    MockExamProductionCoordinator,
    _advance_checkpoint,
    _workflow_request,
)
from eom_api_contracts.mock_exam_execution import MockExamGenerationBlockResolutionV1
from eom_catalog_contracts import (
    EducationalRetrievalRequirement,
    build_integrated_science_mock_exam_production_plan,
    load_integrated_science_editorial_outline,
    load_integrated_science_mock_exam_layout_policy,
    load_integrated_science_mock_exam_policy,
    resolve_integrated_science_curriculum_scope,
)
from eom_catalog_contracts.mock_exam_production_plan import (
    MockExamPlannedWorkflowCallV1,
    MockExamProductionPlanV1,
)
from eom_identifiers import (
    content_sha256,
    new_job_id,
    new_logical_artifact_id,
    new_revision_id,
)
from eom_operator_identity import ActorContext, ActorSource, ActorType
from eom_orchestrator.database import build_session_factory, transaction
from eom_orchestrator.models import JobEventRecord, JobRecord
from eom_workflow.identifiers import new_step_run_id, new_workflow_id
from eom_workflow.models import ArtifactSpec, RoleWorkerInput, WorkflowRequest
from eom_workflow_runner.mock_exam_production_retirement import (
    MockExamProductionRetirementError,
    MockExamProductionRetirementService,
)
from eom_workflow_runner.models import (
    WorkflowCommandRecord,
    WorkflowDefinitionRecord,
    WorkflowEventRecord,
    WorkflowInstanceRecord,
    WorkflowStepRunRecord,
)
from eom_workflow_runner.repository import (
    CommandType,
    enqueue_command,
    workflow_request_storage_document,
)
from eom_workflow_runner.retirement_quiescence import (
    WORKFLOW_RUNNER_DEPLOYMENT_HOLD_DIRECTORY,
    WORKFLOW_RUNNER_DEPLOYMENT_HOLD_PATH,
    WORKFLOW_RUNNER_DEPLOYMENT_HOLD_SHA256,
    WORKFLOW_RUNNER_FRAGMENT_PATH,
    WorkflowRunnerQuiescenceEvidence,
)
from eom_workflow_runner.state_machine import (
    CommandState,
    WorkflowStage,
    WorkflowState,
    record_initial_workflow_event,
    record_workflow_event,
    transition_stage,
    transition_workflow,
)
from sqlalchemy import Engine, delete, select
from sqlalchemy import event as sqlalchemy_event

pytestmark = pytest.mark.integration
NOW = datetime(2026, 9, 8, 3, 4, 5, tzinfo=UTC)
OPERATOR_ID = "operator_" + "a" * 32
PRODUCTION_REQUEST_ID = "productionreq_" + "b" * 32


def _plan():
    return build_integrated_science_mock_exam_production_plan(
        policy=load_integrated_science_mock_exam_policy(),
        layout_policy=load_integrated_science_mock_exam_layout_policy(),
        outline=load_integrated_science_editorial_outline(),
    )


def _resolution(plan) -> MockExamGenerationBlockResolutionV1:
    block = plan.one_item_generation_block
    return MockExamGenerationBlockResolutionV1(
        generation_block_key=block.block_key,
        generation_block_revision=block.block_revision,
        generation_block_sha256=block.block_sha256,
        workflow_definition_key=block.workflow_definition_key,
        workflow_definition_version=block.workflow_definition_version,
        workflow_definition_sha256="sha256:" + "1" * 64,
        content_pack_release_id="packrel_" + "2" * 32,
        content_pack_key=block.content_pack_key,
        content_pack_version=block.content_pack_version,
        content_pack_release_sha256="sha256:" + "3" * 64,
        content_pack_source_tree_sha256=block.content_pack_source_tree_sha256,
        execution_preset_id="execpreset_" + "4" * 32,
        execution_preset_revision_id="execpresetrev_" + "5" * 32,
        execution_preset_key=block.execution_preset_key,
        execution_preset_sha256="sha256:" + "6" * 64,
        resolved_at=NOW,
    )


def _actor() -> ActorContext:
    return ActorContext(
        actor_type=ActorType.OPERATOR,
        operator_id=OPERATOR_ID,
        session_id="apisession_" + "c" * 32,
        request_id="retirement-integration-test",
        authentication_time=NOW,
        permissions=frozenset(),
        source=ActorSource.CLI,
    )


class _HeldRunner:
    @staticmethod
    def observe() -> WorkflowRunnerQuiescenceEvidence:
        return WorkflowRunnerQuiescenceEvidence(
            load_state="loaded",
            active_state="inactive",
            sub_state="dead",
            main_pid=0,
            unit_file_state="enabled",
            job="",
            fragment_path=WORKFLOW_RUNNER_FRAGMENT_PATH,
            drop_in_paths=(WORKFLOW_RUNNER_DEPLOYMENT_HOLD_PATH,),
            refuse_manual_start=True,
            need_daemon_reload=False,
            hold_directory_path=WORKFLOW_RUNNER_DEPLOYMENT_HOLD_DIRECTORY,
            hold_directory_owner_uid=0,
            hold_directory_group_gid=0,
            hold_directory_mode=0o755,
            hold_path=WORKFLOW_RUNNER_DEPLOYMENT_HOLD_PATH,
            hold_sha256=WORKFLOW_RUNNER_DEPLOYMENT_HOLD_SHA256,
            hold_owner_uid=0,
            hold_group_gid=0,
            hold_mode=0o644,
        )


class _NoHeldLeases:
    @staticmethod
    def reconcile_expired_for_workflows(
        workflow_ids: tuple[str, ...],
        *,
        observed_at: datetime,
    ) -> tuple[object, ...]:
        assert len(workflow_ids) == 25
        assert observed_at.tzinfo is not None
        return ()


def _require_explicit_ephemeral_database(engine: Engine) -> None:
    if os.environ.get("EOM_RUN_RETIREMENT_MUTATION_INTEGRATION") != "1":
        pytest.skip("set EOM_RUN_RETIREMENT_MUTATION_INTEGRATION=1 for this mutation test")
    expected = os.environ.get("EOM_RETIREMENT_EPHEMERAL_DATABASE")
    database = engine.url.database
    if (
        not expected
        or database != expected
        or expected.casefold() in {"eom", "postgres", "template0", "template1"}
    ):
        pytest.fail("retirement integration requires an explicitly named disposable database")


def _persisted_request(
    call: MockExamPlannedWorkflowCallV1,
    plan: MockExamProductionPlanV1,
    resolution: MockExamGenerationBlockResolutionV1,
) -> WorkflowRequest:
    api_request = _workflow_request(
        call,
        plan.one_item_generation_block,
        resolution,
        PRODUCTION_REQUEST_ID,
    )
    assert api_request.item_brief is not None
    selected = api_request.item_brief.curriculum_selected_unit_key
    assert selected is not None
    scope = resolve_integrated_science_curriculum_scope(selected)
    brief = api_request.item_brief.model_dump(mode="json")
    brief.pop("curriculum_selected_unit_key")
    brief["curriculum_scope"] = scope.model_dump(mode="json")
    assert api_request.educational_retrieval is not None
    retrieval = api_request.educational_retrieval.model_dump(mode="json")
    retrieval["curriculum_root_key"] = scope.graph_root_stable_key
    retrieval["topic_keys"] = []
    retrieval = EducationalRetrievalRequirement.model_validate(retrieval).model_dump(mode="json")
    assert api_request.pack_key is not None
    assert api_request.production_occurrence is not None
    assert api_request.expected_resolution is not None
    return WorkflowRequest.model_validate(
        {
            "request_name": api_request.request_name,
            "image_mode": api_request.image_mode,
            "content_pack": {
                "pack_key": api_request.pack_key,
                "environment": api_request.environment,
            },
            "profiles": {
                "authoring": "generated-knowledge-authoring",
                "review": "generated-knowledge-review",
                "image": (
                    None if api_request.image_mode == "skip" else "generated-stimulus-drawing"
                ),
                "registration": "generated-structured-registration",
            },
            "source_intake": {"batch_ids": list(api_request.source_intake_batch_ids)},
            "registry_intent": {
                "mode": api_request.registry_mode,
                "item_id": api_request.item_id,
                "base_revision_id": api_request.base_revision_id,
            },
            "item_brief": brief,
            "execution_preset_key": api_request.execution_preset_key,
            "educational_retrieval": retrieval,
            "production_occurrence": api_request.production_occurrence.model_dump(mode="json"),
            "expected_resolution": api_request.expected_resolution.model_dump(mode="json"),
        }
    )


def test_exact_occurrence_retirement_fences_start_commands_and_jobs_atomically(
    integration_engine: Engine,
) -> None:
    _require_explicit_ephemeral_database(integration_engine)
    sessions = build_session_factory(integration_engine)
    suffix = uuid4().hex
    workflow_ids: list[str] = []
    start_ids: list[str] = []
    job_id: str | None = None
    plan = _plan()
    resolution = _resolution(plan)
    checkpoint = MockExamProductionCoordinator.initialize(
        plan,
        production_request_id=PRODUCTION_REQUEST_ID,
        operator_id=OPERATOR_ID,
        at=NOW,
    )
    with sessions() as session:
        definition = session.scalar(
            select(WorkflowDefinitionRecord).where(
                WorkflowDefinitionRecord.definition_key
                == plan.one_item_generation_block.workflow_definition_key,
                WorkflowDefinitionRecord.definition_version
                == plan.one_item_generation_block.workflow_definition_version,
            )
        )
        if definition is None:
            pytest.skip("ephemeral database lacks the pinned Workflow definition")
        definition_id = definition.definition_id
    try:
        with transaction(sessions) as session:
            for position, call in enumerate(plan.workflow_calls, start=1):
                request = _persisted_request(call, plan, resolution)
                document = workflow_request_storage_document(request)
                workflow_id = new_workflow_id()
                workflow = WorkflowInstanceRecord(
                    workflow_id=workflow_id,
                    definition_id=definition_id,
                    definition_key=plan.one_item_generation_block.workflow_definition_key,
                    definition_version=plan.one_item_generation_block.workflow_definition_version,
                    definition_hash=resolution.workflow_definition_sha256,
                    protocol_version="1.0.1",
                    role_schema_version="workflow-role/1.18.0",
                    state=WorkflowState.REQUESTED.value,
                    stage=WorkflowStage.AUTHORING.value,
                    current_step_key="authoring",
                    request_payload=document,
                    initial_request=document,
                    runtime_context={"artifact_pointers": []},
                    idempotency_key=f"retirement-test:{suffix}:{position}",
                    request_hash=content_sha256({"suffix": suffix, "position": position}),
                    lock_version=1,
                    rework_cycle_count=0,
                    created_actor_type="human",
                    created_actor_id=OPERATOR_ID,
                )
                session.add(workflow)
                session.flush()
                record_initial_workflow_event(
                    session,
                    workflow,
                    actor_type="human",
                    actor_id=OPERATOR_ID,
                )
                start, created = enqueue_command(
                    session,
                    workflow_id=workflow_id,
                    command_type=CommandType.START_WORKFLOW,
                    payload={},
                    actor_type="human",
                    actor_id=OPERATOR_ID,
                    source="integration_test",
                    idempotency_key=f"start:{workflow_id}",
                )
                assert created
                workflow_ids.append(workflow_id)
                start_ids.append(start.command_id)

                if position == 1:
                    transition_workflow(
                        session,
                        workflow_id,
                        WorkflowState.RUNNING,
                        "WORKFLOW_STARTED",
                        actor_type="human",
                        actor_id=OPERATOR_ID,
                        command_id=start.command_id,
                        step_key="authoring",
                    )
                    job_id = new_job_id()
                    step_run_id = new_step_run_id()
                    logical_artifact_id = new_logical_artifact_id()
                    revision_id = new_revision_id()
                    job_protocol = "workflow-role/1.18.0"
                    job_task_type = "workflow_authoring"
                    job_request = RoleWorkerInput(
                        protocol_version=job_protocol,
                        job_id=job_id,
                        workflow_id=workflow_id,
                        step_run_id=step_run_id,
                        attempt=1,
                        role="authoring",
                        request=request,
                        upstream_artifacts=(),
                        artifact=ArtifactSpec(
                            logical_artifact_id=logical_artifact_id,
                            revision_id=revision_id,
                        ),
                    ).model_dump(mode="json")
                    session.add(
                        JobRecord(
                            job_id=job_id,
                            protocol_version=job_protocol,
                            idempotency_key=f"retirement-job:{suffix}",
                            request_hash=content_sha256(
                                {
                                    "protocol_version": job_protocol,
                                    "task_type": job_task_type,
                                    "request": job_request,
                                }
                            ),
                            task_type=job_task_type,
                            request=job_request,
                            status="QUEUED",
                            logical_artifact_id=logical_artifact_id,
                            revision_id=revision_id,
                        )
                    )
                    session.flush()
                    for sequence, prior, target, event in (
                        (1, None, "CREATED", "JOB_CREATED"),
                        (2, "CREATED", "VALIDATED", "REQUEST_VALIDATED"),
                        (3, "VALIDATED", "QUEUED", "JOB_QUEUED"),
                    ):
                        session.add(
                            JobEventRecord(
                                job_id=job_id,
                                sequence=sequence,
                                from_state=prior,
                                to_state=target,
                                event=event,
                                data={},
                            )
                        )
                    session.add(
                        WorkflowStepRunRecord(
                            step_run_id=step_run_id,
                            workflow_id=workflow_id,
                            step_key="authoring",
                            attempt=1,
                            step_type="agent",
                            worker_role="authoring",
                            result_schema="authoring-result@9.0",
                            state="RUNNING",
                            platform_job_id=job_id,
                            input_pointer_manifest={},
                        )
                    )
                elif position == 25:
                    workflow.failure_code = "WORKFLOW_STEP_FAILED"
                    workflow.failure_summary = "sanitized test failure"
                    transition_stage(
                        session,
                        workflow_id,
                        WorkflowStage.FAILED,
                        "authoring",
                        "WORKFLOW_FAILURE_STAGE_ENTERED",
                        actor_type="system",
                        actor_id="integration-test",
                        command_id=start.command_id,
                    )
                    transition_workflow(
                        session,
                        workflow_id,
                        WorkflowState.FAILED,
                        "WORKFLOW_FAILED",
                        actor_type="system",
                        actor_id="integration-test",
                        command_id=start.command_id,
                        step_key="authoring",
                    )

            item_runs = tuple(
                row.model_copy(
                    update={
                        "state": "WORKFLOW_ACTIVE",
                        "start_command_id": start_ids[row.position - 1],
                        "workflow_id": workflow_ids[row.position - 1],
                        "workflow_resource_version": 1,
                    }
                )
                for row in checkpoint.item_runs
            )
            checkpoint = _advance_checkpoint(
                checkpoint,
                at=NOW + timedelta(seconds=1),
                generation_block_resolution=resolution,
                item_runs=item_runs,
            )

        service = MockExamProductionRetirementService(
            integration_engine,
            quiescence=_HeldRunner(),
            lease_reconciler=_NoHeldLeases(),
        )
        with service._sessions() as session:
            prepared = service._prepare_command(
                session,
                checkpoint=checkpoint,
                retirement_id=(
                    "productionretire_"
                    + content_sha256(
                        {
                            "schema_version": ("mock-exam-production-retirement-identity/1.0"),
                            "execution_id": checkpoint.execution_id,
                            "execution_revision_id": checkpoint.execution_revision_id,
                            "checkpoint_sha256": checkpoint.checkpoint_sha256,
                            "reason_code": "SUPERSEDED_BY_CORRECTED_PROTOCOL",
                        }
                    ).removeprefix("sha256:")[:32]
                ),
                at=NOW + timedelta(seconds=30),
            )
        with transaction(sessions) as session:
            record_workflow_event(
                session,
                workflow_ids[1],
                "TEST_CONCURRENT_CHANGE",
                actor_type="system",
                actor_id="integration-test",
                command_id=None,
            )
        with pytest.raises(
            MockExamProductionRetirementError,
            match="changed after retirement preparation",
        ) as conflict:
            service._execute(prepared, checkpoint=checkpoint)
        assert conflict.value.code == "PRODUCTION_RETIREMENT_WORKFLOW_CAS_MISMATCH"
        with sessions() as session:
            assert {
                row.state
                for row in session.scalars(
                    select(WorkflowCommandRecord).where(
                        WorkflowCommandRecord.command_id.in_(start_ids)
                    )
                )
            } == {CommandState.PENDING.value}

        updated_workflow_event_ids: list[int] = []

        def observe_workflow_event_update(
            _mapper: object,
            _connection: object,
            target: WorkflowEventRecord,
        ) -> None:
            updated_workflow_event_ids.append(target.event_id)

        sqlalchemy_event.listen(
            WorkflowEventRecord,
            "before_update",
            observe_workflow_event_update,
        )
        try:
            receipt = service.retire(checkpoint, _actor(), at=NOW + timedelta(minutes=1))

            replay = service.retire(
                checkpoint,
                _actor(),
                at=NOW + timedelta(minutes=2),
            )
        finally:
            sqlalchemy_event.remove(
                WorkflowEventRecord,
                "before_update",
                observe_workflow_event_update,
            )

        assert len(receipt.outcomes) == 25
        assert sum(row.disposition == "CANCEL_QUEUED" for row in receipt.outcomes) == 24
        assert (
            sum(row.disposition == "UNSUCCESSFUL_TERMINAL_PRESERVED" for row in receipt.outcomes)
            == 1
        )
        assert replay == receipt
        assert updated_workflow_event_ids == []

        with sessions() as session:
            starts = tuple(
                session.scalars(
                    select(WorkflowCommandRecord).where(
                        WorkflowCommandRecord.command_id.in_(start_ids)
                    )
                )
            )
            assert len(starts) == 25
            assert {row.state for row in starts} == {CommandState.CANCELLED.value}
            active_commands = tuple(
                session.scalars(
                    select(WorkflowCommandRecord).where(
                        WorkflowCommandRecord.workflow_id.in_(workflow_ids),
                        WorkflowCommandRecord.state.in_(
                            (
                                CommandState.PENDING.value,
                                CommandState.LEASED.value,
                                CommandState.PROCESSING.value,
                            )
                        ),
                    )
                )
            )
            assert len(active_commands) == 24
            assert {row.command_type for row in active_commands} == {
                CommandType.CANCEL_WORKFLOW.value
            }
            assert all(
                row.payload["retirement_id"] == receipt.retirement_id for row in active_commands
            )
            audits = tuple(
                session.scalars(
                    select(WorkflowEventRecord).where(
                        WorkflowEventRecord.workflow_id.in_(workflow_ids),
                        WorkflowEventRecord.event_type
                        == "WORKFLOW_PRODUCTION_RETIREMENT_REQUESTED",
                    )
                )
            )
            assert len(audits) == 25
            outcomes_by_workflow = {row.workflow_id: row for row in receipt.outcomes}
            assert all(
                event.payload["retirement_workflow_resource_version"]
                == outcomes_by_workflow[event.workflow_id].retirement_workflow_resource_version
                for event in audits
            )
            assert job_id is not None
            job = session.get(JobRecord, job_id)
            assert job is not None and job.status == "CANCELLED"
            assert (
                session.scalar(
                    select(JobEventRecord.event).where(
                        JobEventRecord.job_id == job_id,
                        JobEventRecord.event == "PRODUCTION_OCCURRENCE_RETIRED",
                    )
                )
                == "PRODUCTION_OCCURRENCE_RETIRED"
            )
    finally:
        with transaction(sessions) as session:
            if workflow_ids:
                session.execute(
                    delete(WorkflowInstanceRecord).where(
                        WorkflowInstanceRecord.workflow_id.in_(workflow_ids)
                    )
                )
            if job_id is not None:
                session.execute(delete(JobRecord).where(JobRecord.job_id == job_id))
