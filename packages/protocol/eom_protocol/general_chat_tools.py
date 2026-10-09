"""Bounded read-only worker intents and Orchestrator-owned search evidence."""

from __future__ import annotations

from typing import Annotated, Literal, Protocol

from pydantic import Field, model_validator

from eom_protocol.artifact_members import ArtifactMemberPointer
from eom_protocol.general_chat import ChatBoundaryValue
from eom_protocol.general_chat_grounding import (
    ChatKnowledgeContext,
    ChatKnowledgeItem,
    ChatKnowledgeSnapshot,
)
from eom_protocol.general_chat_ticket import ChatWorkerTicket

TOOL_RECORD_SCHEMA = "eom://schemas/general-chat/tool-record/1.0"


class ChatSearchArguments(ChatBoundaryValue):
    kind: Literal["TOPIC", "RECENT", "EXAM"]
    source: Literal["ALL", "PAST_EXAM", "GENERATED"]
    terms: tuple[
        Annotated[str, Field(min_length=2, max_length=128, pattern=r"^[a-z0-9가-힣_]+$")], ...
    ] = Field(max_length=8)
    administration_year: int | None = Field(ge=1900, le=2200)
    administration_month: int | None = Field(ge=1, le=12)
    target_school_level: Literal["ELEMENTARY", "MIDDLE_SCHOOL", "HIGH_SCHOOL"] | None
    target_grade: int | None = Field(ge=1, le=6)
    subject_key: str | None = Field(
        min_length=1, max_length=160, pattern=r"^[a-z0-9][a-z0-9._:-]*$"
    )
    item_number: int | None = Field(ge=1, le=200)

    @model_validator(mode="after")
    def unambiguous_query(self) -> ChatSearchArguments:
        exam = (
            self.administration_year,
            self.administration_month,
            self.target_school_level,
            self.target_grade,
            self.subject_key,
        )
        if len(set(self.terms)) != len(self.terms):
            raise ValueError("duplicate discovery term")
        if self.kind == "EXAM":
            if self.terms or any(value is None for value in exam) or self.source != "ALL":
                raise ValueError("exam search requires an exact placement")
        elif any(value is not None for value in (*exam, self.item_number)):
            raise ValueError("unexpected exam filters")
        if self.kind == "TOPIC" and not self.terms:
            raise ValueError("topic search requires terms")
        if self.kind == "RECENT" and (self.terms or self.source == "PAST_EXAM"):
            raise ValueError("invalid recent search")
        return self


class ChatReadArguments(ChatBoundaryValue):
    references: tuple[ChatKnowledgeItem, ...] = Field(min_length=1, max_length=3)

    @model_validator(mode="after")
    def unique_items(self) -> ChatReadArguments:
        if len({ref.item_revision_id for ref in self.references}) != len(self.references):
            raise ValueError("duplicate read revision")
        return self


class ChatSearchCommand(ChatBoundaryValue):
    action: Literal["SEARCH"] = "SEARCH"
    arguments: ChatSearchArguments


class ChatReadCommand(ChatBoundaryValue):
    action: Literal["READ"] = "READ"
    arguments: ChatReadArguments


class ChatToolRequest(ChatBoundaryValue):
    schema_version: Literal["general-chat-tool-request/1.0"] = "general-chat-tool-request/1.0"
    rpc_request_id: str = Field(pattern=r"^chatwrpc_[0-9a-f]{32}$")
    ticket: ChatWorkerTicket
    sequence: int = Field(ge=1, le=5)
    command: Annotated[ChatSearchCommand | ChatReadCommand, Field(discriminator="action")]


class ChatDiscoveryCard(ChatBoundaryValue):
    item: ChatKnowledgeItem
    display_name: str = Field(min_length=1, max_length=512)
    approval: Literal["APPROVED", "PENDING"]
    source_kind: Literal["PAST_EXAM", "GENERATED", "UNCLASSIFIED"]
    graph_membership: Literal["INDEXED", "NOT_INDEXED", "UNAVAILABLE"]


ToolError = Literal[
    "CHAT_KNOWLEDGE_FORBIDDEN",
    "CHAT_KNOWLEDGE_UNAVAILABLE",
    "CHAT_KNOWLEDGE_POINTER_INVALID",
    "CHAT_KNOWLEDGE_QUERY_INVALID",
    "CHAT_KNOWLEDGE_READ_LIMIT",
    "CHAT_KNOWLEDGE_NOT_OFFERED",
]


class ChatToolOutcome(ChatBoundaryValue):
    status: Literal["SUCCEEDED", "EMPTY", "FAILED"]
    cards: tuple[ChatDiscoveryCard, ...] = Field(max_length=6)
    snapshot: ChatKnowledgeSnapshot | None
    truncated: bool
    context: ChatKnowledgeContext | None
    error_code: ToolError | None

    @model_validator(mode="after")
    def truthful_outcome(self) -> ChatToolOutcome:
        if self.status == "FAILED":
            if (
                self.error_code is None
                or self.cards
                or self.context
                or self.snapshot
                or self.truncated
            ):
                raise ValueError("failed tool cannot contain partial evidence")
        elif self.error_code is not None:
            raise ValueError("successful tool cannot contain an error")
        elif self.status == "EMPTY" and (self.cards or self.context or self.truncated):
            raise ValueError("empty tool cannot contain content")
        elif self.status == "SUCCEEDED" and bool(self.cards) == (self.context is not None):
            raise ValueError("successful tool must contain discovery or materialization")
        if self.context is not None and self.snapshot != self.context.selection.snapshot:
            raise ValueError("tool context snapshot mismatch")
        return self


def failed_tool(code: ToolError) -> ChatToolOutcome:
    return ChatToolOutcome(
        status="FAILED", cards=(), snapshot=None, truncated=False, context=None, error_code=code
    )


class ChatToolRecord(ChatBoundaryValue):
    schema_version: Literal["general-chat-tool-record/1.0"] = "general-chat-tool-record/1.0"
    request: ChatToolRequest
    outcome: ChatToolOutcome


class ChatToolReply(ChatBoundaryValue):
    schema_version: Literal["general-chat-tool-reply/1.0"] = "general-chat-tool-reply/1.0"
    record: ChatToolRecord
    pointer: ArtifactMemberPointer

    @model_validator(mode="after")
    def exact_record_pointer(self) -> ChatToolReply:
        from eom_identifiers import canonical_json_bytes, sha256_bytes

        if (
            self.pointer.schema_ref,
            self.pointer.member_path,
            self.pointer.media_type,
            self.pointer.sha256,
        ) != (
            TOOL_RECORD_SCHEMA,
            "chat/evidence.json",
            "application/json",
            sha256_bytes(canonical_json_bytes(self.record.model_dump(mode="json"))),
        ):
            raise ValueError("tool reply pointer does not bind canonical evidence")
        return self


class ChatToolPort(Protocol):
    def call(self, command: object) -> ChatToolReply: ...


class ChatSearchCatalogRequest(ChatBoundaryValue):
    schema_version: Literal["chat-knowledge-search-request/1.0"] = (
        "chat-knowledge-search-request/1.0"
    )
    operation: Literal["SEARCH_CHAT_KNOWLEDGE"] = "SEARCH_CHAT_KNOWLEDGE"
    actor_id: str = Field(pattern=r"^operator_[0-9a-f]{32}$")
    arguments: ChatSearchArguments
    snapshot: ChatKnowledgeSnapshot | None


class ChatSearchCatalogReply(ChatBoundaryValue):
    schema_version: Literal["chat-knowledge-search-reply/1.0"] = "chat-knowledge-search-reply/1.0"
    operation: Literal["SEARCH_CHAT_KNOWLEDGE"] = "SEARCH_CHAT_KNOWLEDGE"
    outcome: ChatToolOutcome


class ChatToolTranscript:
    """Per-turn bounded state; one authoritative live/replay tool invariant."""

    def __init__(self) -> None:
        self.sequence = 0
        self.searches = 0
        self.reads = 0
        self.offered: dict[str, ChatKnowledgeItem] = {}
        self.snapshot: ChatKnowledgeSnapshot | None = None
        self.context: ChatKnowledgeContext | None = None

    def command_error(self, command: ChatSearchCommand | ChatReadCommand) -> ToolError | None:
        if isinstance(command, ChatSearchCommand):
            return "CHAT_KNOWLEDGE_READ_LIMIT" if self.searches >= 4 else None
        if self.reads >= 1:
            return "CHAT_KNOWLEDGE_READ_LIMIT"
        if any(
            self.offered.get(ref.item_revision_id) != ref for ref in command.arguments.references
        ):
            return "CHAT_KNOWLEDGE_NOT_OFFERED"
        return None

    def observe(self, record: ChatToolRecord) -> None:
        request, outcome = record.request, record.outcome
        if request.sequence != self.sequence + 1 or request.sequence > 5:
            raise ValueError("tool sequence differs")
        expected_error = self.command_error(request.command)
        if expected_error is not None and (
            outcome.status != "FAILED" or outcome.error_code != expected_error
        ):
            raise ValueError("tool bypassed scope or budget")
        if isinstance(request.command, ChatSearchCommand):
            if outcome.context is not None:
                raise ValueError("search is discovery, not content materialization")
            if outcome.status != "FAILED":
                if self.snapshot is not None and outcome.snapshot != self.snapshot:
                    raise ValueError("search silently replaced pinned Graph")
                self.snapshot = outcome.snapshot
                for card in outcome.cards:
                    prior = self.offered.get(card.item.item_revision_id)
                    if prior is not None and prior != card.item:
                        raise ValueError("offered revision hash changed")
                    self.offered[card.item.item_revision_id] = card.item
            self.searches += 1
        else:
            if outcome.cards or outcome.status == "EMPTY":
                raise ValueError("read cannot return discovery or empty success")
            if outcome.context is not None:
                if (outcome.context.selection.references, outcome.context.selection.snapshot) != (
                    request.command.arguments.references,
                    self.snapshot,
                ):
                    raise ValueError("materialization differs from exact offered selection")
                self.context = outcome.context
            self.reads += 1
        self.sequence = request.sequence
