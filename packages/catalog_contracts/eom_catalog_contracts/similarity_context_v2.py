"""Explicit mixed evidence observations; never retagged accepted-analysis history."""

from __future__ import annotations

from typing import Annotated, Literal

from eom_identifiers import content_sha256
from eom_protocol.artifact_members import ArtifactMemberPointer
from pydantic import ConfigDict, Field, model_validator

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
from eom_catalog_contracts.inference_transfer_embedding import StoragePartition
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
from eom_catalog_contracts.mixed_embedding_index import (
    MIXED_EMBEDDING_INDEX_SCHEMA_REF,
    MixedEmbeddingIndexManifest,
)
from eom_catalog_contracts.models import FrozenModel, Sha256
from eom_catalog_contracts.registered_item_review_solution import (
    RegisteredItemReviewSolutionEvidence,
)
from eom_catalog_contracts.registered_review_profile import RegisteredReviewProfilePointer
from eom_catalog_contracts.similarity_context import (
    MAX_SIMILARITY_CONTEXT_BYTES,
    ApprovedReferenceItemAnchor,
    SimilarityConsumerPurpose,
    SimilarityContext,
    SimilarityContextRequest,
    SimilarityFailureCode,
    SimilarityModelExplanation,
    SimilarityObservation,
    SimilarityVectorObservation,
    SimilarityViewCoverage,
    parse_similarity_context,
    parse_similarity_context_request,
)

SIMILARITY_CONTEXT_V2_REF = "eom://schemas/knowledge/system-rag-similarity-context/2.0"
type MixedSimilarityProfilePointer = (
    InferenceTransferProfilePointer | RegisteredReviewProfilePointer
)
type SimilarityLimitationV2 = Literal[
    "VECTOR_NOT_AVAILABLE",
    "PARTIAL_EVIDENCE_COVERAGE",
    "PARTIAL_VIEW_COVERAGE",
    "BOUNDED_SCOPE_TRUNCATED",
    "NO_RELATED_CANDIDATES",
    "REFERENCE_ANCHOR_NOT_PRIVATE_INTENT",
]


class _MixedContextValue(FrozenModel):
    model_config = ConfigDict(revalidate_instances="always")

    @model_validator(mode="before")
    @classmethod
    def raw_values(cls, value: object) -> object:
        return raw_similarity_contract_value(value)


class SimilarityIndexPinV2(_MixedContextValue):
    index_id: EmbeddingIndexId
    index_revision_id: EmbeddingIndexRevisionId
    index_manifest: ArtifactMemberPointer
    index_sha256: Sha256
    storage_partition: StoragePartition
    spaces: ReferenceQuerySpaces

    @model_validator(mode="after")
    def mixed_manifest_member(self) -> SimilarityIndexPinV2:
        if (
            self.index_manifest.member_path != "index.json"
            or self.index_manifest.schema_ref != MIXED_EMBEDDING_INDEX_SCHEMA_REF
            or self.index_manifest.media_type != "application/json"
        ):
            raise ValueError("SIMILARITY_INDEX_V2_POINTER_INVALID")
        return self


class SimilarityViewSelectionV2(_MixedContextValue):
    view: ExperimentView
    recipe: ExperimentViewRecipe
    index: SimilarityIndexPinV2 | None


class SimilarityContextRequestV2(_MixedContextValue):
    schema_version: Literal["system-rag-similarity-request/2.0"] = (
        "system-rag-similarity-request/2.0"
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
    views: tuple[SimilarityViewSelectionV2, ...] = Field(min_length=1, max_length=3)
    vector_mode: Literal["OPTIONAL", "REQUIRED"]
    maximum_sources: int = Field(ge=1, le=1024, strict=True)
    top_k: int = Field(ge=1, le=64, strict=True)
    request_sha256: Sha256

    @model_validator(mode="before")
    @classmethod
    def schema_first(cls, value: object) -> object:
        return similarity_contract_document(
            value, "system-rag-similarity-context-v2", MAX_SIMILARITY_CONTEXT_BYTES
        )

    @model_validator(mode="after")
    def exact_scope(self) -> SimilarityContextRequestV2:
        indexes = tuple(row.index for row in self.views if row.index is not None)
        selected = tuple(row.view for row in self.views)
        if (
            self.graph_snapshot.manifest_artifact.sha256 != self.graph_snapshot.manifest_sha256
            or any(
                values != tuple(sorted(set(values)))
                for values in (self.source_classes, self.topics, self.unit_ids)
            )
            or self.anchor.source.source_class not in self.source_classes
            or selected != tuple(view for view in VIEWS if view in selected)
            or len({(row.index_id, row.index_revision_id) for row in indexes}) != len(indexes)
            or any(
                row.spaces != indexes[0].spaces
                or row.storage_partition != indexes[0].storage_partition
                for row in indexes
            )
            or self.request_sha256
            != content_sha256(self.model_dump(mode="json", exclude={"request_sha256"}))
        ):
            raise ValueError("SIMILARITY_REQUEST_V2_SCOPE_INVALID")
        return self


class AcceptedSimilarityCandidateV2(_MixedContextValue):
    evidence_kind: Literal["ACCEPTED_SOLUTION_ANALYSIS"] = "ACCEPTED_SOLUTION_ANALYSIS"
    source: PopulationSource
    profile: InferenceTransferProfilePointer
    solution_evidence: KnowledgeSolutionEvidencePointer
    observations: tuple[SimilarityObservation, ...] = Field(min_length=1, max_length=4)
    explanation: SimilarityModelExplanation | None


class RegisteredReviewSimilarityCandidateV2(_MixedContextValue):
    evidence_kind: Literal["REGISTERED_ITEM_REVIEW_SOLUTION"] = "REGISTERED_ITEM_REVIEW_SOLUTION"
    source: PopulationSource
    profile: RegisteredReviewProfilePointer
    review_evidence: RegisteredItemReviewSolutionEvidence
    observations: tuple[SimilarityObservation, ...] = Field(min_length=1, max_length=4)
    explanation: None

    @model_validator(mode="after")
    def exact_review_source(self) -> RegisteredReviewSimilarityCandidateV2:
        if (
            self.source.source_class != "APPROVED_ITEM"
            or self.source != self.review_evidence.source
        ):
            raise ValueError("SIMILARITY_REVIEW_SOURCE_INVALID")
        return self


type SimilarityCandidateV2 = Annotated[
    AcceptedSimilarityCandidateV2 | RegisteredReviewSimilarityCandidateV2,
    Field(discriminator="evidence_kind"),
]


class SimilarityPopulationV2(_MixedContextValue):
    authorized_source_count: int = Field(ge=0, le=1024, strict=True)
    authorized_source_set_sha256: Sha256
    available_profile_count: int = Field(ge=0, le=1024, strict=True)
    available_profile_set_sha256: Sha256
    missing_evidence_count: int = Field(ge=0, le=1024, strict=True)
    truncated: bool = Field(strict=True)
    views: tuple[SimilarityViewCoverage, ...] = Field(min_length=1, max_length=3)

    @model_validator(mode="after")
    def exact_denominators(self) -> SimilarityPopulationV2:
        selected = tuple(row.view for row in self.views)
        if (
            self.available_profile_count + self.missing_evidence_count
            != self.authorized_source_count
            or selected != tuple(view for view in VIEWS if view in selected)
            or any(
                row.status != "UNAVAILABLE"
                and (
                    row.available_binding_count is None
                    or row.missing_view_count is None
                    or row.available_binding_count + row.missing_view_count
                    != self.available_profile_count
                    or (row.status == "READY" and row.missing_view_count != 0)
                    or (row.status == "PARTIAL" and row.missing_view_count == 0)
                )
                for row in self.views
            )
        ):
            raise ValueError("SIMILARITY_POPULATION_V2_INVALID")
        return self


class SimilarityContextV2(_MixedContextValue):
    schema_version: Literal["system-rag-similarity-context/2.0"] = (
        "system-rag-similarity-context/2.0"
    )
    request: SimilarityContextRequestV2
    status: Literal["READY", "PARTIAL", "EMPTY", "UNAVAILABLE", "FAILED"]
    population: SimilarityPopulationV2 | None
    query_execution: ReferenceQueryExecutionPointer | None
    graph_evidence: ArtifactMemberPointer | None
    candidates: tuple[SimilarityCandidateV2, ...] = Field(max_length=64)
    limitations: tuple[SimilarityLimitationV2, ...] = Field(min_length=1, max_length=8)
    error_code: SimilarityFailureCode | None
    context_sha256: Sha256

    @model_validator(mode="before")
    @classmethod
    def schema_first(cls, value: object) -> object:
        return similarity_contract_document(
            value, "system-rag-similarity-context-v2", MAX_SIMILARITY_CONTEXT_BYTES
        )

    @model_validator(mode="after")
    def exact_observations(self) -> SimilarityContextV2:
        if (
            len(set(self.limitations)) != len(self.limitations)
            or "REFERENCE_ANCHOR_NOT_PRIVATE_INTENT" not in self.limitations
            or self.context_sha256
            != content_sha256(self.model_dump(mode="json", exclude={"context_sha256"}))
        ):
            raise ValueError("SIMILARITY_CONTEXT_V2_HASH_INVALID")
        if self.status == "FAILED":
            return self
        population = self.population
        assert population is not None
        selections = {row.view: row for row in self.request.views}
        coverage = {row.view: row for row in population.views}
        if (
            population.authorized_source_count > self.request.maximum_sources
            or len(self.candidates) > min(self.request.top_k, population.available_profile_count)
            or tuple(coverage) != tuple(selections)
        ):
            raise ValueError("SIMILARITY_CONTEXT_V2_SCOPE_INVALID")
        for row in population.views:
            if (
                (row.status != "UNAVAILABLE" and selections[row.view].index is None)
                or (row.status == "UNAVAILABLE" and "VECTOR_NOT_AVAILABLE" not in self.limitations)
                or (
                    self.request.anchor.profile is None
                    and (row.status != "UNAVAILABLE" or row.reason != "ANCHOR_REPORT_MISSING")
                )
                or (
                    row.reason == "ANCHOR_REPORT_MISSING"
                    and self.request.anchor.profile is not None
                )
                or (row.reason == "INDEX_NOT_PREPARED" and selections[row.view].index is not None)
            ):
                raise ValueError("SIMILARITY_CONTEXT_V2_COVERAGE_INVALID")
        for condition, limitation in (
            (bool(population.missing_evidence_count), "PARTIAL_EVIDENCE_COVERAGE"),
            (population.truncated, "BOUNDED_SCOPE_TRUNCATED"),
            (any(row.missing_view_count for row in population.views), "PARTIAL_VIEW_COVERAGE"),
        ):
            if condition and limitation not in self.limitations:
                raise ValueError("SIMILARITY_CONTEXT_V2_LIMITATION_MISSING")
        revisions = tuple(row.source.item_revision_id for row in self.candidates)
        if (
            len(set(revisions)) != len(revisions)
            or self.request.anchor.source.item_revision_id in revisions
        ):
            raise ValueError("SIMILARITY_CONTEXT_V2_DUPLICATE")
        channel_ranks: set[tuple[str, str, int]] = set()
        vector_count = 0
        for candidate in self.candidates:
            if candidate.source.source_class not in self.request.source_classes:
                raise ValueError("SIMILARITY_CONTEXT_V2_SOURCE_INVALID")
            channels: set[tuple[str, str]] = set()
            for observation in candidate.observations:
                view = (
                    observation.view if isinstance(observation, SimilarityVectorObservation) else ""
                )
                channel = (observation.channel, view)
                rank = (*channel, observation.rank)
                if channel in channels or rank in channel_ranks:
                    raise ValueError("SIMILARITY_CONTEXT_V2_RANK_INVALID")
                channels.add(channel)
                channel_ranks.add(rank)
                if isinstance(observation, SimilarityVectorObservation):
                    vector_count += 1
                    selected = selections.get(observation.view)
                    covered = coverage.get(observation.view)
                    if (
                        selected is None
                        or selected.index is None
                        or covered is None
                        or (
                            covered.status in {"EMPTY", "UNAVAILABLE"}
                            or observation.rank > covered.scored_count
                            or self.query_execution is None
                        )
                    ):
                        raise ValueError("SIMILARITY_CONTEXT_V2_VECTOR_INVALID")
                    if (
                        observation.query_row.shard_manifest.artifact_id,
                        observation.query_row.shard_manifest.artifact_revision_id,
                    ) != (
                        self.query_execution.result_member.artifact_id,
                        self.query_execution.result_member.artifact_revision_id,
                    ):
                        raise ValueError("SIMILARITY_CONTEXT_V2_EXECUTION_INVALID")
        unavailable = any(row.status == "UNAVAILABLE" for row in population.views)
        partial = bool(
            unavailable
            or population.missing_evidence_count
            or population.truncated
            or any(row.missing_view_count for row in population.views)
        )
        if (
            any(row.scored_count for row in population.views) != (self.query_execution is not None)
            or (
                self.request.vector_mode == "REQUIRED"
                and (unavailable or self.query_execution is None)
                and self.status not in {"UNAVAILABLE", "EMPTY"}
            )
            or (self.status == "READY" and (partial or not vector_count))
            or (self.status == "PARTIAL" and not partial)
            or (
                self.status in {"EMPTY", "UNAVAILABLE"}
                and "NO_RELATED_CANDIDATES" not in self.limitations
            )
            or (self.status == "UNAVAILABLE" and not unavailable)
            or (self.status == "EMPTY" and any(row.scored_count for row in population.views))
        ):
            raise ValueError("SIMILARITY_CONTEXT_V2_STATUS_INVALID")
        if self.graph_evidence is not None and (
            self.graph_evidence.member_path != "evidence/manifest.json"
            or self.graph_evidence.media_type != "application/json"
            or self.graph_evidence.schema_ref
            != "eom://schemas/knowledge/evidence-bundle-manifest/5.0"
        ):
            raise ValueError("SIMILARITY_CONTEXT_V2_GRAPH_EVIDENCE_INVALID")
        return self


type SupportedSimilarityContextRequest = SimilarityContextRequest | SimilarityContextRequestV2
type SupportedSimilarityContext = Annotated[
    SimilarityContext | SimilarityContextV2, Field(discriminator="schema_version")
]


def parse_similarity_context_request_v2(value: object) -> SimilarityContextRequestV2:
    return SimilarityContextRequestV2.model_validate(value)


def parse_similarity_context_v2(value: object) -> SimilarityContextV2:
    return SimilarityContextV2.model_validate(value)


def parse_supported_similarity_context_request(value: object) -> SupportedSimilarityContextRequest:
    raw = raw_similarity_contract_value(value)
    if isinstance(raw, dict) and raw.get("schema_version") == "system-rag-similarity-request/2.0":
        return parse_similarity_context_request_v2(raw)
    return parse_similarity_context_request(raw)


def parse_supported_similarity_context(value: object) -> SupportedSimilarityContext:
    raw = raw_similarity_contract_value(value)
    if isinstance(raw, dict) and raw.get("schema_version") == "system-rag-similarity-context/2.0":
        return parse_similarity_context_v2(raw)
    return parse_similarity_context(raw)


def validate_deliverable_similarity_context_v2(
    context: SimilarityContextV2, *, expected_request: SimilarityContextRequestV2
) -> SimilarityContextV2:
    checked = parse_similarity_context_v2(context)
    request = parse_similarity_context_request_v2(expected_request)
    if checked.request != request or checked.status == "FAILED":
        raise ValueError("SIMILARITY_CONTEXT_DELIVERY_INVALID")
    if request.vector_mode == "REQUIRED" and (
        checked.status == "UNAVAILABLE"
        or checked.query_execution is None
        or checked.population is None
        or any(row.status == "UNAVAILABLE" for row in checked.population.views)
    ):
        raise ValueError("SIMILARITY_CONTEXT_REQUIRED_VECTOR_UNAVAILABLE")
    return checked


def validate_similarity_index_pin_v2(
    selection: SimilarityViewSelectionV2,
    pointer: ArtifactMemberPointer,
    manifest: MixedEmbeddingIndexManifest,
) -> None:
    selection = SimilarityViewSelectionV2.model_validate(raw_similarity_contract_value(selection))
    pointer = ArtifactMemberPointer.model_validate(raw_similarity_contract_value(pointer))
    manifest = MixedEmbeddingIndexManifest.model_validate(raw_similarity_contract_value(manifest))
    pin = selection.index
    if pin is None or (
        pointer != pin.index_manifest
        or manifest.index_id != pin.index_id
        or manifest.index_revision_id != pin.index_revision_id
        or manifest.index_sha256 != pin.index_sha256
        or manifest.storage_partition != pin.storage_partition
        or manifest.space != pin.spaces.document
        or manifest.view != selection.view
        or manifest.recipe != selection.recipe
    ):
        raise ValueError("SIMILARITY_INDEX_V2_PIN_MISMATCH")


def validate_similarity_query_execution_v2(
    context: SimilarityContextV2,
    request: SupportedReferenceQueryInput,
    result: EmbeddingReferenceQueryResult,
    result_member: ArtifactMemberPointer,
    shard_member: ArtifactMemberPointer,
) -> None:
    context = parse_similarity_context_v2(context)
    request = parse_supported_reference_query_input(request)
    validate_supported_reference_query_result(request, result)
    result_member = ArtifactMemberPointer.model_validate(
        raw_similarity_contract_value(result_member)
    )
    shard_member = ArtifactMemberPointer.model_validate(raw_similarity_contract_value(shard_member))
    expected = ReferenceQueryExecutionPointer(
        job_id=request.job_id,
        query_request_id=request.query_request_id,
        request_sha256=request.request_sha256,
        input_set_sha256=request.input_set_sha256,
        result_member=result_member,
        result_sha256=result.result_sha256,
    )
    if (
        context.query_execution != expected
        or request.context_request_sha256 != context.request.request_sha256
        or (
            result_member.schema_ref != REFERENCE_QUERY_RESULT_REF
            or (shard_member.artifact_id, shard_member.artifact_revision_id)
            != (result_member.artifact_id, result_member.artifact_revision_id)
            or shard_member.member_path != "shard.json"
            or shard_member.schema_ref != "eom://schemas/knowledge/embedding-vector-shard/1.0"
            or shard_member.media_type != "application/json"
        )
    ):
        raise ValueError("SIMILARITY_QUERY_V2_EXECUTION_MISMATCH")
    selections = {row.view: row for row in context.request.views}
    rows = {row.view: row for row in result.view_rows}
    for row in request.rows:
        selected = selections.get(row.view)
        if (
            selected is None
            or selected.index is None
            or (
                selected.index.spaces != request.spaces
                or selected.recipe != request.recipe
                or selected.index.storage_partition != row.encoding.storage_partition
            )
        ):
            raise ValueError("SIMILARITY_QUERY_V2_VIEW_MISMATCH")
    for candidate in context.candidates:
        for observation in candidate.observations:
            if isinstance(observation, SimilarityVectorObservation):
                result_row = rows.get(observation.view)
                if (
                    result_row is None
                    or observation.query_row.shard_manifest != shard_member
                    or observation.query_row.row_index != result_row.row_index
                    or observation.query_row.encoding_sha256 != result_row.encoding_sha256
                ):
                    raise ValueError("SIMILARITY_QUERY_V2_ROW_MISMATCH")
