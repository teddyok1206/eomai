"""Real private Unix peer/framing; source and publication results are synthetic."""

from __future__ import annotations

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
    MAX_ITEM_SIMILARITY_PUBLICATION_REQUEST_BYTES,
    ItemSimilarityPublicationReply,
)
from eom_catalog_service.item_similarity_publication_dispatch import (
    dispatch_item_similarity_publication_frame,
)
from eom_catalog_service.similarity_context_ports import SimilarityContextReadError
from eom_identifiers import canonical_json_bytes
from eom_orchestrator.general_chat_socket import ChatSocketEndpoint, ChatTransportError

from tests.unit.test_catalog_application_boundary import _server
from tests.unit.test_item_similarity_publication_contract import pair


def test_real_socket_calls_the_owner_on_each_publication_or_replay(tmp_path):
    request, expected = pair()
    server = _server(tmp_path)
    owner = SimpleNamespace(publish=Mock(return_value=expected.publication))
    server.item_similarity_publications = owner
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        client = CatalogItemSimilarityPublicationClient(
            ChatSocketEndpoint(server.socket_path, os.getuid(), os.getgid())
        )
        for _ in range(2):
            assert client.publish(request.actor_id, request.selection) == expected.publication
        assert owner.publish.call_count == 2
        assert all(call.args == (request,) for call in owner.publish.call_args_list)
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


@pytest.mark.parametrize("peer", ("chat", "runner"))
def test_other_trusted_peer_roles_cannot_publish_item_context(tmp_path, peer):
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


@pytest.mark.parametrize("fault", ("wrong_server", "wrong_client"))
def test_actual_peer_rejection_precedes_publication(tmp_path, fault):
    request, expected = pair()
    server = _server(
        tmp_path, allowed_uid=os.getuid() + 100000 if fault == "wrong_client" else None
    )
    server.chat_owner_uid = None
    owner = SimpleNamespace(publish=Mock(return_value=expected.publication))
    server.item_similarity_publications = owner
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        client = CatalogItemSimilarityPublicationClient(
            ChatSocketEndpoint(
                server.socket_path,
                os.getuid() + 100000 if fault == "wrong_server" else os.getuid(),
                os.getgid(),
            )
        )
        with pytest.raises(ItemSimilarityPublicationClientError):
            client.publish(request.actor_id, request.selection)
        owner.publish.assert_not_called()
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


@pytest.mark.parametrize("fault", ("oversize", "two_lines", "no_newline", "json", "authority"))
def test_bad_frames_never_reach_the_publisher(fault):
    request, _ = pair()
    raw = canonical_json_bytes(request) + b"\n"
    if fault == "oversize":
        raw = b"x" * (MAX_ITEM_SIMILARITY_PUBLICATION_REQUEST_BYTES + 1)
    elif fault == "two_lines":
        raw += raw
    elif fault == "no_newline":
        raw = raw[:-1]
    elif fault == "json":
        raw = b'{"private":"do-not-echo"\n'
    else:
        raw = canonical_json_bytes(request.model_dump(mode="json") | {"permission": "ALL"}) + b"\n"
    owner = SimpleNamespace(publish=Mock(side_effect=AssertionError("no publication")))
    reply = ItemSimilarityPublicationReply.model_validate(
        json.loads(dispatch_item_similarity_publication_frame(owner, raw))
    )
    assert reply.status == "FAILED" and reply.actor_id is None and reply.publication is None
    owner.publish.assert_not_called()


@pytest.mark.parametrize("fault", ("disabled", "denied", "unexpected", "wrong_context"))
def test_failed_owner_or_receipt_never_discloses_a_partial_publication(fault):
    request, expected = pair()
    owner = SimpleNamespace(publish=Mock(return_value=expected.publication))
    if fault == "disabled":
        owner = None
    elif fault == "denied":
        owner.publish.side_effect = SimilarityContextReadError("SOURCE_REVOKED")
    elif fault == "unexpected":
        owner.publish.side_effect = RuntimeError("private/path do-not-echo")
    else:
        request = request.model_copy(
            update={
                "selection": request.selection.model_copy(
                    update={"context_request_sha256": "sha256:" + "9" * 64}
                )
            }
        )
    raw = dispatch_item_similarity_publication_frame(owner, canonical_json_bytes(request) + b"\n")
    reply = ItemSimilarityPublicationReply.model_validate(json.loads(raw))
    assert reply.status == "FAILED" and reply.publication is None
    assert reply.error_code == (
        "SOURCE_REVOKED" if fault == "denied" else "ITEM_SIMILARITY_PUBLICATION_UNAVAILABLE"
    )
    assert b"do-not-echo" not in raw and b"private/path" not in raw


@pytest.mark.parametrize("fault", ("actor", "request", "context", "transport", "denied"))
def test_api_rejects_bad_reply_without_automatic_retry(monkeypatch, tmp_path, fault):
    request, expected = pair()
    body = expected.model_dump(mode="json")
    if fault == "actor":
        body["actor_id"] = "operator_" + "9" * 32
    elif fault == "request":
        body["request_sha256"] = "sha256:" + "9" * 64
    elif fault == "context":
        body["publication"]["delivery"]["request_sha256"] = "sha256:" + "9" * 64
    elif fault == "denied":
        body |= {"status": "FAILED", "publication": None, "error_code": "SOURCE_REVOKED"}
    exchange = Mock(return_value=body)
    if fault == "transport":
        exchange.side_effect = ChatTransportError("not proof of no commit")
    monkeypatch.setattr(client_module, "exchange_chat_frame", exchange)
    client = CatalogItemSimilarityPublicationClient(
        ChatSocketEndpoint(tmp_path / "unused.sock", os.getuid(), os.getgid())
    )
    with pytest.raises(ItemSimilarityPublicationClientError) as caught:
        client.publish(request.actor_id, request.selection)
    assert caught.value.code == (
        "SOURCE_REVOKED" if fault == "denied" else "ITEM_SIMILARITY_PUBLICATION_UNAVAILABLE"
    )
    exchange.assert_called_once()
