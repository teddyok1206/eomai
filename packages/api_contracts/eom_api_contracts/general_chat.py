"""Bounded conversation projections; no worker thread identity enters the browser."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from eom_api_contracts.common import ApiModel, UtcDatetime


class GeneralChatCreate(ApiModel):
    title: str = Field(min_length=1, max_length=120, pattern=r"\S")

    @model_validator(mode="after")
    def nonblank(self) -> GeneralChatCreate:
        if not self.title.strip():
            raise ValueError("blank chat title")
        return self


class GeneralChatSummary(ApiModel):
    conversation_id: str = Field(pattern=r"^chat_[0-9a-f]{32}$")
    title: str = Field(min_length=1, max_length=120, pattern=r"\S")
    resource_version: int = Field(ge=1)
    updated_at: UtcDatetime


class GeneralChatList(ApiModel):
    values: tuple[GeneralChatSummary, ...] = Field(max_length=50)
    next_cursor: str | None = Field(default=None, min_length=1, max_length=1024)
    has_more: bool = False

    @model_validator(mode="after")
    def unique_page(self) -> GeneralChatList:
        if len({value.conversation_id for value in self.values}) != len(self.values):
            raise ValueError("duplicate conversations")
        if self.has_more != bool(self.next_cursor):
            raise ValueError("invalid chat page")
        return self


class GeneralChatSubmission(ApiModel):
    text: str = Field(min_length=1, max_length=16000)
    expected_version: int = Field(ge=1)

    @model_validator(mode="after")
    def nonblank(self) -> GeneralChatSubmission:
        if not self.text.strip() or "\x00" in self.text:
            raise ValueError("invalid chat text")
        return self


class GeneralChatSlot(ApiModel):
    slot_key: Literal["chat"] = "chat"
    state: Literal["READY", "BUSY", "UNAVAILABLE"]
    dedicated: Literal[True] = True
    resident: Literal[True] = True
    unavailable_reason: str | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def reason_matches_state(self) -> GeneralChatSlot:
        if (self.state == "UNAVAILABLE") != bool(self.unavailable_reason):
            raise ValueError("chat availability requires an accurate reason")
        return self


class GeneralChatMessage(ApiModel):
    turn_id: str = Field(pattern=r"^chatturn_[0-9a-f]{32}$")
    sequence: int = Field(ge=1)
    role: Literal["user", "assistant"]
    text: str = Field(max_length=32000)
    state: Literal["QUEUED", "RUNNING", "COMPLETED", "FAILED", "CANCELLED"]
    created_at: UtcDatetime

    @model_validator(mode="after")
    def completed_assistant_has_answer(self) -> GeneralChatMessage:
        if self.role == "assistant" and self.state == "COMPLETED" and not self.text.strip():
            raise ValueError("a completed assistant message requires an answer")
        if self.role == "user" and (not self.text.strip() or len(self.text) > 16000):
            raise ValueError("invalid user message")
        if self.role == "assistant" and self.state != "COMPLETED" and self.text:
            raise ValueError("partial/failed output is not a completed answer")
        return self


class GeneralChatConversation(ApiModel):
    conversation_id: str = Field(pattern=r"^chat_[0-9a-f]{32}$")
    title: str = Field(min_length=1, max_length=120, pattern=r"\S")
    resource_version: int = Field(ge=1)
    messages: tuple[GeneralChatMessage, ...] = Field(default=(), max_length=100)
    updated_at: UtcDatetime
    has_more: bool = False
    next_cursor: str | None = Field(default=None, min_length=1, max_length=1024)

    @model_validator(mode="after")
    def ordered_unique_messages(self) -> GeneralChatConversation:
        sequences = tuple(message.sequence for message in self.messages)
        identities = {(message.turn_id, message.role) for message in self.messages}
        if sequences != tuple(sorted(set(sequences))) or len(identities) != len(self.messages):
            raise ValueError("chat messages must be ordered and unique")
        if self.has_more != bool(self.next_cursor):
            raise ValueError("chat pagination must remain explicit")
        return self
