"""Exact public-report demands; no fabricated V10/REVIEW or source authority."""

from collections.abc import Sequence
from typing import Any, Literal, Protocol, Self

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
    AcceptedPublicSolutionEvidence,
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
from eom_catalog_contracts.registered_public_solution_embedding import (
    PublicSolutionEncodingEntry,
    RegisteredPublicSolutionEmbeddingEntry,
    RegisteredPublicSolutionEvidence,
)
from eom_catalog_contracts.registered_public_solution_index import (
    PublicSolutionEmbeddingIndexV4,
    RegisteredPublicSolutionProfilePointer,
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


class PublicSolutionDemandShape(Protocol):
    @property
    def source_revision_id(self) -> str: ...

    @property
    def base_analysis_run_id(self) -> str: ...

    @property
    def evidence(self) -> PublicSolutionEmbeddingEvidence | RegisteredPublicSolutionEvidence: ...

    @property
    def profile(self) -> PublicSolutionProfilePointer | RegisteredPublicSolutionProfilePointer: ...

    @property
    def encoding(self) -> EmbeddingEncodingIdentity: ...


class PublicSolutionSourcePlanShape(Protocol):
    """Read-only semantic values shared by exact plan3 and plan4 schemas."""

    @property
    def sources(self) -> Sequence[PopulationSource]: ...

    @property
    def demands(self) -> Sequence[PublicSolutionDemandShape]: ...

    @property
    def unavailable_views(self) -> Sequence[PublicSolutionUnavailableView]: ...

    @property
    def missing_solution_report_revision_ids(self) -> tuple[str, ...]: ...

    @property
    def graph_snapshot(self) -> KnowledgeGraphSnapshotPointer: ...

    @property
    def namespace(self) -> PublicSolutionIndexNamespace: ...

    @property
    def space(self) -> EmbeddingSpace: ...

    @property
    def recipe(self) -> PublicSolutionEmbeddingRecipe: ...

    @property
    def access_policy_revision_id(self) -> str: ...

    @property
    def access_policy_sha256(self) -> str: ...

    @property
    def source_set_sha256(self) -> str: ...

    @property
    def encoding_set_sha256(self) -> str: ...

    @property
    def plan_sha256(self) -> str: ...

    def model_dump(self, *, mode: Literal["json"]) -> dict[str, Any]: ...


def validate_public_solution_plan_values(plan: PublicSolutionSourcePlanShape) -> None:
    """O(N log N) canonical coverage/encoding sets, not source access or compute admission."""
    groups = (
        tuple(source.item_revision_id for source in plan.sources),
        tuple(demand.source_revision_id for demand in plan.demands),
        tuple(view.source_revision_id for view in plan.unavailable_views),
        plan.missing_solution_report_revision_ids,
    )
    covered = groups[1] + groups[2] + groups[3]
    if (
        any(keys != tuple(sorted(set(keys))) for keys in groups)
        or len(covered) != len(set(covered))
        or set(covered) != set(groups[0])
    ):
        raise ValueError("PUBLIC_SOLUTION_PLAN_COVERAGE_INVALID")
    if (
        plan.graph_snapshot.manifest_sha256 != plan.graph_snapshot.manifest_artifact.sha256
        or plan.space.purpose != "DOCUMENT"
        or plan.namespace.space_sha256 != plan.space.space_sha256
        or plan.namespace.recipe_sha256 != plan.recipe.recipe_sha256
        or plan.source_set_sha256 != population_sha256(tuple(plan.sources))
    ):
        raise ValueError("PUBLIC_SOLUTION_PLAN_SCOPE_INVALID")
    sources = {source.item_revision_id: source for source in plan.sources}
    for demand in plan.demands:
        if (
            demand.encoding.storage_partition != plan.namespace.storage_partition
            or demand.encoding.space_sha256 != plan.space.space_sha256
        ):
            raise ValueError("PUBLIC_SOLUTION_PLAN_ENCODING_INVALID")
        evidence = demand.evidence
        if (
            isinstance(evidence, RegisteredPublicSolutionEvidence)
            and sources[demand.source_revision_id].source_class != "APPROVED_ITEM"
        ):
            raise ValueError("PUBLIC_SOLUTION_PLAN_REGISTERED_SOURCE_INVALID")
        if (
            isinstance(evidence, AcceptedPublicSolutionEvidence | RegisteredPublicSolutionEvidence)
            and demand.base_analysis_run_id != evidence.solution.base_analysis_run_id
        ):
            raise ValueError("PUBLIC_SOLUTION_PLAN_BASE_INVALID")
    unique = {demand.encoding.encoding_sha256: demand.encoding for demand in plan.demands}
    if plan.encoding_set_sha256 != embedding_input_set_sha256(
        tuple(unique[key] for key in sorted(unique))
    ):
        raise ValueError("PUBLIC_SOLUTION_PLAN_ENCODING_SET_INVALID")
    document = plan.model_dump(mode="json")
    if len(canonical_json_bytes(document)) > 64 * 1024**2 or plan.plan_sha256 != content_sha256(
        {key: value for key, value in document.items() if key != "plan_sha256"}
    ):
        raise ValueError("PUBLIC_SOLUTION_PLAN_HASH_INVALID")


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
        validate_public_solution_plan_values(self)
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
    validate_public_solution_plan_entry_values(plan, checked)


def validate_public_solution_plan_entry_values(
    plan: PublicSolutionSourcePlanShape, entries: tuple[PublicSolutionEncodingEntry, ...]
) -> None:
    """One exact entry/demand join after each owner's closed schema validation."""
    by_source = {entry.source.item_revision_id: entry for entry in entries}
    if len(by_source) != len(entries) or set(by_source) != {
        demand.source_revision_id for demand in plan.demands
    }:
        raise ValueError("PUBLIC_SOLUTION_STAGED_SELECTION_INVALID")
    sources = {source.item_revision_id: source for source in plan.sources}
    for demand in plan.demands:
        entry = by_source[demand.source_revision_id]
        profile = (
            RegisteredPublicSolutionProfilePointer.from_entry(entry)
            if isinstance(entry, RegisteredPublicSolutionEmbeddingEntry)
            else PublicSolutionProfilePointer.from_entry(entry)
        )
        if (
            entry.source != sources[demand.source_revision_id]
            or entry.base_analysis_run_id != demand.base_analysis_run_id
            or entry.graph_snapshot != plan.graph_snapshot
            or entry.policy_revision_id != plan.access_policy_revision_id
            or entry.policy_sha256 != plan.access_policy_sha256
            or entry.recipe != plan.recipe
            or profile != demand.profile
            or entry.evidence != demand.evidence
            or entry.public_solution.text is None
            or demand.encoding.input_text_sha256 != entry.public_solution.text_sha256
        ):
            raise ValueError("PUBLIC_SOLUTION_STAGED_DEMAND_INVALID")


def validate_local_embedding_selected_index_coverage_v3(
    plan: LocalEmbeddingSourcePlanV3, index: PublicSolutionEmbeddingIndex
) -> None:
    validate_public_solution_selected_index_values(plan, index)


def validate_public_solution_selected_index_values(
    plan: PublicSolutionSourcePlanShape,
    index: PublicSolutionEmbeddingIndex | PublicSolutionEmbeddingIndexV4,
) -> None:
    """Same required source/report coverage for old and new metadata families."""
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
