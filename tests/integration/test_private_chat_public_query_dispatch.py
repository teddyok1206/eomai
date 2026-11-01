"""Disposable PG private2 queue/claim/fence; source/IAM and native execution are fake ports."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from types import SimpleNamespace

import pytest
from eom_workflow_runner import repository
from eom_workflow_runner.errors import WorkflowError
from eom_workflow_runner.models import WorkflowCommandRecord, WorkflowInstanceRecord
from eom_workflow_runner.native_workflow_transaction import native_fenced_runner_transaction
from eom_workflow_runner.repository import (
    CommandExecutionFamily,
    claim_command_candidate,
    command_lease_identity,
    peek_command_candidate,
)

from tests.integration.test_preset_model_validation_persistence import (
    guarded_engine as guarded_engine,
)
from tests.integration.test_private_chat_document_read import registered as registered
from tests.integration.test_private_chat_public_query_native_persistence import query as query
from tests.integration.test_private_chat_public_query_submission import submission as submission
from tests.unit.local_embedding_admission_fixtures import runtime_profile
from tests.unit.test_private_chat_public_query_submission import submit

pytestmark = [
    pytest.mark.integration,
    pytest.mark.parametrize("registered", [runtime_profile("CPU").space], indirect=True),
]


@pytest.fixture
def pending(submission, monkeypatch):
    value = submission
    old = repository.workflow_definition_is_admitted
    monkeypatch.setattr(
        repository,
        "workflow_definition_is_admitted",
        lambda key, version: (
            (key, version) == ("local-embedding-private-chat-query", "2.0.0") or old(key, version)
        ),
    )
    with value.publisher.sessions.begin() as session:
        started = submit(value, session)
        workflow_id, command_id = started.workflow.workflow_id, started.command.command_id
    return SimpleNamespace(value=value, workflow_id=workflow_id, command_id=command_id)


def candidate_for(pending, session):
    return peek_command_candidate(
        session,
        family=CommandExecutionFamily.PRIVATE_CHAT_QUERY,
        workflow_id=pending.workflow_id,
    )


def claim(pending, session, candidate, *, runner="synthetic-private2-dispatch"):
    return claim_command_candidate(
        session,
        candidate,
        runner_id=runner,
        lease_seconds=120,
        private_chat_query_owner=pending.value.owner,
        private_chat_query_executor=pending.value.executor,
    )


def test_postgres_private2_is_only_selected_by_its_own_family(pending):
    with pending.value.publisher.sessions.begin() as session:
        for family in CommandExecutionFamily:
            result = peek_command_candidate(session, family=family, workflow_id=pending.workflow_id)
            if family is CommandExecutionFamily.PRIVATE_CHAT_QUERY:
                assert result is not None and result.native_request == pending.value.request
            else:
                assert result is None
        row = session.get(WorkflowCommandRecord, pending.command_id)
        assert row.state == "PENDING" and row.lease_generation == row.attempts == 0
    pending.value.executor.execute.assert_not_called()


def test_postgres_private2_claim_and_current_fenced_root_reuse_one_original(pending):
    value = pending.value
    with value.publisher.sessions.begin() as session:
        candidate = candidate_for(pending, session)
        acquired = claim(pending, session, candidate)
        assert acquired.command_id == pending.command_id and acquired.lease_generation == 1
        lease = command_lease_identity(acquired)
    with native_fenced_runner_transaction(
        value.publisher.sessions,
        owner=value.owner,
        workflow_id=pending.workflow_id,
        request=value.request,
        lease=lease,
    ) as session:
        original = session.get(WorkflowInstanceRecord, pending.workflow_id)
        assert original.role_schema_version == "private-chat-query/2.0"
        assert original.initial_request == value.request.model_dump(mode="json")
        original.lock_version += 1
    with value.publisher.sessions.begin() as session:
        assert candidate_for(pending, session) is None
        assert session.get(WorkflowInstanceRecord, pending.workflow_id).lock_version == 2
    value.executor.execute.assert_not_called()


def test_postgres_private2_concurrent_claim_has_exactly_one_winner(pending):
    barrier = Barrier(2)

    def acquire(number):
        with pending.value.publisher.sessions.begin() as session:
            candidate = candidate_for(pending, session)
            assert candidate is not None
            barrier.wait(timeout=15)
            result = claim(pending, session, candidate, runner=f"synthetic-private2-{number}")
            return None if result is None else result.command_id

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(acquire, (1, 2)))
    assert sorted(result for result in results if result is not None) == [pending.command_id]
    with pending.value.publisher.sessions.begin() as session:
        row = session.get(WorkflowCommandRecord, pending.command_id)
        assert row.lease_generation == row.attempts == 1
    pending.value.executor.execute.assert_not_called()


def test_postgres_private2_late_fence_loss_rolls_back_root_without_another_launch(
    pending, monkeypatch
):
    value = pending.value
    with value.publisher.sessions.begin() as session:
        lease = command_lease_identity(claim(pending, session, candidate_for(pending, session)))
    current = value.owner.fence_mutation
    calls = []

    def fence(session, request, original_lease):
        current(session, request, original_lease)
        calls.append(session.get_transaction())
        if len(calls) == 2:
            raise ValueError("SYNTHETIC_LATE_PRIVATE2_SOURCE_LOSS")

    monkeypatch.setattr(value.owner, "fence_mutation", fence)
    with (
        pytest.raises(ValueError, match="SYNTHETIC_LATE_PRIVATE2_SOURCE_LOSS"),
        native_fenced_runner_transaction(
            value.publisher.sessions,
            owner=value.owner,
            workflow_id=pending.workflow_id,
            request=value.request,
            lease=lease,
        ) as session,
    ):
        session.get(WorkflowInstanceRecord, pending.workflow_id).lock_version += 1
    assert len(calls) == 2 and calls[0] is calls[1]
    with value.publisher.sessions.begin() as session:
        assert session.get(WorkflowInstanceRecord, pending.workflow_id).lock_version == 1
        assert session.get(WorkflowCommandRecord, pending.command_id).lease_generation == 1
    value.executor.execute.assert_not_called()


def test_postgres_private2_cannot_claim_without_global_admission(pending, monkeypatch):
    monkeypatch.setattr(repository, "workflow_definition_is_admitted", lambda *_args: False)
    with pytest.raises(WorkflowError), pending.value.publisher.sessions.begin() as session:
        claim(pending, session, candidate_for(pending, session))
    with pending.value.publisher.sessions.begin() as session:
        row = session.get(WorkflowCommandRecord, pending.command_id)
        assert row.state == "PENDING" and row.lease_generation == 0
