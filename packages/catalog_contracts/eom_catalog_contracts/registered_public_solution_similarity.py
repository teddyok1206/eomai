"""Closed metadata4 proof carriers over unchanged public text, model and QUERY2.

No value here grants source access, launches work, resolves latest or proves
scientific correctness. Catalog/QUERY owners retain those actual boundaries.
"""

from typing import Annotated, Literal, Self

from eom_protocol.artifact_members import ArtifactMemberPointer
from pydantic import ConfigDict, Field, model_validator

from eom_catalog_contracts.embedding_reference_query import (
    ReferenceQuerySpaces,
    raw_similarity_contract_value,
    similarity_contract_document,
)
from eom_catalog_contracts.inference_transfer_embedding import StoragePartition
from eom_catalog_contracts.knowledge import (
    ApprovedItemKnowledgeSourceV2,
    KnowledgeGraphSnapshotPointer,
)
from eom_catalog_contracts.models import FrozenModel, Sha256
from eom_catalog_contracts.public_solution_embedding import (
    PublicSolutionEmbeddingEntry,
    PublicSolutionEmbeddingRecipe,
)
from eom_catalog_contracts.public_solution_embedding_index import (
    MAX_PUBLIC_SOLUTION_SOURCES,
    PUBLIC_SOLUTION_INDEX_SCHEMA_REF,
)
from eom_catalog_contracts.public_solution_query import PublicSolutionQueryExecutionPointer
from eom_catalog_contracts.public_solution_reference import (
    PublicSolutionSourceReference,
    validate_public_solution_profile_identity,
)
from eom_catalog_contracts.public_solution_similarity import (
    PublicSolutionSimilarityCandidate,
    PublicSolutionSimilarityContext,
    PublicSolutionSimilarityLimitation,
    PublicSolutionSimilarityPopulation,
    PublicSolutionSimilarityPurpose,
    PublicSolutionSimilarityRequest,
    validate_public_similarity_context_values,
    validate_public_similarity_index_pointer,
    validate_public_similarity_observation,
    validate_public_similarity_request_values,
)
from eom_catalog_contracts.registered_public_solution_embedding import (
    PublicSolutionEncodingEntry,
    RegisteredPublicSolutionEmbeddingEntry,
    RegisteredPublicSolutionEvidence,
)
from eom_catalog_contracts.registered_public_solution_index import (
    REGISTERED_PUBLIC_SOLUTION_INDEX_SCHEMA_REF,
    RegisteredPublicSolutionProfilePointer,
)
from eom_catalog_contracts.similarity_context import (
    MAX_SIMILARITY_CONTEXT_BYTES,
    SimilarityFailureCode,
    SimilarityVectorObservation,
)

REGISTERED_PUBLIC_SIMILARITY_SCHEMA = "public-solution-similarity-v4"
REGISTERED_PUBLIC_SIMILARITY_REF = "eom://schemas/knowledge/system-rag-similarity-context/4.0"


class _RegisteredSimilarityValue(FrozenModel):
    model_config = ConfigDict(revalidate_instances="always", hide_input_in_errors=True)

    @model_validator(mode="before")
    @classmethod
    def raw_values(cls, value: object) -> object:
        return raw_similarity_contract_value(value)


class RegisteredPublicSolutionSourceReference(_RegisteredSimilarityValue):
    basis: Literal["VERIFIABLE_PUBLIC_SOLUTION"] = "VERIFIABLE_PUBLIC_SOLUTION"
    source: ApprovedItemKnowledgeSourceV2
    base_analysis_run_id: str = Field(pattern=r"^analysisrun_[0-9a-f]{32}$")
    profile: RegisteredPublicSolutionProfilePointer
    evidence: RegisteredPublicSolutionEvidence

    @model_validator(mode="after")
    def exact_source(self) -> Self:
        validate_public_solution_profile_identity(
            item_id=self.source.item_id,
            profile_id=self.profile.profile_id,
            profile_revision_id=self.profile.profile_revision_id,
            profile_sha256=self.profile.profile_sha256,
        )
        if (
            self.source.source_class != "APPROVED_ITEM"
            or self.base_analysis_run_id != self.evidence.solution.base_analysis_run_id
        ):
            raise ValueError("REGISTERED_PUBLIC_REFERENCE_BASE_MISMATCH")
        return self

    @classmethod
    def from_entry(cls, entry: RegisteredPublicSolutionEmbeddingEntry) -> Self:
        entry = RegisteredPublicSolutionEmbeddingEntry.model_validate(
            raw_similarity_contract_value(entry)
        )
        return cls(
            source=entry.source,
            base_analysis_run_id=entry.base_analysis_run_id,
            profile=RegisteredPublicSolutionProfilePointer.from_entry(entry),
            evidence=entry.evidence,
        )


type PublicSolutionReferenceV4 = (
    PublicSolutionSourceReference | RegisteredPublicSolutionSourceReference
)


def public_solution_reference_for_entry(
    entry: PublicSolutionEncodingEntry,
) -> PublicSolutionReferenceV4:
    if isinstance(entry, PublicSolutionEmbeddingEntry):
        return PublicSolutionSourceReference.from_entry(entry)
    if isinstance(entry, RegisteredPublicSolutionEmbeddingEntry):
        return RegisteredPublicSolutionSourceReference.from_entry(entry)
    raise ValueError("PUBLIC_SOLUTION_ENTRY_FAMILY_UNSUPPORTED")


class PublicSolutionSimilarityIndexPinV4(_RegisteredSimilarityValue):
    index_id: str = Field(pattern=r"^embeddingindex_[0-9a-f]{32}$")
    index_revision_id: str = Field(pattern=r"^embeddingindexrev_[0-9a-f]{32}$")
    index_manifest: ArtifactMemberPointer
    index_sha256: Sha256
    storage_partition: StoragePartition
    spaces: ReferenceQuerySpaces

    @model_validator(mode="after")
    def exact_manifest(self) -> Self:
        validate_public_similarity_index_pointer(
            self.index_manifest,
            schema_refs=(
                PUBLIC_SOLUTION_INDEX_SCHEMA_REF,
                REGISTERED_PUBLIC_SOLUTION_INDEX_SCHEMA_REF,
            ),
        )
        return self


class PublicSolutionSimilarityViewV4(_RegisteredSimilarityValue):
    view: Literal["CONCRETE_FACETS"] = "CONCRETE_FACETS"
    recipe: PublicSolutionEmbeddingRecipe
    index: PublicSolutionSimilarityIndexPinV4


class PublicSolutionSimilarityRequestV4(_RegisteredSimilarityValue):
    schema_version: Literal["system-rag-similarity-request/4.0"] = (
        "system-rag-similarity-request/4.0"
    )
    request_id: str = Field(pattern=r"^similarityrequest_[0-9a-f]{32}$")
    consumer_purpose: PublicSolutionSimilarityPurpose
    anchor: PublicSolutionReferenceV4
    graph_snapshot: KnowledgeGraphSnapshotPointer
    policy_revision_id: str = Field(pattern=r"^accessrev_[0-9a-f]{32}$")
    policy_sha256: Sha256
    source_classes: tuple[Literal["APPROVED_ITEM", "PAST_EXAM"], ...] = Field(
        min_length=1, max_length=2
    )
    views: tuple[PublicSolutionSimilarityViewV4, ...] = Field(min_length=1, max_length=1)
    maximum_sources: int = Field(ge=1, le=MAX_PUBLIC_SOLUTION_SOURCES, strict=True)
    top_k: int = Field(ge=1, le=64, strict=True)
    request_sha256: Sha256

    @model_validator(mode="before")
    @classmethod
    def schema_first(cls, value: object) -> object:
        return similarity_contract_document(
            value, REGISTERED_PUBLIC_SIMILARITY_SCHEMA, MAX_SIMILARITY_CONTEXT_BYTES
        )

    @model_validator(mode="after")
    def exact_scope(self) -> Self:
        return validate_public_similarity_request_values(self)


class RegisteredPublicSolutionSimilarityCandidate(RegisteredPublicSolutionSourceReference):
    observation: SimilarityVectorObservation

    @model_validator(mode="after")
    def public_view(self) -> Self:
        validate_public_similarity_observation(self.observation)
        return self


class PublicSolutionSimilarityContextV4(_RegisteredSimilarityValue):
    schema_version: Literal["system-rag-similarity-context/4.0"] = (
        "system-rag-similarity-context/4.0"
    )
    request: PublicSolutionSimilarityRequestV4
    status: Literal["READY", "PARTIAL", "EMPTY", "FAILED"]
    population: PublicSolutionSimilarityPopulation | None
    query_execution: PublicSolutionQueryExecutionPointer | None
    candidates: tuple[
        PublicSolutionSimilarityCandidate | RegisteredPublicSolutionSimilarityCandidate, ...
    ] = Field(max_length=64)
    limitations: tuple[PublicSolutionSimilarityLimitation, ...] = Field(min_length=1, max_length=4)
    error_code: SimilarityFailureCode | None
    context_sha256: Sha256

    @model_validator(mode="before")
    @classmethod
    def schema_first(cls, value: object) -> object:
        return similarity_contract_document(
            value, REGISTERED_PUBLIC_SIMILARITY_SCHEMA, MAX_SIMILARITY_CONTEXT_BYTES
        )

    @model_validator(mode="after")
    def exact_observations(self) -> Self:
        return validate_public_similarity_context_values(self)


type SupportedPublicSolutionSimilarityRequest = (
    PublicSolutionSimilarityRequest | PublicSolutionSimilarityRequestV4
)
type SupportedPublicSolutionSimilarityContext = Annotated[
    PublicSolutionSimilarityContext | PublicSolutionSimilarityContextV4,
    Field(discriminator="schema_version"),
]


def parse_supported_public_solution_similarity_request(
    value: object,
) -> SupportedPublicSolutionSimilarityRequest:
    document = raw_similarity_contract_value(value)
    if isinstance(document, dict):
        match document.get("schema_version"):
            case "system-rag-similarity-request/3.0":
                return PublicSolutionSimilarityRequest.model_validate(document)
            case "system-rag-similarity-request/4.0":
                return PublicSolutionSimilarityRequestV4.model_validate(document)
    raise ValueError("PUBLIC_SOLUTION_SIMILARITY_FAMILY_UNSUPPORTED")


def parse_supported_public_solution_similarity_context(
    value: object,
) -> SupportedPublicSolutionSimilarityContext:
    document = raw_similarity_contract_value(value)
    if isinstance(document, dict):
        match document.get("schema_version"):
            case "system-rag-similarity-context/3.0":
                return PublicSolutionSimilarityContext.model_validate(document)
            case "system-rag-similarity-context/4.0":
                return PublicSolutionSimilarityContextV4.model_validate(document)
    raise ValueError("PUBLIC_SOLUTION_SIMILARITY_FAMILY_UNSUPPORTED")
