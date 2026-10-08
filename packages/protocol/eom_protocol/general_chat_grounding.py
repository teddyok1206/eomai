"""Additive pinned-source chat contracts; V1 bytes and plain-text meaning are unchanged."""

from __future__ import annotations

import json
import re
from functools import lru_cache
from importlib.resources import files
from typing import Annotated, Literal

from eom_identifiers import canonical_json_bytes, sha256_bytes
from jsonschema import Draft202012Validator
from pydantic import Field, model_validator
from referencing import Registry, Resource

from eom_protocol.artifact_members import ArtifactMemberPointer
from eom_protocol.general_chat import (
    ChatBoundaryValue,
    ChatContextMessage,
    ChatTurnInput,
    ChatTurnResult,
)
from eom_protocol.models import UtcDatetime

GROUNDING_SCHEMA = "eom://schemas/general-chat/grounding/1.0"
GROUNDED_MESSAGE_SCHEMA = "eom://schemas/general-chat/message/2.0"
GROUNDED_INPUT_SCHEMA = "eom://schemas/general-chat/turn-input/2.0"
GROUNDED_RESULT_SCHEMA = "eom://schemas/general-chat/turn-result/2.0"
GROUNDED_RECEIPT_SCHEMA = "eom://schemas/general-chat/citation-receipt/1.0"
GroundingHash = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
GroundingFailure = Literal[
    "CODEX_UNAVAILABLE",
    "CODEX_AUTH_REQUIRED",
    "CODEX_TIMEOUT",
    "CODEX_PROTOCOL_INVALID",
    "CODEX_TURN_FAILED",
    "CHAT_ISOLATION_NOT_READY",
]


class ChatKnowledgeItem(ChatBoundaryValue):
    item_id: str = Field(pattern=r"^item_[0-9a-f]{32}$")
    item_revision_id: str = Field(pattern=r"^itemrev_[0-9a-f]{32}$")
    manifest_sha256: GroundingHash


class ChatKnowledgeSnapshot(ChatBoundaryValue):
    graph_snapshot_revision_id: str = Field(pattern=r"^graphrev_[0-9a-f]{32}$")
    sha256: GroundingHash


class ChatKnowledgeSelection(ChatBoundaryValue):
    references: tuple[ChatKnowledgeItem, ...] = Field(min_length=1, max_length=3)
    snapshot: ChatKnowledgeSnapshot | None

    @model_validator(mode="after")
    def unique_revisions(self) -> ChatKnowledgeSelection:
        if len({r.item_revision_id for r in self.references}) != len(self.references):
            raise ValueError("duplicate selected revision")
        return self


class ChatKnowledgeSource(ChatBoundaryValue):
    key: str = Field(pattern=r"^S[1-9]$")
    item: ChatKnowledgeItem
    display_name: str = Field(min_length=1, max_length=256)
    kind: Literal["REGISTRY_DIRECT", "GRAPH_ANALYSIS", "SOLUTION_REPORT"]
    approval: Literal["APPROVED", "PENDING"]
    pointer: ArtifactMemberPointer
    location: str = Field(min_length=1, max_length=256)
    text: str = Field(min_length=1, max_length=24000, pattern=r"\S")
    graph_node_ids: tuple[str, ...] = Field(max_length=16)

    @model_validator(mode="after")
    def bounded_unique_source(self) -> ChatKnowledgeSource:
        if "\x00" in self.text or len(set(self.graph_node_ids)) != len(self.graph_node_ids):
            raise ValueError("invalid source text or duplicate nodes")
        if any(not 1 <= len(node) <= 72 for node in self.graph_node_ids):
            raise ValueError("invalid graph node identity")
        if self.pointer.media_type != "application/json":
            raise ValueError("this text-only slice supports JSON source members only")
        if self.kind != "REGISTRY_DIRECT" and self.approval != "APPROVED":
            raise ValueError("unapproved item is a comparison target, not accepted Graph evidence")
        return self


class ChatKnowledgeContext(ChatBoundaryValue):
    schema_version: Literal["chat-knowledge-context/1.0"] = "chat-knowledge-context/1.0"
    selection: ChatKnowledgeSelection
    sources: tuple[ChatKnowledgeSource, ...] = Field(min_length=1, max_length=9)
    limitations: tuple[str, ...] = Field(max_length=12)
    context_sha256: GroundingHash

    @model_validator(mode="after")
    def exact_context(self) -> ChatKnowledgeContext:
        selected = {r.item_revision_id: r for r in self.selection.references}
        keys = tuple(source.key for source in self.sources)
        if keys != tuple(f"S{i}" for i in range(1, len(keys) + 1)):
            raise ValueError("source keys must be ordered and contiguous")
        pointers = set()
        direct = set()
        for source in self.sources:
            if selected.get(source.item.item_revision_id) != source.item:
                raise ValueError("source is outside exact selection")
            if source.kind == "REGISTRY_DIRECT":
                direct.add(source.item.item_revision_id)
            elif self.selection.snapshot is None:
                raise ValueError("Graph evidence requires a pinned snapshot")
            identity = (source.pointer, source.location)
            if identity in pointers:
                raise ValueError("duplicate source member and location")
            pointers.add(identity)
        if direct != set(selected):
            raise ValueError("every selected revision requires its canonical content")
        if len(self.limitations) != len(set(self.limitations)) or any(
            not 1 <= len(value) <= 256 for value in self.limitations
        ):
            raise ValueError("invalid context limitations")
        value = self.model_dump(mode="json", exclude={"context_sha256"})
        payload = canonical_json_bytes(value)
        if len(payload) > 96000 or sha256_bytes(payload) != self.context_sha256:
            raise ValueError("context exceeds budget or hash differs")
        return self


def chat_knowledge_context(
    *,
    selection: ChatKnowledgeSelection,
    sources: tuple[ChatKnowledgeSource, ...],
    limitations: tuple[str, ...],
) -> ChatKnowledgeContext:
    value = {
        "schema_version": "chat-knowledge-context/1.0",
        "selection": selection.model_dump(mode="json"),
        "sources": [source.model_dump(mode="json") for source in sources],
        "limitations": list(limitations),
    }
    value["context_sha256"] = sha256_bytes(canonical_json_bytes(value))
    return read_grounding("Context", value, ChatKnowledgeContext)


class GroundedChatSubmission(ChatBoundaryValue):
    schema_version: Literal["general-chat-grounded-submission/1.0"] = (
        "general-chat-grounded-submission/1.0"
    )
    text: str = Field(min_length=1, max_length=16000, pattern=r"\S")
    expected_version: int = Field(ge=1)
    selection: ChatKnowledgeSelection | None

    @model_validator(mode="after")
    def no_nul(self) -> GroundedChatSubmission:
        if "\x00" in self.text:
            raise ValueError("invalid chat text")
        return self


class StoredGroundedChatMessage(ChatBoundaryValue):
    schema_version: Literal["general-chat-message/2.0"] = "general-chat-message/2.0"
    conversation_id: str = Field(pattern=r"^chat_[0-9a-f]{32}$")
    turn_id: str = Field(pattern=r"^chatturn_[0-9a-f]{32}$")
    role: Literal["user"] = "user"
    text: str = Field(min_length=1, max_length=16000, pattern=r"\S")
    selection: ChatKnowledgeSelection | None

    @model_validator(mode="after")
    def no_nul(self) -> StoredGroundedChatMessage:
        if "\x00" in self.text:
            raise ValueError("invalid chat text")
        return self


class ChatWorkflowCount(ChatBoundaryValue):
    state: Literal[
        "REQUESTED",
        "RUNNING",
        "AWAITING_HUMAN_APPROVAL",
        "REWORK_REQUESTED",
        "APPROVED",
        "REGISTERING",
        "COMPLETED",
        "FAILED",
        "CANCELLED",
    ]
    count: int = Field(ge=0)


class ChatAgentState(ChatBoundaryValue):
    observed_at: UtcDatetime
    permissions: tuple[str, ...] = Field(max_length=32)
    item_count: int | None = Field(ge=0)
    graph_node_count: int | None = Field(ge=0)
    workflow_counts: tuple[ChatWorkflowCount, ...] = Field(max_length=9)


class GroundedChatTurnInput(ChatBoundaryValue):
    protocol_version: Literal["general-chat-turn/2.0"] = "general-chat-turn/2.0"
    conversation_id: str = Field(pattern=r"^chat_[0-9a-f]{32}$")
    turn_id: str = Field(pattern=r"^chatturn_[0-9a-f]{32}$")
    claim_id: str = Field(pattern=r"^chatclaim_[0-9a-f]{32}$")
    prompt_revision: Literal["general-chat-grounded/1.0.0"] = "general-chat-grounded/1.0.0"
    context_sha256: GroundingHash
    messages: tuple[ChatContextMessage, ...] = Field(min_length=1, max_length=40)
    knowledge: ChatKnowledgeContext | None
    agent_state: ChatAgentState | None = None

    @model_validator(mode="after")
    def exact_messages(self) -> GroundedChatTurnInput:
        payload = canonical_json_bytes([message.model_dump() for message in self.messages])
        if (
            len(payload) > 128000
            or sha256_bytes(payload) != self.context_sha256
            or self.messages[-1].role != "user"
        ):
            raise ValueError("invalid grounded conversation input")
        return self


class ChatAnswerSection(ChatBoundaryValue):
    section_id: str = Field(pattern=r"^section_[1-9][0-9]?$")
    markdown: str = Field(min_length=1, max_length=8000, pattern=r"\S")
    support_kind: Literal[
        "SOURCE_SUPPORTED",
        "MODEL_INFERENCE",
        "GENERAL_KNOWLEDGE",
        "INSUFFICIENT_EVIDENCE",
        "SYSTEM_OBSERVATION",
    ]
    citation_keys: tuple[str, ...] = Field(max_length=9)

    @model_validator(mode="after")
    def truthful_support(self) -> ChatAnswerSection:
        # Citation markers are an owner-rendered projection of structured keys,
        # not free-form model text that could claim an unverified source.
        if "\x00" in self.markdown or re.search(r"\[S[0-9]+\]", self.markdown):
            raise ValueError("citation markers must use structured citation keys")
        if len(self.citation_keys) != len(set(self.citation_keys)) or any(
            key not in {f"S{i}" for i in range(1, 10)} for key in self.citation_keys
        ):
            raise ValueError("invalid citation keys")
        if (self.support_kind == "SOURCE_SUPPORTED" and not self.citation_keys) or (
            self.support_kind
            in {"GENERAL_KNOWLEDGE", "INSUFFICIENT_EVIDENCE", "SYSTEM_OBSERVATION"}
            and self.citation_keys
        ):
            raise ValueError("section support and citations differ")
        return self


class ChatGroundedAnswer(ChatBoundaryValue):
    answer_sections: tuple[ChatAnswerSection, ...] = Field(min_length=1, max_length=16)
    limitations: tuple[str, ...] = Field(max_length=12)

    @model_validator(mode="after")
    def ordered_bounded_answer(self) -> ChatGroundedAnswer:
        if tuple(s.section_id for s in self.answer_sections) != tuple(
            f"section_{i}" for i in range(1, len(self.answer_sections) + 1)
        ):
            raise ValueError("sections must be contiguous and ordered")
        if len(self.reply) > 32000 or len(set(self.limitations)) != len(self.limitations):
            raise ValueError("invalid answer budget")
        if any(not 1 <= len(value) <= 512 for value in self.limitations):
            raise ValueError("invalid answer limitation")
        return self

    @property
    def reply(self) -> str:
        sections = []
        for section in self.answer_sections:
            markers = " ".join(f"[{key}]" for key in section.citation_keys)
            sections.append(section.markdown + ("\n\n" + markers if markers else ""))
        if self.limitations:
            sections.append("확인 범위와 한계\n\n" + "\n".join(self.limitations))
        return "\n\n".join(sections)


class GroundedChatTurnResult(ChatBoundaryValue):
    protocol_version: Literal["general-chat-turn/2.0"] = "general-chat-turn/2.0"
    conversation_id: str = Field(pattern=r"^chat_[0-9a-f]{32}$")
    turn_id: str = Field(pattern=r"^chatturn_[0-9a-f]{32}$")
    claim_id: str = Field(pattern=r"^chatclaim_[0-9a-f]{32}$")
    prompt_revision: Literal["general-chat-grounded/1.0.0"] = "general-chat-grounded/1.0.0"
    request_sha256: GroundingHash
    knowledge_sha256: GroundingHash
    agent_state_sha256: GroundingHash
    status: Literal["SUCCEEDED", "FAILED"]
    answer: ChatGroundedAnswer | None
    failure_code: GroundingFailure | None

    @model_validator(mode="after")
    def truthful_result(self) -> GroundedChatTurnResult:
        if self.status == "SUCCEEDED":
            if self.answer is None or self.failure_code is not None:
                raise ValueError("successful grounded turn requires a final answer")
        elif self.answer is not None or self.failure_code is None:
            raise ValueError("failed grounded turn cannot expose partial content")
        return self

    @property
    def reply(self) -> str:
        return "" if self.answer is None else self.answer.reply


class ChatCitationReceipt(ChatBoundaryValue):
    schema_version: Literal["chat-knowledge-citation-receipt/1.0"] = (
        "chat-knowledge-citation-receipt/1.0"
    )
    request_sha256: GroundingHash
    result_sha256: GroundingHash
    context_sha256: GroundingHash
    used_source_keys: tuple[str, ...] = Field(max_length=9)
    verified_references: tuple[ChatKnowledgeItem, ...] = Field(max_length=3)
    meaning: Literal["CITATION_LINK_INTEGRITY_NOT_SCIENTIFIC_APPROVAL"] = (
        "CITATION_LINK_INTEGRITY_NOT_SCIENTIFIC_APPROVAL"
    )

    @model_validator(mode="after")
    def unique_references(self) -> ChatCitationReceipt:
        if len({item.item_revision_id for item in self.verified_references}) != len(
            self.verified_references
        ):
            raise ValueError("duplicate verified revision")
        if len(set(self.used_source_keys)) != len(self.used_source_keys) or any(
            re.fullmatch(r"S[1-9]", key) is None for key in self.used_source_keys
        ):
            raise ValueError("invalid used source keys")
        return self


class ChatKnowledgeSourceCard(ChatBoundaryValue):
    key: str = Field(pattern=r"^S[1-9]$")
    item: ChatKnowledgeItem
    display_name: str = Field(min_length=1, max_length=256)
    kind: Literal["REGISTRY_DIRECT", "GRAPH_ANALYSIS", "SOLUTION_REPORT"]
    approval: Literal["APPROVED", "PENDING"]
    location: str = Field(min_length=1, max_length=256)


class ChatTurnGroundingView(ChatBoundaryValue):
    turn_id: str = Field(pattern=r"^chatturn_[0-9a-f]{32}$")
    sources: tuple[ChatKnowledgeSourceCard, ...] = Field(max_length=9)
    receipt: ChatCitationReceipt | None
    observed_at: UtcDatetime | None


class ChatGroundingViews(ChatBoundaryValue):
    conversation_id: str = Field(pattern=r"^chat_[0-9a-f]{32}$")
    values: tuple[ChatTurnGroundingView, ...] = Field(max_length=50)


class ChatGroundingSubmission(ChatBoundaryValue):
    turn_ids: tuple[Annotated[str, Field(pattern=r"^chatturn_[0-9a-f]{32}$")], ...] = Field(
        min_length=1, max_length=50
    )

    @model_validator(mode="after")
    def unique_turns(self) -> ChatGroundingSubmission:
        if len(set(self.turn_ids)) != len(self.turn_ids):
            raise ValueError("duplicate chat turn")
        return self


class ChatGroundingQuery(ChatGroundingSubmission):
    action: Literal["READ_GROUNDING"] = "READ_GROUNDING"
    actor_id: str = Field(pattern=r"^operator_[0-9a-f]{32}$")
    conversation_id: str = Field(pattern=r"^chat_[0-9a-f]{32}$")


def validate_chat_citations(
    request: GroundedChatTurnInput,
    result: GroundedChatTurnResult,
) -> ChatCitationReceipt:
    for field in ("conversation_id", "turn_id", "claim_id", "prompt_revision"):
        if getattr(request, field) != getattr(result, field):
            raise ValueError("grounded result identity or claim mismatch")
    expected = sha256_bytes(canonical_json_bytes(request.model_dump(mode="json")))
    if result.request_sha256 != expected:
        raise ValueError("grounded result request hash mismatch")
    context_hash = knowledge_hash(request)
    if result.knowledge_sha256 != context_hash:
        raise ValueError("grounded result context hash mismatch")
    if result.agent_state_sha256 != sha256_bytes(
        canonical_json_bytes(
            None if request.agent_state is None else request.agent_state.model_dump(mode="json")
        )
    ):
        raise ValueError("grounded result observation hash mismatch")
    available = {
        source.key: source
        for source in (() if request.knowledge is None else request.knowledge.sources)
    }
    used = {
        key
        for section in (() if result.answer is None else result.answer.answer_sections)
        for key in section.citation_keys
    }
    if (
        request.agent_state is None
        and result.answer is not None
        and any(
            section.support_kind == "SYSTEM_OBSERVATION"
            for section in result.answer.answer_sections
        )
    ):
        raise ValueError("system observation requires prepared state")
    if not used.issubset(available):
        raise ValueError("result cites a source outside exact prepared context")
    receipt = ChatCitationReceipt(
        request_sha256=sha256_bytes(canonical_json_bytes(request.model_dump(mode="json"))),
        result_sha256=sha256_bytes(canonical_json_bytes(result.model_dump(mode="json"))),
        context_sha256=context_hash,
        used_source_keys=tuple(key for key in available if key in used),
        verified_references=()
        if request.knowledge is None
        else request.knowledge.selection.references,
    )
    return read_grounding("Receipt", receipt.model_dump(mode="json"), ChatCitationReceipt)


def knowledge_hash(request: GroundedChatTurnInput) -> str:
    return (
        sha256_bytes(canonical_json_bytes(None))
        if request.knowledge is None
        else request.knowledge.context_sha256
    )


def read_chat_input(document: object) -> ChatInputContract:
    if isinstance(document, dict) and document.get("protocol_version") == "general-chat-turn/2.0":
        return read_grounded_chat_input(document)
    from eom_protocol.general_chat import read_chat_turn_input

    return read_chat_turn_input(document)


def read_chat_result(document: object, *, request: ChatInputContract) -> ChatResultContract:
    if isinstance(request, GroundedChatTurnInput):
        return read_grounded_chat_result(document, request=request)
    from eom_protocol.general_chat import read_chat_turn_result

    return read_chat_turn_result(document, request=request)


def read_chat_result_document(document: object) -> ChatResultContract:
    if isinstance(document, dict) and document.get("protocol_version") == "general-chat-turn/2.0":
        return read_grounding("Result", document, GroundedChatTurnResult)
    from eom_protocol.general_chat import read_chat_turn_result_document

    return read_chat_turn_result_document(document)


def read_grounded_chat_input(document: object) -> GroundedChatTurnInput:
    return read_grounding("Input", document, GroundedChatTurnInput)


def read_grounded_chat_result(
    document: object, *, request: GroundedChatTurnInput
) -> GroundedChatTurnResult:
    result = read_grounding("Result", document, GroundedChatTurnResult)
    validate_chat_citations(request, result)
    return result


ChatInputContract = ChatTurnInput | GroundedChatTurnInput
ChatResultContract = ChatTurnResult | GroundedChatTurnResult
GroundingError = Literal[
    "CHAT_KNOWLEDGE_FORBIDDEN",
    "CHAT_KNOWLEDGE_NOT_FOUND",
    "CHAT_KNOWLEDGE_STALE",
    "CHAT_KNOWLEDGE_HASH_MISMATCH",
    "CHAT_KNOWLEDGE_SOURCE_UNSUPPORTED",
    "CHAT_KNOWLEDGE_CONTEXT_TOO_LARGE",
    "CHAT_KNOWLEDGE_UNAVAILABLE",
]


class ChatKnowledgeCatalogRequest(ChatBoundaryValue):
    schema_version: Literal["chat-knowledge-catalog-request/1.0"] = (
        "chat-knowledge-catalog-request/1.0"
    )
    operation: Literal["RESOLVE_CHAT_KNOWLEDGE"] = "RESOLVE_CHAT_KNOWLEDGE"
    actor_id: str = Field(pattern=r"^operator_[0-9a-f]{32}$")
    selection: ChatKnowledgeSelection | None
    purpose: Literal["MATERIALIZE", "AUTHORIZE"]


class ChatKnowledgeCatalogReply(ChatBoundaryValue):
    schema_version: Literal["chat-knowledge-catalog-reply/1.0"] = "chat-knowledge-catalog-reply/1.0"
    operation: Literal["RESOLVE_CHAT_KNOWLEDGE"] = "RESOLVE_CHAT_KNOWLEDGE"
    status: Literal["SUCCEEDED", "FAILED"]
    context: ChatKnowledgeContext | None
    agent_state: ChatAgentState | None
    error_code: GroundingError | None

    @model_validator(mode="after")
    def truthful_reply(self) -> ChatKnowledgeCatalogReply:
        if self.status == "SUCCEEDED":
            if self.error_code is not None:
                raise ValueError("successful catalog reply cannot include an error")
        elif self.context is not None or self.error_code is None:
            raise ValueError("failed catalog reply cannot include sources")
        return self


@lru_cache(maxsize=16)
def grounding_validator(definition: str) -> Draft202012Validator:
    resources = files("eom_protocol").joinpath("schemas")
    document = json.loads(resources.joinpath("general-chat-grounding.schema.json").read_bytes())
    artifact = json.loads(resources.joinpath("artifact-member-v1.schema.json").read_bytes())
    registry = Registry().with_resources(
        [
            (document["$id"], Resource.from_contents(document)),
            (artifact["$id"], Resource.from_contents(artifact)),
        ]
    )
    Draft202012Validator.check_schema(document)
    if definition not in document["$defs"]:
        raise ValueError("unsupported grounding definition")
    return Draft202012Validator(
        {"$ref": GROUNDING_SCHEMA + "#/$defs/" + definition}, registry=registry
    )


def read_grounding[T: ChatBoundaryValue](definition: str, value: object, model: type[T]) -> T:
    grounding_validator(definition).validate(value)
    return model.model_validate(value)
