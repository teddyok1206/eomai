"""Small independent retrieval observations, never Graph Evidence or approval."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Literal

from eom_identifiers import content_sha256
from eom_protocol.artifact_members import ArtifactMemberPointer
from pydantic import ConfigDict, Field, TypeAdapter, model_validator

from eom_catalog_contracts.embedding_reference_query import (
    REFERENCE_QUERY_RESULT_REF,
    EmbeddingReferenceQueryResult,
    ReferenceQueryExecutionPointer,
    ReferenceQuerySpaces,
    raw_similarity_contract_value,
    similarity_contract_document,
)
from eom_catalog_contracts.embedding_reference_query_v11 import (
    SupportedReferenceQueryInput,
    parse_supported_reference_query_input,
    validate_supported_reference_query_result,
)
from eom_catalog_contracts.embedding_registry import EmbeddingIndexId, EmbeddingIndexRevisionId
from eom_catalog_contracts.inference_transfer_embedding import (
    INDEX_SCHEMA_REF,
    EmbeddingIndexManifest,
    EmbeddingVectorRowRef,
    StoragePartition,
    parse_embedding_index,
)
from eom_catalog_contracts.inference_transfer_experiment import (
    VIEWS,
    ExperimentView,
    ExperimentViewRecipe,
    PopulationSource,
)
from eom_catalog_contracts.item_inference_transfer import InferenceTransferProfilePointer
from eom_catalog_contracts.knowledge import (
    KnowledgeGraphSnapshotPointer,
    KnowledgeSolutionEvidencePointer,
)
from eom_catalog_contracts.models import FrozenModel, Sha256

if TYPE_CHECKING:
    from eom_catalog_contracts.mixed_embedding_index import MixedEmbeddingIndexManifest
    from eom_catalog_contracts.similarity_context_v2 import SimilarityViewSelectionV2

SIMILARITY_CONTEXT_SCHEMA = "system-rag-similarity-context"
SIMILARITY_CONTEXT_REF = "eom://schemas/knowledge/system-rag-similarity-context/1.0"
MAX_SIMILARITY_CONTEXT_BYTES = 512 * 1024
type SimilarityConsumerPurpose = Literal[
    "PAST_EXAM_VARIATION",
    "ITEM_AUTHORING",
    "ITEM_REVIEW",
    "GENERAL_CHAT_READ",
    "MOCK_EXAM_OBSERVATION",
]
type SimilarityUnavailableReason = Literal[
    "INDEX_NOT_PREPARED",
    "QUERY_NOT_OFFERED",
    "ANCHOR_REPORT_MISSING",
    "VIEW_INPUT_MISSING",
    "INPUT_OVERFLOW",
]
type SimilarityLimitation = Literal[
    "VECTOR_NOT_AVAILABLE",
    "PARTIAL_REPORT_COVERAGE",
    "PARTIAL_VIEW_COVERAGE",
    "BOUNDED_SCOPE_TRUNCATED",
    "NO_RELATED_CANDIDATES",
    "REFERENCE_ANCHOR_NOT_PRIVATE_INTENT",
]
type SimilarityFailureCode = Literal[
    "SOURCE_ACCESS_DENIED",
    "SOURCE_REVOKED",
    "SOURCE_POINTER_INVALID",
    "SOURCE_HASH_MISMATCH",
    "INDEX_POINTER_INVALID",
    "INDEX_HASH_MISMATCH",
    "QUERY_RESULT_INVALID",
    "AUTHORITY_UNAVAILABLE",
]


class _ContextValue(FrozenModel):
    model_config = ConfigDict(revalidate_instances="always")

    @model_validator(mode="before")
    @classmethod
    def raw_values(cls, value: object) -> object:
        return raw_similarity_contract_value(value)


class ApprovedReferenceItemAnchor(_ContextValue):
    basis: Literal["APPROVED_REFERENCE_ITEM"] = "APPROVED_REFERENCE_ITEM"
    source: PopulationSource
    profile: InferenceTransferProfilePointer | None
    solution_evidence: KnowledgeSolutionEvidencePointer | None

    @model_validator(mode="after")
    def paired_report(self) -> ApprovedReferenceItemAnchor:
        if (self.profile is None) != (self.solution_evidence is None):
            raise ValueError("approved reference profile/report are present together or absent")
        return self


class SimilarityIndexPin(_ContextValue):
    index_id: EmbeddingIndexId
    index_revision_id: EmbeddingIndexRevisionId
    index_manifest: ArtifactMemberPointer
    index_sha256: Sha256
    storage_partition: StoragePartition
    spaces: ReferenceQuerySpaces

    @model_validator(mode="after")
    def exact_manifest_member(self) -> SimilarityIndexPin:
        if (
            self.index_manifest.member_path != "index.json"
            or self.index_manifest.schema_ref != INDEX_SCHEMA_REF
            or self.index_manifest.media_type != "application/json"
        ):
            raise ValueError("similarity index requires the exact immutable index manifest")
        return self


class SimilarityViewSelection(_ContextValue):
    view: ExperimentView
    recipe: ExperimentViewRecipe
    index: SimilarityIndexPin | None

    @model_validator(mode="after")
    def recipe_hash(self) -> SimilarityViewSelection:
        ExperimentViewRecipe.model_validate(raw_similarity_contract_value(self.recipe))
        return self


class SimilarityContextRequest(_ContextValue):
    schema_version: Literal["system-rag-similarity-request/1.0"] = (
        "system-rag-similarity-request/1.0"
    )
    request_id: str = Field(pattern=r"^similarityrequest_[0-9a-f]{32}$")
    consumer_purpose: SimilarityConsumerPurpose
    anchor: ApprovedReferenceItemAnchor
    graph_snapshot: KnowledgeGraphSnapshotPointer
    policy_revision_id: str = Field(pattern=r"^accessrev_[0-9a-f]{32}$")
    policy_sha256: Sha256
    source_classes: tuple[Literal["APPROVED_ITEM", "PAST_EXAM"], ...] = Field(
        min_length=1, max_length=2
    )
    topics: tuple[Annotated[str, Field(min_length=1, max_length=128)], ...] = Field(max_length=20)
    unit_ids: tuple[Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")], ...] = (
        Field(max_length=20)
    )
    views: tuple[SimilarityViewSelection, ...] = Field(min_length=1, max_length=3)
    vector_mode: Literal["OPTIONAL", "REQUIRED"]
    maximum_sources: int = Field(ge=1, le=1024, strict=True)
    top_k: int = Field(ge=1, le=64, strict=True)
    request_sha256: Sha256

    @model_validator(mode="before")
    @classmethod
    def schema_first(cls, value: object) -> object:
        return similarity_contract_document(
            value, SIMILARITY_CONTEXT_SCHEMA, MAX_SIMILARITY_CONTEXT_BYTES
        )

    @model_validator(mode="after")
    def exact_scope(self) -> SimilarityContextRequest:
        if self.graph_snapshot.manifest_artifact.sha256 != self.graph_snapshot.manifest_sha256:
            raise ValueError("Graph pointer hash differs")
        for values in (self.source_classes, self.topics, self.unit_ids):
            if values != tuple(sorted(set(values))):
                raise ValueError("similarity scope fields must be sorted and unique")
        if self.anchor.source.source_class not in self.source_classes:
            raise ValueError("approved reference class must belong to the admitted source scope")
        selected = tuple(selection.view for selection in self.views)
        if selected != tuple(view for view in VIEWS if view in selected):
            raise ValueError("similarity views must be unique and in the released view order")
        indexes = tuple(selection.index for selection in self.views if selection.index is not None)
        if len({(index.index_id, index.index_revision_id) for index in indexes}) != len(indexes):
            raise ValueError("different views cannot reuse one exact index revision")
        if indexes and any(
            index.spaces != indexes[0].spaces
            or index.storage_partition != indexes[0].storage_partition
            for index in indexes
        ):
            raise ValueError("one reference query cannot mix devices, spaces or partitions")
        if self.request_sha256 != content_sha256(
            self.model_dump(mode="json", exclude={"request_sha256"})
        ):
            raise ValueError("similarity request canonical hash differs")
        return self


def validate_similarity_index_pin(
    selection: SimilarityViewSelection,
    pointer: ArtifactMemberPointer,
    manifest: EmbeddingIndexManifest,
) -> None:
    """Pure resolved-value closure; existence, raw bytes and permissions remain owner checks."""
    selection = SimilarityViewSelection.model_validate(raw_similarity_contract_value(selection))
    pointer = ArtifactMemberPointer.model_validate(raw_similarity_contract_value(pointer))
    manifest = parse_embedding_index(raw_similarity_contract_value(manifest))
    if not similarity_index_matches_pin(selection, pointer, manifest):
        raise ValueError("resolved immutable index differs from its view/recipe/space/revision pin")


def similarity_index_matches_pin(
    selection: SimilarityViewSelection | SimilarityViewSelectionV2,
    pointer: ArtifactMemberPointer,
    manifest: EmbeddingIndexManifest | MixedEmbeddingIndexManifest,
) -> bool:
    """Compare already decoded values; never validate raw input or grant authority.

    Public validators parse all inputs first. Catalog uses the same rule only
    after its canonical member decoder, avoiding a second full binding parse.
    """
    pin = selection.index
    return pin is not None and not (
        pointer != pin.index_manifest
        or manifest.index_id != pin.index_id
        or manifest.index_revision_id != pin.index_revision_id
        or manifest.index_sha256 != pin.index_sha256
        or manifest.storage_partition != pin.storage_partition
        or manifest.space != pin.spaces.document
        or manifest.view != selection.view
        or manifest.recipe != selection.recipe
    )


class SimilarityViewCoverage(_ContextValue):
    view: ExperimentView
    status: Literal["READY", "PARTIAL", "EMPTY", "UNAVAILABLE"]
    available_binding_count: int | None = Field(ge=0, le=1024, strict=True)
    binding_set_sha256: Sha256 | None
    scored_count: int = Field(ge=0, le=1023, strict=True)
    missing_view_count: int | None = Field(ge=0, le=1024, strict=True)
    reason: SimilarityUnavailableReason | None

    @model_validator(mode="after")
    def explicit_absence(self) -> SimilarityViewCoverage:
        counts = (self.available_binding_count, self.binding_set_sha256, self.missing_view_count)
        if self.status == "UNAVAILABLE":
            if (
                any(value is not None for value in counts)
                or self.scored_count
                or self.reason is None
            ):
                raise ValueError("unavailable view cannot claim computed coverage")
        elif any(value is None for value in counts) or self.reason is not None:
            raise ValueError("available view requires exact counts/hash and no unavailable reason")
        elif (
            self.available_binding_count is not None
            and self.scored_count > self.available_binding_count
        ):
            raise ValueError("scored count exceeds available bindings")
        if self.status == "EMPTY" and (self.available_binding_count != 0 or self.scored_count != 0):
            raise ValueError("empty view has no available bindings or scored candidates")
        return self


class SimilarityPopulation(_ContextValue):
    authorized_source_count: int = Field(ge=0, le=1024, strict=True)
    authorized_source_set_sha256: Sha256
    accepted_profile_count: int = Field(ge=0, le=1024, strict=True)
    accepted_profile_set_sha256: Sha256
    missing_report_count: int = Field(ge=0, le=1024, strict=True)
    truncated: bool = Field(strict=True)
    views: tuple[SimilarityViewCoverage, ...] = Field(min_length=1, max_length=3)

    @model_validator(mode="after")
    def separate_denominators(self) -> SimilarityPopulation:
        if self.accepted_profile_count + self.missing_report_count != self.authorized_source_count:
            raise ValueError(
                "accepted profiles and missing reports do not partition the source scope"
            )
        selected = tuple(row.view for row in self.views)
        if selected != tuple(view for view in VIEWS if view in selected):
            raise ValueError("population view coverage must be unique in the released order")
        for row in self.views:
            if row.status != "UNAVAILABLE" and (
                row.available_binding_count is None
                or row.missing_view_count is None
                or row.available_binding_count + row.missing_view_count
                != self.accepted_profile_count
                or (row.status == "READY" and row.missing_view_count != 0)
                or (row.status == "PARTIAL" and row.missing_view_count == 0)
            ):
                raise ValueError("view coverage differs from the accepted-profile denominator")
        return self


class SimilarityGraphObservation(_ContextValue):
    channel: Literal["GRAPH_LEXICAL"] = "GRAPH_LEXICAL"
    rank: int = Field(ge=1, le=64, strict=True)
    graph_relevance_milli: int = Field(ge=0, le=2147483647, strict=True)


class SimilarityVectorObservation(_ContextValue):
    channel: Literal["VECTOR"] = "VECTOR"
    view: ExperimentView
    rank: int = Field(ge=1, le=64, strict=True)
    cosine_millionths: int = Field(ge=-1000000, le=1000000, strict=True)
    score_semantics: Literal["ROUNDED_DISPLAY_ONLY_NOT_RANKING_OR_PROBABILITY"] = (
        "ROUNDED_DISPLAY_ONLY_NOT_RANKING_OR_PROBABILITY"
    )
    query_row: EmbeddingVectorRowRef
    document_row: EmbeddingVectorRowRef


type SimilarityObservation = Annotated[
    SimilarityGraphObservation | SimilarityVectorObservation, Field(discriminator="channel")
]


class SimilarityModelExplanation(_ContextValue):
    kind: Literal["MODEL_INFERENCE"] = "MODEL_INFERENCE"
    request_member: ArtifactMemberPointer
    result_member: ArtifactMemberPointer
    judgement: Literal[
        "INSUFFICIENT", "NO_TRANSFER", "STRUCTURAL_ANALOGY", "NEAR_IDENTICAL_CANDIDATE"
    ]

    @model_validator(mode="after")
    def pair_contracts_not_evidence(self) -> SimilarityModelExplanation:
        if (
            self.request_member.schema_ref
            != "eom://schemas/knowledge/item-inference-transfer-pair-request/1.0"
            or self.result_member.schema_ref
            not in {
                "eom://schemas/knowledge/item-inference-transfer-pair-result/1.0",
                "eom://schemas/knowledge/item-inference-transfer-pair-result/1.1",
            }
            or self.request_member.media_type != "application/json"
            or self.result_member.media_type != "application/json"
        ):
            raise ValueError("comparison explanation must reference supported pair contracts")
        return self


class SimilarityCandidate(_ContextValue):
    source: PopulationSource
    profile: InferenceTransferProfilePointer
    solution_evidence: KnowledgeSolutionEvidencePointer
    observations: tuple[SimilarityObservation, ...] = Field(min_length=1, max_length=4)
    explanation: SimilarityModelExplanation | None

    @model_validator(mode="after")
    def independent_channels(self) -> SimilarityCandidate:
        keys = tuple(
            ("GRAPH_LEXICAL", "")
            if isinstance(row, SimilarityGraphObservation)
            else ("VECTOR", row.view)
            for row in self.observations
        )
        if len(keys) != len(set(keys)):
            raise ValueError("candidate repeats a channel/view observation")
        return self


class _SimilarityContext(_ContextValue):
    schema_version: Literal["system-rag-similarity-context/1.0"] = (
        "system-rag-similarity-context/1.0"
    )
    request: SimilarityContextRequest
    status: Literal["READY", "PARTIAL", "EMPTY", "UNAVAILABLE", "FAILED"]
    population: SimilarityPopulation | None
    query_execution: ReferenceQueryExecutionPointer | None
    graph_evidence: ArtifactMemberPointer | None
    candidates: tuple[SimilarityCandidate, ...] = Field(max_length=64)
    limitations: tuple[SimilarityLimitation, ...] = Field(min_length=1, max_length=8)
    error_code: SimilarityFailureCode | None
    context_sha256: Sha256

    @model_validator(mode="before")
    @classmethod
    def schema_first(cls, value: object) -> object:
        return similarity_contract_document(
            value, SIMILARITY_CONTEXT_SCHEMA, MAX_SIMILARITY_CONTEXT_BYTES
        )

    @model_validator(mode="after")
    def exact_observation_closure(self) -> _SimilarityContext:
        if len(set(self.limitations)) != len(self.limitations) or (
            "REFERENCE_ANCHOR_NOT_PRIVATE_INTENT" not in self.limitations
        ):
            raise ValueError("context must distinguish reference observations from private intent")
        if self.context_sha256 != content_sha256(
            self.model_dump(mode="json", exclude={"context_sha256"})
        ):
            raise ValueError("similarity context canonical hash differs")
        if self.status == "FAILED":
            return self  # Schema already denies partial candidates, counts or evidence disclosure.
        population = self.population
        if population is None:
            raise ValueError("successful context requires scoped population metadata")
        if (
            population.authorized_source_count > self.request.maximum_sources
            or len(self.candidates) > self.request.top_k
            or len(self.candidates) > population.accepted_profile_count
            or tuple(row.view for row in population.views)
            != tuple(row.view for row in self.request.views)
        ):
            raise ValueError("context counts/views differ from its pinned request budget")
        coverage = {row.view: row for row in population.views}
        selections = {row.view: row for row in self.request.views}
        for row in population.views:
            if row.status != "UNAVAILABLE" and selections[row.view].index is None:
                raise ValueError("available view lacks its exact immutable index")
            if row.status == "UNAVAILABLE" and "VECTOR_NOT_AVAILABLE" not in self.limitations:
                raise ValueError("unavailable vector view requires a limitation")
            if self.request.anchor.profile is None and (
                row.status != "UNAVAILABLE" or row.reason != "ANCHOR_REPORT_MISSING"
            ):
                raise ValueError("missing anchor report makes reference QUERY unavailable")
            if row.reason == "ANCHOR_REPORT_MISSING" and self.request.anchor.profile is not None:
                raise ValueError("anchor-report absence differs from its pinned request")
            if row.reason == "INDEX_NOT_PREPARED" and selections[row.view].index is not None:
                raise ValueError("an invalid prepared index is not optional index absence")
        if population.missing_report_count and "PARTIAL_REPORT_COVERAGE" not in self.limitations:
            raise ValueError("missing accepted reports require partial-coverage disclosure")
        if population.truncated and "BOUNDED_SCOPE_TRUNCATED" not in self.limitations:
            raise ValueError("bounded population cannot claim full corpus coverage")
        if (
            any(row.missing_view_count for row in population.views)
            and "PARTIAL_VIEW_COVERAGE" not in self.limitations
        ):
            raise ValueError("missing view bindings require partial-coverage disclosure")
        revisions = tuple(row.source.item_revision_id for row in self.candidates)
        if (
            len(set(revisions)) != len(revisions)
            or self.request.anchor.source.item_revision_id in revisions
        ):
            raise ValueError("context repeats a source or contains its reference anchor")
        channel_ranks: set[tuple[str, str, int]] = set()
        vector_count = 0
        for candidate in self.candidates:
            if candidate.source.source_class not in self.request.source_classes:
                raise ValueError("candidate source class exceeds the requested scope")
            for observation in candidate.observations:
                channel = (observation.channel, "", observation.rank)
                if isinstance(observation, SimilarityVectorObservation):
                    vector_count += 1
                    channel = (observation.channel, observation.view, observation.rank)
                    index = selections.get(observation.view)
                    observed_coverage = coverage.get(observation.view)
                    if (
                        index is None
                        or index.index is None
                        or observed_coverage is None
                        or observed_coverage.status in {"EMPTY", "UNAVAILABLE"}
                    ):
                        raise ValueError(
                            "vector observation lacks its prepared view/index coverage"
                        )
                    if (
                        observation.rank > observed_coverage.scored_count
                        or self.query_execution is None
                    ):
                        raise ValueError("vector rank or exact query execution is absent")
                    member = self.query_execution.result_member
                    shard = observation.query_row.shard_manifest
                    if (shard.artifact_id, shard.artifact_revision_id) != (
                        member.artifact_id,
                        member.artifact_revision_id,
                    ):
                        raise ValueError("query row belongs to another execution Artifact")
                if channel in channel_ranks:
                    raise ValueError("two candidates have the same independent channel rank")
                channel_ranks.add(channel)
        if any(row.scored_count for row in population.views) != (self.query_execution is not None):
            raise ValueError("exact query execution is required when any view was scored")
        unavailable = any(row.status == "UNAVAILABLE" for row in population.views)
        if (
            self.request.vector_mode == "REQUIRED"
            and (unavailable or self.query_execution is None)
            and self.status not in {"UNAVAILABLE", "EMPTY"}
        ):
            raise ValueError("required vectors cannot be replaced by Graph-only success")
        if self.status == "READY" and (
            unavailable
            or any(row.status != "READY" for row in population.views)
            or population.missing_report_count
            or population.truncated
            or not vector_count
        ):
            raise ValueError("ready context cannot hide partial/unavailable coverage")
        if self.status == "PARTIAL" and not (
            unavailable
            or population.missing_report_count
            or population.truncated
            or any(row.missing_view_count for row in population.views)
        ):
            raise ValueError("partial context must have an explicit partial condition")
        if (
            self.status in {"EMPTY", "UNAVAILABLE"}
            and "NO_RELATED_CANDIDATES" not in self.limitations
        ):
            raise ValueError("candidate-free context needs an explicit limitation")
        if self.status == "UNAVAILABLE" and not unavailable:
            raise ValueError(
                "unavailable context must identify an unavailable requested vector view"
            )
        if self.status == "EMPTY" and any(row.scored_count for row in population.views):
            raise ValueError("empty context cannot hide scored candidates")
        if self.graph_evidence is not None and (
            self.graph_evidence.member_path != "evidence/manifest.json"
            or self.graph_evidence.media_type != "application/json"
            or self.graph_evidence.schema_ref
            != "eom://schemas/knowledge/evidence-bundle-manifest/5.0"
        ):
            raise ValueError("Graph Evidence remains a separately resolved official manifest")
        return self


class ReadySimilarityContext(_SimilarityContext):
    status: Literal["READY"] = "READY"


class PartialSimilarityContext(_SimilarityContext):
    status: Literal["PARTIAL"] = "PARTIAL"


class EmptySimilarityContext(_SimilarityContext):
    status: Literal["EMPTY"] = "EMPTY"


class UnavailableSimilarityContext(_SimilarityContext):
    status: Literal["UNAVAILABLE"] = "UNAVAILABLE"


class FailedSimilarityContext(_SimilarityContext):
    status: Literal["FAILED"] = "FAILED"


type SimilarityContext = Annotated[
    ReadySimilarityContext
    | PartialSimilarityContext
    | EmptySimilarityContext
    | UnavailableSimilarityContext
    | FailedSimilarityContext,
    Field(discriminator="status"),
]


def parse_similarity_context_request(value: object) -> SimilarityContextRequest:
    return SimilarityContextRequest.model_validate(value)


def parse_similarity_context(value: object) -> SimilarityContext:
    document = similarity_contract_document(
        value, SIMILARITY_CONTEXT_SCHEMA, MAX_SIMILARITY_CONTEXT_BYTES
    )
    return TypeAdapter[SimilarityContext](SimilarityContext).validate_python(document)


def validate_similarity_query_execution(
    context: SimilarityContext,
    request: SupportedReferenceQueryInput,
    result: EmbeddingReferenceQueryResult,
    result_member: ArtifactMemberPointer,
    shard_member: ArtifactMemberPointer,
) -> None:
    """Check supplied immutable values; this does not resolve or authorize their targets."""
    context = parse_similarity_context(context)
    request = parse_supported_reference_query_input(request)
    validate_supported_reference_query_result(request, result)
    execution = context.query_execution
    result_member = ArtifactMemberPointer.model_validate(
        raw_similarity_contract_value(result_member)
    )
    shard_member = ArtifactMemberPointer.model_validate(raw_similarity_contract_value(shard_member))
    if execution is None or (
        execution.job_id != request.job_id
        or execution.query_request_id != request.query_request_id
        or execution.request_sha256 != request.request_sha256
        or execution.input_set_sha256 != request.input_set_sha256
        or execution.result_sha256 != result.result_sha256
        or execution.result_member != result_member
        or request.context_request_sha256 != context.request.request_sha256
        or result_member.schema_ref != REFERENCE_QUERY_RESULT_REF
        or (shard_member.artifact_id, shard_member.artifact_revision_id)
        != (result_member.artifact_id, result_member.artifact_revision_id)
        or shard_member.member_path != "shard.json"
        or shard_member.schema_ref != "eom://schemas/knowledge/embedding-vector-shard/1.0"
        or shard_member.media_type != "application/json"
    ):
        raise ValueError("context reference QUERY execution differs from its exact supplied result")
    selections = {selection.view: selection for selection in context.request.views}
    rows = {row.view: row for row in result.view_rows}
    for row in request.rows:
        selection = selections.get(row.view)
        if (
            selection is None
            or selection.index is None
            or (
                selection.index.spaces != request.spaces
                or selection.recipe != request.recipe
                or row.encoding.storage_partition != selection.index.storage_partition
            )
        ):
            raise ValueError("QUERY view/recipe/device/partition differs from its document index")
    for candidate in context.candidates:
        for observation in candidate.observations:
            if isinstance(observation, SimilarityVectorObservation):
                result_row = rows.get(observation.view)
                if result_row is None or (
                    observation.query_row.shard_manifest != shard_member
                    or observation.query_row.row_index != result_row.row_index
                    or observation.query_row.encoding_sha256 != result_row.encoding_sha256
                ):
                    raise ValueError(
                        "vector observation uses a missing or different QUERY view row"
                    )
