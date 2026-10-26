from __future__ import annotations

import json
import os
import socket
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from threading import Event, Lock, Thread
from time import monotonic

import pytest
from eom_identifiers import canonical_json_bytes
from eom_orchestrator.general_chat_client import GeneralChatOwnerClient
from eom_orchestrator.general_chat_owner_server import GeneralChatOwnerRpcServer
from eom_orchestrator.general_chat_socket import (
    OWNER_REPLY_LIMIT,
    OWNER_REQUEST_LIMIT,
    ChatSocketEndpoint,
    ChatTransportError,
    bind_chat_listener,
    decode_chat_frame,
    receive_chat_frame,
    send_chat_frame,
)
from eom_orchestrator.general_chat_state import ChatError
from eom_protocol.general_chat_deletion import GeneralChatDelete, GeneralChatDeletion
from eom_protocol.general_chat_owner_messages import (
    ChatCreateCommand,
    ChatDeleteCommand,
    ChatOwnerErrorCode,
    ChatOwnerFault,
    ChatOwnerReply,
    ChatOwnerRequest,
    ChatSlotQuery,
    read_chat_owner_reply,
    read_chat_owner_request,
)
from eom_protocol.general_chat_views import (
    GeneralChatConversation,
    GeneralChatCreate,
    GeneralChatList,
    GeneralChatSlot,
    GeneralChatSubmission,
)
from jsonschema import ValidationError as SchemaError
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[2]
ACTOR = "operator_" + "1" * 32
CONVERSATION = "chat_" + "2" * 32
NOW = datetime(2026, 10, 7, tzinfo=UTC)
INTENT = "chat-owner-intent-001"


class RecordingOwner:
    def __init__(self):
        self.calls = []
        self.lock = Lock()
        self.error = None

    def _record(self, action, actor=None, **values):
        with self.lock:
            self.calls.append((action, actor, values))
        if self.error:
            raise ChatError(self.error)

    def slot(self):
        self._record("SLOT")
        return GeneralChatSlot(state="READY")

    def conversations(self, *, actor_id, cursor):
        self._record("LIST", actor_id, cursor=cursor)
        return GeneralChatList(values=())

    def create(self, *, actor_id, request, idempotency_key):
        self._record("CREATE", actor_id, request=request, idempotency_key=idempotency_key)
        return self._conversation()

    def conversation(self, *, actor_id, conversation_id, cursor):
        self._record("READ", actor_id, conversation_id=conversation_id, cursor=cursor)
        return self._conversation()

    def submit(self, *, actor_id, conversation_id, request, idempotency_key):
        self._record(
            "SUBMIT",
            actor_id,
            conversation_id=conversation_id,
            request=request,
            idempotency_key=idempotency_key,
        )
        return self._conversation()

    def delete(self, *, actor_id, conversation_id, request, idempotency_key):
        self._record(
            "DELETE",
            actor_id,
            conversation_id=conversation_id,
            request=request,
            idempotency_key=idempotency_key,
        )
        return GeneralChatDeletion(
            conversation_id=conversation_id, resource_version=2, deleted_at=NOW
        )

    @staticmethod
    def _conversation():
        return GeneralChatConversation(
            conversation_id=CONVERSATION, title="대화", resource_version=1, updated_at=NOW
        )


@pytest.fixture
def rpc(tmp_path):
    root = tmp_path / "rpc"
    root.mkdir(mode=0o750)
    endpoint = ChatSocketEndpoint(root / "owner.sock", os.getuid(), os.getgid())
    owner = RecordingOwner()
    server = GeneralChatOwnerRpcServer(
        owner, endpoint=endpoint, allowed_uids=frozenset({os.getuid()})
    )
    thread = Thread(target=server.serve)
    thread.start()
    try:
        yield owner, server, GeneralChatOwnerClient(endpoint), endpoint
    finally:
        server.stop()
        thread.join(timeout=5)
        server.close()
        assert not thread.is_alive() and not endpoint.path.exists()


def test_real_socket_routes_typed_queries_commands_to_owner_without_changing_actor_or_intent(rpc):
    owner, _, client, _ = rpc
    assert client.slot().state == "READY"
    assert client.conversations(actor_id=ACTOR, cursor=None).values == ()
    assert (
        client.create(
            actor_id=ACTOR, request=GeneralChatCreate(title="새 대화"), idempotency_key=INTENT
        ).conversation_id
        == CONVERSATION
    )
    assert (
        client.conversation(
            actor_id=ACTOR, conversation_id=CONVERSATION, cursor=None
        ).conversation_id
        == CONVERSATION
    )
    assert (
        client.submit(
            actor_id=ACTOR,
            conversation_id=CONVERSATION,
            request=GeneralChatSubmission(text="질문", expected_version=1),
            idempotency_key=INTENT,
        ).conversation_id
        == CONVERSATION
    )
    assert [call[0] for call in owner.calls] == ["SLOT", "LIST", "CREATE", "READ", "SUBMIT"]
    assert {call[1] for call in owner.calls[1:]} == {ACTOR}
    assert owner.calls[-1][2]["idempotency_key"] == INTENT
    assert owner.calls[-1][2]["request"].text == "질문"


def test_multiple_api_requests_are_safe_and_bounded_without_new_mutation_replay(rpc):
    owner, _, client, _ = rpc
    with ThreadPoolExecutor(max_workers=4) as pool:
        responses = tuple(
            pool.map(lambda _: client.conversations(actor_id=ACTOR, cursor=None), range(20))
        )
    assert len(responses) == len(owner.calls) == 20
    assert all(call[0] == "LIST" for call in owner.calls)


def test_delete_uses_v5_schema_and_preserves_actor_intent_over_real_owner_socket(rpc):
    owner, _, client, _ = rpc
    command = ChatDeleteCommand(
        actor_id=ACTOR,
        conversation_id=CONVERSATION,
        request=GeneralChatDelete(expected_version=1),
        idempotency_key=INTENT,
    )
    envelope = ChatOwnerRequest(
        schema_version="general-chat-owner-request/5.0",
        request_id="chatrpc_" + "3" * 32,
        command=command,
    )
    assert read_chat_owner_request(envelope.model_dump(mode="json")) == envelope
    receipt = client.delete(
        actor_id=ACTOR,
        conversation_id=CONVERSATION,
        request=command.request,
        idempotency_key=INTENT,
    )
    assert receipt.conversation_id == CONVERSATION and receipt.resource_version == 2
    assert owner.calls == [
        (
            "DELETE",
            ACTOR,
            {
                "conversation_id": CONVERSATION,
                "request": command.request,
                "idempotency_key": INTENT,
            },
        )
    ]


def test_delete_successor_does_not_reinterpret_released_owner_requests():
    request = ChatOwnerRequest(
        schema_version="general-chat-owner-request/5.0",
        request_id="chatrpc_" + "3" * 32,
        command=ChatDeleteCommand(
            actor_id=ACTOR,
            conversation_id=CONVERSATION,
            request=GeneralChatDelete(expected_version=1),
            idempotency_key=INTENT,
        ),
    )
    document = request.model_dump(mode="json")
    assert read_chat_owner_request(document) == request
    for old_version in (
        "general-chat-owner-request/1.0",
        "general-chat-owner-request/2.0",
        "general-chat-owner-request/4.0",
    ):
        with pytest.raises((ValueError, SchemaError)):
            read_chat_owner_request({**document, "schema_version": old_version})
    with pytest.raises((ValueError, SchemaError)):
        read_chat_owner_request(
            {
                **document,
                "command": ChatCreateCommand(
                    actor_id=ACTOR,
                    request=GeneralChatCreate(title="대화"),
                    idempotency_key=INTENT,
                ).model_dump(mode="json"),
            }
        )


@pytest.mark.parametrize("code", list(ChatOwnerErrorCode))
def test_stable_business_failure_is_propagated_without_partial_value_or_auto_retry(rpc, code):
    owner, _, client, _ = rpc
    owner.error = code.value
    with pytest.raises(ChatOwnerFault) as failure:
        client.conversations(actor_id=ACTOR, cursor=None)
    assert failure.value.code == code
    assert len(owner.calls) == 1


def test_unknown_owner_failure_is_sanitized(rpc):
    owner, _, client, _ = rpc
    owner.error = "private-native-output-and-path"
    with pytest.raises(ChatOwnerFault) as failure:
        client.slot()
    assert failure.value.code == ChatOwnerErrorCode.UNAVAILABLE
    assert "private" not in str(failure.value)


def test_untrusted_peer_is_denied_before_any_owner_call(rpc):
    owner, server, client, _ = rpc
    server.allowed_uids = frozenset({os.getuid() + 1})
    with pytest.raises(ChatOwnerFault):
        client.slot()
    assert not owner.calls


def test_connected_peer_is_verified_not_just_filesystem_metadata(rpc, monkeypatch):
    owner, _, client, _ = rpc
    monkeypatch.setattr(
        "eom_orchestrator.general_chat_socket.chat_peer_uid", lambda _: os.getuid() + 1
    )
    with pytest.raises(ChatOwnerFault, match="GENERAL_CHAT_PROTOCOL_INVALID"):
        client.slot()
    assert not owner.calls


def test_socket_and_parent_modes_or_symlinks_are_not_silently_followed(rpc):
    owner, _, client, endpoint = rpc
    endpoint.path.chmod(0o666)
    try:
        with pytest.raises(ChatOwnerFault, match="GENERAL_CHAT_PROTOCOL_INVALID"):
            client.slot()
    finally:
        endpoint.path.chmod(0o660)
    endpoint.path.parent.chmod(0o770)
    try:
        with pytest.raises(ChatOwnerFault, match="GENERAL_CHAT_PROTOCOL_INVALID"):
            client.slot()
    finally:
        endpoint.path.parent.chmod(0o750)
    link = endpoint.path.parent / "alias.sock"
    link.symlink_to(endpoint.path)
    with pytest.raises(ChatOwnerFault, match="GENERAL_CHAT_PROTOCOL_INVALID"):
        GeneralChatOwnerClient(ChatSocketEndpoint(link, os.getuid(), os.getgid())).slot()
    assert not owner.calls


def test_stale_endpoint_is_never_overwritten(rpc):
    _, _, _, endpoint = rpc
    before = endpoint.path.stat()
    with pytest.raises(ChatTransportError):
        bind_chat_listener(endpoint, backlog=1)
    assert endpoint.path.stat().st_ino == before.st_ino


def test_missing_optional_service_returns_explicit_fault_without_import_startup_failure(tmp_path):
    endpoint = ChatSocketEndpoint(tmp_path / "missing/owner.sock", os.getuid(), os.getgid())
    client = GeneralChatOwnerClient(endpoint)
    with pytest.raises(ChatOwnerFault, match="GENERAL_CHAT_APPLICATION_UNAVAILABLE"):
        client.slot()


def test_frozen_wire_models_use_canonical_view_schema_offline_and_identical_packaged_bytes():
    command = ChatCreateCommand(
        actor_id=ACTOR, request=GeneralChatCreate(title="대화"), idempotency_key=INTENT
    )
    request = ChatOwnerRequest(request_id="chatrpc_" + "3" * 32, command=command)
    assert read_chat_owner_request(request.model_dump(mode="json")) == request
    reply = ChatOwnerReply(
        request_id=request.request_id,
        action="CREATE",
        status="SUCCEEDED",
        value=RecordingOwner._conversation(),
        error_code=None,
    )
    assert read_chat_owner_reply(reply.model_dump(mode="json"), request=request) == reply
    with pytest.raises(ValidationError):
        request.request_id = "chatrpc_" + "4" * 32
    for name in ("request", "reply"):
        path = f"general-chat-owner-{name}.schema.json"
        assert (ROOT / "schemas/general-chat" / path).read_bytes() == (
            ROOT / "packages/protocol/eom_protocol/schemas" / path
        ).read_bytes()
    assert (ROOT / "schemas/api/v1/general-chat-v1.schema.json").read_bytes() == (
        ROOT / "packages/protocol/eom_protocol/schemas/general-chat-views.schema.json"
    ).read_bytes()


@pytest.mark.parametrize(
    "patch",
    [
        {"request_id": "bad"},
        {"schema_version": "future"},
        {"owner_id": ACTOR},
        {"command": {"action": "SLOT", "actor_id": ACTOR}},
        {"command": {"action": "EXECUTE", "native_thread_id": "caller-thread"}},
        {
            "command": {
                "action": "READ",
                "actor_id": ACTOR,
                "conversation_id": CONVERSATION,
                "cursor": "x" * 1025,
            }
        },
    ],
)
def test_owner_input_does_not_accept_native_or_storage_or_unknown_shape(patch):
    document = ChatOwnerRequest(
        request_id="chatrpc_" + "3" * 32, command=ChatSlotQuery()
    ).model_dump(mode="json")
    document.update(patch)
    with pytest.raises((ValueError, SchemaError)):
        read_chat_owner_request(document)


@pytest.mark.parametrize(
    "patch",
    [
        {"request_id": "chatrpc_" + "4" * 32},
        {"action": "LIST"},
        {"value": None},
        {"value": GeneralChatList(values=()).model_dump(mode="json")},
        {"status": "FAILED", "error_code": "GENERAL_CHAT_NOT_READY"},
        {"error_code": "GENERAL_CHAT_NOT_READY"},
        {"raw_error": "secret-not-allowed"},
    ],
)
def test_reply_exact_request_action_and_truthful_projection_required(patch):
    request = ChatOwnerRequest(request_id="chatrpc_" + "3" * 32, command=ChatSlotQuery())
    document = ChatOwnerReply(
        request_id=request.request_id,
        action="SLOT",
        status="SUCCEEDED",
        value=GeneralChatSlot(state="READY"),
        error_code=None,
    ).model_dump(mode="json")
    document.update(patch)
    with pytest.raises((ValueError, SchemaError)):
        read_chat_owner_reply(document, request=request)


@pytest.mark.parametrize(
    "payload",
    [
        b'{"key":1,"key":2}',
        b'{"a":NaN}',
        b'{"a":1e999}',
        b"[]",
        b"bad",
        b"\xff",
        b"[" * 1500 + b"]" * 1500,
    ],
)
def test_malformed_duplicate_nonfinite_or_deep_json_is_stable_error(payload):
    with pytest.raises(ChatTransportError, match="GENERAL_CHAT_TRANSPORT_INVALID"):
        decode_chat_frame(payload)


@pytest.mark.parametrize("frame", [b"{}", b"{}\n{}\n", b"\n", b"x" * 100 + b"\n"])
def test_truncated_empty_multiple_or_oversized_frames_are_rejected(frame):
    a, b = socket.socketpair()
    with a, b:
        a.sendall(frame)
        a.shutdown(socket.SHUT_WR)
        with pytest.raises(ChatTransportError):
            payload = receive_chat_frame(b, limit=100, deadline=monotonic() + 2)
            decode_chat_frame(payload)


def test_deadline_is_bounded_and_no_retry_is_invented():
    a, b = socket.socketpair()
    with a, b, pytest.raises(ChatTransportError, match="UNAVAILABLE"):
        receive_chat_frame(b, limit=100, deadline=monotonic())


def test_invalid_request_never_reaches_owner(rpc):
    owner, _, _, endpoint = rpc
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.connect(str(endpoint.path))
        send_chat_frame(
            connection, b'{"command":"bad"}', limit=OWNER_REQUEST_LIMIT, deadline=monotonic() + 2
        )
        assert connection.recv(1) == b""
    assert not owner.calls


def test_real_client_rejects_mismatched_reply_identity_before_returning_data(tmp_path):
    root = tmp_path / "bad-server"
    root.mkdir(mode=0o750)
    endpoint = ChatSocketEndpoint(root / "owner.sock", os.getuid(), os.getgid())
    listener = bind_chat_listener(endpoint, backlog=1)
    stopped = Event()

    def bad_server():
        try:
            connection, _ = listener.accept()
            with connection:
                payload = receive_chat_frame(
                    connection, limit=OWNER_REQUEST_LIMIT, deadline=monotonic() + 5
                )
                request = read_chat_owner_request(decode_chat_frame(payload))
                reply = ChatOwnerReply(
                    request_id="chatrpc_" + "f" * 32,
                    action=request.command.action,
                    status="SUCCEEDED",
                    value=GeneralChatSlot(state="READY"),
                    error_code=None,
                )
                send_chat_frame(
                    connection,
                    canonical_json_bytes(reply.model_dump(mode="json")),
                    limit=OWNER_REPLY_LIMIT,
                    deadline=monotonic() + 5,
                )
        finally:
            stopped.set()

    thread = Thread(target=bad_server)
    thread.start()
    try:
        with pytest.raises(ChatOwnerFault, match="GENERAL_CHAT_PROTOCOL_INVALID"):
            GeneralChatOwnerClient(endpoint).slot()
        assert stopped.wait(5)
    finally:
        listener.close()
        thread.join(5)
        endpoint.path.unlink()


def test_protocol_request_and_reply_schemas_are_2020_12_and_forbid_unknown_fields():
    for kind in ("request", "reply"):
        document = json.loads(
            (ROOT / "schemas/general-chat" / f"general-chat-owner-{kind}.schema.json").read_bytes()
        )
        assert document["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        assert document["additionalProperties"] is False
