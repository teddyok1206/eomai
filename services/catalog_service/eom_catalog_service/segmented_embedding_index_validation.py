"""Pure content closure for a segmented index after Catalog has reopened pinned members.

This checks no actor or Graph permission. The Catalog publication/read use case must
first reauthorize the exact current population and resolve every immutable Artifact.
"""

from __future__ import annotations

from eom_catalog_contracts.embedding_reference_query import raw_similarity_contract_value
from eom_catalog_contracts.segmented_embedding_index import (
    MAX_SEGMENTS,
    SegmentedEmbeddingIndexRoot,
)
from eom_identifiers import content_sha256
from eom_protocol.artifact_members import ArtifactMemberPointer
from jsonschema.exceptions import ValidationError as SchemaError

from eom_catalog_service.embedding_device_index_pair import (
    canonical_embedding_index_targets,
    validate_resolved_embedding_index,
)
from eom_catalog_service.embedding_registry_ports import SupportedEmbeddingIndex
from eom_catalog_service.segmented_local_indexing_population_read import (
    SegmentedSourceSelection,
    segmented_source_selection_sha256,
)


class SegmentedEmbeddingIndexError(ValueError):
    def __init__(self) -> None:
        super().__init__("SEGMENTED_EMBEDDING_INDEX_CONTENT_MISMATCH")


def validate_segmented_embedding_index_content(
    root: SegmentedEmbeddingIndexRoot,
    resolved: tuple[tuple[ArtifactMemberPointer, SupportedEmbeddingIndex], ...],
    selection: SegmentedSourceSelection,
) -> SegmentedEmbeddingIndexRoot:
    """O(total bindings) closure; the caller owns the authorized source scan."""
    try:
        root = SegmentedEmbeddingIndexRoot.model_validate(raw_similarity_contract_value(root))
        if (
            type(resolved) is not tuple
            or len(resolved) != len(root.segments)
            or type(selection) is not SegmentedSourceSelection
            or selection.graph_snapshot_revision_id
            != root.graph_snapshot.graph_snapshot_revision_id
            or selection.policy_revision_id != root.policy_revision_id
            or selection.source_count != root.source_count
            or selection.selection_sha256 != root.source_selection_sha256
            or not 2 <= len(selection.segments) <= MAX_SEGMENTS
            or sum(segment.source_count for segment in selection.segments) != selection.source_count
            or any(
                not 1 <= segment.source_count <= 1024
                or segment.first_source_revision_id > segment.last_source_revision_id
                for segment in selection.segments
            )
            or any(
                left.last_source_revision_id >= right.first_source_revision_id
                for left, right in zip(selection.segments, selection.segments[1:], strict=False)
            )
            or selection.selection_sha256
            != segmented_source_selection_sha256(
                selection.graph_snapshot_revision_id,
                selection.policy_revision_id,
                selection.segments,
            )
        ):
            raise SegmentedEmbeddingIndexError()
        index_ids: set[str] = set()
        revision_ids: set[str] = set()
        for descriptor, (member, original) in zip(root.segments, resolved, strict=True):
            pointer, index = validate_resolved_embedding_index(
                member, original, root.space.runtime.device
            )
            if (
                pointer != descriptor.index_manifest
                or index.index_id == root.index_id
                or index.index_id in index_ids
                or index.index_revision_id in revision_ids
                or index.storage_partition != root.storage_partition
                or index.space != root.space
                or index.view != root.view
                or index.recipe != root.recipe
                or len(index.bindings) != descriptor.binding_count
                or not index.bindings
                or index.bindings[0].source.item_revision_id != descriptor.first_source_revision_id
                or index.bindings[-1].source.item_revision_id != descriptor.last_source_revision_id
                or content_sha256(canonical_embedding_index_targets(index))
                != descriptor.target_set_sha256
            ):
                raise SegmentedEmbeddingIndexError()
            index_ids.add(index.index_id)
            revision_ids.add(index.index_revision_id)
            if any(
                binding.graph_snapshot != root.graph_snapshot
                or binding.policy_revision_id != root.policy_revision_id
                or binding.policy_sha256 != root.policy_sha256
                for binding in index.bindings
            ):
                raise SegmentedEmbeddingIndexError()
        return root
    except SegmentedEmbeddingIndexError:
        raise
    except (SchemaError, ValueError, TypeError, AttributeError):
        raise SegmentedEmbeddingIndexError() from None
