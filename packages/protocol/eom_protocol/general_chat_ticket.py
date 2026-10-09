"""Immutable isolated-worker identity, independent of turn and tool families."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from eom_protocol.general_chat import ChatBoundaryValue

WorkerHash = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]


class ChatWorkerTicket(ChatBoundaryValue):
    schema_version: Literal["general-chat-worker-ticket/1.0"] = "general-chat-worker-ticket/1.0"
    conversation_id: str = Field(pattern=r"^chat_[0-9a-f]{32}$")
    turn_id: str = Field(pattern=r"^chatturn_[0-9a-f]{32}$")
    claim_id: str = Field(pattern=r"^chatclaim_[0-9a-f]{32}$")
    request_sha256: WorkerHash
    policy_sha256: WorkerHash
