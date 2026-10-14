"""Completed QUERY read composition, with current Identity and exact execution closure."""

from __future__ import annotations

from eom_catalog_contracts.similarity_context import (
    SimilarityContextRequest,
    parse_similarity_context_request,
)
from eom_catalog_contracts.similarity_read import CompletedSimilarityQuerySelection
from eom_catalog_service.embedding_registry_ports import (
    EmbeddingRegistryCaller,
    EmbeddingRegistryError,
    validate_embedding_registry_actor,
)
from eom_catalog_service.pinned_artifact_resolution import PinnedArtifactReadContext
from eom_catalog_service.similarity_context_ports import (
    PreparedSimilarityContext,
    SimilarityContextReadError,
    VerifiedReferenceQueryRead,
    similarity_context_error_from_registry,
)
from eom_catalog_service.similarity_context_service import validate_similarity_preparation
from eom_identity_service import OperatorAuthorizationFenceError
from eom_orchestrator.database import build_session_factory
from eom_workflow.models import WorkflowId
from eom_workflow.native_reference_query_coordinator import (
    NativeQueryCompleted,
    NativeQueryPublished,
)
from eom_workflow.reference_query_execution import (
    ReferenceQueryWorkflowRequest,
    parse_reference_query_workflow_request,
)
from jsonschema.exceptions import ValidationError as JsonSchemaError
from pydantic import TypeAdapter
from sqlalchemy.orm import Session

from eom_workflow_runner.errors import WorkflowError
from eom_workflow_runner.models import WorkflowInstanceRecord
from eom_workflow_runner.reference_query_publication_read import resolve_reference_query_publication
from eom_workflow_runner.reference_query_source_read import ReferenceQuerySourceOwner


def select_completed_reference_query_request(
    session: Session,
    owner: ReferenceQuerySourceOwner,
    caller: EmbeddingRegistryCaller,
    selection: CompletedSimilarityQuerySelection,
) -> ReferenceQueryWorkflowRequest:
    """Select original metadata in the actual caller root, not transferable read authority.

    Consumers must still resolve current sources and the terminal publication. This
    function never dereferences an Artifact or chooses an implicit latest QUERY.
    """
    root = session.get_transaction()
    if root is None or not root.is_active or session.in_nested_transaction():
        raise SimilarityContextReadError("AUTHORITY_UNAVAILABLE")
    if type(caller) is not EmbeddingRegistryCaller:
        raise SimilarityContextReadError("AUTHORITY_UNAVAILABLE")
    try:
        validate_embedding_registry_actor(caller)
        selection = CompletedSimilarityQuerySelection.model_validate(selection)
        owner.identity.fence_current_operator(session, caller.operator_id)
        with session.no_autoflush:
            row = session.get(WorkflowInstanceRecord, selection.workflow_id, populate_existing=True)
        # Verify creator before parsing private content. ADMIN/read permissions do
        # not authorize impersonation of the original query's actual operator.
        if (
            row is None
            or row.created_actor_type != "human"
            or row.created_actor_id != caller.operator_id
        ):
            raise SimilarityContextReadError("SOURCE_ACCESS_DENIED")
        if row.state != "COMPLETED" or row.initial_request != row.request_payload:
            raise SimilarityContextReadError("QUERY_RESULT_INVALID")
        original = parse_reference_query_workflow_request(row.initial_request)
        if (
            original.operator_audit.operator_id != caller.operator_id
            or original.request_sha256 != selection.workflow_request_sha256
            or original.context_request.request_sha256 != selection.context_request_sha256
        ):
            raise SimilarityContextReadError("QUERY_RESULT_INVALID")
        return original
    except SimilarityContextReadError:
        raise
    except OperatorAuthorizationFenceError:
        raise SimilarityContextReadError("AUTHORITY_UNAVAILABLE") from None
    except EmbeddingRegistryError as error:
        raise similarity_context_error_from_registry(error) from None
    except (JsonSchemaError, ValueError, TypeError, KeyError, WorkflowError):
        raise SimilarityContextReadError("QUERY_RESULT_INVALID") from None


class CatalogCompletedReferenceQueryRead:
    """One trusted, exact completed Workflow selection; no launch, retry or latest lookup.

    Trusted composition supplies the actual caller and installed current read owner.
    A model cannot supply this adapter or turn result/source pointers into authority.
    Reading uses current Identity/source checks, not an expired execution capture,
    mutable command lease or surviving unit state.
    """

    def __init__(
        self,
        owner: ReferenceQuerySourceOwner,
        *,
        workflow_id: str,
        request: ReferenceQueryWorkflowRequest,
        artifact_reader: PinnedArtifactReadContext | None = None,
    ) -> None:
        self.owner = owner
        self.workflow_id = TypeAdapter(WorkflowId).validate_python(workflow_id)
        self.request = parse_reference_query_workflow_request(request)
        self.artifact_reader = artifact_reader
        self.sessions = build_session_factory(owner.catalog.engine)

    def resolve_reference_query(
        self,
        caller: EmbeddingRegistryCaller,
        request: SimilarityContextRequest,
        prepared: PreparedSimilarityContext,
    ) -> VerifiedReferenceQueryRead:
        with self.sessions.begin() as session:
            return self.resolve_reference_query_in_session(session, caller, request, prepared)

    def resolve_reference_query_in_session(
        self,
        session: Session,
        caller: EmbeddingRegistryCaller,
        request: SimilarityContextRequest,
        prepared: PreparedSimilarityContext,
    ) -> VerifiedReferenceQueryRead:
        """Same caller-owned root through Identity/source/history/member and late checks."""
        root = session.get_transaction()
        if root is None or not root.is_active or session.in_nested_transaction():
            raise SimilarityContextReadError("AUTHORITY_UNAVAILABLE")
        request = parse_similarity_context_request(request)
        validate_similarity_preparation(request, prepared)
        if (
            not isinstance(caller, EmbeddingRegistryCaller)
            or caller.operator_id != self.request.operator_audit.operator_id
            or request != self.request.context_request
        ):
            raise SimilarityContextReadError("AUTHORITY_UNAVAILABLE")
        try:
            current = self.owner.resolve_completed_sources(
                session, caller, self.request, workflow_id=self.workflow_id
            )
            if current.sources.prepared != prepared:
                raise SimilarityContextReadError("SOURCE_POINTER_INVALID")
            provenance = (
                PinnedArtifactReadContext(session, self.owner.settings)
                if self.artifact_reader is None
                else self.artifact_reader
            )
            provenance.require_session(session)
            if provenance.settings != self.owner.settings:
                raise SimilarityContextReadError("QUERY_RESULT_INVALID")
            canonical, history = resolve_reference_query_publication(
                self.owner.settings,
                session=session,
                workflow=current.workflow,
                step=current.step,
                sources=current.sources,
                output=current.output,
                artifact_reader=provenance,
            )
            if (
                history.state != "SUCCEEDED"
                or len(history.records) != 4
                or history.records[3].payload != NativeQueryCompleted(output=current.output)
            ):
                raise SimilarityContextReadError("QUERY_RESULT_INVALID")
            late = self.owner.resolve_completed_sources(
                session, caller, self.request, workflow_id=self.workflow_id
            )
            if late.sources != current.sources or late.output != current.output:
                raise SimilarityContextReadError("SOURCE_POINTER_INVALID")
            provenance.revalidate_provenance()
            publication = history.records[2].payload
            assert isinstance(publication, NativeQueryPublished)
            return VerifiedReferenceQueryRead(
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
        except (JsonSchemaError, ValueError, TypeError, KeyError, WorkflowError):
            raise SimilarityContextReadError("QUERY_RESULT_INVALID") from None
