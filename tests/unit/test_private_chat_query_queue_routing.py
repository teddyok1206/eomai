"""Typed metadata/compiled SQL, not current permission, actual claims or execution."""

from dataclasses import replace
from inspect import signature
from unittest.mock import Mock

import pytest
from eom_workflow.private_chat_query_execution import PrivateChatQueryWorkflowRequest
from eom_workflow_runner.engine import WorkflowRunner
from eom_workflow_runner.errors import WorkflowError
from eom_workflow_runner.repository import (
    CommandExecutionFamily,
    claim_command_candidate,
    claim_next_command,
    claimable_command_exists,
    peek_command_candidate,
    workflow_requires_local_embedding,
)
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session

from tests.unit.test_local_embedding_command_claim import candidate_fixture
from tests.unit.test_private_chat_query_execution import execution_case


@pytest.mark.parametrize("family", list(CommandExecutionFamily))
def test_private_markers_are_total_in_every_family_selection(family):
    session = Mock(spec=Session)
    session.execute.return_value.one_or_none.return_value = None
    assert peek_command_candidate(session, family=family) is None
    sql = str(
        session.execute.call_args.args[0].compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )
    for marker in (
        "local-embedding-private-chat-query",
        "private-chat-query/1.0",
        "private-chat-query-workflow-request/1.0",
        "PRIVATE_CHAT_QUERY_WORKFLOW_REQUEST",
        "private-chat-query-submission-context/1.0",
        "encode_private_chat_query",
        "embedding-private-chat-query-result@1.0",
    ):
        assert marker in sql
    assert "coalesce" in sql and "EXISTS" in sql and " LIKE " not in sql
    assert "FOR UPDATE" not in sql and "LIMIT" in sql
    if family is not CommandExecutionFamily.PRIVATE_CHAT_QUERY:
        assert "NOT coalesce" in sql


@pytest.mark.parametrize("operation", ["legacy_claim", "exists", "routing"])
def test_legacy_role_and_native_routing_share_the_private_quarantine(operation):
    session = Mock(spec=Session)
    session.execute.return_value.scalar_one_or_none.return_value = None
    session.scalar.return_value = False if operation == "routing" else None
    if operation == "legacy_claim":
        assert claim_next_command(session, runner_id="synthetic", lease_seconds=60) is None
        query = session.execute.call_args.args[0]
    elif operation == "exists":
        assert claimable_command_exists(session) is False
        query = session.scalar.call_args.args[0]
    else:
        assert (
            workflow_requires_local_embedding(session, workflow_id="workflow_" + "1" * 32) is False
        )
        query = session.scalar.call_args.args[0]
    sql = str(query.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
    assert "private-chat-query-submission-context/1.0" in sql and "PRIVATE_CHAT_QUERY" in sql


def private_candidate():
    fixture, workflow, _command = candidate_fixture()
    request, _, _ = execution_case()
    workflow.initial_request = workflow.request_payload = request.model_dump(mode="json")
    workflow.definition_key = request.workflow_definition_key
    workflow.role_schema_version = "private-chat-query/1.0"
    result = peek_command_candidate(
        fixture.session, family=CommandExecutionFamily.PRIVATE_CHAT_QUERY
    )
    assert isinstance(result.native_request, PrivateChatQueryWorkflowRequest)
    fixture.session.add.reset_mock()
    return fixture, result


@pytest.mark.parametrize(
    "family",
    [
        family
        for family in CommandExecutionFamily
        if family is not CommandExecutionFamily.PRIVATE_CHAT_QUERY
    ],
)
def test_admitted_private_candidate_cannot_borrow_role_index_or_reference_ports(family):
    fixture, candidate = private_candidate()
    fixture.session.execute.reset_mock()
    private_owner = Mock()
    with pytest.raises(WorkflowError):
        claim_command_candidate(
            fixture.session,
            replace(candidate, family=family),
            runner_id="synthetic",
            lease_seconds=60,
            local_embedding_owner=Mock(),
            local_embedding_executor=Mock(),
            reference_query_owner=Mock(),
            reference_query_executor=Mock(),
            private_chat_query_owner=private_owner,
            private_chat_query_executor=Mock(),
        )
    fixture.owner.resolve_claim.assert_not_called()
    private_owner.resolve_claim.assert_not_called()
    fixture.session.execute.assert_not_called()
    fixture.session.add.assert_not_called()


@pytest.mark.parametrize("owner,executor", [(None, None), (Mock(), None), (None, Mock())])
def test_admitted_private_candidate_still_requires_both_private_ports(owner, executor):
    fixture, candidate = private_candidate()
    fixture.session.execute.reset_mock()
    with pytest.raises(WorkflowError, match="actual private owner/executor"):
        claim_command_candidate(
            fixture.session,
            candidate,
            runner_id="synthetic",
            lease_seconds=60,
            local_embedding_owner=Mock(),
            local_embedding_executor=Mock(),
            reference_query_owner=Mock(),
            reference_query_executor=Mock(),
            private_chat_query_owner=owner,
            private_chat_query_executor=executor,
        )
    fixture.session.execute.assert_not_called()
    fixture.session.add.assert_not_called()


def test_existing_default_runner_does_not_silently_enable_the_new_private_family():
    assert signature(WorkflowRunner).parameters["command_families"].default == frozenset(
        {
            CommandExecutionFamily.ROLE,
            CommandExecutionFamily.LOCAL_EMBEDDING,
            CommandExecutionFamily.REFERENCE_QUERY,
        }
    )
