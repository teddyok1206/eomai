"""Closed canonical chat Artifact schema families; no mutable enrollment or authority."""

from __future__ import annotations

from types import MappingProxyType
from typing import Final

from eom_protocol.general_chat import (
    CHAT_INPUT_SCHEMA,
    CHAT_MESSAGE_SCHEMA,
    CHAT_RESULT_SCHEMA,
)
from eom_protocol.general_chat_dispatch import CHAT_DISPATCH_SCHEMA
from eom_protocol.general_chat_grounding import (
    AGENT_INPUT_SCHEMA,
    AGENT_RESULT_SCHEMA,
    GROUNDED_INPUT_SCHEMA,
    GROUNDED_MESSAGE_SCHEMA,
    GROUNDED_RESULT_SCHEMA,
)
from eom_protocol.general_chat_rag_turn import RAG_INPUT_SCHEMA, RAG_RESULT_SCHEMA

_FAMILIES: Final = MappingProxyType(
    {
        CHAT_MESSAGE_SCHEMA: frozenset({CHAT_MESSAGE_SCHEMA, GROUNDED_MESSAGE_SCHEMA}),
        CHAT_INPUT_SCHEMA: frozenset(
            {CHAT_INPUT_SCHEMA, GROUNDED_INPUT_SCHEMA, AGENT_INPUT_SCHEMA, RAG_INPUT_SCHEMA}
        ),
        CHAT_RESULT_SCHEMA: frozenset(
            {CHAT_RESULT_SCHEMA, GROUNDED_RESULT_SCHEMA, AGENT_RESULT_SCHEMA, RAG_RESULT_SCHEMA}
        ),
        CHAT_DISPATCH_SCHEMA: frozenset(
            {
                CHAT_DISPATCH_SCHEMA,
                "eom://schemas/general-chat/dispatch/2.0",
                "eom://schemas/general-chat/dispatch/3.0",
                "eom://schemas/general-chat/dispatch/4.0",
                "eom://schemas/general-chat/dispatch/5.0",
            }
        ),
    }
)


def chat_evidence_schema_family(hint_schema_ref: str) -> frozenset[str]:
    """O(1) lookup shared by the actual Artifact resolver and its checked consumers."""
    return _FAMILIES.get(hint_schema_ref, frozenset())
