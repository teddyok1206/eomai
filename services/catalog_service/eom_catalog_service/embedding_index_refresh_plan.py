"""Pure current-membership observation, not source authorization or Job admission."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from eom_catalog_contracts.embedding_index_families import (
    SupportedEmbeddingBinding,
    SupportedEmbeddingIndex,
)
from eom_catalog_contracts.embedding_reference_query import raw_similarity_contract_value
from eom_catalog_contracts.inference_transfer_embedding import (
    EmbeddingIndexManifest,
    EmbeddingSourceBinding,
    parse_embedding_binding,
)
from eom_catalog_contracts.inference_transfer_experiment import PopulationSource, population_sha256
from eom_catalog_contracts.knowledge import same_approved_item_source_identity
from eom_catalog_contracts.mixed_embedding_index import (
    MIXED_EMBEDDING_INDEX_SCHEMA_REF,
    MixedEmbeddingIndexManifest,
    MixedEmbeddingSourceBinding,
    parse_supported_embedding_binding,
)
from eom_catalog_contracts.public_solution_embedding_index import (
    MAX_PUBLIC_SOLUTION_SOURCES,
    PUBLIC_SOLUTION_INDEX_SCHEMA_REF,
    PublicSolutionEmbeddingIndex,
    PublicSolutionEmbeddingSourceBinding,
)
from eom_catalog_contracts.registered_public_solution_index import (
    REGISTERED_PUBLIC_SOLUTION_INDEX_SCHEMA_REF,
    PublicSolutionBindingV4,
    PublicSolutionEmbeddingIndexV4,
)
from eom_identifiers import content_sha256
from eom_protocol.artifact_members import ArtifactMemberPointer
from eom_workflow.local_embedding_index_refresh import (
    IndexMembershipRefreshBasis,
    IndexRefreshContractError,
    parse_index_refresh_predecessor,
)
from jsonschema.exceptions import ValidationError as SchemaError
from pydantic import TypeAdapter


@lru_cache(maxsize=1)
def _public_binding_adapter() -> TypeAdapter[PublicSolutionBindingV4]:
    return TypeAdapter(PublicSolutionBindingV4)


def _require_binding_scope(
    bindings: tuple[SupportedEmbeddingBinding, ...],
    index: SupportedEmbeddingIndex | None,
) -> None:
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
        _require_binding_scope(bindings, index)
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


def mixed_index_membership_refresh_reason(
    *,
    eligible_sources: tuple[PopulationSource, ...],
    available_bindings: tuple[MixedEmbeddingSourceBinding, ...],
    previous: tuple[ArtifactMemberPointer, MixedEmbeddingIndexManifest] | None,
) -> Literal["MISSING_NAMESPACE_INDEX", "INDEX_MEMBERSHIP_CHANGED"] | None:
    """Compare current authorized mixed metadata; never produce a V1.3 intent.

    The service submits all available source IDs through existing request2/plan2.
    New missing bindings are excluded, so this path can reuse vectors without a
    numeric run. Empty availability never creates an empty index or a fake source.
    O(N log N) time/O(N) space, bounded by the same 1024-source owner capture.
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
                (parse_supported_embedding_binding(value) for value in available_bindings),
                key=lambda value: value.source.item_revision_id,
            )
        )
        if len(sources) != len(eligible_sources) or len(
            {value.source.item_revision_id for value in bindings}
        ) != len(bindings):
            raise IndexRefreshContractError()
        if any(
            (source := sources.get(value.source.item_revision_id)) is None
            or not same_approved_item_source_identity(source, value.source)
            for value in bindings
        ):
            raise IndexRefreshContractError()
        index = None
        if previous is not None:
            if type(previous) is not tuple or len(previous) != 2:
                raise IndexRefreshContractError()
            pointer = ArtifactMemberPointer.model_validate(
                raw_similarity_contract_value(previous[0])
            )
            index = MixedEmbeddingIndexManifest.model_validate(
                raw_similarity_contract_value(previous[1])
            )
            if (
                pointer.member_path != "index.json"
                or pointer.schema_ref != MIXED_EMBEDDING_INDEX_SCHEMA_REF
                or pointer.media_type != "application/json"
                or pointer.sha256 != content_sha256(index.model_dump(mode="json"))
            ):
                raise IndexRefreshContractError()
        if not bindings:
            return None
        _require_binding_scope(bindings, index)
        if index is not None and index.bindings == bindings:
            return None
        return "MISSING_NAMESPACE_INDEX" if index is None else "INDEX_MEMBERSHIP_CHANGED"
    except (ValueError, TypeError, AttributeError, SchemaError):
        raise IndexRefreshContractError() from None


def public_index_membership_refresh_reason(
    *,
    eligible_sources: tuple[PopulationSource, ...],
    available_bindings: tuple[PublicSolutionEmbeddingSourceBinding, ...],
    previous: tuple[ArtifactMemberPointer, PublicSolutionEmbeddingIndex] | None,
) -> Literal["MISSING_NAMESPACE_INDEX", "INDEX_MEMBERSHIP_CHANGED"] | None:
    """Public family keeps full page provenance and has its own explicit larger bound."""
    return _public_index_membership_refresh_reason(
        eligible_sources=eligible_sources,
        available_bindings=available_bindings,
        previous=previous,
        metadata_version="3.0",
    )


def registered_public_index_membership_refresh_reason(
    *,
    eligible_sources: tuple[PopulationSource, ...],
    available_bindings: tuple[PublicSolutionBindingV4, ...],
    previous: tuple[
        ArtifactMemberPointer, PublicSolutionEmbeddingIndex | PublicSolutionEmbeddingIndexV4
    ]
    | None,
) -> Literal["MISSING_NAMESPACE_INDEX", "INDEX_MEMBERSHIP_CHANGED"] | None:
    """Explicit 3→4 reader; identical rows do not imply identical source-proof envelopes."""
    return _public_index_membership_refresh_reason(
        eligible_sources=eligible_sources,
        available_bindings=available_bindings,
        previous=previous,
        metadata_version="4.0",
    )


def _public_index_membership_refresh_reason(
    *,
    eligible_sources: tuple[PopulationSource, ...],
    available_bindings: tuple[PublicSolutionBindingV4, ...],
    previous: tuple[
        ArtifactMemberPointer, PublicSolutionEmbeddingIndex | PublicSolutionEmbeddingIndexV4
    ]
    | None,
    metadata_version: Literal["3.0", "4.0"],
) -> Literal["MISSING_NAMESPACE_INDEX", "INDEX_MEMBERSHIP_CHANGED"] | None:
    if (
        type(eligible_sources) is not tuple
        or type(available_bindings) is not tuple
        or len(eligible_sources) > MAX_PUBLIC_SOLUTION_SOURCES
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
                    _public_binding_adapter().validate_python(raw_similarity_contract_value(value))
                    for value in available_bindings
                ),
                key=lambda value: value.source.item_revision_id,
            )
        )
        if metadata_version == "3.0" and any(
            not isinstance(binding, PublicSolutionEmbeddingSourceBinding) for binding in bindings
        ):
            raise IndexRefreshContractError()
        if (
            len(sources) != len(eligible_sources)
            or len({value.source.item_revision_id for value in bindings}) != len(bindings)
            or any(sources.get(value.source.item_revision_id) != value.source for value in bindings)
        ):
            raise IndexRefreshContractError()
        index: PublicSolutionEmbeddingIndex | PublicSolutionEmbeddingIndexV4 | None = None
        if previous is not None:
            pointer = ArtifactMemberPointer.model_validate(
                raw_similarity_contract_value(previous[0])
            )
            registered = (
                metadata_version == "4.0"
                and pointer.schema_ref == REGISTERED_PUBLIC_SOLUTION_INDEX_SCHEMA_REF
            )
            index = (
                PublicSolutionEmbeddingIndexV4.model_validate(
                    raw_similarity_contract_value(previous[1])
                )
                if registered
                else PublicSolutionEmbeddingIndex.model_validate(
                    raw_similarity_contract_value(previous[1])
                )
            )
            if (
                pointer.member_path != "index.json"
                or pointer.schema_ref
                != (
                    REGISTERED_PUBLIC_SOLUTION_INDEX_SCHEMA_REF
                    if registered
                    else PUBLIC_SOLUTION_INDEX_SCHEMA_REF
                )
                or pointer.media_type != "application/json"
                or pointer.sha256 != content_sha256(index.model_dump(mode="json"))
            ):
                raise IndexRefreshContractError()
        if not bindings:
            return None
        _require_binding_scope(bindings, index)
        if (
            index is not None
            and index.bindings == bindings
            and (metadata_version == "3.0" or isinstance(index, PublicSolutionEmbeddingIndexV4))
        ):
            return None
        return "MISSING_NAMESPACE_INDEX" if index is None else "INDEX_MEMBERSHIP_CHANGED"
    except (ValueError, TypeError, AttributeError, SchemaError):
        raise IndexRefreshContractError() from None
