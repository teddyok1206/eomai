"""Completed QUERY read composition, with current Identity and exact execution closure."""

from __future__ import annotations

from eom_catalog_contracts.similarity_context import (
    SimilarityContextRequest,
    parse_similarity_context_request,
)
from eom_catalog_service.embedding_registry_ports import (
    EmbeddingRegistryCaller,
    EmbeddingRegistryError,
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
    NativeQueryPublished,
)
from eom_workflow.reference_query_execution import (
    ReferenceQueryWorkflowRequest,
    parse_reference_query_workflow_request,
)
from jsonschema.exceptions import ValidationError as JsonSchemaError
from pydantic import TypeAdapter

from eom_workflow_runner.errors import WorkflowError
from eom_workflow_runner.reference_query_completion import NativeReferenceQueryCompletion
from eom_workflow_runner.reference_query_owner_admission import CatalogReferenceQueryOwnerAdmission


class CatalogCompletedReferenceQueryRead:
    """One trusted, exact completed Workflow selection; no launch, retry or latest lookup.

    The actual captured operator and installed controls live in the owner. A model
    cannot supply this adapter or turn its result/source pointers into authority.
    Reading uses a fresh root, not a mutable command lease or surviving unit state.
    """

    def __init__(
        self,
        owner: CatalogReferenceQueryOwnerAdmission,
        *,
        workflow_id: str,
        request: ReferenceQueryWorkflowRequest,
    ) -> None:
        self.owner = owner
        self.workflow_id = TypeAdapter(WorkflowId).validate_python(workflow_id)
        self.request = parse_reference_query_workflow_request(request)
        self.sessions = build_session_factory(owner.catalog.engine)
        self.completion = NativeReferenceQueryCompletion(owner)

    def resolve_reference_query(
        self,
        caller: EmbeddingRegistryCaller,
        request: SimilarityContextRequest,
        prepared: PreparedSimilarityContext,
    ) -> VerifiedReferenceQueryRead:
        request = parse_similarity_context_request(request)
        validate_similarity_preparation(request, prepared)
        if (
            not isinstance(caller, EmbeddingRegistryCaller)
            or caller.operator_id != self.request.operator_audit.operator_id
            or request != self.request.context_request
        ):
            raise SimilarityContextReadError("AUTHORITY_UNAVAILABLE")
        try:
            with self.sessions.begin() as session:
                current = self.owner.resolve_completed_sources(
                    session, caller, self.request, workflow_id=self.workflow_id
                )
                if current.sources.prepared != prepared:
                    raise SimilarityContextReadError("SOURCE_POINTER_INVALID")
                canonical, history = self.completion.resolve_publication(
                    session=session,
                    workflow=current.workflow,
                    step=current.step,
                    sources=current.sources,
                    output=current.output,
                )
                if (
                    history.state != "SUCCEEDED"
                    or len(history.records) != 4
                    or history.records[3].payload != NativeQueryCompleted(output=current.output)
                ):
                    raise SimilarityContextReadError("QUERY_RESULT_INVALID")
                # Re-resolve after bounded member reads, not an authority cache hit.
                late = self.owner.resolve_completed_sources(
                    session, caller, self.request, workflow_id=self.workflow_id
                )
                if late.sources != current.sources or late.output != current.output:
                    raise SimilarityContextReadError("SOURCE_POINTER_INVALID")
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
