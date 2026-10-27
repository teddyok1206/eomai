"""Closed runner-only frames for current creative source authorization."""

from __future__ import annotations

from eom_catalog_contracts.external_item_learning_authorization import (
    MAX_EXTERNAL_ITEM_LEARNING_AUTHORIZATION_BYTES,
    ExternalItemLearningAuthorizationErrorCode,
    ExternalItemLearningAuthorizationReply,
    ExternalItemLearningAuthorizationRequest,
    validate_external_item_learning_authorization_reply,
)
from eom_identifiers import canonical_json_bytes, content_sha256
from eom_orchestrator.general_chat_socket import ChatTransportError, decode_chat_frame
from jsonschema.exceptions import ValidationError as SchemaError

from eom_catalog_service.external_item_learning_authorization_service import (
    CatalogExternalItemLearningAuthorizationService,
    ExternalItemLearningAuthorizationServiceError,
)


def _failed(
    request: ExternalItemLearningAuthorizationRequest | None,
    code: ExternalItemLearningAuthorizationErrorCode,
) -> bytes:
    reply = ExternalItemLearningAuthorizationReply(
        schema_version="external-item-learning-authorization-reply/1.0",
        operation="AUTHORIZE_EXTERNAL_ITEM_LEARNING_INPUT",
        status="FAILED",
        request_sha256=None if request is None else content_sha256(request.model_dump(mode="json")),
        source_input_sha256=None,
        error_code=code,
    )
    return canonical_json_bytes(reply.model_dump(mode="json")) + b"\n"


def dispatch_external_item_learning_authorization_frame(
    service: CatalogExternalItemLearningAuthorizationService | None, raw: bytes
) -> bytes:
    try:
        if (
            len(raw) > MAX_EXTERNAL_ITEM_LEARNING_AUTHORIZATION_BYTES
            or not raw.endswith(b"\n")
            or b"\n" in raw[:-1]
        ):
            raise ValueError("invalid frame")
        request = ExternalItemLearningAuthorizationRequest.model_validate(
            decode_chat_frame(raw[:-1])
        )
    except (ValueError, TypeError, SchemaError, ChatTransportError, RecursionError):
        return _failed(None, "EXTERNAL_CREATIVE_AUTHORIZATION_REQUEST_INVALID")
    if service is None:
        return _failed(request, "EXTERNAL_CREATIVE_AUTHORIZATION_UNAVAILABLE")
    try:
        reply = ExternalItemLearningAuthorizationReply.model_validate(service.authorize(request))
        validate_external_item_learning_authorization_reply(
            request, reply, expected_source_input_sha256=reply.source_input_sha256 or ""
        )
        return canonical_json_bytes(reply.model_dump(mode="json")) + b"\n"
    except ExternalItemLearningAuthorizationServiceError as exc:
        return _failed(request, exc.code)
    except Exception:
        return _failed(request, "EXTERNAL_CREATIVE_AUTHORIZATION_UNAVAILABLE")
