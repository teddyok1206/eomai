"""Synthetic Runner state/owner/executor, not private SQL/source/native admission.

Control/source value shapes are revalidated, but the private step is an ORM view
and the receipt validator/physical executor are explicit mocks in this suite.
"""

from contextlib import contextmanager
from copy import deepcopy
from unittest.mock import Mock

import pytest
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_workflow.private_chat_query_submission_context import (
    build_private_chat_query_submission_context,
)
from eom_workflow.private_chat_query_workflow import (
    PrivateChatQueryStepOutput,
    PrivateChatQueryWorkflowDefinition,
)
from eom_workflow_runner import private_chat_query_step_execution as execution
from eom_workflow_runner.errors import WorkflowError
from eom_workflow_runner.models import WorkflowInstanceRecord, WorkflowStepRunRecord
from eom_workflow_runner.private_chat_query_admission import PrivateChatQueryOwnerAdmission
from eom_workflow_runner.private_chat_query_execution_port import (
    PrivateChatQueryNativeExecutor,
    PrivateChatQueryStepPending,
)
from eom_workflow_runner.repository import CommandLeaseIdentity

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_private_chat_query_source_owner import make_private_source_case
from tests.unit.test_private_chat_query_terminal import private_terminal as private_terminal
from tests.unit.test_private_chat_query_workflow import completed as completed
from tests.unit.test_private_chat_query_workflow import definition_body


@pytest.fixture
def lifecycle(private_terminal, tmp_path, monkeypatch):
    value = private_terminal
    fixed = PrivateChatQueryWorkflowDefinition.model_validate(definition_body())
    source = make_private_source_case(
        tmp_path, monkeypatch, definition_sha256=sha256_bytes(canonical_json_bytes(fixed))
    )
    with source.publisher.sessions.begin() as session:
        source.fault.session = session
        scope = source.owner.resolve_sources(session, source.request, source.projection.origin)
    value.request, value.definition = source.request, fixed
    value.workflow.initial_request = value.request.model_dump(mode="json")
    value.workflow.definition_hash = value.request.workflow_definition_sha256
    value.workflow.runtime_context = build_private_chat_query_submission_context(
        value.request, scope.projection.origin
    ).model_dump(mode="json")
    value.workflow.created_actor_id = scope.projection.origin.actor_id
    value.workflow.current_step_key = "encode_private_chat_query"
    value.step.input_pointer_manifest = {"workflow_request_sha256": value.request.request_sha256}
    value.step.state, value.step.platform_job_id, value.step.output_pointer_manifest = (
        "RUNNING",
        None,
        None,
    )
    value.owner = Mock(spec=PrivateChatQueryOwnerAdmission)
    value.owner.resolve_submission.return_value = scope
    value.executor = Mock(spec=PrivateChatQueryNativeExecutor)
    value.executor.validate_completion.side_effect = lambda **kwargs: kwargs["output"]
    value.depth, value.roots, value.fail_exit = 0, 0, None
    lease = CommandLeaseIdentity("wfcmd_" + "a" * 32, "synthetic-private", "lease", 1)

    def get(model, identifier, **_kw):
        if model is WorkflowInstanceRecord and identifier == value.workflow.workflow_id:
            return value.workflow
        if model is WorkflowStepRunRecord and identifier == value.step.step_run_id:
            return value.step
        return None

    @contextmanager
    def root():
        assert value.depth == 0
        value.depth, value.roots = 1, value.roots + 1
        snapshots = [
            (
                row,
                {
                    column.name: deepcopy(getattr(row, column.name))
                    for column in row.__table__.columns
                },
            )
            for row in (value.workflow, value.step)
        ]
        try:
            yield value.session
            if value.fail_exit == value.roots:
                raise WorkflowError(
                    execution.WorkflowErrorCode.WORKFLOW_CONCURRENCY_CONFLICT,
                    "synthetic late authorization withdrawal",
                )
        except BaseException:
            for row, snapshot in snapshots:
                for name, current in snapshot.items():
                    setattr(row, name, current)
            raise
        finally:
            value.depth = 0

    def allocate(**_kwargs):
        assert value.depth == 1

    def run(**_kwargs):
        assert value.depth == 0, "SQL/source root survived physical execution"
        return value.output

    value.session.get.side_effect = get
    value.executor.allocate_execution.side_effect = allocate
    value.executor.execute.side_effect = run
    monkeypatch.setattr(execution, "native_application_step", lambda *_args: value.step)

    def advance(**overrides):
        return execution.advance_private_chat_query_step(
            **(
                dict(
                    workflow=value.workflow,
                    definition=fixed,
                    request=value.request,
                    lease=lease,
                    owner=value.owner,
                    executor=value.executor,
                    fenced_transaction=root,
                    actor_type="human",
                    actor_id=value.workflow.created_actor_id,
                )
                | overrides
            )
        )

    def complete(**overrides):
        return execution.complete_private_chat_query_terminal(
            **(
                dict(
                    workflow_id=value.workflow.workflow_id,
                    request=value.request,
                    lease=lease,
                    executor=value.executor,
                    fenced_transaction=root,
                    actor_type="human",
                    actor_id=value.workflow.created_actor_id,
                )
                | overrides
            )
        )

    value.advance, value.complete, value.root = advance, complete, root
    return value


def test_running_private_step_success_and_terminal_preserve_context_without_sql_through_execute(
    lifecycle,
):
    value = lifecycle
    context = canonical_json_bytes(value.workflow.runtime_context)
    assert value.advance() is True
    assert value.step.state == "SUCCEEDED" and value.workflow.current_step_key == "complete"
    assert value.step.output_pointer_manifest == value.output.model_dump(mode="json")
    value.complete()
    assert value.workflow.state == "COMPLETED"
    assert canonical_json_bytes(value.workflow.runtime_context) == context
    value.executor.execute.assert_called_once()
    value.complete()
    value.executor.execute.assert_called_once()


def test_successful_private_step_replay_validates_receipt_without_another_execution(lifecycle):
    value = lifecycle
    value.step.state = "SUCCEEDED"
    value.step.platform_job_id = value.output.receipt_owner_job_id
    value.step.output_pointer_manifest = value.output.model_dump(mode="json")
    assert value.advance() is True
    value.executor.execute.assert_not_called()
    value.executor.allocate_execution.assert_not_called()
    value.executor.validate_completion.assert_called_once()


@pytest.mark.parametrize("fault", ["foreign", "malformed", "replacement"])
def test_wrong_private_outcome_never_promotes_step_or_terminal(lifecycle, fault):
    value = lifecycle
    if fault == "foreign":
        value.executor.execute.side_effect = lambda **_kw: (
            PrivateChatQueryStepOutput.model_validate(
                seal(
                    value.output.model_dump(mode="json") | {"workflow_id": "workflow_" + "f" * 32},
                    "output_sha256",
                )
            )
        )
    elif fault == "malformed":
        value.executor.execute.side_effect = lambda **_kw: {"private_question": "DO_NOT_DISCLOSE"}
    else:
        value.executor.validate_completion.side_effect = lambda **_kw: {}
    with pytest.raises(WorkflowError) as error:
        value.advance()
    assert "DO_NOT_DISCLOSE" not in str(error.value)
    assert value.step.state == "RUNNING" and value.step.output_pointer_manifest is None
    assert value.workflow.current_step_key == "encode_private_chat_query"


def test_unproven_pending_launch_cannot_enqueue_another_operation(lifecycle, monkeypatch):
    value = lifecycle
    value.executor.execute.side_effect = lambda **_kw: PrivateChatQueryStepPending(
        "job_" + "f" * 32, "sha256:" + "f" * 64, "BUSY"
    )
    missing = Mock(return_value=None)
    monkeypatch.setattr(execution, "read_native_query_launch", missing)
    # The synthetic Session has no original native launch; no recovery is invented.
    with pytest.raises(WorkflowError):
        value.advance()
    missing.assert_called_once()
    assert (
        value.step.state == "RUNNING"
        and value.workflow.current_step_key == "encode_private_chat_query"
    )


def test_late_completion_fence_rolls_back_step_promotion(lifecycle):
    value = lifecycle
    value.fail_exit = 2
    with pytest.raises(WorkflowError):
        value.advance()
    assert value.step.state == "RUNNING" and value.step.output_pointer_manifest is None
    assert value.workflow.current_step_key == "encode_private_chat_query"


@pytest.mark.parametrize(
    "actor_type,actor_id", [("system", None), ("human", "operator_" + "f" * 32)]
)
def test_private_progression_rejects_wrong_audit_actor_before_source_read(
    lifecycle, actor_type, actor_id
):
    value = lifecycle
    with pytest.raises(WorkflowError):
        value.advance(actor_type=actor_type, actor_id=actor_id or value.workflow.created_actor_id)
    value.owner.resolve_submission.assert_not_called()
    value.executor.allocate_execution.assert_not_called()


def test_private_terminal_audit_actor_cannot_differ_from_original_operator(lifecycle):
    value = lifecycle
    value.advance()
    with pytest.raises(WorkflowError):
        value.complete(actor_id="operator_" + "f" * 32)
    assert value.workflow.state == "RUNNING"


def test_original_start_resolves_sources_before_writing_and_allocates_in_same_root(
    lifecycle, monkeypatch
):
    value = lifecycle
    value.workflow.state, value.step.state = "REQUESTED", "READY"
    scope = value.owner.resolve_submission.return_value

    def resolve(*_args):
        assert value.workflow.state == "REQUESTED" and value.depth == 1
        return scope

    def create(_session, **kwargs):
        assert kwargs["max_attempts"] == 1
        assert kwargs["input_pointer_manifest"] == {
            "workflow_request_sha256": value.request.request_sha256
        }
        return value.step

    value.owner.resolve_submission.side_effect = resolve
    monkeypatch.setattr(execution, "native_application_step", lambda *_args: None)
    monkeypatch.setattr(execution, "create_step_run", create)
    assert value.advance() is True
    assert value.workflow.state == "RUNNING" and value.step.state == "SUCCEEDED"
    value.executor.allocate_execution.assert_called_once()


def test_original_start_with_unexplained_existing_step_is_not_repaired(lifecycle):
    value = lifecycle
    value.workflow.state = "REQUESTED"
    with pytest.raises(WorkflowError):
        value.advance()
    assert value.workflow.state == "REQUESTED"
    value.executor.execute.assert_not_called()


def test_failed_initial_allocation_rolls_back_workflow_start_before_physical_work(
    lifecycle, monkeypatch
):
    value = lifecycle
    value.workflow.state, value.step.state = "REQUESTED", "READY"
    monkeypatch.setattr(execution, "native_application_step", lambda *_args: None)
    monkeypatch.setattr(execution, "create_step_run", lambda *_args, **_kw: value.step)
    value.executor.allocate_execution.side_effect = ValueError("synthetic allocation aborted")
    with pytest.raises(ValueError, match="synthetic allocation aborted"):
        value.advance()
    assert value.workflow.state == "REQUESTED" and value.step.state == "READY"
    value.executor.execute.assert_not_called()


@pytest.mark.parametrize("state", ["pending", "failed", "completed"])
def test_pending_observation_requires_original_real_job_history(tmp_path, monkeypatch, state):
    from eom_orchestrator.native_private_chat_query_coordinator import (
        NativePrivateChatQueryCoordinator,
    )

    from tests.unit.test_private_chat_query_command_lineage import make_continuation_case

    value = make_continuation_case(tmp_path, monkeypatch)
    pending = PrivateChatQueryStepPending(
        value.launch.native_launch_job_id, value.launch.association_sha256, "BUSY"
    )
    if state == "failed":
        with value.query.publisher.sessions.begin() as session:
            NativePrivateChatQueryCoordinator(
                value.query.request, value.launch
            ).record_known_failure(session)
    expected = value.query.execute() if state == "completed" else None
    with value.query.publisher.sessions.begin() as session:
        if state == "failed":
            with pytest.raises(ValueError, match="PRIVATE_CHAT_QUERY_PENDING_HISTORY_INVALID"):
                execution._pending(
                    session,
                    value.query.request,
                    value.query.workflow,
                    value.query.step,
                    pending,
                    value.declared.context,
                )
        else:
            assert (
                execution._pending(
                    session,
                    value.query.request,
                    value.query.workflow,
                    value.query.step,
                    pending,
                    value.declared.context,
                )
                == expected
            )
    assert value.query.encodes == (1 if state == "completed" else 0)
