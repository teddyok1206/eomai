"""Authenticated chat use cases delegated to the Orchestrator's transcript owner."""

from __future__ import annotations

from typing import Protocol

from eom_api_contracts.general_chat import (
    GeneralChatConversation,
    GeneralChatCreate,
    GeneralChatList,
    GeneralChatSlot,
    GeneralChatSubmission,
)

from eom_api.errors import ApiError


class GeneralChatOwner(Protocol):
    """Execution and canonical history boundary, never a browser-selected worker."""

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
        return self.owner.slot()

    def require_owner(self) -> GeneralChatOwner:
        if self.owner is None:
            raise ApiError(
                503,
                "GENERAL_CHAT_NOT_READY",
                "General chat unavailable",
                "The dedicated conversation owner has not been activated.",
            )
        return self.owner
