"""Staged general-chat worker boundary; no auth, storage or native thread handles."""

from __future__ import annotations

import json
from functools import lru_cache
from hashlib import sha256
from importlib.resources import files
from typing import Literal

from eom_identifiers import canonical_json_bytes
from jsonschema import Draft202012Validator
from pydantic import BaseModel, ConfigDict, Field, model_validator


class ChatBoundaryValue(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ChatContextMessage(ChatBoundaryValue):
    role: Literal["user", "assistant"]
    text: str = Field(min_length=1, max_length=32000, pattern=r"\S")

    @model_validator(mode="after")
    def no_nul(self) -> ChatContextMessage:
        if "\x00" in self.text:
            raise ValueError("invalid chat context")
        return self


class ChatTurnIdentity(ChatBoundaryValue):
    protocol_version: Literal["general-chat-turn/1.0"] = "general-chat-turn/1.0"
    conversation_id: str = Field(pattern=r"^chat_[0-9a-f]{32}$")
    turn_id: str = Field(pattern=r"^chatturn_[0-9a-f]{32}$")
    claim_id: str = Field(pattern=r"^chatclaim_[0-9a-f]{32}$")
    prompt_revision: Literal["general-chat/1.0.0"] = "general-chat/1.0.0"


class ChatTurnInput(ChatTurnIdentity):
    context_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    messages: tuple[ChatContextMessage, ...] = Field(min_length=1, max_length=40)

    @model_validator(mode="after")
    def pinned_bounded_context(self) -> ChatTurnInput:
        materialized = canonical_json_bytes([message.model_dump() for message in self.messages])
        if len(materialized) > 128000:
            raise ValueError("chat context exceeds materialization budget")
        if self.context_sha256 != "sha256:" + sha256(materialized).hexdigest():
            raise ValueError("chat context hash mismatch")
        if self.messages[-1].role != "user":
            raise ValueError("a staged turn must end with its new user message")
        return self


class ChatTurnResult(ChatTurnIdentity):
    request_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    status: Literal["SUCCEEDED", "FAILED"]
    reply: str = Field(max_length=32000)
    failure_code: (
        Literal[
            "CODEX_UNAVAILABLE",
            "CODEX_AUTH_REQUIRED",
            "CODEX_TIMEOUT",
            "CODEX_PROTOCOL_INVALID",
            "CODEX_TURN_FAILED",
            "CHAT_ISOLATION_NOT_READY",
        ]
        | None
    )

    @model_validator(mode="after")
    def truthful_terminal_result(self) -> ChatTurnResult:
        if self.status == "SUCCEEDED":
            if not self.reply.strip() or self.failure_code is not None:
                raise ValueError("success requires a final answer and no failure")
        elif self.reply or self.failure_code is None:
            raise ValueError("failure must not publish partial output as an answer")
        return self


@lru_cache(maxsize=2)
def _validator(name: Literal["input", "result"]) -> Draft202012Validator:
    schema = json.loads(
        files("eom_protocol")
        .joinpath("schemas", f"general-chat-turn-{name}.schema.json")
        .read_text(encoding="utf-8")
    )
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def read_chat_turn_input(document: object) -> ChatTurnInput:
    _validator("input").validate(document)
    return ChatTurnInput.model_validate(document)


def read_chat_turn_result(document: object, *, request: ChatTurnInput) -> ChatTurnResult:
    _validator("result").validate(document)
    result = ChatTurnResult.model_validate(document)
    for field in ("conversation_id", "turn_id", "claim_id", "prompt_revision"):
        if getattr(result, field) != getattr(request, field):
            raise ValueError("chat result identity/claim mismatch")
    expected = "sha256:" + sha256(canonical_json_bytes(request.model_dump(mode="json"))).hexdigest()
    if result.request_sha256 != expected:
        raise ValueError("chat result request hash mismatch")
    return result
