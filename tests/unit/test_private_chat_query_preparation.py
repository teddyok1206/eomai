"""Actual immutable control bytes/ORM roots; declared Chat/IAM/persistence seams only."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_catalog_contracts.private_chat_query_read import ChatPrivateQueryOrigin
from eom_catalog_contracts.private_chat_similarity import PrivateChatSimilarityRequest
from eom_catalog_service.embedding_registry_ports import EmbeddingRegistryCaller
from eom_catalog_service.similarity_context_ports import SimilarityContextReadError
from eom_identifiers import canonical_json_bytes, content_sha256
from eom_identity_service import OperatorAuthorizationFenceError
from eom_operator_identity import PermissionKey
from eom_orchestrator.models import JobRecord
from eom_workflow.private_chat_query_submission_context import (
    build_private_chat_query_submission_context,
    private_chat_query_origin_key,
    private_chat_query_submission_key,
)
from eom_workflow_runner import private_chat_query_preparation as module
from eom_workflow_runner.errors import WorkflowError, WorkflowErrorCode
from eom_workflow_runner.models import WorkflowDefinitionRecord, WorkflowInstanceRecord
from eom_workflow_runner.private_chat_query_execution_port import PrivateChatQueryNativeExecutor
from eom_workflow_runner.private_chat_query_owner_admission import (
    CatalogPrivateChatQueryOwnerAdmission,
)

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_private_chat_query_basis import TEXT
from tests.unit.test_private_chat_query_source_owner import source as source


@pytest.fixture
def preparation(source, monkeypatch):
    value = SimpleNamespace(
        source=source,
        owner=CatalogPrivateChatQueryOwnerAdmission(source.owner),
        executor=Mock(spec=PrivateChatQueryNativeExecutor),
        existing=None,
        received=[],
        lookups=[],
        permissions=frozenset({PermissionKey.WORKFLOW_START}),
    )
    value.definition = WorkflowDefinitionRecord(
        definition_id="wfdef_" + "d" * 32,
        definition_key=source.request.workflow_definition_key,
        definition_version=source.request.workflow_definition_version,
        definition_hash=source.request.workflow_definition_sha256,
    )
    session_type = source.publisher.sessions.class_
    original_scalar = session_type.scalar

    def scalar(session, statement, *args, **kwargs):
        model = statement.column_descriptions[0]["entity"]
        if model in {WorkflowInstanceRecord, WorkflowDefinitionRecord}:
            value.lookups.append(model)
            return value.existing if model is WorkflowInstanceRecord else value.definition
        return original_scalar(session, statement, *args, **kwargs)

    def start(session, **kwargs):
        assert session.get_transaction().is_active and not session.in_nested_transaction()
        assert not session.new and not session.dirty and not session.deleted
        value.received.append(kwargs)
        return SimpleNamespace(workflow_created=value.existing is None)

    monkeypatch.setattr(session_type, "scalar", scalar)
    monkeypatch.setattr(module, "effective_permissions", lambda *_: value.permissions)
    value.start = Mock(side_effect=start)
    monkeypatch.setattr(module, "start_private_chat_query_in_session", value.start)
    return value


def prepare(value, session, **overrides):
    return module.prepare_and_start_private_chat_query_in_session(
        session,
        **(
            dict(
                caller=EmbeddingRegistryCaller(value.source.projection.origin.actor_id),
                origin=value.source.projection.origin,
                context=value.source.request.context_request,
                owner=value.owner,
                executor=value.executor,
            )
            | overrides
        ),
    )


def original_row(value):
    args = value.received[0]
    return SimpleNamespace(
        initial_request=args["request"].model_dump(mode="json"),
        runtime_context=args["context"].model_dump(mode="json"),
        created_actor_type="human",
        created_actor_id=args["actor_id"],
    )


def test_builds_first_request_from_real_control_bytes_and_actual_caller(preparation):
    value = preparation
    with value.source.publisher.sessions.begin() as session:
        assert prepare(value, session).workflow_created
        args = value.received[0]
        request, context = args["request"], args["context"]
        assert request.operator_audit.requester_permissions_sha256 == content_sha256(
            sorted(key.value for key in value.permissions)
        )
        assert request.native_execution_policy == value.source.saved_policy.member
        assert request.context_request == value.source.request.context_request
        assert context == build_private_chat_query_submission_context(
            request, value.source.projection.origin
        )
        assert private_chat_query_submission_key(context) == private_chat_query_origin_key(
            context.origin
        )
        assert args["actor_id"] == context.origin.actor_id and args["actor_type"] == "human"
        assert args["definition"] is value.definition
        assert TEXT.encode() not in canonical_json_bytes(request)
        assert TEXT.encode() not in canonical_json_bytes(context)
    assert value.lookups == [WorkflowInstanceRecord, WorkflowDefinitionRecord]
    assert value.source.events == ["identity"]
    value.executor.execute.assert_not_called()


def test_exact_replay_retains_original_audit_context_and_pins_without_rebuilding(
    preparation, monkeypatch
):
    value = preparation
    with value.source.publisher.sessions.begin() as session:
        prepare(value, session)
    value.existing = original_row(value)
    for name in ("read_pinned_private_chat_query_controls", "effective_permissions"):
        monkeypatch.setattr(module, name, Mock(side_effect=AssertionError("rebuilding replay")))
    with value.source.publisher.sessions.begin() as session:
        assert not prepare(value, session).workflow_created
    assert value.received[0] == value.received[1]
    assert value.source.events == ["identity", "identity"]
    assert value.start.call_count == 2
    value.executor.execute.assert_not_called()


@pytest.mark.parametrize("field", ["context", "origin", "actor", "actor_type"])
def test_changed_original_replay_is_rejected_without_reselect_or_new_start(
    preparation, monkeypatch, field
):
    value = preparation
    with value.source.publisher.sessions.begin() as session:
        prepare(value, session)
    value.existing = original_row(value)
    overrides = {}
    if field == "context":
        body = value.source.request.context_request.model_dump(mode="json")
        body["top_k"] = body["top_k"] + 1
        overrides["context"] = PrivateChatSimilarityRequest.model_validate(
            seal(body, "request_sha256")
        )
    elif field == "origin":
        body = value.source.projection.origin.model_dump(mode="json")
        body["runtime_id"] = "chatrt_" + "f" * 32
        overrides["origin"] = ChatPrivateQueryOrigin.model_validate(seal(body, "origin_sha256"))
    elif field == "actor":
        value.existing.created_actor_id = "operator_" + "f" * 32
    else:
        value.existing.created_actor_type = "system"
    monkeypatch.setattr(
        module,
        "read_pinned_private_chat_query_controls",
        Mock(side_effect=AssertionError("reselection")),
    )
    with (
        value.source.publisher.sessions.begin() as session,
        pytest.raises(ValueError, match="PRIVATE_CHAT_QUERY_PREPARATION_REPLAY_MISMATCH"),
    ):
        prepare(value, session, **overrides)
    assert value.start.call_count == 1


@pytest.mark.parametrize("field", ["context", "origin", "actor"])
def test_untrusted_input_rejected_before_any_identity_or_sql_read(preparation, field):
    value = preparation
    overrides = (
        {"caller": EmbeddingRegistryCaller("operator_" + "f" * 32)}
        if field == "actor"
        else {field: {"question": TEXT, "authority": "ADMIN"}}
    )
    with (
        value.source.publisher.sessions.begin() as session,
        pytest.raises(ValueError, match="PRIVATE_CHAT_QUERY_PREPARATION_CONTEXT_INVALID") as error,
    ):
        prepare(value, session, **overrides)
    assert TEXT not in str(error.value) and error.value.__suppress_context__
    assert value.source.events == value.lookups == value.received == []


@pytest.mark.parametrize("field", ["missing", "hash"])
def test_definition_absence_or_stale_hash_does_not_submit(preparation, field):
    value = preparation
    if field == "missing":
        value.definition = None
    else:
        value.definition.definition_hash = "sha256:" + "f" * 64
    with (
        value.source.publisher.sessions.begin() as session,
        pytest.raises(ValueError, match="PRIVATE_CHAT_QUERY_PREPARATION_DEFINITION_UNAVAILABLE"),
    ):
        prepare(value, session)
    assert value.received == []


@pytest.mark.parametrize("field", ["nested", "dirty", "wrong_engine", "caller_type"])
def test_wrong_or_unclean_root_fails_before_identity_or_autoflush(preparation, field, monkeypatch):
    value = preparation
    with value.source.publisher.sessions.begin() as session:
        if field == "nested":
            session.begin_nested()
        elif field == "dirty":
            session.add(JobRecord(job_id="job_" + "f" * 32))
        elif field == "wrong_engine":
            monkeypatch.setattr(value.owner.catalog, "engine", object())
        kwargs = (
            {"caller": SimpleNamespace(operator_id="operator_" + "f" * 32)}
            if field == "caller_type"
            else {}
        )
        with pytest.raises((ValueError, SimilarityContextReadError)):
            prepare(value, session, **kwargs)
        assert value.source.events == value.lookups == []
        session.rollback()


def test_actual_identity_denial_is_not_an_authentication_or_submission(preparation):
    value = preparation
    value.source.fault.value = "identity"
    with (
        value.source.publisher.sessions.begin() as session,
        pytest.raises(OperatorAuthorizationFenceError),
    ):
        prepare(value, session)
    assert value.lookups == value.received == []


def test_preparation_still_cannot_offer_closed_private_definition(preparation, monkeypatch):
    value = preparation
    from eom_workflow_runner.private_chat_query_submission import (
        start_private_chat_query_in_session,
    )

    monkeypatch.setattr(
        module, "start_private_chat_query_in_session", start_private_chat_query_in_session
    )
    with value.source.publisher.sessions.begin() as session, pytest.raises(WorkflowError) as error:
        prepare(value, session)
    assert error.value.code is WorkflowErrorCode.LOCAL_EMBEDDING_EXECUTION_UNAVAILABLE
    assert value.received == []
    value.executor.execute.assert_not_called()
