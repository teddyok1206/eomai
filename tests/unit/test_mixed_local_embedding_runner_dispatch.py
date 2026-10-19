"""Exact family2 dispatch through the existing native lease/fence path, no IO."""

from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock

import pytest
from eom_workflow_runner import engine as runner_module
from eom_workflow_runner import native_workflow_transaction as transaction_module
from eom_workflow_runner.engine import WorkflowRunner
from eom_workflow_runner.errors import WorkflowError
from eom_workflow_runner.models import WorkflowCommandRecord

from tests.unit.test_local_embedding_runner_execution import execution_fixture
from tests.unit.test_mixed_local_embedding_owner_admission import mixed_scope


def mixed_execution():
    c = execution_fixture()
    c.scope, c.compiled, _grant = mixed_scope()
    c.workflow.definition_version = "2.0.0"
    c.workflow.definition_hash = c.compiled.sha256
    c.workflow.initial_request = c.workflow.request_payload = c.scope.request.model_dump(
        mode="json"
    )
    return c


def test_unqueued_definition2_reconcile_denies_before_any_global_readiness(monkeypatch):
    c = mixed_execution()
    runner = object.__new__(WorkflowRunner)
    monkeypatch.setattr(runner, "_load_workflow", lambda _: (c.workflow, c.compiled))
    monkeypatch.setattr(
        runner, "_require_runtime_ready", Mock(side_effect=AssertionError("role readiness"))
    )
    with pytest.raises(WorkflowError, match="actual queued command"):
        runner.reconcile(c.workflow.workflow_id)
    runner._require_runtime_ready.assert_not_called()


def test_definition2_advancement_selects_existing_native_branch_only(monkeypatch):
    c = mixed_execution()
    runner = object.__new__(WorkflowRunner)
    monkeypatch.setattr(runner, "_load_workflow", lambda _: (c.workflow, c.compiled))
    advance = Mock()
    monkeypatch.setattr(runner, "_advance_local_embedding", advance)
    runner._advance(
        c.workflow.workflow_id,
        c.lease.command_id,
        "local_indexing_service",
        c.scope.request.actor_context.service_id,
    )
    advance.assert_called_once_with(
        c.workflow,
        c.compiled,
        c.lease.command_id,
        "local_indexing_service",
        c.scope.request.actor_context.service_id,
    )


def test_definition2_requires_and_reuses_exact_active_native_lease_context(monkeypatch):
    c = mixed_execution()
    runner = object.__new__(WorkflowRunner)
    runner.local_embedding_owner, runner.local_embedding_executor = c.owner, c.executor
    runner.runner_config = Mock(poll_interval_seconds=1)
    monkeypatch.setattr(runner, "_fenced_transaction", c.fenced)
    advance = Mock(return_value=False)
    monkeypatch.setattr(runner_module, "advance_local_embedding_step", advance)
    lease_token = runner_module._ACTIVE_COMMAND_LEASE.set(c.lease)
    request_token = runner_module._ACTIVE_NATIVE_REQUEST.set(
        (c.workflow.workflow_id, c.scope.request)
    )
    try:
        runner._advance_local_embedding(
            c.workflow,
            c.compiled,
            c.lease.command_id,
            "local_indexing_service",
            c.scope.request.actor_context.service_id,
        )
        assert advance.call_args.kwargs["request"] == c.scope.request
        assert advance.call_args.kwargs["lease"] == c.lease
        assert advance.call_args.kwargs["fenced_transaction"] == c.fenced
    finally:
        runner_module._ACTIVE_NATIVE_REQUEST.reset(request_token)
        runner_module._ACTIVE_COMMAND_LEASE.reset(lease_token)


@pytest.mark.parametrize("fault", (None, "original", "late_expiry"))
def test_definition2_fenced_transaction_reloads_original_and_rechecks_lease(monkeypatch, fault):
    c = mixed_execution()
    command = WorkflowCommandRecord(
        command_id=c.lease.command_id,
        workflow_id=c.workflow.workflow_id,
        state="PROCESSING",
        lease_owner=c.lease.runner_id,
        lease_token=c.lease.lease_token,
        lease_generation=c.lease.lease_generation,
        lease_expires_at=datetime.now(UTC) + timedelta(seconds=60),
    )
    order = []

    @contextmanager
    def transaction(_):
        yield c.session

    monkeypatch.setattr(transaction_module, "transaction", transaction)
    c.session.scalar.side_effect = lambda _: (order.append("workflow-lock"), c.workflow)[1]

    def execute(_):
        order.append("command-lock")
        result = Mock()
        result.scalar_one_or_none.return_value = command
        return result

    c.session.execute.side_effect = execute
    c.owner.fence_mutation.side_effect = lambda *_: order.append("current-owner")
    if fault == "original":
        c.workflow.initial_request = c.workflow.initial_request | {
            "request_sha256": "sha256:" + "f" * 64
        }

    def perform():
        with transaction_module.native_fenced_runner_transaction(
            object(),
            owner=c.owner,
            workflow_id=c.workflow.workflow_id,
            request=c.scope.request,
            lease=c.lease,
        ):
            order.append("mutation")
            if fault == "late_expiry":
                command.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)

    if fault is None:
        perform()
        assert order == [
            "workflow-lock",
            "command-lock",
            "current-owner",
            "mutation",
            "current-owner",
            "command-lock",
        ]
    else:
        with pytest.raises(ValueError if fault == "original" else WorkflowError):
            perform()
        if fault == "original":
            assert "mutation" not in order and "current-owner" not in order
