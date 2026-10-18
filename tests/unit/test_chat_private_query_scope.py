"""Synthetic scope identity, read owner and Unix adapter checks; no login or model."""

from __future__ import annotations

import json
import os
import socket
import threading
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, call

import pytest
from eom_catalog_contracts.chat_private_query_scope import (
    CHAT_PRIVATE_SCOPE_REPLY_BYTES,
    CHAT_PRIVATE_SCOPE_REQUEST_BYTES,
    ChatPrivateQueryScopeContractError,
    ChatPrivateQueryScopeReply,
    build_chat_private_query_scope_request,
    failed_chat_private_query_scope_reply,
    parse_chat_private_query_scope_request,
    validate_chat_private_query_scope_reply,
)
from eom_catalog_contracts.knowledge import KnowledgeGraphSnapshotPointer
from eom_catalog_contracts.validation import CATALOG_SCHEMA_RESOURCES, load_schema
from eom_catalog_service.chat_rag_resolution import ChatRagResolutionError
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_orchestrator import general_chat_knowledge as adapter
from eom_orchestrator.general_chat_socket import ChatTransportError
from eom_orchestrator.general_chat_state import ChatError
from jsonschema import Draft202012Validator
from sqlalchemy.exc import SQLAlchemyError

from tests.unit.general_chat_rag_fixtures import scope
from tests.unit.test_catalog_application_boundary import _server
from tests.unit.test_chat_rag_resolution import ACTOR, service


def graph_pointer() -> KnowledgeGraphSnapshotPointer:
    raw_hash = "sha256:" + "b" * 64
    return KnowledgeGraphSnapshotPointer.model_validate(
        {
            "graph_id": "graph_" + "1" * 32,
            "graph_snapshot_revision_id": scope().snapshot.graph_snapshot_revision_id,
            "manifest_sha256": raw_hash,
            "manifest_artifact": {
                "artifact_id": "artifact_" + "3" * 32,
                "artifact_revision_id": "rev_" + "4" * 32,
                "sha256": raw_hash,
                "schema_ref": "eom://schemas/knowledge/knowledge-graph-snapshot-manifest/9.0",
                "media_type": "application/json",
                "member_path": "projections/manifest.json",
                "logical_name": "manifest.json",
            },
        }
    )


def reply_document() -> dict:
    request = build_chat_private_query_scope_request(ACTOR, scope())
    return {
        "schema_version": "chat-private-query-scope-reply/1.0",
        "request_sha256": request.request_sha256,
        "status": "SUCCEEDED",
        "scope": scope().model_dump(mode="json"),
        "graph_snapshot": graph_pointer().model_dump(mode="json"),
        "error_code": None,
    }


def test_schema_resource_matches_canonical_bytes_and_declared_raw_hash():
    root = Path(__file__).resolve().parents[2]
    resource = CATALOG_SCHEMA_RESOURCES["chat-private-query-scope"]
    raw = (root / resource.canonical_path).read_bytes()
    packaged = root / "packages/catalog_contracts/eom_catalog_contracts" / resource.resource_path
    assert raw == packaged.read_bytes()
    assert sha256_bytes(raw) == resource.sha256
    schema = load_schema("chat-private-query-scope")
    Draft202012Validator.check_schema(schema)
    assert schema["$id"] == "eom://schemas/knowledge/chat-private-query-scope/1.0"


def test_scope_hash_and_manifest_raw_hash_remain_distinct_and_fully_pinned():
    request = build_chat_private_query_scope_request(ACTOR, scope())
    reply = validate_chat_private_query_scope_reply(request, reply_document())
    assert reply.scope == request.scope
    assert reply.graph_snapshot == graph_pointer()
    assert reply.graph_snapshot.manifest_sha256 != reply.scope.snapshot.sha256
    assert len(canonical_json_bytes(request.model_dump(mode="json"))) < 4096
    assert len(canonical_json_bytes(reply.model_dump(mode="json"))) < 16384


@pytest.mark.parametrize(
    "change",
    ["role", "actor", "latest", "policy", "hash", "hidden", "oversized"],
)
def test_scope_request_rejects_extra_authority_forged_hash_and_latest(change):
    request = build_chat_private_query_scope_request(ACTOR, scope())
    value = request.model_dump(mode="json")
    if change == "role":
        value["requester_role"] = "ADMIN"
    elif change == "actor":
        value["actor_id"] = "operator_" + "0" * 32
    elif change == "latest":
        value["scope"]["snapshot"]["graph_snapshot_revision_id"] = "latest"
    elif change == "policy":
        value["scope"]["policy"]["sha256"] = "sha256:" + "0" * 64
    elif change == "hash":
        value["request_sha256"] = "sha256:" + "0" * 64
    elif change == "hidden":
        value = request.model_copy(update={"role": "ADMIN"})
    else:
        value["actor_id"] = "x" * CHAT_PRIVATE_SCOPE_REQUEST_BYTES
    with pytest.raises(
        ChatPrivateQueryScopeContractError, match=r"^CHAT_PRIVATE_QUERY_SCOPE_INVALID$"
    ):
        parse_chat_private_query_scope_request(value)


@pytest.mark.parametrize(
    "change",
    ["request", "scope", "revision", "raw", "member", "media", "schema", "missing", "extra"],
)
def test_scope_reply_rejects_incompatible_or_partially_pinned_reply(change):
    request = build_chat_private_query_scope_request(ACTOR, scope())
    value = reply_document()
    if change == "request":
        value["request_sha256"] = "sha256:" + "0" * 64
    elif change == "scope":
        value["scope"]["policy"]["sha256"] = "sha256:" + "0" * 64
    elif change == "revision":
        value["graph_snapshot"]["graph_snapshot_revision_id"] = "graphrev_" + "0" * 32
    elif change == "raw":
        value["graph_snapshot"]["manifest_sha256"] = value["scope"]["snapshot"]["sha256"]
    elif change in {"member", "media", "schema"}:
        key, replacement = {
            "member": ("member_path", "other/manifest.json"),
            "media": ("media_type", "application/pdf"),
            "schema": (
                "schema_ref",
                "eom://schemas/knowledge/knowledge-graph-snapshot-manifest/99.0",
            ),
        }[change]
        value["graph_snapshot"]["manifest_artifact"][key] = replacement
    elif change == "missing":
        value["graph_snapshot"] = None
    else:
        value["graph_snapshot"]["role"] = "ADMIN"
    with pytest.raises(ChatPrivateQueryScopeContractError):
        validate_chat_private_query_scope_reply(request, value)


@pytest.mark.parametrize(
    "code",
    ["CHAT_KNOWLEDGE_FORBIDDEN", "CHAT_KNOWLEDGE_POINTER_INVALID", "CHAT_KNOWLEDGE_UNAVAILABLE"],
)
def test_denial_does_not_expose_partial_pointers(code):
    request = build_chat_private_query_scope_request(ACTOR, scope())
    reply = failed_chat_private_query_scope_reply(request, code)
    assert reply.status == "FAILED"
    assert reply.scope is None and reply.graph_snapshot is None
    document = reply.model_dump(mode="json")
    document["scope"] = scope().model_dump(mode="json")
    with pytest.raises(ChatPrivateQueryScopeContractError):
        validate_chat_private_query_scope_reply(request, document)


def test_scope_read_reuses_actor_and_graph_owner_in_one_read_only_transaction():
    value = service()
    session = MagicMock()
    value.sessions = MagicMock()
    value.sessions.return_value.__enter__.return_value = session
    sequence = Mock()
    value._authority = sequence.authority
    value._scope = sequence.scope
    value._scope.return_value = graph_pointer()
    request = build_chat_private_query_scope_request(ACTOR, scope())
    reply = value.resolve_private_query_scope(request)
    assert reply.status == "SUCCEEDED" and reply.graph_snapshot == graph_pointer()
    session.connection.assert_called_once_with(
        execution_options={"isolation_level": "REPEATABLE READ"}
    )
    assert str(session.execute.call_args.args[0]) == "SET TRANSACTION READ ONLY"
    assert sequence.mock_calls == [
        call.authority(session, ACTOR, scope().policy),
        call.scope(session, scope()),
    ]
    session.add.assert_not_called()
    session.commit.assert_not_called()


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (ChatRagResolutionError("CHAT_KNOWLEDGE_FORBIDDEN"), "CHAT_KNOWLEDGE_FORBIDDEN"),
        (
            ChatRagResolutionError("CHAT_KNOWLEDGE_POINTER_INVALID"),
            "CHAT_KNOWLEDGE_POINTER_INVALID",
        ),
        (SQLAlchemyError("private detail"), "CHAT_KNOWLEDGE_UNAVAILABLE"),
        (OSError("private path"), "CHAT_KNOWLEDGE_POINTER_INVALID"),
    ],
)
def test_scope_read_authority_failure_stops_before_manifest_resolution(error, code):
    value = service()
    value.sessions = MagicMock()
    value._authority = Mock(side_effect=error)
    value._scope = Mock()
    reply = value.resolve_private_query_scope(
        build_chat_private_query_scope_request(ACTOR, scope())
    )
    assert reply.error_code == code and reply.graph_snapshot is None and reply.scope is None
    assert "private path" not in json.dumps(reply.model_dump(mode="json"))
    assert "private detail" not in json.dumps(reply.model_dump(mode="json"))
    value._scope.assert_not_called()


def identities(monkeypatch):
    monkeypatch.setattr(adapter.pwd, "getpwnam", lambda _: SimpleNamespace(pw_uid=os.getuid()))
    monkeypatch.setattr(adapter.grp, "getgrnam", lambda _: SimpleNamespace(gr_gid=os.getgid()))


@pytest.mark.parametrize("kind", ["INVALID", "UNAVAILABLE", "corrupt"])
def test_client_one_exchange_no_fallback_or_retry(monkeypatch, kind):
    identities(monkeypatch)
    exchange = Mock(return_value=reply_document())
    if kind == "corrupt":
        exchange.return_value["request_sha256"] = "sha256:" + "0" * 64
    else:
        exchange.side_effect = ChatTransportError(kind)
    monkeypatch.setattr(adapter, "exchange_chat_frame", exchange)
    code = (
        "GENERAL_CHAT_APPLICATION_UNAVAILABLE"
        if kind == "UNAVAILABLE"
        else "GENERAL_CHAT_POINTER_INVALID"
    )
    with pytest.raises(ChatError, match=code):
        adapter.CatalogChatKnowledgeClient().resolve_private_query_scope(
            actor_id=ACTOR, scope=scope()
        )
    assert exchange.call_count == 1
    assert exchange.call_args.kwargs == {"request_limit": 4096, "reply_limit": 16384, "timeout": 20}


def test_real_temporary_unix_scope_read_uses_chat_readonly_peer_and_exact_reply(
    tmp_path, monkeypatch
):
    identities(monkeypatch)
    server = _server(tmp_path, allowed_uid=os.getuid() + 100000)
    server.chat_owner_uid = os.getuid()
    expected = ChatPrivateQueryScopeReply.model_validate(reply_document())
    resolve = Mock(return_value=expected)
    server.chat_rag = SimpleNamespace(resolve_private_query_scope=resolve)
    monkeypatch.setattr(adapter, "CATALOG_APPLICATION_SOCKET_PATH", str(server.socket_path))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        actual = adapter.CatalogChatKnowledgeClient().resolve_private_query_scope(
            actor_id=ACTOR, scope=scope()
        )
        assert actual == expected
        resolve.assert_called_once_with(build_chat_private_query_scope_request(ACTOR, scope()))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    assert not thread.is_alive()


@pytest.mark.parametrize("failure", ["unconfigured", "raised", "wrong_request", "wrong_scope"])
def test_real_unix_service_failure_never_returns_a_partial_pin(tmp_path, monkeypatch, failure):
    identities(monkeypatch)
    server = _server(tmp_path, allowed_uid=os.getuid() + 100000)
    server.chat_owner_uid = os.getuid()
    response = reply_document()
    if failure == "wrong_request":
        response["request_sha256"] = "sha256:" + "0" * 64
    elif failure == "wrong_scope":
        response["scope"]["policy"]["sha256"] = "sha256:" + "0" * 64
    resolve = Mock(return_value=response)
    if failure == "raised":
        resolve.side_effect = RuntimeError("private service details")
    server.chat_rag = (
        None if failure == "unconfigured" else SimpleNamespace(resolve_private_query_scope=resolve)
    )
    monkeypatch.setattr(adapter, "CATALOG_APPLICATION_SOCKET_PATH", str(server.socket_path))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        actual = adapter.CatalogChatKnowledgeClient().resolve_private_query_scope(
            actor_id=ACTOR, scope=scope()
        )
        assert actual.status == "FAILED" and actual.error_code == "CHAT_KNOWLEDGE_UNAVAILABLE"
        assert actual.scope is None and actual.graph_snapshot is None
        assert resolve.call_count == (0 if failure == "unconfigured" else 1)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    assert not thread.is_alive()


@pytest.mark.parametrize("change", ["noncanonical", "unknown_authority", "oversize", "forged_hash"])
def test_real_unix_invalid_frame_never_reaches_read_owner(tmp_path, change):
    server = _server(tmp_path, allowed_uid=os.getuid() + 100000)
    server.chat_owner_uid = os.getuid()
    resolve = Mock(return_value=reply_document())
    server.chat_rag = SimpleNamespace(resolve_private_query_scope=resolve)
    document = deepcopy(
        build_chat_private_query_scope_request(ACTOR, scope()).model_dump(mode="json")
    )
    if change == "unknown_authority":
        document["role"] = "ADMIN"
        document["request_sha256"] = content_sha256(
            {k: v for k, v in document.items() if k != "request_sha256"}
        )
    elif change == "oversize":
        document["actor_id"] = "x" * CHAT_PRIVATE_SCOPE_REQUEST_BYTES
    elif change == "forged_hash":
        document["request_sha256"] = "sha256:" + "0" * 64
    raw = (
        json.dumps(document).encode()
        if change == "noncanonical"
        else canonical_json_bytes(document)
    ) + b"\n"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with socket.socket(socket.AF_UNIX) as connection:
            connection.settimeout(3)
            connection.connect(str(server.socket_path))
            connection.sendall(raw)
            connection.shutdown(socket.SHUT_WR)
            assert connection.recv(CHAT_PRIVATE_SCOPE_REPLY_BYTES) == b""
        resolve.assert_not_called()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
