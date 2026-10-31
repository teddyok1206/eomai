"""Pure public-solution plan from an actual, authorized Catalog capture."""

from typing import Literal

from eom_catalog_contracts.inference_transfer_embedding import embedding_input_set_sha256
from eom_catalog_contracts.inference_transfer_experiment import population_sha256
from eom_catalog_contracts.public_solution_embedding import (
    PublicSolutionEmbeddingEntry,
    PublicSolutionEmbeddingRecipe,
)
from eom_catalog_contracts.public_solution_embedding_index import (
    MAX_PUBLIC_SOLUTION_SOURCES,
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
)
from eom_identifiers import content_sha256
from eom_workflow.local_embedding_source_plan_v3 import (
    LocalEmbeddingSourcePlanV3,
    PublicSolutionEncodingDemand,
    PublicSolutionUnavailableView,
    parse_local_embedding_source_plan_v3,
)
from eom_workflow.local_embedding_source_plan_v4 import (
    LocalEmbeddingSourcePlanV4,
    PublicSolutionEncodingDemandV4,
    parse_local_embedding_source_plan_v4,
)

from eom_catalog_service.embedding_incremental_plan import plan_embedding_delta
from eom_catalog_service.embedding_registry_ports import (
    EmbeddingRegistryError,
    EmbeddingRegistryLookup,
    ResolvedEmbeddingLookup,
)


def build_local_embedding_source_plan_v3(
    query: EmbeddingRegistryLookup,
    resolved: ResolvedEmbeddingLookup,
    *,
    target_revision_ids: tuple[str, ...],
) -> LocalEmbeddingSourcePlanV3:
    value = _build_public_solution_source_plan(
        query, resolved, target_revision_ids=target_revision_ids, plan_version="3.0"
    )
    assert isinstance(value, LocalEmbeddingSourcePlanV3)
    return value


def build_local_embedding_source_plan_v4(
    query: EmbeddingRegistryLookup,
    resolved: ResolvedEmbeddingLookup,
    *,
    target_revision_ids: tuple[str, ...],
) -> LocalEmbeddingSourcePlanV4:
    value = _build_public_solution_source_plan(
        query, resolved, target_revision_ids=target_revision_ids, plan_version="4.0"
    )
    assert isinstance(value, LocalEmbeddingSourcePlanV4)
    return value


def _build_public_solution_source_plan(
    query: EmbeddingRegistryLookup,
    resolved: ResolvedEmbeddingLookup,
    *,
    target_revision_ids: tuple[str, ...],
    plan_version: Literal["3.0", "4.0"],
) -> LocalEmbeddingSourcePlanV3 | LocalEmbeddingSourcePlanV4:
    """No IO/authority/claim. Missing reports and unavailable text stay explicit."""
    if (
        not isinstance(query.namespace, PublicSolutionIndexNamespace)
        or not isinstance(resolved.recipe, PublicSolutionEmbeddingRecipe)
        or resolved.truncated
        or not 1 <= len(resolved.sources) <= MAX_PUBLIC_SOLUTION_SOURCES
        or type(target_revision_ids) is not tuple
        or not target_revision_ids
        or target_revision_ids != tuple(sorted(set(target_revision_ids)))
        or query.corpus_id != resolved.corpus_id
        or query.namespace.space_sha256 != resolved.space.space_sha256
        or query.namespace.recipe_sha256 != resolved.recipe.recipe_sha256
    ):
        raise EmbeddingRegistryError("EMBEDDING_REGISTRY_SOURCE_PIN_MISMATCH")
    sources = {source.item_revision_id: source for source in resolved.sources}
    entries: dict[str, PublicSolutionEncodingEntry] = {}
    for original in resolved.entries:
        if not isinstance(
            original, PublicSolutionEmbeddingEntry | RegisteredPublicSolutionEmbeddingEntry
        ) or (plan_version == "3.0" and not isinstance(original, PublicSolutionEmbeddingEntry)):
            raise EmbeddingRegistryError("EMBEDDING_REGISTRY_SOURCE_PIN_MISMATCH")
        entry = parse_public_solution_encoding_entry(original)
        entries[entry.source.item_revision_id] = entry
    bases = dict(resolved.base_analysis_run_ids)
    selected = frozenset(target_revision_ids)
    if (
        len(sources) != len(resolved.sources)
        or len(entries) != len(resolved.entries)
        or len(bases) != len(resolved.base_analysis_run_ids)
        or set(bases) != set(sources)
        or not set(entries).issubset(sources)
        or not selected.issubset(sources)
        or not selected.issubset(bases)
    ):
        raise EmbeddingRegistryError("EMBEDDING_REGISTRY_SOURCE_PIN_MISMATCH")
    selected_entries = tuple(entries[key] for key in target_revision_ids if key in entries)
    for entry in selected_entries:
        if (
            entry.source != sources[entry.source.item_revision_id]
            or entry.base_analysis_run_id != bases[entry.source.item_revision_id]
            or entry.graph_snapshot != query.graph_snapshot
            or entry.policy_revision_id != query.policy_revision_id
            or entry.policy_sha256 != query.policy_sha256
            or entry.recipe != resolved.recipe
        ):
            raise EmbeddingRegistryError("EMBEDDING_REGISTRY_SOURCE_PIN_MISMATCH")
    delta = plan_embedding_delta(
        selected_entries,
        space=resolved.space,
        storage_partition=query.namespace.storage_partition,
        views=(query.namespace.view,),
    )
    demands = []
    for demand in delta.demands:
        demanded = entries[demand.source_revision_id]
        profile = (
            RegisteredPublicSolutionProfilePointer.from_entry(demanded)
            if isinstance(demanded, RegisteredPublicSolutionEmbeddingEntry)
            else PublicSolutionProfilePointer.from_entry(demanded)
        )
        body = dict(
            source_revision_id=demand.source_revision_id,
            base_analysis_run_id=demanded.base_analysis_run_id,
            profile=profile,
            evidence=demanded.evidence,
            encoding=demand.encoding,
        )
        demands.append(
            PublicSolutionEncodingDemand.model_validate(body)
            if plan_version == "3.0"
            else PublicSolutionEncodingDemandV4.model_validate(body)
        )
    value = {
        "schema_version": "local-embedding-source-plan/" + plan_version,
        "corpus_id": query.corpus_id,
        "graph_snapshot": query.graph_snapshot,
        "access_policy_revision_id": query.policy_revision_id,
        "access_policy_sha256": query.policy_sha256,
        "namespace": query.namespace,
        "space": resolved.space,
        "recipe": resolved.recipe,
        "sources": tuple(sources[key] for key in target_revision_ids),
        "demands": tuple(demands),
        "missing_solution_report_revision_ids": tuple(
            key for key in target_revision_ids if key not in entries
        ),
        "unavailable_views": tuple(
            PublicSolutionUnavailableView(
                source_revision_id=view.source_revision_id, reason=view.reason
            )
            for view in delta.unavailable_views
        ),
        "source_set_sha256": population_sha256(tuple(sources[key] for key in target_revision_ids)),
        "encoding_set_sha256": embedding_input_set_sha256(
            tuple(row.encoding for row in delta.new_inputs)
        ),
    }
    document = value | {"plan_sha256": content_sha256(value)}
    return (
        parse_local_embedding_source_plan_v3(document)
        if plan_version == "3.0"
        else parse_local_embedding_source_plan_v4(document)
    )
