"""Actual private Unix framing/peers; source authorization is explicitly synthetic."""

from __future__ import annotations

import json
import os
import socket
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_api.services import similarity_context_client as client_module
from eom_api.services.similarity_context_client import (
    CatalogSimilarityContextClient,
    SimilarityContextClientError,
)
from eom_catalog_contracts.similarity_read import (
    MAX_SIMILARITY_READ_FRAME_BYTES,
    SimilarityContextReadReply,
)
from eom_catalog_service.similarity_context_ports import SimilarityContextReadError
from eom_catalog_service.similarity_read_dispatch import dispatch_similarity_read_frame
from eom_identifiers import canonical_json_bytes, content_sha256
from eom_orchestrator.general_chat_socket import ChatSocketEndpoint, ChatTransportError

from tests.unit.test_catalog_application_boundary import _server
from tests.unit.test_similarity_read_contract import pair


def test_fixed_socket_round_trip_calls_owner_with_actual_injected_actor_and_pins(tmp_path):
    request, expected = pair()
    server = _server(tmp_path)
    service = SimpleNamespace(read=Mock(return_value=expected.result))
    server.similarity_context_reads = service
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        client = CatalogSimilarityContextClient(
            ChatSocketEndpoint(server.socket_path, os.getuid(), os.getgid())
        )
        assert client.read(request.actor_id, request.selection) == expected.result
        assert client.read(request.actor_id, request.selection) == expected.result
        assert service.read.call_count == 2
        assert all(call.args == (request,) for call in service.read.call_args_list)
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def test_chat_peer_cannot_call_the_new_api_only_operation(tmp_path):
    server = _server(tmp_path, allowed_uid=os.getuid() + 100000)
    server.chat_owner_uid = os.getuid()
    left, right = socket.socketpair(socket.AF_UNIX)
    try:
        assert server.peer_is_allowed(left)
        assert not server.peer_can_operate(left, "READ_SIMILARITY_CONTEXT")
        assert server.peer_can_operate(left, "CHAT_RAG")
    finally:
        left.close()
        right.close()
        server.server_close()


@pytest.mark.parametrize("fault", ("wrong_server_uid", "wrong_client_uid"))
def test_real_socket_peer_rejection_precedes_owner_read(tmp_path, fault):
    request, expected = pair()
    server = _server(
        tmp_path, allowed_uid=os.getuid() + 100000 if fault == "wrong_client_uid" else None
    )
    server.chat_owner_uid = None
    owner = SimpleNamespace(read=Mock(return_value=expected.result))
    server.similarity_context_reads = owner
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        endpoint = ChatSocketEndpoint(
            server.socket_path,
            os.getuid() + 100000 if fault == "wrong_server_uid" else os.getuid(),
            os.getgid(),
        )
        with pytest.raises(SimilarityContextClientError, match="SIMILARITY_CONTEXT_UNAVAILABLE"):
            CatalogSimilarityContextClient(endpoint).read(request.actor_id, request.selection)
        owner.read.assert_not_called()
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


@pytest.mark.parametrize("fault", ("oversize", "two_lines", "no_newline", "json", "extra"))
def test_bad_frames_do_not_call_owner_or_disclose_input(fault):
    request, _ = pair()
    raw = canonical_json_bytes(request) + b"\n"
    if fault == "oversize":
        raw = b"x" * (MAX_SIMILARITY_READ_FRAME_BYTES + 1)
    elif fault == "two_lines":
        raw += raw
    elif fault == "no_newline":
        raw = raw[:-1]
    elif fault == "json":
        raw = b'{"private":"do-not-echo"\n'
    else:
        raw = canonical_json_bytes(request.model_dump(mode="json") | {"admin": True}) + b"\n"
    owner = SimpleNamespace(read=Mock(side_effect=AssertionError("must not call owner")))
    reply = SimilarityContextReadReply.model_validate(
        json.loads(dispatch_similarity_read_frame(owner, raw))
    )
    assert reply.status == "FAILED" and reply.result is None and reply.actor_id is None
    assert reply.error_code == (
        "SIMILARITY_CONTEXT_BUDGET_EXCEEDED"
        if fault == "oversize"
        else "SIMILARITY_CONTEXT_REQUEST_INVALID"
    )
    owner.read.assert_not_called()


@pytest.mark.parametrize("fault", ("missing", "denied", "unexpected", "bad_reply", "wrong_context"))
def test_owner_failure_and_invalid_results_never_leak_partial_context(fault):
    request, result = pair()
    owner = SimpleNamespace(read=Mock(return_value=result.result))
    if fault == "missing":
        owner = None
    elif fault == "denied":
        owner.read.side_effect = SimilarityContextReadError("SOURCE_ACCESS_DENIED")
    elif fault == "unexpected":
        owner.read.side_effect = RuntimeError("private/path do-not-echo")
    elif fault == "bad_reply":
        owner.read.return_value = {"vectors": [[0.5]], "private": "do-not-echo"}
    else:
        request = request.model_copy(
            update={
                "selection": request.selection.model_copy(
                    update={"context_request_sha256": "sha256:" + "d" * 64}
                )
            }
        )
    raw = dispatch_similarity_read_frame(owner, canonical_json_bytes(request) + b"\n")
    reply = SimilarityContextReadReply.model_validate(json.loads(raw))
    assert reply.status == "FAILED" and reply.result is None
    assert reply.actor_id == request.actor_id
    assert reply.error_code == (
        "SOURCE_ACCESS_DENIED" if fault == "denied" else "SIMILARITY_CONTEXT_UNAVAILABLE"
    )
    assert b"private" not in raw and b"vectors" not in raw


@pytest.mark.parametrize(
    "fault", ("swapped_actor", "swapped_request", "malformed", "transport", "denied")
)
def test_api_adapter_rejects_swapped_or_invalid_peer_reply(monkeypatch, tmp_path, fault):
    request, reply = pair()
    body = reply.model_dump(mode="json")
    if fault == "swapped_actor":
        body["actor_id"] = "operator_" + "d" * 32
    elif fault == "swapped_request":
        body["request_sha256"] = "sha256:" + "d" * 64
    elif fault == "malformed":
        body["vectors"] = []
    elif fault == "denied":
        body |= {"status": "FAILED", "result": None, "error_code": "SOURCE_REVOKED"}
    exchange = Mock(return_value=body)
    if fault == "transport":
        exchange.side_effect = ChatTransportError("transport failed")
    monkeypatch.setattr(client_module, "exchange_chat_frame", exchange)
    client = CatalogSimilarityContextClient(
        ChatSocketEndpoint(tmp_path / "unused.sock", os.getuid(), os.getgid())
    )
    with pytest.raises(SimilarityContextClientError) as caught:
        client.read(request.actor_id, request.selection)
    assert caught.value.code == (
        "SOURCE_REVOKED" if fault == "denied" else "SIMILARITY_CONTEXT_UNAVAILABLE"
    )
    assert exchange.call_args.kwargs["request_limit"] == MAX_SIMILARITY_READ_FRAME_BYTES
    assert exchange.call_args.kwargs["reply_limit"] == MAX_SIMILARITY_READ_FRAME_BYTES


def test_invalid_actual_actor_or_forged_selection_fails_before_transport(monkeypatch):
    request, _ = pair()
    exchange = Mock(side_effect=AssertionError("no wire call"))
    monkeypatch.setattr(client_module, "exchange_chat_frame", exchange)
    for actor, selection in (
        ("ADMIN", request.selection),
        (request.actor_id, request.selection.model_copy(update={"vectors": [1.0]})),
    ):
        with pytest.raises(SimilarityContextClientError) as caught:
            CatalogSimilarityContextClient().read(actor, selection)
        assert caught.value.code == "SIMILARITY_CONTEXT_REQUEST_INVALID"
    exchange.assert_not_called()


@pytest.mark.parametrize("family", ("1.0", "2.0"))
@pytest.mark.parametrize("failure", ("SOURCE_REVOKED", "transport"))
def test_full_population_read_has_one_finite_scoped_deadline(
    monkeypatch, tmp_path, family, failure
):
    request, _reply = pair()

    def exchange(_endpoint, document, **limits):
        # A complete population read is not the short QUERY preparation RPC.
        assert limits == {
            "request_limit": MAX_SIMILARITY_READ_FRAME_BYTES,
            "reply_limit": MAX_SIMILARITY_READ_FRAME_BYTES,
            "timeout": 90.0,
        }
        if failure == "transport":
            raise ChatTransportError("finite deadline expired")
        return {
            "schema_version": f"system-rag-similarity-read-reply/{family}",
            "operation": "READ_SIMILARITY_CONTEXT",
            "status": "FAILED",
            "actor_id": document["actor_id"],
            "request_sha256": content_sha256(document),
            "result": None,
            "error_code": failure,
        }

    transport = Mock(side_effect=exchange)
    monkeypatch.setattr(client_module, "exchange_chat_frame", transport)
    client = CatalogSimilarityContextClient(
        ChatSocketEndpoint(tmp_path / "unused.sock", os.getuid(), os.getgid())
    )
    read = client.read if family == "1.0" else client.read_v2
    with pytest.raises(SimilarityContextClientError) as caught:
        read(request.actor_id, request.selection)
    assert caught.value.code == (
        "SIMILARITY_CONTEXT_UNAVAILABLE" if failure == "transport" else failure
    )
    transport.assert_called_once()
