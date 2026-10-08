"""Exact native read tools and V3 answer admission; no Catalog/DB/file adapters."""

from __future__ import annotations

import json
from importlib.resources import files

from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_protocol.general_chat_grounding import (
    AgentChatTurnInput,
    AgentChatTurnResult,
    ChatKnowledgeContext,
    project_agent_input,
    read_agent,
    validate_agent_citations,
)
from eom_protocol.general_chat_tools import (
    ChatReadArguments,
    ChatReadCommand,
    ChatSearchArguments,
    ChatSearchCommand,
    ChatToolPort,
    ChatToolReply,
    ChatToolTranscript,
)

from eom_orchestrator.general_chat_grounded_prompt import (
    GROUNDED_CHAT_INSTRUCTIONS,
    grounded_chat_result,
)

AGENT_CHAT_INSTRUCTIONS = GROUNDED_CHAT_INSTRUCTIONS.replace(
    "You have no tools, file access, live search, or permission to operate EOM.",
    "You have exactly two read-only internal tools: search_eom_items and read_eom_items. "
    "For an internal Item search/question, proactively search and then read relevant "
    "offered Items; the user need not manually attach anything. You cannot access "
    "files, shell, the internet, databases or mutation tools. Search cards are discovery "
    "metadata, NOT evidence for an Item's content. Use read_eom_items to obtain content "
    "before analyzing it. Never claim search is impossible when these tools are available. "
    "At most four searches and one read (up to three Items) are allowed in this turn. "
    "TOPIC searches use a few short concept terms, not full sentences; try alternative "
    "terms if empty. RECENT supports ALL or GENERATED; EXAM requires exact year, "
    "month, school level, grade and subject_key (for integrated science, integrated-science). "
    "Set unused exam fields to null and unused terms to []. Do not invent exam dates. "
    "Read only exact item/revision/manifest hashes returned by search in THIS turn. "
    "Successful read results are the authoritative current citation context, replacing "
    "initial prepared sources explicitly; use only their actual S keys in the answer. "
    "Sources mentioned in previous answers are not current evidence unless prepared "
    "or read in this turn. Empty results do not prove no such Item exists in the corpus. "
    "Differentiate EMPTY, denied permission and unavailable service; never fabricate "
    "results or pretend an unsuccessful read inspected content.",
)


def native_chat_tools() -> list[dict[str, object]]:
    agent = json.loads(
        files("eom_protocol").joinpath("schemas/general-chat-agent-search.schema.json").read_bytes()
    )
    grounding = json.loads(
        files("eom_protocol").joinpath("schemas/general-chat-grounding.schema.json").read_bytes()
    )
    read = agent["$defs"]["ReadArguments"]
    read["properties"]["references"]["items"] = grounding["$defs"]["Item"]
    read["properties"]["references"].pop("uniqueItems", None)
    return [
        {
            "type": "function",
            "name": "search_eom_items",
            "description": "Search EOM Items by topic, recent creation or exam placement. "
            "Returns six exact revision cards, not content. Read chosen cards to analyze.",
            "inputSchema": agent["$defs"]["SearchArguments"],
        },
        {
            "type": "function",
            "name": "read_eom_items",
            "description": "Read three exact Item references offered by search in this turn, with "
            "canonical content and available Graph-linked solution reports. One read per turn.",
            "inputSchema": read,
        },
    ]


class NativeChatTools:
    def __init__(self, request: AgentChatTurnInput, port: ChatToolPort) -> None:
        self.request, self.port = request, port
        self.transcript = ChatToolTranscript()
        self.records: list[ChatToolReply] = []

    @property
    def knowledge(self) -> ChatKnowledgeContext | None:
        return (
            self.transcript.context
            if self.transcript.context is not None
            else self.request.knowledge
        )

    def call(self, tool: str, arguments: object) -> str:
        if len(self.records) >= 5:
            raise ValueError("tool budget exceeded")
        command: ChatSearchCommand | ChatReadCommand
        if tool == "search_eom_items":
            command = ChatSearchCommand(
                arguments=read_agent("SearchArguments", arguments, ChatSearchArguments)
            )
        elif tool == "read_eom_items":
            command = ChatReadCommand(
                arguments=read_agent("ReadArguments", arguments, ChatReadArguments)
            )
        else:
            raise ValueError("unknown native tool")
        reply = read_agent(
            "Reply",
            self.port.call(command.model_dump(mode="json")).model_dump(mode="json"),
            ChatToolReply,
        )
        ticket = reply.record.request.ticket
        if (ticket.conversation_id, ticket.turn_id, ticket.claim_id, ticket.request_sha256) != (
            self.request.conversation_id,
            self.request.turn_id,
            self.request.claim_id,
            sha256_bytes(canonical_json_bytes(self.request.model_dump(mode="json"))),
        ) or reply.record.request.command != command:
            raise ValueError("native tool reply belongs to another request")
        self.transcript.observe(reply.record)
        self.records.append(reply)
        return canonical_json_bytes(reply.record.outcome.model_dump(mode="json")).decode()

    def result(self, *, reply: str, failure: str | None) -> AgentChatTurnResult:
        prepared = project_agent_input(self.request, self.knowledge)
        parsed = grounded_chat_result(prepared, reply=reply, failure=failure)
        document = parsed.model_dump(mode="json")
        document.update(
            protocol_version=self.request.protocol_version,
            prompt_revision=self.request.prompt_revision,
            request_sha256=sha256_bytes(canonical_json_bytes(self.request.model_dump(mode="json"))),
            tool_records=[value.pointer.model_dump(mode="json") for value in self.records],
        )
        result = read_agent("Result", document, AgentChatTurnResult)
        validate_agent_citations(self.request, result, self.knowledge)
        return result
