"""Owner-only original Chat QUERY prepare/read; metadata never conveys authority."""

from __future__ import annotations

from typing import ClassVar, Literal

from eom_identifiers import content_sha256
from jsonschema.exceptions import ValidationError as SchemaError
from pydantic import ConfigDict, Field, model_validator

from eom_catalog_contracts.embedding_reference_query import (
    raw_similarity_contract_value,
    similarity_contract_document,
)
from eom_catalog_contracts.knowledge import KnowledgeGraphSnapshotPointer
from eom_catalog_contracts.models import FrozenModel, Sha256
from eom_catalog_contracts.private_chat_query_read import ChatPrivateQueryOrigin
from eom_catalog_contracts.private_chat_similarity import PrivateChatSimilarityContext
from eom_catalog_contracts.similarity_context import SimilarityFailureCode

PRIVATE_CHAT_PREPARE_REQUEST_BYTES = 32 * 1024
PRIVATE_CHAT_PREPARE_REPLY_BYTES = 640 * 1024
PRIVATE_CHAT_PREPARE_SOCKET = "/run/eom-private-chat-query-owner/prepare.sock"
type PrivateChatQueryPrepareAction = Literal[
    "PREPARE_PRIVATE_CHAT_QUERY", "READ_PRIVATE_CHAT_QUERY"
]
type PrivateChatQueryPrepareErrorCode = (
    SimilarityFailureCode
    | Literal[
        "PRIVATE_CHAT_QUERY_REQUEST_INVALID",
        "PRIVATE_CHAT_QUERY_UNAVAILABLE",
        "PRIVATE_CHAT_QUERY_NOT_PREPARED",
        "PRIVATE_CHAT_QUERY_EXECUTION_FAILED",
        "INDEX_NOT_PREPARED",
    ]
)


class _PrepareValue(FrozenModel):
    model_config = ConfigDict(revalidate_instances="always")
    maximum_bytes: ClassVar[int] = PRIVATE_CHAT_PREPARE_REPLY_BYTES

    @model_validator(mode="before")
    @classmethod
    def schema_first(cls, value: object) -> object:
        return similarity_contract_document(
            value, "system-rag-private-chat-query-prepare", cls.maximum_bytes
        )


class PrivateChatQueryPrepareRequest(_PrepareValue):
    maximum_bytes = PRIVATE_CHAT_PREPARE_REQUEST_BYTES
    schema_version: Literal["system-rag-private-chat-query-prepare-request/1.0"]
    action: PrivateChatQueryPrepareAction
    request_id: str = Field(pattern=r"^chatqueryprepare_[0-9a-f]{32}$")
    origin: ChatPrivateQueryOrigin
    graph_snapshot: KnowledgeGraphSnapshotPointer
    policy_revision_id: str = Field(pattern=r"^accessrev_[0-9a-f]{32}$")
    policy_sha256: Sha256
    request_sha256: Sha256

    @model_validator(mode="after")
    def exact_request(self) -> PrivateChatQueryPrepareRequest:
        if (
            self.graph_snapshot.manifest_sha256 != self.graph_snapshot.manifest_artifact.sha256
            or self.request_sha256
            != content_sha256(self.model_dump(mode="json", exclude={"request_sha256"}))
        ):
            raise ValueError("PRIVATE_CHAT_QUERY_REQUEST_INVALID")
        return self


class PrivateChatQueryPrepareReply(_PrepareValue):
    schema_version: Literal["system-rag-private-chat-query-prepare-reply/1.0"]
    action: PrivateChatQueryPrepareAction
    request_id: str = Field(pattern=r"^chatqueryprepare_[0-9a-f]{32}$")
    request_sha256: Sha256
    status: Literal["PENDING", "READY", "UNAVAILABLE", "FAILED"]
    workflow_id: str | None = Field(pattern=r"^workflow_[0-9a-f]{32}$")
    context: PrivateChatSimilarityContext | None
    error_code: PrivateChatQueryPrepareErrorCode | None

    @model_validator(mode="after")
    def canonical_ready_only(self) -> PrivateChatQueryPrepareReply:
        if self.context is not None and (
            self.context.status not in {"READY", "PARTIAL", "EMPTY"}
            or self.context.query_execution is None
        ):
            raise ValueError("PRIVATE_CHAT_QUERY_REPLY_INVALID")
        return self


class PrivateChatQueryPrepareProtocolError(ValueError):
    """Only content-free messages leave this boundary, never validator input reprs."""


def private_chat_query_context_request_id(origin: ChatPrivateQueryOrigin) -> str:
    """Stable selection identity only; full original hash remains the unique key."""
    return "similarityrequest_" + origin.origin_sha256.removeprefix("sha256:")[:32]


def parse_private_chat_query_prepare_request(value: object) -> PrivateChatQueryPrepareRequest:
    try:
        return PrivateChatQueryPrepareRequest.model_validate(raw_similarity_contract_value(value))
    except (ValueError, TypeError, SchemaError):
        raise PrivateChatQueryPrepareProtocolError("PRIVATE_CHAT_QUERY_REQUEST_INVALID") from None


def validate_private_chat_query_prepare_reply(
    request: PrivateChatQueryPrepareRequest, value: object
) -> PrivateChatQueryPrepareReply:
    try:
        request = parse_private_chat_query_prepare_request(request)
        reply = PrivateChatQueryPrepareReply.model_validate(raw_similarity_contract_value(value))
        if (reply.action, reply.request_id, reply.request_sha256) != (
            request.action,
            request.request_id,
            request.request_sha256,
        ):
            raise ValueError()
        if reply.context is not None:
            scope = reply.context.request
            if (
                scope.request_id != private_chat_query_context_request_id(request.origin)
                or scope.query_basis != request.origin.basis
                or scope.graph_snapshot != request.graph_snapshot
                or scope.policy_revision_id != request.policy_revision_id
                or scope.policy_sha256 != request.policy_sha256
            ):
                raise ValueError()
        return reply
    except (ValueError, TypeError, SchemaError):
        raise PrivateChatQueryPrepareProtocolError("PRIVATE_CHAT_QUERY_REPLY_INVALID") from None
