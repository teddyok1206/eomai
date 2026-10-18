"""Concrete original-private-query read port; no launch, session cache or public fallback."""

from __future__ import annotations

from eom_catalog_contracts.embedding_reference_query import raw_similarity_contract_value
from eom_catalog_contracts.private_chat_query_read import ChatPrivateQueryOrigin
from eom_catalog_contracts.private_chat_similarity import PrivateChatSimilarityRequest
from eom_catalog_service.embedding_registry_ports import (
    EmbeddingRegistryCaller,
    EmbeddingRegistryError,
    ResolvedPinnedEmbeddingIndex,
    validate_embedding_registry_actor,
)
from eom_catalog_service.pinned_artifact_resolution import PinnedArtifactReadContext
from eom_catalog_service.private_chat_similarity_ports import (
    PreparedPrivateChatSimilarity,
    PrivateChatQueryUnavailable,
    VerifiedPrivateChatQueryRead,
)
from eom_catalog_service.similarity_context_ports import (
    SimilarityContextReadError,
    similarity_context_error_from_registry,
)
from eom_identity_service import OperatorAuthorizationFenceError
from eom_orchestrator.database import build_session_factory
from eom_workflow.native_private_chat_query_coordinator import (
    NativePrivateQueryCompleted,
    NativePrivateQueryPublished,
)
from eom_workflow.private_chat_query_execution import (
    PrivateChatQueryWorkflowRequest,
    parse_private_chat_query_workflow_request,
)
from eom_workflow.private_chat_query_submission_context import (
    build_private_chat_query_submission_context,
    private_chat_query_origin_key,
)
from eom_workflow.private_chat_query_workflow import PrivateChatQueryStepOutput
from jsonschema.exceptions import ValidationError as SchemaError
from sqlalchemy import select
from sqlalchemy.orm import Session

from eom_workflow_runner.errors import WorkflowError
from eom_workflow_runner.models import WorkflowInstanceRecord
from eom_workflow_runner.native_step_completion import (
    native_application_step,
    validate_completed_native_workflow,
)
from eom_workflow_runner.private_chat_query_admission import (
    validate_private_chat_query_workflow_submission,
)
from eom_workflow_runner.private_chat_query_publication_read import (
    resolve_private_chat_query_publication,
)
from eom_workflow_runner.private_chat_query_source_read import (
    CatalogPrivateChatQuerySourceOwner,
    ResolvedPrivateChatQuerySources,
    require_private_chat_query_source_root,
)


def _prepared(sources: ResolvedPrivateChatQuerySources) -> PreparedPrivateChatSimilarity:
    return PreparedPrivateChatSimilarity(
        sources.request.context_request.request_sha256,
        sources.projection.origin.basis,
        sources.projection.text,
        sources.documents.sources,
        sources.documents.truncated,
    )


class CatalogPrivateChatSimilarityRead:
    """Operation-local trusted pins; every method reacquires actual current authority."""

    def __init__(
        self,
        owner: CatalogPrivateChatQuerySourceOwner,
        *,
        request: PrivateChatQueryWorkflowRequest,
        origin: ChatPrivateQueryOrigin,
    ) -> None:
        self.request = parse_private_chat_query_workflow_request(request)
        self.origin = build_private_chat_query_submission_context(self.request, origin).origin
        self.owner = owner
        self.sessions = build_session_factory(owner.catalog.engine)

    def _sources(
        self,
        session: Session,
        caller: EmbeddingRegistryCaller,
        request: PrivateChatSimilarityRequest,
        reader: PinnedArtifactReadContext,
    ) -> ResolvedPrivateChatQuerySources:
        root = require_private_chat_query_source_root(session)
        if type(caller) is not EmbeddingRegistryCaller:
            raise SimilarityContextReadError("AUTHORITY_UNAVAILABLE")
        validate_embedding_registry_actor(caller)
        try:
            request = PrivateChatSimilarityRequest.model_validate(
                raw_similarity_contract_value(request)
            )
            if (
                caller.operator_id != self.origin.actor_id
                or request != self.request.context_request
            ):
                raise SimilarityContextReadError("SOURCE_ACCESS_DENIED")
            sources = self.owner.resolve_sources(
                session, self.request, self.origin, artifact_reader=reader
            )
            if require_private_chat_query_source_root(session) is not root:
                raise SimilarityContextReadError("AUTHORITY_UNAVAILABLE")
            return sources
        except SimilarityContextReadError:
            raise
        except (ValueError, TypeError, SchemaError):
            raise SimilarityContextReadError("SOURCE_POINTER_INVALID") from None

    def _checked_sources(
        self,
        session: Session,
        caller: EmbeddingRegistryCaller,
        request: PrivateChatSimilarityRequest,
        reader: PinnedArtifactReadContext,
        prepared: PreparedPrivateChatSimilarity,
    ) -> ResolvedPrivateChatQuerySources:
        # Missing preparation cannot select first capture or skip comparison.
        if (
            type(prepared) is not PreparedPrivateChatSimilarity
            or type(prepared.truncated) is not bool
        ):
            raise SimilarityContextReadError("SOURCE_POINTER_INVALID")
        sources = self._sources(session, caller, request, reader)
        if _prepared(sources) != prepared:
            raise SimilarityContextReadError("SOURCE_POINTER_INVALID")
        return sources

    def prepare_private_chat_similarity(
        self, caller: EmbeddingRegistryCaller, request: PrivateChatSimilarityRequest
    ) -> PreparedPrivateChatSimilarity:
        with self.sessions.begin() as session:
            reader = PinnedArtifactReadContext(session, self.owner.settings)
            return _prepared(self._sources(session, caller, request, reader))

    def reauthorize_private_chat_similarity(
        self,
        caller: EmbeddingRegistryCaller,
        request: PrivateChatSimilarityRequest,
        prepared: PreparedPrivateChatSimilarity,
    ) -> None:
        with self.sessions.begin() as session:
            reader = PinnedArtifactReadContext(session, self.owner.settings)
            self._checked_sources(session, caller, request, reader, prepared)

    def read_private_chat_similarity_index(
        self,
        caller: EmbeddingRegistryCaller,
        request: PrivateChatSimilarityRequest,
        prepared: PreparedPrivateChatSimilarity,
    ) -> tuple[ResolvedPinnedEmbeddingIndex, ...]:
        with self.sessions.begin() as session:
            reader = PinnedArtifactReadContext(session, self.owner.settings)
            sources = self._checked_sources(session, caller, request, reader, prepared)
            result = self.owner.catalog.read_private_chat_document_index_in_session(
                session,
                caller,
                sources.request.context_request,
                sources.documents,
                artifact_reader=reader,
            )
            self._checked_sources(session, caller, request, reader, prepared)
            reader.revalidate_provenance()
            return result

    def resolve_private_chat_query(
        self,
        caller: EmbeddingRegistryCaller,
        request: PrivateChatSimilarityRequest,
        prepared: PreparedPrivateChatSimilarity,
    ) -> VerifiedPrivateChatQueryRead | PrivateChatQueryUnavailable:
        with self.sessions.begin() as session:
            return self.resolve_private_chat_query_in_session(session, caller, request, prepared)

    def resolve_private_chat_query_in_session(
        self,
        session: Session,
        caller: EmbeddingRegistryCaller,
        request: PrivateChatSimilarityRequest,
        prepared: PreparedPrivateChatSimilarity,
    ) -> VerifiedPrivateChatQueryRead | PrivateChatQueryUnavailable:
        """Exact original key/terminal/receipt/bytes; no command lease or unit revival."""
        try:
            root = require_private_chat_query_source_root(session)
            if session.get_bind() is not self.owner.catalog.engine:
                raise SimilarityContextReadError("AUTHORITY_UNAVAILABLE")
            reader = PinnedArtifactReadContext(session, self.owner.settings)
            sources = self._checked_sources(session, caller, request, reader, prepared)
            workflow = session.scalar(
                select(WorkflowInstanceRecord)
                .where(
                    WorkflowInstanceRecord.idempotency_key
                    == private_chat_query_origin_key(self.origin)
                )
                .execution_options(populate_existing=True)
            )
            if workflow is None:
                return PrivateChatQueryUnavailable("QUERY_NOT_OFFERED")
            context = validate_private_chat_query_workflow_submission(
                session, workflow, self.request
            )
            if context.origin != self.origin:
                raise SimilarityContextReadError("SOURCE_POINTER_INVALID")
            if workflow.state in {"REQUESTED", "RUNNING"}:
                return PrivateChatQueryUnavailable("QUERY_NOT_OFFERED")
            step = native_application_step(
                session, workflow.workflow_id, "encode_private_chat_query"
            )
            if workflow.state != "COMPLETED" or step is None:
                raise SimilarityContextReadError("QUERY_RESULT_INVALID")
            output = PrivateChatQueryStepOutput.model_validate(
                raw_similarity_contract_value(step.output_pointer_manifest)
            )
            validate_completed_native_workflow(session, workflow, step, output)
            canonical, history = resolve_private_chat_query_publication(
                self.owner.settings,
                session=session,
                workflow=workflow,
                step=step,
                sources=sources,
                output=output,
                artifact_reader=reader,
            )
            if (
                history.state != "SUCCEEDED"
                or len(history.records) != 4
                or history.records[3].payload != NativePrivateQueryCompleted(output=output)
            ):
                raise SimilarityContextReadError("QUERY_RESULT_INVALID")
            self._checked_sources(session, caller, request, reader, prepared)
            session.refresh(workflow)
            session.refresh(step)
            late_context = validate_private_chat_query_workflow_submission(
                session, workflow, self.request
            )
            if late_context != context:
                raise SimilarityContextReadError("SOURCE_POINTER_INVALID")
            validate_completed_native_workflow(session, workflow, step, output)
            reader.revalidate_provenance()
            if require_private_chat_query_source_root(session) is not root:
                raise SimilarityContextReadError("AUTHORITY_UNAVAILABLE")
            publication = history.records[2].payload
            if not isinstance(publication, NativePrivateQueryPublished):
                raise SimilarityContextReadError("QUERY_RESULT_INVALID")
            return VerifiedPrivateChatQueryRead(
                canonical.request,
                canonical.result,
                publication.result,
                publication.shard,
                canonical.binary,
            )
        except SimilarityContextReadError:
            raise
        except OperatorAuthorizationFenceError:
            raise SimilarityContextReadError("AUTHORITY_UNAVAILABLE") from None
        except EmbeddingRegistryError as error:
            raise similarity_context_error_from_registry(error) from None
        except (ValueError, TypeError, SchemaError, KeyError, OSError, WorkflowError):
            raise SimilarityContextReadError("QUERY_RESULT_INVALID") from None
