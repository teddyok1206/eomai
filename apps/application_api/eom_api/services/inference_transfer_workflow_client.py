"""Fixed API-peer Catalog transport for purpose-specific canonical comparison reads."""

from __future__ import annotations

import grp
import pwd
from pathlib import Path

from eom_catalog_contracts import CATALOG_APPLICATION_SOCKET_PATH
from eom_catalog_contracts.inference_transfer_invocation import (
    InferenceTransferWorkflowReadRequest,
    InferenceTransferWorkflowReadResult,
)
from eom_catalog_contracts.inference_transfer_workflow_binding import (
    MAX_PRIVATE_TRANSFER_WORKFLOW_BYTES,
    parse_workflow_binding_reply,
    parse_workflow_binding_request,
    validate_workflow_binding_reply,
)
from eom_identifiers import content_sha256
from eom_orchestrator.general_chat_socket import (
    ChatSocketEndpoint,
    ChatTransportError,
    exchange_chat_frame,
)
from jsonschema.exceptions import ValidationError as SchemaError

from eom_api.services.inference_transfer_workflow_read import InferenceTransferWorkflowReadError


class CatalogInferenceTransferWorkflowClient:
    def __init__(self, endpoint: ChatSocketEndpoint | None = None) -> None:
        self.endpoint = endpoint

    def execute(
        self, actor_id: str, request: InferenceTransferWorkflowReadRequest
    ) -> InferenceTransferWorkflowReadResult:
        body: dict[str, object] = {
            "schema_version": "inference-transfer-workflow-binding-request/1.0",
            "operation": "INFERENCE_TRANSFER_WORKFLOW_READ",
            "actor_id": actor_id,
            "request": request.model_dump(mode="json"),
        }
        body["binding_sha256"] = content_sha256(body)
        try:
            binding = parse_workflow_binding_request(body)
        except (ValueError, SchemaError) as exc:
            raise InferenceTransferWorkflowReadError(
                "INFERENCE_TRANSFER_WORKFLOW_REQUEST_INVALID"
            ) from exc
        try:
            endpoint = self.endpoint or ChatSocketEndpoint(
                Path(CATALOG_APPLICATION_SOCKET_PATH),
                pwd.getpwnam("eom-catalog-manager").pw_uid,
                grp.getgrnam("eom-api").gr_gid,
            )
            value = exchange_chat_frame(
                endpoint,
                body,
                request_limit=MAX_PRIVATE_TRANSFER_WORKFLOW_BYTES,
                reply_limit=MAX_PRIVATE_TRANSFER_WORKFLOW_BYTES,
                timeout=120.0,
            )
            if (
                value.get("operation") != binding.operation
                or value.get("schema_version") != "inference-transfer-workflow-binding-reply/1.0"
            ):
                raise InferenceTransferWorkflowReadError("INFERENCE_TRANSFER_WORKFLOW_UNAVAILABLE")
            reply = parse_workflow_binding_reply(value)
            validate_workflow_binding_reply(binding, reply)
        except (ChatTransportError, OSError, KeyError) as exc:
            raise InferenceTransferWorkflowReadError(
                "INFERENCE_TRANSFER_WORKFLOW_UNAVAILABLE"
            ) from exc
        except (ValueError, SchemaError) as exc:
            raise InferenceTransferWorkflowReadError("INFERENCE_TRANSFER_RESULT_INVALID") from exc
        if reply.status != "SUCCESS" or reply.result is None:
            raise InferenceTransferWorkflowReadError(
                reply.error_code or "INFERENCE_TRANSFER_WORKFLOW_UNAVAILABLE"
            )
        return reply.result
