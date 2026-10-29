"""Rebuild current source associations around immutable reusable numeric rows, without IO."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from eom_catalog_contracts.inference_transfer_embedding import (
    MAX_EMBEDDING_ROWS,
    EmbeddingEncodingIdentity,
    EmbeddingIndexManifest,
    EmbeddingSourceBinding,
    EmbeddingVectorRowRef,
    EmbeddingVectorShardManifest,
    parse_embedding_index,
    validate_embedding_index_references,
)
from eom_catalog_contracts.inference_transfer_experiment import (
    ExperimentView,
    ExperimentViewRecipe,
    PopulationSource,
)
from eom_catalog_contracts.item_inference_transfer import InferenceTransferProfilePointer
from eom_catalog_contracts.knowledge import (
    KnowledgeGraphSnapshotPointer,
    KnowledgeSolutionEvidencePointer,
)
from eom_catalog_contracts.public_solution_embedding_index import MAX_PUBLIC_SOLUTION_SOURCES
from eom_identifiers import content_sha256
from eom_protocol.artifact_members import ArtifactMemberPointer
from eom_workflow.local_embedding_source_plan import (
    LocalEmbeddingSourcePlan,
    parse_local_embedding_source_plan,
)

from eom_catalog_service.embedding_incremental_plan import RegisteredEmbeddingRow


@dataclass(frozen=True, slots=True)
class AssembledEmbeddingIndex:
    """Owner-local metadata; no source grant, binary proof or mutable registry head."""

    index: EmbeddingIndexManifest
    shards: tuple[tuple[ArtifactMemberPointer, EmbeddingVectorShardManifest], ...]


@dataclass(frozen=True, slots=True)
class PreparedEmbeddingIndexBasis:
    """One current Catalog root's inputs; later roots independently reauthorize."""

    full_plan: LocalEmbeddingSourcePlan
    reusable_rows: tuple[RegisteredEmbeddingRow, ...]
    shards: tuple[tuple[ArtifactMemberPointer, EmbeddingVectorShardManifest], ...]
    previous: tuple[ArtifactMemberPointer, EmbeddingIndexManifest] | None
    expected_lock_version: int


def assemble_embedding_source_binding(
    *,
    source: PopulationSource,
    profile: InferenceTransferProfilePointer,
    solution_evidence: KnowledgeSolutionEvidencePointer,
    graph_snapshot: KnowledgeGraphSnapshotPointer,
    policy_revision_id: str,
    policy_sha256: str,
    recipe: ExperimentViewRecipe,
    view: ExperimentView,
    projection_version: str,
    row: RegisteredEmbeddingRow,
) -> EmbeddingSourceBinding:
    """One complete immutable value; callers still own current admission and row proof."""
    body: dict[str, object] = {
        "schema_version": "embedding-source-binding/1.0",
        "source": source.model_dump(mode="json"),
        "profile": profile.model_dump(mode="json"),
        "solution_evidence": solution_evidence.model_dump(mode="json"),
        "graph_snapshot": graph_snapshot.model_dump(mode="json"),
        "policy_revision_id": policy_revision_id,
        "policy_sha256": policy_sha256,
        "recipe": recipe.model_dump(mode="json"),
        "view": view,
        "projection_version": projection_version,
        "encoding": row.encoding.model_dump(mode="json"),
        "row_ref": row.row_ref.model_dump(mode="json"),
    }
    return EmbeddingSourceBinding.model_validate(body | {"binding_sha256": content_sha256(body)})


def select_embedding_index_rows(
    demanded_encodings: tuple[EmbeddingEncodingIdentity, ...],
    available_rows: tuple[RegisteredEmbeddingRow, ...],
    *,
    maximum_rows: int = MAX_EMBEDDING_ROWS,
) -> dict[str, RegisteredEmbeddingRow]:
    """Pure exact encoding lookup shared by released and mixed index assembly."""
    if (
        type(maximum_rows) is not int
        or not 1 <= maximum_rows <= MAX_PUBLIC_SOLUTION_SOURCES
        or type(available_rows) is not tuple
        or len(available_rows) > maximum_rows
    ):
        raise ValueError("EMBEDDING_INDEX_ASSEMBLY_LIMIT")
    demands = {encoding.encoding_sha256: encoding for encoding in demanded_encodings}
    rows: dict[str, RegisteredEmbeddingRow] = {}
    for value in available_rows:
        encoding = EmbeddingEncodingIdentity.model_validate(value.encoding.model_dump(mode="json"))
        ref = EmbeddingVectorRowRef.model_validate(value.row_ref.model_dump(mode="json"))
        key = encoding.encoding_sha256
        if key in rows or demands.get(key) != encoding or ref.encoding_sha256 != key:
            raise ValueError("EMBEDDING_INDEX_ASSEMBLY_ROW_INVALID")
        rows[key] = RegisteredEmbeddingRow(encoding, ref)
    return rows


def select_embedding_index_shards(
    needed: frozenset[ArtifactMemberPointer],
    shards: tuple[tuple[ArtifactMemberPointer, EmbeddingVectorShardManifest], ...],
    *,
    maximum_shards: int = MAX_EMBEDDING_ROWS,
) -> tuple[tuple[ArtifactMemberPointer, EmbeddingVectorShardManifest], ...]:
    """Exact required pointer membership with stable order; bytes are verified later."""
    if (
        type(maximum_shards) is not int
        or not 1 <= maximum_shards <= MAX_PUBLIC_SOLUTION_SOURCES
        or type(shards) is not tuple
        or len(shards) > maximum_shards
    ):
        raise ValueError("EMBEDDING_INDEX_ASSEMBLY_LIMIT")
    by_pointer = {pointer: shard for pointer, shard in shards}
    if len(by_pointer) != len(shards):
        raise ValueError("EMBEDDING_INDEX_ASSEMBLY_SHARD_DUPLICATE")
    if not needed.issubset(by_pointer):
        raise ValueError("EMBEDDING_INDEX_ASSEMBLY_SHARD_MISSING")
    return tuple(
        (pointer, by_pointer[pointer])
        for pointer in sorted(
            needed,
            key=lambda pointer: (
                pointer.artifact_id,
                pointer.artifact_revision_id,
                pointer.member_path,
                pointer.sha256,
            ),
        )
    )


def assemble_embedding_index_revision(
    plan: LocalEmbeddingSourcePlan,
    *,
    available_rows: tuple[RegisteredEmbeddingRow, ...],
    shards: tuple[tuple[ArtifactMemberPointer, EmbeddingVectorShardManifest], ...],
    index_id: str,
    index_revision_id: str,
    previous: tuple[ArtifactMemberPointer, EmbeddingIndexManifest] | None,
    created_at: datetime,
) -> AssembledEmbeddingIndex:
    """O(N + K log K), rebuilding bindings ONLY from the current full admitted plan.

    The composition must capture that full plan using the official current source
    owner, and independently verify committed finite/L2 rows before supplying them.
    Available rows may cover only part of the eligible population. Old bindings are
    never copied; Graph/report/source changes retain numbers only when exact input
    identity is unchanged. Revoked/missing-report sources receive no binding.
    """
    plan = parse_local_embedding_source_plan(plan.model_dump(mode="json"))
    if (
        type(available_rows) is not tuple
        or type(shards) is not tuple
        or len(available_rows) > MAX_EMBEDDING_ROWS
        or len(shards) > MAX_EMBEDDING_ROWS
    ):
        raise ValueError("EMBEDDING_INDEX_ASSEMBLY_LIMIT")
    rows = select_embedding_index_rows(tuple(d.encoding for d in plan.demands), available_rows)
    sources = {s.item_revision_id: s for s in plan.sources}
    bindings = []
    for demand in plan.demands:
        row = rows.get(demand.encoding.encoding_sha256)
        if row is None:
            continue
        bindings.append(
            assemble_embedding_source_binding(
                source=sources[demand.source_revision_id],
                profile=demand.profile,
                solution_evidence=demand.solution_evidence,
                graph_snapshot=plan.graph_snapshot,
                policy_revision_id=plan.access_policy_revision_id,
                policy_sha256=plan.access_policy_sha256,
                recipe=plan.recipe,
                view=plan.namespace.view,
                projection_version=plan.namespace.projection_version,
                row=row,
            )
        )
    if not bindings:
        raise ValueError("EMBEDDING_INDEX_ASSEMBLY_NO_AVAILABLE_BINDING")
    selected = select_embedding_index_shards(
        frozenset(binding.row_ref.shard_manifest for binding in bindings), shards
    )
    body = {
        "schema_version": "embedding-index-manifest/1.0",
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
    index = parse_embedding_index(body | {"index_sha256": content_sha256(body)})
    validate_embedding_index_references(index, selected, previous)
    return AssembledEmbeddingIndex(index, selected)
