"""Real Runner dispatch/step composition over synthetic SQL/source/native ports.

No private admission, installed runtime, physical model execution or operating
claim is inferred. Existing immutable input models are used without relabelling.
"""

from contextlib import contextmanager
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_identifiers import canonical_json_bytes
from eom_workflow.compiler import compile_definition_data
from eom_workflow_runner import engine as engine_module
from eom_workflow_runner.composition import build_workflow_runtime
from eom_workflow_runner.engine import WorkflowRunner
from eom_workflow_runner.errors import WorkflowError, WorkflowErrorCode
from eom_workflow_runner.models import WorkflowCommandRecord
from eom_workflow_runner.private_chat_query_admission import PrivateChatQueryOwnerAdmission
from eom_workflow_runner.private_chat_query_execution_port import PrivateChatQueryNativeExecutor
from eom_workflow_runner.readiness import (
    ReadinessStatus,
    RuntimeReadinessCheck,
    RuntimeReadinessReport,
    WorkflowRuntimeNotReady,
)
from eom_workflow_runner.repository import CommandExecutionFamily, CommandLeaseIdentity
from eom_workflow_runner.settings import RunnerConfig, WorkflowSettings
from sqlalchemy import create_engine

from tests.unit.test_private_chat_query_queue_routing import private_candidate
from tests.unit.test_private_chat_query_step_execution import (
    completed as completed,
)
from tests.unit.test_private_chat_query_step_execution import (
    lifecycle as lifecycle,
)
from tests.unit.test_private_chat_query_step_execution import (
    private_terminal as private_terminal,
)
from tests.unit.test_private_chat_query_workflow import definition_body


def configured_runner(value):
    runner = object.__new__(WorkflowRunner)
    runner.command_families = frozenset({CommandExecutionFamily.PRIVATE_CHAT_QUERY})
    runner.command_actor_selection = None
    runner.runner_config = SimpleNamespace(poll_interval_seconds=30)
    runner.private_chat_query_owner = value.owner
    runner.private_chat_query_executor = value.executor
    runner.local_embedding_owner = runner.local_embedding_executor = None
    runner.reference_query_owner = runner.reference_query_executor = None
    runner._fenced_transaction = value.root
    compiled = compile_definition_data(definition_body(), "synthetic-private-runner", set())
    runner._load_workflow = lambda _identity: (value.workflow, compiled)
    lease = CommandLeaseIdentity("wfcmd_" + "a" * 32, "synthetic-private", "lease", 1)
    return runner, lease


@contextmanager
def private_scope(value, lease):
    native_token = engine_module._ACTIVE_NATIVE_REQUEST.set(
        (value.workflow.workflow_id, value.request, lease)
    )
    lease_token = engine_module._ACTIVE_COMMAND_LEASE.set(lease)
    try:
        yield
    finally:
        engine_module._ACTIVE_COMMAND_LEASE.reset(lease_token)
        engine_module._ACTIVE_NATIVE_REQUEST.reset(native_token)


def advance(runner, value, lease, **overrides):
    arguments = dict(
        workflow_id=value.workflow.workflow_id,
        command_id=lease.command_id,
        actor_type="human",
        actor_id=value.workflow.created_actor_id,
    )
    runner._advance(**(arguments | overrides))


def test_runner_dispatches_private_step_and_terminal_without_role_or_public_fallback(lifecycle):
    value = lifecycle
    runner, lease = configured_runner(value)
    original = canonical_json_bytes(value.workflow.runtime_context)
    with private_scope(value, lease):
        advance(runner, value, lease)
        assert value.workflow.state == value.workflow.stage == "COMPLETED"
        assert value.step.state == "SUCCEEDED"
        assert value.terminal.state == "SUCCEEDED"
        advance(runner, value, lease)
    assert canonical_json_bytes(value.workflow.runtime_context) == original
    value.executor.execute.assert_called_once()
    value.executor.allocate_execution.assert_called_once()
    assert value.executor.validate_completion.call_count == 3


@pytest.mark.parametrize(
    "fault", ["family", "owner", "executor", "command", "native_request", "native_lease"]
)
def test_runner_refuses_unoffered_or_foreign_private_context_before_mutation(lifecycle, fault):
    value = lifecycle
    runner, lease = configured_runner(value)
    native = (value.workflow.workflow_id, value.request, lease)
    if fault == "family":
        runner.command_families = frozenset({CommandExecutionFamily.REFERENCE_QUERY})
    elif fault == "owner":
        runner.private_chat_query_owner = None
    elif fault == "executor":
        runner.private_chat_query_executor = None
    elif fault == "native_request":
        native = (native[0], object(), lease)
    elif fault == "native_lease":
        native = (native[0], value.request, replace(lease, lease_generation=2))
    with private_scope(value, lease):
        token = engine_module._ACTIVE_NATIVE_REQUEST.set(native)
        try:
            with pytest.raises(WorkflowError) as error:
                advance(
                    runner,
                    value,
                    lease,
                    **({"command_id": "wfcmd_" + "b" * 32} if fault == "command" else {}),
                )
            assert error.value.code is WorkflowErrorCode.LOCAL_EMBEDDING_EXECUTION_UNAVAILABLE
        finally:
            engine_module._ACTIVE_NATIVE_REQUEST.reset(token)
    value.owner.resolve_submission.assert_not_called()
    value.executor.execute.assert_not_called()
    assert value.workflow.state == "RUNNING" and value.terminal is None


@pytest.mark.parametrize("fault", ["actor", "actor_type", "request", "source"])
def test_runner_private_errors_are_stable_and_never_render_question_or_adapter_details(
    lifecycle, fault
):
    value = lifecycle
    runner, lease = configured_runner(value)
    if fault == "request":
        value.workflow.initial_request = {}
    elif fault == "source":
        value.owner.resolve_submission.side_effect = ValueError("SYNTHETIC_PRIVATE_DO_NOT_RENDER")
    with private_scope(value, lease), pytest.raises(WorkflowError) as error:
        advance(
            runner,
            value,
            lease,
            **(
                {"actor_id": "operator_" + "f" * 32}
                if fault == "actor"
                else {"actor_type": "system"}
                if fault == "actor_type"
                else {}
            ),
        )
    assert error.value.code in {
        WorkflowErrorCode.WORKFLOW_CONCURRENCY_CONFLICT,
        WorkflowErrorCode.LOCAL_EMBEDDING_OUTCOME_INVALID,
    }
    assert "SYNTHETIC_PRIVATE_DO_NOT_RENDER" not in str(error.value)
    assert error.value.__suppress_context__ or fault in {"actor", "actor_type"}
    value.executor.execute.assert_not_called()
    assert value.workflow.state == "RUNNING" and value.terminal is None


@pytest.mark.parametrize("state", ["FAILED", "CANCELLED"])
def test_runner_never_revives_failed_or_cancelled_original_private_work(lifecycle, state):
    value = lifecycle
    runner, lease = configured_runner(value)
    value.workflow.state = state
    before = deepcopy(value.workflow.runtime_context)
    with private_scope(value, lease):
        advance(runner, value, lease)
    assert value.workflow.state == state and value.workflow.runtime_context == before
    value.executor.execute.assert_not_called()


def test_runner_pending_result_returns_without_terminal_or_another_attempt(lifecycle, monkeypatch):
    value = lifecycle
    runner, lease = configured_runner(value)
    pending = Mock(return_value=False)
    monkeypatch.setattr(engine_module, "advance_private_chat_query_step", pending)
    terminal = Mock(side_effect=AssertionError("pending result cannot complete"))
    monkeypatch.setattr(engine_module, "complete_private_chat_query_terminal", terminal)
    with private_scope(value, lease):
        advance(runner, value, lease)
    assert pending.call_args.kwargs["owner"] is value.owner
    assert pending.call_args.kwargs["executor"] is value.executor
    assert pending.call_args.kwargs["request"] == value.request
    assert pending.call_args.kwargs["lease"] == lease
    terminal.assert_not_called()


def test_runner_native_root_uses_private_owner_never_reference_or_index(lifecycle, monkeypatch):
    value = lifecycle
    runner, lease = configured_runner(value)
    runner.sessions = object()
    calls = []

    @contextmanager
    def fenced(factory, **arguments):
        calls.append((factory, arguments))
        yield value.session

    monkeypatch.setattr(engine_module, "native_fenced_runner_transaction", fenced)
    with runner._native_transaction((value.workflow.workflow_id, value.request, lease)) as session:
        assert session is value.session
    assert calls == [
        (
            runner.sessions,
            dict(
                owner=value.owner,
                workflow_id=value.workflow.workflow_id,
                request=value.request,
                lease=lease,
            ),
        )
    ]


@pytest.mark.parametrize("fault", ["family", "owner", "executor"])
def test_runner_refuses_private_mutation_without_the_offered_pair_before_opening_sql(
    lifecycle, monkeypatch, fault
):
    value = lifecycle
    runner, lease = configured_runner(value)
    if fault == "family":
        runner.command_families = frozenset({CommandExecutionFamily.REFERENCE_QUERY})
    elif fault == "owner":
        runner.private_chat_query_owner = None
    else:
        runner.private_chat_query_executor = None
    factory = Mock(side_effect=AssertionError("unoffered private mutation opened SQL"))
    monkeypatch.setattr(engine_module, "native_fenced_runner_transaction", factory)
    with (
        pytest.raises(WorkflowError),
        runner._native_transaction((value.workflow.workflow_id, value.request, lease)),
    ):
        pytest.fail("unoffered private root yielded")
    factory.assert_not_called()


def test_load_private_graph_never_reinterprets_it_as_a_legacy_role_graph(lifecycle):
    value = lifecycle
    runner, _lease = configured_runner(value)
    expected = runner._load_workflow(value.workflow.workflow_id)[1]
    del runner._load_workflow

    @contextmanager
    def read_session():
        yield value.session

    runner.sessions = read_session
    value.session.scalar.return_value = True
    value.session.scalar.side_effect = None
    runner._compiled_for_record = lambda *_args: expected
    workflow, compiled = runner._load_workflow(value.workflow.workflow_id)
    assert workflow is value.workflow and compiled == expected
    value.session.expunge.assert_called_once_with(value.workflow)


def test_run_once_passes_the_private_pair_and_completes_the_original_command(
    lifecycle, monkeypatch
):
    value = lifecycle
    runner, lease = configured_runner(value)
    _fixture, candidate = private_candidate()
    candidate = replace(
        candidate,
        command_id=lease.command_id,
        workflow_id=value.workflow.workflow_id,
        native_request=value.request,
    )
    command = WorkflowCommandRecord(
        command_id=lease.command_id,
        workflow_id=value.workflow.workflow_id,
        command_type="START_WORKFLOW",
        state="LEASED",
        lease_owner=lease.runner_id,
        lease_token=lease.lease_token,
        lease_generation=lease.lease_generation,
        lease_expires_at=datetime.now(UTC) + timedelta(seconds=120),
        actor_type="human",
        actor_id=value.workflow.created_actor_id,
    )
    runner.runner_id = lease.runner_id
    runner.runner_config = SimpleNamespace(poll_interval_seconds=30, command_lease_seconds=120)
    original_get = value.session.get.side_effect
    value.session.get.side_effect = lambda model, identity, **kwargs: (
        command if model is WorkflowCommandRecord else original_get(model, identity, **kwargs)
    )

    @contextmanager
    def read_session():
        yield value.session

    @contextmanager
    def claim_root(_factory):
        yield value.session

    @contextmanager
    def lease_scope(acquired):
        assert acquired == lease
        token = engine_module._ACTIVE_COMMAND_LEASE.set(acquired)
        try:
            yield
        finally:
            engine_module._ACTIVE_COMMAND_LEASE.reset(token)

    runner.sessions = read_session
    runner._ready_command_candidate = lambda *_args: candidate
    runner._command_lease_scope = lease_scope
    claim = Mock(return_value=command)
    monkeypatch.setattr(engine_module, "transaction", claim_root)
    monkeypatch.setattr(engine_module, "claim_command_candidate", claim)
    monkeypatch.setattr(engine_module, "require_command_lease", lambda *_args, **_kw: command)
    assert runner.run_once() is command
    assert command.state == "SUCCEEDED" and value.workflow.state == "COMPLETED"
    assert claim.call_args.kwargs["private_chat_query_owner"] is value.owner
    assert claim.call_args.kwargs["private_chat_query_executor"] is value.executor
    assert claim.call_args.kwargs["reference_query_owner"] is None
    assert claim.call_args.kwargs["local_embedding_owner"] is None
    value.executor.execute.assert_called_once()
    assert engine_module._ACTIVE_NATIVE_REQUEST.get() is None
    assert engine_module._ACTIVE_COMMAND_LEASE.get() is None


@pytest.mark.parametrize("fault", [None, "family", "owner", "executor", "request", "unready"])
def test_private_candidate_readiness_requires_its_own_exact_ports(lifecycle, monkeypatch, fault):
    value = lifecycle
    runner, _lease = configured_runner(value)
    fixture, candidate = private_candidate()

    @contextmanager
    def read_session():
        yield fixture.session

    runner.sessions = read_session
    candidate = replace(candidate, native_request=value.request)
    if fault == "family":
        candidate = replace(candidate, family=CommandExecutionFamily.LOCAL_EMBEDDING)
        runner.command_families = frozenset({candidate.family})
    elif fault == "owner":
        runner.private_chat_query_owner = None
    elif fault == "executor":
        runner.private_chat_query_executor = None
    elif fault == "request":
        candidate = replace(candidate, native_request=None)
    value.executor.evaluate.return_value = RuntimeReadinessReport(
        ()
        if fault != "unready"
        else (RuntimeReadinessCheck("synthetic", ReadinessStatus.FAIL, "UNAVAILABLE", "test"),)
    )
    monkeypatch.setattr(engine_module, "peek_command_candidate", lambda *_args, **_kw: candidate)
    if fault is None:
        assert runner._ready_command_candidate(None) == candidate
        value.executor.evaluate.assert_called_once_with(value.request)
    else:
        with pytest.raises(WorkflowRuntimeNotReady):
            runner._ready_command_candidate(None)
        if fault != "unready":
            value.executor.evaluate.assert_not_called()


def test_unavailable_private_query_cannot_starve_ready_existing_index_work(lifecycle, monkeypatch):
    from tests.unit.local_embedding_admission_fixtures import native_fixture

    value = lifecycle
    runner, _lease = configured_runner(value)
    fixture, private = private_candidate()
    private = replace(private, native_request=value.request)
    index = replace(
        private,
        family=CommandExecutionFamily.LOCAL_EMBEDDING,
        native_request=native_fixture().request,
        created_at=private.created_at + timedelta(seconds=1),
    )
    runner.command_families = frozenset({private.family, index.family})
    runner.private_chat_query_executor.evaluate.return_value = RuntimeReadinessReport(
        (RuntimeReadinessCheck("private", ReadinessStatus.FAIL, "UNAVAILABLE", "test"),)
    )
    runner.local_embedding_owner = Mock()
    runner.local_embedding_executor = Mock()
    runner.local_embedding_executor.evaluate.return_value = RuntimeReadinessReport(())

    @contextmanager
    def read_session():
        yield fixture.session

    runner.sessions = read_session
    monkeypatch.setattr(
        engine_module,
        "peek_command_candidate",
        lambda _session, *, family, **_kw: {private.family: private, index.family: index}[family],
    )
    assert runner._ready_command_candidate(None) is index
    runner.private_chat_query_executor.evaluate.assert_called_once_with(value.request)
    runner.local_embedding_executor.evaluate.assert_called_once_with(index.native_request)


@pytest.mark.parametrize("owner_only", [False, True])
def test_private_composition_rejects_unpaired_ports_before_runtime_io(owner_only):
    with pytest.raises(ValueError, match="private QUERY owner and executor"):
        build_workflow_runtime(
            private_chat_query_owner=Mock(spec=PrivateChatQueryOwnerAdmission)
            if owner_only
            else None,
            private_chat_query_executor=None
            if owner_only
            else Mock(spec=PrivateChatQueryNativeExecutor),
        )


@pytest.mark.parametrize("ports", [False, True])
def test_real_runner_constructor_private_only_never_constructs_a_codex_executor(ports):
    database = create_engine("sqlite://")
    try:
        arguments = dict(
            engine=database,
            settings=WorkflowSettings(),
            runner_config=RunnerConfig(
                version=1,
                poll_interval_seconds=30,
                command_lease_seconds=120,
                max_commands_per_run=1,
            ),
            catalog=Mock(),
            actor_authorizer=Mock(),
            readiness=Mock(),
            available_roles=frozenset(),
            command_families=frozenset({CommandExecutionFamily.PRIVATE_CHAT_QUERY}),
            private_chat_query_owner=Mock(spec=PrivateChatQueryOwnerAdmission) if ports else None,
            private_chat_query_executor=(
                Mock(spec=PrivateChatQueryNativeExecutor) if ports else None
            ),
        )
        if not ports:
            with pytest.raises(ValueError, match="native-only execution requires"):
                WorkflowRunner(**arguments)
        else:
            runner = WorkflowRunner(**arguments)
            assert runner.executor is None
            assert runner.local_embedding_owner is runner.reference_query_owner is None
            assert runner.private_chat_query_owner is arguments["private_chat_query_owner"]
            assert runner.private_chat_query_executor is arguments["private_chat_query_executor"]
    finally:
        database.dispose()
