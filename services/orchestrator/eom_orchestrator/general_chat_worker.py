"""One staged turn per claim, invoked only through the Orchestrator worker port."""

from __future__ import annotations

import re
from threading import Lock
from typing import Protocol

from eom_protocol.general_chat import ChatTurnInput, ChatTurnResult, read_chat_turn_result
from eom_protocol.general_chat_worker_messages import (
    ChatWorkerAdmission,
    ChatWorkerError,
    ChatWorkerExecute,
    ChatWorkerFault,
    ChatWorkerLookup,
    ChatWorkerOutput,
    ChatWorkerPolicy,
    ChatWorkerProbe,
    ChatWorkerReply,
    ChatWorkerRequest,
    ChatWorkerTicket,
    chat_worker_ticket,
    read_chat_worker_policy,
    read_chat_worker_reply,
    read_chat_worker_request,
)


class ChatHandoffPort(Protocol):
    def lookup(self, ticket: ChatWorkerTicket) -> ChatWorkerOutput: ...
    def reserve(self, ticket: ChatWorkerTicket) -> bool: ...
    def publish(self, ticket: ChatWorkerTicket, result: ChatTurnResult) -> None: ...


class ChatAdmittedNativePort(Protocol):
    def require_admission(self, policy: ChatWorkerPolicy) -> None: ...
    def answer(self, request: ChatTurnInput) -> ChatTurnResult: ...


class ChatWorkerApplication:
    def __init__(
        self,
        native: ChatAdmittedNativePort,
        handoff: ChatHandoffPort,
        *,
        policy: ChatWorkerPolicy,
        boot_id: str,
    ) -> None:
        if re.fullmatch(r"chatboot_[0-9a-f]{32}", boot_id) is None:
            raise ValueError("invalid isolated-worker boot identity")
        self.policy = read_chat_worker_policy(policy.model_dump(mode="json"))
        self.boot_id = boot_id
        self.native = native
        self.handoff = handoff
        self._execution_lock = Lock()

    def handle(self, request: ChatWorkerRequest) -> ChatWorkerReply:
        request = read_chat_worker_request(request.model_dump(mode="json"))
        try:
            historical_lookup = isinstance(request.command, ChatWorkerLookup)
            if not historical_lookup and request.policy_sha256 != self.policy.sha256:
                raise ChatWorkerFault(ChatWorkerError.NOT_READY)
            value = self._handle(request)
            reply = ChatWorkerReply(
                request_id=request.request_id,
                boot_id=self.boot_id,
                policy_sha256=request.policy_sha256 if historical_lookup else self.policy.sha256,
                action=request.command.action,
                status="SUCCEEDED",
                value=value,
                error_code=None,
            )
        except ChatWorkerFault as error:
            reply = self.failure(request, error.code)
        except Exception:
            # An uncertain exception is not proof the model failed or did not run.
            reply = self.failure(request, ChatWorkerError.RECOVERY)
        return read_chat_worker_reply(reply.model_dump(mode="json"), request=request)

    def failure(self, request: ChatWorkerRequest, code: ChatWorkerError) -> ChatWorkerReply:
        return ChatWorkerReply(
            request_id=request.request_id,
            boot_id=self.boot_id,
            policy_sha256=self.policy.sha256,
            action=request.command.action,
            status="FAILED",
            value=None,
            error_code=code,
        )

    def _handle(self, request: ChatWorkerRequest) -> ChatWorkerAdmission | ChatWorkerOutput:
        command = request.command
        if isinstance(command, ChatWorkerProbe):
            try:
                self.native.require_admission(self.policy)
            except Exception:
                return ChatWorkerAdmission(ready=False)
            return ChatWorkerAdmission(ready=True)
        if isinstance(command, ChatWorkerLookup):
            # Completed output can be recovered even when native auth is unavailable;
            # this path never enrolls, starts/restarts native processes or generates.
            return self.handoff.lookup(command.ticket)
        assert isinstance(command, ChatWorkerExecute)
        if command.boot_id != self.boot_id:
            raise ChatWorkerFault(ChatWorkerError.NOT_READY)
        ticket = chat_worker_ticket(command.turn, policy_sha256=self.policy.sha256)
        existing = self.handoff.lookup(ticket)
        if existing.state == "KNOWN":
            return existing
        if existing.state == "UNKNOWN":
            raise ChatWorkerFault(ChatWorkerError.RECOVERY)
        if not self._execution_lock.acquire(blocking=False):
            raise ChatWorkerFault(ChatWorkerError.BUSY)
        try:
            self.native.require_admission(self.policy)
            if not self.handoff.reserve(ticket):
                existing = self.handoff.lookup(ticket)
                if existing.state == "KNOWN":
                    return existing
                raise ChatWorkerFault(ChatWorkerError.RECOVERY)
            result = read_chat_turn_result(
                self.native.answer(command.turn).model_dump(mode="json"), request=command.turn
            )
            self.handoff.publish(ticket, result)
            return ChatWorkerOutput(state="KNOWN", result=result)
        finally:
            self._execution_lock.release()
