"""Private typed API-to-Orchestrator messages; no storage or native worker handles."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal, Protocol

from pydantic import Field, model_validator

from eom_protocol.general_chat import ChatBoundaryValue
from eom_protocol.general_chat_grounding import (
    ChatGroundingQuery,
    ChatGroundingViews,
    GroundedChatSubmission,
)
from eom_protocol.general_chat_rag_turn import ChatGroundingViewsV2
from eom_protocol.general_chat_schema_family import validate_chat_envelope
from eom_protocol.general_chat_views import (
    GeneralChatConversation,
    GeneralChatCreate,
    GeneralChatList,
    GeneralChatSlot,
    GeneralChatSubmission,
)

OwnerAction = Literal["SLOT", "LIST", "CREATE", "READ", "SUBMIT", "READ_GROUNDING"]
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
    request: GeneralChatSubmission | GroundedChatSubmission
    idempotency_key: IntentKey


ChatOwnerCommand = Annotated[
    ChatSlotQuery
    | ChatListQuery
    | ChatCreateCommand
    | ChatReadQuery
    | ChatSubmitCommand
    | ChatGroundingQuery,
    Field(discriminator="action"),
]
ChatOwnerValue = (
    GeneralChatSlot
    | GeneralChatList
    | GeneralChatConversation
    | ChatGroundingViews
    | ChatGroundingViewsV2
)


class ChatOwnerRequest(ChatBoundaryValue):
    schema_version: Literal[
        "general-chat-owner-request/1.0",
        "general-chat-owner-request/2.0",
        "general-chat-owner-request/4.0",
    ] = "general-chat-owner-request/1.0"
    request_id: str = Field(pattern=r"^chatrpc_[0-9a-f]{32}$")
    command: ChatOwnerCommand

    @property
    def reply_version(
        self,
    ) -> Literal[
        "general-chat-owner-reply/1.0",
        "general-chat-owner-reply/2.0",
        "general-chat-owner-reply/4.0",
    ]:
        return (
            "general-chat-owner-reply/4.0"
            if self.schema_version.endswith("/4.0")
            else "general-chat-owner-reply/2.0"
            if self.schema_version.endswith("/2.0")
            else "general-chat-owner-reply/1.0"
        )


class ChatOwnerReply(ChatBoundaryValue):
    schema_version: Literal[
        "general-chat-owner-reply/1.0",
        "general-chat-owner-reply/2.0",
        "general-chat-owner-reply/4.0",
    ] = "general-chat-owner-reply/1.0"
    request_id: str = Field(pattern=r"^chatrpc_[0-9a-f]{32}$")
    action: OwnerAction
    status: Literal["SUCCEEDED", "FAILED"]
    value: ChatOwnerValue | None
    error_code: ChatOwnerErrorCode | None

    @model_validator(mode="before")
    @classmethod
    def exact_grounding_family(cls, value: object) -> object:
        # An empty/source-free view is structurally valid in both families.
        # The envelope, not union guessing, selects its promised wire meaning.
        if (
            isinstance(value, dict)
            and value.get("action") == "READ_GROUNDING"
            and value.get("status") == "SUCCEEDED"
            and isinstance(value.get("value"), dict)
        ):
            view_type = (
                ChatGroundingViewsV2
                if value.get("schema_version") == "general-chat-owner-reply/4.0"
                else ChatGroundingViews
            )
            return {**value, "value": view_type.model_validate(value["value"])}
        return value

    @model_validator(mode="after")
    def truthful_typed_outcome(self) -> ChatOwnerReply:
        if self.status == "FAILED":
            if self.value is not None or self.error_code is None:
                raise ValueError("failed chat owner reply requires only a stable error")
            return self
        if self.error_code is not None:
            raise ValueError("successful owner reply cannot contain an error")
        expected: type[ChatBoundaryValue] = (
            GeneralChatSlot
            if self.action == "SLOT"
            else (GeneralChatList if self.action == "LIST" else GeneralChatConversation)
        )
        if self.action == "READ_GROUNDING":
            expected = (
                ChatGroundingViewsV2 if self.schema_version.endswith("/4.0") else ChatGroundingViews
            )
        if not isinstance(self.value, expected):
            raise ValueError("owner reply action and projection differ")
        return self


def read_chat_owner_request(document: object) -> ChatOwnerRequest:
    validate_chat_envelope("owner-request", document)
    return ChatOwnerRequest.model_validate(document)


def read_chat_owner_reply(document: object, *, request: ChatOwnerRequest) -> ChatOwnerReply:
    validate_chat_envelope("owner-reply", document)
    reply = ChatOwnerReply.model_validate(document)
    if (reply.request_id, reply.action, reply.schema_version) != (
        request.request_id,
        request.command.action,
        request.reply_version,
    ):
        raise ValueError("chat owner reply identity mismatch")
    return reply


class ChatOwnerPort(Protocol):
    def grounding(
        self, *, actor_id: str, conversation_id: str, turn_ids: tuple[str, ...]
    ) -> ChatGroundingViews | ChatGroundingViewsV2: ...
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
        request: GeneralChatSubmission | GroundedChatSubmission,
        idempotency_key: str,
    ) -> GeneralChatConversation: ...
