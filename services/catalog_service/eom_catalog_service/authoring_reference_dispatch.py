"""Bounded read-only reference selection, after the existing API-only peer gate."""

from typing import cast

from eom_catalog_contracts.authoring_reference import (
    MAX_AUTHORING_REFERENCE_REPLY_BYTES,
    MAX_AUTHORING_REFERENCE_REQUEST_BYTES,
    AuthoringReferenceErrorCode,
    AuthoringReferenceReply,
    AuthoringReferenceRequest,
    validate_authoring_reference_reply,
)
from eom_identifiers import canonical_json_bytes, content_sha256
from eom_identity_service import OperatorAuthorizationFenceError
from eom_orchestrator.general_chat_socket import ChatTransportError, decode_chat_frame
from jsonschema.exceptions import ValidationError as SchemaError

from eom_catalog_service.authoring_reference_selection import CatalogAuthoringReferenceSelection
from eom_catalog_service.embedding_registry_ports import EmbeddingRegistryError
from eom_catalog_service.similarity_context_ports import (
    SimilarityContextReadError,
    similarity_context_error_from_registry,
)


def _failed(
    request: AuthoringReferenceRequest | None, code: AuthoringReferenceErrorCode
) -> AuthoringReferenceReply:
    return AuthoringReferenceReply(
        schema_version="system-rag-authoring-reference-reply/1.0",
        operation="SELECT_ITEM_AUTHORING_REFERENCE",
        status="FAILED",
        actor_id=None if request is None else request.actor_id,
        request_sha256=None if request is None else content_sha256(request),
        selection=None,
        error_code=code,
    )


def dispatch_authoring_reference_frame(
    service: CatalogAuthoringReferenceSelection | None, raw: bytes
) -> bytes:
    request: AuthoringReferenceRequest | None = None
    try:
        if (
            len(raw) > MAX_AUTHORING_REFERENCE_REQUEST_BYTES
            or not raw.endswith(b"\n")
            or b"\n" in raw[:-1]
        ):
            raise ValueError("invalid reference frame")
        request = AuthoringReferenceRequest.model_validate(decode_chat_frame(raw[:-1]))
    except (ValueError, SchemaError, ChatTransportError, RecursionError):
        return canonical_json_bytes(_failed(None, "AUTHORING_REFERENCE_REQUEST_INVALID")) + b"\n"
    try:
        if service is None:
            raise SimilarityContextReadError("AUTHORITY_UNAVAILABLE")
        selection = service.select(request)
        reply = AuthoringReferenceReply(
            schema_version="system-rag-authoring-reference-reply/1.0",
            operation="SELECT_ITEM_AUTHORING_REFERENCE",
            status="SELECTED" if selection is not None else "UNAVAILABLE",
            actor_id=request.actor_id,
            request_sha256=content_sha256(request),
            selection=selection,
            error_code=None if selection is not None else "REFERENCE_NOT_OFFERED",
        )
        validate_authoring_reference_reply(request, reply)
        result = canonical_json_bytes(reply) + b"\n"
        if len(result) > MAX_AUTHORING_REFERENCE_REPLY_BYTES:
            raise ValueError("invalid reference reply")
        return result
    except OperatorAuthorizationFenceError:
        reply = _failed(request, "AUTHORITY_UNAVAILABLE")
    except (EmbeddingRegistryError, SimilarityContextReadError) as error:
        code = (
            similarity_context_error_from_registry(error).code
            if isinstance(error, EmbeddingRegistryError)
            else error.code
        )
        reply = _failed(
            request,
            cast(AuthoringReferenceErrorCode, code)
            if code
            in {
                "SOURCE_ACCESS_DENIED",
                "SOURCE_REVOKED",
                "SOURCE_POINTER_INVALID",
                "SOURCE_HASH_MISMATCH",
                "AUTHORITY_UNAVAILABLE",
            }
            else "AUTHORING_REFERENCE_UNAVAILABLE",
        )
    except Exception:
        # No partial pointer, arbitrary exception text, fallback source or retry.
        reply = _failed(request, "AUTHORING_REFERENCE_UNAVAILABLE")
    return canonical_json_bytes(reply) + b"\n"
