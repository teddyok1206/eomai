"""Real pinned control bytes, explicit synthetic Identity/Workflow metadata seams."""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_catalog_contracts.similarity_context import parse_similarity_context_request
from eom_catalog_service.embedding_registry_ports import (
    EmbeddingRegistryCaller,
    EmbeddingRegistryError,
    EmbeddingRegistryLookup,
    ReferenceQueryContextPreparation,
    SelectedEmbeddingSources,
)
from eom_catalog_service.pinned_artifact_resolution import PinnedArtifactResolutionError
from eom_identifiers import content_sha256
from eom_identity_service import AuthenticatedSessionFenceError
from eom_operator_identity import PermissionKey
from eom_workflow.compiler import compile_definition_data
from eom_workflow_runner import reference_query_preparation as module
from eom_workflow_runner.models import WorkflowDefinitionRecord, WorkflowInstanceRecord
from eom_workflow_runner.reference_query_execution_port import ReferenceQueryNativeExecutor
from jsonschema.exceptions import ValidationError as JsonSchemaError

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_reference_query_owner_admission import current_all_with_pinned_occurrence
from tests.unit.test_reference_query_owner_admission import source as source
from tests.unit.test_reference_query_workflow_contracts import definition_body


@pytest.fixture
def preparation(source, monkeypatch):
    compiled = compile_definition_data(definition_body(), "synthetic-preparation", set())
    definition = WorkflowDefinitionRecord(
        definition_id="wfdef_" + "e" * 32,
        definition_key="local-embedding-reference-query",
        definition_version="1.0.0",
        definition_hash=compiled.sha256,
    )
    value = SimpleNamespace(
        source=source,
        definition=definition,
        existing=None,
        observations=[],
        executor=Mock(spec=ReferenceQueryNativeExecutor),
        received=[],
        permissions=frozenset({PermissionKey.WORKFLOW_START}),
    )

    def scalar(session, statement, *args, **kwargs):
        model = statement.column_descriptions[0]["entity"]
        if model in {WorkflowInstanceRecord, WorkflowDefinitionRecord}:
            value.observations.append(model)
            return value.existing if model is WorkflowInstanceRecord else value.definition
        return original(session, statement, *args, **kwargs)

    session_type = source.publisher.sessions.class_
    original = session_type.scalar
    monkeypatch.setattr(session_type, "scalar", scalar)
    monkeypatch.setattr(module, "effective_permissions", lambda *_: value.permissions)

    def start(session, **kwargs):
        assert session.get_transaction().is_active and not session.in_nested_transaction()
        value.received.append(kwargs)
        return SimpleNamespace(workflow_created=value.existing is None)

    monkeypatch.setattr(module, "start_reference_query_in_session", start)
    return value


def prepare(value, session, *, caller=None, context=None):
    return module.prepare_and_start_reference_query_in_session(
        session,
        caller=caller or EmbeddingRegistryCaller(value.source.request.operator_audit.operator_id),
        context=context or value.source.request.context_request,
        idempotency_key="synthetic-pinned-query-preparation",
        owner=value.source.owner,
        executor=value.executor,
    )


def context_selection(source):
    context = source.request.context_request
    config = source.owner.configuration.registry
    return ReferenceQueryContextPreparation(
        context.request_id,
        SelectedEmbeddingSources(
            EmbeddingRegistryLookup(
                config.corpus_id,
                config.namespace,
                context.graph_snapshot,
                context.policy_revision_id,
                context.policy_sha256,
                context.maximum_sources,
            ),
            (context.anchor.source.item_revision_id,),
        ),
        source.policy.spaces,
        tuple(row.view for row in context.views),
        context.vector_mode,
        context.top_k,
        context.consumer_purpose,
    )


def prepare_selection(value, session, selection):
    return module.prepare_and_start_reference_query_selection_in_session(
        session,
        caller=EmbeddingRegistryCaller(value.source.request.operator_audit.operator_id),
        preparation=selection,
        idempotency_key="synthetic-selected-query-preparation",
        owner=value.source.owner,
        executor=value.executor,
    )


def test_selected_source_initial_capture_and_replay_share_canonical_start(preparation, monkeypatch):
    value = preparation
    selection = context_selection(value.source)
    capture = Mock(return_value=value.source.request.context_request)
    monkeypatch.setattr(
        value.source.owner.catalog, "prepare_reference_query_context_in_session", capture
    )
    with value.source.publisher.sessions.begin() as session:
        assert prepare_selection(value, session, selection).workflow_created
    original = value.received[0]["request"]
    value.existing = SimpleNamespace(
        initial_request=original.model_dump(mode="json"),
        created_actor_type="human",
        created_actor_id=original.operator_audit.operator_id,
    )
    capture.side_effect = AssertionError("reselecting current index on replay")
    for name in ("read_pinned_reference_query_controls", "effective_permissions"):
        monkeypatch.setattr(module, name, Mock(side_effect=AssertionError("rebuilding audit/pins")))
    with value.source.publisher.sessions.begin() as session:
        assert not prepare_selection(value, session, selection).workflow_created
    assert capture.call_count == 1 and len(value.received) == 2
    assert value.received[1]["request"] == original
    value.executor.execute.assert_not_called()
    value.executor.allocate_execution.assert_not_called()


@pytest.mark.parametrize("change", ("top_k", "source", "request_id", "policy", "purpose"))
def test_selected_source_changed_replay_fails_without_initial_recapture(
    preparation, monkeypatch, change
):
    value = preparation
    request = value.source.request
    value.existing = SimpleNamespace(
        initial_request=request.model_dump(mode="json"),
        created_actor_type="human",
        created_actor_id=request.operator_audit.operator_id,
    )
    selection = context_selection(value.source)
    if change == "top_k":
        selection = replace(selection, top_k=selection.top_k + 1)
    elif change == "request_id":
        selection = replace(selection, request_id="similarityrequest_" + "f" * 32)
    elif change == "purpose":
        selection = replace(selection, consumer_purpose="ITEM_AUTHORING")
    else:
        chosen = selection.selection
        chosen = (
            SelectedEmbeddingSources(chosen.scope, ("itemrev_" + "f" * 32,))
            if change == "source"
            else SelectedEmbeddingSources(
                replace(chosen.scope, policy_sha256="sha256:" + "f" * 64),
                chosen.source_revision_ids,
            )
        )
        selection = replace(selection, selection=chosen)
    capture = Mock(side_effect=AssertionError("recapturing a replay"))
    monkeypatch.setattr(
        value.source.owner.catalog, "prepare_reference_query_context_in_session", capture
    )
    with value.source.publisher.sessions.begin() as session, pytest.raises(EmbeddingRegistryError):
        prepare_selection(value, session, selection)
    capture.assert_not_called()
    assert value.received == []


def test_constructs_existing_request_from_actual_subject_and_exact_canonical_control_bytes(
    preparation,
):
    value = preparation
    with value.source.publisher.sessions.begin() as session:
        assert prepare(value, session).workflow_created
        actual = value.received[0]["request"]
        expected = value.source.request.model_dump(mode="json")
        expected["operator_audit"]["requester_permissions_sha256"] = content_sha256(
            sorted(key.value for key in value.permissions)
        )
        assert actual.model_dump(mode="json") == seal(expected, "request_sha256")
        assert value.received[0]["actor_id"] == actual.operator_audit.operator_id
        assert value.received[0]["actor_type"] == "human"
        assert value.received[0]["definition"] is value.definition
    value.executor.execute.assert_not_called()
    value.executor.allocate_execution.assert_not_called()


@pytest.mark.parametrize("missing", ("report", "index"))
def test_known_absent_auxiliary_input_does_not_create_workflow_or_start(
    preparation, monkeypatch, missing
):
    value = preparation
    context = value.source.request.context_request.model_dump(mode="json")
    if missing == "report":
        context["anchor"]["profile"] = None
        context["anchor"]["solution_evidence"] = None
    else:
        for view in context["views"]:
            view["index"] = None
    context = parse_similarity_context_request(seal(context, "request_sha256"))
    capture = Mock(return_value=context)
    monkeypatch.setattr(
        value.source.owner.catalog, "prepare_reference_query_context_in_session", capture
    )
    with (
        value.source.publisher.sessions.begin() as session,
        pytest.raises(module.ReferenceQueryPreparationUnavailable) as raised,
    ):
        prepare_selection(value, session, context_selection(value.source))
    assert raised.value.code == (
        "ANCHOR_REPORT_MISSING" if missing == "report" else "INDEX_NOT_PREPARED"
    )
    assert value.received == []
    assert value.observations == [WorkflowInstanceRecord]
    assert capture.call_count == 1
    value.executor.execute.assert_not_called()
    value.executor.allocate_execution.assert_not_called()


def test_same_key_reuses_original_audit_and_pins_without_rebuilding_preparation(
    preparation, monkeypatch
):
    value = preparation
    request = value.source.request
    value.existing = SimpleNamespace(
        initial_request=request.model_dump(mode="json"),
        created_actor_type="human",
        created_actor_id=request.operator_audit.operator_id,
    )
    for name in ("read_pinned_reference_query_controls", "effective_permissions"):
        monkeypatch.setattr(module, name, Mock(side_effect=AssertionError("new preparation")))
    with value.source.publisher.sessions.begin() as session:
        assert not prepare(value, session).workflow_created
    assert value.received[0]["request"] == request
    assert [name for name, _ in value.source.calls] == ["identity"]
    # The real atomic delegate, covered separately, still reauthorizes current controls/source.
    value.executor.execute.assert_not_called()


@pytest.mark.parametrize("control", ("policy", "bundle"))
def test_damaged_canonical_control_never_submits_or_repairs(preparation, control):
    value = preparation
    config = value.source.owner.configuration
    pointer = (
        config.native_execution_policy
        if control == "policy"
        else config.runtime_bundle.manifest_member
    )
    target = (
        value.source.owner.settings.nas_artifact_root
        / pointer.artifact_id
        / pointer.artifact_revision_id
        / pointer.member_path
    )
    damaged = target.read_bytes() + b"corrupt"
    target.write_bytes(damaged)
    with (
        value.source.publisher.sessions.begin() as session,
        pytest.raises(PinnedArtifactResolutionError),
    ):
        prepare(value, session)
    assert value.received == [] and target.read_bytes() == damaged


def test_raw_context_authority_extras_are_rejected_before_current_identity(preparation):
    value = preparation
    changed = value.source.request.context_request.model_copy(update={"roles": ["ADMIN"]})
    with (
        value.source.publisher.sessions.begin() as session,
        pytest.raises((ValueError, JsonSchemaError)),
    ):
        prepare(value, session, context=changed)
    assert value.received == [] and value.source.calls == []


@pytest.mark.parametrize("fault", ("actor", "context", "malformed", "definition"))
def test_foreign_or_changed_replay_never_rebuilds_or_submits(preparation, monkeypatch, fault):
    value = preparation
    request = value.source.request
    raw = request.model_dump(mode="json")
    value.existing = SimpleNamespace(
        initial_request=raw,
        created_actor_type="human",
        created_actor_id=request.operator_audit.operator_id,
    )
    context = request.context_request
    if fault == "actor":
        value.existing.created_actor_id = "operator_" + "0" * 32
    elif fault == "context":
        context = parse_similarity_context_request(
            seal(context.model_dump(mode="json") | {"top_k": context.top_k + 1}, "request_sha256")
        )
    elif fault == "malformed":
        raw["operator_audit"]["permissions"] = ["ADMIN"]
    else:
        value.definition.definition_hash = "sha256:" + "f" * 64
    monkeypatch.setattr(
        module, "read_pinned_reference_query_controls", Mock(side_effect=AssertionError("new pins"))
    )
    with (
        value.source.publisher.sessions.begin() as session,
        pytest.raises((ValueError, JsonSchemaError)),
    ):
        prepare(value, session, context=context)
    assert value.received == []


@pytest.mark.parametrize("fault", ("denied", "foreign_actor", "missing_definition"))
def test_current_denial_or_missing_definition_never_submits(preparation, fault):
    value = preparation
    caller = None
    if fault == "denied":
        value.source.deny = True
    elif fault == "foreign_actor":
        caller = EmbeddingRegistryCaller("operator_" + "0" * 32)
    else:
        value.definition = None
    with (
        value.source.publisher.sessions.begin() as session,
        pytest.raises((ValueError, AuthenticatedSessionFenceError)),
    ):
        prepare(value, session, caller=caller)
    assert value.received == []
    if fault != "missing_definition":
        assert value.observations == []


@pytest.mark.parametrize("fault", ("missing", "nested", "foreign", "inactive"))
def test_missing_nested_inactive_or_foreign_owner_root_denies_before_authority(
    preparation, monkeypatch, fault
):
    value = preparation
    with value.source.publisher.sessions() as session:
        if fault != "missing":
            session.begin()
        if fault == "nested":
            session.begin_nested()
        elif fault == "foreign":
            session.get_bind = lambda: object()
        elif fault == "inactive":
            monkeypatch.setattr(
                session, "get_transaction", lambda: SimpleNamespace(is_active=False)
            )
        with pytest.raises(ValueError, match="REFERENCE_QUERY_PREPARATION_ROOT_INVALID"):
            prepare(value, session)
    assert value.source.calls == [] and value.received == []


def test_original_occurrence_replay_normalizes_only_internal_current_namespace(
    preparation, monkeypatch
):
    value = preparation
    original = value.source.request
    selected, selector = current_all_with_pinned_occurrence(value.source, monkeypatch)
    selection = context_selection(value.source)
    assert selection.selection.scope.namespace.population_scope == "ALL_ADMITTED_GRAPH_ITEMS"
    value.existing = SimpleNamespace(
        initial_request=original.model_dump(mode="json"),
        created_actor_type="human",
        created_actor_id=original.operator_audit.operator_id,
    )
    capture = Mock(side_effect=AssertionError("historical replay must not select a current head"))
    monkeypatch.setattr(
        value.source.owner.catalog, "prepare_reference_query_context_in_session", capture
    )
    for name in ("read_pinned_reference_query_controls", "effective_permissions"):
        monkeypatch.setattr(
            module, name, Mock(side_effect=AssertionError("original pins/audit only"))
        )
    with value.source.publisher.sessions.begin() as session:
        assert not prepare_selection(value, session, selection).workflow_created
        selector.assert_called_once_with(
            session,
            EmbeddingRegistryCaller(original.operator_audit.operator_id),
            original.context_request,
        )
    assert value.received[0]["request"] == original
    assert selection.selection.scope.namespace.population_scope == "ALL_ADMITTED_GRAPH_ITEMS"
    assert selected.configuration.namespace.population_scope == "OCCURRENCE_BACKED_PAST_EXAM"
    assert (
        value.source.owner.configuration.registry.namespace.population_scope
        == "ALL_ADMITTED_GRAPH_ITEMS"
    )
    capture.assert_not_called()
    value.executor.execute.assert_not_called()
    value.executor.allocate_execution.assert_not_called()


def test_new_initial_request_cannot_borrow_historical_namespace(preparation, monkeypatch):
    value = preparation
    _selected, selector = current_all_with_pinned_occurrence(value.source, monkeypatch)
    with (
        value.source.publisher.sessions.begin() as session,
        pytest.raises(ValueError, match="REFERENCE_QUERY_INITIAL_NAMESPACE_MISMATCH"),
    ):
        prepare(value, session)
    selector.assert_called_once()
    assert value.received == []
    value.executor.execute.assert_not_called()


def test_initial_current_source_denial_precedes_artifact_context(preparation, monkeypatch):
    value = preparation
    monkeypatch.setattr(
        value.source.owner.catalog,
        "authorize_scope",
        Mock(side_effect=EmbeddingRegistryError("EMBEDDING_REGISTRY_FORBIDDEN")),
    )
    reader = Mock(side_effect=AssertionError("initial denial must precede Artifact context"))
    monkeypatch.setattr(module, "PinnedArtifactReadContext", reader)
    with (
        value.source.publisher.sessions.begin() as session,
        pytest.raises(EmbeddingRegistryError, match="EMBEDDING_REGISTRY_FORBIDDEN"),
    ):
        prepare(value, session)
    reader.assert_not_called()
    assert value.received == []
    value.executor.execute.assert_not_called()
