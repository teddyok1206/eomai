"""Pointer-only native preparation messages, never identity, source or execution authority."""

from __future__ import annotations

from typing import ClassVar, Literal

from eom_identifiers import content_sha256
from pydantic import ConfigDict, Field, model_validator

from eom_catalog_contracts.embedding_reference_query import similarity_contract_document
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

    @model_validator(mode="before")
    @classmethod
    def schema_first(cls, value: object) -> object:
        return similarity_contract_document(
            value,
            "system-rag-reference-query-prepare",
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


def validate_reference_query_prepare_reply(
    request: ReferenceQueryPrepareRequest,
    reply: ReferenceQueryPrepareReply,
) -> None:
    request = ReferenceQueryPrepareRequest.model_validate(request)
    reply = ReferenceQueryPrepareReply.model_validate(reply)
    if reply.operation_id != request.operation_id or reply.request_sha256 != request.request_sha256:
        raise ValueError("REFERENCE_QUERY_PREPARE_REPLY_BINDING_INVALID")
