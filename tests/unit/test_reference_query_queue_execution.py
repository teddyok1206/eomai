"""Synthetic SQL/IAM/numerical seams: source lifecycle, NOT installed QUERY acceptance.

The exact QUERY pair uses real admission. IAM, SQL and numerical execution are
explicit synthetic seams; no installed runtime/default or user grant is claimed.
"""

from __future__ import annotations

import copy
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from unittest.mock import Mock

import pytest
from eom_identifiers import content_sha256
from eom_orchestrator.models import Base
from eom_workflow.admission import workflow_definition_is_admitted
from eom_workflow.compiler import CompiledWorkflowDefinition, compile_definition_data
from eom_workflow.reference_query_execution import validate_reference_query_step_output
from eom_workflow_runner import reference_query_step_execution as step_module
from eom_workflow_runner import repository
from eom_workflow_runner.engine import WorkflowRunner
from eom_workflow_runner.errors import WorkflowError, WorkflowErrorCode
from eom_workflow_runner.models import (
    WorkflowCommandRecord,
    WorkflowDefinitionRecord,
    WorkflowEventRecord,
    WorkflowInstanceRecord,
    WorkflowStepRunRecord,
)
from eom_workflow_runner.native_workflow_transaction import native_fenced_runner_transaction
from eom_workflow_runner.readiness import (
    RuntimeReadinessReport,
    WorkflowRuntimeNotReady,
)
from eom_workflow_runner.reference_query_admission import (
    ReferenceQueryOwnerAdmission,
    ResolvedReferenceQueryAdmission,
    validate_reference_query_runner_admission,
)
from eom_workflow_runner.reference_query_execution_port import (
    ReferenceQueryNativeExecutor,
    ReferenceQueryStepPending,
)
from eom_workflow_runner.reference_query_step_execution import (
    advance_reference_query_step,
    complete_reference_query_terminal,
)
from eom_workflow_runner.repository import (
    CommandExecutionFamily,
    CommandLeaseIdentity,
    claim_command_candidate,
    create_workflow_instance,
    peek_command_candidate,
    reference_query_business_fingerprint,
    validate_reference_query_workflow_submission,
    workflow_request_storage_document,
)
from sqlalchemy import Engine, Table
from sqlalchemy.orm import Session, sessionmaker

from tests.unit.native_reference_query_coordinator_fixtures import query_records
from tests.unit.test_control_file_set_publication import _publisher
from tests.unit.test_reference_query_execution_contracts import Case, case
from tests.unit.test_reference_query_workflow_contracts import definition_body


@dataclass
class QueryFixture:
    case: Case
    compiled: CompiledWorkflowDefinition
    definition: WorkflowDefinitionRecord
    scope: ResolvedReferenceQueryAdmission
    workflow: WorkflowInstanceRecord
    step: WorkflowStepRunRecord
    command: WorkflowCommandRecord
    owner: Mock
    executor: Mock
    session: Mock
    rows: list[Any] = field(default_factory=list)
    depth: int = 0
    roots: int = 0
    deny_at_exit: int | None = None

    @contextmanager
    def savepoint(self) -> Iterator[None]:
        count = len(self.rows)
        self.depth += 1
        try:
            yield
        except Exception:
            del self.rows[count:]
            raise
        finally:
            self.depth -= 1

    def submit(self) -> tuple[WorkflowInstanceRecord, bool]:
        return create_workflow_instance(
            cast(Session, self.session),
            definition=self.definition,
            request=self.scope.request,
            idempotency_key="synthetic-query-submit",
            actor_type="human",
            actor_id=self.scope.request.operator_audit.operator_id,
            reference_query_owner=cast(ReferenceQueryOwnerAdmission, self.owner),
            reference_query_executor=cast(ReferenceQueryNativeExecutor, self.executor),
        )

    def scalar(self, query: Any) -> Any:
        description = query.column_descriptions[0]
        model, name = description["entity"], description["name"]
        if name == "coalesce":
            return 0
        if model is WorkflowDefinitionRecord:
            return self.definition
        if model is WorkflowEventRecord:
            return 1 + sum(isinstance(row, WorkflowEventRecord) for row in self.rows)
        params = query.compile().params
        rows = [row for row in self.rows if isinstance(row, model)]
        for key in ("workflow_id", "command_id", "idempotency_key", "request_hash", "step_key"):
            if hasattr(model, key) and f"{key}_1" in params:
                rows = [row for row in rows if getattr(row, key) == params[f"{key}_1"]]
        state = params.get("state_1")
        if state is not None:
            states = state if isinstance(state, list | tuple) else (state,)
            rows = [row for row in rows if row.state in states]
        return rows[0] if rows else None

    @contextmanager
    def root(self) -> Iterator[Session]:
        assert self.depth == 0
        self.roots += 1
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
        count = len(self.rows)
        self.depth += 1
        try:
            yield cast(Session, self.session)
            if self.deny_at_exit == self.roots:
                raise WorkflowError(
                    WorkflowErrorCode.WORKFLOW_CONCURRENCY_CONFLICT, "synthetic late owner revoked"
                )
        except Exception:
            for row, values in snapshots:
                for key, value in values.items():
                    setattr(row, key, value)
            del self.rows[count:]
            raise
        finally:
            self.depth -= 1

    def advance(self) -> None:
        advance_reference_query_step(
            workflow=self.workflow,
            compiled=self.compiled,
            request=self.scope.request,
            lease=CommandLeaseIdentity(self.command.command_id, "synthetic-query", "lease", 1),
            owner=cast(ReferenceQueryOwnerAdmission, self.owner),
            executor=cast(ReferenceQueryNativeExecutor, self.executor),
            fenced_transaction=self.root,
            actor_type="human",
            actor_id=self.workflow.created_actor_id,
        )

    def complete(self) -> None:
        complete_reference_query_terminal(
            workflow_id=self.workflow.workflow_id,
            request=self.scope.request,
            lease=CommandLeaseIdentity(self.command.command_id, "synthetic-query", "lease", 1),
            executor=cast(ReferenceQueryNativeExecutor, self.executor),
            fenced_transaction=self.root,
            actor_type="human",
            actor_id=self.workflow.created_actor_id,
        )

    def candidate(self) -> repository.CommandCandidate:
        self.session.execute.return_value.one_or_none.return_value = (self.command, self.workflow)
        candidate = peek_command_candidate(
            cast(Session, self.session), family=CommandExecutionFamily.REFERENCE_QUERY
        )
        assert candidate is not None
        return candidate


@pytest.fixture
def source() -> QueryFixture:
    compiled = compile_definition_data(definition_body(), "synthetic-query-lifecycle", set())
    base = case(definition_sha256=compiled.sha256)
    definition = WorkflowDefinitionRecord(
        definition_id="wfdef_" + "1" * 32,
        definition_key=compiled.definition.definition_key,
        definition_version=compiled.definition.definition_version,
        definition_hash=compiled.sha256,
        canonical_definition=compiled.as_dict(),
        schema_version=compiled.definition.schema_version,
        source_path=compiled.source_path,
        active=True,
    )
    actor = base.request.operator_audit.operator_id
    fingerprint = reference_query_business_fingerprint(
        definition, base.request, actor_type="human", actor_id=actor
    )
    workflow = WorkflowInstanceRecord(
        workflow_id=base.output.workflow_id,
        definition_id=definition.definition_id,
        definition_key=definition.definition_key,
        definition_version=definition.definition_version,
        definition_hash=definition.definition_hash,
        protocol_version="1.0.1",
        role_schema_version="reference-query/1.0",
        initial_request=base.request.model_dump(mode="json"),
        request_payload=base.request.model_dump(mode="json"),
        current_step_key="encode_reference_query",
        state="REQUESTED",
        stage="LOCAL_EMBEDDING",
        runtime_context={},
        request_hash=fingerprint,
        idempotency_key="synthetic-query-submission",
        lock_version=1,
        created_actor_type="human",
        created_actor_id=actor,
    )
    step = WorkflowStepRunRecord(
        step_run_id=base.output.step_run_id,
        workflow_id=workflow.workflow_id,
        step_key="encode_reference_query",
        attempt=1,
        step_type="application",
        worker_role=None,
        result_schema="embedding-reference-query-result@1.0",
        state="READY",
        input_pointer_manifest={"workflow_request_sha256": base.request.request_sha256},
    )
    now = datetime.now(UTC)
    command = WorkflowCommandRecord(
        command_id=base.launch.original_command_id,
        workflow_id=workflow.workflow_id,
        command_type="START_WORKFLOW",
        payload={},
        actor_type="human",
        actor_id=actor,
        source="synthetic-query",
        state="PENDING",
        lease_generation=0,
        attempts=0,
        created_at=now - timedelta(seconds=3),
        available_at=now - timedelta(seconds=2),
    )
    command.request_hash = content_sha256(
        {
            "workflow_id": workflow.workflow_id,
            "command_type": command.command_type,
            "payload": {},
            "actor_type": "human",
            "actor_id": actor,
            "source": command.source,
        }
    )
    scope = ResolvedReferenceQueryAdmission(base.request, base.policy, base.bundle)
    session = Mock(spec=Session)
    owner = Mock(spec=ReferenceQueryOwnerAdmission)
    executor = Mock(spec=ReferenceQueryNativeExecutor)
    fixture = QueryFixture(
        base,
        compiled,
        definition,
        scope,
        workflow,
        step,
        command,
        owner,
        executor,
        session,
        [workflow, step, command],
    )
    session.is_active = True
    session.get_transaction.return_value = Mock(is_active=True)
    session.in_nested_transaction.side_effect = lambda: fixture.depth > 0
    session.scalar.side_effect = fixture.scalar
    session.execute.return_value.scalar_one_or_none.return_value = workflow
    session.add.side_effect = fixture.rows.append
    session.begin_nested.side_effect = fixture.savepoint

    def get(model: Any, identity: str) -> Any:
        return next(
            (
                row
                for row in fixture.rows
                if isinstance(row, model)
                and getattr(row, row.__mapper__.primary_key[0].name) == identity
            ),
            None,
        )

    def execute(**_kwargs: Any) -> Any:
        assert fixture.depth == 0, "a SQL/source root survived inference"
        assert executor.allocate_execution.called
        return base.output

    def allocate(**kwargs: Any) -> Any:
        assert fixture.depth == 1, "allocation escaped the step-start root"
        assert kwargs["session"] is session
        assert kwargs["step"] is step and step.state == "RUNNING"
        return base.launch

    def validate(**kwargs: Any) -> Any:
        assert fixture.depth == 1
        validate_reference_query_step_output(kwargs["output"], base.receipt)
        return kwargs["output"]

    session.get.side_effect = get
    owner.resolve_submission.return_value = scope
    owner.resolve_claim.return_value = scope
    executor.execute.side_effect = execute
    executor.allocate_execution.side_effect = allocate
    executor.validate_completion.side_effect = validate
    return fixture


@pytest.fixture
def admitted_query_definition() -> None:
    assert workflow_definition_is_admitted("local-embedding-reference-query", "1.0.0")
    assert not workflow_definition_is_admitted("local-embedding-reference-query", "1.0.1")


def test_fixed_lifecycle_closes_sql_before_inference_and_revalidates_terminal_replay(
    source: QueryFixture,
) -> None:
    source.advance()
    assert source.step.state == "SUCCEEDED" and source.workflow.current_step_key == "complete"
    assert source.step.platform_job_id == source.case.output.receipt_owner_job_id
    assert source.step.output_pointer_manifest == source.case.output.model_dump(mode="json")
    source.complete()
    source.complete()
    assert source.workflow.state == source.workflow.stage == "COMPLETED"
    assert source.executor.execute.call_count == 1
    source.executor.allocate_execution.assert_called_once()
    assert source.executor.validate_completion.call_count == 3
    assert len([row for row in source.rows if isinstance(row, WorkflowStepRunRecord)]) == 2
    final = source.workflow.runtime_context["final_pointer_manifest"]
    assert set(final) == {"reference_query_receipt"}
    assert "text" not in str(final) and "vectors" not in str(final)


@pytest.mark.parametrize("failure", ("allocation", "late_root"))
def test_allocation_failure_cannot_commit_a_running_step_or_reach_inference(source, failure):
    if failure == "allocation":
        source.executor.allocate_execution.side_effect = ValueError("synthetic allocation denied")
    else:
        source.deny_at_exit = 1
    with pytest.raises((ValueError, WorkflowError)):
        source.advance()
    assert source.workflow.state == "REQUESTED" and source.step.state == "READY"
    assert not any(isinstance(row, WorkflowEventRecord) for row in source.rows)
    source.executor.execute.assert_not_called()


@pytest.mark.parametrize("completed", (False, True))
def test_pending_keeps_original_step_or_adopts_exact_late_completion(
    source, monkeypatch, completed
):
    records = query_records(source.case)
    pending = ReferenceQueryStepPending(
        source.case.launch.native_launch_job_id, source.case.launch.association_sha256, "UNCERTAIN"
    )
    source.executor.execute.side_effect = lambda **_: pending
    monkeypatch.setattr(
        step_module, "read_native_reference_query_launch", lambda *_a, **_kw: source.case.launch
    )
    from types import SimpleNamespace

    history = SimpleNamespace(
        state="SUCCEEDED" if completed else "RUNNING", records=records if completed else records[:1]
    )
    monkeypatch.setattr(
        step_module,
        "NativeReferenceQueryCoordinator",
        lambda *_: SimpleNamespace(read=lambda _: history),
    )
    source.advance()
    queued = [
        r for r in source.rows if isinstance(r, WorkflowCommandRecord) and r is not source.command
    ]
    if completed:
        assert not queued and source.step.state == "SUCCEEDED"
        assert source.workflow.current_step_key == "complete"
        source.executor.validate_completion.assert_called_once()
    else:
        assert (
            source.step.state == "RUNNING"
            and source.workflow.current_step_key == "encode_reference_query"
        )
        assert len(queued) == 1 and queued[0].source == "reference-query-owner"
        assert queued[0].payload == {"step_run_id": source.step.step_run_id}
        assert 0 < (queued[0].available_at - datetime.now(UTC)).total_seconds() <= 60
        assert source.step.output_pointer_manifest is None
        source.executor.validate_completion.assert_not_called()


@pytest.mark.parametrize(
    "fault", ("missing", "job", "association", "failed", "unallocated", "scalar")
)
def test_invalid_pending_does_not_enqueue_or_mark_success(source, monkeypatch, fault):
    from types import SimpleNamespace

    launch = source.case.launch
    pending = ReferenceQueryStepPending(
        launch.native_launch_job_id, launch.association_sha256, "BUSY"
    )
    if fault == "job":
        pending = replace(pending, native_launch_job_id="job_" + "f" * 32)
    if fault == "association":
        pending = replace(pending, association_sha256="sha256:" + "f" * 64)
    if fault == "scalar":
        object.__setattr__(pending, "native_launch_job_id", True)
    source.executor.execute.side_effect = lambda **_: pending
    monkeypatch.setattr(
        step_module,
        "read_native_reference_query_launch",
        lambda *_a, **_kw: None if fault == "missing" else launch,
    )
    history = SimpleNamespace(
        state="FAILED" if fault == "failed" else "RUNNING",
        records=() if fault == "unallocated" else query_records(source.case)[:1],
    )
    monkeypatch.setattr(
        step_module,
        "NativeReferenceQueryCoordinator",
        lambda *_: SimpleNamespace(read=lambda _: history),
    )
    with pytest.raises(WorkflowError) as error:
        source.advance()
    assert error.value.code == WorkflowErrorCode.LOCAL_EMBEDDING_OUTCOME_INVALID
    assert source.step.state != "SUCCEEDED"
    assert not [
        r for r in source.rows if isinstance(r, WorkflowCommandRecord) and r is not source.command
    ]
    assert len([row for row in source.rows if isinstance(row, WorkflowStepRunRecord)]) == 1
    assert "final_pointer_manifest" not in (source.workflow.runtime_context or {})


@pytest.mark.parametrize("change", ("input", "attempt", "role", "result", "type"))
def test_changed_step_cannot_reach_numerical_executor(source: QueryFixture, change: str) -> None:
    if change == "input":
        source.step.input_pointer_manifest = {}
    else:
        attribute, value = {
            "attempt": ("attempt", 2),
            "role": ("worker_role", "reviewer"),
            "result": ("result_schema", "incremental-embedding-result@1.0"),
            "type": ("step_type", "agent"),
        }[change]
        setattr(source.step, attribute, value)
    with pytest.raises(WorkflowError):
        source.advance()
    source.executor.execute.assert_not_called()
    assert source.workflow.state == "REQUESTED"


@pytest.mark.parametrize("state", ("FAILED", "CANCELLED"))
def test_terminal_attempt_is_not_restarted(source: QueryFixture, state: str) -> None:
    source.step.state = state
    with pytest.raises(WorkflowError):
        source.advance()
    source.executor.execute.assert_not_called()
    assert source.step.state == state


@pytest.mark.parametrize("failure", ("wrong_type", "invalid_receipt", "late_owner"))
def test_invalid_or_late_completion_never_marks_success(source: QueryFixture, failure: str) -> None:
    if failure == "wrong_type":
        source.executor.execute.side_effect = None
        source.executor.execute.return_value = {"status": "SUCCEEDED"}
    elif failure == "invalid_receipt":
        source.executor.validate_completion.side_effect = ValueError("synthetic corrupt receipt")
    else:
        source.deny_at_exit = 2
    with pytest.raises(WorkflowError):
        source.advance()
    assert (
        source.step.state == "RUNNING"
        and source.workflow.current_step_key == "encode_reference_query"
    )
    assert source.step.output_pointer_manifest is None and source.step.platform_job_id is None


def test_terminal_pointer_tamper_is_not_repaired(source: QueryFixture) -> None:
    source.advance()
    source.complete()
    source.workflow.runtime_context = {}
    with pytest.raises(WorkflowError, match="replay pointer differs"):
        source.complete()
    assert source.workflow.runtime_context == {}
    assert source.executor.execute.call_count == 1


@pytest.mark.parametrize("missing", ("owner", "executor"))
def test_query_admission_cannot_replace_missing_runtime_ports_before_io(
    source: QueryFixture, missing: str
) -> None:
    with pytest.raises(WorkflowError) as failure:
        create_workflow_instance(
            cast(Session, source.session),
            definition=source.definition,
            request=source.scope.request,
            idempotency_key="synthetic-query-unoffered",
            actor_type="human",
            actor_id=source.workflow.created_actor_id,
            reference_query_owner=(
                None if missing == "owner" else cast(ReferenceQueryOwnerAdmission, source.owner)
            ),
            reference_query_executor=(
                None
                if missing == "executor"
                else cast(ReferenceQueryNativeExecutor, source.executor)
            ),
        )
    assert failure.value.code is WorkflowErrorCode.LOCAL_EMBEDDING_EXECUTION_UNAVAILABLE
    assert source.session.mock_calls == [] and source.owner.mock_calls == []


def test_query_claim_is_exact_and_owner_precedes_lease_then_checks_late(
    source: QueryFixture,
    admitted_query_definition: None,
) -> None:
    candidate = source.candidate()
    order: list[str] = []

    def claim(_session: Session, **kwargs: Any) -> ResolvedReferenceQueryAdmission:
        assert kwargs["workflow"] is source.workflow and kwargs["command"] is source.command
        assert source.command.lease_generation == 0
        order.append("current-owner-before-assignment")
        return source.scope

    def fence(*_args: Any) -> None:
        assert source.command.lease_generation == 1 and source.command.lease_token is not None
        order.append("current-owner-after-assignment")

    source.owner.resolve_claim.side_effect = claim
    source.owner.fence_mutation.side_effect = fence
    source.session.execute.return_value.scalar_one_or_none.return_value = source.command
    result = claim_command_candidate(
        cast(Session, source.session),
        candidate,
        runner_id="synthetic-query",
        lease_seconds=60,
        reference_query_owner=cast(ReferenceQueryOwnerAdmission, source.owner),
        reference_query_executor=cast(ReferenceQueryNativeExecutor, source.executor),
    )
    assert result is source.command and result.state == "LEASED"
    assert order == ["current-owner-before-assignment", "current-owner-after-assignment"]
    assert source.executor.mock_calls == []


def test_submission_reuses_the_same_workflow_and_checks_owner_before_and_after_savepoint(
    source: QueryFixture,
    admitted_query_definition: None,
) -> None:
    source.rows.clear()
    depths: list[int] = []

    def resolve(_session: Session, _request: Any) -> ResolvedReferenceQueryAdmission:
        depths.append(source.depth)
        return source.scope

    source.owner.resolve_submission.side_effect = resolve
    first, created = source.submit()
    second, repeated = source.submit()
    assert created and not repeated and first is second
    assert depths == [0, 0, 0, 0]
    assert len([row for row in source.rows if isinstance(row, WorkflowInstanceRecord)]) == 1
    assert source.executor.mock_calls == []
    assert first.role_schema_version == "reference-query/1.0" and first.stage == "LOCAL_EMBEDDING"
    assert first.initial_request == source.scope.request.model_dump(mode="json")


def test_late_submission_revocation_rolls_back_new_rows_and_does_not_execute(
    source: QueryFixture,
    admitted_query_definition: None,
) -> None:
    source.rows.clear()
    source.session.rollback.side_effect = source.rows.clear
    source.owner.resolve_submission.side_effect = [source.scope, ValueError("synthetic revoked")]
    with pytest.raises(ValueError, match="revoked"):
        source.submit()
    assert source.rows == [] and source.executor.mock_calls == []


@pytest.mark.parametrize("change", ("generation", "request", "actor", "definition"))
def test_changed_exact_candidate_cannot_substitute_or_claim(
    source: QueryFixture,
    admitted_query_definition: None,
    change: str,
) -> None:
    candidate = source.candidate()
    if change == "generation":
        source.command.lease_generation = 1
    elif change == "request":
        source.workflow.request_payload = {}
    elif change == "actor":
        source.command.actor_id = "operator_" + "b" * 32
    else:
        source.workflow.definition_hash = "sha256:" + "b" * 64
    assert (
        claim_command_candidate(
            cast(Session, source.session),
            candidate,
            runner_id="synthetic-query",
            lease_seconds=60,
            reference_query_owner=cast(ReferenceQueryOwnerAdmission, source.owner),
            reference_query_executor=cast(ReferenceQueryNativeExecutor, source.executor),
        )
        is None
    )
    assert source.owner.mock_calls == [] and source.command.lease_token is None


def test_query_does_not_accept_index_ports_or_claim_another_family(source: QueryFixture) -> None:
    candidate = source.candidate()
    source.session.reset_mock()
    with pytest.raises(WorkflowError):
        claim_command_candidate(
            cast(Session, source.session),
            replace(candidate, family=CommandExecutionFamily.LOCAL_EMBEDDING),
            runner_id="synthetic-query",
            lease_seconds=60,
        )
    assert source.session.mock_calls == []


@pytest.mark.parametrize("field", ("actor", "payload", "hash", "definition"))
def test_submission_replay_checks_exact_actor_and_original_snapshot(
    source: QueryFixture,
    field: str,
) -> None:
    validate_reference_query_workflow_submission(
        cast(Session, source.session),
        source.workflow,
        definition=source.definition,
        request=source.scope.request,
        actor_type="human",
        actor_id=source.workflow.created_actor_id,
    )
    if field == "actor":
        source.workflow.created_actor_id = "operator_" + "b" * 32
    elif field == "payload":
        source.workflow.request_payload = {}
    elif field == "hash":
        source.workflow.request_hash = "sha256:" + "b" * 64
    else:
        source.definition.definition_key = "local-embedding-index"
    with pytest.raises(ValueError, match="REPLAY_INVALID"):
        validate_reference_query_workflow_submission(
            cast(Session, source.session),
            source.workflow,
            definition=source.definition,
            request=source.scope.request,
            actor_type="human",
            actor_id=source.scope.request.operator_audit.operator_id,
        )


def test_raw_unknown_control_fields_are_not_dropped(source: QueryFixture) -> None:
    forged = source.scope.request.model_copy(update={"unknown": "ADMIN"})
    with pytest.raises(ValueError):
        workflow_request_storage_document(forged)
    assert (
        workflow_request_storage_document(source.scope.request) == source.workflow.initial_request
    )
    with pytest.raises(ValueError):
        validate_reference_query_runner_admission(
            source.scope,
            source.compiled,
            actor_type="system",
            actor_id=source.workflow.created_actor_id,
        )


def test_unavailable_query_does_not_starve_ready_index(
    source: QueryFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    query = source.candidate()
    index = replace(
        query,
        family=CommandExecutionFamily.LOCAL_EMBEDDING,
        native_request=case_index_request(),
        created_at=query.created_at + timedelta(seconds=1),
    )
    runner = object.__new__(WorkflowRunner)
    runner.command_families = frozenset(CommandExecutionFamily)
    runner.command_actor_selection = None

    @contextmanager
    def read_session() -> Iterator[Session]:
        yield cast(Session, source.session)

    runner.sessions = read_session  # type: ignore[assignment]
    runner.reference_query_owner = runner.reference_query_executor = None
    runner.local_embedding_owner = Mock()
    runner.local_embedding_executor = Mock()
    runner.local_embedding_executor.evaluate.return_value = RuntimeReadinessReport(())
    monkeypatch.setattr(
        "eom_workflow_runner.engine.peek_command_candidate",
        lambda _session, *, family, workflow_id, actor_selection=None: {
            query.family: query,
            index.family: index,
        }.get(family),
    )
    assert runner._ready_command_candidate(None) is index
    runner.local_embedding_owner = None
    with pytest.raises(WorkflowRuntimeNotReady):
        runner._ready_command_candidate(None)


def case_index_request() -> Any:
    from tests.unit.local_embedding_admission_fixtures import native_fixture

    return native_fixture().request


@pytest.mark.parametrize("fault", (None, "expiry", "generation"))
def test_actual_shared_root_selects_query_protocol_and_checks_terminal_acquisition_last(
    source: QueryFixture,
    monkeypatch: pytest.MonkeyPatch,
    fault: str | None,
) -> None:
    lease = CommandLeaseIdentity(source.command.command_id, "query-root", "wflease_" + "a" * 32, 1)
    source.command.state = "PROCESSING"
    source.command.lease_owner = lease.runner_id
    source.command.lease_token = lease.lease_token
    source.command.lease_generation = lease.lease_generation
    source.command.lease_expires_at = datetime.now(UTC) + timedelta(seconds=60)
    source.session.execute.return_value.scalar_one_or_none.return_value = source.command

    def fence(*_args: Any) -> None:
        if source.owner.fence_mutation.call_count == 2:
            if fault == "expiry":
                source.command.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
            elif fault == "generation":
                source.command.lease_generation += 1

    source.owner.fence_mutation.side_effect = fence
    monkeypatch.setattr(
        "eom_workflow_runner.native_workflow_transaction.transaction",
        lambda _factory: source.root(),
    )

    def finish() -> None:
        with native_fenced_runner_transaction(
            cast(sessionmaker[Session], object()),
            owner=cast(ReferenceQueryOwnerAdmission, source.owner),
            workflow_id=source.workflow.workflow_id,
            request=source.scope.request,
            lease=lease,
        ):
            source.command.state = "SUCCEEDED"

    if fault is None:
        finish()
        assert source.command.state == "SUCCEEDED"
    else:
        with pytest.raises(WorkflowError, match="lost its acquired lease"):
            finish()
        assert source.command.state == "PROCESSING"
    assert source.owner.fence_mutation.call_count == 2
    assert source.executor.mock_calls == []


def test_actual_sqlite_routing_separates_three_families_and_quarantines_partial_query_markers(
    tmp_path: Path,
) -> None:
    """Actual SQL routing only; synthetic malformed rows never become execution grants."""
    _unused_publisher, raw_engine = _publisher(tmp_path)
    engine = cast(Engine, raw_engine)
    Base.metadata.create_all(
        engine,
        tables=[
            cast(Table, model.__table__)
            for model in (
                WorkflowDefinitionRecord,
                WorkflowInstanceRecord,
                WorkflowCommandRecord,
                WorkflowStepRunRecord,
            )
        ],
    )
    sessions = sessionmaker(engine)
    families: dict[str, CommandExecutionFamily] = {}
    try:
        with sessions.begin() as session:
            for index, marker in enumerate(("role", "index", "query", "partial", "step"), start=1):
                seed = str(index) * 32
                key = {
                    "index": "local-embedding-index",
                    "query": "local-embedding-reference-query",
                }.get(marker, "synthetic-" + marker)
                definition = WorkflowDefinitionRecord(
                    definition_id="wfdef_" + seed,
                    definition_key=key,
                    definition_version="1.0.0",
                    definition_hash="sha256:" + seed * 2,
                    schema_version="1.1",
                    canonical_definition={"definition_key": key},
                    source_path="synthetic-routing-only",
                    active=False,
                )
                workflow = WorkflowInstanceRecord(
                    workflow_id="workflow_" + seed,
                    definition_id=definition.definition_id,
                    definition_key=key,
                    definition_version="1.0.0",
                    definition_hash=definition.definition_hash,
                    protocol_version="1.0.1",
                    role_schema_version="workflow-role/1.20.0",
                    state="REQUESTED",
                    stage="AUTHORING",
                    current_step_key="synthetic",
                    initial_request={},
                    request_payload={"purpose": "REFERENCE_QUERY"} if marker == "partial" else {},
                    runtime_context={},
                    idempotency_key="synthetic-routing:" + marker,
                    request_hash="sha256:" + seed * 2,
                    created_actor_type="human",
                    created_actor_id="synthetic",
                )
                command = WorkflowCommandRecord(
                    command_id="wfcommand_" + seed,
                    workflow_id=workflow.workflow_id,
                    command_type="START_WORKFLOW",
                    payload={},
                    actor_type="human",
                    actor_id="synthetic",
                    source="synthetic-routing-only",
                    idempotency_key="synthetic-cmd:" + marker,
                    request_hash="sha256:" + seed * 2,
                    state="PENDING",
                    attempts=0,
                    lease_generation=0,
                    available_at=datetime.now(UTC) - timedelta(seconds=1),
                )
                session.add(definition)
                session.flush()
                session.add(workflow)
                session.flush()
                session.add(command)
                if marker == "step":
                    session.add(
                        WorkflowStepRunRecord(
                            step_run_id="steprun_" + seed,
                            workflow_id=workflow.workflow_id,
                            step_key="encode_reference_query",
                            step_type="application",
                            attempt=1,
                            worker_role=None,
                            result_schema="embedding-reference-query-result@1.0",
                            state="RUNNING",
                            input_pointer_manifest={},
                        )
                    )
                families[workflow.workflow_id] = (
                    CommandExecutionFamily.ROLE
                    if marker == "role"
                    else CommandExecutionFamily.LOCAL_EMBEDDING
                    if marker == "index"
                    else CommandExecutionFamily.REFERENCE_QUERY
                )
        with sessions() as session:
            for workflow_id, expected in families.items():
                offered = [
                    family
                    for family in CommandExecutionFamily
                    if peek_command_candidate(session, family=family, workflow_id=workflow_id)
                    is not None
                ]
                assert offered == [expected]
    finally:
        engine.dispose()
