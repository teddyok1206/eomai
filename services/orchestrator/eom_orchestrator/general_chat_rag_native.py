"""V4 native read intents and answer parsing; no Catalog, DB or filesystem access."""

from __future__ import annotations

import json
from importlib.resources import files

from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_protocol.general_chat_grounding import read_agent
from eom_protocol.general_chat_rag_knowledge import ChatRagArguments, read_rag
from eom_protocol.general_chat_rag_tools import (
    ChatRagCommand,
    ChatRagToolPort,
    ChatRagToolTranscript,
    ChatToolReplyV2,
)
from eom_protocol.general_chat_rag_turn import (
    RAG_CITATION_KEYS,
    RagChatAnswer,
    RagChatTurnInput,
    RagChatTurnResult,
    rag_knowledge_hash,
    read_rag_chat_result,
    validate_rag_citations,
)
from eom_protocol.general_chat_tools import (
    ChatReadArguments,
    ChatReadCommand,
    ChatSearchArguments,
    ChatSearchCommand,
)
from jsonschema import ValidationError as SchemaError

from eom_orchestrator.general_chat_agent_native import native_chat_tools
from eom_orchestrator.general_chat_grounded_prompt import (
    GROUNDED_CHAT_INSTRUCTIONS,
    _unique_answer_fields,
)

RAG_CHAT_INSTRUCTIONS = GROUNDED_CHAT_INSTRUCTIONS.replace(
    "You have no tools, file access, live search, or permission to operate EOM.",
    "You have three read-only EOM tools: search_eom_items, read_eom_items and "
    "retrieve_eom_knowledge. Proactively use them for questions about internal "
    "materials; no manual attachment is required. You have no shell, filesystem, "
    "internet, database or mutation tools. For a textbook question, use "
    "retrieve_eom_knowledge with TEXTBOOK; for past-exam concepts use PAST_EXAM; "
    "for registered Item knowledge use APPROVED_ITEM. Use a few short Korean or "
    "lowercase ASCII concept terms, never a whole sentence. These source classes "
    "are requests, NOT permission grants. The Orchestrator applies the actual "
    "operator's permissions and the pinned Graph/access policy. At most two "
    "knowledge retrievals, four Item searches and one Item read are allowed, "
    "seven calls total. Item search cards are discovery, not content evidence. "
    "Read only exact Item references offered in this turn. Item TOPIC searches "
    "use short terms; RECENT accepts ALL or GENERATED; EXAM needs exact year, "
    "month, school level, grade and subject_key. Do not invent dates. Set unused "
    "exam fields to null and unused terms to []. Successful Item reads define "
    "the available S keys; successful knowledge retrievals define R1-R3. R keys "
    "are append-only within the same pinned scope. Follow-ups use prepared exact "
    "references, not latest or sources merely mentioned in old answers. Empty, "
    "forbidden and unavailable outcomes are distinct; none licenses invented "
    "internal facts. R evidence is APPROVED ANALYSIS TEXT, not a verbatim source "
    "page quotation or visual observation. Explicitly state that distinction "
    "when using it; retain its limitations. Never say you saw PDF/PNG pixels or "
    "quote an original page when only analysis text was read. If rag_scope is "
    "null, explain retrieval is unavailable rather than bypassing it.",
)


def native_rag_tools() -> list[dict[str, object]]:
    schema = json.loads(
        files("eom_protocol").joinpath("schemas/general-chat-rag.schema.json").read_bytes()
    )
    return [
        *native_chat_tools(),
        {
            "type": "function",
            "name": "retrieve_eom_knowledge",
            "description": "Read approved textbook/past-exam/Item analysis through EOM GraphRAG. "
            "Returns exact R source pins and bounded analysis text, not original page quotes. "
            "Two calls per turn. Short Korean/lowercase concept terms only.",
            "inputSchema": schema["$defs"]["Arguments"],
        },
    ]


def rag_chat_text(request: RagChatTurnInput) -> str:
    return canonical_json_bytes(
        {
            "question": request.messages[-1].text,
            "authorized_pinned_sources": None
            if request.knowledge is None
            else request.knowledge.model_dump(mode="json"),
            "authorized_rag_scope": None
            if request.rag_scope is None
            else request.rag_scope.model_dump(mode="json"),
            "authorized_rag_analysis": None
            if request.rag_knowledge is None
            else request.rag_knowledge.model_dump(mode="json"),
            "agent_state": None
            if request.agent_state is None
            else request.agent_state.model_dump(mode="json"),
        }
    ).decode("utf-8")


def rag_chat_output_schema() -> dict[str, object]:
    # Native shape only. Full JSON Schema and citation admission are authoritative.
    schema = json.loads(
        files("eom_protocol").joinpath("schemas/general-chat-rag.schema.json").read_bytes()
    )
    section = schema["$defs"]["Section"]
    section.pop("allOf")
    section["properties"]["citation_keys"].pop("uniqueItems")
    section["properties"]["citation_keys"]["items"]["enum"] = sorted(RAG_CITATION_KEYS)
    answer = schema["$defs"]["Answer"]
    answer["properties"]["answer_sections"]["items"] = {"$ref": "#/$defs/Section"}
    answer["properties"]["limitations"].pop("uniqueItems")
    return {**answer, "$defs": {"Section": section}}


class NativeRagChatTools:
    tool_names = frozenset({"search_eom_items", "read_eom_items", "retrieve_eom_knowledge"})
    max_calls = 7

    def __init__(self, request: RagChatTurnInput, port: ChatRagToolPort) -> None:
        self.request, self.port = request, port
        self.transcript = ChatRagToolTranscript(
            scope=request.rag_scope,
            item_context=request.knowledge,
            rag_context=request.rag_knowledge,
        )
        self.records: list[ChatToolReplyV2] = []
        self.diagnostic_stage = "NONE"

    def call(self, tool: str, arguments: object) -> str:
        self.diagnostic_stage = "ARGUMENTS"
        if len(self.records) >= self.max_calls:
            raise ValueError("native tool budget exceeded")
        command: ChatSearchCommand | ChatReadCommand | ChatRagCommand
        if tool == "search_eom_items":
            command = ChatSearchCommand(
                arguments=read_agent("SearchArguments", arguments, ChatSearchArguments)
            )
        elif tool == "read_eom_items":
            command = ChatReadCommand(
                arguments=read_agent("ReadArguments", arguments, ChatReadArguments)
            )
        elif tool == "retrieve_eom_knowledge":
            command = ChatRagCommand(arguments=read_rag("Arguments", arguments, ChatRagArguments))
        else:
            raise ValueError("unknown native read tool")
        self.diagnostic_stage = "BROKER"
        returned = self.port.call(command.model_dump(mode="json"))
        self.diagnostic_stage = "REPLY"
        reply = read_rag("Reply", returned.model_dump(mode="json"), ChatToolReplyV2)
        ticket = reply.record.request.ticket
        if (ticket.conversation_id, ticket.turn_id, ticket.claim_id, ticket.request_sha256) != (
            self.request.conversation_id,
            self.request.turn_id,
            self.request.claim_id,
            sha256_bytes(canonical_json_bytes(self.request.model_dump(mode="json"))),
        ) or reply.record.request.command != command:
            raise ValueError("native reply belongs to another request")
        self.diagnostic_stage = "TRANSCRIPT"
        self.transcript.observe(reply.record)
        self.records.append(reply)
        self.diagnostic_stage = "DONE"
        return canonical_json_bytes(reply.record.outcome.model_dump(mode="json")).decode("utf-8")

    def result(self, *, reply: str, failure: str | None) -> RagChatTurnResult:
        answer = None
        if failure is None:
            if not 0 < len(reply.encode("utf-8")) <= 128000:
                raise ValueError("RAG public answer exceeds its bound")
            try:
                answer = read_rag(
                    "Answer",
                    json.loads(reply, object_pairs_hook=_unique_answer_fields),
                    RagChatAnswer,
                )
            except SchemaError as exc:
                raise ValueError("RAG public answer violates its contract") from exc
        item, rag = self.transcript.items.context, self.transcript.rag_context
        result = read_rag_chat_result(
            {
                **{
                    name: getattr(self.request, name)
                    for name in (
                        "protocol_version",
                        "conversation_id",
                        "turn_id",
                        "claim_id",
                        "prompt_revision",
                    )
                },
                "request_sha256": sha256_bytes(
                    canonical_json_bytes(self.request.model_dump(mode="json"))
                ),
                "knowledge_sha256": rag_knowledge_hash(item, rag),
                "agent_state_sha256": sha256_bytes(
                    canonical_json_bytes(
                        None
                        if self.request.agent_state is None
                        else self.request.agent_state.model_dump(mode="json")
                    )
                ),
                "status": "SUCCEEDED" if failure is None else "FAILED",
                "answer": None if answer is None else answer.model_dump(mode="json"),
                "failure_code": failure,
                "tool_records": [value.pointer.model_dump(mode="json") for value in self.records],
            },
            request=self.request,
        )
        validate_rag_citations(self.request, result, item=item, rag=rag)
        return result
