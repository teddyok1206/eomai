"""Private typed API-to-Orchestrator messages; no storage or native worker handles."""

from __future__ import annotations

import json
from enum import StrEnum
from functools import lru_cache
from importlib.resources import files
from typing import Annotated, Literal, Protocol

from jsonschema import Draft202012Validator
from pydantic import Field, model_validator
from referencing import Registry, Resource

from eom_protocol.general_chat import ChatBoundaryValue
from eom_protocol.general_chat_views import (
    GeneralChatConversation,
    GeneralChatCreate,
    GeneralChatList,
    GeneralChatSlot,
    GeneralChatSubmission,
)

OwnerAction = Literal["SLOT", "LIST", "CREATE", "READ", "SUBMIT"]
ActorId = Annotated[str, Field(pattern=r"^operator_[0-9a-f]{32}$")]
ConversationId = Annotated[str, Field(pattern=r"^chat_[0-9a-f]{32}$")]
IntentKey = Annotated[str, Field(pattern=r"^[!-~]{16,128}$")]
Cursor = Annotated[str, Field(min_length=1, max_length=1024)]


class ChatOwnerErrorCode(StrEnum):
    NOT_READY = "GENERAL_CHAT_NOT_READY"
    FORBIDDEN = "GENERAL_CHAT_FORBIDDEN"
    NOT_FOUND = "GENERAL_CHAT_NOT_FOUND"
    IDEMPOTENCY_INVALID = "GENERAL_CHAT_IDEMPOTENCY_INVALID"
    IDEMPOTENCY_CONFLICT = "GENERAL_CHAT_IDEMPOTENCY_CONFLICT"
    STALE_REVISION = "GENERAL_CHAT_STALE_REVISION"
    TURN_IN_PROGRESS = "GENERAL_CHAT_TURN_IN_PROGRESS"
    CURSOR_INVALID = "GENERAL_CHAT_CURSOR_INVALID"
    POINTER_INVALID = "GENERAL_CHAT_POINTER_INVALID"
    UNAVAILABLE = "GENERAL_CHAT_APPLICATION_UNAVAILABLE"
    PROTOCOL_INVALID = "GENERAL_CHAT_PROTOCOL_INVALID"


class ChatOwnerFault(RuntimeError):
    def __init__(self, code: ChatOwnerErrorCode) -> None:
        self.code = code
        super().__init__(code.value)


class ChatSlotQuery(ChatBoundaryValue):
    action: Literal["SLOT"] = "SLOT"


class ChatListQuery(ChatBoundaryValue):
    action: Literal["LIST"] = "LIST"
    actor_id: ActorId
    cursor: Cursor | None = None


class ChatCreateCommand(ChatBoundaryValue):
    action: Literal["CREATE"] = "CREATE"
    actor_id: ActorId
    request: GeneralChatCreate
    idempotency_key: IntentKey


class ChatReadQuery(ChatBoundaryValue):
    action: Literal["READ"] = "READ"
    actor_id: ActorId
    conversation_id: ConversationId
    cursor: Cursor | None = None


class ChatSubmitCommand(ChatBoundaryValue):
    action: Literal["SUBMIT"] = "SUBMIT"
    actor_id: ActorId
    conversation_id: ConversationId
    request: GeneralChatSubmission
    idempotency_key: IntentKey


ChatOwnerCommand = Annotated[
    ChatSlotQuery | ChatListQuery | ChatCreateCommand | ChatReadQuery | ChatSubmitCommand,
    Field(discriminator="action"),
]
ChatOwnerValue = GeneralChatSlot | GeneralChatList | GeneralChatConversation


class ChatOwnerRequest(ChatBoundaryValue):
    schema_version: Literal["general-chat-owner-request/1.0"] = "general-chat-owner-request/1.0"
    request_id: str = Field(pattern=r"^chatrpc_[0-9a-f]{32}$")
    command: ChatOwnerCommand


class ChatOwnerReply(ChatBoundaryValue):
    schema_version: Literal["general-chat-owner-reply/1.0"] = "general-chat-owner-reply/1.0"
    request_id: str = Field(pattern=r"^chatrpc_[0-9a-f]{32}$")
    action: OwnerAction
    status: Literal["SUCCEEDED", "FAILED"]
    value: ChatOwnerValue | None
    error_code: ChatOwnerErrorCode | None

    @model_validator(mode="after")
    def truthful_typed_outcome(self) -> ChatOwnerReply:
        if self.status == "FAILED":
            if self.value is not None or self.error_code is None:
                raise ValueError("failed chat owner reply requires only a stable error")
            return self
        if self.error_code is not None:
            raise ValueError("successful owner reply cannot contain an error")
        expected = (
            GeneralChatSlot
            if self.action == "SLOT"
            else (GeneralChatList if self.action == "LIST" else GeneralChatConversation)
        )
        if not isinstance(self.value, expected):
            raise ValueError("owner reply action and projection differ")
        return self


@lru_cache(maxsize=2)
def _owner_validator(kind: Literal["request", "reply"]) -> Draft202012Validator:
    resources = files("eom_protocol").joinpath("schemas")
    views = json.loads(resources.joinpath("general-chat-views.schema.json").read_bytes())
    registry = Registry().with_resource(views["$id"], Resource.from_contents(views))
    schema = json.loads(resources.joinpath(f"general-chat-owner-{kind}.schema.json").read_bytes())
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, registry=registry)


def read_chat_owner_request(document: object) -> ChatOwnerRequest:
    _owner_validator("request").validate(document)
    return ChatOwnerRequest.model_validate(document)


def read_chat_owner_reply(document: object, *, request: ChatOwnerRequest) -> ChatOwnerReply:
    _owner_validator("reply").validate(document)
    reply = ChatOwnerReply.model_validate(document)
    if (reply.request_id, reply.action) != (request.request_id, request.command.action):
        raise ValueError("chat owner reply identity mismatch")
    return reply


class ChatOwnerPort(Protocol):
    def slot(self) -> GeneralChatSlot: ...
    def conversations(self, *, actor_id: str, cursor: str | None) -> GeneralChatList: ...
    def create(
        self, *, actor_id: str, request: GeneralChatCreate, idempotency_key: str
    ) -> GeneralChatConversation: ...
    def conversation(
        self, *, actor_id: str, conversation_id: str, cursor: str | None
    ) -> GeneralChatConversation: ...
    def submit(
        self,
        *,
        actor_id: str,
        conversation_id: str,
        request: GeneralChatSubmission,
        idempotency_key: str,
    ) -> GeneralChatConversation: ...
