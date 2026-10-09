"""Claim-scoped V4 read use case and canonical transcript replay, owned by Orchestrator."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_protocol.general_chat_grounding import (
    ChatKnowledgeContext,
    ChatKnowledgeItem,
    ChatKnowledgeSelection,
    ChatKnowledgeSnapshot,
)
from eom_protocol.general_chat_rag_knowledge import (
    ChatRagCatalogRequest,
    ChatRagContext,
    ChatRagRetrieveCommand,
    read_rag,
    read_rag_catalog_reply,
)
from eom_protocol.general_chat_rag_tools import (
    RAG_TOOL_RECORD_SCHEMA,
    ChatRagCommand,
    ChatRagToolTranscript,
    ChatToolOutcomeV2,
    ChatToolRecordV2,
    ChatToolReplyV2,
    ChatToolRequestV2,
    failed_rag_tool,
)
from eom_protocol.general_chat_rag_turn import (
    RagChatTurnInput,
    RagChatTurnResult,
    validate_rag_citations,
)
from eom_protocol.general_chat_worker_messages import ChatWorkerTicket
from jsonschema import ValidationError as SchemaError

from eom_orchestrator.general_chat_artifacts import ChatEvidencePort
from eom_orchestrator.general_chat_knowledge import ChatKnowledgePort, ChatRagKnowledgePort
from eom_orchestrator.general_chat_state import ChatError
from eom_orchestrator.general_chat_tool_broker import resolve_item_tool


class ChatRagToolBroker:
    def __init__(
        self,
        *,
        rpc_request_id: str,
        ticket: ChatWorkerTicket,
        prepared: RagChatTurnInput,
        actor_guard: Callable[[], str],
        knowledge: ChatKnowledgePort,
        rag_knowledge: ChatRagKnowledgePort,
        evidence: ChatEvidencePort,
    ) -> None:
        if (ticket.conversation_id, ticket.turn_id, ticket.claim_id, ticket.request_sha256) != (
            prepared.conversation_id,
            prepared.turn_id,
            prepared.claim_id,
            sha256_bytes(canonical_json_bytes(prepared.model_dump(mode="json"))),
        ):
            raise ChatError("GENERAL_CHAT_PROTOCOL_INVALID")
        self.rpc_request_id, self.ticket = rpc_request_id, ticket
        self.actor_guard, self.knowledge = actor_guard, knowledge
        self.rag_knowledge, self.evidence = rag_knowledge, evidence
        self.transcript = ChatRagToolTranscript(
            scope=prepared.rag_scope,
            item_context=prepared.knowledge,
            rag_context=prepared.rag_knowledge,
        )

    def execute(self, request: ChatToolRequestV2) -> ChatToolReplyV2:
        request = read_rag("Request", request.model_dump(mode="json"), ChatToolRequestV2)
        if (request.rpc_request_id, request.ticket, request.sequence) != (
            self.rpc_request_id,
            self.ticket,
            self.transcript.sequence + 1,
        ):
            raise ChatError("GENERAL_CHAT_PROTOCOL_INVALID")
        actor_id = self.actor_guard()
        error = self.transcript.command_error(request.command)
        if error is not None:
            outcome = failed_rag_tool(error)
        elif isinstance(request.command, ChatRagCommand):
            assert self.transcript.scope is not None
            query = ChatRagCatalogRequest(
                actor_id=actor_id,
                command=ChatRagRetrieveCommand(
                    scope=self.transcript.scope,
                    arguments=request.command.arguments,
                    prior_context=self.transcript.rag_context,
                ),
            )
            try:
                reply = read_rag_catalog_reply(
                    self.rag_knowledge.rag(query).model_dump(mode="json"), request=query
                )
                outcome = ChatToolOutcomeV2(
                    status=reply.status,
                    cards=(),
                    snapshot=None if reply.scope is None else reply.scope.snapshot,
                    truncated=False,
                    context=None,
                    rag_context=reply.context,
                    error_code=reply.error_code,
                )
            except ChatError as exc:
                outcome = failed_rag_tool(
                    "CHAT_KNOWLEDGE_FORBIDDEN"
                    if exc.code == "GENERAL_CHAT_FORBIDDEN"
                    else "CHAT_KNOWLEDGE_POINTER_INVALID"
                    if exc.code == "GENERAL_CHAT_POINTER_INVALID"
                    else "CHAT_KNOWLEDGE_UNAVAILABLE"
                )
            except (ValueError, SchemaError):
                outcome = failed_rag_tool("CHAT_KNOWLEDGE_POINTER_INVALID")
        else:
            old = resolve_item_tool(
                command=request.command,
                snapshot=self.transcript.items.snapshot,
                actor_id=actor_id,
                knowledge=self.knowledge,
            )
            outcome = ChatToolOutcomeV2.model_validate(
                {**old.model_dump(mode="json"), "rag_context": None}
            )
        if self.actor_guard() != actor_id:
            raise ChatError("GENERAL_CHAT_FORBIDDEN")
        record = read_rag(
            "Record",
            ChatToolRecordV2(request=request, outcome=outcome).model_dump(mode="json"),
            ChatToolRecordV2,
        )
        self.transcript.observe(record)
        pointer = self.evidence.publish(
            payload=canonical_json_bytes(record.model_dump(mode="json")),
            schema_ref=RAG_TOOL_RECORD_SCHEMA,
            intent=f"chat-tool:{request.ticket.claim_id}:{request.sequence}",
            created_at=datetime.now(UTC),
        )
        return read_rag(
            "Reply",
            ChatToolReplyV2(record=record, pointer=pointer).model_dump(mode="json"),
            ChatToolReplyV2,
        )


@dataclass(frozen=True, slots=True)
class ResolvedRagTools:
    item: ChatKnowledgeContext | None
    rag: ChatRagContext | None
    selections: tuple[ChatKnowledgeSelection, ...]
    rag_contexts: tuple[ChatRagContext, ...]


def rag_tool_knowledge(
    request: RagChatTurnInput,
    result: RagChatTurnResult,
    evidence: ChatEvidencePort,
    *,
    payloads: tuple[bytes, ...] | None = None,
) -> ResolvedRagTools:
    """Replay committed record bytes only; callers reauthorize every returned source."""
    transcript = ChatRagToolTranscript(
        scope=request.rag_scope,
        item_context=request.knowledge,
        rag_context=request.rag_knowledge,
    )
    expected_hash = sha256_bytes(canonical_json_bytes(request.model_dump(mode="json")))
    payloads = evidence.read(result.tool_records) if payloads is None else payloads
    if len(payloads) != len(result.tool_records):
        raise ChatError("GENERAL_CHAT_POINTER_INVALID")
    discovered: dict[ChatKnowledgeSnapshot | None, dict[str, ChatKnowledgeItem]] = {}
    contexts: dict[str, ChatRagContext] = {}
    if request.rag_knowledge is not None:
        contexts[request.rag_knowledge.context_sha256] = request.rag_knowledge
    for pointer, payload in zip(result.tool_records, payloads, strict=True):
        if (
            pointer.sha256 != sha256_bytes(payload)
            or pointer.schema_ref != RAG_TOOL_RECORD_SCHEMA
            or pointer.member_path != "chat/evidence.json"
            or pointer.media_type != "application/json"
        ):
            raise ChatError("GENERAL_CHAT_POINTER_INVALID")
        record = read_rag("Record", json.loads(payload), ChatToolRecordV2)
        ticket = record.request.ticket
        if (ticket.conversation_id, ticket.turn_id, ticket.claim_id, ticket.request_sha256) != (
            request.conversation_id,
            request.turn_id,
            request.claim_id,
            expected_hash,
        ):
            raise ChatError("GENERAL_CHAT_POINTER_INVALID")
        transcript.observe(record)
        if record.outcome.cards:
            group = discovered.setdefault(record.outcome.snapshot, {})
            for card in record.outcome.cards:
                prior = group.get(card.item.item_revision_id)
                if prior is not None and prior != card.item:
                    raise ChatError("GENERAL_CHAT_POINTER_INVALID")
                group[card.item.item_revision_id] = card.item
        context = record.outcome.rag_context
        if context is not None:
            contexts[context.context_sha256] = context
    item, rag = transcript.items.context, transcript.rag_context
    validate_rag_citations(request, result, item=item, rag=rag)
    selections: list[ChatKnowledgeSelection] = []
    if request.knowledge is not None:
        selections.append(request.knowledge.selection)
    for snapshot, group in discovered.items():
        refs = tuple(group.values())
        selections.extend(
            ChatKnowledgeSelection(references=refs[index : index + 3], snapshot=snapshot)
            for index in range(0, len(refs), 3)
        )
    if item is not None and item.selection not in selections:
        selections.append(item.selection)
    return ResolvedRagTools(item, rag, tuple(selections), tuple(contexts.values()))
