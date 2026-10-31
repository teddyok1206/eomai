"""Public-solution association assembly over existing encoding rows and shard helpers."""

from dataclasses import dataclass
from datetime import datetime
from typing import overload

from eom_catalog_contracts.inference_transfer_embedding import (
    EmbeddingSpace,
    EmbeddingVectorShardManifest,
)
from eom_catalog_contracts.public_solution_embedding import (
    PublicSolutionEmbeddingEntry,
    PublicSolutionEmbeddingRecipe,
)
from eom_catalog_contracts.public_solution_embedding_index import (
    MAX_PUBLIC_SOLUTION_SOURCES,
    PublicSolutionEmbeddingIndex,
    PublicSolutionEmbeddingSourceBinding,
    PublicSolutionIndexNamespace,
    PublicSolutionProfilePointer,
)
from eom_catalog_contracts.registered_public_solution_embedding import (
    PublicSolutionEncodingEntry,
    RegisteredPublicSolutionEmbeddingEntry,
    parse_public_solution_encoding_entry,
)
from eom_catalog_contracts.registered_public_solution_index import (
    RegisteredPublicSolutionProfilePointer,
    RegisteredPublicSolutionSourceBinding,
)
from eom_identifiers import content_sha256
from eom_protocol.artifact_members import ArtifactMemberPointer
from eom_workflow.local_embedding_source_plan_v3 import (
    LocalEmbeddingSourcePlanV3,
    parse_local_embedding_source_plan_v3,
)

from eom_catalog_service.embedding_incremental_plan import RegisteredEmbeddingRow
from eom_catalog_service.embedding_index_assembly import (
    select_embedding_index_rows,
    select_embedding_index_shards,
)
from eom_catalog_service.public_solution_encoding import prepare_public_solution_encoding


@dataclass(frozen=True, slots=True)
class AssembledPublicSolutionIndex:
    index: PublicSolutionEmbeddingIndex
    shards: tuple[tuple[ArtifactMemberPointer, EmbeddingVectorShardManifest], ...]


@dataclass(frozen=True, slots=True)
class PreparedPublicSolutionIndexBasis:
    full_plan: LocalEmbeddingSourcePlanV3
    reusable_rows: tuple[RegisteredEmbeddingRow, ...]
    shards: tuple[tuple[ArtifactMemberPointer, EmbeddingVectorShardManifest], ...]
    previous: tuple[ArtifactMemberPointer, PublicSolutionEmbeddingIndex] | None
    expected_lock_version: int


@overload
def assemble_public_solution_binding(
    entry: PublicSolutionEmbeddingEntry,
    *,
    row: RegisteredEmbeddingRow,
    space: EmbeddingSpace,
    namespace: PublicSolutionIndexNamespace,
) -> PublicSolutionEmbeddingSourceBinding: ...


@overload
def assemble_public_solution_binding(
    entry: RegisteredPublicSolutionEmbeddingEntry,
    *,
    row: RegisteredEmbeddingRow,
    space: EmbeddingSpace,
    namespace: PublicSolutionIndexNamespace,
) -> RegisteredPublicSolutionSourceBinding: ...


def assemble_public_solution_binding(
    entry: PublicSolutionEncodingEntry,
    *,
    row: RegisteredEmbeddingRow,
    space: EmbeddingSpace,
    namespace: PublicSolutionIndexNamespace,
) -> PublicSolutionEmbeddingSourceBinding | RegisteredPublicSolutionSourceBinding:
    """Exact source/text/recipe closure; canonical source authority stays with Catalog."""
    entry = parse_public_solution_encoding_entry(entry)
    namespace = PublicSolutionIndexNamespace.model_validate(namespace.model_dump(mode="json"))
    prepared = prepare_public_solution_encoding(
        entry, space=space, storage_partition=namespace.storage_partition
    )
    if (
        space.purpose != "DOCUMENT"
        or namespace.space_sha256 != space.space_sha256
        or namespace.recipe_sha256 != entry.recipe.recipe_sha256
        or prepared.input is None
        or prepared.input.encoding != row.encoding
    ):
        raise ValueError("PUBLIC_SOLUTION_BINDING_INPUT_MISMATCH")
    body = {
        "schema_version": (
            "embedding-source-binding/4.0"
            if isinstance(entry, RegisteredPublicSolutionEmbeddingEntry)
            else "embedding-source-binding/3.0"
        ),
        "source": entry.source,
        "base_analysis_run_id": entry.base_analysis_run_id,
        "profile": (
            RegisteredPublicSolutionProfilePointer.from_entry(entry)
            if isinstance(entry, RegisteredPublicSolutionEmbeddingEntry)
            else PublicSolutionProfilePointer.from_entry(entry)
        ),
        "evidence": entry.evidence,
        "graph_snapshot": entry.graph_snapshot,
        "policy_revision_id": entry.policy_revision_id,
        "policy_sha256": entry.policy_sha256,
        "recipe": entry.recipe,
        "view": namespace.view,
        "projection_version": namespace.projection_version,
        "encoding": row.encoding,
        "row_ref": row.row_ref,
    }
    value = body | {"binding_sha256": content_sha256(body)}
    if isinstance(entry, RegisteredPublicSolutionEmbeddingEntry):
        return RegisteredPublicSolutionSourceBinding.model_validate(value)
    return PublicSolutionEmbeddingSourceBinding.model_validate(value)


def assemble_public_solution_index(
    entries: tuple[PublicSolutionEmbeddingEntry, ...],
    *,
    available_rows: tuple[RegisteredEmbeddingRow, ...],
    shards: tuple[tuple[ArtifactMemberPointer, EmbeddingVectorShardManifest], ...],
    namespace: PublicSolutionIndexNamespace,
    space: EmbeddingSpace,
    index_id: str,
    index_revision_id: str,
    previous_manifest: ArtifactMemberPointer | None,
    created_at: datetime,
) -> AssembledPublicSolutionIndex:
    """O(entries + rows), plus canonical ordering; no fake rows for missing input.

    One bounded index segment is assembled here. Larger source populations retain
    their existing page/segment orchestration and may not be silently truncated.
    """
    if type(entries) is not tuple or not 1 <= len(entries) <= MAX_PUBLIC_SOLUTION_SOURCES:
        raise ValueError("PUBLIC_SOLUTION_INDEX_SELECTION_INVALID")
    checked = tuple(
        PublicSolutionEmbeddingEntry.model_validate(entry.model_dump(mode="json"))
        for entry in entries
    )
    keys = tuple(entry.source.item_revision_id for entry in checked)
    first = checked[0]
    if keys != tuple(sorted(set(keys))) or any(
        (entry.graph_snapshot, entry.policy_revision_id, entry.policy_sha256, entry.recipe)
        != (first.graph_snapshot, first.policy_revision_id, first.policy_sha256, first.recipe)
        for entry in checked
    ):
        raise ValueError("PUBLIC_SOLUTION_INDEX_SCOPE_MISMATCH")
    inputs = tuple(
        prepare_public_solution_encoding(
            entry, space=space, storage_partition=namespace.storage_partition
        )
        for entry in checked
    )
    requested = tuple(value.input.encoding for value in inputs if value.input is not None)
    # Different authorized sources can share one numerical input. Keep all
    # associations while looking up the unique numeric rows exactly once.
    encodings = {value.encoding_sha256: value for value in requested}
    rows = select_embedding_index_rows(
        tuple(encodings[key] for key in sorted(encodings)),
        available_rows,
        maximum_rows=MAX_PUBLIC_SOLUTION_SOURCES,
    )
    bindings = tuple(
        assemble_public_solution_binding(
            entry,
            row=rows[value.input.encoding.encoding_sha256],
            space=space,
            namespace=namespace,
        )
        for entry, value in zip(checked, inputs, strict=True)
        if value.input is not None and value.input.encoding.encoding_sha256 in rows
    )
    if not bindings:
        raise ValueError("PUBLIC_SOLUTION_INDEX_NO_AVAILABLE_BINDING")
    selected = select_embedding_index_shards(
        frozenset(binding.row_ref.shard_manifest for binding in bindings),
        shards,
        maximum_shards=MAX_PUBLIC_SOLUTION_SOURCES,
    )
    return _assemble_public_solution_manifest(
        bindings=bindings,
        shards=selected,
        namespace=namespace,
        space=space,
        recipe=first.recipe,
        index_id=index_id,
        index_revision_id=index_revision_id,
        previous_manifest=previous_manifest,
        created_at=created_at,
    )


def assemble_public_solution_index_revision(
    plan: LocalEmbeddingSourcePlanV3,
    *,
    available_rows: tuple[RegisteredEmbeddingRow, ...],
    shards: tuple[tuple[ArtifactMemberPointer, EmbeddingVectorShardManifest], ...],
    index_id: str,
    index_revision_id: str,
    previous_manifest: ArtifactMemberPointer | None,
    created_at: datetime,
) -> AssembledPublicSolutionIndex:
    """Assemble from admitted metadata pins; never synthesize report text for a plan."""
    plan = parse_local_embedding_source_plan_v3(plan)
    unique = {demand.encoding.encoding_sha256: demand.encoding for demand in plan.demands}
    rows = select_embedding_index_rows(
        tuple(unique[key] for key in sorted(unique)),
        available_rows,
        maximum_rows=MAX_PUBLIC_SOLUTION_SOURCES,
    )
    sources = {source.item_revision_id: source for source in plan.sources}
    bindings = []
    for demand in plan.demands:
        row = rows.get(demand.encoding.encoding_sha256)
        if row is None:
            continue
        body = {
            "schema_version": "embedding-source-binding/3.0",
            "source": sources[demand.source_revision_id],
            "base_analysis_run_id": demand.base_analysis_run_id,
            "profile": demand.profile,
            "evidence": demand.evidence,
            "graph_snapshot": plan.graph_snapshot,
            "policy_revision_id": plan.access_policy_revision_id,
            "policy_sha256": plan.access_policy_sha256,
            "recipe": plan.recipe,
            "view": plan.namespace.view,
            "projection_version": plan.namespace.projection_version,
            "encoding": row.encoding,
            "row_ref": row.row_ref,
        }
        bindings.append(
            PublicSolutionEmbeddingSourceBinding.model_validate(
                body | {"binding_sha256": content_sha256(body)}
            )
        )
    if not bindings:
        raise ValueError("PUBLIC_SOLUTION_INDEX_NO_AVAILABLE_BINDING")
    selected = select_embedding_index_shards(
        frozenset(binding.row_ref.shard_manifest for binding in bindings),
        shards,
        maximum_shards=MAX_PUBLIC_SOLUTION_SOURCES,
    )
    return _assemble_public_solution_manifest(
        bindings=tuple(bindings),
        shards=selected,
        namespace=plan.namespace,
        space=plan.space,
        recipe=plan.recipe,
        index_id=index_id,
        index_revision_id=index_revision_id,
        previous_manifest=previous_manifest,
        created_at=created_at,
    )


def _assemble_public_solution_manifest(
    *,
    bindings: tuple[PublicSolutionEmbeddingSourceBinding, ...],
    shards: tuple[tuple[ArtifactMemberPointer, EmbeddingVectorShardManifest], ...],
    namespace: PublicSolutionIndexNamespace,
    space: EmbeddingSpace,
    recipe: PublicSolutionEmbeddingRecipe,
    index_id: str,
    index_revision_id: str,
    previous_manifest: ArtifactMemberPointer | None,
    created_at: datetime,
) -> AssembledPublicSolutionIndex:
    body = {
        "schema_version": "embedding-index-manifest/3.0",
        "index_id": index_id,
        "index_revision_id": index_revision_id,
        "previous_manifest": previous_manifest,
        "storage_partition": namespace.storage_partition,
        "space": space,
        "view": namespace.view,
        "recipe": recipe,
        "shards": tuple(pointer for pointer, _ in shards),
        "bindings": bindings,
        "created_at": created_at.isoformat().replace("+00:00", "Z"),
    }
    return AssembledPublicSolutionIndex(
        PublicSolutionEmbeddingIndex.model_validate(body | {"index_sha256": content_sha256(body)}),
        shards,
    )
