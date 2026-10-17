"""Real bounded Unix transport; source/claim metadata are explicit synthetic fixtures."""

from __future__ import annotations

import os
from pathlib import Path
from threading import Thread

import pytest
from eom_catalog_contracts.private_chat_query_read import (
    PrivateChatQueryReadProtocolError,
    parse_private_chat_query_read_request,
)
from eom_catalog_contracts.validation import CATALOG_SCHEMA_RESOURCES, load_schema
from eom_identifiers import sha256_bytes
from eom_orchestrator.general_chat_client import GeneralChatOwnerClient
from eom_orchestrator.general_chat_owner_server import (
    GeneralChatOwnerRpcServer,
    PrivateChatQueryRpcAccess,
)
from eom_orchestrator.general_chat_private_query_client import GeneralChatPrivateQueryClient
from eom_orchestrator.general_chat_socket import ChatSocketEndpoint
from eom_orchestrator.general_chat_state import ChatError
from eom_protocol.general_chat_owner_messages import ChatOwnerFault
from eom_protocol.general_chat_worker_messages import (
    load_chat_worker_ticket_schema,
    read_chat_worker_ticket,
)
from jsonschema import Draft202012Validator

from tests.unit.test_general_chat_owner_rpc import RecordingOwner
from tests.unit.test_private_chat_query_source import request, source_case


@pytest.fixture
def rpc(tmp_path):
    root = tmp_path / "source-rpc"
    root.mkdir(mode=0o750)
    endpoint = ChatSocketEndpoint(root / "source.sock", os.getuid(), os.getgid())
    value = source_case()
    server = GeneralChatOwnerRpcServer(
        None,
        endpoint=endpoint,
        allowed_uids=frozenset(),
        private_queries=PrivateChatQueryRpcAccess(value.source, os.getuid()),
        maximum_requests=2,
    )
    thread = Thread(target=server.serve)
    thread.start()
    try:
        yield value, server, GeneralChatPrivateQueryClient(endpoint), endpoint
    finally:
        server.stop()
        thread.join(timeout=5)
        server.close()
        assert not thread.is_alive() and not endpoint.path.exists()


def test_socket_source_profile_materializes_then_authorizes_without_returning_text_twice(rpc):
    value, _, client, _ = rpc
    projection = client.materialize(value.ticket)
    assert projection.text == value.prepared.messages[-1].text
    assert client.authorize(projection.origin) == projection.origin
    assert value.repository.row.state == "RUNNING"


def test_maximum_question_keeps_spaces_units_negation_and_unicode(rpc):
    _, server, client, _ = rpc
    question = "  -2 m/s는 양수가 아니다. " + "가" * 15960 + "  "
    value = source_case(question=question)
    server.private_queries = PrivateChatQueryRpcAccess(value.source, os.getuid())
    assert client.materialize(value.ticket).text == question


def test_source_endpoint_never_accepts_existing_api_owner_commands(rpc):
    value, _, _, endpoint = rpc
    with pytest.raises(ChatOwnerFault):
        GeneralChatOwnerClient(endpoint).slot()
    assert value.evidence.reads == []


def test_api_profile_never_accepts_private_source_commands(tmp_path):
    root = tmp_path / "api-rpc"
    root.mkdir(mode=0o750)
    endpoint = ChatSocketEndpoint(root / "owner.sock", os.getuid(), os.getgid())
    owner = RecordingOwner()
    server = GeneralChatOwnerRpcServer(
        owner, endpoint=endpoint, allowed_uids=frozenset({os.getuid()})
    )
    thread = Thread(target=server.serve)
    thread.start()
    try:
        with pytest.raises(ChatError):
            GeneralChatPrivateQueryClient(endpoint).materialize(source_case().ticket)
        assert owner.calls == []
    finally:
        server.stop()
        thread.join(timeout=5)
        server.close()


def test_kernel_peer_not_socket_metadata_selects_source_access(rpc):
    value, server, client, _ = rpc
    server.private_queries = PrivateChatQueryRpcAccess(value.source, os.getuid() + 1)
    with pytest.raises(ChatError):
        client.materialize(value.ticket)
    assert value.evidence.reads == []


def test_live_revocation_is_not_hidden_as_empty_optional_evidence(rpc):
    value, _, client, _ = rpc
    projection = client.materialize(value.ticket)
    value.repository.revoked = True
    with pytest.raises(ChatError, match="GENERAL_CHAT_FORBIDDEN"):
        client.authorize(projection.origin)


def test_mixed_endpoint_roles_are_rejected_before_binding(tmp_path):
    endpoint = ChatSocketEndpoint(tmp_path / "never-created.sock", os.getuid(), os.getgid())
    value = source_case()
    with pytest.raises(ValueError):
        GeneralChatOwnerRpcServer(
            RecordingOwner(),
            endpoint=endpoint,
            allowed_uids=frozenset({os.getuid()}),
            private_queries=PrivateChatQueryRpcAccess(value.source, os.getuid()),
        )
    assert not endpoint.path.exists()


@pytest.mark.parametrize("extra", ["actor_id", "actor_role", "path", "password", "native_policy"])
def test_no_declared_actor_role_credential_or_path_enters_source_read(extra):
    value = source_case()
    body = request(value.ticket).model_dump(mode="json")
    body["command"][extra] = "untrusted-value"
    with pytest.raises(PrivateChatQueryReadProtocolError) as error:
        parse_private_chat_query_read_request(body)
    assert str(error.value) == "PRIVATE_CHAT_QUERY_SOURCE_INVALID"
    assert value.evidence.reads == []


def test_schema_resource_and_shared_ticket_are_not_a_second_family_copy():
    resource = CATALOG_SCHEMA_RESOURCES["general-chat-private-query-read"]
    root = Path(__file__).resolve().parents[2]
    raw = (root / resource.canonical_path).read_bytes()
    assert (
        raw
        == (
            root / "packages/catalog_contracts/eom_catalog_contracts" / resource.resource_path
        ).read_bytes()
    )
    assert sha256_bytes(raw) == resource.sha256
    schema = load_schema("general-chat-private-query-read")
    Draft202012Validator.check_schema(schema)
    assert schema["$defs"]["materialize"]["properties"]["ticket"] == {
        "$ref": "eom://schemas/general-chat/worker-ticket/1.0",
    }
    returned = load_chat_worker_ticket_schema()
    returned["properties"].clear()
    ticket = source_case().ticket
    assert read_chat_worker_ticket(ticket.model_dump(mode="json")) == ticket
    assert "actor_id" not in load_chat_worker_ticket_schema()["properties"]


def test_copied_nested_ticket_cannot_smuggle_fields_through_serialization():
    value = source_case()
    query = request(value.ticket)
    changed = query.model_copy(
        update={
            "command": query.command.model_copy(
                update={
                    "ticket": query.command.ticket.model_copy(update={"actor_role": "ADMIN"}),
                }
            ),
        }
    )
    with pytest.raises(PrivateChatQueryReadProtocolError):
        parse_private_chat_query_read_request(changed)
