"""Model-free chat discovery use case; execution and source materialization are separate."""

from __future__ import annotations

from typing import Protocol

from eom_api_contracts.chat_knowledge import ChatKnowledgeRequest, ChatKnowledgeSelection
from eom_operator_identity import PermissionKey

from eom_api.errors import ApiError


class ChatKnowledgeReadPort(Protocol):
    def search(self, request: ChatKnowledgeRequest) -> ChatKnowledgeSelection: ...


class ChatKnowledgeApplicationService:
    def __init__(self, reader: ChatKnowledgeReadPort) -> None:
        self.reader = reader

    def search(
        self, request: ChatKnowledgeRequest, permissions: frozenset[PermissionKey]
    ) -> ChatKnowledgeSelection:
        if not {PermissionKey.GENERAL_CHAT_READ, PermissionKey.ITEM_READ} <= permissions:
            raise ApiError(
                403,
                "PERMISSION_DENIED",
                "Permission denied",
                "Chat discovery requires both chat and Item read permission.",
            )
        return self.reader.search(request)
