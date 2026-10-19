"""Pure mixed source plan after real current Catalog/Graph/REVIEW authorization."""

from __future__ import annotations

import re
from collections.abc import Mapping

from eom_catalog_contracts.embedding_reference_query import raw_similarity_contract_value
from eom_catalog_contracts.inference_transfer_embedding import embedding_input_set_sha256
from eom_catalog_contracts.inference_transfer_experiment import (
    StagedExperimentEntry,
    population_sha256,
)
from eom_catalog_contracts.item_inference_transfer import InferenceTransferProfilePointer
from eom_catalog_contracts.mixed_embedding_index import RegisteredReviewEmbeddingEntry
from eom_catalog_contracts.mixed_embedding_registry import MixedEmbeddingIndexNamespace
from eom_catalog_contracts.registered_review_profile import RegisteredReviewProfilePointer
from eom_identifiers import content_sha256
from eom_workflow.local_embedding_source_plan import LocalEmbeddingUnavailableView
from eom_workflow.local_embedding_source_plan_v2 import (
    AcceptedSolutionEncodingDemandV2,
    LocalEmbeddingEncodingDemandV2,
    LocalEmbeddingSourcePlanV2,
    RegisteredReviewEncodingDemandV2,
    parse_local_embedding_source_plan_v2,
    validate_local_embedding_entry_source_v2,
)

from eom_catalog_service.embedding_incremental_plan import plan_embedding_delta
from eom_catalog_service.embedding_registry_ports import (
    EmbeddingRegistryError,
    EmbeddingRegistryLookup,
    ResolvedEmbeddingLookup,
)


def build_local_embedding_source_plan_v2(
    query: EmbeddingRegistryLookup,
    resolved: ResolvedEmbeddingLookup,
    *,
    target_revision_ids: tuple[str, ...],
    base_analysis_run_ids: Mapping[str, str],
) -> LocalEmbeddingSourcePlanV2:
    """Real base IDs are supplied by the owner, never inferred from a REVIEW Job.

    Values and mapping are not authority. No IO, claim, submission or implicit
    population expansion occurs. The owner still validates accepted V2 membership.
    """
    if (
        not isinstance(query.namespace, MixedEmbeddingIndexNamespace)
        or resolved.truncated
        or not 1 <= len(resolved.sources) <= 1024
        or len(resolved.entries) > len(resolved.sources)
        or type(target_revision_ids) is not tuple
        or not 1 <= len(target_revision_ids) <= 1024
        or len(set(target_revision_ids)) != len(target_revision_ids)
        or query.corpus_id != resolved.corpus_id
        or query.namespace.space_sha256 != resolved.space.space_sha256
        or query.namespace.recipe_sha256 != resolved.recipe.recipe_sha256
    ):
        raise EmbeddingRegistryError("EMBEDDING_REGISTRY_SOURCE_PIN_MISMATCH")
    namespace = MixedEmbeddingIndexNamespace.model_validate(
        raw_similarity_contract_value(query.namespace)
    )
    sources = {
        source.item_revision_id: type(source).model_validate(raw_similarity_contract_value(source))
        for source in resolved.sources
    }
    if any(
        type(entry) not in (StagedExperimentEntry, RegisteredReviewEmbeddingEntry)
        for entry in resolved.entries
    ):
        raise EmbeddingRegistryError("EMBEDDING_REGISTRY_SOURCE_PIN_MISMATCH")
    entries = {
        entry.profile.source_basis.source.item_revision_id: type(entry).model_validate(
            raw_similarity_contract_value(entry)
        )
        for entry in resolved.entries
    }
    selected = tuple(sorted(target_revision_ids))
    bases = dict(base_analysis_run_ids)
    if (
        len(sources) != len(resolved.sources)
        or len(entries) != len(resolved.entries)
        or not set(entries).issubset(sources)
        or not set(selected).issubset(sources)
        or not set(selected).issubset(bases)
        or not set(bases).issubset(sources)
        or any(
            type(value) is not str or not re.fullmatch(r"analysisrun_[0-9a-f]{32}", value)
            for value in bases.values()
        )
    ):
        raise EmbeddingRegistryError("EMBEDDING_REGISTRY_SOURCE_PIN_MISMATCH")
    selected_sources = tuple(sources[key] for key in selected)
    selected_entries = tuple(entries[key] for key in selected if key in entries)
    for entry in selected_entries:
        validate_local_embedding_entry_source_v2(
            sources[entry.profile.source_basis.source.item_revision_id],
            entry,
            graph_snapshot=query.graph_snapshot,
            projection_version=namespace.projection_version,
        )
    delta = plan_embedding_delta(
        selected_entries,
        space=resolved.space,
        storage_partition=namespace.storage_partition,
        views=(namespace.view,),
    )
    demands_list: list[LocalEmbeddingEncodingDemandV2] = []
    for demand in delta.demands:
        entry = entries[demand.source_revision_id]
        if isinstance(entry, RegisteredReviewEmbeddingEntry):
            if not isinstance(demand.profile, RegisteredReviewProfilePointer):
                raise EmbeddingRegistryError("EMBEDDING_REGISTRY_SOURCE_PIN_MISMATCH")
            demands_list.append(
                RegisteredReviewEncodingDemandV2(
                    source_revision_id=demand.source_revision_id,
                    base_analysis_run_id=bases[demand.source_revision_id],
                    profile=demand.profile,
                    review_evidence=entry.profile.source_basis.review_evidence,
                    encoding=demand.encoding,
                )
            )
        else:
            if not isinstance(demand.profile, InferenceTransferProfilePointer):
                raise EmbeddingRegistryError("EMBEDDING_REGISTRY_SOURCE_PIN_MISMATCH")
            demands_list.append(
                AcceptedSolutionEncodingDemandV2(
                    source_revision_id=demand.source_revision_id,
                    base_analysis_run_id=bases[demand.source_revision_id],
                    profile=demand.profile,
                    solution_evidence=entry.profile.source_basis.solution_evidence,
                    encoding=demand.encoding,
                )
            )
    value = {
        "schema_version": "local-embedding-source-plan/2.0",
        "corpus_id": query.corpus_id,
        "graph_snapshot": query.graph_snapshot.model_dump(mode="json"),
        "access_policy_revision_id": query.policy_revision_id,
        "access_policy_sha256": query.policy_sha256,
        "namespace": namespace.model_dump(mode="json"),
        "space": resolved.space.model_dump(mode="json"),
        "recipe": resolved.recipe.model_dump(mode="json"),
        "sources": [source.model_dump(mode="json") for source in selected_sources],
        "demands": [demand.model_dump(mode="json") for demand in demands_list],
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
    return parse_local_embedding_source_plan_v2(value | {"plan_sha256": content_sha256(value)})
