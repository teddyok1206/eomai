"""Completed QUERY read composition, with current Identity and exact execution closure."""

from __future__ import annotations

from dataclasses import dataclass

from eom_catalog_contracts.registered_public_solution_similarity import (
    SupportedPublicSolutionSimilarityContext,
    SupportedPublicSolutionSimilarityRequest,
    parse_supported_public_solution_similarity_request,
)
from eom_catalog_contracts.similarity_context_v2 import (
    SupportedSimilarityContextRequest,
    parse_supported_similarity_context_request,
)
from eom_catalog_contracts.similarity_read import CompletedSimilarityQuerySelection
from eom_catalog_service.embedding_registry_ports import (
    EmbeddingRegistryCaller,
    EmbeddingRegistryError,
    validate_embedding_registry_actor,
)
from eom_catalog_service.pinned_artifact_resolution import PinnedArtifactReadContext
from eom_catalog_service.public_solution_similarity_read import CatalogPublicSolutionSimilarityRead
from eom_catalog_service.public_solution_similarity_service import (
    PreparedPublicSolutionQuerySource,
    VerifiedPublicSolutionQueryRead,
)
from eom_catalog_service.reference_query_artifact_read import (
    ResolvedPublicSolutionQueryArtifacts,
    ResolvedReferenceQueryArtifacts,
)
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
    NativeQueryCompletedV2,
    NativeQueryPublished,
    NativeQueryPublishedV2,
)
from eom_workflow.reference_query_execution import (
    PublicReferenceQueryWorkflowRequest,
    ReferenceQueryStepOutput,
    ReferenceQueryStepOutputV2,
    SupportedReferenceQueryStepOutput,
    SupportedReferenceQueryWorkflowRequest,
    parse_supported_reference_query_workflow_request,
)
from jsonschema.exceptions import ValidationError as JsonSchemaError
from pydantic import TypeAdapter
from sqlalchemy.orm import Session

from eom_workflow_runner.errors import WorkflowError
from eom_workflow_runner.models import WorkflowInstanceRecord
from eom_workflow_runner.reference_query_publication_read import resolve_reference_query_publication
from eom_workflow_runner.reference_query_source_read import (
    ReferenceQuerySourceOwner,
    ResolvedPublicSolutionReferenceQuerySources,
    ResolvedReferenceQuerySources,
    select_completed_reference_query_read_owner,
)


@dataclass(frozen=True, slots=True)
class CompletedReferenceQuerySelectionRead:
    selection: CompletedSimilarityQuerySelection
    output: SupportedReferenceQueryStepOutput


def read_completed_reference_query_selection(
    session: Session,
    owner: ReferenceQuerySourceOwner,
    caller: EmbeddingRegistryCaller,
    workflow_id: str,
) -> CompletedReferenceQuerySelectionRead:
    """Same canonical completed-read owner for standalone, CUDA and CPU-routed callers."""
    root = session.get_transaction()
    if root is None or not root.is_active or session.in_nested_transaction():
        raise SimilarityContextReadError("AUTHORITY_UNAVAILABLE")
    owner.identity.fence_current_operator(session, caller.operator_id)
    workflow = session.get(WorkflowInstanceRecord, workflow_id, populate_existing=True)
    if (
        workflow is None
        or workflow.created_actor_type != "human"
        or workflow.created_actor_id != caller.operator_id
    ):
        raise SimilarityContextReadError("SOURCE_ACCESS_DENIED")
    if workflow.state != "COMPLETED":
        raise SimilarityContextReadError("QUERY_RESULT_INVALID")
    request = parse_supported_reference_query_workflow_request(workflow.initial_request)
    owner = select_completed_reference_query_read_owner(owner, request)
    selection = CompletedSimilarityQuerySelection(
        workflow_id=workflow.workflow_id,
        workflow_request_sha256=request.request_sha256,
        context_request_sha256=request.context_request.request_sha256,
    )
    require_completed_query_selection_metadata(workflow, caller, selection)
    reader = PinnedArtifactReadContext.for_session(session, owner.settings)
    current = owner.resolve_completed_sources(
        session, caller, request, workflow_id=workflow_id, artifact_reader=reader
    )
    query_reader = CatalogCompletedReferenceQueryRead(
        owner, workflow_id=workflow_id, request=request, artifact_reader=reader
    )
    if isinstance(request, PublicReferenceQueryWorkflowRequest):
        if not isinstance(current.sources, ResolvedPublicSolutionReferenceQuerySources):
            raise SimilarityContextReadError("SOURCE_POINTER_INVALID")
        query_reader.resolve_public_solution_query_in_session(
            session, caller, request.context_request, current.sources.prepared
        )
    else:
        if not isinstance(current.sources, ResolvedReferenceQuerySources):
            raise SimilarityContextReadError("SOURCE_POINTER_INVALID")
        query_reader.resolve_reference_query_in_session(
            session, caller, request.context_request, current.sources.prepared
        )
    return CompletedReferenceQuerySelectionRead(selection, current.output)


def require_completed_query_selection_metadata(
    row: WorkflowInstanceRecord | None,
    caller: EmbeddingRegistryCaller,
    selection: CompletedSimilarityQuerySelection,
) -> SupportedReferenceQueryWorkflowRequest:
    """Pure exact metadata binding, never Identity/source authority or Artifact access."""
    if type(caller) is not EmbeddingRegistryCaller:
        raise SimilarityContextReadError("AUTHORITY_UNAVAILABLE")
    validate_embedding_registry_actor(caller)
    selection = CompletedSimilarityQuerySelection.model_validate(selection)
    if (
        row is None
        or row.workflow_id != selection.workflow_id
        or row.created_actor_type != "human"
        or row.created_actor_id != caller.operator_id
    ):
        raise SimilarityContextReadError("SOURCE_ACCESS_DENIED")
    if row.state != "COMPLETED" or row.initial_request != row.request_payload:
        raise SimilarityContextReadError("QUERY_RESULT_INVALID")
    original = parse_supported_reference_query_workflow_request(row.initial_request)
    if (
        original.operator_audit.operator_id != caller.operator_id
        or original.request_sha256 != selection.workflow_request_sha256
        or original.context_request.request_sha256 != selection.context_request_sha256
    ):
        raise SimilarityContextReadError("QUERY_RESULT_INVALID")
    return original


def read_completed_public_solution_similarity_in_session(
    session: Session,
    owner: ReferenceQuerySourceOwner,
    caller: EmbeddingRegistryCaller,
    selection: CompletedSimilarityQuerySelection,
) -> SupportedPublicSolutionSimilarityContext:
    """Official completed QUERY2 → current authorized Graph/registry ranking, no new computation."""
    request = select_completed_reference_query_request(session, owner, caller, selection)
    if not isinstance(request, PublicReferenceQueryWorkflowRequest):
        raise SimilarityContextReadError("QUERY_RESULT_INVALID")
    owner = select_completed_reference_query_read_owner(owner, request)
    provenance = PinnedArtifactReadContext.for_session(session, owner.settings)
    current = owner.resolve_completed_sources(
        session,
        caller,
        request,
        workflow_id=selection.workflow_id,
        artifact_reader=provenance,
    )
    if not isinstance(current.sources, ResolvedPublicSolutionReferenceQuerySources):
        raise SimilarityContextReadError("SOURCE_POINTER_INVALID")
    query = CatalogCompletedReferenceQueryRead(
        owner,
        workflow_id=selection.workflow_id,
        request=request,
        artifact_reader=provenance,
    ).resolve_public_solution_query_in_session(
        session, caller, request.context_request, current.sources.prepared
    )
    result = CatalogPublicSolutionSimilarityRead(owner.catalog).read_in_session(
        session, caller, request.context_request, query
    )
    owner.identity.fence_current_operator(session, caller.operator_id)
    provenance.revalidate_provenance()
    return result


def select_completed_reference_query_request(
    session: Session,
    owner: ReferenceQuerySourceOwner,
    caller: EmbeddingRegistryCaller,
    selection: CompletedSimilarityQuerySelection,
) -> SupportedReferenceQueryWorkflowRequest:
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
        # The pure binder is shared with runner expectations, not its authority.
        return require_completed_query_selection_metadata(row, caller, selection)
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
        request: SupportedReferenceQueryWorkflowRequest,
        artifact_reader: PinnedArtifactReadContext | None = None,
    ) -> None:
        self.workflow_id = TypeAdapter(WorkflowId).validate_python(workflow_id)
        self.request = parse_supported_reference_query_workflow_request(request)
        self.owner = select_completed_reference_query_read_owner(owner, self.request)
        self.artifact_reader = artifact_reader
        self.sessions = build_session_factory(self.owner.catalog.engine)

    def resolve_reference_query(
        self,
        caller: EmbeddingRegistryCaller,
        request: SupportedSimilarityContextRequest,
        prepared: PreparedSimilarityContext,
    ) -> VerifiedReferenceQueryRead:
        with self.sessions.begin() as session:
            return self.resolve_reference_query_in_session(session, caller, request, prepared)

    def resolve_public_solution_query_in_session(
        self,
        session: Session,
        caller: EmbeddingRegistryCaller,
        request: SupportedPublicSolutionSimilarityRequest,
        prepared: PreparedPublicSolutionQuerySource,
    ) -> VerifiedPublicSolutionQueryRead:
        """Same canonical completion owner, with exact public-report source/result family."""
        root = session.get_transaction()
        if root is None or not root.is_active or session.in_nested_transaction():
            raise SimilarityContextReadError("AUTHORITY_UNAVAILABLE")
        try:
            request = parse_supported_public_solution_similarity_request(request)
            if (
                type(caller) is not EmbeddingRegistryCaller
                or not isinstance(self.request, PublicReferenceQueryWorkflowRequest)
                or caller.operator_id != self.request.operator_audit.operator_id
                or request != self.request.context_request
                or type(prepared) is not PreparedPublicSolutionQuerySource
            ):
                raise SimilarityContextReadError("AUTHORITY_UNAVAILABLE")
            provenance = self.artifact_reader or PinnedArtifactReadContext.for_session(
                session, self.owner.settings
            )
            provenance.require_session(session)
            if provenance.settings != self.owner.settings:
                raise SimilarityContextReadError("QUERY_RESULT_INVALID")
            current = self.owner.resolve_completed_sources(
                session,
                caller,
                self.request,
                workflow_id=self.workflow_id,
                artifact_reader=provenance,
            )
            if (
                not isinstance(current.sources, ResolvedPublicSolutionReferenceQuerySources)
                or not isinstance(current.output, ReferenceQueryStepOutputV2)
                or current.sources.prepared != prepared
            ):
                raise SimilarityContextReadError("SOURCE_POINTER_INVALID")
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
                not isinstance(canonical, ResolvedPublicSolutionQueryArtifacts)
                or history.state != "SUCCEEDED"
                or len(history.records) != 4
                or history.records[3].payload != NativeQueryCompletedV2(output=current.output)
            ):
                raise SimilarityContextReadError("QUERY_RESULT_INVALID")
            late = self.owner.resolve_completed_sources(
                session,
                caller,
                self.request,
                workflow_id=self.workflow_id,
                artifact_reader=provenance,
            )
            if late != current:
                raise SimilarityContextReadError("SOURCE_POINTER_INVALID")
            provenance.revalidate_provenance()
            published = history.records[2].payload
            if not isinstance(published, NativeQueryPublishedV2):
                raise SimilarityContextReadError("QUERY_RESULT_INVALID")
            return VerifiedPublicSolutionQueryRead(
                canonical.request,
                canonical.result,
                published.result,
                published.shard,
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

    def resolve_reference_query_in_session(
        self,
        session: Session,
        caller: EmbeddingRegistryCaller,
        request: SupportedSimilarityContextRequest,
        prepared: PreparedSimilarityContext,
    ) -> VerifiedReferenceQueryRead:
        """Same caller-owned root through Identity/source/history/member and late checks."""
        root = session.get_transaction()
        if root is None or not root.is_active or session.in_nested_transaction():
            raise SimilarityContextReadError("AUTHORITY_UNAVAILABLE")
        request = parse_supported_similarity_context_request(request)
        consumer_sources = validate_similarity_preparation(request, prepared)
        if (
            not isinstance(caller, EmbeddingRegistryCaller)
            or caller.operator_id != self.request.operator_audit.operator_id
            or request != self.request.context_request
        ):
            raise SimilarityContextReadError("AUTHORITY_UNAVAILABLE")
        try:
            provenance = (
                PinnedArtifactReadContext(session, self.owner.settings)
                if self.artifact_reader is None
                else self.artifact_reader
            )
            provenance.require_session(session)
            if provenance.settings != self.owner.settings:
                raise SimilarityContextReadError("QUERY_RESULT_INVALID")
            current = self.owner.resolve_completed_sources(
                session,
                caller,
                self.request,
                workflow_id=self.workflow_id,
                artifact_reader=provenance,
            )
            if not isinstance(current.sources, ResolvedReferenceQuerySources) or not isinstance(
                current.output, ReferenceQueryStepOutput
            ):
                raise SimilarityContextReadError("QUERY_RESULT_INVALID")
            current_prepared = current.sources.prepared
            anchor_sources = validate_similarity_preparation(request, current_prepared)
            anchor_id = request.anchor.source.item_revision_id
            # QUERY encodes only the exact anchor; the common context owner
            # independently fences the full ranking population before and after use.
            if (
                anchor_sources[anchor_id] != consumer_sources[anchor_id]
                or current_prepared.query_texts != prepared.query_texts
            ):
                raise SimilarityContextReadError("SOURCE_POINTER_INVALID")
            canonical, history = resolve_reference_query_publication(
                self.owner.settings,
                session=session,
                workflow=current.workflow,
                step=current.step,
                sources=current.sources,
                output=current.output,
                artifact_reader=provenance,
            )
            if not isinstance(canonical, ResolvedReferenceQueryArtifacts):
                raise SimilarityContextReadError("QUERY_RESULT_INVALID")
            if (
                history.state != "SUCCEEDED"
                or len(history.records) != 4
                or history.records[3].payload != NativeQueryCompleted(output=current.output)
            ):
                raise SimilarityContextReadError("QUERY_RESULT_INVALID")
            late = self.owner.resolve_completed_sources(
                session,
                caller,
                self.request,
                workflow_id=self.workflow_id,
                artifact_reader=provenance,
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
