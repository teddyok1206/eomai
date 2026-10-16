"""Actual SQLite PK selection; current Identity/source and numeric ports are synthetic."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_catalog_contracts.similarity_context import parse_similarity_context
from eom_catalog_contracts.similarity_read import SimilarityContextReadRequest
from eom_catalog_service import similarity_read_service as module
from eom_catalog_service.embedding_registry_ports import (
    EmbeddingRegistryCaller,
    EmbeddingRegistryError,
)
from eom_catalog_service.similarity_context_ports import SimilarityContextReadError
from eom_catalog_service.similarity_read_service import CatalogSimilarityContextReadService
from eom_identifiers import content_sha256
from eom_identity_service import OperatorAuthorizationFenceError
from eom_workflow_runner.models import WorkflowDefinitionRecord, WorkflowInstanceRecord
from eom_workflow_runner.reference_query_consumer_read import (
    select_completed_reference_query_request,
)
from sqlalchemy import event

from tests.unit.test_reference_query_owner_admission import mutation_rows
from tests.unit.test_reference_query_owner_admission import source as source
from tests.unit.test_similarity_read_contract import pair


@pytest.fixture
def selected(source, monkeypatch):
    # Existing fixture constructs real request/control bytes. Its detached SQL
    # seam is not used by this service: selection below uses actual SQLite rows.
    temporary, _, template, _ = mutation_rows(source, monkeypatch)
    definition = next(
        value for value in temporary.new if isinstance(value, WorkflowDefinitionRecord)
    )
    WorkflowDefinitionRecord.__table__.create(source.publisher.engine)
    WorkflowInstanceRecord.__table__.create(source.publisher.engine)
    body = source.request.model_dump(mode="json")
    with source.publisher.sessions.begin() as session:
        session.add(
            WorkflowDefinitionRecord(
                **{
                    column.name: getattr(definition, column.name)
                    for column in definition.__table__.columns
                    if getattr(definition, column.name) is not None
                }
            )
        )
        session.add(
            WorkflowInstanceRecord(
                workflow_id=template.workflow_id,
                definition_id=definition.definition_id,
                definition_key=definition.definition_key,
                definition_version=definition.definition_version,
                definition_hash=definition.definition_hash,
                protocol_version="1.0.1",
                role_schema_version="reference-query/1.0",
                state="COMPLETED",
                stage="COMPLETED",
                current_step_key="complete",
                request_payload=body,
                initial_request=body,
                request_hash=template.request_hash,
                idempotency_key="synthetic-exact-query-read",
                created_actor_type="human",
                created_actor_id=source.request.operator_audit.operator_id,
            )
        )
    temporary.close()
    request = SimilarityContextReadRequest.model_validate(
        {
            "schema_version": "system-rag-similarity-read-request/1.0",
            "operation": "READ_SIMILARITY_CONTEXT",
            "actor_id": source.request.operator_audit.operator_id,
            "selection": {
                "workflow_id": template.workflow_id,
                "workflow_request_sha256": source.request.request_sha256,
                "context_request_sha256": source.request.context_request.request_sha256,
            },
        }
    )
    # Synthetic common output with the exact original context request/hash.
    _, example = pair()
    result_body = example.result.model_dump(mode="json")
    result_body["request"] = source.request.context_request.model_dump(mode="json")
    # A successful no-vector context is sufficient for selector/control tests;
    # the real canonical member/terminal closure has independent owner tests.
    result_body |= {"status": "UNAVAILABLE", "query_execution": None, "candidates": []}
    result_body["limitations"] = [
        "VECTOR_NOT_AVAILABLE",
        "NO_RELATED_CANDIDATES",
        "REFERENCE_ANCHOR_NOT_PRIVATE_INTENT",
    ]
    population = result_body["population"]
    population["authorized_source_count"] = 1
    population["accepted_profile_count"] = 1
    population["missing_report_count"] = 0
    population["truncated"] = False
    population["views"] = [
        {
            "view": selection.view,
            "status": "UNAVAILABLE",
            "available_binding_count": None,
            "binding_set_sha256": None,
            "scored_count": 0,
            "missing_view_count": None,
            "reason": "QUERY_NOT_OFFERED",
        }
        for selection in source.request.context_request.views
    ]
    result_body["context_sha256"] = content_sha256(
        {key: value for key, value in result_body.items() if key != "context_sha256"}
    )
    result = parse_similarity_context(result_body)
    calls, hooks = [], []

    def current(session, caller, original, *, workflow_id, artifact_reader=None):
        if artifact_reader is not None:
            artifact_reader.require_session(session)
        assert original == source.request and workflow_id == request.selection.workflow_id
        assert caller.operator_id == request.actor_id
        assert session.get_transaction() is not None and not session.in_nested_transaction()
        calls.append(session)
        if hooks:
            hooks.pop(0)()
        return SimpleNamespace(sources="same-pinned-sources", output="same-output")

    owner = SimpleNamespace(
        catalog=SimpleNamespace(engine=source.publisher.engine),
        settings=source.owner.settings,
        identity=SimpleNamespace(fence_current_operator=Mock()),
        resolve_completed_sources=current,
    )
    common = Mock(return_value=result)

    def compose(_reader, session, caller, context):
        assert session is calls[-1] and caller.operator_id == request.actor_id
        assert context == source.request.context_request
        return common()

    monkeypatch.setattr(module.CatalogSimilaritySessionContextReader, "compose_in_session", compose)
    service = CatalogSimilarityContextReadService(owner)
    return SimpleNamespace(
        service=service,
        request=request,
        result=result,
        owner=owner,
        calls=calls,
        hooks=hooks,
        common=common,
        source=source,
    )


def change(value, **fields):
    with value.service.sessions.begin() as session:
        row = session.get(WorkflowInstanceRecord, value.request.selection.workflow_id)
        for name, field in fields.items():
            setattr(row, name, field)


@pytest.mark.parametrize("nested", (False, True))
def test_shared_selector_requires_an_active_non_nested_caller_root(selected, nested):
    value = selected
    with value.service.sessions() as session:
        if nested:
            session.begin()
            session.begin_nested()
        with pytest.raises(SimilarityContextReadError, match="AUTHORITY_UNAVAILABLE"):
            select_completed_reference_query_request(
                session,
                value.owner,
                EmbeddingRegistryCaller(value.request.actor_id),
                value.request.selection,
            )
    value.owner.identity.fence_current_operator.assert_not_called()
    value.common.assert_not_called()


def test_shared_selector_returns_only_exact_request_metadata_without_source_or_numeric_work(
    selected,
):
    value = selected
    with value.service.sessions.begin() as session:
        root = session.get_transaction()
        original = select_completed_reference_query_request(
            session,
            value.owner,
            EmbeddingRegistryCaller(value.request.actor_id),
            value.request.selection,
        )
        assert original == value.source.request
        assert session.get_transaction() is root and root.is_active
        assert not session.new and not session.dirty and not session.deleted
    assert not value.calls
    value.common.assert_not_called()


@pytest.mark.parametrize("fault", ("authority_extra", "malformed_actor", "wrong_caller_kind"))
def test_shared_selector_does_not_trust_model_copies_or_non_human_callers(selected, fault):
    value = selected
    caller = EmbeddingRegistryCaller(value.request.actor_id)
    selection = value.request.selection
    if fault == "authority_extra":
        selection = selection.model_copy(update={"role": "ADMIN"})
    elif fault == "malformed_actor":
        caller = EmbeddingRegistryCaller("not-an-operator")
    else:
        caller = SimpleNamespace(operator_id=value.request.actor_id)
    with value.service.sessions.begin() as session, pytest.raises(SimilarityContextReadError):
        select_completed_reference_query_request(session, value.owner, caller, selection)
    value.owner.identity.fence_current_operator.assert_not_called()
    assert not value.calls
    value.common.assert_not_called()


def test_exact_stored_query_uses_one_root_and_rechecks_without_writes_or_model(selected):
    value = selected
    statements = []

    def record(_connection, _cursor, statement, _parameters, _context, _many):
        statements.append(statement)

    event.listen(value.source.publisher.engine, "before_cursor_execute", record)
    try:
        assert value.service.read(value.request) == value.result
        assert value.service.read(value.request) == value.result
    finally:
        event.remove(value.source.publisher.engine, "before_cursor_execute", record)
    assert len(value.calls) == 4
    assert value.calls[0] is value.calls[1] and value.calls[2] is value.calls[3]
    assert value.calls[0] is not value.calls[2]
    assert all(statement.lstrip().upper().startswith("SELECT") for statement in statements)
    assert len(statements) == 4  # two indexed exact-Workflow reads per call
    assert value.owner.identity.fence_current_operator.call_count == 4


@pytest.mark.parametrize(
    "fault",
    (
        "missing",
        "foreign_creator",
        "service_creator",
        "running",
        "divergent_request",
        "workflow_hash",
        "context_hash",
        "stored_invalid",
    ),
)
def test_invalid_or_foreign_selection_never_reaches_common_materialization(selected, fault):
    value = selected
    if fault == "missing":
        selection = value.request.selection.model_copy(
            update={"workflow_id": "workflow_" + "f" * 32}
        )
        value.request = value.request.model_copy(update={"selection": selection})
    elif fault == "foreign_creator":
        change(
            value, created_actor_id="operator_" + "f" * 32, initial_request={"private": "hidden"}
        )
    elif fault == "service_creator":
        change(value, created_actor_type="service")
    elif fault == "running":
        change(value, state="RUNNING")
    elif fault == "divergent_request":
        change(value, request_payload={"private": "hidden"})
    elif fault == "stored_invalid":
        change(value, initial_request={"invalid": True}, request_payload={"invalid": True})
    else:
        field = "workflow_request_sha256" if fault == "workflow_hash" else "context_request_sha256"
        selection = value.request.selection.model_copy(update={field: "sha256:" + "f" * 64})
        value.request = value.request.model_copy(update={"selection": selection})
    with pytest.raises(SimilarityContextReadError) as caught:
        value.service.read(value.request)
    assert caught.value.code == (
        "SOURCE_ACCESS_DENIED"
        if fault in {"missing", "foreign_creator", "service_creator"}
        else "QUERY_RESULT_INVALID"
    )
    assert not value.calls
    value.common.assert_not_called()


@pytest.mark.parametrize("late", (False, True))
def test_current_identity_revocation_is_not_an_expired_execution_capture_fallback(selected, late):
    value = selected
    error = OperatorAuthorizationFenceError("OPERATOR_AUTHORIZATION_FENCE_FORBIDDEN")
    value.owner.identity.fence_current_operator.side_effect = [None, error] if late else error
    with pytest.raises(SimilarityContextReadError) as caught:
        value.service.read(value.request)
    assert caught.value.code == "AUTHORITY_UNAVAILABLE"
    assert value.common.call_count == (1 if late else 0)


def test_late_changed_completed_selection_is_not_returned(selected):
    value = selected
    value.common.side_effect = lambda: (change(value, state="FAILED"), value.result)[1]
    with pytest.raises(SimilarityContextReadError, match="QUERY_RESULT_INVALID"):
        value.service.read(value.request)


def test_current_source_denial_stays_a_source_denial(selected):
    value = selected
    value.owner.resolve_completed_sources = Mock(
        side_effect=EmbeddingRegistryError("EMBEDDING_REGISTRY_FORBIDDEN")
    )
    with pytest.raises(SimilarityContextReadError, match="SOURCE_ACCESS_DENIED"):
        value.service.read(value.request)
    value.common.assert_not_called()


@pytest.mark.parametrize("field", ("sources", "output"))
def test_late_completed_source_or_output_change_fails_without_returning_context(selected, field):
    value = selected
    current = value.owner.resolve_completed_sources

    def changed(*args, **kwargs):
        resolved = current(*args, **kwargs)
        if len(value.calls) == 2:
            setattr(resolved, field, "changed-exact-pin")
        return resolved

    value.owner.resolve_completed_sources = changed
    with pytest.raises(SimilarityContextReadError, match="QUERY_RESULT_INVALID"):
        value.service.read(value.request)
    value.common.assert_called_once()


def test_concurrent_users_keep_exact_creator_and_root_separate_on_one_service(
    selected, monkeypatch
):
    value = selected
    first = value.request
    second_actor = "operator_" + "f" * 32
    body = value.source.request.model_dump(mode="json")
    body["operator_audit"]["operator_id"] = second_actor
    body["request_sha256"] = content_sha256(
        {key: child for key, child in body.items() if key != "request_sha256"}
    )
    second_workflow = "workflow_" + "f" * 32
    with value.service.sessions.begin() as session:
        template = session.get(WorkflowInstanceRecord, first.selection.workflow_id)
        fields = {
            column.name: getattr(template, column.name)
            for column in template.__table__.columns
            if getattr(template, column.name) is not None
        }
        fields.update(
            workflow_id=second_workflow,
            created_actor_id=second_actor,
            initial_request=body,
            request_payload=body,
            request_hash="sha256:" + "f" * 64,
            idempotency_key="synthetic-other-user-query",
        )
        session.add(WorkflowInstanceRecord(**fields))
    second = SimilarityContextReadRequest.model_validate(
        first.model_dump(mode="json")
        | {
            "actor_id": second_actor,
            "selection": first.selection.model_dump(mode="json")
            | {"workflow_id": second_workflow, "workflow_request_sha256": body["request_sha256"]},
        }
    )
    barrier = Barrier(2)
    observations = []

    def current(session, caller, original, *, workflow_id, artifact_reader=None):
        if artifact_reader is not None:
            artifact_reader.require_session(session)
        assert caller.operator_id == original.operator_audit.operator_id
        assert workflow_id == (
            first.selection.workflow_id if caller.operator_id == first.actor_id else second_workflow
        )
        return SimpleNamespace(sources="same-pinned-sources", output="same-output")

    def compose(reader, session, caller, context):
        assert reader.query.request.operator_audit.operator_id == caller.operator_id
        assert context == reader.query.request.context_request
        root = session.get_transaction()
        assert root is not None and root.is_active
        observations.append((caller.operator_id, session, root))
        barrier.wait(timeout=10)
        return value.result

    value.owner.resolve_completed_sources = current
    monkeypatch.setattr(module.CatalogSimilaritySessionContextReader, "compose_in_session", compose)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(value.service.read, request) for request in (first, second)]
        assert tuple(future.result(timeout=20) for future in futures) == (
            value.result,
            value.result,
        )
    assert {actor for actor, _session, _root in observations} == {first.actor_id, second.actor_id}
    assert observations[0][1] is not observations[1][1]
    assert observations[0][2] is not observations[1][2]
