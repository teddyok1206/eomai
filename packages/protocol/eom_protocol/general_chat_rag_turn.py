"""Additive V4 conversation/citation contracts; legacy readers remain unchanged."""

from __future__ import annotations

from typing import Annotated, Literal

from eom_identifiers import canonical_json_bytes, sha256_bytes
from pydantic import Field, model_validator

from eom_protocol.artifact_members import ArtifactMemberPointer
from eom_protocol.general_chat import ChatBoundaryValue, ChatContextMessage
from eom_protocol.general_chat_grounding import (
    AgentChatTurnInput,
    ChatAgentState,
    ChatAnswerSection,
    ChatCitationReceipt,
    ChatGroundedAnswer,
    ChatKnowledgeContext,
    ChatKnowledgeItem,
    ChatKnowledgeSourceCard,
    GroundingFailure,
    GroundingHash,
    validate_section_support,
)
from eom_protocol.general_chat_rag_knowledge import (
    RAG_TEXT_KIND,
    ChatRagContext,
    ChatRagReference,
    ChatRagScope,
    read_rag,
)
from eom_protocol.models import UtcDatetime

RAG_INPUT_SCHEMA = "eom://schemas/general-chat/turn-input/4.0"
RAG_RESULT_SCHEMA = "eom://schemas/general-chat/turn-result/4.0"
RAG_CITATION_KEYS = frozenset((*[f"S{i}" for i in range(1, 10)], "R1", "R2", "R3"))


class RagChatAnswerSection(ChatAnswerSection):
    citation_keys: tuple[str, ...] = Field(max_length=12)

    @model_validator(mode="after")
    def truthful_support(self) -> RagChatAnswerSection:
        validate_section_support(
            markdown=self.markdown,
            support_kind=self.support_kind,
            citation_keys=self.citation_keys,
            allowed_keys=RAG_CITATION_KEYS,
        )
        return self


class RagChatAnswer(ChatGroundedAnswer):
    answer_sections: tuple[RagChatAnswerSection, ...] = Field(min_length=1, max_length=16)


class RagChatTurnInput(ChatBoundaryValue):
    protocol_version: Literal["general-chat-turn/4.0"] = "general-chat-turn/4.0"
    conversation_id: str = Field(pattern=r"^chat_[0-9a-f]{32}$")
    turn_id: str = Field(pattern=r"^chatturn_[0-9a-f]{32}$")
    claim_id: str = Field(pattern=r"^chatclaim_[0-9a-f]{32}$")
    prompt_revision: Literal["general-chat-rag-agent/1.0.0"] = "general-chat-rag-agent/1.0.0"
    context_sha256: GroundingHash
    messages: tuple[ChatContextMessage, ...] = Field(min_length=1, max_length=40)
    knowledge: ChatKnowledgeContext | None
    agent_state: ChatAgentState | None = None
    rag_scope: ChatRagScope | None
    rag_knowledge: ChatRagContext | None

    @model_validator(mode="after")
    def exact_prepared_sources(self) -> RagChatTurnInput:
        # Reuse the authoritative message/Item validation without reinterpreting
        # V4 bytes or pretending document references are Item references.
        value = self.model_dump(mode="json", exclude={"rag_scope", "rag_knowledge"})
        value.update(
            protocol_version="general-chat-turn/3.0", prompt_revision="general-chat-agent/1.0.0"
        )
        AgentChatTurnInput.model_validate(value)
        if self.rag_knowledge is not None and self.rag_knowledge.scope != self.rag_scope:
            raise ValueError("prepared RAG context differs from scope")
        if (
            self.knowledge is not None
            and self.knowledge.selection.snapshot is not None
            and (
                self.rag_scope is not None
                and self.knowledge.selection.snapshot != self.rag_scope.snapshot
            )
        ):
            raise ValueError("prepared Item/RAG Graph pins differ")
        materialized = canonical_json_bytes(
            {
                "item": None if self.knowledge is None else self.knowledge.model_dump(mode="json"),
                "rag": None
                if self.rag_knowledge is None
                else self.rag_knowledge.model_dump(mode="json"),
            }
        )
        if len(materialized) > 128000:
            raise ValueError("combined prepared evidence exceeds budget")
        return self


class RagChatTurnResult(ChatBoundaryValue):
    protocol_version: Literal["general-chat-turn/4.0"] = "general-chat-turn/4.0"
    conversation_id: str = Field(pattern=r"^chat_[0-9a-f]{32}$")
    turn_id: str = Field(pattern=r"^chatturn_[0-9a-f]{32}$")
    claim_id: str = Field(pattern=r"^chatclaim_[0-9a-f]{32}$")
    prompt_revision: Literal["general-chat-rag-agent/1.0.0"] = "general-chat-rag-agent/1.0.0"
    request_sha256: GroundingHash
    knowledge_sha256: GroundingHash
    agent_state_sha256: GroundingHash
    status: Literal["SUCCEEDED", "FAILED"]
    answer: RagChatAnswer | None
    failure_code: GroundingFailure | None
    tool_records: tuple[ArtifactMemberPointer, ...] = Field(max_length=7)

    @model_validator(mode="after")
    def truthful_result(self) -> RagChatTurnResult:
        if (self.status == "SUCCEEDED") != (self.answer is not None) or (
            (self.status == "FAILED") != (self.failure_code is not None)
        ):
            raise ValueError("RAG result status and answer/failure differ")
        if len(set(self.tool_records)) != len(self.tool_records) or any(
            pointer.schema_ref != "eom://schemas/general-chat/tool-record/2.0"
            or pointer.media_type != "application/json"
            or pointer.member_path != "chat/evidence.json"
            for pointer in self.tool_records
        ):
            raise ValueError("invalid V4 tool evidence pointer")
        return self

    @property
    def reply(self) -> str:
        return "" if self.answer is None else self.answer.reply


class ChatCitationReceiptV2(ChatBoundaryValue):
    schema_version: Literal["chat-knowledge-citation-receipt/2.0"] = (
        "chat-knowledge-citation-receipt/2.0"
    )
    request_sha256: GroundingHash
    result_sha256: GroundingHash
    context_sha256: GroundingHash
    used_source_keys: tuple[str, ...] = Field(max_length=12)
    verified_references: tuple[ChatKnowledgeItem, ...] = Field(max_length=3)
    verified_rag_references: tuple[ChatRagReference, ...] = Field(max_length=3)
    meaning: Literal["CITATION_LINK_INTEGRITY_NOT_SCIENTIFIC_APPROVAL"] = (
        "CITATION_LINK_INTEGRITY_NOT_SCIENTIFIC_APPROVAL"
    )

    @model_validator(mode="after")
    def unique_pinned_references(self) -> ChatCitationReceiptV2:
        if (
            len(set(self.used_source_keys)) != len(self.used_source_keys)
            or not set(self.used_source_keys).issubset(RAG_CITATION_KEYS)
            or len({ref.item_revision_id for ref in self.verified_references})
            != len(self.verified_references)
            or len({ref.source for ref in self.verified_rag_references})
            != len(self.verified_rag_references)
        ):
            raise ValueError("invalid or duplicate verified references")
        return self


class ChatRagSourceCard(ChatBoundaryValue):
    key: str = Field(pattern=r"^R[1-3]$")
    reference: ChatRagReference
    display_name: str = Field(min_length=1, max_length=256)
    kind: Literal["RAG_ANALYSIS"] = "RAG_ANALYSIS"
    approval: Literal["APPROVED"] = "APPROVED"
    location: str = Field(min_length=1, max_length=256)
    text_kind: Literal["APPROVED_ANALYSIS_NOT_VERBATIM_SOURCE"] = RAG_TEXT_KIND


class ChatTurnGroundingViewV2(ChatBoundaryValue):
    turn_id: str = Field(pattern=r"^chatturn_[0-9a-f]{32}$")
    sources: tuple[
        Annotated[ChatKnowledgeSourceCard | ChatRagSourceCard, Field(discriminator="kind")], ...
    ] = Field(max_length=12)
    receipt: ChatCitationReceipt | ChatCitationReceiptV2 | None
    observed_at: UtcDatetime | None


class ChatGroundingViewsV2(ChatBoundaryValue):
    conversation_id: str = Field(pattern=r"^chat_[0-9a-f]{32}$")
    values: tuple[ChatTurnGroundingViewV2, ...] = Field(max_length=50)


def rag_knowledge_hash(item: ChatKnowledgeContext | None, rag: ChatRagContext | None) -> str:
    return sha256_bytes(
        canonical_json_bytes(
            {
                "item_context": None if item is None else item.context_sha256,
                "rag_context": None if rag is None else rag.context_sha256,
            }
        )
    )


def read_rag_chat_result(document: object, *, request: RagChatTurnInput) -> RagChatTurnResult:
    result = read_rag("Result", document, RagChatTurnResult)
    if any(
        getattr(request, name) != getattr(result, name)
        for name in ("conversation_id", "turn_id", "claim_id", "prompt_revision")
    ) or (
        result.request_sha256 != sha256_bytes(canonical_json_bytes(request.model_dump(mode="json")))
    ):
        raise ValueError("RAG result identity/hash differs")
    state_hash = sha256_bytes(
        canonical_json_bytes(
            None if request.agent_state is None else request.agent_state.model_dump(mode="json")
        )
    )
    if result.agent_state_sha256 != state_hash:
        raise ValueError("RAG result observation hash differs")
    if not result.tool_records and result.knowledge_sha256 != rag_knowledge_hash(
        request.knowledge, request.rag_knowledge
    ):
        raise ValueError("unresolved RAG knowledge hash differs")
    return result


def validate_rag_citations(
    request: RagChatTurnInput,
    result: RagChatTurnResult,
    *,
    item: ChatKnowledgeContext | None,
    rag: ChatRagContext | None,
) -> ChatCitationReceiptV2:
    read_rag_chat_result(result.model_dump(mode="json"), request=request)
    context_hash = rag_knowledge_hash(item, rag)
    if result.knowledge_sha256 != context_hash:
        raise ValueError("resolved RAG evidence hash differs")
    if rag is not None and rag.scope != request.rag_scope:
        raise ValueError("resolved RAG scope differs")
    if (
        item is not None
        and item.selection.snapshot is not None
        and (
            request.rag_scope is not None and item.selection.snapshot != request.rag_scope.snapshot
        )
    ):
        raise ValueError("resolved Item/RAG Graph pins differ")
    available = tuple(s.key for s in (() if item is None else item.sources)) + tuple(
        s.key for s in (() if rag is None else rag.sources)
    )
    used = {
        key
        for section in (() if result.answer is None else result.answer.answer_sections)
        for key in section.citation_keys
    }
    if not used.issubset(available):
        raise ValueError("result cites a source outside exact resolved context")
    if (
        request.agent_state is None
        and result.answer is not None
        and any(s.support_kind == "SYSTEM_OBSERVATION" for s in result.answer.answer_sections)
    ):
        raise ValueError("system observation requires prepared state")
    receipt = ChatCitationReceiptV2(
        request_sha256=result.request_sha256,
        result_sha256=sha256_bytes(canonical_json_bytes(result.model_dump(mode="json"))),
        context_sha256=context_hash,
        used_source_keys=tuple(key for key in available if key in used),
        verified_references=() if item is None else item.selection.references,
        verified_rag_references=() if rag is None else tuple(s.reference for s in rag.sources),
    )
    return read_rag("Receipt", receipt.model_dump(mode="json"), ChatCitationReceiptV2)
