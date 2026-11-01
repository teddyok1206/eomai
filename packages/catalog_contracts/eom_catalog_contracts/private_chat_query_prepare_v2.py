"""Closed successor wire for common context2; origin metadata is never authority.

Legacy wire1 remains immutable and is selected only by its exact discriminator.
The existing reply budget already carries the bounded context and its envelope.
"""

from __future__ import annotations

from typing import ClassVar, Literal, Self

from eom_identifiers import content_sha256
from jsonschema.exceptions import ValidationError as SchemaError
from pydantic import ConfigDict, Field, model_validator

from eom_catalog_contracts.embedding_reference_query import (
    raw_similarity_contract_value,
    similarity_contract_document,
)
from eom_catalog_contracts.knowledge import KnowledgeGraphSnapshotPointer
from eom_catalog_contracts.models import FrozenModel, Sha256
from eom_catalog_contracts.private_chat_query_prepare import (
    PRIVATE_CHAT_PREPARE_REPLY_BYTES,
    PRIVATE_CHAT_PREPARE_REQUEST_BYTES,
    PrivateChatQueryPrepareAction,
    PrivateChatQueryPrepareErrorCode,
    PrivateChatQueryPrepareProtocolError,
    PrivateChatQueryPrepareReply,
    PrivateChatQueryPrepareRequest,
    parse_private_chat_query_prepare_request,
    private_chat_query_context_request_id,
    validate_private_chat_query_prepare_reply,
)
from eom_catalog_contracts.private_chat_query_read import ChatPrivateQueryOrigin
from eom_catalog_contracts.private_chat_similarity_v2 import PrivateChatSimilarityContextV2


class _CommonPrepareValue(FrozenModel):
    model_config = ConfigDict(revalidate_instances="always", hide_input_in_errors=True)
    maximum_bytes: ClassVar[int] = PRIVATE_CHAT_PREPARE_REPLY_BYTES

    @model_validator(mode="before")
    @classmethod
    def schema_first(cls, value: object) -> object:
        return similarity_contract_document(
            value, "system-rag-private-chat-query-prepare-v2", cls.maximum_bytes
        )


class PrivateChatQueryPrepareRequestV2(_CommonPrepareValue):
    maximum_bytes = PRIVATE_CHAT_PREPARE_REQUEST_BYTES
    schema_version: Literal["system-rag-private-chat-query-prepare-request/2.0"]
    action: PrivateChatQueryPrepareAction
    request_id: str = Field(pattern=r"^chatqueryprepare_[0-9a-f]{32}$")
    origin: ChatPrivateQueryOrigin
    graph_snapshot: KnowledgeGraphSnapshotPointer
    policy_revision_id: str = Field(pattern=r"^accessrev_[0-9a-f]{32}$")
    policy_sha256: Sha256
    request_sha256: Sha256

    @model_validator(mode="after")
    def exact_request(self) -> Self:
        if (
            self.graph_snapshot.manifest_sha256 != self.graph_snapshot.manifest_artifact.sha256
            or self.request_sha256
            != content_sha256(self.model_dump(mode="json", exclude={"request_sha256"}))
        ):
            raise ValueError("PRIVATE_CHAT_QUERY_REQUEST_INVALID")
        return self


class PrivateChatQueryPrepareReplyV2(_CommonPrepareValue):
    schema_version: Literal["system-rag-private-chat-query-prepare-reply/2.0"]
    action: PrivateChatQueryPrepareAction
    request_id: str = Field(pattern=r"^chatqueryprepare_[0-9a-f]{32}$")
    request_sha256: Sha256
    status: Literal["PENDING", "READY", "UNAVAILABLE", "FAILED"]
    workflow_id: str | None = Field(pattern=r"^workflow_[0-9a-f]{32}$")
    context: PrivateChatSimilarityContextV2 | None
    error_code: PrivateChatQueryPrepareErrorCode | None


type SupportedPrivateChatQueryPrepareRequest = (
    PrivateChatQueryPrepareRequest | PrivateChatQueryPrepareRequestV2
)
type SupportedPrivateChatQueryPrepareReply = (
    PrivateChatQueryPrepareReply | PrivateChatQueryPrepareReplyV2
)


def parse_supported_private_chat_query_prepare_request(
    value: object,
) -> SupportedPrivateChatQueryPrepareRequest:
    try:
        document = raw_similarity_contract_value(value)
        if isinstance(document, dict):
            version = document.get("schema_version")
            if version == "system-rag-private-chat-query-prepare-request/1.0":
                return parse_private_chat_query_prepare_request(document)
            if version == "system-rag-private-chat-query-prepare-request/2.0":
                return PrivateChatQueryPrepareRequestV2.model_validate(document)
        raise ValueError("unknown private prepare family")
    except (ValueError, TypeError, SchemaError):
        raise PrivateChatQueryPrepareProtocolError("PRIVATE_CHAT_QUERY_REQUEST_INVALID") from None


def validate_supported_private_chat_query_prepare_reply(
    request: SupportedPrivateChatQueryPrepareRequest, value: object
) -> SupportedPrivateChatQueryPrepareReply:
    try:
        request = parse_supported_private_chat_query_prepare_request(request)
        if isinstance(request, PrivateChatQueryPrepareRequest):
            return validate_private_chat_query_prepare_reply(request, value)
        reply = PrivateChatQueryPrepareReplyV2.model_validate(raw_similarity_contract_value(value))
        if (reply.action, reply.request_id, reply.request_sha256) != (
            request.action,
            request.request_id,
            request.request_sha256,
        ):
            raise ValueError("private prepare correlation differs")
        if reply.context is not None:
            scope = reply.context.request
            if (
                scope.request_id != private_chat_query_context_request_id(request.origin)
                or scope.query_basis != request.origin.basis
                or scope.graph_snapshot != request.graph_snapshot
                or scope.policy_revision_id != request.policy_revision_id
                or scope.policy_sha256 != request.policy_sha256
            ):
                raise ValueError("private prepare scope differs")
        return reply
    except (ValueError, TypeError, SchemaError):
        raise PrivateChatQueryPrepareProtocolError("PRIVATE_CHAT_QUERY_REPLY_INVALID") from None
