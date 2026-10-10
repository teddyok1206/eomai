"""Fixed API-peer comparison reads with synthetic owners and temporary sockets."""

from __future__ import annotations

import json
import os
import socket
import threading
from unittest.mock import Mock

import pytest
from eom_catalog_contracts.inference_transfer_workflow_binding import (
    MAX_PRIVATE_TRANSFER_WORKFLOW_BYTES,
    parse_workflow_binding_reply,
    validate_workflow_binding_reply,
)
from eom_catalog_service.inference_transfer_service import InferenceTransferServiceError
from eom_catalog_service.inference_transfer_workflow_dispatch import (
    dispatch_inference_transfer_workflow_frame,
)
from eom_identifiers import canonical_json_bytes

from tests.unit.inference_transfer_invocation_fixtures import binding_pair
from tests.unit.test_catalog_application_boundary import _server


def test_dispatch_binds_actual_actor_request_and_typed_canonical_result():
    request, expected = binding_pair()
    owner = Mock()
    owner.read.return_value = expected.result
    reply = parse_workflow_binding_reply(
        json.loads(
            dispatch_inference_transfer_workflow_frame(owner, canonical_json_bytes(request) + b"\n")
        )
    )
    validate_workflow_binding_reply(request, reply)
    assert reply == expected
    owner.read.assert_called_once_with(request.actor_id, request.request)


@pytest.mark.parametrize(
    "code",
    [
        "INFERENCE_TRANSFER_FORBIDDEN",
        "INFERENCE_TRANSFER_SOURCE_PIN_MISMATCH",
        "INFERENCE_TRANSFER_WORKFLOW_CHANGED",
    ],
)
def test_owner_errors_have_exact_valid_context_and_no_partial_content(code):
    request, _ = binding_pair()
    owner = Mock()
    owner.read.side_effect = InferenceTransferServiceError(code)
    reply = parse_workflow_binding_reply(
        json.loads(
            dispatch_inference_transfer_workflow_frame(owner, canonical_json_bytes(request) + b"\n")
        )
    )
    assert reply.error_code == code and reply.result is None
    assert (
        reply.actor_id == request.actor_id
        and reply.request_binding_sha256 == request.binding_sha256
    )
    validate_workflow_binding_reply(request, reply)


@pytest.mark.parametrize(
    "failure",
    [RuntimeError("secret item contents"), InferenceTransferServiceError("UNKNOWN_SECRET_CODE")],
)
def test_unknown_failure_is_sanitized_without_private_error_or_content(failure):
    request, _ = binding_pair()
    owner = Mock()
    owner.read.side_effect = failure
    raw = dispatch_inference_transfer_workflow_frame(owner, canonical_json_bytes(request) + b"\n")
    reply = parse_workflow_binding_reply(json.loads(raw))
    assert reply.error_code == "INFERENCE_TRANSFER_WORKFLOW_UNAVAILABLE"
    assert b"secret item" not in raw and b"UNKNOWN_SECRET" not in raw


def test_missing_source_composition_reports_unavailable_not_fake_pending():
    request, _ = binding_pair()
    reply = parse_workflow_binding_reply(
        json.loads(
            dispatch_inference_transfer_workflow_frame(None, canonical_json_bytes(request) + b"\n")
        )
    )
    assert reply.error_code == "INFERENCE_TRANSFER_WORKFLOW_UNAVAILABLE"
    assert reply.result is None


@pytest.mark.parametrize(
    "mutation",
    ["actor_override", "duplicate_actor", "hash", "no_newline", "two_frames", "oversize"],
)
def test_invalid_frame_never_manufactures_context_or_calls_owner(mutation):
    request, _ = binding_pair()
    document = request.model_dump(mode="json")
    raw = canonical_json_bytes(document) + b"\n"
    if mutation == "actor_override":
        document["role"] = "ADMIN"
        raw = canonical_json_bytes(document) + b"\n"
    elif mutation == "duplicate_actor":
        raw = raw[:-2] + b',"actor_id":"ADMIN"}\n'
    elif mutation == "hash":
        document["binding_sha256"] = "sha256:" + "9" * 64
        raw = canonical_json_bytes(document) + b"\n"
    elif mutation == "no_newline":
        raw = raw[:-1]
    elif mutation == "two_frames":
        raw += raw
    else:
        raw = b" " * (MAX_PRIVATE_TRANSFER_WORKFLOW_BYTES + 1)
    owner = Mock()
    reply = parse_workflow_binding_reply(
        json.loads(dispatch_inference_transfer_workflow_frame(owner, raw))
    )
    assert reply.status == "FAILED" and reply.result is None
    assert reply.actor_id is None and reply.request_binding_sha256 is None
    owner.read.assert_not_called()


def test_owner_cannot_return_other_workflow_or_unverified_mode():
    request, expected = binding_pair()
    owner = Mock()
    owner.read.return_value = expected.result.model_copy(
        update={"workflow_id": "workflow_" + "9" * 32}
    )
    reply = parse_workflow_binding_reply(
        json.loads(
            dispatch_inference_transfer_workflow_frame(owner, canonical_json_bytes(request) + b"\n")
        )
    )
    assert reply.status == "FAILED" and reply.result is None


def test_production_server_branch_round_trip_uses_existing_fixed_peer_socket(tmp_path):
    request, expected = binding_pair()
    server = _server(tmp_path)
    owner = Mock()
    owner.read.return_value = expected.result
    server.inference_transfer_workflow_reads = owner
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(5)
            connection.connect(str(server.socket_path))
            connection.sendall(canonical_json_bytes(request) + b"\n")
            with connection.makefile("rb") as stream:
                reply = parse_workflow_binding_reply(
                    json.loads(stream.readline(MAX_PRIVATE_TRANSFER_WORKFLOW_BYTES + 1))
                )
        validate_workflow_binding_reply(request, reply)
        assert reply == expected
        owner.read.assert_called_once_with(request.actor_id, request.request)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@pytest.mark.parametrize("peer", ["chat_owner", "worker"])
def test_chat_owner_and_workers_cannot_use_new_operation_even_with_actor_string(tmp_path, peer):
    server = _server(tmp_path, allowed_uid=os.getuid() + 100000)
    server.chat_owner_uid = os.getuid() if peer == "chat_owner" else os.getuid() + 200000
    left, right = socket.socketpair(socket.AF_UNIX)
    try:
        assert not server.peer_can_operate(left, "INFERENCE_TRANSFER_WORKFLOW_READ")
    finally:
        left.close()
        right.close()
        server.server_close()
