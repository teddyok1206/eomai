"""One bounded V2 transcript for interleaved Item and textbook read intents."""

from __future__ import annotations

from typing import Annotated, Literal, Protocol

from eom_identifiers import canonical_json_bytes, sha256_bytes
from pydantic import Field, model_validator

from eom_protocol.artifact_members import ArtifactMemberPointer
from eom_protocol.general_chat import ChatBoundaryValue
from eom_protocol.general_chat_grounding import ChatKnowledgeContext, ChatKnowledgeSnapshot
from eom_protocol.general_chat_rag_knowledge import (
    ChatRagArguments,
    ChatRagContext,
    ChatRagScope,
    RagError,
    validate_rag_extension,
)
from eom_protocol.general_chat_tools import (
    ChatDiscoveryCard,
    ChatReadCommand,
    ChatSearchCommand,
    ChatToolOutcome,
    ChatToolRecord,
    ChatToolRequest,
    ChatToolTranscript,
)
from eom_protocol.general_chat_worker_messages import ChatWorkerTicket

RAG_TOOL_RECORD_SCHEMA = "eom://schemas/general-chat/tool-record/2.0"


class ChatRagCommand(ChatBoundaryValue):
    action: Literal["RAG"] = "RAG"
    arguments: ChatRagArguments


type ChatReadCommandV2 = Annotated[
    ChatSearchCommand | ChatReadCommand | ChatRagCommand, Field(discriminator="action")
]


class ChatToolRequestV2(ChatBoundaryValue):
    schema_version: Literal["general-chat-tool-request/2.0"] = "general-chat-tool-request/2.0"
    rpc_request_id: str = Field(pattern=r"^chatwrpc_[0-9a-f]{32}$")
    ticket: ChatWorkerTicket
    sequence: int = Field(ge=1, le=7)
    command: ChatReadCommandV2


class ChatToolOutcomeV2(ChatBoundaryValue):
    status: Literal["SUCCEEDED", "EMPTY", "FAILED"]
    cards: tuple[ChatDiscoveryCard, ...] = Field(max_length=6)
    snapshot: ChatKnowledgeSnapshot | None
    truncated: bool
    context: ChatKnowledgeContext | None
    rag_context: ChatRagContext | None
    error_code: RagError | None

    @model_validator(mode="after")
    def truthful_outcome(self) -> ChatToolOutcomeV2:
        if self.status == "FAILED":
            if (
                self.error_code is None
                or self.cards
                or self.context
                or self.rag_context
                or self.snapshot
                or self.truncated
            ):
                raise ValueError("failed tool cannot contain partial evidence")
        elif self.error_code is not None:
            raise ValueError("successful tool cannot contain an error")
        elif self.status == "EMPTY" and (
            self.cards or self.context or self.rag_context or self.truncated
        ):
            raise ValueError("empty tool cannot contain content")
        elif (
            self.status == "SUCCEEDED"
            and sum(
                (
                    bool(self.cards),
                    self.context is not None,
                    self.rag_context is not None,
                )
            )
            != 1
        ):
            raise ValueError("successful tool must contain exactly one kind of evidence")
        if self.context is not None and self.snapshot != self.context.selection.snapshot:
            raise ValueError("tool Item snapshot differs")
        if self.rag_context is not None and self.snapshot != self.rag_context.scope.snapshot:
            raise ValueError("tool RAG snapshot differs")
        return self


def failed_rag_tool(code: RagError) -> ChatToolOutcomeV2:
    return ChatToolOutcomeV2(
        status="FAILED",
        cards=(),
        snapshot=None,
        truncated=False,
        context=None,
        rag_context=None,
        error_code=code,
    )


class ChatToolRecordV2(ChatBoundaryValue):
    schema_version: Literal["general-chat-tool-record/2.0"] = "general-chat-tool-record/2.0"
    request: ChatToolRequestV2
    outcome: ChatToolOutcomeV2


class ChatToolReplyV2(ChatBoundaryValue):
    schema_version: Literal["general-chat-tool-reply/2.0"] = "general-chat-tool-reply/2.0"
    record: ChatToolRecordV2
    pointer: ArtifactMemberPointer

    @model_validator(mode="after")
    def exact_record_pointer(self) -> ChatToolReplyV2:
        if (
            self.pointer.schema_ref,
            self.pointer.member_path,
            self.pointer.media_type,
            self.pointer.sha256,
        ) != (
            RAG_TOOL_RECORD_SCHEMA,
            "chat/evidence.json",
            "application/json",
            sha256_bytes(canonical_json_bytes(self.record.model_dump(mode="json"))),
        ):
            raise ValueError("tool reply pointer does not bind canonical V2 evidence")
        return self


class ChatRagToolPort(Protocol):
    def call(self, command: object) -> ChatToolReplyV2: ...


class ChatRagToolTranscript:
    """Reuse the existing offered-Item rule; R reads append, never retarget, citations."""

    def __init__(
        self,
        *,
        scope: ChatRagScope | None,
        item_context: ChatKnowledgeContext | None = None,
        rag_context: ChatRagContext | None = None,
    ) -> None:
        if rag_context is not None and rag_context.scope != scope:
            raise ValueError("prepared RAG context scope differs")
        if (
            item_context is not None
            and item_context.selection.snapshot is not None
            and (scope is not None and item_context.selection.snapshot != scope.snapshot)
        ):
            raise ValueError("prepared Item and RAG snapshot differ")
        self.sequence = 0
        self.rag_reads = 0
        self.scope = scope
        self.rag_context = rag_context
        self.items = ChatToolTranscript()
        self.items.context = item_context
        self.items.snapshot = (
            scope.snapshot
            if scope is not None
            else item_context.selection.snapshot
            if item_context is not None
            else None
        )
        self.ticket: ChatWorkerTicket | None = None
        self.rpc_request_id: str | None = None

    def command_error(self, command: ChatReadCommandV2) -> RagError | None:
        if isinstance(command, ChatRagCommand):
            if self.rag_reads >= 2:
                return "CHAT_KNOWLEDGE_READ_LIMIT"
            if self.scope is None:
                return "CHAT_KNOWLEDGE_UNAVAILABLE"
            return None
        return self.items.command_error(command)

    def observe(self, record: ChatToolRecordV2) -> None:
        request, outcome = record.request, record.outcome
        if request.sequence != self.sequence + 1 or request.sequence > 7:
            raise ValueError("tool sequence differs")
        if self.ticket is not None and (
            request.ticket != self.ticket or request.rpc_request_id != self.rpc_request_id
        ):
            raise ValueError("tool ticket or RPC identity changed")
        expected = self.command_error(request.command)
        if expected is not None and (outcome.status != "FAILED" or outcome.error_code != expected):
            raise ValueError("tool bypassed its scope or budget")
        if isinstance(request.command, ChatRagCommand):
            self._observe_rag(request.command, outcome)
            self.rag_reads += 1
        else:
            if outcome.rag_context is not None:
                raise ValueError("Item tool cannot introduce RAG evidence")
            # V2 global sequence includes RAG reads. The existing Item state machine
            # receives its own monotonically ordered Item subsequence, not rewritten history.
            legacy = ChatToolRecord(
                request=ChatToolRequest(
                    rpc_request_id=request.rpc_request_id,
                    ticket=request.ticket,
                    sequence=self.items.sequence + 1,
                    command=request.command,
                ),
                outcome=ChatToolOutcome.model_validate(outcome.model_dump(exclude={"rag_context"})),
            )
            self.items.observe(legacy)
        self.sequence = request.sequence
        self.ticket = request.ticket
        self.rpc_request_id = request.rpc_request_id

    def _observe_rag(self, command: ChatRagCommand, outcome: ChatToolOutcomeV2) -> None:
        if outcome.cards or outcome.context is not None:
            raise ValueError("RAG tool cannot impersonate Item discovery/materialization")
        if outcome.status == "FAILED":
            return
        if self.scope is None or outcome.snapshot != self.scope.snapshot:
            raise ValueError("RAG tool replaced its pinned Graph")
        if outcome.status == "EMPTY":
            return
        context = outcome.rag_context
        if context is None:
            raise ValueError("RAG materialization is missing")
        validate_rag_extension(
            scope=self.scope,
            previous=self.rag_context,
            context=context,
            source_classes=command.arguments.source_classes,
        )
        self.rag_context = context
