"""Read one exact completed QUERY through current Catalog authority and common context."""

from __future__ import annotations

from eom_catalog_contracts.similarity_context import SimilarityContext
from eom_catalog_contracts.similarity_read import (
    CompletedSimilarityQuerySelection,
    SimilarityContextReadRequest,
)
from eom_identity_service import OperatorAuthorizationFenceError
from eom_orchestrator.database import build_session_factory
from eom_workflow.reference_query_execution import (
    ReferenceQueryWorkflowRequest,
    parse_reference_query_workflow_request,
)
from eom_workflow_runner.errors import WorkflowError
from eom_workflow_runner.models import WorkflowInstanceRecord
from eom_workflow_runner.reference_query_consumer_read import CatalogCompletedReferenceQueryRead
from eom_workflow_runner.reference_query_source_read import ReferenceQuerySourceOwner
from eom_workflow_runner.similarity_context_session_reader import (
    CatalogSimilaritySessionContextReader,
)
from jsonschema.exceptions import ValidationError as SchemaError
from sqlalchemy.orm import Session

from eom_catalog_service.embedding_registry_ports import (
    EmbeddingRegistryCaller,
    EmbeddingRegistryError,
)
from eom_catalog_service.pinned_artifact_resolution import PinnedArtifactReadContext
from eom_catalog_service.similarity_context_ports import (
    SimilarityContextReadError,
    similarity_context_error_from_registry,
)


class CatalogSimilarityContextReadService:
    """Trusted explicit read owner; no capture, native owner, launch or latest fallback."""

    def __init__(self, owner: ReferenceQuerySourceOwner) -> None:
        self.owner = owner
        self.sessions = build_session_factory(owner.catalog.engine)

    def read(self, request: SimilarityContextReadRequest) -> SimilarityContext:
        request = SimilarityContextReadRequest.model_validate(request)
        caller = EmbeddingRegistryCaller(request.actor_id)
        try:
            with self.sessions.begin() as session:
                original = self._select(session, caller, request.selection)
                current = self.owner.resolve_completed_sources(
                    session, caller, original, workflow_id=request.selection.workflow_id
                )
                provenance = PinnedArtifactReadContext(session, self.owner.settings)
                query = CatalogCompletedReferenceQueryRead(
                    self.owner,
                    workflow_id=request.selection.workflow_id,
                    request=original,
                    artifact_reader=provenance,
                )
                result = CatalogSimilaritySessionContextReader(query).compose_in_session(
                    session, caller, original.context_request
                )
                if result.status == "FAILED":
                    assert result.error_code is not None
                    raise SimilarityContextReadError(result.error_code)
                late_request = self._select(session, caller, request.selection)
                late = self.owner.resolve_completed_sources(
                    session, caller, late_request, workflow_id=request.selection.workflow_id
                )
                if (
                    late_request != original
                    or late.sources != current.sources
                    or (late.output != current.output)
                ):
                    raise SimilarityContextReadError("QUERY_RESULT_INVALID")
                provenance.revalidate_provenance()
                return result
        except SimilarityContextReadError:
            raise
        except OperatorAuthorizationFenceError:
            raise SimilarityContextReadError("AUTHORITY_UNAVAILABLE") from None
        except EmbeddingRegistryError as error:
            raise similarity_context_error_from_registry(error) from None
        except (ValueError, SchemaError, TypeError, KeyError, WorkflowError):
            raise SimilarityContextReadError("QUERY_RESULT_INVALID") from None

    def _select(
        self,
        session: Session,
        caller: EmbeddingRegistryCaller,
        selection: CompletedSimilarityQuerySelection,
    ) -> ReferenceQueryWorkflowRequest:
        self.owner.identity.fence_current_operator(session, caller.operator_id)
        row = session.get(WorkflowInstanceRecord, selection.workflow_id, populate_existing=True)
        # Do not parse or disclose a foreign creator's stored request. Generic read
        # permission or ADMIN is not authority to impersonate its original actor.
        if (
            row is None
            or row.created_actor_type != "human"
            or (row.created_actor_id != caller.operator_id)
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
