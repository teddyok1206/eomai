"""Runner-only closed read frames; no native admission, launch or untrusted actor."""

from __future__ import annotations

from eom_catalog_contracts.public_workflow_similarity_read import (
    PublicWorkflowSimilarityReadReply,
    PublicWorkflowSimilarityReadRequest,
    validate_public_workflow_similarity_reply,
)
from eom_catalog_contracts.workflow_similarity_read import (
    MAX_WORKFLOW_SIMILARITY_REPLY_BYTES,
    MAX_WORKFLOW_SIMILARITY_REQUEST_BYTES,
    WorkflowSimilarityReadErrorCode,
    WorkflowSimilarityReadReply,
    WorkflowSimilarityReadRequest,
    validate_workflow_similarity_read_reply,
)
from eom_identifiers import canonical_json_bytes, content_sha256
from eom_orchestrator.general_chat_socket import ChatTransportError, decode_chat_frame
from jsonschema.exceptions import ValidationError as SchemaError

from eom_catalog_service.workflow_similarity_read_service import (
    CatalogWorkflowSimilarityReadService,
    WorkflowSimilarityReadServiceError,
)


def _failed(
    request: WorkflowSimilarityReadRequest | PublicWorkflowSimilarityReadRequest | None,
    code: WorkflowSimilarityReadErrorCode,
    *,
    public: bool = False,
) -> bytes:
    reply_type = PublicWorkflowSimilarityReadReply if public else WorkflowSimilarityReadReply
    reply = reply_type.model_validate(
        {
            "schema_version": (
                "system-rag-workflow-similarity-read-reply/2.0"
                if public
                else "system-rag-workflow-similarity-read-reply/1.0"
            ),
            "operation": "READ_WORKFLOW_SIMILARITY_MATERIALS",
            "status": "FAILED",
            "request_sha256": None
            if request is None
            else content_sha256(request.model_dump(mode="json")),
            "operator_id": None,
            "context": None,
            "materials": None,
            "error_code": code,
        }
    )
    return canonical_json_bytes(reply.model_dump(mode="json")) + b"\n"


def dispatch_workflow_similarity_read_frame(
    service: CatalogWorkflowSimilarityReadService | None, raw: bytes
) -> bytes:
    if len(raw) > MAX_WORKFLOW_SIMILARITY_REQUEST_BYTES:
        return _failed(None, "WORKFLOW_SIMILARITY_BUDGET_EXCEEDED")
    public = False
    try:
        if not raw.endswith(b"\n") or b"\n" in raw[:-1]:
            raise ValueError("invalid frame")
        document = decode_chat_frame(raw[:-1])
        public = document.get("schema_version") == "system-rag-workflow-similarity-read-request/2.0"
        request = (
            PublicWorkflowSimilarityReadRequest.model_validate(document)
            if public
            else WorkflowSimilarityReadRequest.model_validate(document)
        )
    except (ValueError, SchemaError, ChatTransportError, RecursionError):
        return _failed(None, "WORKFLOW_SIMILARITY_REQUEST_INVALID", public=public)
    if service is None:
        return _failed(request, "WORKFLOW_SIMILARITY_UNAVAILABLE", public=public)
    try:
        reply: WorkflowSimilarityReadReply | PublicWorkflowSimilarityReadReply
        if isinstance(request, PublicWorkflowSimilarityReadRequest):
            reply = PublicWorkflowSimilarityReadReply.model_validate(service.read_public(request))
            validate_public_workflow_similarity_reply(
                request, reply, expected_operator_id=reply.operator_id or ""
            )
        else:
            reply = WorkflowSimilarityReadReply.model_validate(service.read(request))
            validate_workflow_similarity_read_reply(
                request, reply, expected_operator_id=reply.operator_id or ""
            )
        result = canonical_json_bytes(reply.model_dump(mode="json")) + b"\n"
        if len(result) > MAX_WORKFLOW_SIMILARITY_REPLY_BYTES:
            return _failed(request, "WORKFLOW_SIMILARITY_BUDGET_EXCEEDED", public=public)
        return result
    except WorkflowSimilarityReadServiceError as error:
        return _failed(request, error.code, public=public)
    except Exception:
        return _failed(request, "WORKFLOW_SIMILARITY_UNAVAILABLE", public=public)
