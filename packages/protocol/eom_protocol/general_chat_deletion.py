"""Typed owner-scoped logical deletion; no transcript or Artifact mutation."""

from __future__ import annotations

from pydantic import Field

from eom_protocol.general_chat import ChatBoundaryValue
from eom_protocol.models import UtcDatetime


class GeneralChatDelete(ChatBoundaryValue):
    expected_version: int = Field(ge=1)


class GeneralChatDeletion(ChatBoundaryValue):
    conversation_id: str = Field(pattern=r"^chat_[0-9a-f]{32}$")
    resource_version: int = Field(ge=2)
    deleted_at: UtcDatetime
