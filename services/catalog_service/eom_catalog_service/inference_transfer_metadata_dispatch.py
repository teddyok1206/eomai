"""Bounded metadata frame dispatch; the server checks the fixed API peer first."""

from __future__ import annotations

from typing import cast

from eom_catalog_contracts.inference_transfer_metadata import (
    MAX_METADATA_FRAME_BYTES,
    METADATA_ERRORS,
    InferenceTransferMetadataBindingReply,
    InferenceTransferMetadataBindingRequest,
    InferenceTransferMetadataError,
    parse_metadata_binding_reply,
    parse_metadata_binding_request,
    validate_metadata_binding_reply,
)
from eom_identifiers import canonical_json_bytes
from eom_orchestrator.general_chat_socket import ChatTransportError, decode_chat_frame
from jsonschema import ValidationError as SchemaError

from eom_catalog_service.inference_transfer_metadata_service import (
    CatalogInferenceTransferMetadataService,
)
from eom_catalog_service.inference_transfer_service import InferenceTransferServiceError


def dispatch_metadata_frame(
    service: CatalogInferenceTransferMetadataService | None, raw: bytes
) -> bytes:
    request: InferenceTransferMetadataBindingRequest | None = None
    error: InferenceTransferMetadataError = "INFERENCE_TRANSFER_METADATA_REQUEST_INVALID"
    try:
        if len(raw) > MAX_METADATA_FRAME_BYTES:
            error = "INFERENCE_TRANSFER_METADATA_BUDGET_EXCEEDED"
            raise ValueError("metadata frame exceeds bound")
        if not raw.endswith(b"\n") or b"\n" in raw[:-1]:
            raise ValueError("metadata frame must have exactly one terminal newline")
        request = parse_metadata_binding_request(decode_chat_frame(raw[:-1]))
        if service is None:
            raise InferenceTransferServiceError("INFERENCE_TRANSFER_METADATA_UNAVAILABLE")
        result = service.resolve(request.actor_id, request.request)
        reply = InferenceTransferMetadataBindingReply(
            status="SUCCESS",
            actor_id=request.actor_id,
            request_sha256=request.request.request_sha256,
            result=result,
            error_code=None,
        )
        validate_metadata_binding_reply(request, reply)
    except InferenceTransferServiceError as exc:
        error = (
            cast(InferenceTransferMetadataError, exc.code)
            if exc.code in METADATA_ERRORS
            else ("INFERENCE_TRANSFER_METADATA_UNAVAILABLE")
        )
        reply = _failed(request, error)
    except (ValueError, SchemaError, ChatTransportError):
        if request is not None:
            error = "INFERENCE_TRANSFER_METADATA_UNAVAILABLE"
        reply = _failed(request, error)
    except Exception:
        reply = _failed(request, "INFERENCE_TRANSFER_METADATA_UNAVAILABLE")
    reply = parse_metadata_binding_reply(reply.model_dump(mode="json"))
    return canonical_json_bytes(reply.model_dump(mode="json")) + b"\n"


def _failed(
    request: InferenceTransferMetadataBindingRequest | None, error: InferenceTransferMetadataError
) -> InferenceTransferMetadataBindingReply:
    return InferenceTransferMetadataBindingReply(
        status="FAILED",
        actor_id=None if request is None else request.actor_id,
        request_sha256=None if request is None else request.request.request_sha256,
        result=None,
        error_code=error,
    )
