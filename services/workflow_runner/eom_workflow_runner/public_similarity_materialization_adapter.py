"""Catalog-root current public QUERY, exact context member and selected question/report IO."""

from __future__ import annotations

from pathlib import Path

from eom_catalog_contracts.inference_transfer_experiment import PopulationSource
from eom_catalog_contracts.registered_public_solution_similarity import (
    SupportedPublicSolutionSimilarityRequest,
)
from eom_catalog_contracts.similarity_context import MAX_SIMILARITY_CONTEXT_BYTES
from eom_catalog_contracts.similarity_read import CompletedSimilarityQuerySelection
from eom_catalog_service.embedding_registry_ports import EmbeddingRegistryCaller
from eom_catalog_service.pinned_artifact_resolution import (
    PinnedArtifactReadContext,
    PinnedArtifactResolutionError,
)
from eom_catalog_service.public_similarity_materials_read import CatalogPublicSolutionMaterialsRead
from eom_catalog_service.similarity_context_ports import SimilarityContextReadError
from eom_identifiers import canonical_json_bytes
from eom_identity_service import OperatorAuthorizationFenceError
from eom_orchestrator.control_service import ControlPlaneError
from eom_orchestrator.file_set_control_artifacts import CONTROL_FILE_SET_PROTOCOL
from eom_orchestrator.similarity_context_artifact import SIMILARITY_CONTEXT_ARTIFACT_TYPE
from eom_orchestrator.similarity_materialization import SimilarityWorkspaceMaterials
from eom_workflow.public_similarity_control import (
    SupportedPublicSimilarityExecutionPlan,
    parse_public_similarity_execution_plan,
    validate_public_similarity_original_source,
    validate_public_similarity_plan_context,
    validate_public_similarity_plan_request,
)
from jsonschema.exceptions import ValidationError as SchemaError
from sqlalchemy.orm import Session

from eom_workflow_runner.reference_query_consumer_read import (
    read_completed_public_solution_similarity_in_session,
    select_completed_reference_query_request,
)
from eom_workflow_runner.reference_query_source_read import (
    ReferenceQuerySourceOwner,
    select_completed_reference_query_read_owner,
)


class CatalogPublicSimilarityMaterializationReader:
    """No source grant, user cache, model execution or writes; same current root twice."""

    def __init__(
        self,
        owner: ReferenceQuerySourceOwner,
        caller: EmbeddingRegistryCaller,
        selection: CompletedSimilarityQuerySelection,
    ) -> None:
        self.owner = owner
        self.caller = caller
        self.selection = CompletedSimilarityQuerySelection.model_validate(selection)

    def resolve(
        self,
        session: Session,
        *,
        plan: SupportedPublicSimilarityExecutionPlan,
        operator_id: str,
        request: SupportedPublicSolutionSimilarityRequest,
        original_source: PopulationSource,
        canonical_artifact_root: Path,
        authorized_artifact_revision_ids: frozenset[str],
    ) -> SimilarityWorkspaceMaterials:
        checked = parse_public_similarity_execution_plan(plan)
        pin = checked.similarity_delivery.context_member
        if operator_id != self.caller.operator_id:
            raise ControlPlaneError("CONTROL_SIMILARITY_AUTHORITY_DENIED", "caller differs")
        if pin.artifact_revision_id not in authorized_artifact_revision_ids:
            raise ControlPlaneError("CONTROL_POINTER_PERMISSION_DENIED", "member not allowed")
        try:
            validate_public_similarity_plan_request(checked, request)
            original = select_completed_reference_query_request(
                session, self.owner, self.caller, self.selection
            )
            owner = select_completed_reference_query_read_owner(self.owner, original)
            if canonical_artifact_root != owner.settings.nas_artifact_root:
                raise ValueError("PUBLIC_SIMILARITY_ROOT_MISMATCH")
            first = read_completed_public_solution_similarity_in_session(
                session, owner, self.caller, self.selection
            )
            validate_public_similarity_plan_context(checked, first)
            validate_public_similarity_original_source(checked, first, original_source)
            reader = PinnedArtifactReadContext.for_session(session, owner.settings)
            reader.prefetch(((pin.artifact_id, pin.artifact_revision_id),))
            reader.require_file_set(
                pin.artifact_id,
                pin.artifact_revision_id,
                ("context.json",),
                manifest_version=CONTROL_FILE_SET_PROTOCOL,
            )
            arguments = pin.model_dump(mode="python") | {
                "expected_artifact_types": (SIMILARITY_CONTEXT_ARTIFACT_TYPE,),
                "expected_primary_file": "context.json",
                "max_bytes": MAX_SIMILARITY_CONTEXT_BYTES,
            }
            member = reader.read_pinned(**arguments)
            if member.payload != canonical_json_bytes(first.model_dump(mode="json")):
                raise ValueError("PUBLIC_SIMILARITY_MEMBER_CHANGED")
            materials = CatalogPublicSolutionMaterialsRead(owner.catalog).read_in_session(
                session, self.caller, first
            )
            late = read_completed_public_solution_similarity_in_session(
                session, owner, self.caller, self.selection
            )
            if late != first:
                raise ValueError("PUBLIC_SIMILARITY_CURRENT_CHANGED")
            reader.revalidate_provenance()
            if reader.read_pinned(**arguments).payload != member.payload:
                raise ValueError("PUBLIC_SIMILARITY_MEMBER_CHANGED")
            return SimilarityWorkspaceMaterials(
                member.payload, canonical_json_bytes(materials.model_dump(mode="json"))
            )
        except OperatorAuthorizationFenceError as error:
            raise ControlPlaneError(
                "CONTROL_SIMILARITY_AUTHORITY_DENIED"
                if error.code == "OPERATOR_AUTHORIZATION_FENCE_FORBIDDEN"
                else "CONTROL_SIMILARITY_AUTHORITY_UNAVAILABLE",
                "current public operator unavailable",
            ) from None
        except SimilarityContextReadError as error:
            raise ControlPlaneError(
                "CONTROL_SIMILARITY_AUTHORITY_DENIED"
                if error.code in {"SOURCE_ACCESS_DENIED", "SOURCE_REVOKED"}
                else "CONTROL_SIMILARITY_AUTHORITY_UNAVAILABLE"
                if error.code == "AUTHORITY_UNAVAILABLE"
                else "CONTROL_SIMILARITY_CONTEXT_INVALID",
                "current public sources unavailable",
            ) from None
        except (PinnedArtifactResolutionError, ValueError, TypeError, SchemaError):
            raise ControlPlaneError(
                "CONTROL_SIMILARITY_CONTEXT_INVALID", "public source/member pins differ"
            ) from None
