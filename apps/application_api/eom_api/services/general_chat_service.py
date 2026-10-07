"""Authenticated chat use cases delegated to the Orchestrator's transcript owner."""

from __future__ import annotations

from collections.abc import Callable
from types import MappingProxyType
from typing import TypeVar

from eom_api_contracts.general_chat import (
    GeneralChatConversation,
    GeneralChatCreate,
    GeneralChatList,
    GeneralChatSlot,
    GeneralChatSubmission,
)
from eom_protocol.general_chat_owner_messages import (
    ChatOwnerErrorCode,
    ChatOwnerFault,
)
from eom_protocol.general_chat_owner_messages import (
    ChatOwnerPort as GeneralChatOwner,
)

from eom_api.errors import ApiError

T = TypeVar("T")
CHAT_HTTP_STATUSES = MappingProxyType(
    {
        ChatOwnerErrorCode.FORBIDDEN: 403,
        ChatOwnerErrorCode.NOT_FOUND: 404,
        ChatOwnerErrorCode.IDEMPOTENCY_INVALID: 400,
        ChatOwnerErrorCode.IDEMPOTENCY_CONFLICT: 409,
        ChatOwnerErrorCode.STALE_REVISION: 409,
        ChatOwnerErrorCode.TURN_IN_PROGRESS: 409,
        ChatOwnerErrorCode.CURSOR_INVALID: 400,
    }
)


class GeneralChatApplicationService:
    """The dedicated owner must be admitted before any conversation can be created."""

    def __init__(self, owner: GeneralChatOwner | None = None) -> None:
        self.owner = owner

    def slot(self) -> GeneralChatSlot:
        if self.owner is None:
            return GeneralChatSlot(
                state="UNAVAILABLE",
                unavailable_reason="전용 대화 서비스를 준비 중입니다.",
            )
        try:
            return self.owner.slot()
        except ChatOwnerFault:
            return GeneralChatSlot(
                state="UNAVAILABLE",
                unavailable_reason="전용 대화 서비스의 연결 상태를 확인 중입니다.",
            )

    def require_owner(self) -> GeneralChatOwner:
        self._owner()
        return self

    def _owner(self) -> GeneralChatOwner:
        if self.owner is None:
            raise ApiError(
                503,
                "GENERAL_CHAT_NOT_READY",
                "General chat unavailable",
                "The dedicated conversation owner has not been activated.",
            )
        return self.owner

    def _call(self, action: Callable[[GeneralChatOwner], T]) -> T:
        try:
            return action(self._owner())
        except ChatOwnerFault as exc:
            raise ApiError(
                CHAT_HTTP_STATUSES.get(exc.code, 503),
                exc.code.value,
                "General chat request failed",
                "The dedicated conversation owner could not complete this request.",
            ) from None

    def conversations(self, *, actor_id: str, cursor: str | None) -> GeneralChatList:
        return self._call(lambda owner: owner.conversations(actor_id=actor_id, cursor=cursor))

    def create(
        self, *, actor_id: str, request: GeneralChatCreate, idempotency_key: str
    ) -> GeneralChatConversation:
        return self._call(
            lambda owner: owner.create(
                actor_id=actor_id, request=request, idempotency_key=idempotency_key
            )
        )

    def conversation(
        self, *, actor_id: str, conversation_id: str, cursor: str | None
    ) -> GeneralChatConversation:
        return self._call(
            lambda owner: owner.conversation(
                actor_id=actor_id, conversation_id=conversation_id, cursor=cursor
            )
        )

    def submit(
        self,
        *,
        actor_id: str,
        conversation_id: str,
        request: GeneralChatSubmission,
        idempotency_key: str,
    ) -> GeneralChatConversation:
        return self._call(
            lambda owner: owner.submit(
                actor_id=actor_id,
                conversation_id=conversation_id,
                request=request,
                idempotency_key=idempotency_key,
            )
        )
