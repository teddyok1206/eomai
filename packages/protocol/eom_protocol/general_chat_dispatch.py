"""Canonical dispatch provenance; small policy values and pinned input pointers."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from eom_protocol.artifact_members import ArtifactMemberPointer
from eom_protocol.general_chat import CHAT_INPUT_SCHEMA, CHAT_MEMBER, ChatBoundaryValue
from eom_protocol.general_chat_grounding import AGENT_INPUT_SCHEMA, GROUNDED_INPUT_SCHEMA
from eom_protocol.general_chat_rag_turn import RAG_INPUT_SCHEMA
from eom_protocol.general_chat_schema_family import validate_chat_envelope
from eom_protocol.general_chat_worker_messages import ChatWorkerPolicy, ChatWorkerTicket

CHAT_DISPATCH_SCHEMA = "eom://schemas/general-chat/dispatch/1.0"


class ChatExecutionIdentity(ChatBoundaryValue):
    boot_id: str = Field(pattern=r"^chatboot_[0-9a-f]{32}$")
    policy: ChatWorkerPolicy


class ChatDispatchReceipt(ChatBoundaryValue):
    schema_version: Literal[
        "general-chat-dispatch/1.0",
        "general-chat-dispatch/2.0",
        "general-chat-dispatch/3.0",
        "general-chat-dispatch/4.0",
        "general-chat-dispatch/5.0",
    ] = "general-chat-dispatch/1.0"
    runtime_id: str = Field(pattern=r"^chatrt_[0-9a-f]{32}$")
    identity: ChatExecutionIdentity
    ticket: ChatWorkerTicket
    input: ArtifactMemberPointer

    @model_validator(mode="after")
    def exact_input_and_policy(self) -> ChatDispatchReceipt:
        if self.identity.policy.sha256 != self.ticket.policy_sha256:
            raise ValueError("dispatch policy differs from exact ticket")
        if (self.schema_version == "general-chat-dispatch/5.0") != (
            self.identity.policy.schema_version == "general-chat-worker-policy/5.0"
        ):
            raise ValueError("dispatch successor must pin its exact policy family")
        expected_schema = (
            RAG_INPUT_SCHEMA
            if self.schema_version == "general-chat-dispatch/5.0"
            or (
                self.schema_version == "general-chat-dispatch/4.0"
                and self.input.schema_ref == RAG_INPUT_SCHEMA
            )
            else AGENT_INPUT_SCHEMA
            if self.schema_version == "general-chat-dispatch/3.0"
            and self.input.schema_ref == AGENT_INPUT_SCHEMA
            else (
                GROUNDED_INPUT_SCHEMA
                if self.input.schema_ref == GROUNDED_INPUT_SCHEMA
                and self.schema_version == "general-chat-dispatch/2.0"
                else CHAT_INPUT_SCHEMA
            )
        )
        if (
            self.input.schema_ref,
            self.input.member_path,
            self.input.media_type,
            self.input.sha256,
        ) != (expected_schema, CHAT_MEMBER, "application/json", self.ticket.request_sha256):
            raise ValueError("dispatch input pointer differs from exact ticket")
        return self


def read_chat_dispatch(document: object) -> ChatDispatchReceipt:
    validate_chat_envelope("dispatch", document)
    return ChatDispatchReceipt.model_validate(document)
