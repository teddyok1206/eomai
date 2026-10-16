"""Real private Unix peer/framing, synthetic original Evidence/selected source observations."""

import json
import os
import socket
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_api.services import authoring_reference_client as client_module
from eom_api.services.authoring_reference_client import (
    AuthoringReferenceClientError,
    CatalogAuthoringReferenceClient,
)
from eom_catalog_contracts.authoring_reference import (
    MAX_AUTHORING_REFERENCE_REQUEST_BYTES,
    AuthoringReferenceReply,
)
from eom_catalog_service.authoring_reference_dispatch import dispatch_authoring_reference_frame
from eom_catalog_service.authoring_reference_selection import select_authoring_reference
from eom_catalog_service.similarity_context_ports import SimilarityContextReadError
from eom_identifiers import canonical_json_bytes, content_sha256
from eom_orchestrator.general_chat_socket import ChatSocketEndpoint, ChatTransportError

from tests.unit.test_authoring_reference_selection import case
from tests.unit.test_catalog_application_boundary import _server


def reply_for(value, status="SELECTED"):
    return AuthoringReferenceReply(
        schema_version="system-rag-authoring-reference-reply/1.0",
        operation="SELECT_ITEM_AUTHORING_REFERENCE",
        status=status,
        actor_id=value.request.actor_id,
        request_sha256=content_sha256(value.request),
        selection=select_authoring_reference(value.manifest, value.resolved)
        if status == "SELECTED"
        else None,
        error_code=None
        if status == "SELECTED"
        else "REFERENCE_NOT_OFFERED"
        if status == "UNAVAILABLE"
        else "SOURCE_ACCESS_DENIED",
    )


@pytest.mark.parametrize("available", (True, False))
def test_actual_socket_selects_original_evidence_without_caching_or_query_submission(
    tmp_path, available
):
    value = case()
    expected = reply_for(value).selection if available else None
    server = _server(tmp_path)
    service = SimpleNamespace(select=Mock(return_value=expected))
    server.authoring_reference_selection = service
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        client = CatalogAuthoringReferenceClient(
            ChatSocketEndpoint(server.socket_path, os.getuid(), os.getgid())
        )
        for _ in range(2):
            assert client.select(value.request.actor_id, value.publication) == expected
        assert service.select.call_count == 2
        assert all(call.args == (value.request,) for call in service.select.call_args_list)
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


@pytest.mark.parametrize("peer", ("chat", "runner"))
def test_other_existing_trusted_peers_cannot_select_an_authoring_reference(tmp_path, peer):
    server = _server(tmp_path, allowed_uid=os.getuid() + 100000)
    server.chat_owner_uid = os.getuid() if peer == "chat" else None
    server.workflow_runner_uid = os.getuid() if peer == "runner" else None
    server.workflow_similarity_reads = object() if peer == "runner" else None
    left, right = socket.socketpair(socket.AF_UNIX)
    try:
        assert server.peer_is_allowed(left)
        assert not server.peer_can_operate(left, "SELECT_ITEM_AUTHORING_REFERENCE")
    finally:
        left.close()
        right.close()
        server.server_close()


@pytest.mark.parametrize("fault", ("oversize", "two_lines", "no_newline", "bad_json", "role"))
def test_raw_invalid_selection_never_reaches_source_owner(fault):
    value = case()
    raw = canonical_json_bytes(value.request) + b"\n"
    if fault == "oversize":
        raw = b"x" * (MAX_AUTHORING_REFERENCE_REQUEST_BYTES + 1)
    elif fault == "two_lines":
        raw += raw
    elif fault == "no_newline":
        raw = raw[:-1]
    elif fault == "bad_json":
        raw = b'{"private":"do-not-echo"\n'
    else:
        raw = (
            canonical_json_bytes(value.request.model_dump(mode="json") | {"role": "ADMIN"}) + b"\n"
        )
    service = SimpleNamespace(select=Mock(side_effect=AssertionError("no source read")))
    raw_reply = dispatch_authoring_reference_frame(service, raw)
    reply = AuthoringReferenceReply.model_validate(json.loads(raw_reply))
    assert reply.status == "FAILED" and reply.selection is None and reply.actor_id is None
    assert reply.error_code == "AUTHORING_REFERENCE_REQUEST_INVALID"
    service.select.assert_not_called()
    assert b"do-not-echo" not in raw_reply


@pytest.mark.parametrize("fault", ("disabled", "denied", "exception", "bad_selection"))
def test_source_failures_never_become_optional_absence_or_partial_pointer(fault):
    value = case()
    service = SimpleNamespace(select=Mock(return_value=reply_for(value).selection))
    if fault == "disabled":
        service = None
    elif fault == "denied":
        service.select.side_effect = SimilarityContextReadError("SOURCE_REVOKED")
    elif fault == "exception":
        service.select.side_effect = RuntimeError("private/path do-not-echo")
    else:
        service.select.return_value = service.select.return_value.model_copy(
            update={"authority": "ADMIN"}
        )
    raw = dispatch_authoring_reference_frame(service, canonical_json_bytes(value.request) + b"\n")
    reply = AuthoringReferenceReply.model_validate(json.loads(raw))
    assert reply.status == "FAILED" and reply.selection is None
    assert reply.error_code == (
        "AUTHORITY_UNAVAILABLE"
        if fault == "disabled"
        else "SOURCE_REVOKED"
        if fault == "denied"
        else "AUTHORING_REFERENCE_UNAVAILABLE"
    )
    assert b"do-not-echo" not in raw and b"private/path" not in raw


@pytest.mark.parametrize("fault", ("actor", "request", "transport", "denied"))
def test_api_reply_binds_exact_current_actor_evidence_and_never_retries(
    monkeypatch, tmp_path, fault
):
    value = case()
    body = reply_for(value, "FAILED" if fault == "denied" else "SELECTED").model_dump(mode="json")
    if fault == "actor":
        body["actor_id"] = "operator_" + "f" * 32
    elif fault == "request":
        body["request_sha256"] = "sha256:" + "f" * 64
    exchange = Mock(return_value=body)
    if fault == "transport":
        exchange.side_effect = ChatTransportError("unknown outcome")
    monkeypatch.setattr(client_module, "exchange_chat_frame", exchange)
    client = CatalogAuthoringReferenceClient(
        ChatSocketEndpoint(tmp_path / "unused.sock", os.getuid(), os.getgid())
    )
    with pytest.raises(AuthoringReferenceClientError) as caught:
        client.select(value.request.actor_id, value.publication)
    assert caught.value.code == (
        "SOURCE_ACCESS_DENIED" if fault == "denied" else "AUTHORING_REFERENCE_UNAVAILABLE"
    )
    exchange.assert_called_once()
