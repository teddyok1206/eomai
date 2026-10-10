"""Fixed Catalog socket metadata adapter; API never reads Catalog DB or NAS."""

from __future__ import annotations

import grp
import pwd
from pathlib import Path

from eom_catalog_contracts import CATALOG_APPLICATION_SOCKET_PATH
from eom_catalog_contracts.inference_transfer_metadata import (
    MAX_METADATA_FRAME_BYTES,
    InferenceTransferMetadataBindingReply,
    InferenceTransferMetadataBindingRequest,
    InferenceTransferMetadataResolveRequest,
    InferenceTransferMetadataResolveResult,
    parse_metadata_binding_reply,
    parse_metadata_binding_request,
    validate_metadata_binding_reply,
)
from eom_orchestrator.general_chat_socket import (
    ChatSocketEndpoint,
    ChatTransportError,
    exchange_chat_frame,
)
from jsonschema import ValidationError as SchemaError

from eom_api.services.inference_transfer_metadata import InferenceTransferMetadataReadError


class CatalogInferenceTransferMetadataClient:
    def __init__(self, endpoint: ChatSocketEndpoint | None = None) -> None:
        self.endpoint = endpoint

    def resolve(
        self, actor_id: str, request: InferenceTransferMetadataResolveRequest
    ) -> InferenceTransferMetadataResolveResult:
        try:
            binding = parse_metadata_binding_request(
                InferenceTransferMetadataBindingRequest(
                    actor_id=actor_id, request=request
                ).model_dump(mode="json")
            )
        except (ValueError, SchemaError) as exc:
            raise InferenceTransferMetadataReadError(
                "INFERENCE_TRANSFER_METADATA_REQUEST_INVALID"
            ) from exc
        try:
            endpoint = self.endpoint or ChatSocketEndpoint(
                Path(CATALOG_APPLICATION_SOCKET_PATH),
                pwd.getpwnam("eom-catalog-manager").pw_uid,
                grp.getgrnam("eom-api").gr_gid,
            )
            value = exchange_chat_frame(
                endpoint,
                binding.model_dump(mode="json"),
                request_limit=MAX_METADATA_FRAME_BYTES,
                reply_limit=MAX_METADATA_FRAME_BYTES,
                timeout=30.0,
            )
            if any(
                value.get(field)
                != InferenceTransferMetadataBindingReply.model_fields[field].default
                for field in ("schema_version", "operation")
            ):
                raise InferenceTransferMetadataReadError("INFERENCE_TRANSFER_METADATA_UNAVAILABLE")
            reply = parse_metadata_binding_reply(value)
            validate_metadata_binding_reply(binding, reply)
        except ChatTransportError as exc:
            raise InferenceTransferMetadataReadError(
                "INFERENCE_TRANSFER_METADATA_UNAVAILABLE"
            ) from exc
        except (ValueError, SchemaError, KeyError, OSError) as exc:
            raise InferenceTransferMetadataReadError(
                "INFERENCE_TRANSFER_METADATA_UNAVAILABLE"
            ) from exc
        if reply.result is None:
            raise InferenceTransferMetadataReadError(
                reply.error_code or "INFERENCE_TRANSFER_METADATA_UNAVAILABLE"
            )
        return reply.result
