"""Private basis1 plus common public document recipe2/index3/4 and numerical QUERY2.

These closed values do not authorize Chat/source access or native execution. The
question is not an approved Item and is never removed as a fictional self anchor.
"""

from __future__ import annotations

from typing import Literal, Self

from eom_identifiers import content_sha256
from eom_protocol.artifact_members import ArtifactMemberPointer
from jsonschema.exceptions import ValidationError as SchemaError
from pydantic import ConfigDict, Field, model_validator

from eom_catalog_contracts.embedding_reference_query import (
    raw_similarity_contract_value,
    similarity_contract_document,
)
from eom_catalog_contracts.inference_transfer_embedding import SHARD_SCHEMA_REF
from eom_catalog_contracts.knowledge import KnowledgeGraphSnapshotPointer
from eom_catalog_contracts.models import FrozenModel, Sha256
from eom_catalog_contracts.private_chat_query_basis import (
    PrivateChatQueryBasis,
    private_chat_query_text_sha256,
)
from eom_catalog_contracts.private_chat_similarity import (
    MAX_PRIVATE_CHAT_SIMILARITY_BYTES,
    PRIVATE_CHAT_LIMITATION_ORDER,
    PrivateChatSimilarityContext,
    PrivateChatSimilarityLimitation,
    PrivateChatSimilarityRequest,
)
from eom_catalog_contracts.public_solution_embedding import PublicSolutionEmbeddingRecipe
from eom_catalog_contracts.public_solution_embedding_index import MAX_PUBLIC_SOLUTION_SOURCES
from eom_catalog_contracts.public_solution_query import (
    PublicSolutionQueryExecutionPointer,
    PublicSolutionQueryInput,
    PublicSolutionQueryResult,
    validate_public_solution_query_result,
)
from eom_catalog_contracts.public_solution_similarity import PublicSolutionSimilarityCandidate
from eom_catalog_contracts.registered_public_solution_similarity import (
    PublicSolutionSimilarityIndexPinV4,
    RegisteredPublicSolutionSimilarityCandidate,
)
from eom_catalog_contracts.similarity_context import SimilarityFailureCode

PRIVATE_CHAT_PUBLIC_CONTEXT_SCHEMA = "system-rag-private-chat-similarity-v2"
type PrivateChatPublicUnavailableReason = Literal[
    "INDEX_NOT_PREPARED", "QUERY_NOT_OFFERED", "INPUT_OVERFLOW"
]


class _PrivatePublicContextValue(FrozenModel):
    model_config = ConfigDict(revalidate_instances="always", hide_input_in_errors=True)

    @model_validator(mode="before")
    @classmethod
    def schema_first(cls, value: object) -> object:
        return similarity_contract_document(
            value, PRIVATE_CHAT_PUBLIC_CONTEXT_SCHEMA, MAX_PRIVATE_CHAT_SIMILARITY_BYTES
        )


class PrivateChatPublicDocumentView(FrozenModel):
    model_config = ConfigDict(revalidate_instances="always", hide_input_in_errors=True)

    view: Literal["CONCRETE_FACETS"] = "CONCRETE_FACETS"
    recipe: PublicSolutionEmbeddingRecipe
    index: PublicSolutionSimilarityIndexPinV4 | None


class PrivateChatSimilarityRequestV2(_PrivatePublicContextValue):
    schema_version: Literal["system-rag-private-chat-similarity-request/2.0"]
    request_id: str = Field(pattern=r"^similarityrequest_[0-9a-f]{32}$")
    consumer_purpose: Literal["GENERAL_CHAT_READ"]
    query_basis: PrivateChatQueryBasis
    graph_snapshot: KnowledgeGraphSnapshotPointer
    policy_revision_id: str = Field(pattern=r"^accessrev_[0-9a-f]{32}$")
    policy_sha256: Sha256
    source_classes: tuple[Literal["APPROVED_ITEM", "PAST_EXAM"], ...] = Field(
        min_length=1, max_length=2
    )
    views: tuple[PrivateChatPublicDocumentView, ...] = Field(min_length=1, max_length=1)
    vector_mode: Literal["REQUIRED"]
    maximum_sources: int = Field(ge=1, le=MAX_PUBLIC_SOLUTION_SOURCES, strict=True)
    top_k: int = Field(ge=1, le=64, strict=True)
    request_sha256: Sha256

    @model_validator(mode="after")
    def exact_scope(self) -> Self:
        if (
            self.source_classes != tuple(sorted(set(self.source_classes)))
            or self.graph_snapshot.manifest_sha256 != self.graph_snapshot.manifest_artifact.sha256
            or self.request_sha256
            != content_sha256(self.model_dump(mode="json", exclude={"request_sha256"}))
        ):
            raise ValueError("PRIVATE_CHAT_PUBLIC_CONTEXT_REQUEST_INVALID")
        return self


class PrivateChatPublicQueryExecutionPointer(PublicSolutionQueryExecutionPointer):
    """Private association around unchanged QUERY2; basis is not a native source claim."""

    basis_sha256: Sha256


class PrivateChatPublicPopulation(FrozenModel):
    model_config = ConfigDict(revalidate_instances="always", hide_input_in_errors=True)

    authorized_source_count: int = Field(ge=0, le=MAX_PUBLIC_SOLUTION_SOURCES, strict=True)
    authorized_source_set_sha256: Sha256
    available_report_count: int = Field(ge=0, le=MAX_PUBLIC_SOLUTION_SOURCES, strict=True)
    available_report_set_sha256: Sha256
    available_binding_count: int = Field(ge=0, le=MAX_PUBLIC_SOLUTION_SOURCES, strict=True)
    binding_set_sha256: Sha256
    scored_count: int = Field(ge=0, le=MAX_PUBLIC_SOLUTION_SOURCES, strict=True)
    truncated: bool = Field(strict=True)

    @model_validator(mode="after")
    def exact_counts(self) -> Self:
        if not (
            self.scored_count
            == self.available_binding_count
            <= self.available_report_count
            <= self.authorized_source_count
        ):
            raise ValueError("PRIVATE_CHAT_PUBLIC_CONTEXT_COVERAGE_INVALID")
        return self


class PrivateChatSimilarityContextV2(_PrivatePublicContextValue):
    schema_version: Literal["system-rag-private-chat-similarity-context/2.0"]
    request: PrivateChatSimilarityRequestV2
    status: Literal["READY", "PARTIAL", "EMPTY", "UNAVAILABLE", "FAILED"]
    population: PrivateChatPublicPopulation | None
    query_execution: PrivateChatPublicQueryExecutionPointer | None
    candidates: tuple[
        PublicSolutionSimilarityCandidate | RegisteredPublicSolutionSimilarityCandidate, ...
    ] = Field(max_length=64)
    limitations: tuple[PrivateChatSimilarityLimitation, ...] = Field(min_length=3, max_length=8)
    unavailable_reason: PrivateChatPublicUnavailableReason | None
    error_code: SimilarityFailureCode | None
    context_sha256: Sha256

    @model_validator(mode="after")
    def exact_context(self) -> Self:
        if (
            not set(PRIVATE_CHAT_LIMITATION_ORDER[:3]).issubset(self.limitations)
            or self.limitations
            != tuple(v for v in PRIVATE_CHAT_LIMITATION_ORDER if v in self.limitations)
            or self.context_sha256
            != content_sha256(self.model_dump(mode="json", exclude={"context_sha256"}))
        ):
            raise ValueError("PRIVATE_CHAT_PUBLIC_CONTEXT_HASH_INVALID")
        index = self.request.views[0].index
        if self.status == "FAILED":
            if (
                self.error_code is None
                or self.population is not None
                or self.query_execution is not None
                or self.candidates
                or self.unavailable_reason is not None
                or self.limitations != PRIVATE_CHAT_LIMITATION_ORDER[:3]
            ):
                raise ValueError("PRIVATE_CHAT_PUBLIC_CONTEXT_FAILURE_DISCLOSURE")
            return self
        if self.status == "UNAVAILABLE":
            if (
                self.error_code is not None
                or self.population is not None
                or self.query_execution is not None
                or self.candidates
                or self.unavailable_reason is None
                or ((index is None) != (self.unavailable_reason == "INDEX_NOT_PREPARED"))
                or self.limitations != (*PRIVATE_CHAT_LIMITATION_ORDER[:3], "VECTOR_NOT_AVAILABLE")
            ):
                raise ValueError("PRIVATE_CHAT_PUBLIC_CONTEXT_UNAVAILABLE_INVALID")
            return self
        population, execution = self.population, self.query_execution
        if (
            index is None
            or population is None
            or self.error_code is not None
            or self.unavailable_reason is not None
            or population.authorized_source_count > self.request.maximum_sources
            or len(self.candidates) != min(self.request.top_k, population.scored_count)
            or ((population.scored_count > 0) != (execution is not None))
        ):
            raise ValueError("PRIVATE_CHAT_PUBLIC_CONTEXT_SCOPE_INVALID")
        flags: set[str] = set(PRIVATE_CHAT_LIMITATION_ORDER[:3])
        for condition, limitation in (
            (
                population.available_report_count < population.authorized_source_count,
                "PARTIAL_REPORT_COVERAGE",
            ),
            (
                population.available_binding_count < population.available_report_count,
                "PARTIAL_VIEW_COVERAGE",
            ),
            (population.truncated, "BOUNDED_SCOPE_TRUNCATED"),
            (not self.candidates, "NO_RELATED_CANDIDATES"),
        ):
            if condition:
                flags.add(limitation)
        if self.limitations != tuple(v for v in PRIVATE_CHAT_LIMITATION_ORDER if v in flags):
            raise ValueError("PRIVATE_CHAT_PUBLIC_CONTEXT_LIMITATIONS_INVALID")
        expected = "EMPTY" if not self.candidates else "PARTIAL" if len(flags) > 3 else "READY"
        if self.status != expected:
            raise ValueError("PRIVATE_CHAT_PUBLIC_CONTEXT_STATUS_INVALID")
        if (
            execution is not None
            and execution.basis_sha256 != self.request.query_basis.basis_sha256
        ):
            raise ValueError("PRIVATE_CHAT_PUBLIC_CONTEXT_EXECUTION_INVALID")
        revisions = {candidate.source.item_revision_id for candidate in self.candidates}
        if len(revisions) != len(self.candidates):
            raise ValueError("PRIVATE_CHAT_PUBLIC_CONTEXT_DUPLICATE_SOURCE")
        for rank, candidate in enumerate(self.candidates, 1):
            observation = candidate.observation
            if (
                execution is None
                or candidate.source.source_class not in self.request.source_classes
                or observation.rank != rank
                or observation.query_row.row_index != 0
                or (
                    observation.query_row.shard_manifest.artifact_id,
                    observation.query_row.shard_manifest.artifact_revision_id,
                )
                != (
                    execution.result_member.artifact_id,
                    execution.result_member.artifact_revision_id,
                )
            ):
                raise ValueError("PRIVATE_CHAT_PUBLIC_CONTEXT_CANDIDATE_INVALID")
        return self


def validate_private_chat_public_query_execution(
    context: PrivateChatSimilarityContextV2,
    request: PublicSolutionQueryInput,
    result: PublicSolutionQueryResult,
    result_member: ArtifactMemberPointer,
    shard_member: ArtifactMemberPointer,
) -> None:
    """Pure exact private parent/common numerical/member closure, never current authority."""
    try:
        _require_private_chat_public_query_execution(
            context, request, result, result_member, shard_member
        )
    except (ValueError, TypeError, AttributeError, SchemaError):
        # Schema errors may embed the full numerical question. Preserve the
        # rejection, not private text in an owner's diagnostic/error receipt.
        raise ValueError("PRIVATE_CHAT_PUBLIC_CONTEXT_NATIVE_ASSOCIATION_INVALID") from None


def _require_private_chat_public_query_execution(
    context: PrivateChatSimilarityContextV2,
    request: PublicSolutionQueryInput,
    result: PublicSolutionQueryResult,
    result_member: ArtifactMemberPointer,
    shard_member: ArtifactMemberPointer,
) -> None:
    context = PrivateChatSimilarityContextV2.model_validate(raw_similarity_contract_value(context))
    request = PublicSolutionQueryInput.model_validate(raw_similarity_contract_value(request))
    result = PublicSolutionQueryResult.model_validate(raw_similarity_contract_value(result))
    result_member = ArtifactMemberPointer.model_validate(
        raw_similarity_contract_value(result_member)
    )
    shard_member = ArtifactMemberPointer.model_validate(raw_similarity_contract_value(shard_member))
    validate_public_solution_query_result(request, result)
    index = context.request.views[0].index
    expected = PrivateChatPublicQueryExecutionPointer(
        job_id=request.job_id,
        query_request_id=request.query_request_id,
        request_sha256=request.request_sha256,
        input_set_sha256=request.input_set_sha256,
        result_member=result_member,
        result_sha256=result.result_sha256,
        basis_sha256=context.request.query_basis.basis_sha256,
    )
    if (
        context.query_execution != expected
        or index is None
        or request.context_request_sha256 != context.request.request_sha256
        or private_chat_query_text_sha256(request.rows[0].text)
        != context.request.query_basis.query_text_sha256
        or request.spaces != index.spaces
        or request.recipe != context.request.views[0].recipe
        or request.rows[0].encoding.storage_partition != index.storage_partition
        or result_member.sha256 != content_sha256(result)
        or shard_member.member_path != "shard.json"
        or shard_member.schema_ref != SHARD_SCHEMA_REF
        or shard_member.media_type != "application/json"
        or shard_member.sha256 != content_sha256(result.shard)
        or (shard_member.artifact_id, shard_member.artifact_revision_id)
        != (result_member.artifact_id, result_member.artifact_revision_id)
        or any(
            candidate.observation.query_row.shard_manifest != shard_member
            or candidate.observation.query_row.encoding_sha256
            != request.rows[0].encoding.encoding_sha256
            for candidate in context.candidates
        )
    ):
        raise ValueError("PRIVATE_CHAT_PUBLIC_CONTEXT_NATIVE_ASSOCIATION_INVALID")


type SupportedPrivateChatSimilarityRequest = (
    PrivateChatSimilarityRequest | PrivateChatSimilarityRequestV2
)
type SupportedPrivateChatSimilarityContext = (
    PrivateChatSimilarityContext | PrivateChatSimilarityContextV2
)


def parse_supported_private_chat_similarity_request(
    value: object,
) -> SupportedPrivateChatSimilarityRequest:
    document = raw_similarity_contract_value(value)
    if (
        isinstance(document, dict)
        and document.get("schema_version") == "system-rag-private-chat-similarity-request/2.0"
    ):
        return PrivateChatSimilarityRequestV2.model_validate(document)
    return PrivateChatSimilarityRequest.model_validate(document)


def parse_supported_private_chat_similarity_context(
    value: object,
) -> SupportedPrivateChatSimilarityContext:
    document = raw_similarity_contract_value(value)
    if (
        isinstance(document, dict)
        and document.get("schema_version") == "system-rag-private-chat-similarity-context/2.0"
    ):
        return PrivateChatSimilarityContextV2.model_validate(document)
    return PrivateChatSimilarityContext.model_validate(document)
