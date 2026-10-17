"""Actual temporary command/Job metadata; private step/source authority is synthetic."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from eom_orchestrator.models import Base, JobRecord
from eom_workflow_runner import private_chat_query_command_lineage as lineage
from eom_workflow_runner import private_chat_query_owner_admission as owner_module
from eom_workflow_runner.models import (
    WorkflowCommandRecord,
    WorkflowDefinitionRecord,
    WorkflowInstanceRecord,
    WorkflowStepRunRecord,
)
from eom_workflow_runner.private_chat_query_owner_admission import (
    CatalogPrivateChatQueryOwnerAdmission,
)
from eom_workflow_runner.repository import CommandLeaseIdentity, CommandType, enqueue_command

from tests.unit.test_private_chat_query_native_executor import make_private_executor_case
from tests.unit.test_private_chat_query_owner_admission import seed_owner_rows


def make_continuation_case(tmp_path, monkeypatch, *, source=None):
    query = make_private_executor_case(tmp_path, monkeypatch, source=source)
    if query.publisher.engine.dialect.name == "sqlite":
        Base.metadata.create_all(
            query.publisher.engine,
            tables=[
                WorkflowDefinitionRecord.__table__,
                WorkflowInstanceRecord.__table__,
                WorkflowCommandRecord.__table__,
                WorkflowStepRunRecord.__table__,
            ],
        )
    declared = seed_owner_rows(query.publisher, query.request, query.source.projection.origin)
    query.workflow.workflow_id = declared.workflow_id
    query.step.workflow_id = declared.workflow_id
    original_lease = CommandLeaseIdentity(
        declared.command_id, "synthetic-original", "wflease_" + uuid4().hex, 1
    )
    with query.root() as session:
        launch = query.service.allocate_execution(
            session=session,
            workflow=query.workflow,
            step=query.step,
            request=query.request,
            command_lease=original_lease,
        )
    with query.publisher.sessions.begin() as session:
        workflow = session.get(WorkflowInstanceRecord, declared.workflow_id)
        workflow.state = "RUNNING"
        original = session.get(WorkflowCommandRecord, declared.command_id)
        # Fixture declaration only, not evidence of actual START execution.
        original.state, original.attempts, original.lease_generation = "SUCCEEDED", 1, 1
        original.lease_owner, original.lease_token = (
            original_lease.runner_id,
            original_lease.lease_token,
        )
        original.lease_expires_at = datetime.now(UTC) + timedelta(minutes=5)
    monkeypatch.setattr(lineage, "native_application_step", lambda *_args: query.step)
    monkeypatch.setattr(owner_module, "native_application_step", lambda *_args: query.step)
    return SimpleNamespace(
        query=query,
        declared=declared,
        launch=launch,
        owner=CatalogPrivateChatQueryOwnerAdmission(query.source.owner),
    )


@pytest.fixture
def continuation(tmp_path, monkeypatch):
    return make_continuation_case(tmp_path, monkeypatch)


def enqueue_continuation(value, *, parent_id=None, source=None, payload=None, key=None):
    parent_id = value.declared.command_id if parent_id is None else parent_id
    with value.query.publisher.sessions.begin() as session:
        command, created = enqueue_command(
            session,
            workflow_id=value.declared.workflow_id,
            command_type=CommandType.ADVANCE_WORKFLOW,
            payload={"step_run_id": value.query.step.step_run_id} if payload is None else payload,
            actor_type="human",
            actor_id=value.query.source.projection.origin.actor_id,
            source=lineage.PRIVATE_CHAT_QUERY_CONTINUATION_SOURCE if source is None else source,
            idempotency_key=lineage.private_chat_query_continuation_key(
                value.query.step.step_run_id, parent_id
            )
            if key is None
            else key,
        )
        return command.command_id, created


def resolve_continuation(value, command_id):
    with value.query.publisher.sessions.begin() as session:
        value.query.source.fault.session = session
        workflow = session.get(WorkflowInstanceRecord, value.declared.workflow_id)
        command = session.get(WorkflowCommandRecord, command_id)
        result = value.owner.resolve_claim(
            session, workflow=workflow, command=command, request=value.query.request
        )
        assert command.state == "PENDING" and command.lease_generation == 0
        assert not session.new and not session.dirty
        return result


def test_exact_private_continuation_reuses_original_allocated_execution(continuation):
    value = continuation
    command_id, created = enqueue_continuation(value)
    assert created
    assert enqueue_continuation(value) == (command_id, False)
    result = resolve_continuation(value, command_id)
    assert result.projection.origin == value.query.source.projection.origin
    launch, history = value.query.history()
    assert launch == value.launch and len(history.records) == 1 and value.query.encodes == 0


def test_second_poll_links_successful_predecessor_and_same_original_start(continuation):
    value = continuation
    first, _ = enqueue_continuation(value)
    resolve_continuation(value, first)
    with value.query.publisher.sessions.begin() as session:
        row = session.get(WorkflowCommandRecord, first)
        row.state, row.attempts, row.lease_generation = "SUCCEEDED", 1, 1
        row.lease_owner, row.lease_token = "synthetic-continuation", "wflease_" + uuid4().hex
        row.lease_expires_at = datetime.now(UTC) + timedelta(minutes=1)
    second, _ = enqueue_continuation(value, parent_id=first)
    assert (
        resolve_continuation(value, second).projection.origin
        == value.query.source.projection.origin
    )
    assert value.query.history()[0] == value.launch and not value.query.runs


@pytest.mark.parametrize("state", ["PENDING", "PROCESSING", "FAILED", "CANCELLED"])
def test_parent_must_be_successful_not_pending_or_failed(continuation, state):
    value = continuation
    command_id, _ = enqueue_continuation(value)
    with value.query.publisher.sessions.begin() as session:
        session.get(WorkflowCommandRecord, value.declared.command_id).state = state
    before = len(value.query.source.events)
    with pytest.raises(ValueError, match="PRIVATE_CHAT_QUERY_CONTINUATION_PARENT_UNAVAILABLE"):
        resolve_continuation(value, command_id)
    assert len(value.query.source.events) == before and not value.query.runs


@pytest.mark.parametrize("fault", ["source", "payload", "key", "parent"])
def test_forged_continuation_cannot_borrow_original_private_execution(continuation, fault):
    value = continuation
    args = {}
    if fault == "source":
        args["source"] = "reference-query-owner"
    elif fault == "payload":
        args["payload"] = {"step_run_id": "steprun_" + "f" * 32}
    elif fault == "key":
        args["key"] = "untrusted-retry-key"
    else:
        args["parent_id"] = "wfcmd_" + "f" * 32
    command_id, _ = enqueue_continuation(value, **args)
    before = len(value.query.source.events)
    with pytest.raises(ValueError):
        resolve_continuation(value, command_id)
    assert len(value.query.source.events) == before and not value.query.runs


def test_failed_original_job_cannot_be_observed_as_a_new_execution(continuation):
    value = continuation
    command_id, _ = enqueue_continuation(value)
    from eom_orchestrator.native_private_chat_query_coordinator import (
        NativePrivateChatQueryCoordinator,
    )

    with value.query.publisher.sessions.begin() as session:
        NativePrivateChatQueryCoordinator(value.query.request, value.launch).record_known_failure(
            session
        )
    with pytest.raises(ValueError, match="PRIVATE_CHAT_QUERY_ORIGINAL_EXECUTION_UNAVAILABLE"):
        resolve_continuation(value, command_id)
    with value.query.publisher.sessions() as session:
        assert session.get(JobRecord, value.launch.native_launch_job_id).status == "FAILED"
    assert not value.query.runs


@pytest.mark.parametrize(
    "field,bad",
    [
        ("attempts", 0),
        ("lease_generation", 0),
        ("lease_owner", None),
        ("lease_token", None),
        ("lease_expires_at", None),
    ],
)
def test_terminal_label_without_acquisition_metadata_is_not_success_proof(continuation, field, bad):
    value = continuation
    command_id, _ = enqueue_continuation(value)
    with value.query.publisher.sessions.begin() as session:
        setattr(session.get(WorkflowCommandRecord, value.declared.command_id), field, bad)
    with pytest.raises(ValueError, match="PRIVATE_CHAT_QUERY_CONTINUATION_PARENT_UNAVAILABLE"):
        resolve_continuation(value, command_id)
    assert not value.query.runs


def test_expired_historical_parent_lease_is_metadata_not_current_authority(continuation):
    value = continuation
    with value.query.publisher.sessions.begin() as session:
        session.get(WorkflowCommandRecord, value.declared.command_id).lease_expires_at = (
            datetime.now(UTC) - timedelta(minutes=1)
        )
    command_id, _ = enqueue_continuation(value)
    assert (
        resolve_continuation(value, command_id).projection.origin
        == value.query.source.projection.origin
    )
    assert not value.query.runs


@pytest.mark.parametrize(
    "step,parent",
    [(None, "wfcmd_" + "1" * 32), ("steprun_" + "1" * 32, None), ("wrong", "wfcmd_" + "1" * 32)],
)
def test_continuation_key_rejects_untyped_identifiers(step, parent):
    with pytest.raises(ValueError, match="PRIVATE_CHAT_QUERY_COMMAND_CONTEXT_INVALID"):
        lineage.private_chat_query_continuation_key(step, parent)
