"""Closed metadata-only read RPC after the existing API-only Unix peer gate."""

from __future__ import annotations

from eom_catalog_contracts.similarity_read import (
    MAX_SIMILARITY_READ_FRAME_BYTES,
    SimilarityContextReadReply,
    SimilarityContextReadRequest,
    SimilarityReadErrorCode,
    validate_similarity_read_reply,
)
from eom_identifiers import canonical_json_bytes, content_sha256
from eom_orchestrator.general_chat_socket import ChatTransportError, decode_chat_frame
from jsonschema.exceptions import ValidationError as SchemaError

from eom_catalog_service.similarity_context_ports import SimilarityContextReadError
from eom_catalog_service.similarity_read_service import CatalogSimilarityContextReadService


def _failed(
    request: SimilarityContextReadRequest | None, code: SimilarityReadErrorCode
) -> SimilarityContextReadReply:
    return SimilarityContextReadReply(
        schema_version="system-rag-similarity-read-reply/1.0",
        operation="READ_SIMILARITY_CONTEXT",
        status="FAILED",
        actor_id=None if request is None else request.actor_id,
        request_sha256=None if request is None else content_sha256(request.model_dump(mode="json")),
        result=None,
        error_code=code,
    )


def dispatch_similarity_read_frame(
    service: CatalogSimilarityContextReadService | None, raw: bytes
) -> bytes:
    request: SimilarityContextReadRequest | None = None
    if len(raw) > MAX_SIMILARITY_READ_FRAME_BYTES:
        return canonical_json_bytes(_failed(None, "SIMILARITY_CONTEXT_BUDGET_EXCEEDED")) + b"\n"
    try:
        if not raw.endswith(b"\n") or b"\n" in raw[:-1]:
            raise ValueError("invalid similarity read frame")
        request = SimilarityContextReadRequest.model_validate(decode_chat_frame(raw[:-1]))
    except (ValueError, SchemaError, ChatTransportError, RecursionError):
        return canonical_json_bytes(_failed(None, "SIMILARITY_CONTEXT_REQUEST_INVALID")) + b"\n"
    if service is None:
        return canonical_json_bytes(_failed(request, "SIMILARITY_CONTEXT_UNAVAILABLE")) + b"\n"
    try:
        result = service.read(request)
        reply = SimilarityContextReadReply(
            schema_version="system-rag-similarity-read-reply/1.0",
            operation="READ_SIMILARITY_CONTEXT",
            status="SUCCESS",
            actor_id=request.actor_id,
            request_sha256=content_sha256(request.model_dump(mode="json")),
            result=result,
            error_code=None,
        )
        validate_similarity_read_reply(request, reply)
        return canonical_json_bytes(reply) + b"\n"
    except SimilarityContextReadError as error:
        # The typed contract rejects unknown owner codes; exception prose and
        # partially composed candidates never cross this boundary.
        try:
            reply = _failed(request, error.code)
        except (ValueError, SchemaError):
            reply = _failed(request, "SIMILARITY_CONTEXT_UNAVAILABLE")
    except Exception:
        reply = _failed(request, "SIMILARITY_CONTEXT_UNAVAILABLE")
    return canonical_json_bytes(reply) + b"\n"
