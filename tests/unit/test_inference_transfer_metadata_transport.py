"""Temporary Unix-socket/fake-owner metadata transport, not installed auth proof."""

from __future__ import annotations

import json
import os
import socket
import threading
from pathlib import Path
from unittest.mock import Mock

import eom_api.services.inference_transfer_metadata_client as client_module
import pytest
from eom_api.services.inference_transfer_metadata import InferenceTransferMetadataReadError
from eom_api.services.inference_transfer_metadata_client import (
    CatalogInferenceTransferMetadataClient,
)
from eom_catalog_contracts.inference_transfer_metadata import (
    MAX_METADATA_FRAME_BYTES,
    InferenceTransferMetadataBindingRequest,
    parse_metadata_binding_reply,
)
from eom_catalog_service.inference_transfer_metadata_dispatch import dispatch_metadata_frame
from eom_catalog_service.inference_transfer_service import InferenceTransferServiceError
from eom_identifiers import canonical_json_bytes
from eom_orchestrator.general_chat_socket import ChatSocketEndpoint

from tests.unit.inference_transfer_metadata_fixtures import ACTOR, metadata_request, metadata_result
from tests.unit.test_catalog_application_boundary import _server


def frame():
    return (
        canonical_json_bytes(
            InferenceTransferMetadataBindingRequest(
                actor_id=ACTOR, request=metadata_request()
            ).model_dump(mode="json")
        )
        + b"\n"
    )


def test_api_peer_roundtrip_uses_actual_actor_existing_socket(tmp_path):
    server = _server(tmp_path)
    owner = Mock()
    owner.resolve.return_value = metadata_result()
    server.inference_transfer_metadata = owner
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        client = CatalogInferenceTransferMetadataClient(
            ChatSocketEndpoint(server.socket_path, os.getuid(), os.getgid())
        )
        assert client.resolve(ACTOR, metadata_request()) == metadata_result()
        owner.resolve.assert_called_once_with(ACTOR, metadata_request())
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@pytest.mark.parametrize("peer", ["chat_owner", "worker"])
def test_api_only_operation_is_not_open_to_chat_or_worker(tmp_path, peer):
    server = _server(tmp_path, allowed_uid=os.getuid() + 100000)
    server.chat_owner_uid = os.getuid() if peer == "chat_owner" else os.getuid() + 200000
    left, right = socket.socketpair()
    try:
        assert not server.peer_can_operate(left, "INFERENCE_TRANSFER_METADATA_RESOLVE")
    finally:
        left.close()
        right.close()
        server.server_close()


@pytest.mark.parametrize("mutation", ["authority", "duplicate", "no_newline", "oversize"])
def test_untrusted_frame_rejected_before_owner(mutation):
    raw = frame()
    if mutation == "authority":
        value = json.loads(raw)
        value["role"] = "ADMIN"
        raw = canonical_json_bytes(value) + b"\n"
    elif mutation == "duplicate":
        raw = raw.replace(b'"actor_id":', b'"actor_id":"bad","actor_id":')
    elif mutation == "no_newline":
        raw = raw[:-1]
    elif mutation == "oversize":
        raw = b"x" * (MAX_METADATA_FRAME_BYTES + 1)
    owner = Mock()
    reply = parse_metadata_binding_reply(json.loads(dispatch_metadata_frame(owner, raw)))
    assert reply.status == "FAILED" and reply.actor_id is None
    owner.resolve.assert_not_called()


@pytest.mark.parametrize(
    "failure", ["INFERENCE_TRANSFER_FORBIDDEN", "INTERNAL_SECRET", "exception"]
)
def test_owner_failures_are_sanitized_and_exact_request_bound(failure):
    owner = Mock()
    owner.resolve.side_effect = (
        RuntimeError("secret-body")
        if failure == "exception"
        else InferenceTransferServiceError(failure)
    )
    raw = dispatch_metadata_frame(owner, frame())
    reply = parse_metadata_binding_reply(json.loads(raw))
    assert reply.actor_id == ACTOR and reply.request_sha256 == metadata_request().request_sha256
    assert reply.error_code == (
        failure
        if failure == "INFERENCE_TRANSFER_FORBIDDEN"
        else "INFERENCE_TRANSFER_METADATA_UNAVAILABLE"
    )
    assert b"secret-body" not in raw and b"INTERNAL_SECRET" not in raw


def test_missing_successor_owner_is_explicit_unavailable():
    reply = parse_metadata_binding_reply(json.loads(dispatch_metadata_frame(None, frame())))
    assert reply.error_code == "INFERENCE_TRANSFER_METADATA_UNAVAILABLE"


def test_client_rejects_predecessor_protocol_without_reinterpreting(monkeypatch):
    monkeypatch.setattr(
        client_module,
        "exchange_chat_frame",
        Mock(return_value={"operation": "CHAT_RAG", "status": "SUCCESS"}),
    )
    with pytest.raises(InferenceTransferMetadataReadError, match="UNAVAILABLE"):
        CatalogInferenceTransferMetadataClient(
            ChatSocketEndpoint(path=Path("/nonexistent"), owner_uid=0, group_gid=0)
        ).resolve(ACTOR, metadata_request())
