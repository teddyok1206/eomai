"""Real existing Unix server/peer framing; synthetic source authority and results."""

import json
import os
import socket
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_api.services import exam_similarity_client as client_module
from eom_api.services.exam_similarity_client import (
    CatalogExamSimilarityClient,
    ExamSimilarityClientError,
)
from eom_catalog_contracts.exam_similarity_read import (
    MAX_EXAM_READ_FRAME_BYTES,
    ExamObservationReadReply,
)
from eom_catalog_service.exam_similarity_read_dispatch import dispatch_exam_similarity_read_frame
from eom_catalog_service.exam_similarity_read_service import ExamObservationReadError
from eom_identifiers import canonical_json_bytes
from eom_orchestrator.general_chat_socket import ChatSocketEndpoint

from tests.unit.exam_similarity_read_fixtures import read_case
from tests.unit.test_catalog_application_boundary import _server


def test_real_existing_socket_replays_read_without_submitting_commands(tmp_path):
    request, expected, _ = read_case()
    server = _server(tmp_path)
    reader = SimpleNamespace(read=Mock(return_value=expected.result))
    server.exam_similarity_reads = reader
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        client = CatalogExamSimilarityClient(
            ChatSocketEndpoint(server.socket_path, os.getuid(), os.getgid())
        )
        for _ in range(2):
            assert client.read(request.actor_id, request.selection) == expected.result
        assert reader.read.call_count == 2
        assert all(call.args == (request,) for call in reader.read.call_args_list)
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


@pytest.mark.parametrize("peer", ("chat", "runner"))
def test_non_api_peers_cannot_use_assembly_observation(tmp_path, peer):
    server = _server(tmp_path, allowed_uid=os.getuid() + 100000)
    if peer == "chat":
        server.chat_owner_uid = os.getuid()
    else:
        server.workflow_runner_uid = os.getuid()
        server.workflow_similarity_reads = object()
    left, right = socket.socketpair(socket.AF_UNIX)
    try:
        assert server.peer_is_allowed(left)
        assert not server.peer_can_operate(left, "READ_EXAM_SIMILARITY_OBSERVATION")
    finally:
        left.close()
        right.close()
        server.server_close()


@pytest.mark.parametrize("fault", ("oversize", "no_newline", "two_lines", "extra", "json"))
def test_malformed_frames_never_reach_owner_or_echo_input(fault):
    request, _, _ = read_case()
    raw = canonical_json_bytes(request) + b"\n"
    if fault == "oversize":
        raw = b"x" * (MAX_EXAM_READ_FRAME_BYTES + 1)
    elif fault == "no_newline":
        raw = raw[:-1]
    elif fault == "two_lines":
        raw += raw
    elif fault == "extra":
        raw = canonical_json_bytes(request.model_dump(mode="json") | {"private": "no-echo"}) + b"\n"
    else:
        raw = b'{"private":"no-echo"\n'
    reader = SimpleNamespace(read=Mock())
    wire = dispatch_exam_similarity_read_frame(reader, raw)
    reply = ExamObservationReadReply.model_validate(json.loads(wire))
    assert reply.status == "FAILED" and reply.result is None and reply.actor_id is None
    assert b"no-echo" not in wire
    reader.read.assert_not_called()


@pytest.mark.parametrize("fault", ("missing", "denied", "unexpected", "bad_result", "unknown_code"))
def test_owner_errors_never_disclose_partial_result_or_exception(fault):
    request, expected, _ = read_case()
    reader = SimpleNamespace(read=Mock(return_value=expected.result))
    if fault == "missing":
        reader = None
    elif fault == "denied":
        reader.read.side_effect = ExamObservationReadError("SOURCE_ACCESS_DENIED")
    elif fault == "unexpected":
        reader.read.side_effect = RuntimeError("private/path no-echo")
    elif fault == "bad_result":
        reader.read.return_value = {"private": "no-echo"}
    else:
        reader.read.side_effect = ExamObservationReadError("private/path no-echo")
    wire = dispatch_exam_similarity_read_frame(reader, canonical_json_bytes(request) + b"\n")
    reply = ExamObservationReadReply.model_validate(json.loads(wire))
    assert reply.status == "FAILED" and reply.result is None
    assert b"no-echo" not in wire


@pytest.mark.parametrize("fault", ("actor", "hash", "operation"))
def test_client_rejects_well_formed_substitution(monkeypatch, fault):
    request, reply, _ = read_case()
    body = reply.model_dump(mode="json")
    if fault == "actor":
        body["actor_id"] = "operator_" + "f" * 32
    elif fault == "hash":
        body["request_sha256"] = "sha256:" + "f" * 64
    else:
        body["operation"] = "READ_SIMILARITY_CONTEXT"
    monkeypatch.setattr(client_module, "exchange_chat_frame", Mock(return_value=body))
    client = CatalogExamSimilarityClient(
        ChatSocketEndpoint(Path("/tmp/synthetic-not-opened-catalog.sock"), os.getuid(), os.getgid())
    )
    with pytest.raises(ExamSimilarityClientError, match="EXAM_OBSERVATION_UNAVAILABLE"):
        client.read(request.actor_id, request.selection)
