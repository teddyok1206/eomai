"""Private isolated-worker handoff; no native handles, auth or storage locations."""

from __future__ import annotations

import json
from enum import StrEnum
from functools import lru_cache
from importlib.resources import files
from typing import Annotated, Literal

from eom_identifiers import canonical_json_bytes, sha256_bytes
from jsonschema import Draft202012Validator
from pydantic import Field, model_validator
from referencing import Registry, Resource

from eom_protocol.general_chat import (
    ChatBoundaryValue,
    ChatTurnInput,
    ChatTurnResult,
    read_chat_turn_input,
    read_chat_turn_result,
)

WorkerBootId = Annotated[str, Field(pattern=r"^chatboot_[0-9a-f]{32}$")]
WorkerHash = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
WorkerAction = Literal["PROBE", "EXECUTE", "RESULT"]


class ChatWorkerError(StrEnum):
    NOT_READY = "GENERAL_CHAT_WORKER_NOT_READY"
    BUSY = "GENERAL_CHAT_WORKER_BUSY"
    INVALID = "GENERAL_CHAT_WORKER_PROTOCOL_INVALID"
    RECOVERY = "GENERAL_CHAT_RECONCILIATION_REQUIRED"


class ChatWorkerFault(RuntimeError):
    def __init__(self, code: ChatWorkerError) -> None:
        self.code = code
        super().__init__(code.value)


class ChatWorkerPolicy(ChatBoundaryValue):
    schema_version: Literal["general-chat-worker-policy/1.0"] = "general-chat-worker-policy/1.0"
    model: str = Field(min_length=1, max_length=128, pattern=r"^[a-zA-Z0-9._-]+$")
    native_profile: Literal["codex-app-server/0.160.0/environment-free/1.0"]
    prompt_revision: Literal["general-chat/1.0.0"] = "general-chat/1.0.0"
    prompt_sha256: WorkerHash

    @property
    def sha256(self) -> str:
        return sha256_bytes(canonical_json_bytes(self.model_dump(mode="json")))


class ChatWorkerTicket(ChatBoundaryValue):
    schema_version: Literal["general-chat-worker-ticket/1.0"] = "general-chat-worker-ticket/1.0"
    conversation_id: str = Field(pattern=r"^chat_[0-9a-f]{32}$")
    turn_id: str = Field(pattern=r"^chatturn_[0-9a-f]{32}$")
    claim_id: str = Field(pattern=r"^chatclaim_[0-9a-f]{32}$")
    request_sha256: WorkerHash
    policy_sha256: WorkerHash


def chat_worker_ticket(turn: ChatTurnInput, *, policy_sha256: str) -> ChatWorkerTicket:
    read_chat_turn_input(turn.model_dump(mode="json"))
    return ChatWorkerTicket(
        conversation_id=turn.conversation_id,
        turn_id=turn.turn_id,
        claim_id=turn.claim_id,
        request_sha256=sha256_bytes(canonical_json_bytes(turn.model_dump(mode="json"))),
        policy_sha256=policy_sha256,
    )


class ChatWorkerProbe(ChatBoundaryValue):
    action: Literal["PROBE"] = "PROBE"


class ChatWorkerExecute(ChatBoundaryValue):
    action: Literal["EXECUTE"] = "EXECUTE"
    boot_id: WorkerBootId
    turn: ChatTurnInput


class ChatWorkerLookup(ChatBoundaryValue):
    action: Literal["RESULT"] = "RESULT"
    ticket: ChatWorkerTicket


ChatWorkerCommand = Annotated[
    ChatWorkerProbe | ChatWorkerExecute | ChatWorkerLookup, Field(discriminator="action")
]


class ChatWorkerRequest(ChatBoundaryValue):
    schema_version: Literal["general-chat-worker-request/1.0"] = "general-chat-worker-request/1.0"
    request_id: str = Field(pattern=r"^chatwrpc_[0-9a-f]{32}$")
    policy_sha256: WorkerHash
    command: ChatWorkerCommand

    @model_validator(mode="after")
    def pinned_ticket_policy(self) -> ChatWorkerRequest:
        if (
            isinstance(self.command, ChatWorkerLookup)
            and self.command.ticket.policy_sha256 != self.policy_sha256
        ):
            raise ValueError("worker lookup policy mismatch")
        return self


class ChatWorkerAdmission(ChatBoundaryValue):
    ready: bool


class ChatWorkerOutput(ChatBoundaryValue):
    state: Literal["KNOWN", "UNKNOWN", "ABSENT"]
    result: ChatTurnResult | None

    @model_validator(mode="after")
    def known_result_only(self) -> ChatWorkerOutput:
        if (self.state == "KNOWN") != (self.result is not None):
            raise ValueError("worker output state and result differ")
        return self


class ChatWorkerReply(ChatBoundaryValue):
    schema_version: Literal["general-chat-worker-reply/1.0"] = "general-chat-worker-reply/1.0"
    request_id: str = Field(pattern=r"^chatwrpc_[0-9a-f]{32}$")
    boot_id: WorkerBootId
    policy_sha256: WorkerHash
    action: WorkerAction
    status: Literal["SUCCEEDED", "FAILED"]
    value: ChatWorkerAdmission | ChatWorkerOutput | None
    error_code: ChatWorkerError | None

    @model_validator(mode="after")
    def typed_truthful_reply(self) -> ChatWorkerReply:
        if self.status == "FAILED":
            if self.value is not None or self.error_code is None:
                raise ValueError("failed worker reply requires only a stable error")
        else:
            expected = ChatWorkerAdmission if self.action == "PROBE" else ChatWorkerOutput
            if self.error_code is not None or not isinstance(self.value, expected):
                raise ValueError("worker reply action and value differ")
            if (
                self.action == "EXECUTE"
                and isinstance(self.value, ChatWorkerOutput)
                and self.value.state != "KNOWN"
            ):
                raise ValueError("execute success requires a known exact result")
        return self


@lru_cache(maxsize=4)
def _worker_validator(
    kind: Literal["request", "reply", "ticket", "policy"],
) -> Draft202012Validator:
    resources = files("eom_protocol").joinpath("schemas")
    registry: Registry = Registry()
    for leaf in (
        "general-chat-turn-input.schema.json",
        "general-chat-turn-result.schema.json",
        "general-chat-worker-ticket.schema.json",
    ):
        dependency = json.loads(resources.joinpath(leaf).read_bytes())
        registry = registry.with_resource(dependency["$id"], Resource.from_contents(dependency))
    schema = json.loads(resources.joinpath(f"general-chat-worker-{kind}.schema.json").read_bytes())
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, registry=registry)


def read_chat_worker_policy(document: object) -> ChatWorkerPolicy:
    _worker_validator("policy").validate(document)
    return ChatWorkerPolicy.model_validate(document)


def read_chat_worker_ticket(document: object) -> ChatWorkerTicket:
    _worker_validator("ticket").validate(document)
    return ChatWorkerTicket.model_validate(document)


def read_chat_worker_request(document: object) -> ChatWorkerRequest:
    _worker_validator("request").validate(document)
    request = ChatWorkerRequest.model_validate(document)
    if isinstance(request.command, ChatWorkerExecute):
        read_chat_turn_input(request.command.turn.model_dump(mode="json"))
    return request


def require_chat_ticket_result(ticket: ChatWorkerTicket, result: ChatTurnResult) -> None:
    if (result.conversation_id, result.turn_id, result.claim_id, result.request_sha256) != (
        ticket.conversation_id,
        ticket.turn_id,
        ticket.claim_id,
        ticket.request_sha256,
    ):
        raise ValueError("worker result does not match exact ticket")


def read_chat_worker_reply(document: object, *, request: ChatWorkerRequest) -> ChatWorkerReply:
    _worker_validator("reply").validate(document)
    reply = ChatWorkerReply.model_validate(document)
    if (reply.request_id, reply.action) != (request.request_id, request.command.action):
        raise ValueError("worker reply identity/action mismatch")
    if reply.status == "SUCCEEDED":
        if reply.policy_sha256 != request.policy_sha256:
            raise ValueError("worker reply policy mismatch")
        command = request.command
        if isinstance(command, ChatWorkerExecute) and reply.boot_id != command.boot_id:
            raise ValueError("worker boot changed during execution")
        if isinstance(reply.value, ChatWorkerOutput) and reply.value.result is not None:
            if isinstance(command, ChatWorkerExecute):
                read_chat_turn_result(
                    reply.value.result.model_dump(mode="json"), request=command.turn
                )
            elif isinstance(command, ChatWorkerLookup):
                require_chat_ticket_result(command.ticket, reply.value.result)
    return reply
