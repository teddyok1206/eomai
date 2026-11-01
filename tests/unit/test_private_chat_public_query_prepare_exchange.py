"""Common wire2 uses the existing finite Unix transport and owner application.

Actual sockets/schema/family checks are tested; source/native authorization is a mock port.
"""

import os
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_catalog_contracts.private_chat_query_prepare import PrivateChatQueryPrepareProtocolError
from eom_catalog_contracts.private_chat_query_prepare_v2 import (
    PrivateChatQueryPrepareReplyV2,
    PrivateChatQueryPrepareRequestV2,
    parse_supported_private_chat_query_prepare_request,
)
from eom_catalog_contracts.public_solution_embedding_index import PublicSolutionIndexNamespace
from eom_catalog_service.embedding_registry_ports import EmbeddingRegistryOwnerConfiguration
from eom_catalog_service.similarity_context_ports import SimilarityContextReadError
from eom_orchestrator.general_chat_socket import ChatSocketEndpoint, ChatTransportError
from eom_orchestrator.private_chat_query_prepare_client import PrivateChatQueryPrepareClient
from eom_workflow_runner.native_query_prepare_driver import NativeQueryPrepareDriver
from eom_workflow_runner.private_chat_query_execution_port import PrivateChatQueryNativeExecutor
from eom_workflow_runner.private_chat_query_owner_admission import (
    CatalogPrivateChatQueryOwnerAdmission,
)
from eom_workflow_runner.private_chat_query_prepare_application import (
    NativePrivateChatQueryPreparation,
    PreparedPrivateChatQueryWorkflow,
    PrivateChatQueryNotPrepared,
)
from eom_workflow_runner.private_chat_query_prepare_dispatch import (
    NativePrivateChatQueryPrepareDispatch,
)

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_private_chat_public_query_prepare_contracts import common as common
from tests.unit.test_private_chat_public_similarity_read import common_read as common_read
from tests.unit.test_private_chat_query_prepare_application import private_runner
from tests.unit.test_private_chat_query_prepare_exchange import (
    case as case,
)
from tests.unit.test_private_chat_query_prepare_exchange import (
    prepare_socket_case,
)


@pytest.fixture
def wire(common):
    context = common.workflow.context_request
    view = context.views[0]
    registry = EmbeddingRegistryOwnerConfiguration(
        "corpus_" + "1" * 32,
        PublicSolutionIndexNamespace(
            storage_partition=view.index.storage_partition,
            space_sha256=view.index.spaces.document.space_sha256,
            recipe_sha256=view.recipe.recipe_sha256,
        ),
        view.index.spaces.document,
        view.recipe,
        context.source_classes,
    )
    result = PreparedPrivateChatQueryWorkflow(
        common.reply.workflow_id, common.workflow, common.request.origin, "PENDING"
    )
    application = SimpleNamespace(
        owner=SimpleNamespace(configuration=SimpleNamespace(registry=registry)),
        prepare=Mock(return_value=result),
        read=Mock(return_value=result),
    )
    return SimpleNamespace(
        common=common,
        request=common.request,
        application=application,
        result=result,
        dispatch=NativePrivateChatQueryPrepareDispatch(
            application, view.index.spaces, maximum_sources=16384
        ),
    )


@pytest.fixture
def connected(wire, tmp_path):
    with prepare_socket_case(wire, tmp_path) as value:
        yield value


@pytest.fixture
def local_client(tmp_path):
    # Follow-up contract tests replace execute; no unused listening thread is needed.
    return PrivateChatQueryPrepareClient(
        ChatSocketEndpoint(tmp_path / "unused.sock", os.getuid(), os.getgid())
    )


@pytest.mark.parametrize("action", ("PREPARE_PRIVATE_CHAT_QUERY", "READ_PRIVATE_CHAT_QUERY"))
def test_common_dispatch_selects_only_original_operation_with_common_owner_scope(wire, action):
    request = parse_supported_private_chat_query_prepare_request(
        seal(wire.request.model_dump(mode="json") | {"action": action}, "request_sha256")
    )
    reply = wire.dispatch.execute(request)
    selected = wire.application.prepare if action.startswith("PREPARE") else wire.application.read
    other = wire.application.read if action.startswith("PREPARE") else wire.application.prepare
    origin, preparation = selected.call_args.args
    assert origin == request.origin
    assert preparation.scope.namespace == wire.application.owner.configuration.registry.namespace
    assert preparation.scope.maximum_sources == 16384
    assert reply.status == "PENDING" and isinstance(reply, PrivateChatQueryPrepareReplyV2)
    other.assert_not_called()


def test_common_reply_ready_keeps_exact_empty_context_without_fictional_execution(wire):
    wire.application.prepare.return_value = replace(
        wire.result, status="READY", context=wire.common.reply.context
    )
    reply = wire.dispatch.execute(wire.request)
    assert reply.context == wire.common.reply.context and reply.status == "READY"
    assert reply.context.query_execution is None


def test_common_request_never_uses_a_legacy_owner_or_starts_work(wire):
    old = wire.common.legacy
    reply = old.dispatch.execute(wire.request)
    assert isinstance(reply, PrivateChatQueryPrepareReplyV2)
    assert reply.status == "FAILED" and reply.error_code == "AUTHORITY_UNAVAILABLE"
    old.application.prepare.assert_not_called()
    old.application.read.assert_not_called()


def test_common_dispatch_never_relabels_a_legacy_original_workflow(wire):
    wire.application.prepare.return_value = wire.common.legacy.result
    reply = wire.dispatch.execute(wire.request)
    assert reply.status == "FAILED" and reply.error_code == "QUERY_RESULT_INVALID"
    assert reply.workflow_id is None and reply.context is None


@pytest.mark.parametrize(
    "error", (SimilarityContextReadError("SOURCE_REVOKED"), PrivateChatQueryNotPrepared())
)
def test_failure_or_absence_is_not_retried_or_reinterpreted_as_empty(wire, error):
    wire.application.read.side_effect = error
    request = parse_supported_private_chat_query_prepare_request(
        seal(
            wire.request.model_dump(mode="json") | {"action": "READ_PRIVATE_CHAT_QUERY"},
            "request_sha256",
        )
    )
    reply = wire.dispatch.execute(request)
    assert reply.status in {"FAILED", "UNAVAILABLE"} and reply.context is None
    wire.application.read.assert_called_once()
    wire.application.prepare.assert_not_called()


def test_actual_kernel_peer_and_canonical_common_frames_execute_once(wire, connected):
    reply = connected.client.execute(wire.request)
    assert isinstance(reply, PrivateChatQueryPrepareReplyV2) and reply.status == "PENDING"
    connected.application.execute.assert_called_once_with(wire.request)
    connected.factory.application.assert_called_once_with(wire.request.origin)


def test_common_unknown_outcome_returns_same_family_without_retries_or_private_prose(
    wire, connected
):
    connected.application.execute.side_effect = RuntimeError("PRIVATE_DO_NOT_DISCLOSE")
    reply = connected.client.execute(wire.request)
    assert isinstance(reply, PrivateChatQueryPrepareReplyV2)
    assert reply.status == "FAILED" and reply.error_code == "PRIVATE_CHAT_QUERY_UNAVAILABLE"
    assert "PRIVATE_DO_NOT_DISCLOSE" not in reply.model_dump_json()
    connected.application.execute.assert_called_once()


def test_common_wrong_kernel_peer_cannot_resolve_the_private_origin(wire, connected):
    connected.peer.uid += 1
    with pytest.raises(ChatTransportError):
        connected.client.execute(wire.request)
    connected.factory.application.assert_not_called()
    connected.application.execute.assert_not_called()


@pytest.mark.parametrize("method", ("read_original", "continue_pending_original"))
def test_common_followup_retains_original_request_scope_and_workflow(
    wire, local_client, monkeypatch, method
):
    acknowledged = wire.dispatch.execute(wire.request)
    requests = []

    def exchange(actual):
        requests.append(actual)
        return wire.dispatch.execute(actual)

    monkeypatch.setattr(local_client, "execute", exchange)
    reply = getattr(local_client, method)(wire.request, acknowledged)
    assert reply.workflow_id == acknowledged.workflow_id
    assert len(requests) == 1
    assert requests[0].schema_version == wire.request.schema_version
    assert requests[0].origin == wire.request.origin
    assert requests[0].graph_snapshot == wire.request.graph_snapshot
    assert requests[0].action == (
        "READ_PRIVATE_CHAT_QUERY" if method == "read_original" else wire.request.action
    )


def test_common_followup_rejects_a_different_original_workflow(wire, local_client, monkeypatch):
    first = wire.dispatch.execute(wire.request)
    monkeypatch.setattr(
        local_client,
        "execute",
        lambda _: first.model_copy(update={"workflow_id": "workflow_" + "f" * 32}),
    )
    with pytest.raises(PrivateChatQueryPrepareProtocolError):
        local_client.continue_pending_original(wire.request, first)


def test_common_wire_read_reaches_actual_canonical_three_source_result_without_new_work(
    common_read,
):
    value = common_read
    owner = CatalogPrivateChatQueryOwnerAdmission(value.source.owner)
    executor = Mock(spec=PrivateChatQueryNativeExecutor)
    runner = private_runner(value.source, owner, executor)
    driver = NativeQueryPrepareDriver()
    driver.offer_private_chat_query = Mock(side_effect=AssertionError("READ cannot offer work"))
    app = NativePrivateChatQueryPreparation(
        owner=owner, executor=executor, runner=runner, driver=driver
    )
    context = value.source.request.context_request
    dispatch = NativePrivateChatQueryPrepareDispatch(
        app,
        value.source.policy.spaces,
        maximum_sources=context.maximum_sources,
        top_k=context.top_k,
    )
    request = PrivateChatQueryPrepareRequestV2.model_validate(
        seal(
            dict(
                schema_version="system-rag-private-chat-query-prepare-request/2.0",
                action="READ_PRIVATE_CHAT_QUERY",
                request_id="chatqueryprepare_" + "7" * 32,
                origin=value.source.projection.origin.model_dump(mode="json"),
                graph_snapshot=context.graph_snapshot.model_dump(mode="json"),
                policy_revision_id=context.policy_revision_id,
                policy_sha256=context.policy_sha256,
            ),
            "request_sha256",
        )
    )
    first = dispatch.execute(request)
    assert first == dispatch.execute(request)
    assert isinstance(first, PrivateChatQueryPrepareReplyV2) and first.status == "READY"
    assert len(first.context.candidates) == 3 and first.context.query_execution is not None
    assert value.native.encodes == 1 and executor.mock_calls == []
    driver.offer_private_chat_query.assert_not_called()
