"""Pure initial/private replay intent closure; actual Chat/Catalog authority stays upstream."""

from eom_catalog_contracts.embedding_reference_query import raw_similarity_contract_value
from eom_catalog_contracts.private_chat_similarity_v2 import (
    PrivateChatSimilarityRequestV2,
    SupportedPrivateChatSimilarityRequest,
    parse_supported_private_chat_similarity_request,
)
from eom_catalog_contracts.public_solution_embedding_index import PublicSolutionIndexNamespace
from jsonschema.exceptions import ValidationError as SchemaError

from eom_catalog_service.embedding_registry_ports import (
    EmbeddingRegistryError,
    EmbeddingRegistryOwnerConfiguration,
    PrivateChatContextPreparation,
)


def validate_private_chat_context_preparation(
    preparation: PrivateChatContextPreparation,
    configuration: EmbeddingRegistryOwnerConfiguration,
    request: SupportedPrivateChatSimilarityRequest | None = None,
) -> None:
    """Compare intent, not a newly selected index head or source ownership."""
    if type(preparation) is not PrivateChatContextPreparation:
        raise EmbeddingRegistryError("EMBEDDING_REGISTRY_REQUEST_INVALID")
    preparation.__post_init__()
    scope = preparation.scope
    if (
        scope.corpus_id != configuration.corpus_id
        or scope.namespace != configuration.namespace
        or preparation.spaces.document != configuration.space
    ):
        raise EmbeddingRegistryError("EMBEDDING_REGISTRY_SOURCE_PIN_MISMATCH")
    if request is None:
        return
    try:
        request = parse_supported_private_chat_similarity_request(
            raw_similarity_contract_value(request)
        )
    except (ValueError, TypeError, SchemaError):
        raise EmbeddingRegistryError("EMBEDDING_REGISTRY_REQUEST_INVALID") from None
    if (
        isinstance(request, PrivateChatSimilarityRequestV2)
        != isinstance(configuration.namespace, PublicSolutionIndexNamespace)
        or request.request_id != preparation.request_id
        or request.query_basis != preparation.query_basis
        or request.graph_snapshot != scope.graph_snapshot
        or request.policy_revision_id != scope.policy_revision_id
        or request.policy_sha256 != scope.policy_sha256
        or request.source_classes != configuration.source_classes
        or request.maximum_sources != scope.maximum_sources
        or request.top_k != preparation.top_k
        or request.views[0].recipe != configuration.recipe
        or (
            request.views[0].index is not None
            and request.views[0].index.spaces != preparation.spaces
        )
    ):
        raise EmbeddingRegistryError("EMBEDDING_REGISTRY_SOURCE_PIN_MISMATCH")
