"""Frozen staged experiment values; none of these values grants source access."""

from __future__ import annotations

from typing import Annotated, Literal

from eom_identifiers import content_sha256
from pydantic import Field, model_validator

from eom_catalog_contracts.inference_transfer_text import concrete_profile_text
from eom_catalog_contracts.item_inference_transfer import (
    InferenceTransferProfile,
    InferenceTransferProfilePointer,
    LocalEmbeddingModelSpec,
    TransferText,
)
from eom_catalog_contracts.knowledge import (
    ApprovedItemKnowledgeSourceV2,
    ApprovedPastExamItemKnowledgeSourceV3,
    KnowledgeAnalysisSourceArtifactMemberV2,
    KnowledgeGraphSnapshotPointer,
)
from eom_catalog_contracts.models import ActorId, FrozenModel, Sha256, UtcDatetime

type ExperimentView = Literal["CONTENT_ONLY", "CONCRETE_FACETS", "METADATA_ONLY"]
VIEWS: tuple[ExperimentView, ...] = ("CONTENT_ONLY", "CONCRETE_FACETS", "METADATA_ONLY")
type PopulationSource = ApprovedItemKnowledgeSourceV2 | ApprovedPastExamItemKnowledgeSourceV3
type BoundedLimitation = Annotated[TransferText, Field(min_length=1, max_length=1000)]
type ExperimentDataProvenance = Literal["AUTHORIZED_CORPUS_SNAPSHOT", "TEST_ONLY_SYNTHETIC"]


def profile_key(pointer: InferenceTransferProfilePointer) -> tuple[str, str, str]:
    return pointer.profile_id, pointer.profile_revision_id, pointer.profile_sha256


def profile_set_sha256(pointers: tuple[InferenceTransferProfilePointer, ...]) -> str:
    return content_sha256(
        [pointer.model_dump(mode="json") for pointer in sorted(pointers, key=profile_key)]
    )


def population_sha256(sources: tuple[PopulationSource, ...]) -> str:
    return content_sha256(
        [
            source.model_dump(mode="json")
            for source in sorted(sources, key=lambda s: s.item_revision_id)
        ]
    )


def _hash(value: FrozenModel, name: str) -> None:
    if getattr(value, name) != content_sha256(value.model_dump(mode="json", exclude={name})):
        raise ValueError(f"{name} differs from canonical experiment content")


class ExperimentViewRecipe(FrozenModel):
    schema_version: Literal["inference-transfer-view-recipe/1.0"] = (
        "inference-transfer-view-recipe/1.0"
    )
    content: Literal["CANONICAL_ITEM_TEXT_NO_SOLUTION"] = "CANONICAL_ITEM_TEXT_NO_SOLUTION"
    facets: Literal["EXACT_PROFILE_CLAIMS"] = "EXACT_PROFILE_CLAIMS"
    metadata: Literal["SORTED_ACCEPTED_FIELDS"] = "SORTED_ACCEPTED_FIELDS"
    overflow: Literal["REJECT_OVERFLOW"] = "REJECT_OVERFLOW"
    maximum_text_bytes: Literal[262144] = 262144
    ranking: Literal["EXACT_FLOAT64_COSINE_REF_TIES"] = "EXACT_FLOAT64_COSINE_REF_TIES"
    recipe_sha256: Sha256

    @model_validator(mode="after")
    def canonical(self) -> ExperimentViewRecipe:
        _hash(self, "recipe_sha256")
        return self


class ExperimentMetadataField(FrozenModel):
    key: Literal[
        "SCIENCE_DOMAIN",
        "CONCEPT",
        "OBSERVABLE",
        "FORMULA",
        "ASSESSMENT_PATTERN",
        "MATERIAL_FORM",
        "CURRICULUM_UNIT",
        "DIFFICULTY",
    ]
    value: TransferText = Field(min_length=1, max_length=512)
    basis: Literal["ORIGINAL_ITEM", "ACCEPTED_SOLUTION"]
    source_sha256: Sha256


class CanonicalExperimentItemText(FrozenModel):
    text: TransferText = Field(max_length=262144)
    original_source: KnowledgeAnalysisSourceArtifactMemberV2
    renderer_version: Literal["canonical-item-text-no-solution/1.0"] = (
        "canonical-item-text-no-solution/1.0"
    )
    text_sha256: Sha256

    @model_validator(mode="after")
    def canonical(self) -> CanonicalExperimentItemText:
        if self.text_sha256 != content_sha256(self.text):
            raise ValueError("canonical Item text hash differs")
        return self


class StagedExperimentEntry(FrozenModel):
    profile: InferenceTransferProfile
    content: CanonicalExperimentItemText | None
    metadata: tuple[ExperimentMetadataField, ...] = Field(max_length=32)
    limitations: tuple[BoundedLimitation, ...] = Field(max_length=32)

    @model_validator(mode="after")
    def source_closure(self) -> StagedExperimentEntry:
        source = self.profile.source_basis.source.artifact_member
        if self.content is not None and self.content.original_source != source:
            raise ValueError("Item text and admitted profile source differ")
        metadata_keys = tuple((field.key, field.value, field.basis) for field in self.metadata)
        if metadata_keys != tuple(sorted(set(metadata_keys))):
            raise ValueError("metadata must be sorted and unique")
        for field in self.metadata:
            expected = (
                source.sha256
                if field.basis == "ORIGINAL_ITEM"
                else self.profile.source_basis.solution_evidence.solution_report.sha256
            )
            if field.source_sha256 != expected:
                raise ValueError("metadata origin differs from exact source/report")
        if len(self.limitations) != len(set(self.limitations)):
            raise ValueError("entry limitations must be unique")
        return self


def experiment_view_text(entry: StagedExperimentEntry, view: ExperimentView) -> str | None:
    """The pinned view recipe is a pure value transformation, not a source resolver."""
    if view == "CONTENT_ONLY":
        return None if entry.content is None else entry.content.text
    if view == "CONCRETE_FACETS":
        return concrete_profile_text(entry.profile)
    if view == "METADATA_ONLY":
        return "\n".join(f"{field.key}: {field.value}" for field in entry.metadata)
    raise ValueError("INFERENCE_EXPERIMENT_VIEW_INVALID")


MAX_GRAPH_BASELINE_CANDIDATES = 64


class SuppliedGraphBaseline(FrozenModel):
    query: InferenceTransferProfilePointer
    command_sha256: Sha256
    result_sha256: Sha256
    provenance: Literal["SUPPORTED_GRAPH_LEXICAL_SUPPLIED_BY_PRODUCER"] = (
        "SUPPORTED_GRAPH_LEXICAL_SUPPLIED_BY_PRODUCER"
    )
    ordered_candidates: tuple[InferenceTransferProfilePointer, ...] = Field(
        max_length=MAX_GRAPH_BASELINE_CANDIDATES
    )

    @model_validator(mode="after")
    def canonical(self) -> SuppliedGraphBaseline:
        if len(set(self.ordered_candidates)) != len(self.ordered_candidates):
            raise ValueError("Graph baseline repeats a candidate")
        if self.query in self.ordered_candidates:
            raise ValueError("Graph baseline contains its query")
        _hash(self, "result_sha256")
        return self


class ExperimentBudget(FrozenModel):
    maximum_profiles: int = Field(default=1024, ge=1, le=1024, strict=True)
    maximum_queries: int = Field(default=16, ge=1, le=16, strict=True)
    top_k: int = Field(default=8, ge=1, le=64, strict=True)
    minimum_common_candidates: int = Field(default=8, ge=1, le=1023, strict=True)
    maximum_input_bytes: int = Field(default=64 * 1024**2, ge=1024, le=64 * 1024**2, strict=True)
    maximum_encoded_texts: int = Field(default=3072, ge=1, le=3072, strict=True)
    batch_size: int = Field(default=4, ge=1, le=16, strict=True)
    threads: int = Field(default=4, ge=1, le=16, strict=True)


class ExperimentAdmissionScope(FrozenModel):
    actor_id: ActorId
    graph_snapshot: KnowledgeGraphSnapshotPointer
    policy_revision_id: str = Field(pattern=r"^accessrev_[0-9a-f]{32}$")
    population_scope: Literal["ALL_ADMITTED_GRAPH_ITEMS", "OCCURRENCE_BACKED_PAST_EXAM"]
    policy_sha256: Sha256
    projection_version: Literal["accepted-solution-comparison/1.0"] = (
        "accepted-solution-comparison/1.0"
    )
    population_sources: tuple[PopulationSource, ...] = Field(min_length=1, max_length=1024)
    population_sha256: Sha256
    eligible_profile_set_sha256: Sha256
    data_provenance: ExperimentDataProvenance
    producer_admission: Literal["CATALOG_AUTHORIZED_SNAPSHOT", "SYNTHETIC_NON_AUTHORITATIVE"]

    @model_validator(mode="after")
    def canonical(self) -> ExperimentAdmissionScope:
        revisions = tuple(source.item_revision_id for source in self.population_sources)
        if revisions != tuple(sorted(set(revisions))):
            raise ValueError("source population must be sorted and unique")
        if self.population_sha256 != population_sha256(self.population_sources):
            raise ValueError("source population hash differs")
        expected = (
            "CATALOG_AUTHORIZED_SNAPSHOT"
            if self.data_provenance == "AUTHORIZED_CORPUS_SNAPSHOT"
            else "SYNTHETIC_NON_AUTHORITATIVE"
        )
        if self.producer_admission != expected:
            raise ValueError("data origin and producer admission claim differ")
        if self.population_scope == "OCCURRENCE_BACKED_PAST_EXAM" and any(
            source.source_class != "PAST_EXAM" for source in self.population_sources
        ):
            raise ValueError("past-exam scope contains another source class")
        return self


class InferenceTransferExperimentRequest(FrozenModel):
    schema_version: Literal["inference-transfer-experiment-request/1.0"] = (
        "inference-transfer-experiment-request/1.0"
    )
    experiment_id: str = Field(pattern=r"^embeddingexperiment_[0-9a-f]{32}$")
    experiment_revision_id: str = Field(pattern=r"^embeddingexperimentrev_[0-9a-f]{32}$")
    scope: ExperimentAdmissionScope
    model_spec: LocalEmbeddingModelSpec
    recipe: ExperimentViewRecipe
    entries: tuple[StagedExperimentEntry, ...] = Field(min_length=1, max_length=1024)
    queries: tuple[InferenceTransferProfilePointer, ...] = Field(min_length=1, max_length=16)
    baselines: tuple[SuppliedGraphBaseline, ...] = Field(max_length=16)
    budget: ExperimentBudget
    request_sha256: Sha256

    @model_validator(mode="after")
    def closed_admission(self) -> InferenceTransferExperimentRequest:
        pointers = tuple(
            InferenceTransferProfilePointer.from_profile(entry.profile) for entry in self.entries
        )
        if tuple(map(profile_key, pointers)) != tuple(sorted(set(map(profile_key, pointers)))):
            raise ValueError("staged profiles must be sorted and unique")
        source_map = {source.item_revision_id: source for source in self.scope.population_sources}
        item_revisions: set[str] = set()
        for entry in self.entries:
            basis = entry.profile.source_basis
            source = source_map.get(basis.source.item_revision_id)
            if source is None or (source.source_class, source.item_id, source.artifact_member) != (
                basis.source.source_class,
                basis.source.item_id,
                basis.source.artifact_member,
            ):
                raise ValueError("profile source is outside admitted population")
            if basis.source.item_revision_id in item_revisions:
                raise ValueError("multiple profiles for one source revision")
            item_revisions.add(basis.source.item_revision_id)
            if basis.graph_snapshot != self.scope.graph_snapshot:
                raise ValueError("profile Graph pin differs from admitted scope")
        if self.scope.eligible_profile_set_sha256 != profile_set_sha256(pointers):
            raise ValueError("eligible profile set hash differs")
        if tuple(map(profile_key, self.queries)) != tuple(
            sorted(set(map(profile_key, self.queries)))
        ) or not set(self.queries).issubset(pointers):
            raise ValueError("queries must be exact canonical admitted profiles")
        if (
            len(self.entries) > self.budget.maximum_profiles
            or len(self.queries) > self.budget.maximum_queries
        ):
            raise ValueError("experiment exceeds its profile/query budget")
        baseline_queries = tuple(row.query for row in self.baselines)
        if len(set(baseline_queries)) != len(baseline_queries) or not set(
            baseline_queries
        ).issubset(self.queries):
            raise ValueError("baseline query is duplicate or unrequested")
        if any(not set(row.ordered_candidates).issubset(pointers) for row in self.baselines):
            raise ValueError("baseline candidate is outside admitted profile set")
        if self.model_spec.query_prefix != self.model_spec.document_prefix:
            raise ValueError("encode-once requires symmetric prefixes")
        _hash(self, "request_sha256")
        return self


class ExperimentTokenCoverage(FrozenModel):
    profile: InferenceTransferProfilePointer
    view: ExperimentView
    text_sha256: Sha256
    utf8_bytes: int = Field(ge=0, le=4 * 1024**2, strict=True)
    token_count: int | None = Field(ge=0, le=4 * 1024**2, strict=True)
    status: Literal[
        "ENCODABLE", "TOKEN_OVERFLOW", "BYTE_LIMIT_EXCEEDED", "EMPTY", "MISSING_SOURCE_VIEW"
    ]

    @model_validator(mode="after")
    def explicit_measurement(self) -> ExperimentTokenCoverage:
        if (self.status in {"ENCODABLE", "TOKEN_OVERFLOW"}) != (self.token_count is not None):
            raise ValueError("token count and measurement status differ")
        return self


class ExperimentRank(FrozenModel):
    profile: InferenceTransferProfilePointer
    rank: int = Field(ge=1, le=64, strict=True)
    cosine_millionths: int = Field(ge=-1_000_000, le=1_000_000, strict=True)


class ExperimentQueryResult(FrozenModel):
    query: InferenceTransferProfilePointer
    view: ExperimentView
    ranks: tuple[ExperimentRank, ...] = Field(max_length=64)
    ranking_milliseconds: int = Field(ge=0, le=86_400_000, strict=True)

    @model_validator(mode="after")
    def canonical(self) -> ExperimentQueryResult:
        if tuple(row.rank for row in self.ranks) != tuple(range(1, len(self.ranks) + 1)):
            raise ValueError("rank ordinals must be contiguous")
        if len({row.profile for row in self.ranks}) != len(self.ranks) or any(
            row.profile == self.query for row in self.ranks
        ):
            raise ValueError("ranking repeats a candidate or contains its query")
        return self


class ExperimentMeasurements(FrozenModel):
    model_load_milliseconds: int = Field(ge=0, le=86_400_000, strict=True)
    token_measurement_milliseconds: int = Field(ge=0, le=86_400_000, strict=True)
    encoding_milliseconds: int = Field(ge=0, le=86_400_000, strict=True)
    peak_rss_kib_linux: int = Field(ge=0, le=2**31, strict=True)
    encoding_requests_started: int = Field(ge=0, le=3072, strict=True)
    encoding_requests_completed: int = Field(ge=0, le=3072, strict=True)
    requested_text_count: int = Field(ge=0, le=3072, strict=True)
    encoded_text_count: int = Field(ge=0, le=3072, strict=True)


class InferenceTransferExperimentResult(FrozenModel):
    schema_version: Literal["inference-transfer-experiment-result/1.0"] = (
        "inference-transfer-experiment-result/1.0"
    )
    execution_id: str = Field(pattern=r"^embeddingexecution_[0-9a-f]{32}$")
    created_at: UtcDatetime
    request_sha256: Sha256
    input_profile_set_sha256: Sha256
    model_manifest_sha256: Sha256
    actual_model_manifest_sha256: Sha256 | None
    view_recipe_sha256: Sha256
    status: Literal["MEASURED", "INSUFFICIENT_ENCODING_COVERAGE"]
    common_profiles: tuple[InferenceTransferProfilePointer, ...] = Field(max_length=1024)
    common_profile_set_sha256: Sha256
    coverage: tuple[ExperimentTokenCoverage, ...] = Field(min_length=3, max_length=3072)
    query_results: tuple[ExperimentQueryResult, ...] = Field(max_length=48)
    baseline_status: Literal["NOT_MATERIALIZED", "SUPPLIED_NOT_REEXECUTED"]
    measurements: ExperimentMeasurements
    backend_kind: Literal["PINNED_MODEL", "TEST_ONLY"]
    data_provenance: ExperimentDataProvenance
    current_authorization: Literal["NOT_VERIFIED_BY_HARNESS"] = "NOT_VERIFIED_BY_HARNESS"
    human_transfer_review: Literal["NOT_EVALUATED"] = "NOT_EVALUATED"
    production_activation: Literal["NOT_PERFORMED"] = "NOT_PERFORMED"
    limitations: tuple[BoundedLimitation, ...] = Field(max_length=32)
    result_sha256: Sha256

    @model_validator(mode="after")
    def closed_result(self) -> InferenceTransferExperimentResult:
        if tuple(map(profile_key, self.common_profiles)) != tuple(
            sorted(set(map(profile_key, self.common_profiles)))
        ):
            raise ValueError("common profile set must be canonical")
        if self.common_profile_set_sha256 != profile_set_sha256(self.common_profiles):
            raise ValueError("common profile set hash differs")
        keys = tuple((profile_key(row.profile), row.view) for row in self.coverage)
        if len(set(keys)) != len(keys):
            raise ValueError("coverage repeats an exact profile/view")
        populations = {
            view: {row.profile for row in self.coverage if row.view == view} for view in VIEWS
        }
        if any(populations[view] != populations[VIEWS[0]] for view in VIEWS):
            raise ValueError("views do not share the same measured population")
        common = set.intersection(
            *(
                {
                    row.profile
                    for row in self.coverage
                    if row.view == view and row.status == "ENCODABLE"
                }
                for view in VIEWS
            )
        )
        if set(self.common_profiles) != common:
            raise ValueError("common pool differs from all-view encodable intersection")
        if (self.backend_kind == "PINNED_MODEL") != (self.actual_model_manifest_sha256 is not None):
            raise ValueError("fake backend must not claim actual model identity")
        if (
            self.actual_model_manifest_sha256 is not None
            and self.actual_model_manifest_sha256 != self.model_manifest_sha256
        ):
            raise ValueError("actual model differs from requested pinned manifest")
        if self.status == "INSUFFICIENT_ENCODING_COVERAGE" and (
            self.query_results or self.measurements.encoded_text_count
        ):
            raise ValueError("insufficient coverage must not run model encoding")
        result_keys = tuple((row.query, row.view) for row in self.query_results)
        if len(set(result_keys)) != len(result_keys):
            raise ValueError("duplicate query/view results")
        if any(
            row.query not in common or any(rank.profile not in common for rank in row.ranks)
            for row in self.query_results
        ):
            raise ValueError("ranking contains profiles outside the common pool")
        _hash(self, "result_sha256")
        return self


def validate_experiment_result(
    request: InferenceTransferExperimentRequest, result: InferenceTransferExperimentResult
) -> None:
    request = InferenceTransferExperimentRequest.model_validate(request.model_dump(mode="json"))
    result = InferenceTransferExperimentResult.model_validate(result.model_dump(mode="json"))
    if (
        result.request_sha256,
        result.input_profile_set_sha256,
        result.model_manifest_sha256,
        result.view_recipe_sha256,
    ) != (
        request.request_sha256,
        request.scope.eligible_profile_set_sha256,
        request.model_spec.manifest_sha256,
        request.recipe.recipe_sha256,
    ):
        raise ValueError("experiment result has different exact request/model/recipe pins")
    pointers = {
        InferenceTransferProfilePointer.from_profile(entry.profile) for entry in request.entries
    }
    if {row.profile for row in result.coverage} != pointers:
        raise ValueError("coverage population differs from admitted request")
    if result.data_provenance != request.scope.data_provenance:
        raise ValueError("result changes staged data origin")
    if result.baseline_status != (
        "SUPPLIED_NOT_REEXECUTED" if request.baselines else "NOT_MATERIALIZED"
    ):
        raise ValueError("result changes supplied baseline availability")
    entry_map = {
        InferenceTransferProfilePointer.from_profile(entry.profile): entry
        for entry in request.entries
    }
    for row in result.coverage:
        text = experiment_view_text(entry_map[row.profile], row.view)
        size = len(text.encode("utf-8")) if text is not None else 0
        if row.text_sha256 != content_sha256(text) or row.utf8_bytes != size:
            raise ValueError("coverage measured a different exact text view")
        expected_status = (
            "MISSING_SOURCE_VIEW"
            if text is None
            else "EMPTY"
            if not text.strip()
            else "BYTE_LIMIT_EXCEEDED"
            if size > request.recipe.maximum_text_bytes
            else None
        )
        if (expected_status is not None and row.status != expected_status) or (
            expected_status is None and row.status not in {"ENCODABLE", "TOKEN_OVERFLOW"}
        ):
            raise ValueError("coverage changes source/empty/byte measurement status")
        if row.status == "ENCODABLE" and (
            row.token_count is None or not 0 < row.token_count <= request.model_spec.maximum_tokens
        ):
            raise ValueError("encodable coverage exceeds pinned token limit")
        if row.status == "TOKEN_OVERFLOW" and (
            row.token_count is None or row.token_count <= request.model_spec.maximum_tokens
        ):
            raise ValueError("overflow coverage does not exceed pinned token limit")
    enough = (
        len(result.common_profiles) - 1 >= request.budget.minimum_common_candidates
        and set(request.queries).issubset(result.common_profiles)
        and len(result.common_profiles) * len(VIEWS) <= request.budget.maximum_encoded_texts
    )
    if (result.status == "MEASURED") != enough:
        raise ValueError("coverage status differs from required common-pool budget")
    if result.status == "MEASURED":
        expected = {
            (query, view)
            for query in request.queries
            if query in result.common_profiles
            for view in VIEWS
        }
        if {(row.query, row.view) for row in result.query_results} != expected:
            raise ValueError("query results do not cover each encodable requested view")
        if any(
            len(row.ranks) != min(request.budget.top_k, len(result.common_profiles) - 1)
            for row in result.query_results
        ):
            raise ValueError("ranking count differs from exact common candidate pool")
        if (
            result.measurements.encoding_requests_started != len(VIEWS)
            or result.measurements.encoding_requests_completed != len(VIEWS)
            or result.measurements.requested_text_count != len(result.common_profiles) * len(VIEWS)
            or result.measurements.encoded_text_count != len(result.common_profiles) * len(VIEWS)
        ):
            raise ValueError("measured result did not encode each view exactly once")
    elif any(
        (
            result.measurements.encoding_requests_started,
            result.measurements.encoding_requests_completed,
            result.measurements.requested_text_count,
            result.measurements.encoded_text_count,
        )
    ):
        raise ValueError("insufficient coverage must not request encodings")
    if result.measurements.encoded_text_count > request.budget.maximum_encoded_texts:
        raise ValueError("result exceeds encoding budget")
