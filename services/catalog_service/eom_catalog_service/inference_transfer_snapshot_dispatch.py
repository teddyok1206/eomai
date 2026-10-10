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

# Error titles/locations can be attacker-controlled. Only closed categories may
# cross the logging boundary; neither exception prose nor source values do.
_MODEL_CATEGORIES = {
    "InferenceTransferSnapshotReadResult": "READ_RESULT",
    "InferenceTransferSnapshotRecord": "SOURCE_RECORD",
    "CreateEvidenceBundleCommand": "BASELINE_COMMAND",
    "SuppliedGraphBaseline": "BASELINE_RESULT",
    "EducationRetrievalRequestV2": "GRAPH_REQUEST",
    "InferenceTransferSnapshotPrepareResult": "PREPARE_RESULT",
    "InferenceTransferSnapshotHeader": "PREPARE_HEADER",
    "InferenceTransferSnapshotReadRequest": "READ_REQUEST",
}
_FIELD_CATEGORIES = {
    "header": "HEADER",
    "index": "INDEX",
    "index_entry": "INDEX_ENTRY",
    "source": "SOURCE",
    "staged_entry": "STAGED_ENTRY",
    "records": "RECORDS",
    "baselines": "BASELINES",
    "limitations": "LIMITATIONS",
    "query": "QUERY",
    "ordered_candidates": "CANDIDATES",
    "topic_keys": "TOPIC_KEYS",
    "evidence_budget": "EVIDENCE_BUDGET",
    "requester_permission_keys": "PERMISSIONS",
    "requester_role": "ROLE",
    "requested_by": "ACTOR",
    "source_classes": "SOURCE_CLASSES",
    "header_sha256": "HEADER_HASH",
    "read_sha256": "READ_HASH",
    "result_sha256": "RESULT_HASH",
    "submission_sha256": "COMMAND_HASH",
}
_VALIDATION_CATEGORIES = {
    "value_error": "VALUE_INVARIANT",
    "too_long": "SIZE_OR_COUNT",
    "too_short": "SIZE_OR_COUNT",
    "string_too_long": "TEXT_SIZE",
    "string_too_short": "TEXT_SIZE",
    "extra_forbidden": "CLOSED_FIELDS",
    "literal_error": "VERSION_OR_ENUM",
    "enum": "VERSION_OR_ENUM",
    "string_pattern_mismatch": "FORMAT",
    "int_parsing": "TYPE",
    "int_type": "TYPE",
    "string_type": "TYPE",
    "tuple_type": "TYPE",
    "model_type": "TYPE",
    "missing": "MISSING",
}


def _model_failure_categories(error: ModelError) -> dict[str, object]:
    fields: set[str] = set()
    categories: set[str] = set()
    for detail in error.errors(include_input=False, include_context=False, include_url=False)[:16]:
        location = detail["loc"]
        field = location[0] if location else None
        fields.add(
            "ROOT"
            if field is None
            else _FIELD_CATEGORIES.get(field, "OTHER")
            if isinstance(field, str)
            else "OTHER"
        )
        categories.add(_VALIDATION_CATEGORIES.get(detail["type"], "OTHER"))
    return {
        "model_category": _MODEL_CATEGORIES.get(error.title, "OTHER"),
        "field_categories": sorted(fields),
        "validation_categories": sorted(categories),
    }


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
    # Diagnostics are optional; handler failure must not replace the safe reply.
    with suppress(Exception):
        diagnostic: dict[str, object] = {
            "event": "SNAPSHOT_VALIDATION_FAILED",
            "phase": phase if phase in {"PREPARE", "READ", "AUTHORIZE"} else "UNKNOWN",
            "validation_stage": stage.value,
            "error_kind": kind,
        }
        if isinstance(error, ModelError):
            diagnostic.update(_model_failure_categories(error))
        log_event(
            _LOGGER,
            logging.WARNING,
            canonical_json_bytes(diagnostic).decode("utf-8"),
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
