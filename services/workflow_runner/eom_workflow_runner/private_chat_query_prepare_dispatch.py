"""Closed owner request → existing original private preparation/read application."""

from __future__ import annotations

from eom_catalog_contracts.embedding_reference_query import ReferenceQuerySpaces
from eom_catalog_contracts.embedding_registry import EmbeddingIndexNamespace
from eom_catalog_contracts.private_chat_query_prepare import (
    PrivateChatQueryPrepareErrorCode,
    PrivateChatQueryPrepareReply,
    private_chat_query_context_request_id,
)
from eom_catalog_contracts.private_chat_query_prepare_v2 import (
    PrivateChatQueryPrepareReplyV2,
    PrivateChatQueryPrepareRequestV2,
    SupportedPrivateChatQueryPrepareReply,
    SupportedPrivateChatQueryPrepareRequest,
    parse_supported_private_chat_query_prepare_request,
    validate_supported_private_chat_query_prepare_reply,
)
from eom_catalog_contracts.private_chat_similarity import PrivateChatSimilarityContext
from eom_catalog_contracts.private_chat_similarity_v2 import PrivateChatSimilarityContextV2
from eom_catalog_contracts.public_solution_embedding_index import (
    MAX_PUBLIC_SOLUTION_SOURCES,
    PublicSolutionIndexNamespace,
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
from eom_workflow.private_chat_query_execution import PrivateChatQueryWorkflowRequest
from eom_workflow.private_chat_query_execution_v2 import PrivateChatQueryWorkflowRequestV2

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
        namespace = application.owner.configuration.registry.namespace
        if (
            spaces.document != application.owner.configuration.registry.space
            or not isinstance(namespace, EmbeddingIndexNamespace | PublicSolutionIndexNamespace)
            or type(maximum_sources) is not int
            or not 1
            <= maximum_sources
            <= (
                MAX_PUBLIC_SOLUTION_SOURCES
                if isinstance(namespace, PublicSolutionIndexNamespace)
                else 1024
            )
            or type(top_k) is not int
            or not 1 <= top_k <= 64
        ):
            raise ValueError("PRIVATE_CHAT_QUERY_PREPARE_COMPOSITION_INVALID")
        self.application, self.spaces = application, spaces
        self.maximum_sources, self.top_k = maximum_sources, top_k

    def execute(
        self, request: SupportedPrivateChatQueryPrepareRequest
    ) -> SupportedPrivateChatQueryPrepareReply:
        request = parse_supported_private_chat_query_prepare_request(request)
        config = self.application.owner.configuration.registry
        if isinstance(request, PrivateChatQueryPrepareRequestV2) != isinstance(
            config.namespace, PublicSolutionIndexNamespace
        ):
            return self._failure(request, "FAILED", "AUTHORITY_UNAVAILABLE")
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
            context = result.context
            expected_request = (
                PrivateChatQueryWorkflowRequestV2
                if isinstance(request, PrivateChatQueryPrepareRequestV2)
                else PrivateChatQueryWorkflowRequest
            )
            expected_context = (
                PrivateChatSimilarityContextV2
                if isinstance(request, PrivateChatQueryPrepareRequestV2)
                else PrivateChatSimilarityContext
            )
            if not isinstance(result.request, expected_request) or (
                context is not None and not isinstance(context, expected_context)
            ):
                return self._failure(request, "FAILED", "QUERY_RESULT_INVALID")
            reply_type = (
                PrivateChatQueryPrepareReplyV2
                if isinstance(request, PrivateChatQueryPrepareRequestV2)
                else PrivateChatQueryPrepareReply
            )
            family = "2.0" if isinstance(request, PrivateChatQueryPrepareRequestV2) else "1.0"
            reply = reply_type.model_validate(
                dict(
                    schema_version=f"system-rag-private-chat-query-prepare-reply/{family}",
                    action=request.action,
                    request_id=request.request_id,
                    request_sha256=request.request_sha256,
                    status=result.status,
                    workflow_id=result.workflow_id,
                    context=context,
                    error_code=result.failure_code,
                )
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
        return validate_supported_private_chat_query_prepare_reply(request, reply)

    @staticmethod
    def _failure(
        request: SupportedPrivateChatQueryPrepareRequest,
        status: str,
        code: PrivateChatQueryPrepareErrorCode,
    ) -> SupportedPrivateChatQueryPrepareReply:
        reply_type = (
            PrivateChatQueryPrepareReplyV2
            if isinstance(request, PrivateChatQueryPrepareRequestV2)
            else PrivateChatQueryPrepareReply
        )
        family = "2.0" if isinstance(request, PrivateChatQueryPrepareRequestV2) else "1.0"
        return reply_type.model_validate(
            dict(
                schema_version=f"system-rag-private-chat-query-prepare-reply/{family}",
                action=request.action,
                request_id=request.request_id,
                request_sha256=request.request_sha256,
                status=status,
                workflow_id=None,
                context=None,
                error_code=code,
            )
        )
