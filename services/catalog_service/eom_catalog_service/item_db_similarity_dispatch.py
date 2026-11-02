"""One bounded Catalog read operation after the existing API-only peer gate."""

from eom_catalog_contracts.item_db_similarity_selection import (
    MAX_ITEM_DB_SIMILARITY_SELECTION_BYTES,
    ItemDbSimilaritySelectionErrorCode,
    ItemDbSimilaritySelectionReply,
    ItemDbSimilaritySelectionRequest,
    validate_item_db_similarity_selection_reply,
)
from eom_catalog_contracts.item_db_similarity_selection_v2 import (
    ItemDbSimilaritySelectionReplyV2,
    ItemDbSimilaritySelectionRequestV2,
    validate_item_db_similarity_selection_reply_v2,
)
from eom_identifiers import canonical_json_bytes, content_sha256
from eom_orchestrator.general_chat_socket import ChatTransportError, decode_chat_frame
from jsonschema.exceptions import ValidationError as SchemaError

from eom_catalog_service.item_db_similarity_selection import (
    CatalogItemDbSimilaritySelection,
    ItemDbSimilaritySelectionError,
)


def _failed(
    request: ItemDbSimilaritySelectionRequest | ItemDbSimilaritySelectionRequestV2 | None,
    code: ItemDbSimilaritySelectionErrorCode,
) -> ItemDbSimilaritySelectionReply | ItemDbSimilaritySelectionReplyV2:
    reply_type = (
        ItemDbSimilaritySelectionReplyV2
        if isinstance(request, ItemDbSimilaritySelectionRequestV2)
        else ItemDbSimilaritySelectionReply
    )
    return reply_type.model_validate(
        dict(
            schema_version="item-db-similarity-selection-reply/2.0"
            if isinstance(request, ItemDbSimilaritySelectionRequestV2)
            else "item-db-similarity-selection-reply/1.0",
            operation="RESOLVE_ITEM_DB_SIMILARITY_LIST"
            if isinstance(request, ItemDbSimilaritySelectionRequestV2)
            else "RESOLVE_ITEM_DB_SIMILARITY",
            status="UNAVAILABLE"
            if code
            in {
                "ITEM_DB_SIMILARITY_NOT_REGISTERED",
                "ITEM_DB_SIMILARITY_NOT_INDEXED",
                "ITEM_DB_SIMILARITY_UNAVAILABLE",
            }
            else "FAILED",
            actor_id=request.actor_id if request else None,
            request_sha256=content_sha256(request) if request else None,
            result=None,
            error_code=code,
        )
    )


def dispatch_item_db_similarity_selection(
    service: CatalogItemDbSimilaritySelection | None,
    raw: bytes,
) -> bytes:
    request: ItemDbSimilaritySelectionRequest | ItemDbSimilaritySelectionRequestV2 | None = None
    try:
        if (
            len(raw) > MAX_ITEM_DB_SIMILARITY_SELECTION_BYTES
            or not raw.endswith(b"\n")
            or b"\n" in raw[:-1]
        ):
            raise ValueError("invalid frame")
        document = decode_chat_frame(raw[:-1])
        request = (
            ItemDbSimilaritySelectionRequestV2.model_validate(document)
            if document.get("schema_version") == "item-db-similarity-selection-request/2.0"
            else ItemDbSimilaritySelectionRequest.model_validate(document)
        )
    except (ValueError, SchemaError, ChatTransportError, RecursionError):
        return canonical_json_bytes(_failed(None, "ITEM_DB_SIMILARITY_REQUEST_INVALID")) + b"\n"
    reply: ItemDbSimilaritySelectionReply | ItemDbSimilaritySelectionReplyV2
    try:
        if service is None:
            raise ItemDbSimilaritySelectionError("ITEM_DB_SIMILARITY_UNAVAILABLE")
        if isinstance(request, ItemDbSimilaritySelectionRequestV2):
            reply = ItemDbSimilaritySelectionReplyV2(
                schema_version="item-db-similarity-selection-reply/2.0",
                operation="RESOLVE_ITEM_DB_SIMILARITY_LIST",
                status="READY",
                actor_id=request.actor_id,
                request_sha256=content_sha256(request),
                result=service.resolve_many(request),
                error_code=None,
            )
            validate_item_db_similarity_selection_reply_v2(request, reply)
        else:
            reply = ItemDbSimilaritySelectionReply(
                schema_version="item-db-similarity-selection-reply/1.0",
                operation="RESOLVE_ITEM_DB_SIMILARITY",
                status="READY",
                actor_id=request.actor_id,
                request_sha256=content_sha256(request),
                result=service.resolve(request),
                error_code=None,
            )
            validate_item_db_similarity_selection_reply(request, reply)
    except ItemDbSimilaritySelectionError as error:
        reply = _failed(request, error.code)
    except Exception:
        reply = _failed(request, "ITEM_DB_SIMILARITY_UNAVAILABLE")
    return canonical_json_bytes(reply) + b"\n"
