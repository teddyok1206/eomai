"""Closed owner request → existing original private preparation/read application."""

from __future__ import annotations

from eom_catalog_contracts.embedding_reference_query import ReferenceQuerySpaces
from eom_catalog_contracts.private_chat_query_prepare import (
    PrivateChatQueryPrepareErrorCode,
    PrivateChatQueryPrepareReply,
    PrivateChatQueryPrepareRequest,
    parse_private_chat_query_prepare_request,
    private_chat_query_context_request_id,
    validate_private_chat_query_prepare_reply,
)
from eom_catalog_service.embedding_registry_ports import (
    EmbeddingRegistryError,
    EmbeddingRegistryLookup,
    PrivateChatContextPreparation,
)
from eom_catalog_service.similarity_context_ports import (
    SimilarityContextReadError,
    similarity_context_error_from_registry,
)
from eom_identity_service import OperatorAuthorizationFenceError

from eom_workflow_runner.private_chat_query_preparation import (
    PrivateChatQueryPreparationUnavailable,
)
from eom_workflow_runner.private_chat_query_prepare_application import (
    NativePrivateChatQueryPreparation,
    PrivateChatQueryNotPrepared,
)


class NativePrivateChatQueryPrepareDispatch:
    """Operation-local composition; no session cache or caller-selected runtime controls."""

    def __init__(
        self,
        application: NativePrivateChatQueryPreparation,
        spaces: ReferenceQuerySpaces,
        *,
        maximum_sources: int = 1024,
        top_k: int = 64,
    ) -> None:
        spaces = ReferenceQuerySpaces.model_validate(spaces)
        if (
            spaces.document != application.owner.configuration.registry.space
            or type(maximum_sources) is not int
            or not 1 <= maximum_sources <= 1024
            or type(top_k) is not int
            or not 1 <= top_k <= 64
        ):
            raise ValueError("PRIVATE_CHAT_QUERY_PREPARE_COMPOSITION_INVALID")
        self.application, self.spaces = application, spaces
        self.maximum_sources, self.top_k = maximum_sources, top_k

    def execute(self, request: PrivateChatQueryPrepareRequest) -> PrivateChatQueryPrepareReply:
        request = parse_private_chat_query_prepare_request(request)
        config = self.application.owner.configuration.registry
        preparation = PrivateChatContextPreparation(
            private_chat_query_context_request_id(request.origin),
            request.origin.basis,
            EmbeddingRegistryLookup(
                config.corpus_id,
                config.namespace,
                request.graph_snapshot,
                request.policy_revision_id,
                request.policy_sha256,
                self.maximum_sources,
            ),
            self.spaces,
            self.top_k,
        )
        action = (
            self.application.prepare
            if request.action == "PREPARE_PRIVATE_CHAT_QUERY"
            else self.application.read
        )
        try:
            result = action(request.origin, preparation)
            if result.origin != request.origin:
                raise ValueError("PRIVATE_CHAT_QUERY_REPLY_INVALID")
            reply = PrivateChatQueryPrepareReply(
                schema_version="system-rag-private-chat-query-prepare-reply/1.0",
                action=request.action,
                request_id=request.request_id,
                request_sha256=request.request_sha256,
                status=result.status,
                workflow_id=result.workflow_id,
                context=result.context,
                error_code=result.failure_code,
            )
        except (PrivateChatQueryPreparationUnavailable, PrivateChatQueryNotPrepared) as error:
            reply = self._failure(request, "UNAVAILABLE", error.code)
        except SimilarityContextReadError as error:
            reply = self._failure(request, "FAILED", error.code)
        except EmbeddingRegistryError as error:
            reply = self._failure(
                request, "FAILED", similarity_context_error_from_registry(error).code
            )
        except OperatorAuthorizationFenceError as error:
            reply = self._failure(
                request,
                "FAILED",
                "SOURCE_ACCESS_DENIED"
                if error.code == "OPERATOR_AUTHORIZATION_FENCE_FORBIDDEN"
                else "AUTHORITY_UNAVAILABLE",
            )
        return validate_private_chat_query_prepare_reply(request, reply)

    @staticmethod
    def _failure(
        request: PrivateChatQueryPrepareRequest,
        status: str,
        code: PrivateChatQueryPrepareErrorCode,
    ) -> PrivateChatQueryPrepareReply:
        return PrivateChatQueryPrepareReply.model_validate(
            dict(
                schema_version="system-rag-private-chat-query-prepare-reply/1.0",
                action=request.action,
                request_id=request.request_id,
                request_sha256=request.request_sha256,
                status=status,
                workflow_id=None,
                context=None,
                error_code=code,
            )
        )
