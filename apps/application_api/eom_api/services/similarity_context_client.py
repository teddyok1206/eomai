"""Fixed Catalog read adapter; no DB, NAS, model or execution authority in the API."""

from __future__ import annotations

import grp
import pwd
from pathlib import Path

from eom_catalog_contracts import CATALOG_APPLICATION_SOCKET_PATH
from eom_catalog_contracts.similarity_context import SimilarityContext
from eom_catalog_contracts.similarity_context_v2 import (
    SimilarityContextV2,
    SupportedSimilarityContext,
)
from eom_catalog_contracts.similarity_read import (
    MAX_SIMILARITY_READ_FRAME_BYTES,
    CompletedSimilarityQuerySelection,
    SimilarityContextReadReply,
    SimilarityContextReadRequest,
    SimilarityReadErrorCode,
    validate_similarity_read_reply,
)
from eom_catalog_contracts.similarity_read_v2 import (
    SimilarityContextReadReplyV2,
    SimilarityContextReadRequestV2,
    validate_similarity_read_reply_v2,
)
from eom_orchestrator.general_chat_socket import (
    ChatSocketEndpoint,
    ChatTransportError,
    exchange_chat_frame,
)
from jsonschema.exceptions import ValidationError as SchemaError


class SimilarityContextClientError(ValueError):
    def __init__(self, code: SimilarityReadErrorCode) -> None:
        self.code = code
        super().__init__(code)


class CatalogSimilarityContextClient:
    """Only a trusted authenticated API use case supplies the actual operator."""

    def __init__(self, endpoint: ChatSocketEndpoint | None = None) -> None:
        self.endpoint = endpoint

    def read(
        self, actor_id: str, selection: CompletedSimilarityQuerySelection
    ) -> SimilarityContext:
        try:
            request = SimilarityContextReadRequest(
                schema_version="system-rag-similarity-read-request/1.0",
                operation="READ_SIMILARITY_CONTEXT",
                actor_id=actor_id,
                selection=selection,
            )
        except (ValueError, SchemaError):
            raise SimilarityContextClientError("SIMILARITY_CONTEXT_REQUEST_INVALID") from None
        result = self._exchange(request)
        if isinstance(result, SimilarityContextV2):
            raise SimilarityContextClientError("SIMILARITY_CONTEXT_UNAVAILABLE")
        return result

    def read_v2(
        self, actor_id: str, selection: CompletedSimilarityQuerySelection
    ) -> SimilarityContextV2:
        try:
            request = SimilarityContextReadRequestV2(
                schema_version="system-rag-similarity-read-request/2.0",
                operation="READ_SIMILARITY_CONTEXT",
                actor_id=actor_id,
                selection=selection,
            )
        except (ValueError, SchemaError):
            raise SimilarityContextClientError("SIMILARITY_CONTEXT_REQUEST_INVALID") from None
        result = self._exchange(request)
        if not isinstance(result, SimilarityContextV2):
            raise SimilarityContextClientError("SIMILARITY_CONTEXT_UNAVAILABLE")
        return result

    def _exchange(
        self, request: SimilarityContextReadRequest | SimilarityContextReadRequestV2
    ) -> SupportedSimilarityContext:
        try:
            endpoint = self.endpoint or ChatSocketEndpoint(
                Path(CATALOG_APPLICATION_SOCKET_PATH),
                pwd.getpwnam("eom-catalog-manager").pw_uid,
                grp.getgrnam("eom-api").gr_gid,
            )
            value = exchange_chat_frame(
                endpoint,
                request.model_dump(mode="json"),
                request_limit=MAX_SIMILARITY_READ_FRAME_BYTES,
                reply_limit=MAX_SIMILARITY_READ_FRAME_BYTES,
                timeout=30.0,
            )
            reply: SimilarityContextReadReply | SimilarityContextReadReplyV2
            if isinstance(request, SimilarityContextReadRequestV2):
                reply = SimilarityContextReadReplyV2.model_validate(value)
                validate_similarity_read_reply_v2(request, reply)
            else:
                reply = SimilarityContextReadReply.model_validate(value)
                validate_similarity_read_reply(request, reply)
        except (ValueError, SchemaError, ChatTransportError, KeyError, OSError):
            raise SimilarityContextClientError("SIMILARITY_CONTEXT_UNAVAILABLE") from None
        if reply.result is None:
            raise SimilarityContextClientError(reply.error_code or "SIMILARITY_CONTEXT_UNAVAILABLE")
        return reply.result
