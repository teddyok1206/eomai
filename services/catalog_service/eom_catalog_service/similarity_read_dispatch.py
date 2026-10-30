"""Closed metadata-only read RPC after the existing API-only Unix peer gate."""

from __future__ import annotations

from eom_catalog_contracts.similarity_read import (
    MAX_SIMILARITY_READ_FRAME_BYTES,
    SimilarityContextReadReply,
    SimilarityContextReadRequest,
    SimilarityReadErrorCode,
    validate_similarity_read_reply,
)
from eom_catalog_contracts.similarity_read_v2 import (
    SimilarityContextReadReplyV2,
    SimilarityContextReadRequestV2,
    validate_similarity_read_reply_v2,
)
from eom_catalog_contracts.similarity_read_v3 import (
    SimilarityContextReadReplyV3,
    SimilarityContextReadRequestV3,
    validate_similarity_read_reply_v3,
)
from eom_identifiers import canonical_json_bytes, content_sha256
from eom_orchestrator.general_chat_socket import ChatTransportError, decode_chat_frame
from jsonschema.exceptions import ValidationError as SchemaError

from eom_catalog_service.similarity_context_ports import SimilarityContextReadError
from eom_catalog_service.similarity_read_service import CatalogSimilarityContextReadService

type ReadRequest = (
    SimilarityContextReadRequest | SimilarityContextReadRequestV2 | SimilarityContextReadRequestV3
)
type ReadReply = (
    SimilarityContextReadReply | SimilarityContextReadReplyV2 | SimilarityContextReadReplyV3
)


def _reply_family(request: ReadRequest | None) -> tuple[str, type[ReadReply]]:
    if isinstance(request, SimilarityContextReadRequestV3):
        return "3.0", SimilarityContextReadReplyV3
    if isinstance(request, SimilarityContextReadRequestV2):
        return "2.0", SimilarityContextReadReplyV2
    return "1.0", SimilarityContextReadReply


def _failed(
    request: ReadRequest | None,
    code: SimilarityReadErrorCode,
) -> ReadReply:
    family, reply_type = _reply_family(request)
    return reply_type.model_validate(
        dict(
            schema_version=f"system-rag-similarity-read-reply/{family}",
            operation="READ_SIMILARITY_CONTEXT",
            status="FAILED",
            actor_id=None if request is None else request.actor_id,
            request_sha256=None
            if request is None
            else content_sha256(request.model_dump(mode="json")),
            result=None,
            error_code=code,
        )
    )


def dispatch_similarity_read_frame(
    service: CatalogSimilarityContextReadService | None, raw: bytes
) -> bytes:
    request: ReadRequest | None = None
    if len(raw) > MAX_SIMILARITY_READ_FRAME_BYTES:
        return canonical_json_bytes(_failed(None, "SIMILARITY_CONTEXT_BUDGET_EXCEEDED")) + b"\n"
    try:
        if not raw.endswith(b"\n") or b"\n" in raw[:-1]:
            raise ValueError("invalid similarity read frame")
        value = decode_chat_frame(raw[:-1])
        version = value.get("schema_version")
        if not isinstance(version, str):
            raise ValueError("invalid similarity read family")
        request_types: dict[str, type[ReadRequest]] = {
            "system-rag-similarity-read-request/1.0": SimilarityContextReadRequest,
            "system-rag-similarity-read-request/2.0": SimilarityContextReadRequestV2,
            "system-rag-similarity-read-request/3.0": SimilarityContextReadRequestV3,
        }
        request_type = request_types.get(version, SimilarityContextReadRequest)
        request = request_type.model_validate(value)
    except (ValueError, SchemaError, ChatTransportError, RecursionError):
        return canonical_json_bytes(_failed(None, "SIMILARITY_CONTEXT_REQUEST_INVALID")) + b"\n"
    if service is None:
        return canonical_json_bytes(_failed(request, "SIMILARITY_CONTEXT_UNAVAILABLE")) + b"\n"
    try:
        result = service.read(request)
        family, reply_type = _reply_family(request)
        reply = reply_type.model_validate(
            dict(
                schema_version=f"system-rag-similarity-read-reply/{family}",
                operation="READ_SIMILARITY_CONTEXT",
                status="SUCCESS",
                actor_id=request.actor_id,
                request_sha256=content_sha256(request.model_dump(mode="json")),
                result=result,
                error_code=None,
            )
        )
        if isinstance(request, SimilarityContextReadRequestV3) and isinstance(
            reply, SimilarityContextReadReplyV3
        ):
            validate_similarity_read_reply_v3(request, reply)
        elif isinstance(request, SimilarityContextReadRequestV2) and isinstance(
            reply, SimilarityContextReadReplyV2
        ):
            validate_similarity_read_reply_v2(request, reply)
        elif isinstance(request, SimilarityContextReadRequest) and isinstance(
            reply, SimilarityContextReadReply
        ):
            validate_similarity_read_reply(request, reply)
        else:
            raise ValueError("similarity read request/reply families differ")
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
