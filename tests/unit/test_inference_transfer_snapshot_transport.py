"""Private successor binding with fake owners and temporary fixed-identity Unix sockets."""

from __future__ import annotations

import json
import os
import socket
import threading
from unittest.mock import Mock

import eom_api.services.inference_transfer_snapshot_client as client_module
import pytest
from eom_api.services.inference_transfer_snapshot_client import (
    SNAPSHOT_RESPONSE_TIMEOUT_SECONDS,
    CatalogInferenceTransferSnapshotClient,
    InferenceTransferSnapshotClientError,
)
from eom_catalog_contracts.inference_transfer_snapshot_binding import (
    MAX_PRIVATE_SNAPSHOT_FRAME_BYTES,
    InferenceTransferSnapshotBindingReply,
    InferenceTransferSnapshotBindingRequest,
    parse_binding_reply,
)
from eom_catalog_service.inference_transfer_service import InferenceTransferServiceError
from eom_catalog_service.inference_transfer_snapshot_dispatch import dispatch_snapshot_frame
from eom_identifiers import canonical_json_bytes
from eom_orchestrator.general_chat_socket import ChatSocketEndpoint, ChatTransportError

from tests.unit.inference_transfer_snapshot_fixtures import (
    snapshot_prepare,
    snapshot_prepare_result,
)
from tests.unit.test_catalog_application_boundary import _server

ACTOR = "synthetic-operator"


def binding():
    return InferenceTransferSnapshotBindingRequest(actor_id=ACTOR, request=snapshot_prepare())


def client(server):
    return CatalogInferenceTransferSnapshotClient(
        ChatSocketEndpoint(server.socket_path, os.getuid(), os.getgid())
    )


def test_supported_snapshot_round_trip_uses_same_socket_actual_actor_and_context(tmp_path):
    server = _server(tmp_path)
    owner = Mock()
    owner.prepare.return_value = snapshot_prepare_result()
    server.inference_transfer_snapshot = owner
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        result = client(server).execute(ACTOR, snapshot_prepare())
        assert result == snapshot_prepare_result()
        owner.prepare.assert_called_once_with(ACTOR, snapshot_prepare())
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@pytest.mark.parametrize("peer", ["chat_owner", "worker"])
def test_snapshot_is_not_an_operation_for_chat_owner_or_worker(tmp_path, peer):
    server = _server(tmp_path, allowed_uid=os.getuid() + 100000)
    server.chat_owner_uid = os.getuid() if peer == "chat_owner" else os.getuid() + 200000
    owner = Mock()
    server.inference_transfer_snapshot = owner
    left, right = socket.socketpair(socket.AF_UNIX)
    try:
        assert not server.peer_can_operate(left, "INFERENCE_TRANSFER_SNAPSHOT")
    finally:
        left.close()
        right.close()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with pytest.raises(InferenceTransferSnapshotClientError):
            client(server).execute(ACTOR, snapshot_prepare())
        owner.prepare.assert_not_called()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_unsupported_old_server_is_explicit_unavailable_not_a_schema_guess(tmp_path):
    server = _server(tmp_path)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with pytest.raises(InferenceTransferSnapshotClientError, match="SNAPSHOT_UNAVAILABLE"):
            client(server).execute(ACTOR, snapshot_prepare())
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@pytest.mark.parametrize(
    "code",
    [
        "INFERENCE_TRANSFER_FORBIDDEN",
        "INFERENCE_TRANSFER_SNAPSHOT_CHANGED",
        "INFERENCE_TRANSFER_SOURCE_PIN_MISMATCH",
    ],
)
def test_owner_stable_failure_has_no_exception_text_or_partial_content(code):
    owner = Mock()
    owner.prepare.side_effect = InferenceTransferServiceError(code)
    raw = dispatch_snapshot_frame(owner, canonical_json_bytes(binding()) + b"\n")
    reply = parse_binding_reply(json.loads(raw))
    assert reply.error_code == code and reply.result is None


def test_unexpected_owner_failure_is_sanitized():
    owner = Mock()
    owner.prepare.side_effect = RuntimeError("secret-and-item-content-must-not-leak")
    raw = dispatch_snapshot_frame(owner, canonical_json_bytes(binding()) + b"\n")
    reply = parse_binding_reply(json.loads(raw))
    assert reply.error_code == "INFERENCE_TRANSFER_SNAPSHOT_UNAVAILABLE"
    assert b"secret-and-item" not in raw


def test_unregistered_source_error_uses_contract_allowlist_not_adapter_copy():
    owner = Mock()
    owner.prepare.side_effect = InferenceTransferServiceError("INTERNAL_SECRET_ERROR")
    raw = dispatch_snapshot_frame(owner, canonical_json_bytes(binding()) + b"\n")
    reply = parse_binding_reply(json.loads(raw))
    assert reply.error_code == "INFERENCE_TRANSFER_SNAPSHOT_UNAVAILABLE"
    assert b"INTERNAL_SECRET" not in raw


@pytest.mark.parametrize(
    "mutation", ["role", "permissions", "duplicate_actor", "no_newline", "oversize"]
)
def test_untrusted_binding_is_rejected_before_owner(mutation):
    owner = Mock()
    value = binding().model_dump(mode="json")
    raw = canonical_json_bytes(value) + b"\n"
    if mutation in {"role", "permissions"}:
        value[mutation] = "ADMIN"
        raw = canonical_json_bytes(value) + b"\n"
    elif mutation == "duplicate_actor":
        raw = raw.replace(b'{"actor_id":', b'{"actor_id":"spoofed","actor_id":', 1)
    elif mutation == "no_newline":
        raw = raw[:-1]
    else:
        raw = b" " * (MAX_PRIVATE_SNAPSHOT_FRAME_BYTES + 1)
    reply = parse_binding_reply(json.loads(dispatch_snapshot_frame(owner, raw)))
    assert reply.error_code == (
        "INFERENCE_TRANSFER_SNAPSHOT_BUDGET_EXCEEDED"
        if mutation == "oversize"
        else "INFERENCE_TRANSFER_SNAPSHOT_REQUEST_INVALID"
    )
    owner.prepare.assert_not_called()


def test_client_reuses_bounded_transport_and_fixed_endpoint(monkeypatch):
    expected = snapshot_prepare_result()
    reply = InferenceTransferSnapshotBindingReply(
        status="SUCCESS", result=expected, error_code=None
    )
    exchange = Mock(return_value=reply.model_dump(mode="json"))
    monkeypatch.setattr(client_module, "exchange_chat_frame", exchange)
    endpoint = ChatSocketEndpoint(client_module.Path("/fixed/private/catalog.sock"), 12345, 45678)
    assert (
        CatalogInferenceTransferSnapshotClient(endpoint).execute(ACTOR, snapshot_prepare())
        == expected
    )
    assert exchange.call_args.args[0] == endpoint
    assert exchange.call_args.kwargs == {
        "request_limit": MAX_PRIVATE_SNAPSHOT_FRAME_BYTES,
        "reply_limit": MAX_PRIVATE_SNAPSHOT_FRAME_BYTES,
        "timeout": SNAPSHOT_RESPONSE_TIMEOUT_SECONDS,
    }


@pytest.mark.parametrize(
    "kind,code", [("UNAVAILABLE", "SNAPSHOT_UNAVAILABLE"), ("INVALID", "SNAPSHOT_REQUEST_INVALID")]
)
def test_client_preserves_transport_classification_without_retry(monkeypatch, kind, code):
    exchange = Mock(side_effect=ChatTransportError(kind))
    monkeypatch.setattr(client_module, "exchange_chat_frame", exchange)
    endpoint = ChatSocketEndpoint(client_module.Path("/fixed/private/catalog.sock"), 12345, 45678)
    with pytest.raises(InferenceTransferSnapshotClientError, match=code):
        CatalogInferenceTransferSnapshotClient(endpoint).execute(ACTOR, snapshot_prepare())
    assert exchange.call_count == 1


def test_other_actor_response_is_rejected_without_content_return(monkeypatch):
    from tests.unit.inference_transfer_snapshot_fixtures import snapshot_header

    foreign = snapshot_prepare_result(header=snapshot_header(actor_id="other-operator"))
    reply = InferenceTransferSnapshotBindingReply(status="SUCCESS", result=foreign, error_code=None)
    monkeypatch.setattr(
        client_module, "exchange_chat_frame", Mock(return_value=reply.model_dump(mode="json"))
    )
    endpoint = ChatSocketEndpoint(client_module.Path("/fixed/private/catalog.sock"), 12345, 45678)
    with pytest.raises(InferenceTransferSnapshotClientError, match="REQUEST_INVALID"):
        CatalogInferenceTransferSnapshotClient(endpoint).execute(ACTOR, snapshot_prepare())


def test_predecessor_reply_is_unavailable_without_cross_schema_reinterpretation(monkeypatch):
    old_reply = {
        "operation": "GET_ITEM_CONTENT",
        "status": "FAILED",
        "error_code": "CATALOG_APPLICATION_REQUEST_INVALID",
    }
    monkeypatch.setattr(client_module, "exchange_chat_frame", Mock(return_value=old_reply))
    endpoint = ChatSocketEndpoint(client_module.Path("/fixed/private/catalog.sock"), 12345, 45678)
    with pytest.raises(InferenceTransferSnapshotClientError, match="SNAPSHOT_UNAVAILABLE"):
        CatalogInferenceTransferSnapshotClient(endpoint).execute(ACTOR, snapshot_prepare())
