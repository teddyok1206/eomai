"""Public-report QUERY/index observations; never source authority or scientific approval."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Literal, Protocol, Self

from eom_identifiers import content_sha256
from eom_protocol.artifact_members import ArtifactMemberPointer
from pydantic import ConfigDict, Field, model_validator

from eom_catalog_contracts.embedding_reference_query import (
    ReferenceQuerySpaces,
    raw_similarity_contract_value,
    similarity_contract_document,
)
from eom_catalog_contracts.inference_transfer_embedding import StoragePartition
from eom_catalog_contracts.inference_transfer_experiment import PopulationSource
from eom_catalog_contracts.knowledge import KnowledgeGraphSnapshotPointer
from eom_catalog_contracts.models import FrozenModel, Sha256
from eom_catalog_contracts.public_solution_embedding import PublicSolutionEmbeddingRecipe
from eom_catalog_contracts.public_solution_embedding_index import (
    MAX_PUBLIC_SOLUTION_SOURCES,
    PUBLIC_SOLUTION_INDEX_SCHEMA_REF,
)
from eom_catalog_contracts.public_solution_query import PublicSolutionQueryExecutionPointer
from eom_catalog_contracts.public_solution_reference import PublicSolutionSourceReference
from eom_catalog_contracts.similarity_context import (
    MAX_SIMILARITY_CONTEXT_BYTES,
    SimilarityFailureCode,
    SimilarityVectorObservation,
)

PUBLIC_SOLUTION_SIMILARITY_SCHEMA = "public-solution-similarity-v3"
PUBLIC_SOLUTION_SIMILARITY_REF = "eom://schemas/knowledge/system-rag-similarity-context/3.0"
type PublicSolutionSimilarityPurpose = Literal[
    "ITEM_DATABASE_SEARCH", "PAST_EXAM_VARIATION", "ITEM_AUTHORING", "ITEM_REVIEW"
]
type PublicSolutionSimilarityLimitation = Literal[
    "SCORE_IS_NOT_PROOF_OF_IDENTICAL_REASONING",
    "PARTIAL_REPORT_COVERAGE",
    "PARTIAL_VIEW_COVERAGE",
    "BOUNDED_SCOPE_TRUNCATED",
]


class _PublicSimilarityValue(FrozenModel):
    model_config = ConfigDict(revalidate_instances="always", hide_input_in_errors=True)

    @model_validator(mode="before")
    @classmethod
    def raw_values(cls, value: object) -> object:
        return raw_similarity_contract_value(value)


class PublicSolutionSimilarityIndexPin(_PublicSimilarityValue):
    index_id: str = Field(pattern=r"^embeddingindex_[0-9a-f]{32}$")
    index_revision_id: str = Field(pattern=r"^embeddingindexrev_[0-9a-f]{32}$")
    index_manifest: ArtifactMemberPointer
    index_sha256: Sha256
    storage_partition: StoragePartition
    spaces: ReferenceQuerySpaces

    @model_validator(mode="after")
    def exact_manifest(self) -> Self:
        validate_public_similarity_index_pointer(
            self.index_manifest, schema_refs=(PUBLIC_SOLUTION_INDEX_SCHEMA_REF,)
        )
        return self


class PublicSolutionSimilarityView(_PublicSimilarityValue):
    view: Literal["CONCRETE_FACETS"] = "CONCRETE_FACETS"
    recipe: PublicSolutionEmbeddingRecipe
    index: PublicSolutionSimilarityIndexPin


class PublicSolutionSimilarityRequest(_PublicSimilarityValue):
    schema_version: Literal["system-rag-similarity-request/3.0"] = (
        "system-rag-similarity-request/3.0"
    )
    request_id: str = Field(pattern=r"^similarityrequest_[0-9a-f]{32}$")
    consumer_purpose: PublicSolutionSimilarityPurpose
    anchor: PublicSolutionSourceReference
    graph_snapshot: KnowledgeGraphSnapshotPointer
    policy_revision_id: str = Field(pattern=r"^accessrev_[0-9a-f]{32}$")
    policy_sha256: Sha256
    source_classes: tuple[Literal["APPROVED_ITEM", "PAST_EXAM"], ...] = Field(
        min_length=1, max_length=2
    )
    views: tuple[PublicSolutionSimilarityView, ...] = Field(min_length=1, max_length=1)
    maximum_sources: int = Field(ge=1, le=MAX_PUBLIC_SOLUTION_SOURCES, strict=True)
    top_k: int = Field(ge=1, le=64, strict=True)
    request_sha256: Sha256

    @model_validator(mode="before")
    @classmethod
    def schema_first(cls, value: object) -> object:
        return similarity_contract_document(
            value, PUBLIC_SOLUTION_SIMILARITY_SCHEMA, MAX_SIMILARITY_CONTEXT_BYTES
        )

    @model_validator(mode="after")
    def exact_scope(self) -> Self:
        return validate_public_similarity_request_values(self)


class PublicSolutionSimilarityPopulation(_PublicSimilarityValue):
    authorized_source_count: int = Field(ge=1, le=MAX_PUBLIC_SOLUTION_SOURCES, strict=True)
    authorized_source_set_sha256: Sha256
    available_report_count: int = Field(ge=1, le=MAX_PUBLIC_SOLUTION_SOURCES, strict=True)
    available_report_set_sha256: Sha256
    available_binding_count: int = Field(ge=0, le=MAX_PUBLIC_SOLUTION_SOURCES, strict=True)
    binding_set_sha256: Sha256
    scored_count: int = Field(ge=0, le=MAX_PUBLIC_SOLUTION_SOURCES - 1, strict=True)
    truncated: bool = Field(strict=True)

    @model_validator(mode="after")
    def exact_counts(self) -> Self:
        if not (
            self.scored_count
            <= self.available_binding_count
            <= self.available_report_count
            <= self.authorized_source_count
        ):
            raise ValueError("PUBLIC_SIMILARITY_COVERAGE_INVALID")
        return self


class PublicSolutionSimilarityCandidate(PublicSolutionSourceReference):
    observation: SimilarityVectorObservation

    @model_validator(mode="after")
    def public_view(self) -> Self:
        validate_public_similarity_observation(self.observation)
        return self


class PublicSolutionSimilarityContext(_PublicSimilarityValue):
    schema_version: Literal["system-rag-similarity-context/3.0"] = (
        "system-rag-similarity-context/3.0"
    )
    request: PublicSolutionSimilarityRequest
    status: Literal["READY", "PARTIAL", "EMPTY", "FAILED"]
    population: PublicSolutionSimilarityPopulation | None
    query_execution: PublicSolutionQueryExecutionPointer | None
    candidates: tuple[PublicSolutionSimilarityCandidate, ...] = Field(max_length=64)
    limitations: tuple[PublicSolutionSimilarityLimitation, ...] = Field(min_length=1, max_length=4)
    error_code: SimilarityFailureCode | None
    context_sha256: Sha256

    @model_validator(mode="before")
    @classmethod
    def schema_first(cls, value: object) -> object:
        return similarity_contract_document(
            value, PUBLIC_SOLUTION_SIMILARITY_SCHEMA, MAX_SIMILARITY_CONTEXT_BYTES
        )

    @model_validator(mode="after")
    def exact_observations(self) -> Self:
        return validate_public_similarity_context_values(self)


class PublicSimilarityReferenceValues(Protocol):
    @property
    def source(self) -> PopulationSource: ...


class PublicSimilarityRequestValues(Protocol):
    @property
    def anchor(self) -> PublicSimilarityReferenceValues: ...

    @property
    def source_classes(self) -> tuple[Literal["APPROVED_ITEM", "PAST_EXAM"], ...]: ...

    @property
    def graph_snapshot(self) -> KnowledgeGraphSnapshotPointer: ...

    @property
    def request_sha256(self) -> str: ...

    @property
    def maximum_sources(self) -> int: ...

    @property
    def top_k(self) -> int: ...

    def model_dump(self, *, mode: Literal["json"], exclude: set[str]) -> dict[str, Any]: ...


class PublicSimilarityCandidateValues(PublicSimilarityReferenceValues, Protocol):
    @property
    def observation(self) -> SimilarityVectorObservation: ...


class PublicSimilarityContextValues(Protocol):
    @property
    def request(self) -> PublicSimilarityRequestValues: ...

    @property
    def status(self) -> str: ...

    @property
    def population(self) -> PublicSolutionSimilarityPopulation | None: ...

    @property
    def query_execution(self) -> PublicSolutionQueryExecutionPointer | None: ...

    @property
    def candidates(self) -> Sequence[PublicSimilarityCandidateValues]: ...

    @property
    def limitations(self) -> tuple[PublicSolutionSimilarityLimitation, ...]: ...

    @property
    def error_code(self) -> SimilarityFailureCode | None: ...

    @property
    def context_sha256(self) -> str: ...

    def model_dump(self, *, mode: Literal["json"], exclude: set[str]) -> dict[str, Any]: ...


def validate_public_similarity_index_pointer(
    pointer: ArtifactMemberPointer, *, schema_refs: tuple[str, ...]
) -> None:
    if (
        pointer.member_path != "index.json"
        or pointer.schema_ref not in schema_refs
        or pointer.media_type != "application/json"
    ):
        raise ValueError("PUBLIC_SIMILARITY_INDEX_POINTER_INVALID")


def validate_public_similarity_observation(observation: SimilarityVectorObservation) -> None:
    if observation.view != "CONCRETE_FACETS":
        raise ValueError("PUBLIC_SIMILARITY_CANDIDATE_VIEW_INVALID")


def validate_public_similarity_request_values[T: PublicSimilarityRequestValues](value: T) -> T:
    """One scope/hash rule for closed predecessor3 and registered metadata4."""
    if (
        value.source_classes != tuple(sorted(set(value.source_classes)))
        or value.anchor.source.source_class not in value.source_classes
        or value.graph_snapshot.manifest_sha256 != value.graph_snapshot.manifest_artifact.sha256
        or value.request_sha256
        != content_sha256(value.model_dump(mode="json", exclude={"request_sha256"}))
    ):
        raise ValueError("PUBLIC_SIMILARITY_REQUEST_INVALID")
    return value


def validate_public_similarity_context_values[T: PublicSimilarityContextValues](self: T) -> T:
    """Same finite coverage/rank/execution closure, independent of report proof envelope."""
    if (
        len(set(self.limitations)) != len(self.limitations)
        or "SCORE_IS_NOT_PROOF_OF_IDENTICAL_REASONING" not in self.limitations
        or self.context_sha256
        != content_sha256(self.model_dump(mode="json", exclude={"context_sha256"}))
    ):
        raise ValueError("PUBLIC_SIMILARITY_CONTEXT_HASH_INVALID")
    if self.status == "FAILED":
        if (
            self.error_code is None
            or self.population is not None
            or self.query_execution is not None
            or self.candidates
        ):
            raise ValueError("PUBLIC_SIMILARITY_FAILED_HAS_RESULT")
        return self
    population, query = self.population, self.query_execution
    if population is None or query is None or self.error_code is not None:
        raise ValueError("PUBLIC_SIMILARITY_EXECUTION_MISSING")
    if population.authorized_source_count > self.request.maximum_sources or len(
        self.candidates
    ) != min(population.scored_count, self.request.top_k):
        raise ValueError("PUBLIC_SIMILARITY_RESULT_SCOPE_INVALID")
    partial = False
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
    ):
        if condition != (limitation in self.limitations):
            raise ValueError("PUBLIC_SIMILARITY_LIMITATION_INVALID")
        partial = partial or condition
    expected = "EMPTY" if not population.scored_count else "PARTIAL" if partial else "READY"
    if self.status != expected:
        raise ValueError("PUBLIC_SIMILARITY_STATUS_INVALID")
    revisions = {candidate.source.item_revision_id for candidate in self.candidates}
    if (
        len(revisions) != len(self.candidates)
        or self.request.anchor.source.item_revision_id in revisions
    ):
        raise ValueError("PUBLIC_SIMILARITY_DUPLICATE_CANDIDATE")
    query_artifact = (query.result_member.artifact_id, query.result_member.artifact_revision_id)
    for rank, candidate in enumerate(self.candidates, 1):
        observation = candidate.observation
        if (
            observation.rank != rank
            or candidate.source.source_class not in self.request.source_classes
            or (
                observation.query_row.shard_manifest.artifact_id,
                observation.query_row.shard_manifest.artifact_revision_id,
            )
            != query_artifact
            or observation.query_row.row_index != 0
        ):
            raise ValueError("PUBLIC_SIMILARITY_CANDIDATE_EXECUTION_INVALID")
    return self
