"""Explicit mixed branch assembly around existing immutable numeric rows; no IO."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from eom_catalog_contracts.inference_transfer_embedding import (
    MAX_EMBEDDING_ROWS,
    EmbeddingIndexManifest,
    EmbeddingVectorShardManifest,
)
from eom_catalog_contracts.inference_transfer_experiment import ExperimentView, ExperimentViewRecipe
from eom_catalog_contracts.knowledge import (
    ApprovedItemKnowledgeSourceV2,
    KnowledgeGraphSnapshotPointer,
)
from eom_catalog_contracts.mixed_embedding_index import (
    MixedEmbeddingIndexManifest,
    MixedEmbeddingSourceBinding,
    RegisteredReviewEmbeddingSourceBinding,
    validate_mixed_embedding_index_references,
)
from eom_catalog_contracts.registered_item_review_solution import (
    RegisteredItemReviewSolutionEvidence,
)
from eom_catalog_contracts.registered_review_profile import (
    REGISTERED_REVIEW_EXTRACTOR_VERSION,
    RegisteredReviewProfilePointer,
)
from eom_identifiers import content_sha256
from eom_protocol.artifact_members import ArtifactMemberPointer
from eom_workflow.local_embedding_source_plan_v2 import (
    LocalEmbeddingSourcePlanV2,
    RegisteredReviewEncodingDemandV2,
    parse_local_embedding_source_plan_v2,
)

from eom_catalog_service.embedding_incremental_plan import RegisteredEmbeddingRow
from eom_catalog_service.embedding_index_assembly import (
    assemble_embedding_source_binding,
    select_embedding_index_rows,
    select_embedding_index_shards,
)


@dataclass(frozen=True, slots=True)
class AssembledMixedEmbeddingIndex:
    index: MixedEmbeddingIndexManifest
    shards: tuple[tuple[ArtifactMemberPointer, EmbeddingVectorShardManifest], ...]


@dataclass(frozen=True, slots=True)
class PreparedMixedEmbeddingIndexBasis:
    full_plan: LocalEmbeddingSourcePlanV2
    reusable_rows: tuple[RegisteredEmbeddingRow, ...]
    shards: tuple[tuple[ArtifactMemberPointer, EmbeddingVectorShardManifest], ...]
    previous: (
        tuple[ArtifactMemberPointer, EmbeddingIndexManifest | MixedEmbeddingIndexManifest] | None
    )
    expected_lock_version: int


def assemble_registered_review_source_binding(
    *,
    source: ApprovedItemKnowledgeSourceV2,
    base_analysis_run_id: str,
    profile: RegisteredReviewProfilePointer,
    review_evidence: RegisteredItemReviewSolutionEvidence,
    graph_snapshot: KnowledgeGraphSnapshotPointer,
    policy_revision_id: str,
    policy_sha256: str,
    recipe: ExperimentViewRecipe,
    view: ExperimentView,
    row: RegisteredEmbeddingRow,
) -> RegisteredReviewEmbeddingSourceBinding:
    """Pure exact REVIEW association; does not prove current accepted V2 membership."""
    body: dict[str, object] = {
        "schema_version": "embedding-source-binding/2.0",
        "source": source,
        "base_analysis_run_id": base_analysis_run_id,
        "profile": profile,
        "review_evidence": review_evidence,
        "graph_snapshot": graph_snapshot,
        "policy_revision_id": policy_revision_id,
        "policy_sha256": policy_sha256,
        "recipe": recipe,
        "view": view,
        "projection_version": REGISTERED_REVIEW_EXTRACTOR_VERSION,
        "encoding": row.encoding,
        "row_ref": row.row_ref,
    }
    return RegisteredReviewEmbeddingSourceBinding.model_validate(
        body | {"binding_sha256": content_sha256(body)}
    )


def assemble_embedding_index_revision_v2(
    plan: LocalEmbeddingSourcePlanV2,
    *,
    available_rows: tuple[RegisteredEmbeddingRow, ...],
    shards: tuple[tuple[ArtifactMemberPointer, EmbeddingVectorShardManifest], ...],
    index_id: str,
    index_revision_id: str,
    previous: tuple[ArtifactMemberPointer, EmbeddingIndexManifest | MixedEmbeddingIndexManifest]
    | None,
    created_at: datetime,
) -> AssembledMixedEmbeddingIndex:
    """Rebuild only current eligible associations; partial rows never imply full coverage."""
    plan = parse_local_embedding_source_plan_v2(plan)
    if (
        type(available_rows) is not tuple
        or type(shards) is not tuple
        or len(available_rows) > MAX_EMBEDDING_ROWS
        or len(shards) > MAX_EMBEDDING_ROWS
    ):
        raise ValueError("EMBEDDING_INDEX_ASSEMBLY_LIMIT")
    rows = select_embedding_index_rows(tuple(d.encoding for d in plan.demands), available_rows)
    sources = {source.item_revision_id: source for source in plan.sources}
    bindings: list[MixedEmbeddingSourceBinding] = []
    for demand in plan.demands:
        row = rows.get(demand.encoding.encoding_sha256)
        if row is None:
            continue
        binding: MixedEmbeddingSourceBinding
        if isinstance(demand, RegisteredReviewEncodingDemandV2):
            source = sources[demand.source_revision_id]
            # plan2's exact source/evidence closure already proves this branch;
            # the explicit type check also closes accidental caller widening.
            if not isinstance(source, ApprovedItemKnowledgeSourceV2):
                raise ValueError("EMBEDDING_INDEX_ASSEMBLY_SOURCE_INVALID")
            binding = assemble_registered_review_source_binding(
                source=source,
                base_analysis_run_id=demand.base_analysis_run_id,
                profile=demand.profile,
                review_evidence=demand.review_evidence,
                graph_snapshot=plan.graph_snapshot,
                policy_revision_id=plan.access_policy_revision_id,
                policy_sha256=plan.access_policy_sha256,
                recipe=plan.recipe,
                view=plan.namespace.view,
                row=row,
            )
        else:
            binding = assemble_embedding_source_binding(
                source=sources[demand.source_revision_id],
                profile=demand.profile,
                solution_evidence=demand.solution_evidence,
                graph_snapshot=plan.graph_snapshot,
                policy_revision_id=plan.access_policy_revision_id,
                policy_sha256=plan.access_policy_sha256,
                recipe=plan.recipe,
                view=plan.namespace.view,
                projection_version="accepted-solution-comparison/1.0",
                row=row,
            )
        bindings.append(binding)
    if not bindings:
        raise ValueError("EMBEDDING_INDEX_ASSEMBLY_NO_AVAILABLE_BINDING")
    selected = select_embedding_index_shards(
        frozenset(binding.row_ref.shard_manifest for binding in bindings), shards
    )
    body = {
        "schema_version": "embedding-index-manifest/2.0",
        "index_id": index_id,
        "index_revision_id": index_revision_id,
        "previous_manifest": None if previous is None else previous[0].model_dump(mode="json"),
        "storage_partition": plan.namespace.storage_partition,
        "space": plan.space.model_dump(mode="json"),
        "view": plan.namespace.view,
        "recipe": plan.recipe.model_dump(mode="json"),
        "shards": [pointer.model_dump(mode="json") for pointer, _ in selected],
        "bindings": [binding.model_dump(mode="json") for binding in bindings],
        "created_at": created_at.isoformat().replace("+00:00", "Z"),
    }
    index = MixedEmbeddingIndexManifest.model_validate(
        body | {"index_sha256": content_sha256(body)}
    )
    validate_mixed_embedding_index_references(index, selected, previous)
    return AssembledMixedEmbeddingIndex(index, selected)
