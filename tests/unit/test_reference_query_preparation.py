"""Real pinned control bytes, explicit synthetic Identity/Workflow metadata seams."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_catalog_contracts.similarity_context import parse_similarity_context_request
from eom_catalog_service.embedding_registry_ports import EmbeddingRegistryCaller
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
