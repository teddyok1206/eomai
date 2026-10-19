"""Pointer-only native preparation messages, never identity, source or execution authority."""

from __future__ import annotations

from typing import Annotated, ClassVar, Literal

from eom_identifiers import content_sha256
from pydantic import ConfigDict, Field, model_validator

from eom_catalog_contracts.embedding_reference_query import (
    raw_similarity_contract_value,
    similarity_contract_document,
)
from eom_catalog_contracts.knowledge import KnowledgeGraphSnapshotPointer
from eom_catalog_contracts.models import FrozenModel, Sha256
from eom_catalog_contracts.similarity_context import SimilarityFailureCode
from eom_catalog_contracts.similarity_read import CompletedSimilarityQuerySelection

MAX_REFERENCE_QUERY_PREPARE_REQUEST_BYTES = 8192
MAX_REFERENCE_QUERY_PREPARE_REPLY_BYTES = 4096
REFERENCE_QUERY_PREPARE_SOCKET = "/run/eom-reference-query-owner/owner.sock"
type ReferenceQueryPrepareErrorCode = (
    SimilarityFailureCode
    | Literal[
        "REFERENCE_QUERY_PREPARE_REQUEST_INVALID",
        "REFERENCE_QUERY_PREPARE_UNAVAILABLE",
        "REFERENCE_QUERY_PREPARE_CONFLICT",
        "REFERENCE_QUERY_EXECUTION_FAILED",
        "ANCHOR_REPORT_MISSING",
        "INDEX_NOT_PREPARED",
    ]
)


class _PrepareValue(FrozenModel):
    model_config = ConfigDict(revalidate_instances="always")
    maximum_bytes: ClassVar[int] = MAX_REFERENCE_QUERY_PREPARE_REPLY_BYTES
    contract_schema: ClassVar[str] = "system-rag-reference-query-prepare"

    @model_validator(mode="before")
    @classmethod
    def schema_first(cls, value: object) -> object:
        return similarity_contract_document(
            value,
            cls.contract_schema,
            cls.maximum_bytes,
        )


class ReferenceQueryPrepareRequest(_PrepareValue):
    maximum_bytes = MAX_REFERENCE_QUERY_PREPARE_REQUEST_BYTES
    schema_version: Literal["system-rag-reference-query-prepare-request/1.0"]
    operation: Literal["PREPARE_REFERENCE_QUERY"]
    operation_id: str = Field(pattern=r"^queryprepare_[0-9a-f]{32}$")
    idempotency_key: str = Field(min_length=8, max_length=128, pattern=r"^[A-Za-z0-9_.:-]{8,128}$")
    source_item_revision_id: str = Field(pattern=r"^itemrev_[0-9a-f]{32}$")
    graph_snapshot: KnowledgeGraphSnapshotPointer
    policy_revision_id: str = Field(pattern=r"^accessrev_[0-9a-f]{32}$")
    policy_sha256: Sha256
    request_sha256: Sha256

    @model_validator(mode="after")
    def exact_request(self) -> ReferenceQueryPrepareRequest:
        if (
            self.graph_snapshot.manifest_sha256 != self.graph_snapshot.manifest_artifact.sha256
            or self.request_sha256
            != content_sha256(self.model_dump(mode="json", exclude={"request_sha256"}))
        ):
            raise ValueError("REFERENCE_QUERY_PREPARE_REQUEST_INVALID")
        return self


class ReferenceQueryPrepareRequestV11(ReferenceQueryPrepareRequest):
    """Explicit reference purpose only; does not grant source, identity or execution access."""

    contract_schema: ClassVar[str] = "system-rag-reference-query-prepare-v1.1"
    schema_version: Literal["system-rag-reference-query-prepare-request/1.1"]  # type: ignore[assignment]
    consumer_purpose: Literal["ITEM_AUTHORING", "ITEM_REVIEW"]


class ReferenceQueryPrepareRequestV2(_PrepareValue):
    """Explicit mixed runtime selection, not authority or an old request subtype."""

    maximum_bytes = MAX_REFERENCE_QUERY_PREPARE_REQUEST_BYTES
    contract_schema: ClassVar[str] = "system-rag-reference-query-prepare-v2"
    schema_version: Literal["system-rag-reference-query-prepare-request/2.0"]
    operation: Literal["PREPARE_REFERENCE_QUERY"]
    operation_id: str = Field(pattern=r"^queryprepare_[0-9a-f]{32}$")
    idempotency_key: str = Field(min_length=8, max_length=128, pattern=r"^[A-Za-z0-9_.:-]{8,128}$")
    source_item_revision_id: str = Field(pattern=r"^itemrev_[0-9a-f]{32}$")
    graph_snapshot: KnowledgeGraphSnapshotPointer
    policy_revision_id: str = Field(pattern=r"^accessrev_[0-9a-f]{32}$")
    policy_sha256: Sha256
    consumer_purpose: Literal["PAST_EXAM_VARIATION", "ITEM_AUTHORING", "ITEM_REVIEW"]
    request_sha256: Sha256

    @model_validator(mode="after")
    def exact_request(self) -> ReferenceQueryPrepareRequestV2:
        if self.graph_snapshot.manifest_sha256 != self.graph_snapshot.manifest_artifact.sha256 or (
            self.request_sha256
            != content_sha256(self.model_dump(mode="json", exclude={"request_sha256"}))
        ):
            raise ValueError("REFERENCE_QUERY_PREPARE_REQUEST_INVALID")
        return self


type SupportedReferenceQueryPrepareRequest = (
    ReferenceQueryPrepareRequest | ReferenceQueryPrepareRequestV11 | ReferenceQueryPrepareRequestV2
)


def parse_supported_reference_query_prepare_request(
    value: object,
) -> SupportedReferenceQueryPrepareRequest:
    document = raw_similarity_contract_value(value)
    if isinstance(document, dict):
        version = document.get("schema_version")
        if version == "system-rag-reference-query-prepare-request/1.0":
            return ReferenceQueryPrepareRequest.model_validate(document)
        if version == "system-rag-reference-query-prepare-request/1.1":
            return ReferenceQueryPrepareRequestV11.model_validate(document)
        if version == "system-rag-reference-query-prepare-request/2.0":
            return ReferenceQueryPrepareRequestV2.model_validate(document)
    raise ValueError("REFERENCE_QUERY_PREPARE_REQUEST_INVALID")


class ReferenceQueryPrepareReply(_PrepareValue):
    schema_version: Literal["system-rag-reference-query-prepare-reply/1.0"]
    operation: Literal["PREPARE_REFERENCE_QUERY"]
    operation_id: str | None = Field(pattern=r"^queryprepare_[0-9a-f]{32}$")
    request_sha256: Sha256 | None
    status: Literal["PENDING", "READY", "UNAVAILABLE", "FAILED"]
    workflow_id: str | None = Field(pattern=r"^workflow_[0-9a-f]{32}$")
    selection: CompletedSimilarityQuerySelection | None
    error_code: ReferenceQueryPrepareErrorCode | None

    @model_validator(mode="after")
    def exact_target(self) -> ReferenceQueryPrepareReply:
        if self.selection is not None and self.workflow_id != self.selection.workflow_id:
            raise ValueError("REFERENCE_QUERY_PREPARE_REPLY_BINDING_INVALID")
        return self


class ReferenceQueryPrepareReplyV2(_PrepareValue):
    contract_schema: ClassVar[str] = "system-rag-reference-query-prepare-v2"
    schema_version: Literal["system-rag-reference-query-prepare-reply/2.0"]
    operation: Literal["PREPARE_REFERENCE_QUERY"]
    operation_id: str | None = Field(pattern=r"^queryprepare_[0-9a-f]{32}$")
    request_sha256: Sha256 | None
    status: Literal["PENDING", "READY", "UNAVAILABLE", "FAILED"]
    workflow_id: str | None = Field(pattern=r"^workflow_[0-9a-f]{32}$")
    selection: CompletedSimilarityQuerySelection | None
    error_code: ReferenceQueryPrepareErrorCode | None

    @model_validator(mode="after")
    def exact_target(self) -> ReferenceQueryPrepareReplyV2:
        if self.selection is not None and self.workflow_id != self.selection.workflow_id:
            raise ValueError("REFERENCE_QUERY_PREPARE_REPLY_BINDING_INVALID")
        return self


type SupportedReferenceQueryPrepareReply = Annotated[
    ReferenceQueryPrepareReply | ReferenceQueryPrepareReplyV2,
    Field(discriminator="schema_version"),
]


def parse_supported_reference_query_prepare_reply(
    value: object,
) -> SupportedReferenceQueryPrepareReply:
    raw = raw_similarity_contract_value(value)
    if (
        isinstance(raw, dict)
        and raw.get("schema_version") == "system-rag-reference-query-prepare-reply/2.0"
    ):
        return ReferenceQueryPrepareReplyV2.model_validate(raw)
    return ReferenceQueryPrepareReply.model_validate(raw)


def validate_supported_reference_query_prepare_reply(
    request: SupportedReferenceQueryPrepareRequest, reply: SupportedReferenceQueryPrepareReply
) -> None:
    request = parse_supported_reference_query_prepare_request(request)
    reply = parse_supported_reference_query_prepare_reply(reply)
    if isinstance(request, ReferenceQueryPrepareRequestV2) != isinstance(
        reply, ReferenceQueryPrepareReplyV2
    ) or (
        reply.operation_id != request.operation_id or reply.request_sha256 != request.request_sha256
    ):
        raise ValueError("REFERENCE_QUERY_PREPARE_REPLY_BINDING_INVALID")


def validate_reference_query_prepare_reply(
    request: SupportedReferenceQueryPrepareRequest,
    reply: ReferenceQueryPrepareReply,
) -> None:
    request = parse_supported_reference_query_prepare_request(request)
    if isinstance(request, ReferenceQueryPrepareRequestV2):
        raise ValueError("REFERENCE_QUERY_PREPARE_REPLY_BINDING_INVALID")
    reply = ReferenceQueryPrepareReply.model_validate(reply)
    if reply.operation_id != request.operation_id or reply.request_sha256 != request.request_sha256:
        raise ValueError("REFERENCE_QUERY_PREPARE_REPLY_BINDING_INVALID")
