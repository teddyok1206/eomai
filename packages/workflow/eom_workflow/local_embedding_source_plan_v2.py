"""Metadata-only mixed plans; immutable values are never source authority."""

from __future__ import annotations

from typing import Annotated, Literal

from eom_catalog_contracts.embedding_reference_query import raw_similarity_contract_value
from eom_catalog_contracts.inference_transfer_embedding import (
    EmbeddingEncodingIdentity,
    EmbeddingSpace,
    embedding_input_set_sha256,
)
from eom_catalog_contracts.inference_transfer_experiment import (
    ExperimentViewRecipe,
    PopulationSource,
    StagedExperimentEntry,
    experiment_view_text,
    population_sha256,
)
from eom_catalog_contracts.item_inference_transfer import InferenceTransferProfilePointer
from eom_catalog_contracts.knowledge import (
    KnowledgeGraphSnapshotPointer,
    KnowledgeSolutionEvidencePointer,
)
from eom_catalog_contracts.mixed_embedding_index import (
    MIXED_EMBEDDING_PROJECTION_VERSION,
    MixedEmbeddingIndexManifest,
    RegisteredReviewEmbeddingEntry,
    RegisteredReviewEmbeddingSourceBinding,
    registered_review_embedding_text,
)
from eom_catalog_contracts.mixed_embedding_registry import MixedEmbeddingIndexNamespace
from eom_catalog_contracts.models import Sha256
from eom_catalog_contracts.registered_item_review_solution import (
    RegisteredItemReviewSolutionEvidence,
)
from eom_catalog_contracts.registered_review_profile import (
    REGISTERED_REVIEW_EXTRACTOR_VERSION,
    RegisteredReviewProfilePointer,
)
from eom_identifiers import canonical_json_bytes, content_sha256
from pydantic import Field, model_validator

from eom_workflow.local_embedding_source_plan import (
    LocalEmbeddingUnavailableView,
    SourceRevisionId,
    validate_local_embedding_entry_source,
)
from eom_workflow.schemas import (
    LocalEmbeddingAdmissionContractError,
    NativeEmbeddingContract,
    validate_local_embedding_admission_message,
)

LOCAL_EMBEDDING_SOURCE_PLAN_V2_SCHEMA_REF = "eom://schemas/workflow/local-embedding-source-plan/2.0"
type MixedEmbeddingEntry = StagedExperimentEntry | RegisteredReviewEmbeddingEntry
type BaseAnalysisRunId = Annotated[str, Field(pattern=r"^analysisrun_[0-9a-f]{32}$")]


class AcceptedSolutionEncodingDemandV2(NativeEmbeddingContract):
    evidence_kind: Literal["ACCEPTED_SOLUTION_ANALYSIS"] = "ACCEPTED_SOLUTION_ANALYSIS"
    source_revision_id: SourceRevisionId
    base_analysis_run_id: BaseAnalysisRunId
    profile: InferenceTransferProfilePointer
    solution_evidence: KnowledgeSolutionEvidencePointer
    encoding: EmbeddingEncodingIdentity

    @model_validator(mode="after")
    def exact_base(self) -> AcceptedSolutionEncodingDemandV2:
        if self.base_analysis_run_id != self.solution_evidence.base_analysis_run_id:
            raise ValueError("mixed accepted demand differs from its genuine base analysis")
        return self


class RegisteredReviewEncodingDemandV2(NativeEmbeddingContract):
    evidence_kind: Literal["REGISTERED_ITEM_REVIEW_SOLUTION"] = "REGISTERED_ITEM_REVIEW_SOLUTION"
    source_revision_id: SourceRevisionId
    base_analysis_run_id: BaseAnalysisRunId
    profile: RegisteredReviewProfilePointer
    review_evidence: RegisteredItemReviewSolutionEvidence
    encoding: EmbeddingEncodingIdentity

    @model_validator(mode="after")
    def exact_source(self) -> RegisteredReviewEncodingDemandV2:
        if self.source_revision_id != self.review_evidence.source.item_revision_id:
            raise ValueError("mixed review demand differs from its exact registered source")
        return self


type LocalEmbeddingEncodingDemandV2 = Annotated[
    AcceptedSolutionEncodingDemandV2 | RegisteredReviewEncodingDemandV2,
    Field(discriminator="evidence_kind"),
]


class LocalEmbeddingSourcePlanV2(NativeEmbeddingContract):
    schema_version: Literal["local-embedding-source-plan/2.0"] = "local-embedding-source-plan/2.0"
    corpus_id: str = Field(pattern=r"^corpus_[0-9a-f]{32}$")
    graph_snapshot: KnowledgeGraphSnapshotPointer
    access_policy_revision_id: str = Field(pattern=r"^accessrev_[0-9a-f]{32}$")
    access_policy_sha256: Sha256
    namespace: MixedEmbeddingIndexNamespace
    space: EmbeddingSpace
    recipe: ExperimentViewRecipe
    sources: tuple[PopulationSource, ...] = Field(min_length=1, max_length=1024)
    demands: tuple[LocalEmbeddingEncodingDemandV2, ...] = Field(max_length=1024)
    missing_solution_report_revision_ids: tuple[SourceRevisionId, ...] = Field(max_length=1024)
    unavailable_views: tuple[LocalEmbeddingUnavailableView, ...] = Field(max_length=1024)
    source_set_sha256: Sha256
    encoding_set_sha256: Sha256
    plan_sha256: Sha256

    @model_validator(mode="after")
    def exact_plan(self) -> LocalEmbeddingSourcePlanV2:
        sources = tuple(source.item_revision_id for source in self.sources)
        demanded = tuple(demand.source_revision_id for demand in self.demands)
        unavailable = tuple(view.source_revision_id for view in self.unavailable_views)
        missing = self.missing_solution_report_revision_ids
        if any(
            keys != tuple(sorted(set(keys))) for keys in (sources, demanded, unavailable, missing)
        ):
            raise ValueError("mixed source plan identities must be sorted and unique")
        covered = demanded + unavailable + missing
        if len(covered) != len(set(covered)) or set(covered) != set(sources):
            raise ValueError("mixed source plan coverage is missing, foreign or duplicated")
        if (
            self.graph_snapshot.manifest_sha256 != self.graph_snapshot.manifest_artifact.sha256
            or self.space.purpose != "DOCUMENT"
            or self.namespace.space_sha256 != self.space.space_sha256
            or self.namespace.recipe_sha256 != self.recipe.recipe_sha256
            or self.source_set_sha256 != population_sha256(self.sources)
        ):
            raise ValueError("mixed source plan space, recipe, Graph or source pins differ")
        by_source = {source.item_revision_id: source for source in self.sources}
        for demand in self.demands:
            if (
                demand.encoding.storage_partition != self.namespace.storage_partition
                or demand.encoding.space_sha256 != self.space.space_sha256
                or (
                    isinstance(demand, RegisteredReviewEncodingDemandV2)
                    and demand.review_evidence.source != by_source[demand.source_revision_id]
                )
            ):
                raise ValueError("mixed source demand differs from its exact namespace/source")
        unique = {demand.encoding.encoding_sha256: demand.encoding for demand in self.demands}
        if self.encoding_set_sha256 != embedding_input_set_sha256(
            tuple(unique[key] for key in sorted(unique))
        ):
            raise ValueError("mixed source plan unique encoding set differs")
        body = self.model_dump(mode="json")
        if len(canonical_json_bytes(body)) > 64 * 1024**2 or self.plan_sha256 != content_sha256(
            {key: value for key, value in body.items() if key != "plan_sha256"}
        ):
            raise ValueError("mixed source plan canonical hash or byte bound differs")
        return self


def parse_local_embedding_source_plan_v2(value: object) -> LocalEmbeddingSourcePlanV2:
    try:
        document = raw_similarity_contract_value(value)
        validate_local_embedding_admission_message("mixed-source-plan", document)
        return LocalEmbeddingSourcePlanV2.model_validate(document)
    except Exception:
        raise LocalEmbeddingAdmissionContractError("LOCAL_EMBEDDING_CONTRACT_INVALID") from None


def local_embedding_source_plan_v2_bytes(value: LocalEmbeddingSourcePlanV2) -> bytes:
    return canonical_json_bytes(parse_local_embedding_source_plan_v2(value).model_dump(mode="json"))


def validate_local_embedding_entry_source_v2(
    source: PopulationSource,
    entry: MixedEmbeddingEntry,
    *,
    graph_snapshot: KnowledgeGraphSnapshotPointer,
    projection_version: str,
) -> None:
    """Pure original source closure, including an unavailable view; not Graph admission."""
    if projection_version != MIXED_EMBEDDING_PROJECTION_VERSION:
        raise ValueError("mixed entry projection differs from its exact namespace")
    if isinstance(entry, StagedExperimentEntry):
        validate_local_embedding_entry_source(
            source,
            entry,
            graph_snapshot=graph_snapshot,
            projection_version="accepted-solution-comparison/1.0",
        )
        return
    if (
        not isinstance(entry, RegisteredReviewEmbeddingEntry)
        or source != entry.profile.source_basis.source
        or graph_snapshot != entry.profile.source_basis.graph_snapshot
        or entry.profile.extractor_version != REGISTERED_REVIEW_EXTRACTOR_VERSION
    ):
        raise ValueError("mixed entry differs from exact source/Graph/projection values")


def validate_local_embedding_plan_entries_v2(
    plan: LocalEmbeddingSourcePlanV2, entries: tuple[MixedEmbeddingEntry, ...]
) -> None:
    """Exact staged demand closure; current source authority remains the owner boundary."""
    plan = parse_local_embedding_source_plan_v2(plan)
    if type(entries) is not tuple or len(entries) > 1024:
        raise ValueError("mixed staged entry selection is invalid")
    if any(
        type(entry) not in (StagedExperimentEntry, RegisteredReviewEmbeddingEntry)
        for entry in entries
    ):
        raise ValueError("mixed staged entry family is invalid")
    checked = tuple(
        type(entry).model_validate(raw_similarity_contract_value(entry)) for entry in entries
    )
    by_source = {entry.profile.source_basis.source.item_revision_id: entry for entry in checked}
    if len(by_source) != len(checked) or set(by_source) != {
        demand.source_revision_id for demand in plan.demands
    }:
        raise ValueError("mixed staged entries do not exactly cover plan demands")
    sources = {source.item_revision_id: source for source in plan.sources}
    for demand in plan.demands:
        entry, source = by_source[demand.source_revision_id], sources[demand.source_revision_id]
        validate_local_embedding_entry_source_v2(
            source,
            entry,
            graph_snapshot=plan.graph_snapshot,
            projection_version=plan.namespace.projection_version,
        )
        if isinstance(demand, RegisteredReviewEncodingDemandV2):
            if not isinstance(entry, RegisteredReviewEmbeddingEntry) or (
                demand.profile != RegisteredReviewProfilePointer.from_profile(entry.profile)
                or demand.review_evidence != entry.profile.source_basis.review_evidence
            ):
                raise ValueError("mixed demand differs from its original review evidence/profile")
            text = registered_review_embedding_text(entry, plan.namespace.view)
        else:
            if not isinstance(entry, StagedExperimentEntry) or (
                demand.profile != InferenceTransferProfilePointer.from_profile(entry.profile)
                or demand.solution_evidence != entry.profile.source_basis.solution_evidence
            ):
                raise ValueError("mixed demand differs from its original solution evidence/profile")
            text = experiment_view_text(entry, plan.namespace.view)
        if (
            text is None
            or not text.strip()
            or demand.encoding.input_text_sha256 != content_sha256(text)
        ):
            raise ValueError("mixed demand differs from its materialized view text")


def validate_local_embedding_selected_index_coverage_v2(
    plan: LocalEmbeddingSourcePlanV2, index: MixedEmbeddingIndexManifest
) -> None:
    """Compare already validated values without reparsing the whole index in a loop."""
    sources = {value.item_revision_id: value for value in plan.sources}
    bindings = {value.source.item_revision_id: value for value in index.bindings}
    if (
        index.space != plan.space
        or index.storage_partition != plan.namespace.storage_partition
        or index.view != plan.namespace.view
        or index.recipe != plan.recipe
    ):
        raise ValueError("mixed completion index namespace differs")
    for demand in plan.demands:
        binding = bindings.get(demand.source_revision_id)
        if (
            binding is None
            or binding.source != sources[demand.source_revision_id]
            or binding.encoding != demand.encoding
            or binding.profile != demand.profile
            or binding.graph_snapshot != plan.graph_snapshot
            or binding.policy_revision_id != plan.access_policy_revision_id
            or binding.policy_sha256 != plan.access_policy_sha256
        ):
            raise ValueError("mixed completion index does not cover an exact selected demand")
        if isinstance(demand, RegisteredReviewEncodingDemandV2):
            if not isinstance(binding, RegisteredReviewEmbeddingSourceBinding) or (
                binding.review_evidence != demand.review_evidence
                or binding.base_analysis_run_id != demand.base_analysis_run_id
            ):
                raise ValueError("mixed completion index review evidence differs")
        elif isinstance(binding, RegisteredReviewEmbeddingSourceBinding) or (
            binding.solution_evidence != demand.solution_evidence
            or binding.solution_evidence.base_analysis_run_id != demand.base_analysis_run_id
        ):
            raise ValueError("mixed completion index solution evidence differs")
