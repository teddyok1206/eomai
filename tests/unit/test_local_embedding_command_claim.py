"""Metadata/SQL source checks only; real concurrent claims require the guarded DB gate."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from unittest.mock import Mock

import pytest
from eom_workflow_runner.errors import WorkflowError, WorkflowErrorCode
from eom_workflow_runner.local_embedding_admission import LocalEmbeddingOwnerAdmission
from eom_workflow_runner.local_embedding_execution_port import LocalEmbeddingNativeExecutor
from eom_workflow_runner.models import WorkflowCommandRecord, WorkflowInstanceRecord
from eom_workflow_runner.repository import (
    CommandCandidate,
    CommandExecutionFamily,
    claim_command_candidate,
    claim_next_command,
    claimable_command_exists,
    peek_command_candidate,
    workflow_requires_local_embedding,
)
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine import Dialect
from sqlalchemy.orm import Session

from tests.unit.test_local_embedding_submission import SyntheticSubmission, submission_fixture

SQL_DIALECT = cast(type[Dialect], postgresql.dialect)()


def candidate_fixture() -> tuple[
    SyntheticSubmission, WorkflowInstanceRecord, WorkflowCommandRecord
]:
    fixture = submission_fixture()
    result = fixture.submit()
    workflow, command = result.workflow, result.command
    now = datetime.now(UTC)
    command.created_at = now - timedelta(seconds=2)
    command.available_at = now - timedelta(seconds=1)
    command.lease_generation = 0
    command.lease_expires_at = None
    workflow.created_at = now - timedelta(seconds=3)
    fixture.session.execute.return_value.one_or_none.return_value = (command, workflow)
    return fixture, workflow, command


def peek(fixture: SyntheticSubmission) -> CommandCandidate:
    candidate = peek_command_candidate(
        cast(Session, fixture.session), family=CommandExecutionFamily.LOCAL_EMBEDDING
    )
    assert candidate is not None
    return candidate


def claim(
    fixture: SyntheticSubmission, candidate: CommandCandidate
) -> WorkflowCommandRecord | None:
    return claim_command_candidate(
        cast(Session, fixture.session),
        candidate,
        runner_id="synthetic-native-runner",
        lease_seconds=60,
        local_embedding_owner=cast(LocalEmbeddingOwnerAdmission, fixture.owner),
        local_embedding_executor=cast(LocalEmbeddingNativeExecutor, fixture.executor),
    )


def prepare_claim(
    fixture: SyntheticSubmission, workflow: WorkflowInstanceRecord, command: WorkflowCommandRecord
) -> list[str]:
    order: list[str] = []
    original_scalar = fixture.scalar

    def scalar(query: Any) -> Any:
        model = query.column_descriptions[0]["entity"]
        name = "workflow" if model is WorkflowInstanceRecord else "command"
        if model in {WorkflowInstanceRecord, WorkflowCommandRecord}:
            order.append(name)
            assert query.get_execution_options()["populate_existing"] is True
        if model is WorkflowInstanceRecord:
            return workflow
        if model is WorkflowCommandRecord:
            return command
        return original_scalar(query)

    def resolve(*_args: Any, **kwargs: Any) -> Any:
        order.append("owner-before-lease")
        assert kwargs["workflow"] is workflow and kwargs["command"] is command
        assert command.lease_generation == 0 and command.lease_token is None
        return fixture.scope

    def fence(*_args: Any) -> None:
        order.append("owner-late")
        assert command.lease_generation == 1 and command.lease_token is not None

    fixture.session.scalar.side_effect = scalar
    fixture.session.scalar.reset_mock()
    fixture.session.execute.return_value.scalar_one_or_none.return_value = command
    fixture.owner.resolve_claim.side_effect = resolve
    fixture.owner.fence_mutation.side_effect = fence
    return order


@pytest.mark.parametrize("family", list(CommandExecutionFamily))
def test_peek_is_bounded_nonlocking_read_and_contains_no_lease_token(
    family: CommandExecutionFamily,
) -> None:
    fixture, _workflow, command = candidate_fixture()
    candidate = peek_command_candidate(
        cast(Session, fixture.session), family=family, workflow_id=command.workflow_id
    )
    assert candidate is not None and candidate.family is family
    query = fixture.session.execute.call_args.args[0]
    sql = str(query.compile(dialect=SQL_DIALECT))
    assert "LIMIT" in sql and "FOR UPDATE" not in sql
    assert "workflow_commands.created_at, workflow_commands.command_id" in sql
    assert "workflow_commands.workflow_id" in sql
    assert not hasattr(candidate, "lease_token") and not hasattr(candidate, "actor_id")
    assert fixture.owner.resolve_claim.call_count == 0
    assert fixture.owner.fence_mutation.call_count == 0
    assert fixture.executor.evaluate.call_count == 0
    assert command.lease_generation == 0


def test_native_exact_claim_uses_workflow_then_command_and_owner_before_generation() -> None:
    fixture, workflow, command = candidate_fixture()
    candidate = peek(fixture)
    order = prepare_claim(fixture, workflow, command)
    assert claim(fixture, candidate) is command
    assert order[:3] == ["workflow", "command", "owner-before-lease"]
    assert order[-1] == "owner-late"
    assert command.state == "LEASED" and command.lease_generation == 1 and command.attempts == 1
    for call in fixture.session.scalar.call_args_list[:2]:
        sql = str(call.args[0].compile(dialect=SQL_DIALECT))
        assert "FOR UPDATE SKIP LOCKED" in sql
    assert fixture.executor.evaluate.call_count == fixture.executor.execute.call_count == 0


@pytest.mark.parametrize("missing", ["owner", "executor"])
def test_missing_native_port_denies_before_any_query(missing: str) -> None:
    fixture, _workflow, _command = candidate_fixture()
    candidate = peek(fixture)
    fixture.session.reset_mock()
    with pytest.raises(WorkflowError) as failure:
        claim_command_candidate(
            cast(Session, fixture.session),
            candidate,
            runner_id="synthetic-native-runner",
            lease_seconds=60,
            local_embedding_owner=None
            if missing == "owner"
            else cast(LocalEmbeddingOwnerAdmission, fixture.owner),
            local_embedding_executor=None
            if missing == "executor"
            else cast(LocalEmbeddingNativeExecutor, fixture.executor),
        )
    assert failure.value.code is WorkflowErrorCode.LOCAL_EMBEDDING_EXECUTION_UNAVAILABLE
    assert fixture.session.scalar.call_count == fixture.session.execute.call_count == 0


@pytest.mark.parametrize(
    "field", ["attempts", "lease_generation", "current_step_key", "lock_version"]
)
def test_changed_exact_header_is_not_replaced_or_claimed(field: str) -> None:
    fixture, workflow, command = candidate_fixture()
    candidate = peek(fixture)
    prepare_claim(fixture, workflow, command)
    record = workflow if field in {"current_step_key", "lock_version"} else command
    setattr(
        record, field, "complete" if field == "current_step_key" else getattr(record, field) + 1
    )
    assert claim(fixture, candidate) is None
    assert fixture.owner.resolve_claim.call_count == 0 and command.lease_token is None


@pytest.mark.parametrize("locked_row", ["workflow", "command"])
def test_busy_or_disappeared_exact_row_does_not_substitute(locked_row: str) -> None:
    fixture, workflow, command = candidate_fixture()
    candidate = peek(fixture)
    prepare_claim(fixture, workflow, command)
    original = fixture.session.scalar.side_effect

    def scalar(query: Any) -> Any:
        model = query.column_descriptions[0]["entity"]
        missing = WorkflowInstanceRecord if locked_row == "workflow" else WorkflowCommandRecord
        return None if model is missing else original(query)

    fixture.session.scalar.side_effect = scalar
    assert claim(fixture, candidate) is None
    assert fixture.owner.resolve_claim.call_count == 0 and command.lease_token is None


def test_native_expired_reclaim_requires_current_owner_recovery_before_reassignment() -> None:
    fixture, workflow, command = candidate_fixture()
    command.state, command.lease_generation = "PROCESSING", 4
    command.lease_owner, command.lease_token = "old-runner", "wflease_" + "4" * 32
    command.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    candidate = peek(fixture)
    prepare_claim(fixture, workflow, command)
    fixture.owner.resolve_claim.side_effect = WorkflowError(
        WorkflowErrorCode.LOCAL_EMBEDDING_EXECUTION_UNAVAILABLE,
        "synthetic linked recovery admission absent",
    )
    with pytest.raises(WorkflowError):
        claim(fixture, candidate)
    assert command.lease_generation == 4 and command.lease_token == "wflease_" + "4" * 32
    assert command.attempts == 0 and command.state == "PROCESSING"


def test_native_owner_denial_happens_before_new_lease() -> None:
    fixture, workflow, command = candidate_fixture()
    candidate = peek(fixture)
    prepare_claim(fixture, workflow, command)
    fixture.owner.resolve_claim.side_effect = ValueError("SYNTHETIC_SOURCE_REVOKED")
    with pytest.raises(ValueError, match="SYNTHETIC_SOURCE_REVOKED"):
        claim(fixture, candidate)
    assert command.lease_generation == 0 and command.lease_token is None


@pytest.mark.parametrize("nested", [False, True])
def test_exact_claim_requires_active_root_not_a_nested_authority(nested: bool) -> None:
    fixture, _workflow, command = candidate_fixture()
    candidate = peek(fixture)
    fixture.session.in_nested_transaction.side_effect = None
    fixture.session.in_nested_transaction.return_value = nested
    if not nested:
        fixture.session.get_transaction.return_value = None
    with pytest.raises(WorkflowError):
        claim(fixture, candidate)
    assert command.lease_token is None


def test_command_payload_change_without_hash_change_is_detected() -> None:
    fixture, workflow, command = candidate_fixture()
    candidate = peek(fixture)
    prepare_claim(fixture, workflow, command)
    command.payload = {"forged": "value"}
    assert claim(fixture, candidate) is None
    assert command.lease_token is None


def test_malformed_native_snapshot_does_not_become_role_readiness() -> None:
    fixture, workflow, _command = candidate_fixture()
    workflow.initial_request = {"schema_version": "local-embedding-workflow-request/1.1"}
    candidate = peek(fixture)
    assert candidate.family is CommandExecutionFamily.LOCAL_EMBEDDING
    assert candidate.native_request is None


@pytest.mark.parametrize("operation", ["claim", "exists"])
def test_old_claim_and_exists_queries_exclude_native_markers_themselves(operation: str) -> None:
    session = Mock(spec=Session)
    session.execute.return_value.scalar_one_or_none.return_value = None
    session.scalar.return_value = None
    if operation == "claim":
        assert claim_next_command(session, runner_id="legacy", lease_seconds=60) is None
        query = session.execute.call_args.args[0]
    else:
        assert claimable_command_exists(session, workflow_id="workflow_" + "a" * 32) is False
        query = session.scalar.call_args.args[0]
    sql = str(query.compile(dialect=SQL_DIALECT, compile_kwargs={"literal_binds": True}))
    assert "NOT coalesce" in sql
    for marker in (
        "local-embedding-index",
        "local-embedding/1.0",
        "local-embedding-workflow-request/1.0",
        "local-embedding-workflow-request/1.1",
        "incremental-embedding-result@1.0",
    ):
        assert marker in sql
    assert "EXISTS" in sql and "workflow_step_runs.workflow_id" in sql
    assert " LIKE " not in sql and "workflow_events" not in sql


def test_legacy_exact_claim_keeps_generation_without_calling_native_owner() -> None:
    fixture, workflow, command = candidate_fixture()
    candidate = replace(peek(fixture), family=CommandExecutionFamily.ROLE, native_request=None)
    # Source spy ignores the SQL purpose predicate; the guarded DB tests prove it.
    prepare_claim(fixture, workflow, command)
    assert claim(fixture, candidate) is command
    assert fixture.owner.resolve_claim.call_count == fixture.owner.fence_mutation.call_count == 0
    assert command.lease_generation == 1


def test_role_header_cannot_carry_local_embedding_request_even_with_native_ports() -> None:
    fixture, _workflow, command = candidate_fixture()
    candidate = replace(peek(fixture), family=CommandExecutionFamily.ROLE)
    assert candidate.native_request is not None
    fixture.session.reset_mock()
    with pytest.raises(WorkflowError) as failure:
        claim(fixture, candidate)
    assert failure.value.code is WorkflowErrorCode.LOCAL_EMBEDDING_EXECUTION_UNAVAILABLE
    fixture.session.scalar.assert_not_called()
    fixture.session.execute.assert_not_called()
    fixture.owner.resolve_claim.assert_not_called()
    fixture.owner.fence_mutation.assert_not_called()
    assert command.lease_generation == 0 and command.lease_token is None


@pytest.mark.parametrize("native", [False, True])
def test_direct_routing_lookup_reuses_total_predicate_at_exact_pk(native: bool) -> None:
    session = Mock(spec=Session)
    session.scalar.return_value = native
    workflow_id = "workflow_" + "b" * 32
    assert workflow_requires_local_embedding(session, workflow_id=workflow_id) is native
    query = session.scalar.call_args.args[0]
    sql = str(query.compile(dialect=SQL_DIALECT, compile_kwargs={"literal_binds": True}))
    assert workflow_id in sql and "EXISTS" in sql and "coalesce" in sql
    assert "workflow_step_runs.workflow_id" in sql and "workflow_definitions.definition_id" in sql
    assert "FOR UPDATE" not in sql and "workflow_events" not in sql
    assert "incremental-embedding-result@1.0" in sql and "local-embedding-index" in sql


@pytest.mark.parametrize("invalid", [None, 0, 1])
def test_missing_or_invalid_routing_projection_does_not_mean_legacy(invalid: object) -> None:
    session = Mock(spec=Session)
    session.scalar.return_value = invalid
    with pytest.raises(WorkflowError):
        workflow_requires_local_embedding(session, workflow_id="workflow_" + "b" * 32)
