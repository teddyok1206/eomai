"""Bounded C5 metadata read frames after the existing API-only peer gate."""

from __future__ import annotations

from eom_catalog_contracts.exam_similarity_read import (
    MAX_EXAM_READ_FRAME_BYTES,
    ExamObservationReadErrorCode,
    ExamObservationReadReply,
    ExamObservationReadRequest,
    validate_exam_observation_read_reply,
)
from eom_identifiers import canonical_json_bytes, content_sha256
from eom_orchestrator.general_chat_socket import ChatTransportError, decode_chat_frame
from jsonschema.exceptions import ValidationError as SchemaError

from eom_catalog_service.exam_similarity_read_service import (
    CatalogExamSimilarityReadService,
    ExamObservationReadError,
)


def _failed(
    request: ExamObservationReadRequest | None, code: ExamObservationReadErrorCode
) -> ExamObservationReadReply:
    return ExamObservationReadReply(
        schema_version="system-rag-exam-observation-read-reply/1.0",
        operation="READ_EXAM_SIMILARITY_OBSERVATION",
        status="FAILED",
        actor_id=None if request is None else request.actor_id,
        request_sha256=None if request is None else content_sha256(request.model_dump(mode="json")),
        result=None,
        error_code=code,
    )


def dispatch_exam_similarity_read_frame(
    service: CatalogExamSimilarityReadService | None, raw: bytes
) -> bytes:
    request = None
    if len(raw) > MAX_EXAM_READ_FRAME_BYTES:
        return canonical_json_bytes(_failed(None, "EXAM_OBSERVATION_BUDGET_EXCEEDED")) + b"\n"
    try:
        if not raw.endswith(b"\n") or b"\n" in raw[:-1]:
            raise ValueError("invalid read frame")
        request = ExamObservationReadRequest.model_validate(decode_chat_frame(raw[:-1]))
    except (ValueError, SchemaError, ChatTransportError, RecursionError):
        return canonical_json_bytes(_failed(None, "EXAM_OBSERVATION_REQUEST_INVALID")) + b"\n"
    if service is None:
        return canonical_json_bytes(_failed(request, "EXAM_OBSERVATION_UNAVAILABLE")) + b"\n"
    try:
        reply = ExamObservationReadReply(
            schema_version="system-rag-exam-observation-read-reply/1.0",
            operation="READ_EXAM_SIMILARITY_OBSERVATION",
            status="SUCCESS",
            actor_id=request.actor_id,
            request_sha256=content_sha256(request.model_dump(mode="json")),
            result=service.read(request),
            error_code=None,
        )
        validate_exam_observation_read_reply(request, reply)
        return canonical_json_bytes(reply) + b"\n"
    except ExamObservationReadError as error:
        try:
            reply = _failed(request, error.code)
        except (ValueError, SchemaError):
            reply = _failed(request, "EXAM_OBSERVATION_UNAVAILABLE")
    except Exception:
        reply = _failed(request, "EXAM_OBSERVATION_UNAVAILABLE")
    return canonical_json_bytes(reply) + b"\n"
