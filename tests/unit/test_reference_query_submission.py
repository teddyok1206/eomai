"""Real exact-pair admission with synthetic SQL/IAM submission seams, never a grant."""

from __future__ import annotations

from unittest.mock import Mock

import pytest
from eom_catalog_service.embedding_registry_catalog_adapter import CatalogEmbeddingRegistryVerifier
from eom_identifiers import content_sha256
from eom_workflow_runner import native_start_command
from eom_workflow_runner.errors import WorkflowError, WorkflowErrorCode
from eom_workflow_runner.models import (
    WorkflowCommandRecord,
    WorkflowInstanceRecord,
)
from eom_workflow_runner.reference_query_submission import (
    ReferenceQueryWorkflowSubmitted,
    start_reference_query_in_session,
)
from eom_workflow_runner.repository import CommandType, command_business_fingerprint

from tests.unit.test_reference_query_queue_execution import (
    admitted_query_definition as admitted_query_definition,
)
from tests.unit.test_reference_query_queue_execution import source as source


@pytest.mark.parametrize("source", ("local_embedding_submission", "reference_query_submission"))
def test_shared_command_hash_preserves_the_original_exact_serialization(source):
    values = {
        "workflow_id": "workflow_" + "a" * 32,
        "command_type": "START_WORKFLOW",
        "payload": {},
        "actor_type": "human",
        "actor_id": "operator_" + "b" * 32,
        "source": source,
    }
    assert command_business_fingerprint(
        **(values | {"command_type": CommandType.START_WORKFLOW})
    ) == content_sha256(values)


def submit(value, *, key="synthetic-atomic-query"):
    # A new synthetic call models a new caller root with already committed history.
    before = tuple(value.rows)

    def rollback():
        value.rows[:] = before

    value.session.rollback.side_effect = rollback
    return start_reference_query_in_session(
        value.session,
        definition=value.definition,
        request=value.scope.request,
        idempotency_key=key,
        actor_type="human",
        actor_id=value.scope.request.operator_audit.operator_id,
        owner=value.owner,
        executor=value.executor,
    )


def fresh(value):
    value.rows.clear()
    value.owner.reset_mock()
    return value


def test_atomic_submission_preserves_catalog_root_only_read_contract(source):
    fresh(source)

    def current(session, request):
        CatalogEmbeddingRegistryVerifier._require_similarity_root(session)
        assert request == source.scope.request
        return source.scope

    source.owner.resolve_submission.side_effect = current
    first = submit(source)
    replay = submit(source)
    assert first.workflow_created and first.command_created
    assert not replay.workflow_created and not replay.command_created
    assert replay.workflow is first.workflow and replay.command is first.command


def test_admitted_query_still_requires_current_owner_before_atomic_start(source):
    fresh(source)
    source.owner.resolve_submission.side_effect = ValueError("SYNTHETIC_CURRENT_OWNER_DENIED")
    with pytest.raises(ValueError, match="CURRENT_OWNER_DENIED"):
        submit(source)
    assert not source.rows
    source.owner.resolve_submission.assert_called_once()
    source.executor.execute.assert_not_called()


def test_atomic_query_creates_once_and_replays_original_command_without_launch(
    source, admitted_query_definition
):
    fresh(source)
    depths = []

    def resolve(_session, request):
        depths.append(source.depth)
        assert request == source.scope.request
        return source.scope

    source.owner.resolve_submission.side_effect = resolve
    first = submit(source)
    repeated = submit(source)
    equivalent = submit(source, key="synthetic-equivalent-query-key")
    assert isinstance(first, ReferenceQueryWorkflowSubmitted)
    assert first.workflow_created and first.command_created
    for result in (repeated, equivalent):
        assert result.workflow is first.workflow and result.command is first.command
        assert result.workflow_created is result.command_created is False
    assert len([row for row in source.rows if isinstance(row, WorkflowInstanceRecord)]) == 1
    assert len([row for row in source.rows if isinstance(row, WorkflowCommandRecord)]) == 1
    assert first.command.source == "reference_query_submission"
    assert first.command.idempotency_key == f"start:{first.workflow.workflow_id}"
    assert depths == [0] * 12
    source.executor.execute.assert_not_called()
    source.executor.evaluate.assert_not_called()
    source.session.commit.assert_not_called()
    source.session.rollback.assert_not_called()


@pytest.mark.parametrize("when", (1, 2, 3, 4))
def test_current_owner_denial_rolls_back_both_new_rows(source, admitted_query_definition, when):
    fresh(source)
    count = 0

    def deny(_session, _request):
        nonlocal count
        count += 1
        if count == when:
            raise ValueError("SYNTHETIC_CURRENT_OWNER_REVOKED")
        return source.scope

    source.owner.resolve_submission.side_effect = deny
    with pytest.raises(ValueError, match="CURRENT_OWNER_REVOKED"):
        submit(source)
    assert not source.rows
    source.executor.execute.assert_not_called()


def test_queue_failure_cannot_leave_a_dangling_workflow(
    source, admitted_query_definition, monkeypatch
):
    fresh(source)
    failed = Mock(side_effect=ValueError("SYNTHETIC_ENQUEUE_FAILED"))
    monkeypatch.setattr(native_start_command, "enqueue_command", failed)
    with pytest.raises(ValueError, match="ENQUEUE_FAILED"):
        submit(source)
    assert not source.rows
    failed.assert_called_once()


@pytest.mark.parametrize(
    "field,value",
    (
        ("payload", {"changed": True}),
        ("actor_id", "operator_" + "0" * 32),
        ("source", "local_embedding_submission"),
        ("request_hash", "sha256:" + "0" * 64),
        ("idempotency_key", "another-start"),
    ),
)
def test_changed_original_command_fails_without_repair(
    source, admitted_query_definition, field, value
):
    fresh(source)
    original = submit(source)
    setattr(original.command, field, value)
    before = tuple(source.rows)
    with pytest.raises(ValueError, match="REFERENCE_QUERY_SUBMISSION_REPLAY_INVALID"):
        submit(source)
    assert tuple(source.rows) == before and getattr(original.command, field) == value


def test_missing_start_is_not_recreated_for_an_existing_workflow(source, admitted_query_definition):
    fresh(source)
    original = submit(source)
    source.rows.remove(original.command)
    before = tuple(source.rows)
    with pytest.raises(ValueError, match="REFERENCE_QUERY_SUBMISSION_REPLAY_INVALID"):
        submit(source)
    assert tuple(source.rows) == before


def test_nested_entry_fails_before_owner_or_new_rows(source, admitted_query_definition):
    fresh(source)
    with source.savepoint(), pytest.raises(WorkflowError) as error:
        submit(source)
    assert error.value.code is WorkflowErrorCode.ACTOR_AUTHORIZATION_UNAVAILABLE
    assert not source.rows
    source.owner.resolve_submission.assert_not_called()
