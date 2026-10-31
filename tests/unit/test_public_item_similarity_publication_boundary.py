"""Real Unix peer/framing with synthetic public QUERY receipts; no live publication authority."""

import json
import os
import socket
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_api.services import item_similarity_publication_client as client_module
from eom_api.services.item_similarity_publication_client import (
    CatalogItemSimilarityPublicationClient,
    ItemSimilarityPublicationClientError,
)
from eom_catalog_contracts.item_similarity_publication import (
    ItemSimilarityPublicationReplyV2,
)
from eom_catalog_service.item_similarity_publication_dispatch import (
    dispatch_item_similarity_publication_frame,
)
from eom_catalog_service.similarity_context_ports import SimilarityContextReadError
from eom_identifiers import canonical_json_bytes
from eom_orchestrator.general_chat_socket import ChatSocketEndpoint, ChatTransportError

from tests.unit.test_catalog_application_boundary import _server
from tests.unit.test_item_similarity_publication_contract import pair as legacy_pair
from tests.unit.test_public_item_similarity_publication_contract import public_publication_pair


@pytest.mark.parametrize("version", (3, 4))
def test_real_socket_keeps_public_family_and_calls_owner_on_every_replay(tmp_path, version):
    request, reply = public_publication_pair(version)
    server = _server(tmp_path)
    owner = SimpleNamespace(publish_public=Mock(return_value=reply.publication), publish=Mock())
    server.item_similarity_publications = owner
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        client = CatalogItemSimilarityPublicationClient(
            ChatSocketEndpoint(server.socket_path, os.getuid(), os.getgid())
        )
        for _ in range(2):
            assert client.publish_public(request.actor_id, request.selection) == reply.publication
        assert owner.publish_public.call_count == 2
        assert all(call.args == (request,) for call in owner.publish_public.call_args_list)
        owner.publish.assert_not_called()
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


@pytest.mark.parametrize("peer", ("chat", "runner"))
def test_publication2_does_not_broaden_peer_operation_permissions(tmp_path, peer):
    server = _server(tmp_path, allowed_uid=os.getuid() + 100000)
    server.chat_owner_uid = os.getuid() if peer == "chat" else None
    server.workflow_runner_uid = os.getuid() if peer == "runner" else None
    server.workflow_similarity_reads = object() if peer == "runner" else None
    left, right = socket.socketpair(socket.AF_UNIX)
    try:
        assert server.peer_is_allowed(left)
        assert not server.peer_can_operate(left, "PUBLISH_ITEM_SIMILARITY_CONTEXT")
    finally:
        left.close()
        right.close()
        server.server_close()


@pytest.mark.parametrize("fault", ("disabled", "revoked", "unexpected", "wrong_context"))
def test_public_failure_echoes_exact_request_without_partial_receipt_or_private_log(fault):
    request, reply = public_publication_pair()
    owner = SimpleNamespace(publish_public=Mock(return_value=reply.publication), publish=Mock())
    if fault == "disabled":
        owner = None
    elif fault == "revoked":
        owner.publish_public.side_effect = SimilarityContextReadError("SOURCE_REVOKED")
    elif fault == "unexpected":
        owner.publish_public.side_effect = RuntimeError("private/path should-not-echo")
    else:
        request = request.model_copy(
            update={
                "selection": request.selection.model_copy(
                    update={"context_request_sha256": "sha256:" + "0" * 64}
                )
            }
        )
    raw = dispatch_item_similarity_publication_frame(owner, canonical_json_bytes(request) + b"\n")
    result = ItemSimilarityPublicationReplyV2.model_validate(json.loads(raw))
    assert result.status == "FAILED" and result.publication is None
    assert result.error_code == (
        "SOURCE_REVOKED" if fault == "revoked" else "ITEM_SIMILARITY_PUBLICATION_UNAVAILABLE"
    )
    assert b"private/path" not in raw and b"should-not-echo" not in raw
    if owner is not None:
        owner.publish.assert_not_called()


@pytest.mark.parametrize("fault", ("actor", "request", "context", "transport", "denied", "legacy"))
def test_api_never_retries_or_uses_legacy_after_public_reply_or_transport_failure(
    monkeypatch, tmp_path, fault
):
    request, reply = public_publication_pair()
    body = reply.model_dump(mode="json")
    if fault == "actor":
        body["actor_id"] = "operator_" + "0" * 32
    elif fault == "request":
        body["request_sha256"] = "sha256:" + "0" * 64
    elif fault == "context":
        body["publication"]["delivery"]["request_sha256"] = "sha256:" + "0" * 64
    elif fault == "denied":
        body.update(status="FAILED", publication=None, error_code="SOURCE_REVOKED")
    elif fault == "legacy":
        body = legacy_pair()[1].model_dump(mode="json")
    exchange = Mock(return_value=body)
    if fault == "transport":
        exchange.side_effect = ChatTransportError("not proof of no commit")
    monkeypatch.setattr(client_module, "exchange_chat_frame", exchange)
    client = CatalogItemSimilarityPublicationClient(
        ChatSocketEndpoint(tmp_path / "unused.sock", os.getuid(), os.getgid())
    )
    with pytest.raises(ItemSimilarityPublicationClientError) as caught:
        client.publish_public(request.actor_id, request.selection)
    assert caught.value.code == (
        "SOURCE_REVOKED" if fault == "denied" else "ITEM_SIMILARITY_PUBLICATION_UNAVAILABLE"
    )
    exchange.assert_called_once()
