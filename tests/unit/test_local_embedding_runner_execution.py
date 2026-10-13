"""Synthetic native control/transaction gates, never runtime or current authority evidence."""

from __future__ import annotations

import copy
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import Mock

import pytest
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_operator_identity import PermissionKey
from eom_workflow.compiler import CompiledWorkflowDefinition, compile_definition
from eom_workflow.local_embedding_encoding_job import EmbeddingEncodingReadResult
from eom_workflow.local_embedding_workflow_receipt import (
    LocalEmbeddingStepOutput,
    LocalEmbeddingWorkflowReceipt,
    validate_local_embedding_step_output,
    validate_local_embedding_workflow_receipt,
)
from eom_workflow_runner.actor_authorization import (
    WorkflowActorAuthorization,
    WorkflowActorNamespace,
)
from eom_workflow_runner.engine import WorkflowRunner
from eom_workflow_runner.errors import WorkflowError, WorkflowErrorCode
from eom_workflow_runner.local_embedding_admission import (
    LocalEmbeddingOwnerAdmission,
    ResolvedLocalEmbeddingAdmission,
)
from eom_workflow_runner.local_embedding_execution_port import (
    LocalEmbeddingNativeExecutor,
    LocalEmbeddingStepPending,
)
from eom_workflow_runner.local_embedding_step_execution import (
    advance_local_embedding_step,
    complete_local_embedding_terminal,
    native_fenced_runner_transaction,
)
from eom_workflow_runner.models import (
    ApprovalRequestRecord,
    WorkflowCommandRecord,
    WorkflowDefinitionRecord,
    WorkflowEventRecord,
    WorkflowInstanceRecord,
    WorkflowStepRunRecord,
)
from eom_workflow_runner.readiness import (
    ReadinessStatus,
    RuntimeReadinessCheck,
    RuntimeReadinessReport,
    WorkflowRuntimeNotReady,
)
from eom_workflow_runner.repository import CommandExecutionFamily, CommandLeaseIdentity
from sqlalchemy.orm import Session, sessionmaker

from tests.unit.embedding_encoding_reservation_fixtures import read_result
from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.local_embedding_admission_fixtures import native_fixture
from tests.unit.local_embedding_workflow_receipt_fixtures import receipt_fixture
from tests.unit.test_local_embedding_command_claim import candidate_fixture, peek
from tests.unit.test_local_embedding_runner_admission import scope_fixture


@dataclass
class SyntheticExecution:
    scope: ResolvedLocalEmbeddingAdmission
    compiled: CompiledWorkflowDefinition
    workflow: WorkflowInstanceRecord
    step: WorkflowStepRunRecord
    session: Mock
    owner: Mock
    executor: Mock
    output: LocalEmbeddingStepOutput
    receipt: LocalEmbeddingWorkflowReceipt
    lease: CommandLeaseIdentity
    rows: list[Any]
    depth: int = 0
    roots: int = 0
    deny_at_exit: int | None = None

    @contextmanager
    def fenced(self) -> Iterator[Session]:
        assert self.depth == 0
        self.roots += 1
        self.depth += 1
        snapshots = [
            (
                row,
                {
                    column.name: copy.deepcopy(getattr(row, column.name))
                    for column in row.__table__.columns
                },
            )
            for row in self.rows
        ]
        original_length = len(self.rows)
        try:
            yield cast(Session, self.session)
            if self.deny_at_exit == self.roots:
                raise WorkflowError(
                    WorkflowErrorCode.WORKFLOW_CONCURRENCY_CONFLICT, "synthetic late owner revoked"
                )
        except Exception:
            for row, values in snapshots:
                for name, value in values.items():
                    setattr(row, name, value)
            del self.rows[original_length:]
            raise
        finally:
            self.depth -= 1

    def advance(self) -> bool:
        return advance_local_embedding_step(
            workflow=self.workflow,
            compiled=self.compiled,
            request=self.scope.request,
            lease=self.lease,
            owner=cast(LocalEmbeddingOwnerAdmission, self.owner),
            executor=cast(LocalEmbeddingNativeExecutor, self.executor),
            fenced_transaction=self.fenced,
            poll_interval_seconds=1,
            actor_type="human",
            actor_id=self.workflow.created_actor_id,
        )

    def complete(self) -> None:
        complete_local_embedding_terminal(
            workflow_id=self.workflow.workflow_id,
            request=self.scope.request,
            lease=self.lease,
            executor=cast(LocalEmbeddingNativeExecutor, self.executor),
            fenced_transaction=self.fenced,
            actor_type="human",
            actor_id=self.workflow.created_actor_id,
        )


def execution_fixture() -> SyntheticExecution:
    scope, compiled = scope_fixture()
    original = receipt_fixture(borrowed_only=True, historical=True)
    receipt = LocalEmbeddingWorkflowReceipt.model_validate(
        seal(
            original.receipt.model_dump(mode="json")
            | {
                "workflow_definition_sha256": scope.request.workflow_definition_sha256,
                "workflow_request_sha256": scope.request.request_sha256,
            },
            "receipt_sha256",
        )
    )
    output = LocalEmbeddingStepOutput.model_validate(
        seal(
            original.output.model_dump(mode="json")
            | {
                "receipt_sha256": receipt.receipt_sha256,
                "receipt": original.output.receipt.model_dump(mode="json")
                | {"sha256": sha256_bytes(canonical_json_bytes(receipt.model_dump(mode="json")))},
            },
            "output_sha256",
        )
    )
    workflow = WorkflowInstanceRecord(
        workflow_id=output.workflow_id,
        definition_key="local-embedding-index",
        definition_version="1.0.0",
        definition_id="wfdef_" + "1" * 32,
        definition_hash=compiled.sha256,
        protocol_version="1.0.1",
        role_schema_version="local-embedding/1.0",
        initial_request=scope.request.model_dump(mode="json"),
        request_payload=scope.request.model_dump(mode="json"),
        current_step_key="encode_batch",
        state="REQUESTED",
        stage="LOCAL_EMBEDDING",
        runtime_context={},
        lock_version=1,
        created_actor_type="human",
        created_actor_id="operator_" + "1" * 32,
    )
    step = WorkflowStepRunRecord(
        step_run_id=output.step_run_id,
        workflow_id=workflow.workflow_id,
        step_key="encode_batch",
        attempt=1,
        step_type="application",
        worker_role=None,
        result_schema="incremental-embedding-result@1.0",
        state="READY",
        input_pointer_manifest={
            "source_plan": scope.request.source_plan.model_dump(mode="json"),
            "source_plan_sha256": scope.request.source_plan_sha256,
        },
    )
    session, owner, executor = (
        Mock(spec=Session),
        Mock(spec=LocalEmbeddingOwnerAdmission),
        Mock(spec=LocalEmbeddingNativeExecutor),
    )
    fixture = SyntheticExecution(
        scope,
        compiled,
        workflow,
        step,
        session,
        owner,
        executor,
        output,
        receipt,
        CommandLeaseIdentity("wfcmd_" + "3" * 32, "synthetic-native", "wflease_" + "4" * 32, 1),
        [workflow, step],
    )

    def get(model: Any, identity: str) -> Any:
        return next(
            (
                row
                for row in fixture.rows
                if isinstance(row, model)
                and (row.workflow_id if model is WorkflowInstanceRecord else row.step_run_id)
                == identity
            ),
            None,
        )

    def scalar(query: Any) -> Any:
        model = query.column_descriptions[0]["entity"]
        if model is WorkflowStepRunRecord:
            if query.column_descriptions[0]["name"] == "coalesce":
                return 0
            parameters = query.compile().params
            key = parameters.get("step_key_1")
            if parameters.get("state_1") == "SUPERSEDED":
                return None
            return next(
                (
                    row
                    for row in fixture.rows
                    if isinstance(row, WorkflowStepRunRecord) and row.step_key == key
                ),
                None,
            )
        if model is WorkflowCommandRecord:
            return None
        if model is WorkflowEventRecord:
            return 1 + sum(isinstance(row, WorkflowEventRecord) for row in fixture.rows)
        raise AssertionError(f"unexpected synthetic query model {model}")

    def execute(**_kwargs: Any) -> Any:
        assert fixture.depth == 0, "inference must not execute within SQL/source fences"
        return fixture.output

    def completion(**kwargs: Any) -> LocalEmbeddingStepOutput:
        assert fixture.depth == 1
        validate_local_embedding_workflow_receipt(
            fixture.receipt,
            fixture.scope.request,
            fixture.scope.plan,
            fixture.scope.policy,
            workflow_id=fixture.workflow.workflow_id,
            step_run_id=fixture.step.step_run_id,
            receipt_owner_job_id=fixture.output.receipt_owner_job_id,
            launch_association=None,
            owned_input=None,
        )
        return validate_local_embedding_step_output(kwargs["output"], fixture.receipt)

    session.get.side_effect = get
    session.scalar.side_effect = scalar
    session.execute.return_value.scalar_one_or_none.return_value = workflow

    def add(row: Any) -> None:
        if isinstance(row, WorkflowStepRunRecord):
            row.platform_job_id = row.output_pointer_manifest = None
        fixture.rows.append(row)

    session.add.side_effect = add
    owner.resolve_submission.return_value = scope
    executor.execute.side_effect = execute
    executor.validate_completion.side_effect = completion
    return fixture


def pending_fixture(
    fixture: SyntheticExecution, *, borrowed: bool = False
) -> LocalEmbeddingStepPending:
    native = native_fixture()
    intent_body = native.association.intent.model_dump(mode="json") | {
        "workflow_request_sha256": fixture.scope.request.request_sha256
    }
    if borrowed:
        intent_body["workflow_id"] = "workflow_" + "d" * 32
        intent_body["step_run_id"] = "steprun_" + "d" * 32
    intent = type(native.association.intent).model_validate(seal(intent_body, "intent_sha256"))
    readings = []
    for job in native.association.owned_jobs:
        row = read_result(job, intent)
        if borrowed:
            row = EmbeddingEncodingReadResult.model_validate(
                seal(row.model_dump(mode="json") | {"status": "BORROWED"}, "read_sha256")
            )
        readings.append(row)
    return LocalEmbeddingStepPending(tuple(readings))


def test_success_and_terminal_resolve_exact_carrier_twice_without_generic_artifact() -> None:
    fixture = execution_fixture()
    assert fixture.advance() is True
    assert fixture.step.state == "SUCCEEDED" and fixture.workflow.current_step_key == "complete"
    assert fixture.step.platform_job_id == fixture.output.receipt_owner_job_id
    assert fixture.step.output_pointer_manifest == fixture.output.model_dump(mode="json")
    fixture.complete()
    assert fixture.workflow.state == fixture.workflow.stage == "COMPLETED"
    assert (
        fixture.executor.execute.call_count == 1
        and fixture.executor.validate_completion.call_count == 2
    )
    assert fixture.workflow.runtime_context["final_pointer_manifest"] == {
        "embedding_receipt": fixture.output.model_dump(mode="json")
    }
    assert "registration_command" not in repr(fixture.step.output_pointer_manifest)
    assert "vectors.f32" not in repr(fixture.workflow.runtime_context)


def test_successful_terminal_replay_does_not_run_inference_or_rewind_history() -> None:
    fixture = execution_fixture()
    assert fixture.advance() is True
    fixture.complete()
    before = copy.deepcopy(fixture.workflow.runtime_context)
    events = len(fixture.rows)
    fixture.complete()
    assert fixture.executor.execute.call_count == 1
    assert fixture.executor.validate_completion.call_count == 3
    assert fixture.workflow.runtime_context == before and len(fixture.rows) == events
    assert fixture.receipt.registration_result.is_current is False


@pytest.mark.parametrize("borrowed", [False, True])
def test_pending_original_keys_schedule_one_bounded_advance_without_copying_reads(
    borrowed: bool,
) -> None:
    fixture = execution_fixture()
    pending = pending_fixture(fixture, borrowed=borrowed)
    fixture.executor.execute.side_effect = lambda **_kwargs: pending
    assert fixture.advance() is False
    assert fixture.step.state == "RUNNING" and fixture.step.output_pointer_manifest is None
    commands = [row for row in fixture.rows if isinstance(row, WorkflowCommandRecord)]
    assert len(commands) == 1 and commands[0].command_type == "ADVANCE_WORKFLOW"
    assert commands[0].payload == {"step_run_id": fixture.step.step_run_id}
    assert commands[0].available_at > datetime.now(UTC)
    assert pending.readings[0].owner_intent.workflow_id == (
        "workflow_" + "d" * 32 if borrowed else fixture.workflow.workflow_id
    )
    assert fixture.executor.validate_completion.call_count == 0


def test_missing_pending_key_is_not_considered_complete_or_scheduled() -> None:
    fixture = execution_fixture()
    pending = pending_fixture(fixture)
    fixture.executor.execute.side_effect = lambda **_kwargs: LocalEmbeddingStepPending(
        pending.readings[:1]
    )
    with pytest.raises(WorkflowError) as failure:
        fixture.advance()
    assert failure.value.code is WorkflowErrorCode.LOCAL_EMBEDDING_OUTCOME_INVALID
    assert fixture.step.state == "RUNNING" and fixture.step.output_pointer_manifest is None
    assert not any(isinstance(row, WorkflowCommandRecord) for row in fixture.rows)


def test_forged_pending_raw_values_raise_stable_error_without_success_or_cleanup() -> None:
    fixture = execution_fixture()
    pending = pending_fixture(fixture)
    object.__setattr__(pending, "readings", ())
    fixture.executor.execute.side_effect = lambda **_kwargs: pending
    with pytest.raises(WorkflowError) as failure:
        fixture.advance()
    assert failure.value.code is WorkflowErrorCode.LOCAL_EMBEDDING_OUTCOME_INVALID
    assert fixture.step.state == "RUNNING" and fixture.step.output_pointer_manifest is None
    assert (
        fixture.step.platform_job_id is None and fixture.workflow.current_step_key == "encode_batch"
    )
    fixture.executor.validate_completion.assert_not_called()
    assert not any(isinstance(row, WorkflowCommandRecord) for row in fixture.rows)


@pytest.mark.parametrize("entry", ["reconcile", "advance", "load"])
@pytest.mark.parametrize("native_marked", [False, True])
def test_native_related_marker_under_legacy_parent_blocks_direct_route_before_readiness(
    monkeypatch: pytest.MonkeyPatch, entry: str, native_marked: bool
) -> None:
    fixture = execution_fixture()
    roles = {"authoring", "review", "image", "item_management", "support"}
    compiled = compile_definition(
        Path("config/workflows/generic-item-development.v1.2.yaml"), roles
    )
    workflow = fixture.workflow
    workflow.definition_key = compiled.definition.definition_key
    workflow.definition_version = compiled.definition.definition_version
    workflow.definition_hash = compiled.sha256
    workflow.role_schema_version = "1.0"
    workflow.stage = "AUTHORING"
    workflow.state = "RUNNING"
    workflow.current_step_key = compiled.definition.start_step
    workflow.initial_request = workflow.request_payload = {"schema_version": "1.0"}
    definition = WorkflowDefinitionRecord(
        definition_id=workflow.definition_id,
        definition_key=compiled.definition.definition_key,
        definition_version=compiled.definition.definition_version,
        definition_hash=compiled.sha256,
        canonical_definition=compiled.as_dict(),
        source_path=compiled.source_path,
    )
    session = Mock(spec=Session)
    session.get.side_effect = lambda model, _id: (
        workflow if model is (WorkflowInstanceRecord) else definition
    )
    # SQL projection independently finds a related native definition or child.
    # Actual relation lookup is additionally covered by the guarded DB tests.
    session.scalar.return_value = native_marked

    @contextmanager
    def read() -> Iterator[Session]:
        yield cast(Session, session)

    runner = object.__new__(WorkflowRunner)
    runner.sessions = cast(sessionmaker[Session], read)
    runner.available_roles = frozenset(roles)
    runner.runner_id = "source-routing-only"
    ready, agent = Mock(), Mock(return_value=False)
    monkeypatch.setattr(runner, "_require_runtime_ready", ready)
    monkeypatch.setattr(runner, "_execute_agent", agent)

    def invoke() -> None:
        if entry == "reconcile":
            runner.reconcile(workflow.workflow_id)
        elif entry == "advance":
            runner._advance(workflow.workflow_id, None, "system", "synthetic-review-only")
        else:
            runner._load_workflow(workflow.workflow_id)

    if native_marked:
        with pytest.raises(WorkflowError) as failure:
            invoke()
        assert failure.value.code is WorkflowErrorCode.LOCAL_EMBEDDING_EXECUTION_UNAVAILABLE
        ready.assert_not_called()
        agent.assert_not_called()
    else:
        invoke()
        assert ready.call_count == (1 if entry == "reconcile" else 0)
        assert agent.call_count == (0 if entry == "load" else 1)
    query = session.scalar.call_args.args[0]
    assert query.compile().params["workflow_id_1"] == workflow.workflow_id


def test_foreign_owned_intent_is_not_relabelled_to_current_workflow() -> None:
    fixture = execution_fixture()
    borrowed = pending_fixture(fixture, borrowed=True)
    readings = tuple(
        EmbeddingEncodingReadResult.model_validate(
            seal(row.model_dump(mode="json") | {"status": "OWNED"}, "read_sha256")
        )
        for row in borrowed.readings
    )
    fixture.executor.execute.side_effect = lambda **_kwargs: LocalEmbeddingStepPending(readings)
    with pytest.raises(WorkflowError, match="original plan"):
        fixture.advance()
    assert fixture.step.output_pointer_manifest is None


@pytest.mark.parametrize("bad_outcome", [None, {}, True, "SUCCEEDED"])
def test_unknown_executor_outcome_never_creates_success(bad_outcome: object) -> None:
    fixture = execution_fixture()
    fixture.executor.execute.side_effect = lambda **_kwargs: bad_outcome
    with pytest.raises(WorkflowError) as failure:
        fixture.advance()
    assert failure.value.code is WorkflowErrorCode.LOCAL_EMBEDDING_OUTCOME_INVALID
    assert fixture.step.state == "RUNNING" and fixture.step.platform_job_id is None


@pytest.mark.parametrize("stage", ["step", "terminal", "replay"])
def test_canonical_receipt_denial_never_commits_later_success(stage: str) -> None:
    fixture = execution_fixture()
    if stage != "step":
        fixture.advance()
    if stage == "replay":
        fixture.complete()
    before = copy.deepcopy(fixture.workflow.runtime_context)
    fixture.executor.validate_completion.side_effect = ValueError("SYNTHETIC_RECEIPT_REVOKED")
    with pytest.raises(WorkflowError):
        fixture.advance() if stage == "step" else fixture.complete()
    assert fixture.workflow.runtime_context == before
    assert fixture.workflow.state != "COMPLETED" or stage == "replay"


def test_returned_different_checked_carrier_is_not_a_silent_repair() -> None:
    fixture = execution_fixture()
    replacement = LocalEmbeddingStepOutput.model_validate(
        seal(
            fixture.output.model_dump(mode="json")
            | {
                "receipt": fixture.output.receipt.model_dump(mode="json")
                | {"sha256": "sha256:" + "0" * 64}
            },
            "output_sha256",
        )
    )
    fixture.executor.validate_completion.side_effect = None
    fixture.executor.validate_completion.return_value = replacement
    with pytest.raises(WorkflowError):
        fixture.advance()
    assert fixture.step.state == "RUNNING" and fixture.step.output_pointer_manifest is None


@pytest.mark.parametrize("stage", ["step", "terminal"])
def test_late_owner_revocation_rolls_back_synthetic_success_root(stage: str) -> None:
    fixture = execution_fixture()
    if stage == "terminal":
        fixture.advance()
    fixture.deny_at_exit = fixture.roots + (2 if stage == "step" else 1)
    with pytest.raises(WorkflowError, match="late owner revoked"):
        fixture.advance() if stage == "step" else fixture.complete()
    assert fixture.workflow.state != "COMPLETED"
    if stage == "step":
        assert fixture.step.state == "RUNNING" and fixture.step.output_pointer_manifest is None


@pytest.mark.parametrize("state", ["FAILED", "CANCELLED", "SUPERSEDED"])
def test_failed_step_cannot_start_second_native_attempt(state: str) -> None:
    fixture = execution_fixture()
    fixture.step.state = state
    with pytest.raises(WorkflowError):
        fixture.advance()
    assert fixture.executor.execute.call_count == 0 and fixture.step.attempt == 1


def test_successful_step_replay_validates_receipt_without_rerunning_model() -> None:
    fixture = execution_fixture()
    fixture.advance()
    fixture.workflow.current_step_key = "encode_batch"
    assert fixture.advance() is True
    assert (
        fixture.executor.execute.call_count == 1
        and fixture.executor.validate_completion.call_count == 2
    )


def test_terminal_replay_corrupted_stored_manifest_is_rejected() -> None:
    fixture = execution_fixture()
    fixture.advance()
    fixture.complete()
    fixture.workflow.runtime_context = {"final_pointer_manifest": {"embedding_receipt": "forged"}}
    with pytest.raises(WorkflowError, match="replay pointer differs"):
        fixture.complete()


def test_native_unavailable_does_not_starve_ready_legacy_and_does_not_acquire_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, _workflow, _command = candidate_fixture()
    native = peek(source)
    legacy = replace(native, family=CommandExecutionFamily.ROLE, native_request=None)
    legacy = replace(legacy, created_at=native.created_at + timedelta(seconds=1))
    runner = object.__new__(WorkflowRunner)
    runner.local_embedding_owner = None
    runner.local_embedding_executor = None
    runner.readiness = Mock()
    runner.readiness.evaluate.return_value = RuntimeReadinessReport(())

    @contextmanager
    def session() -> Iterator[Session]:
        yield cast(Session, object())

    runner.sessions = session  # type: ignore[assignment]
    monkeypatch.setattr(
        "eom_workflow_runner.engine.peek_command_candidate",
        lambda *_args, **kwargs: native if kwargs["family"] is native.family else legacy,
    )
    assert runner._ready_command_candidate(None) is legacy
    assert source.owner.resolve_claim.call_count == 0
    runner.readiness.evaluate.assert_called_once()


def test_native_ready_does_not_depend_on_global_codex_readiness(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, _workflow, _command = candidate_fixture()
    native = peek(source)
    runner = object.__new__(WorkflowRunner)
    runner.local_embedding_owner = cast(LocalEmbeddingOwnerAdmission, source.owner)
    runner.local_embedding_executor = cast(LocalEmbeddingNativeExecutor, source.executor)
    source.executor.evaluate.return_value = RuntimeReadinessReport(())
    runner.readiness = Mock()
    runner.readiness.evaluate.side_effect = AssertionError(
        "Codex readiness is not native readiness"
    )

    @contextmanager
    def session() -> Iterator[Session]:
        yield cast(Session, object())

    runner.sessions = session  # type: ignore[assignment]
    monkeypatch.setattr(
        "eom_workflow_runner.engine.peek_command_candidate",
        lambda *_args, **kwargs: native if kwargs["family"] is native.family else None,
    )
    assert runner._ready_command_candidate(None) is native
    source.executor.evaluate.assert_called_once_with(native.native_request)
    assert source.owner.resolve_claim.call_count == source.owner.fence_mutation.call_count == 0


def test_only_unready_native_reports_unavailable_without_mutations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, _workflow, _command = candidate_fixture()
    native = peek(source)
    runner = object.__new__(WorkflowRunner)
    runner.local_embedding_owner = cast(LocalEmbeddingOwnerAdmission, source.owner)
    runner.local_embedding_executor = cast(LocalEmbeddingNativeExecutor, source.executor)
    source.executor.evaluate.return_value = RuntimeReadinessReport(
        (RuntimeReadinessCheck("gpu", ReadinessStatus.FAIL, "GPU_BUSY", "synthetic busy"),)
    )

    @contextmanager
    def session() -> Iterator[Session]:
        yield cast(Session, object())

    runner.sessions = session  # type: ignore[assignment]
    monkeypatch.setattr(
        "eom_workflow_runner.engine.peek_command_candidate",
        lambda *_args, **kwargs: native if kwargs["family"] is native.family else None,
    )
    with pytest.raises(WorkflowRuntimeNotReady) as failure:
        runner._ready_command_candidate(native.workflow_id)
    assert failure.value.report.failed_codes == ("GPU_BUSY",)
    assert source.owner.resolve_claim.call_count == 0


def test_direct_native_reconcile_denies_before_global_readiness(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = execution_fixture()
    runner = object.__new__(WorkflowRunner)
    monkeypatch.setattr(runner, "_load_workflow", lambda _id: (fixture.workflow, fixture.compiled))
    monkeypatch.setattr(
        runner, "_require_runtime_ready", lambda: pytest.fail("global readiness called")
    )
    with pytest.raises(WorkflowError) as failure:
        runner.reconcile(fixture.workflow.workflow_id)
    assert failure.value.code is WorkflowErrorCode.LOCAL_EMBEDDING_EXECUTION_UNAVAILABLE


def test_native_root_mutation_locks_workflow_before_command_and_fences_late_expiry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = execution_fixture()
    order: list[str] = []
    command = WorkflowCommandRecord(
        command_id=fixture.lease.command_id,
        workflow_id=fixture.workflow.workflow_id,
        state="PROCESSING",
        lease_owner=fixture.lease.runner_id,
        lease_token=fixture.lease.lease_token,
        lease_generation=fixture.lease.lease_generation,
        lease_expires_at=datetime.now(UTC) + timedelta(seconds=60),
    )

    @contextmanager
    def transaction(_factory: object) -> Iterator[Session]:
        yield cast(Session, fixture.session)

    def scalar(_query: Any) -> WorkflowInstanceRecord:
        order.append("workflow-lock")
        return fixture.workflow

    def execute(_query: Any) -> Any:
        order.append("command-lock")
        result = Mock()
        result.scalar_one_or_none.return_value = command
        return result

    fixture.session.scalar.side_effect = scalar
    fixture.session.execute.side_effect = execute
    fixture.owner.fence_mutation.side_effect = lambda *_args: order.append("current-owner")
    monkeypatch.setattr(
        "eom_workflow_runner.local_embedding_step_execution.transaction", transaction
    )
    with (
        pytest.raises(WorkflowError, match="ownership was lost"),
        native_fenced_runner_transaction(
            cast(sessionmaker[Session], object()),
            owner=cast(LocalEmbeddingOwnerAdmission, fixture.owner),
            workflow_id=fixture.workflow.workflow_id,
            request=fixture.scope.request,
            lease=fixture.lease,
        ),
    ):
        order.append("mutation")
        command.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    assert order == [
        "workflow-lock",
        "command-lock",
        "current-owner",
        "mutation",
        "current-owner",
        "command-lock",
    ]


def test_native_cancellation_is_durable_stop_not_capacity_or_gpu_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = execution_fixture()
    fixture.workflow.state = fixture.step.state = "RUNNING"
    cancellation = WorkflowCommandRecord(
        command_id=fixture.lease.command_id,
        workflow_id=fixture.workflow.workflow_id,
        command_type="CANCEL_WORKFLOW",
        payload={"reason": "synthetic operator stop"},
        actor_type="human",
        actor_id=fixture.workflow.created_actor_id,
        state="PROCESSING",
    )
    running = WorkflowCommandRecord(
        command_id="wfcmd_" + "9" * 32,
        workflow_id=fixture.workflow.workflow_id,
        state="PROCESSING",
    )
    fixture.rows.extend((running, cancellation))
    scalar = fixture.session.scalar.side_effect
    fixture.session.scalar.side_effect = lambda query: (
        None if (query.column_descriptions[0]["entity"] is ApprovalRequestRecord) else scalar(query)
    )
    fixture.session.scalars.side_effect = lambda query: (
        (running,)
        if (query.column_descriptions[0]["entity"] is WorkflowCommandRecord)
        else (fixture.step,)
    )
    runner = object.__new__(WorkflowRunner)
    monkeypatch.setattr(runner, "_fenced_transaction", fixture.fenced)
    authorization = WorkflowActorAuthorization(
        fixture.workflow.created_actor_id,
        WorkflowActorNamespace.OPERATOR_IDENTITY,
        True,
        frozenset({PermissionKey.WORKFLOW_CANCEL}),
        frozenset({"admin"}),
    )
    monkeypatch.setattr(runner, "_authorize_actor", lambda *_args: authorization)
    runner._cancel(cancellation)
    assert fixture.workflow.state == fixture.workflow.stage == fixture.step.state == "CANCELLED"
    assert running.state == "CANCELLED" and cancellation.state == "PROCESSING"
    fixture.executor.execute.assert_not_called()
    fixture.executor.validate_completion.assert_not_called()
    assert fixture.step.platform_job_id is None and fixture.step.output_pointer_manifest is None


@pytest.mark.parametrize("fault", [None, "expiry", "generation"])
def test_native_terminal_command_commit_retains_late_live_identity(
    monkeypatch: pytest.MonkeyPatch, fault: str | None
) -> None:
    fixture = execution_fixture()
    command = WorkflowCommandRecord(
        command_id=fixture.lease.command_id,
        workflow_id=fixture.workflow.workflow_id,
        state="PROCESSING",
        lease_owner=fixture.lease.runner_id,
        lease_token=fixture.lease.lease_token,
        lease_generation=fixture.lease.lease_generation,
        lease_expires_at=datetime.now(UTC) + timedelta(seconds=60),
    )

    @contextmanager
    def transaction(_factory: object) -> Iterator[Session]:
        yield cast(Session, fixture.session)

    def scalar(query: Any) -> Any:
        return (
            fixture.workflow
            if query.column_descriptions[0]["entity"] is (WorkflowInstanceRecord)
            else command
        )

    def fence(*_args: Any) -> None:
        if fixture.owner.fence_mutation.call_count == 2:
            if fault == "expiry":
                command.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
            elif fault == "generation":
                command.lease_generation += 1

    fixture.session.scalar.side_effect = scalar
    fixture.session.execute.return_value.scalar_one_or_none.return_value = command
    fixture.owner.fence_mutation.side_effect = fence
    monkeypatch.setattr(
        "eom_workflow_runner.local_embedding_step_execution.transaction", transaction
    )

    def finish() -> None:
        with native_fenced_runner_transaction(
            cast(sessionmaker[Session], object()),
            owner=cast(LocalEmbeddingOwnerAdmission, fixture.owner),
            workflow_id=fixture.workflow.workflow_id,
            request=fixture.scope.request,
            lease=fixture.lease,
        ):
            command.state = "SUCCEEDED"

    if fault is None:
        finish()
        assert command.state == "SUCCEEDED"
    else:
        with pytest.raises(WorkflowError, match="lost its acquired lease"):
            finish()


@pytest.mark.parametrize("unavailable", [False, True])
def test_busy_native_exact_claim_uses_new_root_for_ready_legacy(
    monkeypatch: pytest.MonkeyPatch,
    unavailable: bool,
) -> None:
    source, _workflow, command = candidate_fixture()
    native = peek(source)
    legacy = replace(native, family=CommandExecutionFamily.ROLE, native_request=None)
    command.state = "LEASED"
    command.lease_owner, command.lease_token = "runner", "wflease_" + "e" * 32
    command.lease_generation = 1
    command.lease_expires_at = datetime.now(UTC) + timedelta(seconds=60)
    runner = object.__new__(WorkflowRunner)
    runner.runner_id = "runner"
    runner.runner_config = cast(Any, SimpleNamespace(command_lease_seconds=60))
    runner.local_embedding_owner = cast(LocalEmbeddingOwnerAdmission, source.owner)
    runner.local_embedding_executor = cast(LocalEmbeddingNativeExecutor, source.executor)
    session = Mock(spec=Session)
    session.get.return_value = command
    session.execute.return_value.scalar_one_or_none.return_value = command
    roots: list[int] = []

    @contextmanager
    def root(_factory: object = None) -> Iterator[Session]:
        roots.append(1)
        yield cast(Session, session)

    @contextmanager
    def scope(*_args: Any) -> Iterator[None]:
        yield

    runner.sessions = cast(sessionmaker[Session], root)
    ready = Mock(side_effect=(native, legacy))
    failure = (
        WorkflowError(
            WorkflowErrorCode.LOCAL_EMBEDDING_EXECUTION_UNAVAILABLE,
            "synthetic actual linked recovery unavailable",
        )
        if unavailable
        else None
    )
    claim = Mock(side_effect=(failure, command))
    monkeypatch.setattr(runner, "_ready_command_candidate", ready)
    monkeypatch.setattr("eom_workflow_runner.engine.claim_command_candidate", claim)
    monkeypatch.setattr("eom_workflow_runner.engine.transaction", root)
    monkeypatch.setattr(runner, "_fenced_transaction", root)
    monkeypatch.setattr(runner, "_execution_family_scope", scope)
    monkeypatch.setattr(runner, "_command_lease_scope", scope)
    monkeypatch.setattr(runner, "_process_command", lambda _id: None)
    assert runner.run_once() is command
    assert ready.call_args_list[1].args[1] == frozenset({CommandExecutionFamily.LOCAL_EMBEDDING})
    assert claim.call_count == 2 and command.state == "SUCCEEDED"
