"""Trusted owner worker port; bounded dispatch, no automatic inference replay."""

from __future__ import annotations

from threading import Lock
from uuid import uuid4

from eom_protocol.general_chat import ChatTurnInput, ChatTurnResult
from eom_protocol.general_chat_dispatch import ChatExecutionIdentity
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
    read_chat_worker_policy,
    read_chat_worker_reply,
    read_chat_worker_request,
)
from jsonschema import ValidationError as SchemaError

from eom_orchestrator.general_chat_socket import (
    WORKER_EXECUTE_TIMEOUT,
    WORKER_FRAME_LIMIT,
    WORKER_PROBE_TIMEOUT,
    ChatSocketEndpoint,
    ChatTransportError,
    exchange_chat_frame,
)
from eom_orchestrator.general_chat_state import ChatError


class ChatWorkerClient:
    def __init__(self, *, endpoint: ChatSocketEndpoint, policy: ChatWorkerPolicy) -> None:
        self.endpoint = endpoint
        self.policy = read_chat_worker_policy(policy.model_dump(mode="json"))
        self._boot_id: str | None = None
        self._admission_lock = Lock()

    def _call(self, command: ChatWorkerCommand) -> ChatWorkerReply:
        request = ChatWorkerRequest(
            request_id="chatwrpc_" + uuid4().hex,
            policy_sha256=command.ticket.policy_sha256
            if isinstance(command, ChatWorkerLookup)
            else self.policy.sha256,
            command=command,
        )
        document = request.model_dump(mode="json")
        read_chat_worker_request(document)
        try:
            reply_document = exchange_chat_frame(
                self.endpoint,
                document,
                request_limit=WORKER_FRAME_LIMIT,
                reply_limit=WORKER_FRAME_LIMIT,
                timeout=WORKER_EXECUTE_TIMEOUT
                if isinstance(command, ChatWorkerExecute)
                else WORKER_PROBE_TIMEOUT,
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
