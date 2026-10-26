"""Private Orchestrator-owner client implementing the neutral chat application port."""

from __future__ import annotations

import grp
import pwd
from uuid import uuid4

from eom_protocol.general_chat_deletion import GeneralChatDelete, GeneralChatDeletion
from eom_protocol.general_chat_grounding import (
    ChatGroundingQuery,
    GroundedChatSubmission,
)
from eom_protocol.general_chat_owner_messages import (
    ChatCreateCommand,
    ChatDeleteCommand,
    ChatListQuery,
    ChatOwnerCommand,
    ChatOwnerErrorCode,
    ChatOwnerFault,
    ChatOwnerRequest,
    ChatOwnerValue,
    ChatReadQuery,
    ChatSlotQuery,
    ChatSubmitCommand,
    read_chat_owner_reply,
    read_chat_owner_request,
)
from eom_protocol.general_chat_rag_turn import ChatGroundingViewsV2
from eom_protocol.general_chat_views import (
    GeneralChatConversation,
    GeneralChatCreate,
    GeneralChatList,
    GeneralChatSlot,
    GeneralChatSubmission,
)
from jsonschema import ValidationError as SchemaError

from eom_orchestrator.general_chat_socket import (
    OWNER_REPLY_LIMIT,
    OWNER_REQUEST_LIMIT,
    OWNER_RPC_TIMEOUT,
    OWNER_SOCKET,
    ChatSocketEndpoint,
    ChatTransportError,
    exchange_chat_frame,
)


class GeneralChatOwnerClient:
    def __init__(self, endpoint: ChatSocketEndpoint | None = None) -> None:
        # Resolve installed identities at call time. An optional/uninstalled chat
        # service must not make unrelated API startup fail.
        self.endpoint = endpoint

    def _endpoint(self) -> ChatSocketEndpoint:
        if self.endpoint is not None:
            return self.endpoint
        try:
            return ChatSocketEndpoint(
                OWNER_SOCKET,
                pwd.getpwnam("eom-general-chat").pw_uid,
                grp.getgrnam("eom-api").gr_gid,
            )
        except KeyError:
            raise ChatOwnerFault(ChatOwnerErrorCode.NOT_READY) from None

    def _request(self, command: ChatOwnerCommand) -> ChatOwnerValue:
        request = ChatOwnerRequest(
            schema_version="general-chat-owner-request/5.0"
            if isinstance(command, ChatDeleteCommand)
            else "general-chat-owner-request/4.0"
            if isinstance(command, ChatGroundingQuery)
            else "general-chat-owner-request/2.0"
            if (
                isinstance(command, ChatSubmitCommand)
                and isinstance(command.request, GroundedChatSubmission)
            )
            else "general-chat-owner-request/1.0",
            request_id="chatrpc_" + uuid4().hex,
            command=command,
        )
        document = request.model_dump(mode="json")
        read_chat_owner_request(document)
        try:
            document = exchange_chat_frame(
                self._endpoint(),
                document,
                request_limit=OWNER_REQUEST_LIMIT,
                reply_limit=OWNER_REPLY_LIMIT,
                timeout=OWNER_RPC_TIMEOUT,
            )
            response = read_chat_owner_reply(document, request=request)
        except ChatTransportError as exc:
            code = (
                ChatOwnerErrorCode.UNAVAILABLE
                if exc.kind == "UNAVAILABLE"
                else ChatOwnerErrorCode.PROTOCOL_INVALID
            )
            raise ChatOwnerFault(code) from None
        except (ValueError, SchemaError):
            raise ChatOwnerFault(ChatOwnerErrorCode.PROTOCOL_INVALID) from None
        if response.error_code is not None:
            raise ChatOwnerFault(response.error_code)
        assert response.value is not None
        return response.value

    def slot(self) -> GeneralChatSlot:
        value = self._request(ChatSlotQuery())
        assert isinstance(value, GeneralChatSlot)
        return value

    def grounding(
        self, *, actor_id: str, conversation_id: str, turn_ids: tuple[str, ...]
    ) -> ChatGroundingViewsV2:
        value = self._request(
            ChatGroundingQuery(
                actor_id=actor_id, conversation_id=conversation_id, turn_ids=turn_ids
            )
        )
        assert isinstance(value, ChatGroundingViewsV2)
        return value

    def conversations(self, *, actor_id: str, cursor: str | None) -> GeneralChatList:
        value = self._request(ChatListQuery(actor_id=actor_id, cursor=cursor))
        assert isinstance(value, GeneralChatList)
        return value

    def create(
        self, *, actor_id: str, request: GeneralChatCreate, idempotency_key: str
    ) -> GeneralChatConversation:
        value = self._request(
            ChatCreateCommand(actor_id=actor_id, request=request, idempotency_key=idempotency_key)
        )
        assert isinstance(value, GeneralChatConversation)
        return value

    def conversation(
        self, *, actor_id: str, conversation_id: str, cursor: str | None
    ) -> GeneralChatConversation:
        value = self._request(
            ChatReadQuery(actor_id=actor_id, conversation_id=conversation_id, cursor=cursor)
        )
        assert isinstance(value, GeneralChatConversation)
        return value

    def submit(
        self,
        *,
        actor_id: str,
        conversation_id: str,
        request: GeneralChatSubmission | GroundedChatSubmission,
        idempotency_key: str,
    ) -> GeneralChatConversation:
        value = self._request(
            ChatSubmitCommand(
                actor_id=actor_id,
                conversation_id=conversation_id,
                request=request,
                idempotency_key=idempotency_key,
            )
        )
        assert isinstance(value, GeneralChatConversation)
        return value

    def delete(
        self,
        *,
        actor_id: str,
        conversation_id: str,
        request: GeneralChatDelete,
        idempotency_key: str,
    ) -> GeneralChatDeletion:
        value = self._request(
            ChatDeleteCommand(
                actor_id=actor_id,
                conversation_id=conversation_id,
                request=request,
                idempotency_key=idempotency_key,
            )
        )
        assert isinstance(value, GeneralChatDeletion)
        return value
