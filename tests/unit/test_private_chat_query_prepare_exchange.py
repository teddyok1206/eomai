"""Real bounded Unix frames/schema resources; source, admission and native ports are fixtures."""

from __future__ import annotations

import json
import os
import socket
from dataclasses import replace
from pathlib import Path
from threading import Thread
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_catalog_contracts.embedding_registry import EmbeddingIndexNamespace
from eom_catalog_contracts.private_chat_query_prepare import (
    PrivateChatQueryPrepareProtocolError,
    PrivateChatQueryPrepareRequest,
    parse_private_chat_query_prepare_request,
    private_chat_query_context_request_id,
    validate_private_chat_query_prepare_reply,
)
from eom_catalog_contracts.private_chat_similarity import PrivateChatSimilarityRequest
from eom_catalog_contracts.validation import CATALOG_SCHEMA_RESOURCES, load_schema
from eom_catalog_service.embedding_registry_ports import EmbeddingRegistryOwnerConfiguration
from eom_catalog_service.similarity_context_ports import SimilarityContextReadError
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_orchestrator.general_chat_socket import (
    ChatSocketEndpoint,
    ChatTransportError,
    bind_chat_listener,
)
from eom_orchestrator.private_chat_query_prepare_client import PrivateChatQueryPrepareClient
from eom_orchestrator.private_chat_query_prepare_transport import (
    handle_private_chat_query_prepare_connection,
)
from eom_workflow.private_chat_query_execution import PrivateChatQueryWorkflowRequest
from eom_workflow_runner.private_chat_query_preparation import (
    PrivateChatQueryPreparationUnavailable,
)
from eom_workflow_runner.private_chat_query_prepare_application import (
    PreparedPrivateChatQueryWorkflow,
    PrivateChatQueryNotPrepared,
)
from eom_workflow_runner.private_chat_query_prepare_dispatch import (
    NativePrivateChatQueryPrepareDispatch,
)
from jsonschema import Draft202012Validator

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_private_chat_query_basis import TEXT
from tests.unit.test_private_chat_query_execution import execution_case
from tests.unit.test_private_chat_query_prepare_application import empty_completed_context
from tests.unit.test_private_chat_query_source import source_case


@pytest.fixture
def case():
    workflow, policy, _ = execution_case()
    chat = source_case(question=TEXT)
    origin = chat.execution.materialize_live_private_query(chat.ticket).origin
    context = PrivateChatSimilarityRequest.model_validate(
        seal(
            workflow.context_request.model_dump(mode="json")
            | {
                "request_id": private_chat_query_context_request_id(origin),
                "query_basis": origin.basis.model_dump(mode="json"),
                "maximum_sources": 1024,
                "top_k": 64,
            },
            "request_sha256",
        )
    )
    workflow = PrivateChatQueryWorkflowRequest.model_validate(
        seal(
            workflow.model_dump(mode="json")
            | {
                "context_request": context.model_dump(mode="json"),
                "operator_audit": workflow.operator_audit.model_dump(mode="json")
                | {"operator_id": origin.actor_id},
            },
            "request_sha256",
        )
    )
    body = seal(
        dict(
            schema_version="system-rag-private-chat-query-prepare-request/1.0",
            action="PREPARE_PRIVATE_CHAT_QUERY",
            request_id="chatqueryprepare_" + "1" * 32,
            origin=origin.model_dump(mode="json"),
            graph_snapshot=context.graph_snapshot.model_dump(mode="json"),
            policy_revision_id=context.policy_revision_id,
            policy_sha256=context.policy_sha256,
        ),
        "request_sha256",
    )
    request = parse_private_chat_query_prepare_request(body)
    registry = EmbeddingRegistryOwnerConfiguration(
        "corpus_" + "1" * 32,
        EmbeddingIndexNamespace(
            storage_partition=context.views[0].index.storage_partition,
            space_sha256=policy.spaces.document.space_sha256,
            view="CONTENT_ONLY",
            recipe_sha256=context.views[0].recipe.recipe_sha256,
            population_scope="OCCURRENCE_BACKED_PAST_EXAM",
        ),
        policy.spaces.document,
        context.views[0].recipe,
        context.source_classes,
    )
    result = PreparedPrivateChatQueryWorkflow("workflow_" + "2" * 32, workflow, origin, "PENDING")
    application = SimpleNamespace(
        owner=SimpleNamespace(configuration=SimpleNamespace(registry=registry)),
        prepare=Mock(return_value=result),
        read=Mock(return_value=result),
    )
    return SimpleNamespace(
        body=body,
        request=request,
        result=result,
        application=application,
        dispatch=NativePrivateChatQueryPrepareDispatch(application, policy.spaces),
        spaces=policy.spaces,
        workflow=workflow,
    )


def changed_request(case, **changes):
    return parse_private_chat_query_prepare_request(seal(case.body | changes, "request_sha256"))


def ready(case):
    context = empty_completed_context(SimpleNamespace(request=case.workflow))
    return replace(case.result, status="READY", context=context)


def test_schema_resources_are_exact_packaged_pins_and_all_external_references_resolve(case):
    root = Path(__file__).resolve().parents[2]
    resource = CATALOG_SCHEMA_RESOURCES["system-rag-private-chat-query-prepare"]
    canonical = (root / resource.canonical_path).read_bytes()
    assert (
        canonical
        == (
            root / "packages/catalog_contracts/eom_catalog_contracts" / resource.resource_path
        ).read_bytes()
    )
    assert sha256_bytes(canonical) == resource.sha256
    Draft202012Validator.check_schema(load_schema("system-rag-private-chat-query-prepare"))
    assert PrivateChatQueryPrepareRequest.model_validate(case.body) == case.request
    case.application.prepare.return_value = ready(case)
    reply = case.dispatch.execute(case.request)
    assert reply.status == "READY" and reply.context.query_execution is not None


@pytest.mark.parametrize(
    "field",
    (
        "actor_id",
        "actor_role",
        "text",
        "path",
        "password",
        "idempotency_key",
        "native_policy",
        "index",
    ),
)
def test_untrusted_extra_authority_text_or_runtime_selection_is_closed(case, field):
    with pytest.raises(PrivateChatQueryPrepareProtocolError) as error:
        parse_private_chat_query_prepare_request(case.body | {field: "DO_NOT_DISCLOSE"})
    assert str(error.value) == "PRIVATE_CHAT_QUERY_REQUEST_INVALID"
    case.application.prepare.assert_not_called()


def test_mutated_instance_is_revalidated_not_accepted_as_trusted(case):
    invalid = case.request.model_copy(update={"request_sha256": "sha256:" + "f" * 64})
    with pytest.raises(PrivateChatQueryPrepareProtocolError):
        case.dispatch.execute(invalid)
    case.application.prepare.assert_not_called()


@pytest.mark.parametrize(
    "status,workflow,context,error",
    (
        ("READY", None, None, None),
        ("READY", "workflow_" + "a" * 32, None, None),
        ("PENDING", None, None, None),
        ("PENDING", "workflow_" + "a" * 32, None, "QUERY_RESULT_INVALID"),
        ("FAILED", None, None, None),
        ("FAILED", None, None, "PRIVATE_CHAT_QUERY_NOT_PREPARED"),
        ("UNAVAILABLE", None, None, "SOURCE_ACCESS_DENIED"),
    ),
)
def test_schema_itself_rejects_ambiguous_state_not_just_client_checks(
    case, status, workflow, context, error
):
    from eom_catalog_contracts.validation import validate_contract
    from jsonschema import ValidationError

    body = case.dispatch.execute(case.request).model_dump(mode="json") | dict(
        status=status, workflow_id=workflow, context=context, error_code=error
    )
    with pytest.raises(ValidationError):
        validate_contract("system-rag-private-chat-query-prepare", body)


@pytest.mark.parametrize("action", ("PREPARE_PRIVATE_CHAT_QUERY", "READ_PRIVATE_CHAT_QUERY"))
def test_dispatch_uses_only_selected_operation_and_owner_controls(case, action):
    request = changed_request(case, action=action)
    reply = case.dispatch.execute(request)
    selected = case.application.prepare if action.startswith("PREPARE") else case.application.read
    other = case.application.read if action.startswith("PREPARE") else case.application.prepare
    origin, preparation = selected.call_args.args
    assert origin == request.origin
    assert preparation.request_id == private_chat_query_context_request_id(origin)
    assert preparation.scope.graph_snapshot == request.graph_snapshot
    assert preparation.scope.policy_revision_id == request.policy_revision_id
    assert preparation.scope.policy_sha256 == request.policy_sha256
    assert preparation.spaces == case.spaces
    assert (preparation.scope.maximum_sources, preparation.top_k) == (1024, 64)
    assert reply.status == "PENDING" and reply.context is None
    other.assert_not_called()


def test_new_rpc_correlation_does_not_make_new_original_context_identity(case):
    case.dispatch.execute(case.request)
    request = changed_request(case, request_id="chatqueryprepare_" + "3" * 32)
    case.dispatch.execute(request)
    first, second = case.application.prepare.call_args_list
    assert first.args == second.args


@pytest.mark.parametrize(
    "code",
    ("SOURCE_REVOKED", "SOURCE_ACCESS_DENIED", "SOURCE_HASH_MISMATCH", "QUERY_RESULT_INVALID"),
)
def test_current_denial_is_failure_not_empty_or_automatic_retry(case, code):
    case.application.prepare.side_effect = SimilarityContextReadError(code)
    reply = case.dispatch.execute(case.request)
    assert reply.status == "FAILED" and reply.error_code == code and reply.context is None
    assert case.application.prepare.call_count == 1
    case.application.read.assert_not_called()


@pytest.mark.parametrize(
    "error", (PrivateChatQueryNotPrepared, PrivateChatQueryPreparationUnavailable)
)
def test_known_absence_is_unavailable_not_failed_or_empty(case, error):
    case.application.read.side_effect = error()
    request = changed_request(case, action="READ_PRIVATE_CHAT_QUERY")
    reply = case.dispatch.execute(request)
    assert reply.status == "UNAVAILABLE" and reply.error_code == error.code
    case.application.prepare.assert_not_called()


@pytest.mark.parametrize(
    "field,value",
    (
        ("request_id", "chatqueryprepare_" + "a" * 32),
        ("request_sha256", "sha256:" + "f" * 64),
        ("action", "READ_PRIVATE_CHAT_QUERY"),
    ),
)
def test_cross_request_response_is_rejected(case, field, value):
    reply = case.dispatch.execute(case.request)
    with pytest.raises(PrivateChatQueryPrepareProtocolError):
        validate_private_chat_query_prepare_reply(
            case.request, reply.model_copy(update={field: value})
        )


@pytest.mark.parametrize("field", ("policy", "graph", "basis", "context_id"))
def test_ready_context_cannot_cross_original_scope(case, field):
    case.application.prepare.return_value = ready(case)
    reply = case.dispatch.execute(case.request)
    body = reply.context.model_dump(mode="json")
    request = body["request"]
    if field == "policy":
        request["policy_sha256"] = "sha256:" + "f" * 64
    elif field == "graph":
        request["graph_snapshot"]["graph_snapshot_revision_id"] = "graphrev_" + "f" * 32
    elif field == "context_id":
        request["request_id"] = "similarityrequest_" + "f" * 32
    else:
        basis = request["query_basis"]
        basis["turn_id"] = "chatturn_" + "f" * 32
        request["query_basis"] = seal(basis, "basis_sha256")
    body["request"] = seal(request, "request_sha256")
    body = seal(body, "context_sha256")
    altered = reply.model_dump(mode="json") | {"context": body}
    with pytest.raises(PrivateChatQueryPrepareProtocolError):
        validate_private_chat_query_prepare_reply(case.request, altered)


@pytest.fixture
def socket_case(case, tmp_path):
    parent = tmp_path / "query-owner"
    parent.mkdir(mode=0o750)
    endpoint = ChatSocketEndpoint(parent / "private.sock", os.getuid(), os.getgid())
    listener = bind_chat_listener(endpoint, backlog=1)
    observed = []
    peer = SimpleNamespace(uid=os.getuid())
    application = SimpleNamespace(execute=Mock(side_effect=case.dispatch.execute))
    factory = SimpleNamespace(application=Mock(return_value=application))

    def serve():
        with listener.accept()[0] as connection:
            handle_private_chat_query_prepare_connection(
                connection, chat_uid=peer.uid, factory=factory
            )
            observed.append("closed")

    thread = Thread(target=serve)
    thread.start()
    try:
        yield SimpleNamespace(
            client=PrivateChatQueryPrepareClient(endpoint),
            peer=peer,
            application=application,
            factory=factory,
            observed=observed,
            endpoint=endpoint,
        )
    finally:
        listener.close()
        thread.join(timeout=3)
        endpoint.path.unlink(missing_ok=True)
        assert not thread.is_alive()


def test_real_kernel_peer_and_canonical_frames_call_application_exactly_once(case, socket_case):
    reply = socket_case.client.execute(case.request)
    assert reply.status == "PENDING"
    socket_case.application.execute.assert_called_once_with(case.request)
    socket_case.factory.application.assert_called_once_with(case.request.origin)


def test_wrong_kernel_peer_never_calls_application(case, socket_case):
    socket_case.peer.uid = os.getuid() + 1
    with pytest.raises(ChatTransportError):
        socket_case.client.execute(case.request)
    socket_case.application.execute.assert_not_called()
    socket_case.factory.application.assert_not_called()


def test_origin_factory_failure_never_executes_or_retries_application(case, socket_case):
    socket_case.factory.application.side_effect = RuntimeError("DO_NOT_DISCLOSE_ORIGIN")
    reply = socket_case.client.execute(case.request)
    assert reply.status == "FAILED" and reply.error_code == "PRIVATE_CHAT_QUERY_UNAVAILABLE"
    socket_case.factory.application.assert_called_once_with(case.request.origin)
    socket_case.application.execute.assert_not_called()
    assert b"DO_NOT_DISCLOSE" not in canonical_json_bytes(reply.model_dump(mode="json"))


def test_unknown_committed_outcome_is_not_retried_or_claimed_missing(case, socket_case):
    socket_case.application.execute.side_effect = RuntimeError("DO_NOT_DISCLOSE_PRIVATE_TEXT")
    reply = socket_case.client.execute(case.request)
    assert reply.status == "FAILED" and reply.error_code == "PRIVATE_CHAT_QUERY_UNAVAILABLE"
    assert b"DO_NOT_DISCLOSE" not in canonical_json_bytes(reply.model_dump(mode="json"))
    assert socket_case.application.execute.call_count == 1


def test_noncanonical_or_additional_authority_frame_is_not_executed(case, socket_case):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(3)
        connection.connect(str(socket_case.endpoint.path))
        # Correct semantic document but deliberately noncanonical JSON framing.
        connection.sendall(json.dumps(case.body).encode() + b"\n")
        connection.shutdown(socket.SHUT_WR)
        assert connection.recv(1) == b""
    socket_case.application.execute.assert_not_called()
