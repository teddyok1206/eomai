"""Immutable metadata-only encoding demands; Catalog still owns source authority."""

from __future__ import annotations

from typing import Annotated, Literal

from eom_catalog_contracts.embedding_registry import EmbeddingIndexNamespace
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
    ApprovedPastExamItemKnowledgeSourceV3,
    KnowledgeGraphSnapshotPointer,
    KnowledgeSolutionEvidencePointer,
)
from eom_catalog_contracts.models import Sha256
from eom_identifiers import canonical_json_bytes, content_sha256
from pydantic import Field, model_validator

from eom_workflow.schemas import (
    LocalEmbeddingAdmissionContractError,
    NativeEmbeddingContract,
    validate_local_embedding_admission_message,
)

LOCAL_EMBEDDING_SOURCE_PLAN_SCHEMA_REF = "eom://schemas/workflow/local-embedding-source-plan/1.0"
type SourceRevisionId = Annotated[str, Field(pattern=r"^itemrev_[0-9a-f]{32}$")]


class LocalEmbeddingEncodingDemand(NativeEmbeddingContract):
    source_revision_id: str = Field(pattern=r"^itemrev_[0-9a-f]{32}$")
    profile: InferenceTransferProfilePointer
    solution_evidence: KnowledgeSolutionEvidencePointer
    encoding: EmbeddingEncodingIdentity


class LocalEmbeddingUnavailableView(NativeEmbeddingContract):
    source_revision_id: str = Field(pattern=r"^itemrev_[0-9a-f]{32}$")
    reason: Literal["VIEW_NOT_MATERIALIZED", "EMPTY_VIEW"]


class LocalEmbeddingSourcePlan(NativeEmbeddingContract):
    """At most 1,024 ordered sources, one pinned namespace/view, exhaustive coverage."""

    schema_version: Literal["local-embedding-source-plan/1.0"] = "local-embedding-source-plan/1.0"
    corpus_id: str = Field(pattern=r"^corpus_[0-9a-f]{32}$")
    graph_snapshot: KnowledgeGraphSnapshotPointer
    access_policy_revision_id: str = Field(pattern=r"^accessrev_[0-9a-f]{32}$")
    access_policy_sha256: Sha256
    namespace: EmbeddingIndexNamespace
    space: EmbeddingSpace
    recipe: ExperimentViewRecipe
    sources: tuple[PopulationSource, ...] = Field(min_length=1, max_length=1024)
    demands: tuple[LocalEmbeddingEncodingDemand, ...] = Field(max_length=1024)
    missing_solution_report_revision_ids: tuple[SourceRevisionId, ...] = Field(max_length=1024)
    unavailable_views: tuple[LocalEmbeddingUnavailableView, ...] = Field(max_length=1024)
    source_set_sha256: Sha256
    encoding_set_sha256: Sha256
    plan_sha256: Sha256

    @model_validator(mode="after")
    def exact_plan(self) -> LocalEmbeddingSourcePlan:
        sources = tuple(source.item_revision_id for source in self.sources)
        demanded = tuple(demand.source_revision_id for demand in self.demands)
        unavailable = tuple(view.source_revision_id for view in self.unavailable_views)
        missing = self.missing_solution_report_revision_ids
        groups = (sources, demanded, unavailable, missing)
        if any(keys != tuple(sorted(set(keys))) for keys in groups):
            raise ValueError("native source plan identities must be sorted and unique")
        covered = demanded + unavailable + missing
        if len(covered) != len(set(covered)) or set(covered) != set(sources):
            raise ValueError("native source plan coverage is missing, foreign or duplicated")
        if (
            self.graph_snapshot.manifest_sha256 != self.graph_snapshot.manifest_artifact.sha256
            or self.space.purpose != "DOCUMENT"
            or self.namespace.space_sha256 != self.space.space_sha256
            or self.namespace.recipe_sha256 != self.recipe.recipe_sha256
            or self.source_set_sha256 != population_sha256(self.sources)
        ):
            raise ValueError("native source plan space, recipe, Graph or source pins differ")
        for demand in self.demands:
            if (
                demand.encoding.storage_partition != self.namespace.storage_partition
                or demand.encoding.space_sha256 != self.space.space_sha256
            ):
                raise ValueError("native demand encoding namespace differs")
        if self.namespace.population_scope == "OCCURRENCE_BACKED_PAST_EXAM" and any(
            not isinstance(source, ApprovedPastExamItemKnowledgeSourceV3) for source in self.sources
        ):
            raise ValueError("native occurrence population requires full occurrence provenance")
        unique = {demand.encoding.encoding_sha256: demand.encoding for demand in self.demands}
        rows = tuple(unique[key] for key in sorted(unique))
        if self.encoding_set_sha256 != embedding_input_set_sha256(rows):
            raise ValueError("native source plan unique encoding set differs")
        if len(canonical_json_bytes(self.model_dump(mode="json"))) > 64 * 1024**2:
            raise ValueError("native source plan exceeds its metadata bound")
        if self.plan_sha256 != content_sha256(
            self.model_dump(mode="json", exclude={"plan_sha256"})
        ):
            raise ValueError("native source plan canonical hash differs")
        return self


def parse_local_embedding_source_plan(value: object) -> LocalEmbeddingSourcePlan:
    validate_local_embedding_admission_message("source-plan", value)
    try:
        return LocalEmbeddingSourcePlan.model_validate(value)
    except Exception:
        raise LocalEmbeddingAdmissionContractError("LOCAL_EMBEDDING_CONTRACT_INVALID") from None


def validate_local_embedding_entry_source(
    source: PopulationSource,
    entry: StagedExperimentEntry,
    *,
    graph_snapshot: KnowledgeGraphSnapshotPointer,
    projection_version: str,
) -> None:
    """Compare validated pure values, including profiles with an unavailable view.

    Callers validate the contracts first. This does not resolve or authorize any
    current source, report or Graph; that remains the Catalog owner's boundary.
    """
    basis = entry.profile.source_basis
    core = (
        "source_kind",
        "source_class",
        "item_id",
        "item_revision_id",
        "lifecycle_state",
        "artifact_member",
    )
    if (
        any(getattr(source, name) != getattr(basis.source, name) for name in core)
        or basis.graph_snapshot != graph_snapshot
        or entry.profile.extraction.method != "DETERMINISTIC_REPORT_PROJECTION"
        or entry.profile.extraction.extractor_version != projection_version
    ):
        raise ValueError("native entry differs from exact source/Graph/projection values")


def validate_local_embedding_plan_entries(
    plan: LocalEmbeddingSourcePlan, entries: tuple[StagedExperimentEntry, ...]
) -> None:
    """Check demanded pure values, not current source/report authorization or storage."""
    plan = LocalEmbeddingSourcePlan.model_validate(plan)
    plan = parse_local_embedding_source_plan(plan.model_dump(mode="json"))
    checked = tuple(
        StagedExperimentEntry.model_validate(entry.model_dump(mode="json", warnings="error"))
        for entry in entries
    )
    by_source = {entry.profile.source_basis.source.item_revision_id: entry for entry in checked}
    if len(by_source) != len(checked) or set(by_source) != {
        d.source_revision_id for d in plan.demands
    }:
        raise ValueError("native staged entries do not exactly cover plan demands")
    sources = {source.item_revision_id: source for source in plan.sources}
    for demand in plan.demands:
        entry, source = by_source[demand.source_revision_id], sources[demand.source_revision_id]
        basis = entry.profile.source_basis
        validate_local_embedding_entry_source(
            source,
            entry,
            graph_snapshot=plan.graph_snapshot,
            projection_version=plan.namespace.projection_version,
        )
        text = experiment_view_text(entry, plan.namespace.view)
        if (
            demand.profile != InferenceTransferProfilePointer.from_profile(entry.profile)
            or demand.solution_evidence != basis.solution_evidence
            or text is None
            or not text.strip()
            or demand.encoding.input_text_sha256 != content_sha256(text)
        ):
            raise ValueError("native demand differs from exact admitted profile/view values")
