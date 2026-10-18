"""Read one exact completed QUERY through current Catalog authority and common context."""

from __future__ import annotations

from dataclasses import replace

from eom_catalog_contracts.similarity_context import SimilarityContext
from eom_catalog_contracts.similarity_read import (
    SimilarityContextReadRequest,
)
from eom_identity_service import OperatorAuthorizationFenceError
from eom_orchestrator.database import build_session_factory
from eom_workflow_runner.errors import WorkflowError
from eom_workflow_runner.reference_query_consumer_read import (
    CatalogCompletedReferenceQueryRead,
    select_completed_reference_query_request,
)
from eom_workflow_runner.reference_query_source_read import (
    CatalogReferenceQueryReadOwner,
    ReferenceQuerySourceOwner,
)
from eom_workflow_runner.similarity_context_session_reader import (
    CatalogSimilaritySessionContextReader,
)
from jsonschema.exceptions import ValidationError as SchemaError

from eom_catalog_service.embedding_registry_ports import (
    EmbeddingRegistryCaller,
    EmbeddingRegistryError,
)
from eom_catalog_service.inference_transfer_read_timing import (
    InferenceTransferReadStage,
    observe_read_stage,
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
                original = select_completed_reference_query_request(
                    session, self.owner, caller, request.selection
                )
                provenance = PinnedArtifactReadContext(session, self.owner.settings)
                selected = self.owner.catalog.for_pinned_similarity_request_in_session(
                    session, caller, original.context_request, artifact_reader=provenance
                )
                owner = self.owner
                if selected.configuration != self.owner.catalog.configuration:
                    owner = CatalogReferenceQueryReadOwner(
                        self.owner.catalog.engine,
                        replace(self.owner.configuration, registry=selected.configuration),
                        identity_fence=self.owner.identity,
                        settings=self.owner.settings,
                    )
                with observe_read_stage(InferenceTransferReadStage.RESOLVE_COMPLETED_BEFORE):
                    current = owner.resolve_completed_sources(
                        session,
                        caller,
                        original,
                        workflow_id=request.selection.workflow_id,
                        artifact_reader=provenance,
                    )
                query = CatalogCompletedReferenceQueryRead(
                    owner,
                    workflow_id=request.selection.workflow_id,
                    request=original,
                    artifact_reader=provenance,
                )
                with observe_read_stage(InferenceTransferReadStage.COMPOSE_CONTEXT):
                    result = CatalogSimilaritySessionContextReader(query).compose_in_session(
                        session, caller, original.context_request
                    )
                if result.status == "FAILED":
                    assert result.error_code is not None
                    raise SimilarityContextReadError(result.error_code)
                late_request = select_completed_reference_query_request(
                    session, owner, caller, request.selection
                )
                with observe_read_stage(InferenceTransferReadStage.RESOLVE_COMPLETED_AFTER):
                    late = owner.resolve_completed_sources(
                        session,
                        caller,
                        late_request,
                        workflow_id=request.selection.workflow_id,
                        artifact_reader=provenance,
                    )
                if (
                    late_request != original
                    or late.sources != current.sources
                    or (late.output != current.output)
                ):
                    raise SimilarityContextReadError("QUERY_RESULT_INVALID")
                with observe_read_stage(InferenceTransferReadStage.FINAL_PROVENANCE):
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
