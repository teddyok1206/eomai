"""API leaf client to the existing fixed Catalog owner socket, no local DB/NAS reads."""

from __future__ import annotations

import grp
import pwd
from pathlib import Path

from eom_catalog_contracts import CATALOG_APPLICATION_SOCKET_PATH
from eom_catalog_contracts.inference_transfer_snapshot import (
    InferenceTransferSnapshotRequest,
    InferenceTransferSnapshotResult,
)
from eom_catalog_contracts.inference_transfer_snapshot_binding import (
    MAX_PRIVATE_SNAPSHOT_FRAME_BYTES,
    InferenceTransferSnapshotBindingReply,
    InferenceTransferSnapshotBindingRequest,
    parse_binding_reply,
    parse_binding_request,
    validate_binding_reply,
)
from eom_catalog_contracts.inference_transfer_snapshot_timing import (
    DEFAULT_SNAPSHOT_TIMEOUT_SECONDS,
    snapshot_phase_deadlines,
)
from eom_orchestrator.general_chat_socket import (
    ChatSocketEndpoint,
    ChatTransportError,
    exchange_chat_frame,
)
from jsonschema import ValidationError as SchemaError

from eom_api.services.inference_transfer_snapshot_port import InferenceTransferSnapshotReadError

# Preserve the existing adapter import; per-phase rules have one shared owner.
SNAPSHOT_RESPONSE_TIMEOUT_SECONDS = DEFAULT_SNAPSHOT_TIMEOUT_SECONDS


class InferenceTransferSnapshotClientError(InferenceTransferSnapshotReadError):
    """Concrete adapter spelling preserved; application code catches the port error."""


class CatalogInferenceTransferSnapshotClient:
    """Actual actor is injected by API application code, never public input."""

    def __init__(self, endpoint: ChatSocketEndpoint | None = None) -> None:
        self.endpoint = endpoint

    def execute(
        self,
        actor_id: str,
        request: InferenceTransferSnapshotRequest,
    ) -> InferenceTransferSnapshotResult:
        try:
            binding = InferenceTransferSnapshotBindingRequest(actor_id=actor_id, request=request)
            document = binding.model_dump(mode="json")
            binding = parse_binding_request(document)
        except (ValueError, SchemaError) as exc:
            raise InferenceTransferSnapshotClientError(
                "INFERENCE_TRANSFER_SNAPSHOT_REQUEST_INVALID"
            ) from exc
        try:
            endpoint = self.endpoint or ChatSocketEndpoint(
                Path(CATALOG_APPLICATION_SOCKET_PATH),
                pwd.getpwnam("eom-catalog-manager").pw_uid,
                grp.getgrnam("eom-api").gr_gid,
            )
            value = exchange_chat_frame(
                endpoint,
                document,
                request_limit=MAX_PRIVATE_SNAPSHOT_FRAME_BYTES,
                reply_limit=MAX_PRIVATE_SNAPSHOT_FRAME_BYTES,
                timeout=snapshot_phase_deadlines(binding.request.phase).catalog_response_seconds,
            )
            if any(
                value.get(field)
                != InferenceTransferSnapshotBindingReply.model_fields[field].default
                for field in ("schema_version", "operation")
            ):
                # A predecessor/unsupported owner response is unavailable, not
                # permission to reinterpret its content as the new protocol.
                raise InferenceTransferSnapshotClientError(
                    "INFERENCE_TRANSFER_SNAPSHOT_UNAVAILABLE"
                )
            reply = parse_binding_reply(value)
            validate_binding_reply(binding, reply)
        except ChatTransportError as exc:
            code = (
                "INFERENCE_TRANSFER_SNAPSHOT_UNAVAILABLE"
                if exc.kind == "UNAVAILABLE"
                else "INFERENCE_TRANSFER_SNAPSHOT_REQUEST_INVALID"
            )
            raise InferenceTransferSnapshotClientError(code) from exc
        except (ValueError, SchemaError) as exc:
            raise InferenceTransferSnapshotClientError(
                "INFERENCE_TRANSFER_SNAPSHOT_REQUEST_INVALID"
            ) from exc
        except (KeyError, OSError) as exc:
            raise InferenceTransferSnapshotClientError(
                "INFERENCE_TRANSFER_SNAPSHOT_UNAVAILABLE"
            ) from exc
        if reply.status != "SUCCESS" or reply.result is None:
            raise InferenceTransferSnapshotClientError(
                reply.error_code or "INFERENCE_TRANSFER_SNAPSHOT_UNAVAILABLE"
            )
        return reply.result
