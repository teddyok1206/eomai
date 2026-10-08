"""Canonical dispatch provenance; small policy values and pinned input pointers."""

from __future__ import annotations

import json
from functools import lru_cache
from importlib.resources import files
from typing import Literal

from jsonschema import Draft202012Validator
from pydantic import Field, model_validator
from referencing import Registry, Resource

from eom_protocol.artifact_members import ArtifactMemberPointer
from eom_protocol.general_chat import CHAT_INPUT_SCHEMA, CHAT_MEMBER, ChatBoundaryValue
from eom_protocol.general_chat_worker_messages import ChatWorkerPolicy, ChatWorkerTicket

CHAT_DISPATCH_SCHEMA = "eom://schemas/general-chat/dispatch/1.0"


class ChatExecutionIdentity(ChatBoundaryValue):
    boot_id: str = Field(pattern=r"^chatboot_[0-9a-f]{32}$")
    policy: ChatWorkerPolicy


class ChatDispatchReceipt(ChatBoundaryValue):
    schema_version: Literal["general-chat-dispatch/1.0"] = "general-chat-dispatch/1.0"
    runtime_id: str = Field(pattern=r"^chatrt_[0-9a-f]{32}$")
    identity: ChatExecutionIdentity
    ticket: ChatWorkerTicket
    input: ArtifactMemberPointer

    @model_validator(mode="after")
    def exact_input_and_policy(self) -> ChatDispatchReceipt:
        if self.identity.policy.sha256 != self.ticket.policy_sha256:
            raise ValueError("dispatch policy differs from exact ticket")
        if (
            self.input.schema_ref,
            self.input.member_path,
            self.input.media_type,
            self.input.sha256,
        ) != (CHAT_INPUT_SCHEMA, CHAT_MEMBER, "application/json", self.ticket.request_sha256):
            raise ValueError("dispatch input pointer differs from exact ticket")
        return self


@lru_cache(maxsize=1)
def _dispatch_validator() -> Draft202012Validator:
    resources = files("eom_protocol").joinpath("schemas")
    registry: Registry = Registry()
    for leaf in (
        "artifact-member-v1.schema.json",
        "general-chat-worker-policy.schema.json",
        "general-chat-worker-ticket.schema.json",
    ):
        document = json.loads(resources.joinpath(leaf).read_bytes())
        registry = registry.with_resource(document["$id"], Resource.from_contents(document))
    schema = json.loads(resources.joinpath("general-chat-dispatch.schema.json").read_bytes())
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, registry=registry)


def read_chat_dispatch(document: object) -> ChatDispatchReceipt:
    _dispatch_validator().validate(document)
    return ChatDispatchReceipt.model_validate(document)
