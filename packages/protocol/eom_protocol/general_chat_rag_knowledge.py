"""Storage-neutral, pinned document evidence for bounded conversational GraphRAG."""

from __future__ import annotations

import json
import re
from functools import lru_cache
from importlib.resources import files
from typing import Annotated, Literal

from eom_identifiers import canonical_json_bytes, sha256_bytes
from jsonschema import Draft202012Validator
from pydantic import Field, field_validator, model_validator
from referencing import Registry, Resource

from eom_protocol.artifact_members import ArtifactMemberPointer
from eom_protocol.general_chat import ChatBoundaryValue
from eom_protocol.general_chat_grounding import ChatKnowledgeSnapshot, GroundingHash

RAG_SCHEMA = "eom://schemas/general-chat/rag/1.0"
RAG_TEXT_KIND: Literal["APPROVED_ANALYSIS_NOT_VERBATIM_SOURCE"] = (
    "APPROVED_ANALYSIS_NOT_VERBATIM_SOURCE"
)
MAX_RAG_CONTEXT_BYTES = 32000
MAX_RAG_TEXT_BYTES = 8000


class ChatRagPolicy(ChatBoundaryValue):
    access_policy_revision_id: str = Field(pattern=r"^accessrev_[0-9a-f]{32}$")
    sha256: GroundingHash


class ChatRagScope(ChatBoundaryValue):
    snapshot: ChatKnowledgeSnapshot
    policy: ChatRagPolicy


class ChatRagOriginalPointer(ChatBoundaryValue):
    artifact_id: str = Field(pattern=r"^artifact_[0-9a-f]{32}$")
    artifact_revision_id: str = Field(pattern=r"^rev_[0-9a-f]{32}$")
    member_path: str = Field(min_length=1, max_length=512)
    sha256: GroundingHash
    schema_ref: str | None = Field(min_length=1, max_length=256)
    media_type: Literal["application/pdf", "application/json"]
    bytes: int = Field(ge=1, le=1073741824)

    @field_validator("member_path")
    @classmethod
    def safe_member(cls, value: str) -> str:
        return ArtifactMemberPointer.safe_member(value)


class ChatRagDocumentReference(ChatBoundaryValue):
    source_kind: Literal["DOCUMENT_REVISION"] = "DOCUMENT_REVISION"
    source_class: Literal["TEXTBOOK"] = "TEXTBOOK"
    document_id: str = Field(pattern=r"^edudoc_[0-9a-f]{32}$")
    document_revision_id: str = Field(pattern=r"^edudocrev_[0-9a-f]{32}$")
    artifact_member: ChatRagOriginalPointer
    first_physical_page: int = Field(ge=1, le=100000)
    last_physical_page: int = Field(ge=1, le=100000)

    @model_validator(mode="after")
    def bounded_page_range(self) -> ChatRagDocumentReference:
        if (
            not 0 <= self.last_physical_page - self.first_physical_page < 32
            or self.artifact_member.media_type != "application/pdf"
            or self.artifact_member.schema_ref
            != "eom://schemas/educational-document/pdf-source/1.0"
        ):
            raise ValueError("invalid pinned textbook range or original member")
        return self


class ChatRagIntakeReference(ChatBoundaryValue):
    source_kind: Literal["CONTENT_INTAKE_FILE"] = "CONTENT_INTAKE_FILE"
    source_class: Literal["TEXTBOOK", "PAST_EXAM"]
    source_file_id: str = Field(pattern=r"^sourcefile_[0-9a-f]{32}$")
    artifact_member: ChatRagOriginalPointer


class ChatRagItemReference(ChatBoundaryValue):
    source_kind: Literal["APPROVED_ITEM_REVISION"] = "APPROVED_ITEM_REVISION"
    source_class: Literal["PAST_EXAM", "APPROVED_ITEM"]
    item_id: str = Field(pattern=r"^item_[0-9a-f]{32}$")
    item_revision_id: str = Field(pattern=r"^itemrev_[0-9a-f]{32}$")
    artifact_member: ChatRagOriginalPointer

    @model_validator(mode="after")
    def structured_item(self) -> ChatRagItemReference:
        if self.artifact_member.media_type != "application/json":
            raise ValueError("approved Item reference must use its canonical JSON member")
        return self


type ChatRagSourceReference = Annotated[
    ChatRagDocumentReference | ChatRagIntakeReference | ChatRagItemReference,
    Field(discriminator="source_kind"),
]


class ChatRagAnchor(ChatBoundaryValue):
    anchor_id: str = Field(min_length=1, max_length=96)
    artifact_revision_id: str = Field(pattern=r"^rev_[0-9a-f]{32}$")
    member_path: str = Field(min_length=1, max_length=512)
    locator: str = Field(min_length=1, max_length=256)
    excerpt_sha256: GroundingHash

    @field_validator("member_path")
    @classmethod
    def safe_member(cls, value: str) -> str:
        return ArtifactMemberPointer.safe_member(value)

    @field_validator("anchor_id", "locator")
    @classmethod
    def safe_location(cls, value: str) -> str:
        if "\x00" in value or not value.strip():
            raise ValueError("invalid source location")
        return value


class ChatRagReference(ChatBoundaryValue):
    source: ChatRagSourceReference
    analysis_run_id: str = Field(pattern=r"^analysisrun_[0-9a-f]{32}$")
    accepted_result: ArtifactMemberPointer
    analysis_member: ArtifactMemberPointer
    anchors: tuple[ChatRagAnchor, ...] = Field(min_length=1, max_length=32)
    graph_node_ids: tuple[Annotated[str, Field(min_length=1, max_length=72)], ...] = Field(
        min_length=1, max_length=32
    )

    @model_validator(mode="after")
    def exact_analysis_members(self) -> ChatRagReference:
        if (
            self.accepted_result.media_type != "application/json"
            or self.accepted_result.member_path != "evidence/accepted-result.json"
            or re.fullmatch(
                r"eom://schemas/knowledge/knowledge-analysis-result/(?:[2-9]|10)\.0",
                self.accepted_result.schema_ref,
            )
            is None
            or self.analysis_member.media_type != "text/markdown"
            or self.analysis_member.schema_ref != "eom://schemas/knowledge/normalized-markdown/1.0"
            or len({a.anchor_id for a in self.anchors}) != len(self.anchors)
            or len(set(self.graph_node_ids)) != len(self.graph_node_ids)
        ):
            raise ValueError("invalid analysis identity, schema or duplicate source anchors")
        return self


class ChatRagSource(ChatBoundaryValue):
    key: str = Field(pattern=r"^R[1-3]$")
    reference: ChatRagReference
    display_name: str = Field(min_length=1, max_length=256)
    location: str = Field(min_length=1, max_length=256)
    text_kind: Literal["APPROVED_ANALYSIS_NOT_VERBATIM_SOURCE"] = RAG_TEXT_KIND
    text: str = Field(min_length=1, max_length=6000, pattern=r"\S")

    @model_validator(mode="after")
    def untrusted_text_is_data(self) -> ChatRagSource:
        if any("\x00" in value for value in (self.text, self.display_name, self.location)):
            raise ValueError("invalid source text")
        return self


class ChatRagContext(ChatBoundaryValue):
    schema_version: Literal["chat-rag-context/1.0"] = "chat-rag-context/1.0"
    scope: ChatRagScope
    sources: tuple[ChatRagSource, ...] = Field(min_length=1, max_length=3)
    limitations: tuple[Annotated[str, Field(min_length=1, max_length=256)], ...] = Field(
        max_length=12
    )
    context_sha256: GroundingHash

    @model_validator(mode="after")
    def exact_bounded_context(self) -> ChatRagContext:
        if tuple(s.key for s in self.sources) != tuple(
            f"R{i}" for i in range(1, len(self.sources) + 1)
        ):
            raise ValueError("RAG keys must be contiguous and ordered")
        if (
            len({s.reference.source for s in self.sources}) != len(self.sources)
            or len({s.reference.analysis_run_id for s in self.sources}) != len(self.sources)
            or len(set(self.limitations)) != len(self.limitations)
            or any("\x00" in value for value in self.limitations)
            or len({node for s in self.sources for node in s.reference.graph_node_ids}) > 32
            or sum(len(s.text.encode("utf-8")) for s in self.sources) > MAX_RAG_TEXT_BYTES
        ):
            raise ValueError("RAG sources are duplicated or exceed the retrieval budget")
        payload = canonical_json_bytes(self.model_dump(mode="json", exclude={"context_sha256"}))
        if len(payload) > MAX_RAG_CONTEXT_BYTES or sha256_bytes(payload) != self.context_sha256:
            raise ValueError("RAG context hash or size differs")
        return self


def chat_rag_context(
    *, scope: ChatRagScope, sources: tuple[ChatRagSource, ...], limitations: tuple[str, ...]
) -> ChatRagContext:
    value = {
        "schema_version": "chat-rag-context/1.0",
        "scope": scope.model_dump(mode="json"),
        "sources": [source.model_dump(mode="json") for source in sources],
        "limitations": list(limitations),
    }
    value["context_sha256"] = sha256_bytes(canonical_json_bytes(value))
    return read_rag("Context", value, ChatRagContext)


class ChatRagArguments(ChatBoundaryValue):
    terms: tuple[
        Annotated[str, Field(min_length=2, max_length=128, pattern=r"^[a-z0-9가-힣_]+$")], ...
    ] = Field(min_length=1, max_length=8)
    source_classes: tuple[Literal["TEXTBOOK", "PAST_EXAM", "APPROVED_ITEM"], ...] = Field(
        min_length=1, max_length=3
    )

    @model_validator(mode="after")
    def distinct_terms_and_classes(self) -> ChatRagArguments:
        if len(set(self.terms)) != len(self.terms) or len(set(self.source_classes)) != len(
            self.source_classes
        ):
            raise ValueError("duplicate retrieval term or source class")
        return self


class ChatRagPrepareCommand(ChatBoundaryValue):
    action: Literal["PREPARE_CHAT_RAG"] = "PREPARE_CHAT_RAG"
    snapshot: ChatKnowledgeSnapshot | None
    policy: ChatRagPolicy


class ChatRagRetrieveCommand(ChatBoundaryValue):
    action: Literal["RETRIEVE_CHAT_RAG"] = "RETRIEVE_CHAT_RAG"
    scope: ChatRagScope
    arguments: ChatRagArguments
    prior_context: ChatRagContext | None

    @model_validator(mode="after")
    def pinned_prior(self) -> ChatRagRetrieveCommand:
        if self.prior_context is not None and self.prior_context.scope != self.scope:
            raise ValueError("retrieval cannot change the prior evidence scope")
        return self


class ChatRagAuthorizeCommand(ChatBoundaryValue):
    action: Literal["AUTHORIZE_CHAT_RAG"] = "AUTHORIZE_CHAT_RAG"
    context: ChatRagContext


class ChatRagCatalogRequest(ChatBoundaryValue):
    schema_version: Literal["chat-rag-catalog-request/1.0"] = "chat-rag-catalog-request/1.0"
    operation: Literal["CHAT_RAG"] = "CHAT_RAG"
    actor_id: str = Field(pattern=r"^operator_[0-9a-f]{32}$")
    command: Annotated[
        ChatRagPrepareCommand | ChatRagRetrieveCommand | ChatRagAuthorizeCommand,
        Field(discriminator="action"),
    ]


RagError = Literal[
    "CHAT_KNOWLEDGE_FORBIDDEN",
    "CHAT_KNOWLEDGE_UNAVAILABLE",
    "CHAT_KNOWLEDGE_POINTER_INVALID",
    "CHAT_KNOWLEDGE_QUERY_INVALID",
    "CHAT_KNOWLEDGE_READ_LIMIT",
    "CHAT_KNOWLEDGE_NOT_OFFERED",
]


class ChatRagCatalogReply(ChatBoundaryValue):
    schema_version: Literal["chat-rag-catalog-reply/1.0"] = "chat-rag-catalog-reply/1.0"
    operation: Literal["CHAT_RAG"] = "CHAT_RAG"
    status: Literal["SUCCEEDED", "EMPTY", "FAILED"]
    scope: ChatRagScope | None
    context: ChatRagContext | None
    error_code: RagError | None

    @model_validator(mode="after")
    def no_partial_or_unpinned_evidence(self) -> ChatRagCatalogReply:
        if self.status == "FAILED":
            if self.scope is not None or self.context is not None or self.error_code is None:
                raise ValueError("failed retrieval cannot reveal partial evidence")
        elif self.scope is None or self.error_code is not None:
            raise ValueError("successful retrieval requires an exact scope and no error")
        if self.status == "EMPTY" and self.context is not None:
            raise ValueError("empty retrieval cannot contain evidence")
        if self.context is not None and self.context.scope != self.scope:
            raise ValueError("retrieval scope and materialized evidence differ")
        return self


def validate_rag_extension(
    *,
    scope: ChatRagScope,
    previous: ChatRagContext | None,
    context: ChatRagContext,
    source_classes: tuple[str, ...],
) -> None:
    """The same source-key stability rule protects Catalog replies and transcript replay."""
    if context.scope != scope or (previous is not None and previous.scope != scope):
        raise ValueError("RAG materialization changed scope or policy")
    prior = () if previous is None else previous.sources
    if context.sources[: len(prior)] != prior:
        raise ValueError("RAG source keys were deleted or retargeted")
    if any(
        source.reference.source.source_class not in source_classes
        for source in context.sources[len(prior) :]
    ):
        raise ValueError("RAG source is outside requested classes")
    if previous is not None and not set(previous.limitations).issubset(context.limitations):
        raise ValueError("RAG limitations were silently removed")


def read_rag_catalog_reply(
    document: object, *, request: ChatRagCatalogRequest
) -> ChatRagCatalogReply:
    reply = read_rag("CatalogReply", document, ChatRagCatalogReply)
    if reply.status == "FAILED":
        return reply
    command = request.command
    if isinstance(command, ChatRagPrepareCommand):
        if (
            reply.status != "SUCCEEDED"
            or reply.context is not None
            or reply.scope is None
            or reply.scope.policy != command.policy
            or (command.snapshot is not None and command.snapshot != reply.scope.snapshot)
        ):
            raise ValueError("prepared RAG scope differs from requested pins")
    elif isinstance(command, ChatRagRetrieveCommand):
        if reply.scope != command.scope:
            raise ValueError("retrieval reply scope changed")
        if reply.status == "SUCCEEDED":
            if reply.context is None:
                raise ValueError("successful retrieval must materialize evidence")
            validate_rag_extension(
                scope=command.scope,
                previous=command.prior_context,
                context=reply.context,
                source_classes=command.arguments.source_classes,
            )
    elif reply.status != "SUCCEEDED" or reply.context != command.context:
        raise ValueError("reauthorization cannot replace exact evidence")
    return reply


@lru_cache(maxsize=1)
def _rag_resources() -> tuple[Registry, frozenset[str]]:
    root = files("eom_protocol").joinpath("schemas")
    registry: Registry = Registry()
    definitions: frozenset[str] = frozenset()
    for name in (
        "artifact-member-v1",
        "general-chat-grounding",
        "general-chat-worker-ticket",
        "general-chat-agent-search",
        "general-chat-rag",
    ):
        document = json.loads(root.joinpath(name + ".schema.json").read_bytes())
        Draft202012Validator.check_schema(document)
        registry = registry.with_resource(document["$id"], Resource.from_contents(document))
        if document["$id"] == RAG_SCHEMA:
            definitions = frozenset(document["$defs"])
    return registry, definitions


@lru_cache(maxsize=32)
def rag_validator(definition: str) -> Draft202012Validator:
    registry, definitions = _rag_resources()
    if definition not in definitions:
        raise ValueError("unsupported RAG definition")
    return Draft202012Validator({"$ref": RAG_SCHEMA + "#/$defs/" + definition}, registry=registry)


def read_rag[T: ChatBoundaryValue](definition: str, value: object, model: type[T]) -> T:
    rag_validator(definition).validate(value)
    return model.model_validate(value)
