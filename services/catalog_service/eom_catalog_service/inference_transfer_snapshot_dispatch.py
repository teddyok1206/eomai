"""Small successor dispatch on the existing fixed-peer Catalog socket.

The caller must enforce the API-only OS peer check first. Parsing a binding
request, actor string or successful reply does not independently grant access.
"""

from __future__ import annotations

import logging
from contextlib import suppress
from enum import StrEnum

from eom_catalog_contracts.inference_transfer_snapshot import (
    InferenceTransferSnapshotAuthorizeRequest,
    InferenceTransferSnapshotPrepareRequest,
    InferenceTransferSnapshotReadRequest,
    InferenceTransferSnapshotResult,
)
from eom_catalog_contracts.inference_transfer_snapshot_binding import (
    MAX_PRIVATE_SNAPSHOT_FRAME_BYTES,
    InferenceTransferSnapshotBindingReply,
    parse_binding_reply,
    parse_binding_request,
    validate_binding_reply,
)
from eom_identifiers import canonical_json_bytes
from eom_orchestrator.general_chat_socket import ChatTransportError, decode_chat_frame
from eom_orchestrator.logging import log_event
from jsonschema import ValidationError as SchemaError
from pydantic import ValidationError as ModelError

from eom_catalog_service.inference_transfer_service import InferenceTransferServiceError
from eom_catalog_service.inference_transfer_snapshot_service import (
    InferenceTransferSnapshotApplicationService,
)


class _ValidationStage(StrEnum):
    INPUT_PARSE = "INPUT_PARSE"
    OWNER_SERVICE = "OWNER_SERVICE"
    REPLY_SCHEMA = "REPLY_SCHEMA"
    REPLY_CONTEXT = "REPLY_CONTEXT"
    ENCODE = "ENCODE"


_LOGGER = logging.getLogger(__name__)


def _record_validation_failure(
    stage: _ValidationStage, phase: str, error: Exception, *, code: str
) -> None:
    """Record closed diagnostic categories, never exception text or input values."""
    kind = (
        "JSON_SCHEMA"
        if isinstance(error, SchemaError)
        else "FROZEN_MODEL"
        if isinstance(error, ModelError)
        else "OWNER_SOURCE"
        if isinstance(error, InferenceTransferServiceError)
        else "VALUE_VALIDATION"
        if isinstance(error, ValueError)
        else "UNEXPECTED"
    )
    message = canonical_json_bytes(
        {
            "event": "SNAPSHOT_VALIDATION_FAILED",
            "phase": phase if phase in {"PREPARE", "READ", "AUTHORIZE"} else "UNKNOWN",
            "validation_stage": stage.value,
            "error_kind": kind,
        }
    ).decode("utf-8")
    # Diagnostics are optional; handler failure must not replace the safe reply.
    with suppress(Exception):
        log_event(
            _LOGGER,
            logging.WARNING,
            message,
            job_id=None,
            worker_slot=None,
            component="catalog_snapshot",
            event="SNAPSHOT_VALIDATION_FAILED",
            error_code=code,
        )


def _failed(code: str) -> bytes:
    reply = InferenceTransferSnapshotBindingReply.model_validate(
        {
            "status": "FAILED",
            "result": None,
            "error_code": code,
        }
    )
    parse_binding_reply(reply.model_dump(mode="json"))
    return canonical_json_bytes(reply) + b"\n"


def dispatch_snapshot_frame(
    service: InferenceTransferSnapshotApplicationService | None,
    raw: bytes,
) -> bytes:
    """Validate and dispatch one bounded line after the existing peer gate."""
    if len(raw) > MAX_PRIVATE_SNAPSHOT_FRAME_BYTES:
        return _failed("INFERENCE_TRANSFER_SNAPSHOT_BUDGET_EXCEEDED")
    try:
        if not raw.endswith(b"\n") or b"\n" in raw[:-1]:
            raise ValueError("invalid snapshot frame")
        request = parse_binding_request(decode_chat_frame(raw[:-1]))
    except (ValueError, SchemaError, ChatTransportError, RecursionError) as exc:
        _record_validation_failure(
            _ValidationStage.INPUT_PARSE,
            "UNKNOWN",
            exc,
            code="INFERENCE_TRANSFER_SNAPSHOT_REQUEST_INVALID",
        )
        return _failed("INFERENCE_TRANSFER_SNAPSHOT_REQUEST_INVALID")
    if service is None:
        return _failed("INFERENCE_TRANSFER_SNAPSHOT_UNAVAILABLE")
    stage = _ValidationStage.OWNER_SERVICE
    phase_name = request.request.phase
    try:
        phase = request.request
        result: InferenceTransferSnapshotResult
        if isinstance(phase, InferenceTransferSnapshotPrepareRequest):
            result = service.prepare(request.actor_id, phase)
        elif isinstance(phase, InferenceTransferSnapshotReadRequest):
            result = service.read(request.actor_id, phase)
        elif isinstance(phase, InferenceTransferSnapshotAuthorizeRequest):
            result = service.authorize(request.actor_id, phase)
        else:
            raise ValueError("unsupported phase")
        stage = _ValidationStage.REPLY_SCHEMA
        reply = InferenceTransferSnapshotBindingReply(
            status="SUCCESS", result=result, error_code=None
        )
        parse_binding_reply(reply.model_dump(mode="json"))
        stage = _ValidationStage.REPLY_CONTEXT
        validate_binding_reply(request, reply)
        stage = _ValidationStage.ENCODE
        encoded = canonical_json_bytes(reply) + b"\n"
        if len(encoded) > MAX_PRIVATE_SNAPSHOT_FRAME_BYTES:
            return _failed("INFERENCE_TRANSFER_SNAPSHOT_BUDGET_EXCEEDED")
        return encoded
    except InferenceTransferServiceError as exc:
        try:
            failed = _failed(exc.code)
            code = exc.code
        except (ValueError, SchemaError):
            # The typed binding contract owns the one authoritative safe
            # allowlist; never duplicate it in an adapter or expose new codes.
            code = "INFERENCE_TRANSFER_SNAPSHOT_UNAVAILABLE"
            failed = _failed(code)
        _record_validation_failure(stage, phase_name, exc, code=code)
        return failed
    except (ValueError, SchemaError) as exc:
        _record_validation_failure(
            stage, phase_name, exc, code="INFERENCE_TRANSFER_SNAPSHOT_REQUEST_INVALID"
        )
        return _failed("INFERENCE_TRANSFER_SNAPSHOT_REQUEST_INVALID")
    except Exception as exc:
        # Never expose source data, exception text or credentials in transport.
        _record_validation_failure(
            stage, phase_name, exc, code="INFERENCE_TRANSFER_SNAPSHOT_UNAVAILABLE"
        )
        return _failed("INFERENCE_TRANSFER_SNAPSHOT_UNAVAILABLE")
