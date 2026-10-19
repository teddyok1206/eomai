"""Build native plan values from the official current Catalog capture, without IO."""

from __future__ import annotations

from eom_catalog_contracts.inference_transfer_embedding import embedding_input_set_sha256
from eom_catalog_contracts.inference_transfer_experiment import (
    StagedExperimentEntry,
    population_sha256,
)
from eom_catalog_contracts.item_inference_transfer import InferenceTransferProfilePointer
from eom_identifiers import content_sha256
from eom_workflow.local_embedding_source_plan import (
    LocalEmbeddingEncodingDemand,
    LocalEmbeddingSourcePlan,
    LocalEmbeddingUnavailableView,
    parse_local_embedding_source_plan,
    validate_local_embedding_entry_source,
)

from eom_catalog_service.embedding_incremental_plan import plan_embedding_delta
from eom_catalog_service.embedding_registry_ports import (
    EmbeddingRegistryError,
    EmbeddingRegistryLookup,
    ResolvedEmbeddingLookup,
)


def build_local_embedding_source_plan(
    query: EmbeddingRegistryLookup,
    resolved: ResolvedEmbeddingLookup,
    *,
    target_revision_ids: tuple[str, ...],
) -> LocalEmbeddingSourcePlan:
    """O(N + input bytes + K log K); a selection never silently expands to latest.

    ``resolved`` is data, not authority. The owner obtains it in the current root
    through the supported Catalog resolver. This pure builder cannot admit a Job.
    Missing profiles are explicit report coverage, not zero/placeholder vectors.
    """
    if (
        resolved.truncated
        or not 1 <= len(resolved.sources) <= 1024
        or len(resolved.entries) > len(resolved.sources)
        or not isinstance(target_revision_ids, tuple)
        or not 1 <= len(target_revision_ids) <= 1024
        or len(set(target_revision_ids)) != len(target_revision_ids)
        or query.corpus_id != resolved.corpus_id
        or query.namespace.space_sha256 != resolved.space.space_sha256
        or query.namespace.recipe_sha256 != resolved.recipe.recipe_sha256
    ):
        raise EmbeddingRegistryError("EMBEDDING_REGISTRY_SOURCE_PIN_MISMATCH")
    sources = {
        source.item_revision_id: type(source).model_validate(source.model_dump(mode="json"))
        for source in resolved.sources
    }
    entries = {
        entry.profile.source_basis.source.item_revision_id: StagedExperimentEntry.model_validate(
            entry.model_dump(mode="json", warnings="error")
        )
        for entry in resolved.entries
    }
    selected = tuple(sorted(target_revision_ids))
    if (
        len(sources) != len(resolved.sources)
        or len(entries) != len(resolved.entries)
        or not set(entries).issubset(sources)
        or not set(selected).issubset(sources)
    ):
        raise EmbeddingRegistryError("EMBEDDING_REGISTRY_SOURCE_PIN_MISMATCH")
    selected_sources = tuple(sources[key] for key in selected)
    selected_entries = tuple(entries[key] for key in selected if key in entries)
    for entry in selected_entries:
        validate_local_embedding_entry_source(
            sources[entry.profile.source_basis.source.item_revision_id],
            entry,
            graph_snapshot=query.graph_snapshot,
            projection_version=query.namespace.projection_version,
        )
    delta = plan_embedding_delta(
        selected_entries,
        space=resolved.space,
        storage_partition=query.namespace.storage_partition,
        views=(query.namespace.view,),
    )
    demands_list: list[LocalEmbeddingEncodingDemand] = []
    for demand in delta.demands:
        # Source-plan1 is a released accepted-V10 closure. Supporting a new
        # profile in the pure numerical planner does not activate that protocol.
        if not isinstance(demand.profile, InferenceTransferProfilePointer):
            raise EmbeddingRegistryError("EMBEDDING_REGISTRY_SOURCE_PIN_MISMATCH")
        demands_list.append(
            LocalEmbeddingEncodingDemand(
                source_revision_id=demand.source_revision_id,
                profile=demand.profile,
                solution_evidence=entries[
                    demand.source_revision_id
                ].profile.source_basis.solution_evidence,
                encoding=demand.encoding,
            )
        )
    demands = tuple(demands_list)
    value = {
        "schema_version": "local-embedding-source-plan/1.0",
        "corpus_id": query.corpus_id,
        "graph_snapshot": query.graph_snapshot.model_dump(mode="json"),
        "access_policy_revision_id": query.policy_revision_id,
        "access_policy_sha256": query.policy_sha256,
        "namespace": query.namespace.model_dump(mode="json"),
        "space": resolved.space.model_dump(mode="json"),
        "recipe": resolved.recipe.model_dump(mode="json"),
        "sources": [source.model_dump(mode="json") for source in selected_sources],
        "demands": [demand.model_dump(mode="json") for demand in demands],
        "missing_solution_report_revision_ids": [key for key in selected if key not in entries],
        "unavailable_views": [
            LocalEmbeddingUnavailableView(
                source_revision_id=view.source_revision_id, reason=view.reason
            ).model_dump(mode="json")
            for view in delta.unavailable_views
        ],
        "source_set_sha256": population_sha256(selected_sources),
        "encoding_set_sha256": embedding_input_set_sha256(
            tuple(row.encoding for row in delta.new_inputs)
        ),
    }
    return parse_local_embedding_source_plan(value | {"plan_sha256": content_sha256(value)})
