"""Closed comparison read successor on the existing fixed API-peer socket."""

from __future__ import annotations

from eom_catalog_contracts.inference_transfer_workflow_binding_v11 import (
    MAX_PRIVATE_TRANSFER_WORKFLOW_BYTES,
    InferenceTransferWorkflowBindingReplyV11,
    InferenceTransferWorkflowBindingRequestV11,
    parse_workflow_binding_reply_v11,
    parse_workflow_binding_request_v11,
    validate_workflow_binding_reply_v11,
)
from eom_identifiers import canonical_json_bytes, content_sha256
from eom_orchestrator.general_chat_socket import ChatTransportError, decode_chat_frame
from jsonschema import ValidationError as SchemaError

from eom_catalog_service.inference_transfer_service import InferenceTransferServiceError
from eom_catalog_service.inference_transfer_workflow_read import (
    CatalogInferenceTransferWorkflowReadService,
)


def _failed(code: str, request: InferenceTransferWorkflowBindingRequestV11 | None = None) -> bytes:
    body = {
        "schema_version": "inference-transfer-workflow-binding-reply/1.1",
        "operation": "INFERENCE_TRANSFER_WORKFLOW_READ",
        "actor_id": None if request is None else request.actor_id,
        "request_binding_sha256": None if request is None else request.binding_sha256,
        "status": "FAILED",
        "result": None,
        "error_code": code,
    }
    reply = parse_workflow_binding_reply_v11(body | {"reply_sha256": content_sha256(body)})
    return canonical_json_bytes(reply) + b"\n"


def dispatch_inference_transfer_workflow_frame_v11(
    service: CatalogInferenceTransferWorkflowReadService | None, raw: bytes
) -> bytes:
    """Caller must first apply existing API UID/OS-peer authorization."""

    if len(raw) > MAX_PRIVATE_TRANSFER_WORKFLOW_BYTES:
        return _failed("INFERENCE_TRANSFER_WORKFLOW_BUDGET_EXCEEDED")
    try:
        if not raw.endswith(b"\n") or b"\n" in raw[:-1]:
            raise ValueError("invalid comparison read frame")
        request = parse_workflow_binding_request_v11(decode_chat_frame(raw[:-1]))
    except (ValueError, SchemaError, ChatTransportError, RecursionError):
        return _failed("INFERENCE_TRANSFER_WORKFLOW_REQUEST_INVALID")
    if service is None:
        return _failed("INFERENCE_TRANSFER_WORKFLOW_UNAVAILABLE", request)
    try:
        result = service.read_v11(request.actor_id, request.request)
        body = {
            "schema_version": "inference-transfer-workflow-binding-reply/1.1",
            "operation": "INFERENCE_TRANSFER_WORKFLOW_READ",
            "actor_id": request.actor_id,
            "request_binding_sha256": request.binding_sha256,
            "status": "SUCCESS",
            "result": result.model_dump(mode="json"),
            "error_code": None,
        }
        reply: InferenceTransferWorkflowBindingReplyV11 = parse_workflow_binding_reply_v11(
            body | {"reply_sha256": content_sha256(body)}
        )
        validate_workflow_binding_reply_v11(request, reply)
        encoded = canonical_json_bytes(reply) + b"\n"
        if len(encoded) > MAX_PRIVATE_TRANSFER_WORKFLOW_BYTES:
            return _failed("INFERENCE_TRANSFER_WORKFLOW_BUDGET_EXCEEDED", request)
        return encoded
    except InferenceTransferServiceError as exc:
        try:
            # The binding model owns the allowlist. Unknown internal codes are
            # never copied into user-visible error text or partial results.
            return _failed(exc.code, request)
        except (ValueError, SchemaError):
            return _failed("INFERENCE_TRANSFER_WORKFLOW_UNAVAILABLE", request)
    except (ValueError, SchemaError):
        return _failed("INFERENCE_TRANSFER_RESULT_INVALID", request)
    except Exception:
        return _failed("INFERENCE_TRANSFER_WORKFLOW_UNAVAILABLE", request)
