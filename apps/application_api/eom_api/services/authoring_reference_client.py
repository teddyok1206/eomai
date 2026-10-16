"""API presentation adapter to the same existing Catalog owner/socket, not a searcher."""

import grp
import pwd
from pathlib import Path

from eom_catalog_contracts import CATALOG_APPLICATION_SOCKET_PATH, EvidenceBundlePublicationResultV5
from eom_catalog_contracts.authoring_reference import (
    MAX_AUTHORING_REFERENCE_REPLY_BYTES,
    MAX_AUTHORING_REFERENCE_REQUEST_BYTES,
    AuthoringReferenceErrorCode,
    AuthoringReferenceReply,
    AuthoringReferenceRequest,
    AuthoringReferenceSelection,
    validate_authoring_reference_reply,
)
from eom_orchestrator.general_chat_socket import (
    ChatSocketEndpoint,
    ChatTransportError,
    exchange_chat_frame,
)
from jsonschema.exceptions import ValidationError as SchemaError


class AuthoringReferenceClientError(ValueError):
    def __init__(self, code: AuthoringReferenceErrorCode) -> None:
        self.code = code
        super().__init__(code)


class CatalogAuthoringReferenceClient:
    """The application supplies its actual operator; no public authority fields."""

    def __init__(self, endpoint: ChatSocketEndpoint | None = None) -> None:
        self.endpoint = endpoint

    def select(
        self, actor_id: str, evidence: EvidenceBundlePublicationResultV5
    ) -> AuthoringReferenceSelection | None:
        try:
            request = AuthoringReferenceRequest(
                schema_version="system-rag-authoring-reference-request/1.0",
                operation="SELECT_ITEM_AUTHORING_REFERENCE",
                actor_id=actor_id,
                evidence=evidence,
            )
            endpoint = self.endpoint or ChatSocketEndpoint(
                Path(CATALOG_APPLICATION_SOCKET_PATH),
                pwd.getpwnam("eom-catalog-manager").pw_uid,
                grp.getgrnam("eom-api").gr_gid,
            )
            value = exchange_chat_frame(
                endpoint,
                request.model_dump(mode="json"),
                request_limit=MAX_AUTHORING_REFERENCE_REQUEST_BYTES,
                reply_limit=MAX_AUTHORING_REFERENCE_REPLY_BYTES,
                timeout=30.0,
            )
            reply = AuthoringReferenceReply.model_validate(value)
            validate_authoring_reference_reply(request, reply)
        except (ValueError, SchemaError, ChatTransportError, KeyError, OSError):
            raise AuthoringReferenceClientError("AUTHORING_REFERENCE_UNAVAILABLE") from None
        if reply.status == "UNAVAILABLE":
            return None
        if reply.selection is None:
            raise AuthoringReferenceClientError(
                reply.error_code or "AUTHORING_REFERENCE_UNAVAILABLE"
            )
        return reply.selection
