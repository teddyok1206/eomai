"""Pure current-membership observation, not source authorization or Job admission."""

from __future__ import annotations

from eom_catalog_contracts.embedding_reference_query import raw_similarity_contract_value
from eom_catalog_contracts.inference_transfer_embedding import (
    EmbeddingIndexManifest,
    EmbeddingSourceBinding,
    parse_embedding_binding,
)
from eom_catalog_contracts.inference_transfer_experiment import PopulationSource, population_sha256
from eom_identifiers import content_sha256
from eom_protocol.artifact_members import ArtifactMemberPointer
from eom_workflow.local_embedding_index_refresh import (
    IndexMembershipRefreshBasis,
    IndexRefreshContractError,
    parse_index_refresh_predecessor,
)
from jsonschema.exceptions import ValidationError as SchemaError
from pydantic import TypeAdapter


def plan_index_membership_refresh(
    *,
    eligible_sources: tuple[PopulationSource, ...],
    available_bindings: tuple[EmbeddingSourceBinding, ...],
    previous: tuple[ArtifactMemberPointer, EmbeddingIndexManifest] | None,
) -> IndexMembershipRefreshBasis | None:
    """O(N log N) stable metadata comparison, O(N) space, N<=1024.

    Catalog must independently resolve/authorize all current sources, registered
    bindings and the exact namespace predecessor in the same root before calling.
    No-data/report-wait/view-unavailable cases do not produce empty placeholders.
    A same-member eligible population change only affects live coverage, not index
    bytes. Different membership retains reusable row pointers, never reencodes them.
    """
    if (
        type(eligible_sources) is not tuple
        or type(available_bindings) is not tuple
        or len(eligible_sources) > 1024
        or len(available_bindings) > len(eligible_sources)
    ):
        raise IndexRefreshContractError()
    try:
        adapter: TypeAdapter[PopulationSource] = TypeAdapter(PopulationSource)
        sources = {
            value.item_revision_id: adapter.validate_python(raw_similarity_contract_value(value))
            for value in eligible_sources
        }
        bindings = tuple(
            sorted(
                (
                    parse_embedding_binding(raw_similarity_contract_value(value))
                    for value in available_bindings
                ),
                key=lambda value: value.source.item_revision_id,
            )
        )
        if len(sources) != len(eligible_sources) or len(
            {value.source.item_revision_id for value in bindings}
        ) != len(bindings):
            raise IndexRefreshContractError()
        if any(sources.get(value.source.item_revision_id) != value.source for value in bindings):
            raise IndexRefreshContractError()
        predecessor = parse_index_refresh_predecessor(previous)
        pointer, index = (None, None) if predecessor is None else predecessor
        if not bindings:
            return None
        first = bindings[0]
        if any(
            value.graph_snapshot != first.graph_snapshot
            or value.policy_revision_id != first.policy_revision_id
            or value.policy_sha256 != first.policy_sha256
            or value.view != first.view
            or value.recipe != first.recipe
            or value.encoding.space_sha256 != first.encoding.space_sha256
            or value.encoding.storage_partition != first.encoding.storage_partition
            for value in bindings
        ) or (
            index is not None
            and (
                index.space.space_sha256 != first.encoding.space_sha256
                or index.storage_partition != first.encoding.storage_partition
                or index.view != first.view
                or index.recipe != first.recipe
            )
        ):
            raise IndexRefreshContractError()
        if index is not None and index.bindings == bindings:
            return None
        return IndexMembershipRefreshBasis(
            reason="MISSING_NAMESPACE_INDEX" if index is None else "INDEX_MEMBERSHIP_CHANGED",
            previous_index_manifest=pointer,
            previous_index_sha256=None if index is None else index.index_sha256,
            eligible_source_set_sha256=population_sha256(
                tuple(sources[key] for key in sorted(sources))
            ),
            eligible_source_count=len(sources),
            available_binding_set_sha256=content_sha256(
                [value.binding_sha256 for value in bindings]
            ),
            available_binding_count=len(bindings),
        )
    except (ValueError, TypeError, AttributeError, SchemaError):
        raise IndexRefreshContractError() from None
