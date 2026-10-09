"""Orchestrator tool use case; actor/claim-scoped reads and sole Artifact commit."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_protocol.general_chat_grounding import (
    AgentChatTurnInput,
    AgentChatTurnResult,
    ChatKnowledgeContext,
    ChatKnowledgeItem,
    ChatKnowledgeSelection,
    ChatKnowledgeSnapshot,
    read_agent,
    validate_agent_citations,
)
from eom_protocol.general_chat_tools import (
    TOOL_RECORD_SCHEMA,
    ChatReadCommand,
    ChatSearchCommand,
    ChatToolOutcome,
    ChatToolRecord,
    ChatToolReply,
    ChatToolRequest,
    ChatToolTranscript,
    failed_tool,
)
from eom_protocol.general_chat_worker_messages import ChatWorkerTicket

from eom_orchestrator.general_chat_artifacts import ChatEvidencePort
from eom_orchestrator.general_chat_knowledge import ChatKnowledgePort
from eom_orchestrator.general_chat_state import ChatError


def resolve_item_tool(
    *,
    command: ChatReadCommand | ChatSearchCommand,
    snapshot: ChatKnowledgeSnapshot | None,
    actor_id: str,
    knowledge: ChatKnowledgePort,
) -> ChatToolOutcome:
    """One existing Item materialization boundary shared by V3 and V4 brokers."""
    try:
        if isinstance(command, ChatReadCommand):
            selection = ChatKnowledgeSelection(
                references=command.arguments.references, snapshot=snapshot
            )
            resolved = knowledge.resolve(
                actor_id=actor_id, selection=selection, purpose="MATERIALIZE"
            )
            if resolved.context is None or resolved.context.selection != selection:
                raise ChatError("GENERAL_CHAT_POINTER_INVALID")
            return ChatToolOutcome(
                status="SUCCEEDED",
                cards=(),
                snapshot=selection.snapshot,
                truncated=False,
                context=resolved.context,
                error_code=None,
            )
        return knowledge.search(actor_id=actor_id, arguments=command.arguments, snapshot=snapshot)
    except ChatError as exc:
        return failed_tool(
            "CHAT_KNOWLEDGE_FORBIDDEN"
            if exc.code == "GENERAL_CHAT_FORBIDDEN"
            else "CHAT_KNOWLEDGE_POINTER_INVALID"
            if exc.code == "GENERAL_CHAT_POINTER_INVALID"
            else "CHAT_KNOWLEDGE_UNAVAILABLE"
        )


class ChatToolBroker:
    def __init__(
        self,
        *,
        rpc_request_id: str,
        ticket: ChatWorkerTicket,
        actor_guard: Callable[[], str],
        knowledge: ChatKnowledgePort,
        evidence: ChatEvidencePort,
    ) -> None:
        self.rpc_request_id, self.ticket = rpc_request_id, ticket
        self.actor_guard, self.knowledge, self.evidence = actor_guard, knowledge, evidence
        self.transcript = ChatToolTranscript()

    def execute(self, request: ChatToolRequest) -> ChatToolReply:
        request = read_agent("Request", request.model_dump(mode="json"), ChatToolRequest)
        if (request.rpc_request_id, request.ticket, request.sequence) != (
            self.rpc_request_id,
            self.ticket,
            self.transcript.sequence + 1,
        ):
            raise ChatError("GENERAL_CHAT_PROTOCOL_INVALID")
        actor_id = self.actor_guard()
        error = self.transcript.command_error(request.command)
        if error is not None:
            outcome = failed_tool(error)
        else:
            outcome = resolve_item_tool(
                command=request.command,
                snapshot=self.transcript.snapshot,
                actor_id=actor_id,
                knowledge=self.knowledge,
            )
        self.actor_guard()
        record = read_agent(
            "Record",
            ChatToolRecord(request=request, outcome=outcome).model_dump(mode="json"),
            ChatToolRecord,
        )
        self.transcript.observe(record)
        pointer = self.evidence.publish(
            payload=canonical_json_bytes(record.model_dump(mode="json")),
            schema_ref=TOOL_RECORD_SCHEMA,
            intent=f"chat-tool:{request.ticket.claim_id}:{request.sequence}",
            created_at=datetime.now(UTC),
        )
        return read_agent(
            "Reply",
            ChatToolReply(record=record, pointer=pointer).model_dump(mode="json"),
            ChatToolReply,
        )


@dataclass(frozen=True, slots=True)
class ResolvedAgentTools:
    context: ChatKnowledgeContext | None
    selections: tuple[ChatKnowledgeSelection, ...]


def agent_tool_knowledge(
    request: AgentChatTurnInput,
    result: AgentChatTurnResult,
    evidence: ChatEvidencePort,
    *,
    payloads: tuple[bytes, ...] | None = None,
) -> ResolvedAgentTools:
    """Resolve trusted canonical records, not source claims supplied by the worker."""
    transcript = ChatToolTranscript()
    rpc_id = None
    ticket = None
    expected_hash = sha256_bytes(canonical_json_bytes(request.model_dump(mode="json")))
    payloads = evidence.read(result.tool_records) if payloads is None else payloads
    discovered: dict[ChatKnowledgeSnapshot | None, dict[str, ChatKnowledgeItem]] = {}
    if len(payloads) != len(result.tool_records):
        raise ChatError("GENERAL_CHAT_POINTER_INVALID")
    for pointer, payload in zip(result.tool_records, payloads, strict=True):
        if pointer.sha256 != sha256_bytes(payload) or pointer.schema_ref != TOOL_RECORD_SCHEMA:
            raise ChatError("GENERAL_CHAT_POINTER_INVALID")
        record = read_agent("Record", json.loads(payload), ChatToolRecord)
        candidate = record.request.ticket
        if (
            (
                candidate.conversation_id,
                candidate.turn_id,
                candidate.claim_id,
                candidate.request_sha256,
            )
            != (request.conversation_id, request.turn_id, request.claim_id, expected_hash)
            or (ticket is not None and candidate != ticket)
            or (rpc_id is not None and rpc_id != record.request.rpc_request_id)
        ):
            raise ChatError("GENERAL_CHAT_POINTER_INVALID")
        ticket, rpc_id = candidate, record.request.rpc_request_id
        transcript.observe(record)
        if record.outcome.cards:
            group = discovered.setdefault(record.outcome.snapshot, {})
            for card in record.outcome.cards:
                prior = group.get(card.item.item_revision_id)
                if prior is not None and prior != card.item:
                    raise ChatError("GENERAL_CHAT_POINTER_INVALID")
                group[card.item.item_revision_id] = card.item
    context = transcript.context if transcript.context is not None else request.knowledge
    validate_agent_citations(request, result, context)
    selections: list[ChatKnowledgeSelection] = []
    for snapshot, group in discovered.items():
        refs = tuple(group.values())
        selections.extend(
            ChatKnowledgeSelection(references=refs[i : i + 3], snapshot=snapshot)
            for i in range(0, len(refs), 3)
        )
    if context is not None:
        selections.append(context.selection)
    return ResolvedAgentTools(context, tuple(selections))
