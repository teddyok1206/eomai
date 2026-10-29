"""Exact public-report demands; no fabricated V10/REVIEW or source authority."""

from typing import Literal, Self

from eom_catalog_contracts.embedding_reference_query import raw_similarity_contract_value
from eom_catalog_contracts.inference_transfer_embedding import (
    EmbeddingEncodingIdentity,
    EmbeddingSpace,
    embedding_input_set_sha256,
)
from eom_catalog_contracts.inference_transfer_experiment import PopulationSource, population_sha256
from eom_catalog_contracts.knowledge import KnowledgeGraphSnapshotPointer
from eom_catalog_contracts.models import Sha256
from eom_catalog_contracts.public_solution_embedding import (
    PublicSolutionEmbeddingEntry,
    PublicSolutionEmbeddingEvidence,
    PublicSolutionEmbeddingRecipe,
)
from eom_catalog_contracts.public_solution_embedding_index import (
    MAX_PUBLIC_SOLUTION_SOURCES,
    PublicSolutionEmbeddingIndex,
    PublicSolutionIndexNamespace,
    PublicSolutionProfilePointer,
)
from eom_identifiers import canonical_json_bytes, content_sha256
from pydantic import Field, model_validator

from eom_workflow.local_embedding_source_plan import SourceRevisionId
from eom_workflow.schemas import NativeEmbeddingContract, validate_local_embedding_admission_message

LOCAL_EMBEDDING_SOURCE_PLAN_V3_SCHEMA_REF = "eom://schemas/workflow/local-embedding-source-plan/3.0"


class PublicSolutionEncodingDemand(NativeEmbeddingContract):
    source_revision_id: SourceRevisionId
    base_analysis_run_id: str = Field(pattern=r"^analysisrun_[0-9a-f]{32}$")
    profile: PublicSolutionProfilePointer
    evidence: PublicSolutionEmbeddingEvidence
    encoding: EmbeddingEncodingIdentity


class PublicSolutionUnavailableView(NativeEmbeddingContract):
    source_revision_id: SourceRevisionId
    reason: Literal["VIEW_NOT_MATERIALIZED", "EMPTY_VIEW", "PUBLIC_SOLUTION_TEXT_LIMIT"]


class LocalEmbeddingSourcePlanV3(NativeEmbeddingContract):
    schema_version: Literal["local-embedding-source-plan/3.0"] = "local-embedding-source-plan/3.0"
    corpus_id: str = Field(pattern=r"^corpus_[0-9a-f]{32}$")
    graph_snapshot: KnowledgeGraphSnapshotPointer
    access_policy_revision_id: str = Field(pattern=r"^accessrev_[0-9a-f]{32}$")
    access_policy_sha256: Sha256
    namespace: PublicSolutionIndexNamespace
    space: EmbeddingSpace
    recipe: PublicSolutionEmbeddingRecipe
    sources: tuple[PopulationSource, ...] = Field(
        min_length=1, max_length=MAX_PUBLIC_SOLUTION_SOURCES
    )
    demands: tuple[PublicSolutionEncodingDemand, ...] = Field(
        max_length=MAX_PUBLIC_SOLUTION_SOURCES
    )
    missing_solution_report_revision_ids: tuple[SourceRevisionId, ...] = Field(
        max_length=MAX_PUBLIC_SOLUTION_SOURCES
    )
    unavailable_views: tuple[PublicSolutionUnavailableView, ...] = Field(
        max_length=MAX_PUBLIC_SOLUTION_SOURCES
    )
    source_set_sha256: Sha256
    encoding_set_sha256: Sha256
    plan_sha256: Sha256

    @model_validator(mode="after")
    def exact_plan(self) -> Self:
        groups = (
            tuple(source.item_revision_id for source in self.sources),
            tuple(demand.source_revision_id for demand in self.demands),
            tuple(view.source_revision_id for view in self.unavailable_views),
            self.missing_solution_report_revision_ids,
        )
        covered = groups[1] + groups[2] + groups[3]
        if (
            any(keys != tuple(sorted(set(keys))) for keys in groups)
            or len(covered) != len(set(covered))
            or set(covered) != set(groups[0])
        ):
            raise ValueError("PUBLIC_SOLUTION_PLAN_COVERAGE_INVALID")
        if (
            self.graph_snapshot.manifest_sha256 != self.graph_snapshot.manifest_artifact.sha256
            or self.space.purpose != "DOCUMENT"
            or self.namespace.space_sha256 != self.space.space_sha256
            or self.namespace.recipe_sha256 != self.recipe.recipe_sha256
            or self.source_set_sha256 != population_sha256(self.sources)
        ):
            raise ValueError("PUBLIC_SOLUTION_PLAN_SCOPE_INVALID")
        for demand in self.demands:
            if (
                demand.encoding.storage_partition != self.namespace.storage_partition
                or demand.encoding.space_sha256 != self.space.space_sha256
            ):
                raise ValueError("PUBLIC_SOLUTION_PLAN_ENCODING_INVALID")
            if (
                demand.evidence.kind == "ACCEPTED_SOLUTION_ANALYSIS"
                and demand.base_analysis_run_id != demand.evidence.solution.base_analysis_run_id
            ):
                raise ValueError("PUBLIC_SOLUTION_PLAN_BASE_INVALID")
        unique = {demand.encoding.encoding_sha256: demand.encoding for demand in self.demands}
        if self.encoding_set_sha256 != embedding_input_set_sha256(
            tuple(unique[key] for key in sorted(unique))
        ):
            raise ValueError("PUBLIC_SOLUTION_PLAN_ENCODING_SET_INVALID")
        if len(
            canonical_json_bytes(self.model_dump(mode="json"))
        ) > 64 * 1024**2 or self.plan_sha256 != content_sha256(
            self.model_dump(mode="json", exclude={"plan_sha256"})
        ):
            raise ValueError("PUBLIC_SOLUTION_PLAN_HASH_INVALID")
        return self


def parse_local_embedding_source_plan_v3(value: object) -> LocalEmbeddingSourcePlanV3:
    document = raw_similarity_contract_value(value)
    validate_local_embedding_admission_message("public-source-plan", document)
    return LocalEmbeddingSourcePlanV3.model_validate(document)


def validate_local_embedding_plan_entries_v3(
    plan: LocalEmbeddingSourcePlanV3, entries: tuple[PublicSolutionEmbeddingEntry, ...]
) -> None:
    plan = parse_local_embedding_source_plan_v3(plan)
    checked = tuple(
        PublicSolutionEmbeddingEntry.model_validate(raw_similarity_contract_value(entry))
        for entry in entries
    )
    by_source = {entry.source.item_revision_id: entry for entry in checked}
    if len(by_source) != len(checked) or set(by_source) != {
        demand.source_revision_id for demand in plan.demands
    }:
        raise ValueError("PUBLIC_SOLUTION_STAGED_SELECTION_INVALID")
    sources = {source.item_revision_id: source for source in plan.sources}
    for demand in plan.demands:
        entry = by_source[demand.source_revision_id]
        if (
            entry.source != sources[demand.source_revision_id]
            or entry.base_analysis_run_id != demand.base_analysis_run_id
            or entry.graph_snapshot != plan.graph_snapshot
            or entry.policy_revision_id != plan.access_policy_revision_id
            or entry.policy_sha256 != plan.access_policy_sha256
            or entry.recipe != plan.recipe
            or PublicSolutionProfilePointer.from_entry(entry) != demand.profile
            or entry.evidence != demand.evidence
            or entry.public_solution.text is None
            or demand.encoding.input_text_sha256 != entry.public_solution.text_sha256
        ):
            raise ValueError("PUBLIC_SOLUTION_STAGED_DEMAND_INVALID")


def validate_local_embedding_selected_index_coverage_v3(
    plan: LocalEmbeddingSourcePlanV3, index: PublicSolutionEmbeddingIndex
) -> None:
    sources = {source.item_revision_id: source for source in plan.sources}
    bindings = {binding.source.item_revision_id: binding for binding in index.bindings}
    if (
        index.space != plan.space
        or index.storage_partition != plan.namespace.storage_partition
        or index.view != plan.namespace.view
        or index.recipe != plan.recipe
    ):
        raise ValueError("PUBLIC_SOLUTION_COMPLETION_NAMESPACE_INVALID")
    for demand in plan.demands:
        binding = bindings.get(demand.source_revision_id)
        if (
            binding is None
            or binding.source != sources[demand.source_revision_id]
            or binding.base_analysis_run_id != demand.base_analysis_run_id
            or binding.encoding != demand.encoding
            or binding.profile != demand.profile
            or binding.evidence != demand.evidence
            or binding.graph_snapshot != plan.graph_snapshot
            or binding.policy_revision_id != plan.access_policy_revision_id
            or binding.policy_sha256 != plan.access_policy_sha256
        ):
            raise ValueError("PUBLIC_SOLUTION_COMPLETION_DEMAND_INVALID")
