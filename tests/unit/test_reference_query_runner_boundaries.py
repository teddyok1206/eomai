"""Exact QUERY admission never substitutes for paired runtime owners or source grants."""

from __future__ import annotations

from typing import Any, cast
from unittest.mock import Mock

import pytest
from eom_workflow.admission import workflow_definition_is_admitted
from eom_workflow.compiler import compile_definition_data
from eom_workflow.models import WorkflowRequest
from eom_workflow.reference_query_execution import ReferenceQueryWorkflowRequest
from eom_workflow.reference_query_workflow import (
    REFERENCE_QUERY_EXECUTION_PROTOCOL,
    REFERENCE_QUERY_WORKFLOW_KEY,
)
from eom_workflow_runner.errors import WorkflowError, WorkflowErrorCode
from eom_workflow_runner.local_embedding_admission import LocalEmbeddingOwnerAdmission
from eom_workflow_runner.local_embedding_execution_port import LocalEmbeddingNativeExecutor
from eom_workflow_runner.models import WorkflowDefinitionRecord
from eom_workflow_runner.repository import (
    CommandExecutionFamily,
    admitted_workflow_definition,
    claim_command_candidate,
    claim_next_command,
    claimable_command_exists,
    create_workflow_instance,
    import_workflow_definition,
    peek_command_candidate,
    workflow_definition_admission_statuses,
    workflow_requires_local_embedding,
)
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine import Dialect
from sqlalchemy.orm import Session

from tests.unit.inference_transfer_fixtures import sha
from tests.unit.test_local_embedding_command_claim import (
    candidate_fixture,
    peek,
    prepare_claim,
)
from tests.unit.test_reference_query_execution_contracts import case
from tests.unit.test_reference_query_workflow_contracts import definition_body

SQL_DIALECT = cast(type[Dialect], postgresql.dialect)()


def record(*, active: bool = False) -> WorkflowDefinitionRecord:
    compiled = compile_definition_data(definition_body(), "synthetic-query-only", set())
    return WorkflowDefinitionRecord(
        definition_id="wfdef_" + "b" * 32,
        definition_key=compiled.definition.definition_key,
        definition_version=compiled.definition.definition_version,
        schema_version=compiled.definition.schema_version,
        canonical_definition=compiled.as_dict(),
        definition_hash=compiled.sha256,
        active=active,
        source_path=compiled.source_path,
    )


@pytest.fixture(scope="module")
def query_request() -> ReferenceQueryWorkflowRequest:
    return case().request


def test_exact_query_import_admission_is_distinct_from_native_execution() -> None:
    compiled = compile_definition_data(definition_body(), "synthetic-query-import", set())
    session = Mock(spec=Session)
    session.scalar.return_value = None
    imported, created = import_workflow_definition(session, compiled)
    assert created and imported.active is True
    assert imported.definition_hash == compiled.sha256
    session.scalars.return_value = (imported,)
    (status,) = workflow_definition_admission_statuses(session)
    assert status.role_protocol_version == REFERENCE_QUERY_EXECUTION_PROTOCOL
    assert status.role_protocol_error is None
    assert status.active is status.admitted is status.accepts_new_work is True
    session.reset_mock()
    session.scalar.return_value = imported
    assert (
        admitted_workflow_definition(
            session,
            definition_key=REFERENCE_QUERY_WORKFLOW_KEY,
            definition_version="1.0.0",
        )
        is imported
    )
    session.scalar.assert_called_once()


def test_query_admission_never_reactivates_an_existing_inactive_snapshot() -> None:
    existing = record(active=False)
    compiled = compile_definition_data(definition_body(), "synthetic-old-query", set())
    session = Mock(spec=Session)
    session.scalar.return_value = existing
    imported, created = import_workflow_definition(session, compiled)
    assert imported is existing and not created and imported.active is False
    session.add.assert_not_called()
    session.flush.assert_not_called()
    session.scalars.return_value = (existing,)
    (status,) = workflow_definition_admission_statuses(session)
    assert status.admitted and not status.active and not status.accepts_new_work


@pytest.mark.parametrize("active", (False, True))
def test_query_status_keeps_activation_separate_from_exact_pair_admission(active: bool) -> None:
    definition = record(active=active)
    session = Mock(spec=Session)
    session.scalars.return_value = (definition,)
    (status,) = workflow_definition_admission_statuses(session)
    assert status.role_protocol_version == REFERENCE_QUERY_EXECUTION_PROTOCOL
    assert status.active is active
    assert status.admitted and status.accepts_new_work is active
    assert workflow_definition_is_admitted(definition.definition_key, definition.definition_version)


@pytest.mark.parametrize("change", ("hash", "version", "schema", "canonical_key", "extra"))
@pytest.mark.parametrize("active", (False, True))
def test_stored_query_identity_and_hash_are_revalidated(change: str, active: bool) -> None:
    definition = record(active=active)
    if change == "hash":
        definition.definition_hash = sha("0")
    elif change == "version":
        definition.definition_version = "1.0.1"
    elif change == "schema":
        definition.schema_version = "1.1"
    elif change == "canonical_key":
        definition.canonical_definition["definition_key"] = "local-embedding-index"
    else:
        definition.canonical_definition["authority"] = "ADMIN"
    session = Mock(spec=Session)
    session.scalars.return_value = (definition,)
    if active or change != "version":
        with pytest.raises(WorkflowError) as failure:
            workflow_definition_admission_statuses(session)
        assert failure.value.code is WorkflowErrorCode.WORKFLOW_DEFINITION_INVALID
    else:
        (status,) = workflow_definition_admission_statuses(session)
        assert status.role_protocol_version is None and status.role_protocol_error is not None
        assert status.accepts_new_work is False


@pytest.mark.parametrize("matching", (True, False))
@pytest.mark.parametrize("ports", (False, True))
def test_query_submission_is_stable_unavailable_or_cross_purpose_before_lookup(
    query_request: ReferenceQueryWorkflowRequest, matching: bool, ports: bool
) -> None:
    definition = record()
    if not matching:
        definition.definition_key = "local-embedding-index"
    session = Mock(spec=Session)
    with pytest.raises(WorkflowError) as failure:
        create_workflow_instance(
            session,
            definition=definition,
            request=query_request,
            idempotency_key="synthetic-query-unoffered",
            actor_type="human",
            actor_id=query_request.operator_audit.operator_id,
            runtime_context={} if ports else None,
            local_embedding_owner=cast(LocalEmbeddingOwnerAdmission, Mock()) if ports else None,
            local_embedding_executor=cast(LocalEmbeddingNativeExecutor, Mock()) if ports else None,
        )
    expected = (
        WorkflowErrorCode.LOCAL_EMBEDDING_EXECUTION_UNAVAILABLE
        if matching
        else WorkflowErrorCode.WORKFLOW_REQUEST_INVALID
    )
    assert failure.value.code is expected
    assert session.mock_calls == []


@pytest.mark.parametrize("kind", ("document", "role"))
def test_query_definition_rejects_other_request_types_before_lookup(kind: str) -> None:
    fixture, _workflow, _command = candidate_fixture()
    request = (
        fixture.scope.request
        if kind == "document"
        else cast(WorkflowRequest, Mock(spec=WorkflowRequest))
    )
    session = Mock(spec=Session)
    with pytest.raises(WorkflowError) as failure:
        create_workflow_instance(
            session,
            definition=record(),
            request=request,
            idempotency_key="synthetic-query-cross-purpose",
            actor_type="human",
            actor_id="operator_" + "1" * 32,
        )
    assert failure.value.code is WorkflowErrorCode.WORKFLOW_REQUEST_INVALID
    assert session.mock_calls == []


@pytest.mark.parametrize(
    "operation", ("peek_native", "peek_role", "claim_legacy", "exists", "routing")
)
def test_query_markers_are_quarantined_by_the_same_total_routing_predicate(operation: str) -> None:
    session = Mock(spec=Session)
    session.execute.return_value.one_or_none.return_value = None
    session.execute.return_value.scalar_one_or_none.return_value = None
    session.scalar.return_value = False if operation == "routing" else None
    if operation.startswith("peek"):
        assert (
            peek_command_candidate(
                session,
                family=CommandExecutionFamily.LOCAL_EMBEDDING
                if operation == "peek_native"
                else CommandExecutionFamily.ROLE,
            )
            is None
        )
        query = session.execute.call_args.args[0]
    elif operation == "claim_legacy":
        assert claim_next_command(session, runner_id="synthetic-role", lease_seconds=60) is None
        query = session.execute.call_args.args[0]
    elif operation == "exists":
        assert claimable_command_exists(session, workflow_id="workflow_" + "1" * 32) is False
        query = session.scalar.call_args.args[0]
    else:
        assert (
            workflow_requires_local_embedding(session, workflow_id="workflow_" + "1" * 32) is False
        )
        query = session.scalar.call_args.args[0]
    sql = str(query.compile(dialect=SQL_DIALECT, compile_kwargs={"literal_binds": True}))
    for marker in (
        "local-embedding-index",
        "local-embedding/1.0",
        "local-embedding-workflow-request/1.1",
        "incremental-embedding-result@1.0",
        "local-embedding-reference-query",
        "reference-query/1.0",
        "reference-query-workflow-request/1.0",
        "REFERENCE_QUERY",
        "embedding-reference-query-result@1.0",
    ):
        assert marker in sql
    assert "coalesce" in sql and "EXISTS" in sql and " LIKE " not in sql
    if operation in {"peek_role", "claim_legacy", "exists"}:
        assert "NOT coalesce" in sql
    assert set(CommandExecutionFamily) == {
        CommandExecutionFamily.ROLE,
        CommandExecutionFamily.LOCAL_EMBEDDING,
        CommandExecutionFamily.REFERENCE_QUERY,
        CommandExecutionFamily.PRIVATE_CHAT_QUERY,
    }


@pytest.mark.parametrize(
    "marker",
    ("key", "protocol", "initial_schema", "payload_schema", "initial_purpose", "payload_purpose"),
)
def test_visible_query_marker_never_relabels_a_valid_document_request(marker: str) -> None:
    fixture, workflow, command = candidate_fixture()
    if marker == "key":
        workflow.definition_key = REFERENCE_QUERY_WORKFLOW_KEY
    elif marker == "protocol":
        workflow.role_schema_version = REFERENCE_QUERY_EXECUTION_PROTOCOL
    else:
        field, name = marker.split("_")
        document = dict(
            workflow.initial_request if field == "initial" else workflow.request_payload
        )
        document["schema_version" if name == "schema" else "purpose"] = (
            "reference-query-workflow-request/1.0" if name == "schema" else "REFERENCE_QUERY"
        )
        if field == "initial":
            workflow.initial_request = document
        else:
            workflow.request_payload = document
    candidate = peek(fixture)
    assert candidate.native_request is None
    fixture.session.reset_mock()
    with pytest.raises(WorkflowError) as failure:
        claim_command_candidate(
            cast(Session, fixture.session),
            candidate,
            runner_id="synthetic-query-unoffered",
            lease_seconds=60,
            local_embedding_owner=cast(LocalEmbeddingOwnerAdmission, fixture.owner),
            local_embedding_executor=cast(LocalEmbeddingNativeExecutor, fixture.executor),
        )
    assert failure.value.code is WorkflowErrorCode.LOCAL_EMBEDDING_EXECUTION_UNAVAILABLE
    assert fixture.session.mock_calls == []
    assert fixture.owner.resolve_claim.call_count == 0
    assert command.lease_generation == 0 and command.lease_token is None


@pytest.mark.parametrize("marker", ("record", "canonical"))
def test_query_related_definition_only_is_denied_before_owner_and_lease(marker: str) -> None:
    fixture, workflow, command = candidate_fixture()
    candidate = peek(fixture)
    assert candidate.native_request == fixture.scope.request
    prepare_claim(fixture, workflow, command)
    if marker == "record":
        fixture.definition.definition_key = REFERENCE_QUERY_WORKFLOW_KEY
    else:
        fixture.definition.canonical_definition["definition_key"] = REFERENCE_QUERY_WORKFLOW_KEY
    with pytest.raises(WorkflowError) as failure:
        claim_command_candidate(
            cast(Session, fixture.session),
            candidate,
            runner_id="synthetic-query-unoffered",
            lease_seconds=60,
            local_embedding_owner=cast(LocalEmbeddingOwnerAdmission, fixture.owner),
            local_embedding_executor=cast(LocalEmbeddingNativeExecutor, fixture.executor),
        )
    assert failure.value.code is WorkflowErrorCode.LOCAL_EMBEDDING_EXECUTION_UNAVAILABLE
    assert fixture.owner.resolve_claim.call_count == 0
    assert fixture.owner.fence_mutation.call_count == 0
    assert command.lease_generation == 0 and command.lease_token is None


@pytest.mark.parametrize("malformed", (None, [], "not-an-object", True))
def test_nonobject_stored_native_definition_has_a_stable_error_before_owner(
    malformed: object,
) -> None:
    fixture, workflow, command = candidate_fixture()
    candidate = peek(fixture)
    prepare_claim(fixture, workflow, command)
    fixture.definition.canonical_definition = cast(dict[str, Any], malformed)
    with pytest.raises(WorkflowError) as failure:
        claim_command_candidate(
            cast(Session, fixture.session),
            candidate,
            runner_id="synthetic-corrupt-native-definition",
            lease_seconds=60,
            local_embedding_owner=cast(LocalEmbeddingOwnerAdmission, fixture.owner),
            local_embedding_executor=cast(LocalEmbeddingNativeExecutor, fixture.executor),
        )
    assert failure.value.code is WorkflowErrorCode.WORKFLOW_DEFINITION_INVALID
    assert fixture.owner.resolve_claim.call_count == fixture.owner.fence_mutation.call_count == 0
    assert command.lease_generation == 0 and command.lease_token is None
