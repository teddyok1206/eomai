"""Fixed existing Catalog peer read; no direct storage, model or authentication bypass."""

import grp
import pwd
from pathlib import Path

from eom_catalog_contracts import CATALOG_APPLICATION_SOCKET_PATH
from eom_catalog_contracts.item_db_similarity_selection import (
    MAX_ITEM_DB_SIMILARITY_SELECTION_BYTES,
    ItemDbSimilaritySelectionReply,
    ItemDbSimilaritySelectionRequest,
    validate_item_db_similarity_selection_reply,
)
from eom_orchestrator.general_chat_socket import (
    ChatSocketEndpoint,
    ChatTransportError,
    exchange_chat_frame,
)
from jsonschema.exceptions import ValidationError as SchemaError


class ItemDbSimilarityClientError(ValueError):
    def __init__(self) -> None:
        self.code = "ITEM_DB_SIMILARITY_UNAVAILABLE"
        super().__init__(self.code)


class CatalogItemDbSimilarityClient:
    def __init__(self, endpoint: ChatSocketEndpoint | None = None) -> None:
        self.endpoint = endpoint

    def resolve(self, request: ItemDbSimilaritySelectionRequest) -> ItemDbSimilaritySelectionReply:
        try:
            request = ItemDbSimilaritySelectionRequest.model_validate(request)
            endpoint = self.endpoint or ChatSocketEndpoint(
                Path(CATALOG_APPLICATION_SOCKET_PATH),
                pwd.getpwnam("eom-catalog-manager").pw_uid,
                grp.getgrnam("eom-api").gr_gid,
            )
            raw = exchange_chat_frame(
                endpoint,
                request.model_dump(mode="json"),
                request_limit=MAX_ITEM_DB_SIMILARITY_SELECTION_BYTES,
                reply_limit=MAX_ITEM_DB_SIMILARITY_SELECTION_BYTES,
                timeout=90.0,
            )
            reply = ItemDbSimilaritySelectionReply.model_validate(raw)
            validate_item_db_similarity_selection_reply(request, reply)
            return reply
        except (ValueError, SchemaError, ChatTransportError, KeyError, OSError):
            raise ItemDbSimilarityClientError() from None
