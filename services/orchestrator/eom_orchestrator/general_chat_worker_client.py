"""Trusted owner worker port; bounded dispatch, no automatic inference replay."""

from __future__ import annotations

import socket
from collections.abc import Callable
from threading import Lock
from time import monotonic
from uuid import uuid4

from eom_protocol.general_chat_dispatch import ChatExecutionIdentity
from eom_protocol.general_chat_grounding import read_agent
from eom_protocol.general_chat_rag_knowledge import read_rag
from eom_protocol.general_chat_rag_tools import ChatToolRequestV2
from eom_protocol.general_chat_rag_turn import RagChatTurnInput
from eom_protocol.general_chat_tools import ChatToolRequest
from eom_protocol.general_chat_turn_contracts import ChatInputContract as ChatTurnInput
from eom_protocol.general_chat_turn_contracts import ChatResultContract as ChatTurnResult
from eom_protocol.general_chat_worker_messages import (
    ChatWorkerAdmission,
    ChatWorkerCommand,
    ChatWorkerError,
    ChatWorkerExecute,
    ChatWorkerLookup,
    ChatWorkerOutput,
    ChatWorkerPolicy,
    ChatWorkerProbe,
    ChatWorkerReply,
    ChatWorkerRequest,
    ChatWorkerTicket,
    chat_worker_protocol_version,
    read_chat_worker_policy,
    read_chat_worker_reply,
    read_chat_worker_request,
)
from jsonschema import ValidationError as SchemaError

from eom_orchestrator.general_chat_rag_broker import ChatRagToolBroker
from eom_orchestrator.general_chat_socket import (
    WORKER_EXECUTE_TIMEOUT,
    WORKER_FRAME_LIMIT,
    WORKER_PROBE_TIMEOUT,
    ChatSocketEndpoint,
    ChatTransportError,
    chat_peer_uid,
    exchange_chat_frame,
    receive_chat_stream,
    send_chat_stream,
)
from eom_orchestrator.general_chat_state import ChatError
from eom_orchestrator.general_chat_tool_broker import ChatToolBroker


class ChatWorkerClient:
    def __init__(
        self,
        *,
        endpoint: ChatSocketEndpoint,
        policy: ChatWorkerPolicy,
        tools: Callable[[ChatWorkerRequest], ChatToolBroker | ChatRagToolBroker] | None = None,
    ) -> None:
        self.endpoint = endpoint
        self.policy = read_chat_worker_policy(policy.model_dump(mode="json"))
        self._boot_id: str | None = None
        self._admission_lock = Lock()
        self.tools = tools

    def _stream(self, request: ChatWorkerRequest) -> dict[str, object]:
        self.endpoint.require_socket()
        timeout = (
            WORKER_EXECUTE_TIMEOUT
            if isinstance(request.command, ChatWorkerExecute)
            else WORKER_PROBE_TIMEOUT
        )
        deadline = monotonic() + timeout
        broker = (
            self.tools(request)
            if isinstance(request.command, ChatWorkerExecute) and self.tools is not None
            else None
        )
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
                connection.settimeout(timeout)
                connection.connect(str(self.endpoint.path))
                if chat_peer_uid(connection) != self.endpoint.owner_uid:
                    raise ChatTransportError("INVALID")
                send_chat_stream(connection, request.model_dump(mode="json"), deadline=deadline)
                rag = isinstance(request.command, ChatWorkerExecute) and isinstance(
                    request.command.turn, RagChatTurnInput
                )
                for _ in range(8 if rag else 6):
                    document = receive_chat_stream(connection, deadline=deadline)
                    if document.get("schema_version") == "general-chat-tool-request/2.0":
                        if not rag or not isinstance(broker, ChatRagToolBroker):
                            raise ChatTransportError("INVALID")
                        intent_v2 = read_rag("Request", document, ChatToolRequestV2)
                        reply_v2 = broker.execute(intent_v2)
                        send_chat_stream(
                            connection, reply_v2.model_dump(mode="json"), deadline=deadline
                        )
                        continue
                    if document.get("schema_version") != "general-chat-tool-request/1.0":
                        return document
                    if rag or not isinstance(broker, ChatToolBroker):
                        raise ChatTransportError("INVALID")
                    intent = read_agent("Request", document, ChatToolRequest)
                    reply = broker.execute(intent)
                    send_chat_stream(connection, reply.model_dump(mode="json"), deadline=deadline)
                raise ChatTransportError("INVALID")
        except OSError:
            raise ChatTransportError("UNAVAILABLE") from None

    def _call(self, command: ChatWorkerCommand) -> ChatWorkerReply:
        protocol = chat_worker_protocol_version(self.policy)
        request = ChatWorkerRequest(
            schema_version="general-chat-worker-request/4.0"
            if protocol == 4
            else "general-chat-worker-request/3.0"
            if protocol == 3
            else "general-chat-worker-request/2.0"
            if protocol == 2
            else "general-chat-worker-request/1.0",
            request_id="chatwrpc_" + uuid4().hex,
            policy_sha256=command.ticket.policy_sha256
            if isinstance(command, ChatWorkerLookup)
            else self.policy.sha256,
            command=command,
        )
        document = request.model_dump(mode="json")
        read_chat_worker_request(document)
        try:
            reply_document = (
                self._stream(request)
                if request.schema_version.endswith(("/3.0", "/4.0"))
                else exchange_chat_frame(
                    self.endpoint,
                    document,
                    request_limit=WORKER_FRAME_LIMIT,
                    reply_limit=WORKER_FRAME_LIMIT,
                    timeout=WORKER_EXECUTE_TIMEOUT
                    if isinstance(command, ChatWorkerExecute)
                    else WORKER_PROBE_TIMEOUT,
                )
            )
            reply = read_chat_worker_reply(reply_document, request=request)
        except (ChatTransportError, ValueError, SchemaError):
            # A transport failure is not proof that EXECUTE did not happen.
            code = (
                ChatWorkerError.RECOVERY
                if isinstance(command, ChatWorkerExecute)
                else ChatWorkerError.NOT_READY
            )
            raise ChatError(code.value) from None
        if reply.status == "FAILED":
            assert reply.error_code is not None
            raise ChatError(reply.error_code.value)
        return reply

    def check_admission(self) -> None:
        reply = self._call(ChatWorkerProbe())
        assert isinstance(reply.value, ChatWorkerAdmission)
        if not reply.value.ready:
            raise ChatError(ChatWorkerError.NOT_READY.value)
        with self._admission_lock:
            if self._boot_id is not None and self._boot_id != reply.boot_id:
                raise ChatError(ChatWorkerError.NOT_READY.value)
            self._boot_id = reply.boot_id

    @property
    def execution_identity(self) -> ChatExecutionIdentity:
        """Already-admitted immutable identity; no probe or implicit reboot adoption."""
        with self._admission_lock:
            if self._boot_id is None:
                raise ChatError(ChatWorkerError.NOT_READY.value)
            return ChatExecutionIdentity(boot_id=self._boot_id, policy=self.policy)

    def answer(self, request: ChatTurnInput) -> ChatTurnResult:
        with self._admission_lock:
            boot_id = self._boot_id
        if boot_id is None:
            raise ChatError(ChatWorkerError.NOT_READY.value)
        reply = self._call(ChatWorkerExecute(boot_id=boot_id, turn=request))
        assert isinstance(reply.value, ChatWorkerOutput) and reply.value.result is not None
        return reply.value.result

    def lookup(self, ticket: ChatWorkerTicket) -> ChatWorkerOutput:
        reply = self._call(ChatWorkerLookup(ticket=ticket))
        assert isinstance(reply.value, ChatWorkerOutput)
        return reply.value
