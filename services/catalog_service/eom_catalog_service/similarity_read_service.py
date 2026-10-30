"""Read one exact completed QUERY through current Catalog authority and common context."""

from __future__ import annotations

from dataclasses import replace

from eom_catalog_contracts.mixed_embedding_registry import MixedEmbeddingIndexNamespace
from eom_catalog_contracts.public_solution_embedding_index import PublicSolutionIndexNamespace
from eom_catalog_contracts.public_solution_similarity import PublicSolutionSimilarityContext
from eom_catalog_contracts.similarity_context_v2 import (
    SimilarityContextRequestV2,
    SupportedSimilarityContext,
)
from eom_catalog_contracts.similarity_read import (
    SimilarityContextReadRequest,
)
from eom_catalog_contracts.similarity_read_v2 import SimilarityContextReadRequestV2
from eom_catalog_contracts.similarity_read_v3 import SimilarityContextReadRequestV3
from eom_identity_service import OperatorAuthorizationFenceError
from eom_orchestrator.database import build_session_factory
from eom_workflow.reference_query_execution import ReferenceQueryWorkflowRequestV3
from eom_workflow_runner.errors import WorkflowError
from eom_workflow_runner.reference_query_consumer_read import (
    CatalogCompletedReferenceQueryRead,
    read_completed_public_solution_similarity_in_session,
    select_completed_reference_query_request,
)
from eom_workflow_runner.reference_query_source_read import (
    CatalogReferenceQueryReadOwner,
    ReferenceQuerySourceOwner,
    select_completed_reference_query_read_owner,
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

    def __init__(
        self,
        owner: ReferenceQuerySourceOwner,
        *,
        mixed_owner: ReferenceQuerySourceOwner | None = None,
        public_owner: ReferenceQuerySourceOwner | None = None,
    ) -> None:
        if mixed_owner is not None and (
            mixed_owner.catalog.engine is not owner.catalog.engine
            or not isinstance(
                mixed_owner.configuration.registry.namespace, MixedEmbeddingIndexNamespace
            )
        ):
            raise ValueError("mixed similarity reader composition differs")
        self.owner = owner
        self.mixed_owner = mixed_owner
        if public_owner is not None and (
            public_owner.catalog.engine is not owner.catalog.engine
            or not isinstance(
                public_owner.configuration.registry.namespace, PublicSolutionIndexNamespace
            )
        ):
            raise ValueError("public similarity reader composition differs")
        self.public_owner = public_owner
        self.sessions = build_session_factory(owner.catalog.engine)

    def read(
        self,
        request: SimilarityContextReadRequest
        | SimilarityContextReadRequestV2
        | SimilarityContextReadRequestV3,
    ) -> SupportedSimilarityContext | PublicSolutionSimilarityContext:
        if isinstance(request, SimilarityContextReadRequestV3):
            return self._read_public(request)
        request = (
            SimilarityContextReadRequestV2.model_validate(request)
            if isinstance(request, SimilarityContextReadRequestV2)
            else SimilarityContextReadRequest.model_validate(request)
        )
        source_owner = self.owner
        if isinstance(request, SimilarityContextReadRequestV2):
            if self.mixed_owner is not None:
                source_owner = self.mixed_owner
            elif not isinstance(
                self.owner.configuration.registry.namespace, MixedEmbeddingIndexNamespace
            ):
                raise SimilarityContextReadError("QUERY_RESULT_INVALID")
        caller = EmbeddingRegistryCaller(request.actor_id)
        try:
            with self.sessions.begin() as session:
                original = select_completed_reference_query_request(
                    session, source_owner, caller, request.selection
                )
                if isinstance(original, ReferenceQueryWorkflowRequestV3):
                    raise SimilarityContextReadError("QUERY_RESULT_INVALID")
                if isinstance(original.context_request, SimilarityContextRequestV2) != isinstance(
                    request, SimilarityContextReadRequestV2
                ):
                    raise SimilarityContextReadError("QUERY_RESULT_INVALID")
                source_owner = select_completed_reference_query_read_owner(source_owner, original)
                provenance = PinnedArtifactReadContext(session, source_owner.settings)
                selected = source_owner.catalog.for_pinned_similarity_request_in_session(
                    session, caller, original.context_request, artifact_reader=provenance
                )
                owner = source_owner
                if selected.configuration != source_owner.catalog.configuration:
                    owner = CatalogReferenceQueryReadOwner(
                        source_owner.catalog.engine,
                        replace(source_owner.configuration, registry=selected.configuration),
                        identity_fence=source_owner.identity,
                        settings=source_owner.settings,
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

    def _read_public(
        self, request: SimilarityContextReadRequestV3
    ) -> PublicSolutionSimilarityContext:
        request = SimilarityContextReadRequestV3.model_validate(request)
        owner = self.public_owner
        if owner is None:
            raise SimilarityContextReadError("QUERY_RESULT_INVALID")
        try:
            with self.sessions.begin() as session:
                return read_completed_public_solution_similarity_in_session(
                    session, owner, EmbeddingRegistryCaller(request.actor_id), request.selection
                )
        except SimilarityContextReadError:
            raise
        except OperatorAuthorizationFenceError:
            raise SimilarityContextReadError("AUTHORITY_UNAVAILABLE") from None
        except EmbeddingRegistryError as error:
            raise similarity_context_error_from_registry(error) from None
        except (ValueError, SchemaError, TypeError, KeyError, WorkflowError):
            raise SimilarityContextReadError("QUERY_RESULT_INVALID") from None
