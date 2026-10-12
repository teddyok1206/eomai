"""Fixed API-peer Catalog transport for purpose-specific canonical comparison reads."""

from __future__ import annotations

import grp
import pwd
from pathlib import Path
from typing import cast

from eom_catalog_contracts import CATALOG_APPLICATION_SOCKET_PATH
from eom_catalog_contracts.inference_transfer_invocation import (
    InferenceTransferWorkflowReadRequest,
    InferenceTransferWorkflowReadResult,
)
from eom_catalog_contracts.inference_transfer_invocation_v11 import (
    InferenceTransferWorkflowReadRequestV11,
    InferenceTransferWorkflowReadResultV11,
)
from eom_catalog_contracts.inference_transfer_snapshot_timing import (
    COMPARISON_WORKFLOW_READ_TIMEOUT_SECONDS,
)
from eom_catalog_contracts.inference_transfer_workflow_binding import (
    MAX_PRIVATE_TRANSFER_WORKFLOW_BYTES,
    InferenceTransferWorkflowBindingReply,
    parse_workflow_binding_reply,
    parse_workflow_binding_request,
    validate_workflow_binding_reply,
)
from eom_catalog_contracts.inference_transfer_workflow_binding_v11 import (
    InferenceTransferWorkflowBindingReplyV11,
    parse_workflow_binding_reply_v11,
    parse_workflow_binding_request_v11,
    validate_workflow_binding_reply_v11,
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
        if not isinstance(request, InferenceTransferWorkflowReadRequest):
            raise InferenceTransferWorkflowReadError("INFERENCE_TRANSFER_WORKFLOW_REQUEST_INVALID")
        return cast(InferenceTransferWorkflowReadResult, self._execute(actor_id, request))

    def execute_v11(
        self, actor_id: str, request: InferenceTransferWorkflowReadRequestV11
    ) -> InferenceTransferWorkflowReadResultV11:
        if not isinstance(request, InferenceTransferWorkflowReadRequestV11):
            raise InferenceTransferWorkflowReadError("INFERENCE_TRANSFER_WORKFLOW_REQUEST_INVALID")
        return cast(InferenceTransferWorkflowReadResultV11, self._execute(actor_id, request))

    def _execute(
        self,
        actor_id: str,
        request: InferenceTransferWorkflowReadRequest | InferenceTransferWorkflowReadRequestV11,
    ) -> InferenceTransferWorkflowReadResult | InferenceTransferWorkflowReadResultV11:
        version = "1.1" if isinstance(request, InferenceTransferWorkflowReadRequestV11) else "1.0"
        body: dict[str, object] = {
            "schema_version": f"inference-transfer-workflow-binding-request/{version}",
            "operation": "INFERENCE_TRANSFER_WORKFLOW_READ",
            "actor_id": actor_id,
            "request": request.model_dump(mode="json"),
        }
        body["binding_sha256"] = content_sha256(body)
        try:
            binding = (
                parse_workflow_binding_request_v11(body)
                if isinstance(request, InferenceTransferWorkflowReadRequestV11)
                else parse_workflow_binding_request(body)
            )
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
                timeout=COMPARISON_WORKFLOW_READ_TIMEOUT_SECONDS,
            )
            if (
                value.get("operation") != binding.operation
                or value.get("schema_version")
                != f"inference-transfer-workflow-binding-reply/{version}"
            ):
                raise InferenceTransferWorkflowReadError("INFERENCE_TRANSFER_WORKFLOW_UNAVAILABLE")
            reply: InferenceTransferWorkflowBindingReply | InferenceTransferWorkflowBindingReplyV11
            if isinstance(request, InferenceTransferWorkflowReadRequestV11):
                successor_binding = parse_workflow_binding_request_v11(body)
                reply = parse_workflow_binding_reply_v11(value)
                validate_workflow_binding_reply_v11(successor_binding, reply)
            else:
                predecessor_binding = parse_workflow_binding_request(body)
                reply = parse_workflow_binding_reply(value)
                validate_workflow_binding_reply(predecessor_binding, reply)
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
