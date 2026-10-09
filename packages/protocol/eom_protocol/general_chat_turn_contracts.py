"""Supported closed V1-V4 turn family; predecessor readers keep their exact semantics."""

from __future__ import annotations

from eom_protocol.general_chat_grounding import (
    ChatInputContract as LegacyChatInput,
)
from eom_protocol.general_chat_grounding import (
    ChatResultContract as LegacyChatResult,
)
from eom_protocol.general_chat_grounding import (
    read_chat_input as read_legacy_input,
)
from eom_protocol.general_chat_grounding import (
    read_chat_result as read_legacy_result,
)
from eom_protocol.general_chat_grounding import (
    read_chat_result_document as read_legacy_result_document,
)
from eom_protocol.general_chat_rag_knowledge import read_rag
from eom_protocol.general_chat_rag_turn import (
    RagChatTurnInput,
    RagChatTurnResult,
    read_rag_chat_result,
)

ChatInputContract = LegacyChatInput | RagChatTurnInput
ChatResultContract = LegacyChatResult | RagChatTurnResult


def read_chat_input(document: object) -> ChatInputContract:
    if isinstance(document, dict) and document.get("protocol_version") == "general-chat-turn/4.0":
        return read_rag("Input", document, RagChatTurnInput)
    return read_legacy_input(document)


def read_chat_result(document: object, *, request: ChatInputContract) -> ChatResultContract:
    if isinstance(request, RagChatTurnInput):
        return read_rag_chat_result(document, request=request)
    return read_legacy_result(document, request=request)


def read_chat_result_document(document: object) -> ChatResultContract:
    if isinstance(document, dict) and document.get("protocol_version") == "general-chat-turn/4.0":
        return read_rag("Result", document, RagChatTurnResult)
    return read_legacy_result_document(document)
