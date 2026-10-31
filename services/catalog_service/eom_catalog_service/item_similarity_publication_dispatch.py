"""Closed pointer-only publication dispatch, after the installed API-only peer gate."""

from __future__ import annotations

from eom_catalog_contracts.item_similarity_publication import (
    MAX_ITEM_SIMILARITY_PUBLICATION_REPLY_BYTES,
    MAX_ITEM_SIMILARITY_PUBLICATION_REQUEST_BYTES,
    ItemSimilarityPublicationErrorCode,
    ItemSimilarityPublicationReply,
    ItemSimilarityPublicationReplyV2,
    ItemSimilarityPublicationRequestV2,
    SupportedItemSimilarityPublicationReply,
    SupportedItemSimilarityPublicationRequest,
    parse_supported_item_similarity_publication_request,
    validate_item_similarity_publication_reply,
    validate_public_item_similarity_publication_reply,
)
from eom_identifiers import canonical_json_bytes, content_sha256
from eom_identity_service import OperatorAuthorizationFenceError
from eom_orchestrator.control_service import ControlPlaneError
from eom_orchestrator.general_chat_socket import ChatTransportError, decode_chat_frame
from jsonschema.exceptions import ValidationError as SchemaError

from eom_catalog_service.item_similarity_publication_service import (
    CatalogItemSimilarityPublicationService,
)
from eom_catalog_service.similarity_context_ports import SimilarityContextReadError


def _failed(
    request: SupportedItemSimilarityPublicationRequest | None,
    code: ItemSimilarityPublicationErrorCode,
) -> SupportedItemSimilarityPublicationReply:
    reply_type = (
        ItemSimilarityPublicationReplyV2
        if isinstance(request, ItemSimilarityPublicationRequestV2)
        else ItemSimilarityPublicationReply
    )
    return reply_type.model_validate(
        dict(
            schema_version=(
                "system-rag-item-similarity-publication-reply/2.0"
                if isinstance(request, ItemSimilarityPublicationRequestV2)
                else "system-rag-item-similarity-publication-reply/1.0"
            ),
            operation="PUBLISH_ITEM_SIMILARITY_CONTEXT",
            status="FAILED",
            actor_id=None if request is None else request.actor_id,
            request_sha256=None
            if request is None
            else content_sha256(request.model_dump(mode="json")),
            publication=None,
            error_code=code,
        )
    )


def dispatch_item_similarity_publication_frame(
    service: CatalogItemSimilarityPublicationService | None, raw: bytes
) -> bytes:
    request: SupportedItemSimilarityPublicationRequest | None = None
    try:
        if len(raw) > MAX_ITEM_SIMILARITY_PUBLICATION_REQUEST_BYTES:
            return (
                canonical_json_bytes(_failed(None, "ITEM_SIMILARITY_PUBLICATION_BUDGET_EXCEEDED"))
                + b"\n"
            )
        if not raw.endswith(b"\n") or b"\n" in raw[:-1]:
            raise ValueError("invalid publication frame")
        request = parse_supported_item_similarity_publication_request(decode_chat_frame(raw[:-1]))
    except (ValueError, SchemaError, ChatTransportError, RecursionError):
        return (
            canonical_json_bytes(_failed(None, "ITEM_SIMILARITY_PUBLICATION_REQUEST_INVALID"))
            + b"\n"
        )
    try:
        if service is None:
            return (
                canonical_json_bytes(_failed(request, "ITEM_SIMILARITY_PUBLICATION_UNAVAILABLE"))
                + b"\n"
            )
        reply: SupportedItemSimilarityPublicationReply
        if isinstance(request, ItemSimilarityPublicationRequestV2):
            public_reply = ItemSimilarityPublicationReplyV2(
                schema_version="system-rag-item-similarity-publication-reply/2.0",
                operation="PUBLISH_ITEM_SIMILARITY_CONTEXT",
                status="SUCCESS",
                actor_id=request.actor_id,
                request_sha256=content_sha256(request.model_dump(mode="json")),
                publication=service.publish_public(request),
                error_code=None,
            )
            validate_public_item_similarity_publication_reply(request, public_reply)
            reply = public_reply
        else:
            legacy_reply = ItemSimilarityPublicationReply(
                schema_version="system-rag-item-similarity-publication-reply/1.0",
                operation="PUBLISH_ITEM_SIMILARITY_CONTEXT",
                status="SUCCESS",
                actor_id=request.actor_id,
                request_sha256=content_sha256(request.model_dump(mode="json")),
                publication=service.publish(request),
                error_code=None,
            )
            validate_item_similarity_publication_reply(request, legacy_reply)
            reply = legacy_reply
        raw_reply = canonical_json_bytes(reply) + b"\n"
        if len(raw_reply) > MAX_ITEM_SIMILARITY_PUBLICATION_REPLY_BYTES:
            raise ValueError("publication reply bound exceeded")
        return raw_reply
    except SimilarityContextReadError as error:
        try:
            reply = _failed(request, error.code)
        except (ValueError, SchemaError):
            reply = _failed(request, "ITEM_SIMILARITY_PUBLICATION_UNAVAILABLE")
    except OperatorAuthorizationFenceError:
        reply = _failed(request, "AUTHORITY_UNAVAILABLE")
    except ControlPlaneError as error:
        reply = _failed(
            request,
            "SOURCE_ACCESS_DENIED"
            if error.code == "CONTROL_SIMILARITY_AUTHORITY_DENIED"
            else "AUTHORITY_UNAVAILABLE"
            if error.code == "CONTROL_SIMILARITY_AUTHORITY_UNAVAILABLE"
            else "ITEM_SIMILARITY_PUBLICATION_UNAVAILABLE",
        )
    except Exception:
        # A publication may already be committed. Preserve it; never retry here.
        reply = _failed(request, "ITEM_SIMILARITY_PUBLICATION_UNAVAILABLE")
    return canonical_json_bytes(reply) + b"\n"
