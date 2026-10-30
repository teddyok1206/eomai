"""One bounded Catalog read operation after the existing API-only peer gate."""

from eom_catalog_contracts.item_db_similarity_selection import (
    MAX_ITEM_DB_SIMILARITY_SELECTION_BYTES,
    ItemDbSimilaritySelectionErrorCode,
    ItemDbSimilaritySelectionReply,
    ItemDbSimilaritySelectionRequest,
    validate_item_db_similarity_selection_reply,
)
from eom_identifiers import canonical_json_bytes, content_sha256
from eom_orchestrator.general_chat_socket import ChatTransportError, decode_chat_frame
from jsonschema.exceptions import ValidationError as SchemaError

from eom_catalog_service.item_db_similarity_selection import (
    CatalogItemDbSimilaritySelection,
    ItemDbSimilaritySelectionError,
)


def _failed(
    request: ItemDbSimilaritySelectionRequest | None,
    code: ItemDbSimilaritySelectionErrorCode,
) -> ItemDbSimilaritySelectionReply:
    return ItemDbSimilaritySelectionReply(
        schema_version="item-db-similarity-selection-reply/1.0",
        operation="RESOLVE_ITEM_DB_SIMILARITY",
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


def dispatch_item_db_similarity_selection(
    service: CatalogItemDbSimilaritySelection | None,
    raw: bytes,
) -> bytes:
    request = None
    try:
        if (
            len(raw) > MAX_ITEM_DB_SIMILARITY_SELECTION_BYTES
            or not raw.endswith(b"\n")
            or b"\n" in raw[:-1]
        ):
            raise ValueError("invalid frame")
        request = ItemDbSimilaritySelectionRequest.model_validate(decode_chat_frame(raw[:-1]))
    except (ValueError, SchemaError, ChatTransportError, RecursionError):
        return canonical_json_bytes(_failed(None, "ITEM_DB_SIMILARITY_REQUEST_INVALID")) + b"\n"
    try:
        if service is None:
            raise ItemDbSimilaritySelectionError("ITEM_DB_SIMILARITY_UNAVAILABLE")
        result = service.resolve(request)
        reply = ItemDbSimilaritySelectionReply(
            schema_version="item-db-similarity-selection-reply/1.0",
            operation="RESOLVE_ITEM_DB_SIMILARITY",
            status="READY",
            actor_id=request.actor_id,
            request_sha256=content_sha256(request),
            result=result,
            error_code=None,
        )
        validate_item_db_similarity_selection_reply(request, reply)
    except ItemDbSimilaritySelectionError as error:
        reply = _failed(request, error.code)
    except Exception:
        reply = _failed(request, "ITEM_DB_SIMILARITY_UNAVAILABLE")
    return canonical_json_bytes(reply) + b"\n"
