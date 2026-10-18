"""Ordered metadata join keys; not Artifact file reads or native source authority."""

from __future__ import annotations

from typing import ClassVar, Literal

from eom_identifiers import content_sha256
from eom_protocol.general_chat_rag_knowledge import ChatRagScope
from eom_protocol.general_chat_tools import ChatDiscoveryCard, ChatSearchArguments
from jsonschema.exceptions import ValidationError as SchemaError
from pydantic import ConfigDict, Field, model_validator

from eom_catalog_contracts.chat_private_query_scope import ChatPrivateQueryScopeErrorCode
from eom_catalog_contracts.embedding_reference_query import (
    raw_similarity_contract_value,
    similarity_contract_document,
)
from eom_catalog_contracts.models import FrozenModel, Sha256
from eom_catalog_contracts.private_chat_similarity import PrivateChatSimilarityContext

CHAT_RANKED_READ_REQUEST_BYTES = 32 * 1024
CHAT_RANKED_READ_REPLY_BYTES = 16 * 1024


class ChatRankedCandidateReadError(ValueError):
    def __init__(self) -> None:
        super().__init__("CHAT_RANKED_CANDIDATE_READ_INVALID")


class ChatRankedCandidateKey(FrozenModel):
    item_id: str = Field(pattern=r"^item_[0-9a-f]{32}$")
    item_revision_id: str = Field(pattern=r"^itemrev_[0-9a-f]{32}$")
    source_class: Literal["APPROVED_ITEM", "PAST_EXAM"]
    component_artifact_id: str = Field(pattern=r"^artifact_[0-9a-f]{32}$")
    component_artifact_revision_id: str = Field(pattern=r"^rev_[0-9a-f]{32}$")
    component_sha256: Sha256


class _RankedReadValue(FrozenModel):
    model_config = ConfigDict(revalidate_instances="always", hide_input_in_errors=True)
    maximum_bytes: ClassVar[int] = CHAT_RANKED_READ_REPLY_BYTES - 1

    @model_validator(mode="before")
    @classmethod
    def schema_first(cls, value: object) -> object:
        return similarity_contract_document(value, "chat-ranked-candidate-read", cls.maximum_bytes)


class ChatRankedCandidateReadRequest(_RankedReadValue):
    maximum_bytes = CHAT_RANKED_READ_REQUEST_BYTES - 1
    schema_version: Literal["chat-ranked-candidate-read-request/1.0"]
    operation: Literal["READ_CHAT_RANKED_CANDIDATES"]
    actor_id: str = Field(pattern=r"^operator_[0-9a-f]{32}$")
    scope: ChatRagScope
    arguments: ChatSearchArguments
    candidates: tuple[ChatRankedCandidateKey, ...] = Field(max_length=64)
    request_sha256: Sha256

    @model_validator(mode="after")
    def exact_ordered_keys(self) -> ChatRankedCandidateReadRequest:
        revisions = tuple(key.item_revision_id for key in self.candidates)
        if len(set(revisions)) != len(revisions) or self.request_sha256 != content_sha256(
            self.model_dump(mode="json", exclude={"request_sha256"})
        ):
            raise ChatRankedCandidateReadError()
        return self


class ChatRankedCandidateReadReply(_RankedReadValue):
    schema_version: Literal["chat-ranked-candidate-read-reply/1.0"]
    request_sha256: Sha256
    status: Literal["SUCCEEDED", "EMPTY", "FAILED"]
    scope: ChatRagScope | None
    cards: tuple[ChatDiscoveryCard, ...] = Field(max_length=6)
    truncated: bool
    error_code: ChatPrivateQueryScopeErrorCode | None


def parse_chat_ranked_candidate_read_request(value: object) -> ChatRankedCandidateReadRequest:
    try:
        return ChatRankedCandidateReadRequest.model_validate(raw_similarity_contract_value(value))
    except (ValueError, TypeError, SchemaError):
        raise ChatRankedCandidateReadError() from None


def build_chat_ranked_candidate_read_request(
    *,
    actor_id: str,
    scope: ChatRagScope,
    arguments: ChatSearchArguments,
    candidates: tuple[ChatRankedCandidateKey, ...],
) -> ChatRankedCandidateReadRequest:
    try:
        body = dict(
            schema_version="chat-ranked-candidate-read-request/1.0",
            operation="READ_CHAT_RANKED_CANDIDATES",
            actor_id=actor_id,
            scope=raw_similarity_contract_value(scope),
            arguments=raw_similarity_contract_value(arguments),
            candidates=raw_similarity_contract_value(candidates),
        )
        return parse_chat_ranked_candidate_read_request(
            body | {"request_sha256": content_sha256(body)}
        )
    except (ValueError, TypeError, SchemaError):
        raise ChatRankedCandidateReadError() from None


def chat_ranked_candidate_keys(
    context: PrivateChatSimilarityContext,
) -> tuple[ChatRankedCandidateKey, ...]:
    """Project an already admitted observation; these keys do not reproduce that grant."""
    try:
        context = PrivateChatSimilarityContext.model_validate(
            raw_similarity_contract_value(context)
        )
        if context.status not in {"READY", "PARTIAL", "EMPTY"} or context.query_execution is None:
            raise ChatRankedCandidateReadError()
        return tuple(
            ChatRankedCandidateKey(
                item_id=c.source.item_id,
                item_revision_id=c.source.item_revision_id,
                source_class=c.source.source_class,
                component_artifact_id=c.source.artifact_member.artifact_id,
                component_artifact_revision_id=c.source.artifact_member.artifact_revision_id,
                component_sha256=c.source.artifact_member.sha256,
            )
            for c in context.candidates
        )
    except (ValueError, TypeError, SchemaError):
        raise ChatRankedCandidateReadError() from None


def validate_chat_ranked_candidate_read_reply(
    request: ChatRankedCandidateReadRequest, value: object
) -> ChatRankedCandidateReadReply:
    try:
        request = parse_chat_ranked_candidate_read_request(request)
        reply = ChatRankedCandidateReadReply.model_validate(raw_similarity_contract_value(value))
        if reply.request_sha256 != request.request_sha256 or (
            reply.status != "FAILED" and reply.scope != request.scope
        ):
            raise ChatRankedCandidateReadError()
        offered = {key.item_revision_id: (rank, key) for rank, key in enumerate(request.candidates)}
        ranks = []
        for card in reply.cards:
            pair = offered.get(card.item.item_revision_id)
            if pair is None or pair[1].item_id != card.item.item_id:
                raise ChatRankedCandidateReadError()
            if request.arguments.source != "ALL" and card.source_kind != request.arguments.source:
                raise ChatRankedCandidateReadError()
            ranks.append(pair[0])
        if ranks != sorted(set(ranks)):
            raise ChatRankedCandidateReadError()
        if reply.truncated and len(reply.cards) >= len(request.candidates):
            raise ChatRankedCandidateReadError()
        return reply
    except (ValueError, TypeError, SchemaError):
        raise ChatRankedCandidateReadError() from None


def failed_chat_ranked_candidate_read_reply(
    request: ChatRankedCandidateReadRequest,
    code: ChatPrivateQueryScopeErrorCode,
) -> ChatRankedCandidateReadReply:
    return validate_chat_ranked_candidate_read_reply(
        request,
        dict(
            schema_version="chat-ranked-candidate-read-reply/1.0",
            request_sha256=request.request_sha256,
            status="FAILED",
            scope=None,
            cards=[],
            truncated=False,
            error_code=code,
        ),
    )
