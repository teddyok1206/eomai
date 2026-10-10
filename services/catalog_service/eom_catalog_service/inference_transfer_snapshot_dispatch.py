"""Small successor dispatch on the existing fixed-peer Catalog socket.

The caller must enforce the API-only OS peer check first. Parsing a binding
request, actor string or successful reply does not independently grant access.
"""

from __future__ import annotations

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
from jsonschema import ValidationError as SchemaError

from eom_catalog_service.inference_transfer_service import InferenceTransferServiceError
from eom_catalog_service.inference_transfer_snapshot_service import (
    InferenceTransferSnapshotApplicationService,
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
    except (ValueError, SchemaError, ChatTransportError, RecursionError):
        return _failed("INFERENCE_TRANSFER_SNAPSHOT_REQUEST_INVALID")
    if service is None:
        return _failed("INFERENCE_TRANSFER_SNAPSHOT_UNAVAILABLE")
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
        reply = InferenceTransferSnapshotBindingReply(
            status="SUCCESS", result=result, error_code=None
        )
        parse_binding_reply(reply.model_dump(mode="json"))
        validate_binding_reply(request, reply)
        encoded = canonical_json_bytes(reply) + b"\n"
        if len(encoded) > MAX_PRIVATE_SNAPSHOT_FRAME_BYTES:
            return _failed("INFERENCE_TRANSFER_SNAPSHOT_BUDGET_EXCEEDED")
        return encoded
    except InferenceTransferServiceError as exc:
        try:
            return _failed(exc.code)
        except (ValueError, SchemaError):
            # The typed binding contract owns the one authoritative safe
            # allowlist; never duplicate it in an adapter or expose new codes.
            return _failed("INFERENCE_TRANSFER_SNAPSHOT_UNAVAILABLE")
    except (ValueError, SchemaError):
        return _failed("INFERENCE_TRANSFER_SNAPSHOT_REQUEST_INVALID")
    except Exception:
        # Never expose source data, exception text or credentials in transport.
        return _failed("INFERENCE_TRANSFER_SNAPSHOT_UNAVAILABLE")
