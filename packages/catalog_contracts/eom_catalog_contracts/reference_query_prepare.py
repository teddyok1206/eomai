"""Pointer-only native preparation messages, never identity, source or execution authority."""

from __future__ import annotations

from typing import Annotated, ClassVar, Literal

from eom_identifiers import content_sha256
from eom_protocol.artifact_members import ArtifactMemberPointer
from pydantic import ConfigDict, Field, model_validator

from eom_catalog_contracts.embedding_reference_query import (
    raw_similarity_contract_value,
    similarity_contract_document,
)
from eom_catalog_contracts.knowledge import KnowledgeGraphSnapshotPointer
from eom_catalog_contracts.models import FrozenModel, Sha256
from eom_catalog_contracts.public_solution_similarity import PublicSolutionSimilarityPurpose
from eom_catalog_contracts.similarity_context import SimilarityFailureCode
from eom_catalog_contracts.similarity_read import CompletedSimilarityQuerySelection

MAX_REFERENCE_QUERY_PREPARE_REQUEST_BYTES = 8192
MAX_REFERENCE_QUERY_PREPARE_REPLY_BYTES = 4096
# Transport successors do not change the old per-contract byte budgets.
MAX_ROUTED_QUERY_PREPARE_REQUEST_BYTES = 128 * 1024
MAX_ROUTED_QUERY_PREPARE_REPLY_BYTES = 32 * 1024
MAX_ROUTED_REFERENCE_QUERIES = 16
MAX_PUBLIC_REFERENCE_QUERIES = 32
REFERENCE_QUERY_PREPARE_SOCKET = "/run/eom-reference-query-owner/owner.sock"
# Response work may validate both device indexes. Keep this below the BFF's
# 240-second HTTP budget; authentication capture retains its separate short limit.
REFERENCE_QUERY_PREPARE_RESPONSE_SECONDS = 210.0
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


type SingleReferenceQueryPrepareRequest = (
    ReferenceQueryPrepareRequest | ReferenceQueryPrepareRequestV11 | ReferenceQueryPrepareRequestV2
)


class ReferenceQueryPrepareRequestV3(_PrepareValue):
    maximum_bytes = MAX_ROUTED_QUERY_PREPARE_REQUEST_BYTES
    contract_schema: ClassVar[str] = "system-rag-reference-query-prepare-v3"
    schema_version: Literal["system-rag-reference-query-prepare-request/3.0"]
    operation: Literal["PREPARE_REFERENCE_QUERY"]
    operation_id: str = Field(pattern=r"^queryprepare_[0-9a-f]{32}$")
    idempotency_key: str = Field(min_length=8, max_length=128, pattern=r"^[A-Za-z0-9_.:-]{8,128}$")
    requests: tuple[
        Annotated[SingleReferenceQueryPrepareRequest, Field(discriminator="schema_version")], ...
    ] = Field(min_length=1, max_length=MAX_ROUTED_REFERENCE_QUERIES)
    request_sha256: Sha256

    @model_validator(mode="after")
    def exact_batch(self) -> ReferenceQueryPrepareRequestV3:
        first = self.requests[0]
        if self.request_sha256 != content_sha256(
            self.model_dump(mode="json", exclude={"request_sha256"})
        ) or len({r.source_item_revision_id for r in self.requests}) != len(self.requests):
            raise ValueError("REFERENCE_QUERY_PREPARE_REQUEST_INVALID")
        first_purpose = getattr(first, "consumer_purpose", "PAST_EXAM_VARIATION")
        if any(
            r.graph_snapshot != first.graph_snapshot
            or r.policy_revision_id != first.policy_revision_id
            or r.policy_sha256 != first.policy_sha256
            or isinstance(r, ReferenceQueryPrepareRequestV2)
            != isinstance(first, ReferenceQueryPrepareRequestV2)
            or getattr(r, "consumer_purpose", "PAST_EXAM_VARIATION") != first_purpose
            for r in self.requests
        ):
            raise ValueError("REFERENCE_QUERY_PREPARE_REQUEST_INVALID")
        return self


class ReferenceQueryPrepareRequestV4(_PrepareValue):
    """One bounded public-report source scope, never an authority or runtime selector."""

    maximum_bytes = MAX_ROUTED_QUERY_PREPARE_REQUEST_BYTES
    contract_schema: ClassVar[str] = "system-rag-reference-query-prepare-v4"
    schema_version: Literal["system-rag-reference-query-prepare-request/4.0"]
    operation: Literal["PREPARE_REFERENCE_QUERY"]
    operation_id: str = Field(pattern=r"^queryprepare_[0-9a-f]{32}$")
    idempotency_key: str = Field(min_length=8, max_length=128, pattern=r"^[A-Za-z0-9_.:-]{8,128}$")
    source_item_revision_ids: tuple[str, ...] = Field(
        min_length=1, max_length=MAX_PUBLIC_REFERENCE_QUERIES
    )
    graph_snapshot: KnowledgeGraphSnapshotPointer
    policy_revision_id: str = Field(pattern=r"^accessrev_[0-9a-f]{32}$")
    policy_sha256: Sha256
    consumer_purpose: PublicSolutionSimilarityPurpose
    top_k: int = Field(strict=True, ge=1, le=64)
    request_sha256: Sha256

    @model_validator(mode="after")
    def exact_scope(self) -> ReferenceQueryPrepareRequestV4:
        if (
            len(set(self.source_item_revision_ids)) != len(self.source_item_revision_ids)
            or self.graph_snapshot.manifest_sha256 != self.graph_snapshot.manifest_artifact.sha256
            or self.request_sha256
            != content_sha256(self.model_dump(mode="json", exclude={"request_sha256"}))
        ):
            raise ValueError("REFERENCE_QUERY_PREPARE_REQUEST_INVALID")
        return self


type SupportedReferenceQueryPrepareRequest = (
    SingleReferenceQueryPrepareRequest
    | ReferenceQueryPrepareRequestV3
    | ReferenceQueryPrepareRequestV4
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
        if version == "system-rag-reference-query-prepare-request/3.0":
            return ReferenceQueryPrepareRequestV3.model_validate(document)
        if version == "system-rag-reference-query-prepare-request/4.0":
            return ReferenceQueryPrepareRequestV4.model_validate(document)
    raise ValueError("REFERENCE_QUERY_PREPARE_REQUEST_INVALID")


def parse_single_reference_query_prepare_request(
    value: object,
) -> SingleReferenceQueryPrepareRequest:
    parsed = parse_supported_reference_query_prepare_request(value)
    if isinstance(parsed, ReferenceQueryPrepareRequestV3 | ReferenceQueryPrepareRequestV4):
        raise ValueError("REFERENCE_QUERY_PREPARE_REQUEST_INVALID")
    return parsed


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


class RoutedReferenceQueryChild(_PrepareValue):
    # This nested shape is validated with the entire reply before construction.
    ordinal: int = Field(strict=True, ge=0, lt=MAX_ROUTED_REFERENCE_QUERIES)
    source_item_revision_id: str = Field(pattern=r"^itemrev_[0-9a-f]{32}$")
    workflow_id: str | None = Field(pattern=r"^workflow_[0-9a-f]{32}$")
    state: Literal["PENDING", "COMPLETED", "FAILED"]
    selection: CompletedSimilarityQuerySelection | None

    @model_validator(mode="before")
    @classmethod
    def schema_first(cls, value: object) -> object:
        return raw_similarity_contract_value(value)

    @model_validator(mode="after")
    def completed_pointer(self) -> RoutedReferenceQueryChild:
        if (
            (self.state == "COMPLETED") != (self.selection is not None)
            or (self.selection is not None and self.workflow_id != self.selection.workflow_id)
            or (self.state == "FAILED" and self.workflow_id is None)
        ):
            raise ValueError("REFERENCE_QUERY_PREPARE_REPLY_BINDING_INVALID")
        return self


class ReferenceQueryPrepareReplyV3(_PrepareValue):
    maximum_bytes = MAX_ROUTED_QUERY_PREPARE_REPLY_BYTES
    contract_schema: ClassVar[str] = "system-rag-reference-query-prepare-v3"
    schema_version: Literal["system-rag-reference-query-prepare-reply/3.0"]
    operation: Literal["PREPARE_REFERENCE_QUERY"]
    operation_id: str | None = Field(pattern=r"^queryprepare_[0-9a-f]{32}$")
    request_sha256: Sha256 | None
    request_schema_version: (
        Literal[
            "system-rag-reference-query-prepare-request/1.0",
            "system-rag-reference-query-prepare-request/1.1",
            "system-rag-reference-query-prepare-request/2.0",
            "system-rag-reference-query-prepare-request/3.0",
        ]
        | None
    )
    status: Literal["PENDING", "READY", "UNAVAILABLE", "FAILED"]
    preparation: ArtifactMemberPointer | None
    parent_request_sha256: Sha256 | None
    device: Literal["CPU", "CUDA"] | None
    children: tuple[RoutedReferenceQueryChild, ...] = Field(max_length=MAX_ROUTED_REFERENCE_QUERIES)
    workflow_id: str | None = Field(pattern=r"^workflow_[0-9a-f]{32}$")
    selection: CompletedSimilarityQuerySelection | None
    error_code: ReferenceQueryPrepareErrorCode | None

    @model_validator(mode="after")
    def original_order_and_summary(self) -> ReferenceQueryPrepareReplyV3:
        _validate_routed_reply_summary(self)
        return self


class PublicRoutedReferenceQueryChild(RoutedReferenceQueryChild):
    ordinal: int = Field(strict=True, ge=0, lt=MAX_PUBLIC_REFERENCE_QUERIES)


class ReferenceQueryPrepareReplyV4(_PrepareValue):
    maximum_bytes = MAX_ROUTED_QUERY_PREPARE_REPLY_BYTES
    contract_schema: ClassVar[str] = "system-rag-reference-query-prepare-v4"
    schema_version: Literal["system-rag-reference-query-prepare-reply/4.0"]
    operation: Literal["PREPARE_REFERENCE_QUERY"]
    operation_id: str | None = Field(pattern=r"^queryprepare_[0-9a-f]{32}$")
    request_sha256: Sha256 | None
    request_schema_version: Literal["system-rag-reference-query-prepare-request/4.0"] | None
    status: Literal["PENDING", "READY", "UNAVAILABLE", "FAILED"]
    preparation: ArtifactMemberPointer | None
    parent_request_sha256: Sha256 | None
    device: Literal["CPU", "CUDA"] | None
    children: tuple[PublicRoutedReferenceQueryChild, ...] = Field(
        max_length=MAX_PUBLIC_REFERENCE_QUERIES
    )
    workflow_id: str | None = Field(pattern=r"^workflow_[0-9a-f]{32}$")
    selection: CompletedSimilarityQuerySelection | None
    error_code: ReferenceQueryPrepareErrorCode | None

    @model_validator(mode="after")
    def original_order_and_summary(self) -> ReferenceQueryPrepareReplyV4:
        _validate_routed_reply_summary(self)
        return self


def _validate_routed_reply_summary(
    self: ReferenceQueryPrepareReplyV3 | ReferenceQueryPrepareReplyV4,
) -> None:
    missing_binding = (
        self.operation_id is None,
        self.request_sha256 is None,
        self.request_schema_version is None,
    )
    if any(missing_binding) and not all(missing_binding):
        raise ValueError("REFERENCE_QUERY_PREPARE_REPLY_BINDING_INVALID")
    if tuple(c.ordinal for c in self.children) != tuple(range(len(self.children))) or (
        len({c.source_item_revision_id for c in self.children}) != len(self.children)
    ):
        raise ValueError("REFERENCE_QUERY_PREPARE_REPLY_BINDING_INVALID")
    workflow_ids = [c.workflow_id for c in self.children if c.workflow_id is not None]
    if len(set(workflow_ids)) != len(workflow_ids):
        raise ValueError("REFERENCE_QUERY_PREPARE_REPLY_BINDING_INVALID")
    if (
        bool(self.preparation) != bool(self.parent_request_sha256)
        or (self.children and self.preparation is None)
        or (self.device is None and any(c.workflow_id is not None for c in self.children))
    ):
        raise ValueError("REFERENCE_QUERY_PREPARE_REPLY_BINDING_INVALID")
    expected_workflow = self.children[0].workflow_id if len(self.children) == 1 else None
    expected_selection = (
        self.children[0].selection if len(self.children) == 1 and self.status == "READY" else None
    )
    if (
        self.workflow_id != expected_workflow
        or self.selection != expected_selection
        or (self.status == "PENDING" and all(c.state == "COMPLETED" for c in self.children))
        or (self.status == "PENDING" and any(c.state == "FAILED" for c in self.children))
    ):
        raise ValueError("REFERENCE_QUERY_PREPARE_REPLY_BINDING_INVALID")


def routed_reference_query_error_reply(
    request: SupportedReferenceQueryPrepareRequest | None,
    *,
    status: str = "FAILED",
    error_code: str = "REFERENCE_QUERY_PREPARE_UNAVAILABLE",
) -> ReferenceQueryPrepareReplyV3 | ReferenceQueryPrepareReplyV4:
    """Closed failure value only; no retry, source resolution or authority side effect."""
    public = isinstance(request, ReferenceQueryPrepareRequestV4)
    reply_type = ReferenceQueryPrepareReplyV4 if public else ReferenceQueryPrepareReplyV3
    return reply_type.model_validate(
        dict(
            schema_version="system-rag-reference-query-prepare-reply/4.0"
            if public
            else "system-rag-reference-query-prepare-reply/3.0",
            operation="PREPARE_REFERENCE_QUERY",
            operation_id=None if request is None else request.operation_id,
            request_sha256=None if request is None else request.request_sha256,
            request_schema_version=None if request is None else request.schema_version,
            status=status,
            preparation=None,
            parent_request_sha256=None,
            device=None,
            children=[],
            workflow_id=None,
            selection=None,
            error_code=error_code,
        )
    )


type SupportedReferenceQueryPrepareReply = Annotated[
    ReferenceQueryPrepareReply
    | ReferenceQueryPrepareReplyV2
    | ReferenceQueryPrepareReplyV3
    | ReferenceQueryPrepareReplyV4,
    Field(discriminator="schema_version"),
]


def parse_supported_reference_query_prepare_reply(
    value: object,
) -> SupportedReferenceQueryPrepareReply:
    raw = raw_similarity_contract_value(value)
    if isinstance(raw, dict) and raw.get("schema_version") == (
        "system-rag-reference-query-prepare-reply/4.0"
    ):
        return ReferenceQueryPrepareReplyV4.model_validate(raw)
    if (
        isinstance(raw, dict)
        and raw.get("schema_version") == "system-rag-reference-query-prepare-reply/3.0"
    ):
        return ReferenceQueryPrepareReplyV3.model_validate(raw)
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
    if isinstance(request, ReferenceQueryPrepareRequestV4):
        if (
            not isinstance(reply, ReferenceQueryPrepareReplyV4)
            or reply.operation_id != request.operation_id
            or reply.request_sha256 != request.request_sha256
            or reply.request_schema_version != request.schema_version
            or (
                reply.children
                and tuple(c.source_item_revision_id for c in reply.children)
                != request.source_item_revision_ids
            )
        ):
            raise ValueError("REFERENCE_QUERY_PREPARE_REPLY_BINDING_INVALID")
        return
    if isinstance(reply, ReferenceQueryPrepareReplyV4):
        raise ValueError("REFERENCE_QUERY_PREPARE_REPLY_BINDING_INVALID")
    if isinstance(reply, ReferenceQueryPrepareReplyV3):
        singles = (
            request.requests if isinstance(request, ReferenceQueryPrepareRequestV3) else (request,)
        )
        if (
            reply.operation_id != request.operation_id
            or reply.request_sha256 != request.request_sha256
            or reply.request_schema_version != request.schema_version
            or (
                reply.children
                and tuple(c.source_item_revision_id for c in reply.children)
                != tuple(r.source_item_revision_id for r in singles)
            )
        ):
            raise ValueError("REFERENCE_QUERY_PREPARE_REPLY_BINDING_INVALID")
        return
    if isinstance(request, ReferenceQueryPrepareRequestV3):
        raise ValueError("REFERENCE_QUERY_PREPARE_REPLY_BINDING_INVALID")
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
    if isinstance(
        request,
        ReferenceQueryPrepareRequestV2
        | ReferenceQueryPrepareRequestV3
        | ReferenceQueryPrepareRequestV4,
    ):
        raise ValueError("REFERENCE_QUERY_PREPARE_REPLY_BINDING_INVALID")
    reply = ReferenceQueryPrepareReply.model_validate(reply)
    if reply.operation_id != request.operation_id or reply.request_sha256 != request.request_sha256:
        raise ValueError("REFERENCE_QUERY_PREPARE_REPLY_BINDING_INVALID")
