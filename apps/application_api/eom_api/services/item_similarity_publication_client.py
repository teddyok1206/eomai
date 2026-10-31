"""Fixed Catalog publication adapter; no native/source/store authority in the API."""

from __future__ import annotations

import grp
import pwd
from pathlib import Path
from typing import Any

from eom_catalog_contracts import CATALOG_APPLICATION_SOCKET_PATH
from eom_catalog_contracts.item_similarity_publication import (
    MAX_ITEM_SIMILARITY_PUBLICATION_REPLY_BYTES,
    MAX_ITEM_SIMILARITY_PUBLICATION_REQUEST_BYTES,
    ItemSimilarityPublication,
    ItemSimilarityPublicationErrorCode,
    ItemSimilarityPublicationReply,
    ItemSimilarityPublicationReplyV2,
    ItemSimilarityPublicationRequest,
    ItemSimilarityPublicationRequestV2,
    ItemSimilarityPublicationV2,
    SupportedItemSimilarityPublicationRequest,
    validate_item_similarity_publication_reply,
    validate_public_item_similarity_publication_reply,
)
from eom_catalog_contracts.similarity_read import CompletedSimilarityQuerySelection
from eom_orchestrator.general_chat_socket import (
    ChatSocketEndpoint,
    ChatTransportError,
    exchange_chat_frame,
)
from jsonschema.exceptions import ValidationError as SchemaError


class ItemSimilarityPublicationClientError(ValueError):
    def __init__(self, code: ItemSimilarityPublicationErrorCode) -> None:
        self.code = code
        super().__init__(code)


class CatalogItemSimilarityPublicationClient:
    """Trusted API application supplies its authenticated operator and exact QUERY."""

    def __init__(self, endpoint: ChatSocketEndpoint | None = None) -> None:
        self.endpoint = endpoint

    def publish(
        self, actor_id: str, selection: CompletedSimilarityQuerySelection
    ) -> ItemSimilarityPublication:
        try:
            request = ItemSimilarityPublicationRequest(
                schema_version="system-rag-item-similarity-publication-request/1.0",
                operation="PUBLISH_ITEM_SIMILARITY_CONTEXT",
                actor_id=actor_id,
                selection=selection,
            )
        except (ValueError, SchemaError):
            raise ItemSimilarityPublicationClientError(
                "ITEM_SIMILARITY_PUBLICATION_REQUEST_INVALID"
            ) from None
        try:
            value = self._exchange(request)
            reply = ItemSimilarityPublicationReply.model_validate(value)
            validate_item_similarity_publication_reply(request, reply)
        except (ValueError, SchemaError, ChatTransportError, KeyError, OSError):
            # A timeout is not proof that Catalog did not commit. No automatic retry.
            raise ItemSimilarityPublicationClientError(
                "ITEM_SIMILARITY_PUBLICATION_UNAVAILABLE"
            ) from None
        if reply.publication is None:
            raise ItemSimilarityPublicationClientError(
                reply.error_code or "ITEM_SIMILARITY_PUBLICATION_UNAVAILABLE"
            )
        return reply.publication

    def publish_public(
        self, actor_id: str, selection: CompletedSimilarityQuerySelection
    ) -> ItemSimilarityPublicationV2:
        try:
            request = ItemSimilarityPublicationRequestV2(
                schema_version="system-rag-item-similarity-publication-request/2.0",
                operation="PUBLISH_ITEM_SIMILARITY_CONTEXT",
                actor_id=actor_id,
                selection=selection,
            )
        except (ValueError, SchemaError):
            raise ItemSimilarityPublicationClientError(
                "ITEM_SIMILARITY_PUBLICATION_REQUEST_INVALID"
            ) from None
        try:
            reply = ItemSimilarityPublicationReplyV2.model_validate(self._exchange(request))
            validate_public_item_similarity_publication_reply(request, reply)
        except (ValueError, SchemaError, ChatTransportError, KeyError, OSError):
            # Retain the exact selection on timeout; do not retry or use the legacy route.
            raise ItemSimilarityPublicationClientError(
                "ITEM_SIMILARITY_PUBLICATION_UNAVAILABLE"
            ) from None
        if reply.publication is None:
            raise ItemSimilarityPublicationClientError(
                reply.error_code or "ITEM_SIMILARITY_PUBLICATION_UNAVAILABLE"
            )
        return reply.publication

    def _exchange(self, request: SupportedItemSimilarityPublicationRequest) -> dict[str, Any]:
        endpoint = self.endpoint or ChatSocketEndpoint(
            Path(CATALOG_APPLICATION_SOCKET_PATH),
            pwd.getpwnam("eom-catalog-manager").pw_uid,
            grp.getgrnam("eom-api").gr_gid,
        )
        return exchange_chat_frame(
            endpoint,
            request.model_dump(mode="json"),
            request_limit=MAX_ITEM_SIMILARITY_PUBLICATION_REQUEST_BYTES,
            reply_limit=MAX_ITEM_SIMILARITY_PUBLICATION_REPLY_BYTES,
            timeout=30.0,
        )
