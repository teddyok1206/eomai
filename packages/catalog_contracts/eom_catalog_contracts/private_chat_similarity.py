"""Private question auxiliary observations, never approved-source or execution authority."""

from __future__ import annotations

from typing import Literal

from eom_identifiers import content_sha256
from eom_protocol.artifact_members import ArtifactMemberPointer
from eom_protocol.models import JobId
from pydantic import ConfigDict, Field, model_validator

from eom_catalog_contracts.embedding_private_chat_query import (
    PRIVATE_CHAT_QUERY_RESULT_REF,
    EmbeddingPrivateChatQueryInput,
    EmbeddingPrivateChatQueryResult,
    validate_private_chat_query_result,
)
from eom_catalog_contracts.embedding_reference_query import (
    raw_similarity_contract_value,
    similarity_contract_document,
)
from eom_catalog_contracts.knowledge import KnowledgeGraphSnapshotPointer
from eom_catalog_contracts.models import FrozenModel, Sha256
from eom_catalog_contracts.private_chat_query_basis import PrivateChatQueryBasis
from eom_catalog_contracts.similarity_context import (
    SimilarityCandidate,
    SimilarityFailureCode,
    SimilarityPopulation,
    SimilarityVectorObservation,
    SimilarityViewCoverage,
    SimilarityViewSelection,
)

MAX_PRIVATE_CHAT_SIMILARITY_BYTES = 512 * 1024
type PrivateChatSimilarityLimitation = Literal[
    "PRIVATE_QUERY_IS_NOT_SOURCE_EVIDENCE",
    "SINGLE_USER_MESSAGE_ONLY",
    "SCORES_ARE_NOT_SOLUTION_EQUALITY_OR_APPROVAL",
    "VECTOR_NOT_AVAILABLE",
    "PARTIAL_REPORT_COVERAGE",
    "PARTIAL_VIEW_COVERAGE",
    "BOUNDED_SCOPE_TRUNCATED",
    "NO_RELATED_CANDIDATES",
]
PRIVATE_CHAT_LIMITATION_ORDER: tuple[PrivateChatSimilarityLimitation, ...] = (
    "PRIVATE_QUERY_IS_NOT_SOURCE_EVIDENCE",
    "SINGLE_USER_MESSAGE_ONLY",
    "SCORES_ARE_NOT_SOLUTION_EQUALITY_OR_APPROVAL",
    "VECTOR_NOT_AVAILABLE",
    "PARTIAL_REPORT_COVERAGE",
    "PARTIAL_VIEW_COVERAGE",
    "BOUNDED_SCOPE_TRUNCATED",
    "NO_RELATED_CANDIDATES",
)


class _PrivateContextValue(FrozenModel):
    model_config = ConfigDict(revalidate_instances="always")

    @model_validator(mode="before")
    @classmethod
    def schema_first(cls, value: object) -> object:
        return similarity_contract_document(
            value, "system-rag-private-chat-similarity", MAX_PRIVATE_CHAT_SIMILARITY_BYTES
        )


class PrivateChatSimilarityRequest(_PrivateContextValue):
    schema_version: Literal["system-rag-private-chat-similarity-request/1.0"]
    request_id: str = Field(pattern=r"^similarityrequest_[0-9a-f]{32}$")
    consumer_purpose: Literal["GENERAL_CHAT_READ"]
    query_basis: PrivateChatQueryBasis
    graph_snapshot: KnowledgeGraphSnapshotPointer
    policy_revision_id: str = Field(pattern=r"^accessrev_[0-9a-f]{32}$")
    policy_sha256: Sha256
    source_classes: tuple[Literal["APPROVED_ITEM", "PAST_EXAM"], ...] = Field(
        min_length=1, max_length=2
    )
    views: tuple[SimilarityViewSelection, ...] = Field(min_length=1, max_length=1)
    vector_mode: Literal["REQUIRED"]
    maximum_sources: int = Field(ge=1, le=1024, strict=True)
    top_k: int = Field(ge=1, le=64, strict=True)
    request_sha256: Sha256

    @model_validator(mode="after")
    def exact_scope(self) -> PrivateChatSimilarityRequest:
        if (
            self.views[0].view != "CONTENT_ONLY"
            or self.source_classes != tuple(sorted(set(self.source_classes)))
            or self.graph_snapshot.manifest_artifact.sha256 != self.graph_snapshot.manifest_sha256
            or self.request_sha256
            != content_sha256(self.model_dump(mode="json", exclude={"request_sha256"}))
        ):
            raise ValueError("private Chat context request hash/scope differs")
        return self


class PrivateChatQueryExecutionPointer(FrozenModel):
    model_config = ConfigDict(revalidate_instances="always")

    @model_validator(mode="before")
    @classmethod
    def raw_values(cls, value: object) -> object:
        return raw_similarity_contract_value(value)

    job_id: JobId
    query_request_id: str = Field(pattern=r"^embeddingquery_[0-9a-f]{32}$")
    request_sha256: Sha256
    input_set_sha256: Sha256
    basis_sha256: Sha256
    result_member: ArtifactMemberPointer
    result_sha256: Sha256

    @model_validator(mode="after")
    def exact_result_member(self) -> PrivateChatQueryExecutionPointer:
        if (
            self.result_member.member_path != "result.json"
            or self.result_member.schema_ref != PRIVATE_CHAT_QUERY_RESULT_REF
            or self.result_member.media_type != "application/json"
        ):
            raise ValueError("private Chat query execution requires its distinct result member")
        return self


class PrivateChatViewCoverage(SimilarityViewCoverage):
    """No approved query Item is removed: all1024 authorized bindings can be scored."""

    view: Literal["CONTENT_ONLY"]
    scored_count: int = Field(ge=0, le=1024, strict=True)


class PrivateChatPopulation(SimilarityPopulation):
    views: tuple[PrivateChatViewCoverage, ...] = Field(min_length=1, max_length=1)


class PrivateChatSimilarityContext(_PrivateContextValue):
    schema_version: Literal["system-rag-private-chat-similarity-context/1.0"]
    request: PrivateChatSimilarityRequest
    status: Literal["READY", "PARTIAL", "EMPTY", "UNAVAILABLE", "FAILED"]
    population: PrivateChatPopulation | None
    query_execution: PrivateChatQueryExecutionPointer | None
    candidates: tuple[SimilarityCandidate, ...] = Field(max_length=64)
    limitations: tuple[PrivateChatSimilarityLimitation, ...] = Field(min_length=3, max_length=8)
    error_code: SimilarityFailureCode | None
    context_sha256: Sha256

    @model_validator(mode="after")
    def exact_observation(self) -> PrivateChatSimilarityContext:
        if (
            not set(PRIVATE_CHAT_LIMITATION_ORDER[:3]).issubset(self.limitations)
            or self.limitations
            != tuple(v for v in PRIVATE_CHAT_LIMITATION_ORDER if v in self.limitations)
            or self.context_sha256
            != content_sha256(self.model_dump(mode="json", exclude={"context_sha256"}))
        ):
            raise ValueError("private Chat limitations/hash differ")
        if self.status == "FAILED":
            return self  # Schema prohibits partial candidate/count/execution disclosure.
        population = self.population
        assert population is not None
        coverage = population.views[0]
        index = self.request.views[0].index
        if population.authorized_source_count > self.request.maximum_sources or (
            len(self.candidates) > min(self.request.top_k, population.accepted_profile_count)
        ):
            raise ValueError("private Chat population/result exceeds its exact scope")
        for condition, limitation in (
            (bool(population.missing_report_count), "PARTIAL_REPORT_COVERAGE"),
            (bool(coverage.missing_view_count), "PARTIAL_VIEW_COVERAGE"),
            (population.truncated, "BOUNDED_SCOPE_TRUNCATED"),
            (not self.candidates, "NO_RELATED_CANDIDATES"),
            (coverage.status == "UNAVAILABLE", "VECTOR_NOT_AVAILABLE"),
        ):
            if condition != (limitation in self.limitations):
                raise ValueError("private Chat limitation differs from actual coverage")
        if self.query_execution is not None and (
            index is None
            or self.query_execution.basis_sha256 != self.request.query_basis.basis_sha256
        ):
            raise ValueError("private execution basis/index differs")
        if coverage.status == "UNAVAILABLE":
            if self.status != "UNAVAILABLE" or self.query_execution is not None or self.candidates:
                raise ValueError("private vector unavailability cannot become another success")
            if (index is None) != (coverage.reason == "INDEX_NOT_PREPARED"):
                raise ValueError("private index absence is not invalid prepared-index recovery")
            return self
        if index is None or coverage.scored_count != coverage.available_binding_count:
            raise ValueError("private lookup cannot silently exclude an approved anchor")
        if coverage.scored_count and self.query_execution is None:
            raise ValueError("private scored candidates require an exact query execution")
        if len(self.candidates) != min(self.request.top_k, coverage.scored_count):
            raise ValueError("private candidate count differs from the actual scored population")
        revisions = tuple(v.source.item_revision_id for v in self.candidates)
        if len(set(revisions)) != len(revisions):
            raise ValueError("private context repeats a candidate source")
        for rank, candidate in enumerate(self.candidates, 1):
            if (
                candidate.source.source_class not in self.request.source_classes
                or candidate.explanation is not None
                or len(candidate.observations) != 1
            ):
                raise ValueError("private candidate scope/channel differs")
            observation = candidate.observations[0]
            if not isinstance(observation, SimilarityVectorObservation) or (
                observation.view != "CONTENT_ONLY"
                or observation.rank != rank
                or observation.query_row.row_index != 0
                or self.query_execution is None
                or (
                    observation.query_row.shard_manifest.artifact_id,
                    observation.query_row.shard_manifest.artifact_revision_id,
                )
                != (
                    self.query_execution.result_member.artifact_id,
                    self.query_execution.result_member.artifact_revision_id,
                )
            ):
                raise ValueError("private candidate rank/query row differs")
        partial = bool(
            population.missing_report_count or coverage.missing_view_count or population.truncated
        )
        expected = "EMPTY" if not self.candidates else "PARTIAL" if partial else "READY"
        if self.status != expected:
            raise ValueError("private context status hides actual coverage")
        return self


def validate_private_chat_query_execution(
    context: PrivateChatSimilarityContext,
    request: EmbeddingPrivateChatQueryInput,
    result: EmbeddingPrivateChatQueryResult,
    result_member: ArtifactMemberPointer,
    shard_member: ArtifactMemberPointer,
) -> None:
    """Pure exact parent/native/result/member closure, never a read or admission grant."""
    context = PrivateChatSimilarityContext.model_validate(raw_similarity_contract_value(context))
    request = EmbeddingPrivateChatQueryInput.model_validate(raw_similarity_contract_value(request))
    result = EmbeddingPrivateChatQueryResult.model_validate(raw_similarity_contract_value(result))
    result_member = ArtifactMemberPointer.model_validate(
        raw_similarity_contract_value(result_member)
    )
    shard_member = ArtifactMemberPointer.model_validate(raw_similarity_contract_value(shard_member))
    validate_private_chat_query_result(request, result)
    index = context.request.views[0].index
    expected = PrivateChatQueryExecutionPointer(
        job_id=request.job_id,
        query_request_id=request.query_request_id,
        request_sha256=request.request_sha256,
        input_set_sha256=request.input_set_sha256,
        basis_sha256=request.basis.basis_sha256,
        result_member=result_member,
        result_sha256=result.result_sha256,
    )
    if (
        context.query_execution != expected
        or index is None
        or request.context_request_sha256 != context.request.request_sha256
        or request.basis != context.request.query_basis
        or request.spaces != index.spaces
        or request.document_recipe != context.request.views[0].recipe
        or request.row.encoding.storage_partition != index.storage_partition
        or result_member.sha256 != content_sha256(result)
        or shard_member.member_path != "shard.json"
        or shard_member.schema_ref != "eom://schemas/knowledge/embedding-vector-shard/1.0"
        or shard_member.media_type != "application/json"
        or shard_member.sha256 != content_sha256(result.shard)
        or (shard_member.artifact_id, shard_member.artifact_revision_id)
        != (result_member.artifact_id, result_member.artifact_revision_id)
    ):
        raise ValueError("private context/native/member association differs")
    for candidate in context.candidates:
        observation = candidate.observations[0]
        assert isinstance(observation, SimilarityVectorObservation)
        if observation.query_row.shard_manifest != shard_member or (
            observation.query_row.encoding_sha256 != request.row.encoding.encoding_sha256
        ):
            raise ValueError("private query row differs from its exact committed execution")
