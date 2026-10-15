"""Pure initial/replay intent closure; actual source/index authority stays with Catalog."""

from eom_catalog_contracts.similarity_context import (
    SimilarityContextRequest,
    parse_similarity_context_request,
)

from eom_catalog_service.embedding_registry_ports import (
    EmbeddingRegistryError,
    EmbeddingRegistryOwnerConfiguration,
    ReferenceQueryContextPreparation,
)


def validate_reference_query_context_preparation(
    preparation: ReferenceQueryContextPreparation,
    configuration: EmbeddingRegistryOwnerConfiguration,
    request: SimilarityContextRequest | None = None,
) -> None:
    """Replay compares intent, never a newly selected head/profile or new audit."""
    if type(preparation) is not ReferenceQueryContextPreparation:
        raise EmbeddingRegistryError("EMBEDDING_REGISTRY_REQUEST_INVALID")
    preparation.__post_init__()
    scope = preparation.selection.scope
    if (
        scope.corpus_id != configuration.corpus_id
        or scope.namespace != configuration.namespace
        or preparation.spaces.document != configuration.space
    ):
        raise EmbeddingRegistryError("EMBEDDING_REGISTRY_SOURCE_PIN_MISMATCH")
    if request is None:
        return
    request = parse_similarity_context_request(request)
    if (
        request.request_id != preparation.request_id
        or request.consumer_purpose != "PAST_EXAM_VARIATION"
        or request.anchor.source.item_revision_id != preparation.selection.source_revision_ids[0]
        or request.anchor.source.source_class != "PAST_EXAM"
        or request.graph_snapshot != scope.graph_snapshot
        or request.policy_revision_id != scope.policy_revision_id
        or request.policy_sha256 != scope.policy_sha256
        or request.source_classes != configuration.source_classes
        or request.topics
        or request.unit_ids
        or request.maximum_sources != scope.maximum_sources
        or request.top_k != preparation.top_k
        or request.vector_mode != preparation.vector_mode
        or tuple(row.view for row in request.views) != preparation.views
        or any(
            row.recipe != configuration.recipe
            or (row.index is not None and row.index.spaces != preparation.spaces)
            for row in request.views
        )
    ):
        raise EmbeddingRegistryError("EMBEDDING_REGISTRY_SOURCE_PIN_MISMATCH")
