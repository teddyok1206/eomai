"""Explicit retry lineage and races in the marker-guarded disposable PostgreSQL.

Only synthetic metadata is committed for concurrency fixtures. Model availability
is fake; no source authentication, files, worker, model or live DB is exercised.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Barrier
from typing import Any
from uuid import uuid4

import pytest
from eom_api.errors import ApiError
from eom_api.services.inference_transfer_retry import AuthorizedInferenceTransferRetry
from eom_api.services.inference_transfer_retry_adapter import (
    RETRY_CONTEXT,
    RETRY_EVENT,
    InferenceTransferRetryAdapter,
)
from eom_api.services.inference_transfer_start_adapter import InferenceTransferStartAdapter
from eom_catalog_contracts.inference_transfer_invocation_v11 import (
    InferenceTransferPairSubmitRequestV11,
)
from eom_catalog_contracts.inference_transfer_retry import InferenceTransferPairRetryRequestV1
from eom_identifiers import content_sha256
from eom_operator_identity import ActorContext
from eom_orchestrator import inference_transfer_resolution as resolution
from eom_orchestrator.control_models import (
    ExecutionPresetRecord,
    ExecutionPresetRevisionRecord,
    ExecutionPresetRolePolicyRecord,
    ResolvedExecutionPlanRecord,
)
from eom_orchestrator.models import JobRecord
from eom_orchestrator.repository import ensure_protocol_version
from eom_workflow.control_plane import ExecutionPresetRevision
from eom_workflow.inference_transfer import TRANSFER_PAIR_PROTOCOL_V11
from eom_workflow.inference_transfer_workflow import InferenceTransferWorkflowRequestV11
from eom_workflow.schemas import role_schema_bundle_hash
from eom_workflow_runner.models import (
    WorkflowCommandRecord,
    WorkflowDefinitionRecord,
    WorkflowEventRecord,
    WorkflowInstanceRecord,
    WorkflowStepRunRecord,
)
from eom_workflow_runner.repository import create_step_run
from eom_workflow_runner.state_machine import (
    CommandState,
    StepState,
    WorkflowStage,
    WorkflowState,
    transition_command,
    transition_stage,
    transition_step,
    transition_workflow,
)
from sqlalchemy import Connection, Engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from tests.integration.test_inference_transfer_api_submission_persistence import _actor, _submission
from tests.integration.test_inference_transfer_plan_persistence import _controls
from tests.integration.test_inference_transfer_stage_migration import (
    stage_owner_connection as stage_owner_connection,
)
from tests.unit.inference_transfer_fixtures import sha
from tests.unit.test_inference_transfer_workflow_v11 import _definition

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]


def _axes_controls(session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    _controls(session, monkeypatch)
    ensure_protocol_version(
        session, TRANSFER_PAIR_PROTOCOL_V11, role_schema_bundle_hash(TRANSFER_PAIR_PROTOCOL_V11)
    )
    logical = session.scalar(
        select(ExecutionPresetRecord).where(
            ExecutionPresetRecord.preset_key == resolution.AXES_PRESET_KEY
        )
    )
    if logical is not None:
        assert logical.created_by == "synthetic-transfer-retry"
        return
    old = session.scalar(
        select(ExecutionPresetRecord).where(
            ExecutionPresetRecord.preset_key == resolution.PRESET_KEY
        )
    )
    assert old is not None
    row = session.get(ExecutionPresetRevisionRecord, old.current_revision_id)
    assert row is not None
    body = dict(row.canonical_document)
    body.update(
        preset_id="execpreset_" + uuid4().hex,
        preset_revision_id="execpresetrev_" + uuid4().hex,
        compatible_workflow_protocols=[TRANSFER_PAIR_PROTOCOL_V11],
    )
    body.pop("content_sha256")
    preset = ExecutionPresetRevision.model_validate(body | {"content_sha256": content_sha256(body)})
    logical = ExecutionPresetRecord(
        preset_id=preset.preset_id,
        preset_key=resolution.AXES_PRESET_KEY,
        state="ACTIVE",
        created_by="synthetic-transfer-retry",
    )
    session.add(logical)
    session.flush()
    session.add(
        ExecutionPresetRevisionRecord(
            **{
                key: getattr(preset, key)
                for key in (
                    "preset_id",
                    "preset_revision_id",
                    "revision_number",
                    "schema_version",
                    "state",
                    "display_name",
                    "description",
                    "capacity_policy_revision_id",
                    "general_knowledge_policy",
                    "content_sha256",
                )
            },
            compatible_workflow_protocols=list(preset.compatible_workflow_protocols),
            canonical_document=preset.model_dump(mode="json"),
            created_by="synthetic-transfer-retry",
        )
    )
    session.flush()
    policy = preset.role_policies[0]
    session.add(
        ExecutionPresetRolePolicyRecord(
            preset_revision_id=preset.preset_revision_id,
            role=str(policy.role),
            model_candidates=[value.model_dump(mode="json") for value in policy.model_candidates],
            instruction_bundle_revision_id=policy.instruction_bundle.bundle_revision_id,
            reference_bundle_revision_id=None,
            worker_pool_key=policy.worker_pool_key,
            timeout_seconds=policy.timeout_seconds,
            sandbox=policy.sandbox,
            network=policy.network,
        )
    )
    session.flush()
    logical.current_revision_id = preset.preset_revision_id
    session.flush()


def _seed(connection: Connection | Engine, monkeypatch: pytest.MonkeyPatch) -> None:
    with (
        Session(bind=connection, join_transaction_mode="create_savepoint") as session,
        session.begin(),
    ):
        _axes_controls(session, monkeypatch)
        target = _definition()
        stored = session.scalar(
            select(WorkflowDefinitionRecord).where(
                WorkflowDefinitionRecord.definition_key == target.definition_key,
                WorkflowDefinitionRecord.definition_version == target.definition_version,
            )
        )
        if stored is None:
            session.add(target)
        else:
            assert stored.definition_hash == target.definition_hash


def _start_adapter(bind: Connection | Engine) -> InferenceTransferStartAdapter:
    adapter = object.__new__(InferenceTransferStartAdapter)
    adapter.sessions = sessionmaker(
        bind=bind, expire_on_commit=False, join_transaction_mode="create_savepoint"
    )
    return adapter


def _retry_adapter(bind: Connection | Engine) -> InferenceTransferRetryAdapter:
    adapter = object.__new__(InferenceTransferRetryAdapter)
    adapter.sessions = sessionmaker(
        bind=bind, expire_on_commit=False, join_transaction_mode="create_savepoint"
    )
    return adapter


def _failed_parent(
    bind: Connection | Engine, actor: ActorContext
) -> tuple[AuthorizedInferenceTransferRetry, int]:
    legacy = _submission(actor)
    body = legacy.workflow_request.model_dump(mode="json", exclude={"request_sha256"})
    body.update(
        schema_version="inference-transfer-workflow-request/1.1",
        request_name="ITEM_INFERENCE_TRANSFER_PAIR_REQUEST_V11",
        execution_preset_key=resolution.AXES_PRESET_KEY,
    )
    wrapper = InferenceTransferWorkflowRequestV11.model_validate(
        body | {"request_sha256": content_sha256(body)}
    )
    selected = legacy.selection.model_dump(mode="json", exclude={"submission_sha256"})
    selected["schema_version"] = "inference-transfer-pair-submit/1.1"
    selection = InferenceTransferPairSubmitRequestV11.model_validate(
        selected | {"submission_sha256": content_sha256(selected)}
    )
    submission = replace(legacy, workflow_request=wrapper, selection=selection)
    command_id, workflow_id, _ = _start_adapter(bind).start(
        submission, actor, idempotency_key="synthetic-retry-parent-" + uuid4().hex
    )
    with Session(bind=bind, join_transaction_mode="create_savepoint") as session, session.begin():
        command = session.get(WorkflowCommandRecord, command_id)
        assert command is not None
        transition_command(command, CommandState.CANCELLED)
        transition_workflow(
            session,
            workflow_id,
            WorkflowState.RUNNING,
            "SYNTHETIC_RUNNING",
            actor_type="system",
            actor_id="synthetic",
            command_id=None,
        )
        step = create_step_run(
            session,
            workflow_id=workflow_id,
            step_key="compare_pair",
            step_type="agent",
            worker_role="support",
            result_schema="item-inference-transfer-pair-result@1.1",
            input_pointer_manifest={"fixture_only": True},
            max_attempts=1,
        )
        transition_step(step, StepState.RUNNING)
        job = JobRecord(
            job_id="job_" + uuid4().hex,
            protocol_version=TRANSFER_PAIR_PROTOCOL_V11,
            idempotency_key="synthetic-retry-job-" + uuid4().hex,
            request_hash=sha("1"),
            task_type="synthetic_metadata_only",
            request={
                "workflow_id": workflow_id,
                "step_run_id": step.step_run_id,
                "attempt": 1,
                "role": "support",
            },
            status="FAILED",
            logical_artifact_id="artifact_" + uuid4().hex,
            revision_id="rev_" + uuid4().hex,
            error_code="WORKER_RESULT_INVALID",
            error_message="Synthetic original failure",
        )
        session.add(job)
        session.flush()
        step.platform_job_id = job.job_id
        transition_step(step, StepState.FAILED)
        step.error_code = "WORKFLOW_STEP_FAILED"
        step.error_summary = "Synthetic original failure"
        parent = transition_workflow(
            session,
            workflow_id,
            WorkflowState.FAILED,
            "SYNTHETIC_FAILED",
            actor_type="system",
            actor_id="synthetic",
            command_id=None,
        )
        transition_stage(
            session,
            workflow_id,
            WorkflowStage.FAILED,
            "compare_pair",
            "SYNTHETIC_STAGE_FAILED",
            actor_type="system",
            actor_id="synthetic",
            command_id=None,
        )
        parent.failure_code = "WORKFLOW_STEP_FAILED"
        parent.failure_summary = "Synthetic original failure"
        session.flush()
        request_body = {
            "schema_version": "inference-transfer-pair-retry/1.0",
            "failed_step_run_id": step.step_run_id,
            "failed_attempt": 1,
            "selection": selection.model_dump(mode="json"),
            "reason": "Retry corrected generation-only validation with exact original pins.",
        }
        request = InferenceTransferPairRetryRequestV1.model_validate(
            request_body | {"retry_sha256": content_sha256(request_body)}
        )
        return AuthorizedInferenceTransferRetry(
            workflow_id, request, submission
        ), parent.lock_version


def _history(session: Session, authorized: AuthorizedInferenceTransferRetry) -> tuple[Any, ...]:
    parent = session.get(WorkflowInstanceRecord, authorized.parent_workflow_id)
    step = session.get(WorkflowStepRunRecord, authorized.request.failed_step_run_id)
    assert parent is not None and step is not None
    job = session.get(JobRecord, step.platform_job_id)
    assert job is not None
    return (
        parent.state,
        parent.stage,
        parent.current_step_key,
        parent.completed_at,
        parent.failure_code,
        parent.failure_summary,
        dict(parent.initial_request),
        dict(parent.runtime_context),
        step.state,
        step.attempt,
        step.finished_at,
        step.error_code,
        step.error_summary,
        step.output_pointer_manifest,
        job.status,
        job.error_code,
        job.error_message,
    )


def test_successor_reuses_exact_controls_and_preserves_all_failed_history(
    stage_owner_connection: Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed(stage_owner_connection, monkeypatch)
    actor = _actor()
    authorized, version = _failed_parent(stage_owner_connection, actor)
    with Session(bind=stage_owner_connection, join_transaction_mode="create_savepoint") as session:
        before = _history(session, authorized)
    key = "synthetic-retry-" + uuid4().hex
    adapter = _retry_adapter(stage_owner_connection)
    first = adapter.retry(authorized, actor, expected_version=version, idempotency_key=key)
    assert first == adapter.retry(authorized, actor, expected_version=version, idempotency_key=key)
    with Session(bind=stage_owner_connection, join_transaction_mode="create_savepoint") as session:
        assert _history(session, authorized) == before
        parent = session.get(WorkflowInstanceRecord, authorized.parent_workflow_id)
        child = session.get(WorkflowInstanceRecord, first[1])
        assert parent is not None and child is not None
        assert parent.lock_version == version + 1
        assert child.state == "REQUESTED" and child.workflow_id != parent.workflow_id
        assert (
            child.definition_id == parent.definition_id
            and child.role_schema_version == TRANSFER_PAIR_PROTOCOL_V11
        )
        assert child.initial_request == parent.initial_request
        assert child.runtime_context[RETRY_CONTEXT]["parent_workflow_id"] == parent.workflow_id
        plans = {
            row.workflow_id: row.canonical_document
            for row in session.scalars(
                select(ResolvedExecutionPlanRecord).where(
                    ResolvedExecutionPlanRecord.workflow_id.in_(
                        [parent.workflow_id, child.workflow_id]
                    )
                )
            )
        }
        excluded = {
            "plan_id",
            "workflow_id",
            "resolved_at",
            "plan_sha256",
            "requester_permissions_sha256",
        }
        assert {k: v for k, v in plans[parent.workflow_id].items() if k not in excluded} == {
            k: v for k, v in plans[child.workflow_id].items() if k not in excluded
        }
        assert (
            session.scalar(
                select(func.count())
                .select_from(WorkflowEventRecord)
                .where(
                    WorkflowEventRecord.workflow_id == parent.workflow_id,
                    WorkflowEventRecord.event_type == RETRY_EVENT,
                )
            )
            == 1
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(WorkflowStepRunRecord)
                .where(WorkflowStepRunRecord.workflow_id == parent.workflow_id)
            )
            == 1
        )


@pytest.mark.parametrize("same_key", [True, False])
def test_concurrent_retries_create_one_successor_not_another_attempt(
    stage_owner_connection: Connection, monkeypatch: pytest.MonkeyPatch, same_key: bool
) -> None:
    # The entry fixture validates the owner/marker/head before any committed metadata.
    engine = stage_owner_connection.engine
    _seed(engine, monkeypatch)
    actor = _actor()
    authorized, version = _failed_parent(engine, actor)
    first_key = "synthetic-retry-race-" + uuid4().hex
    keys = (first_key, first_key if same_key else "synthetic-retry-race-" + uuid4().hex)
    barrier = Barrier(2)

    def run(key: str) -> tuple[str, str, int] | str:
        barrier.wait(timeout=10)
        try:
            return InferenceTransferRetryAdapter(engine).retry(
                authorized, actor, expected_version=version, idempotency_key=key
            )
        except ApiError as exc:
            return exc.error_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = tuple(pool.map(run, keys))
    successes = tuple(value for value in outcomes if isinstance(value, tuple))
    assert len(successes) == (2 if same_key else 1)
    assert len({value[1] for value in successes}) == 1
    if not same_key:
        assert "INFERENCE_TRANSFER_RETRY_CONFLICT" in outcomes
    with Session(engine) as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(WorkflowEventRecord)
                .where(
                    WorkflowEventRecord.workflow_id == authorized.parent_workflow_id,
                    WorkflowEventRecord.event_type == RETRY_EVENT,
                )
            )
            == 1
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(WorkflowStepRunRecord)
                .where(WorkflowStepRunRecord.workflow_id == authorized.parent_workflow_id)
            )
            == 1
        )


def test_stale_parent_version_rolls_back_without_child_or_lineage(
    stage_owner_connection: Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed(stage_owner_connection, monkeypatch)
    actor = _actor()
    authorized, version = _failed_parent(stage_owner_connection, actor)
    key = "synthetic-retry-stale-" + uuid4().hex
    with pytest.raises(ApiError, match="API_PRECONDITION_FAILED"):
        _retry_adapter(stage_owner_connection).retry(
            authorized, actor, expected_version=version - 1, idempotency_key=key
        )
    with Session(bind=stage_owner_connection, join_transaction_mode="create_savepoint") as session:
        assert (
            session.scalar(
                select(WorkflowInstanceRecord).where(WorkflowInstanceRecord.idempotency_key == key)
            )
            is None
        )
        assert (
            session.scalar(
                select(WorkflowEventRecord).where(
                    WorkflowEventRecord.workflow_id == authorized.parent_workflow_id,
                    WorkflowEventRecord.event_type == RETRY_EVENT,
                )
            )
            is None
        )
