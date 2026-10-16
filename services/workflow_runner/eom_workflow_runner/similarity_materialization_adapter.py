"""Catalog common read and exact Artifact resolution behind the Orchestrator delivery port."""

from __future__ import annotations

from pathlib import Path

from eom_catalog_contracts.inference_transfer_experiment import PopulationSource
from eom_catalog_contracts.similarity_context import (
    MAX_SIMILARITY_CONTEXT_BYTES,
    SimilarityContext,
    SimilarityContextRequest,
    parse_similarity_context,
)
from eom_catalog_contracts.similarity_materials import validate_similarity_materials
from eom_catalog_service.embedding_registry_ports import (
    EmbeddingRegistryCaller,
    SimilarityMaterialsReadPort,
    validate_embedding_registry_actor,
)
from eom_catalog_service.pinned_artifact_resolution import (
    PinnedArtifactReadContext,
    PinnedArtifactResolutionError,
)
from eom_catalog_service.settings import CatalogSettings
from eom_catalog_service.similarity_context_ports import (
    SimilarityContextReadError,
)
from eom_identifiers import canonical_json_bytes
from eom_orchestrator.control_service import ControlPlaneError
from eom_orchestrator.file_set_control_artifacts import CONTROL_FILE_SET_PROTOCOL
from eom_orchestrator.similarity_context_artifact import SIMILARITY_CONTEXT_ARTIFACT_TYPE
from eom_orchestrator.similarity_materialization import (
    SimilarityMaterializationReadPort,
    SimilarityWorkspaceMaterials,
)
from eom_workflow.similarity_control import (
    SupportedSimilarityExecutionPlan,
    parse_supported_similarity_execution_plan,
    validate_similarity_original_source,
    validate_similarity_plan_context,
    validate_similarity_plan_request,
)
from jsonschema.exceptions import ValidationError as SchemaError
from sqlalchemy.orm import Session

from eom_workflow_runner.similarity_role_context import SimilaritySessionContextReader


class CatalogSimilarityMaterializationReader(SimilarityMaterializationReadPort):
    """Bound to the actual captured caller and common application, not model authority."""

    def __init__(
        self,
        caller: EmbeddingRegistryCaller,
        reader: SimilaritySessionContextReader,
        materials_reader: SimilarityMaterialsReadPort,
    ) -> None:
        if (
            not isinstance(caller, EmbeddingRegistryCaller)
            or not callable(getattr(reader, "compose_in_session", None))
            or not callable(getattr(materials_reader, "read_similarity_materials_in_session", None))
        ):
            raise ValueError("SIMILARITY_MATERIALIZATION_CONTEXT_INVALID")
        validate_embedding_registry_actor(caller)
        self.caller = caller
        self.reader = reader
        self.materials_reader = materials_reader

    def _current_context(
        self,
        session: Session,
        plan: SupportedSimilarityExecutionPlan,
        request: SimilarityContextRequest,
    ) -> SimilarityContext:
        try:
            current = parse_similarity_context(
                self.reader.compose_in_session(session, self.caller, request)
            )
            if current.status == "FAILED":
                if current.error_code in {"SOURCE_ACCESS_DENIED", "SOURCE_REVOKED"}:
                    raise ControlPlaneError(
                        "CONTROL_SIMILARITY_AUTHORITY_DENIED",
                        "similarity source authorization failed",
                    )
                if current.error_code == "AUTHORITY_UNAVAILABLE":
                    raise ControlPlaneError(
                        "CONTROL_SIMILARITY_AUTHORITY_UNAVAILABLE",
                        "current similarity reader unavailable",
                    )
            return validate_similarity_plan_context(plan, current)
        except (ValueError, TypeError, SchemaError):
            raise ControlPlaneError(
                "CONTROL_SIMILARITY_CONTEXT_INVALID", "current similarity result differs from plan"
            ) from None

    def resolve(
        self,
        session: Session,
        *,
        plan: SupportedSimilarityExecutionPlan,
        operator_id: str,
        request: SimilarityContextRequest,
        original_source: PopulationSource,
        canonical_artifact_root: Path,
        authorized_artifact_revision_ids: frozenset[str],
    ) -> SimilarityWorkspaceMaterials:
        """No model execution or writes; current common read before and after member IO."""
        checked = parse_supported_similarity_execution_plan(plan)
        validate_similarity_plan_request(checked, request)
        if operator_id != self.caller.operator_id:
            raise ControlPlaneError(
                "CONTROL_SIMILARITY_AUTHORITY_DENIED", "actual similarity caller differs"
            )
        pin = checked.similarity_delivery.context_member
        if pin.artifact_revision_id not in authorized_artifact_revision_ids:
            raise ControlPlaneError(
                "CONTROL_POINTER_PERMISSION_DENIED", "similarity member is not authorized"
            )
        first = self._current_context(session, checked, request)
        try:
            validate_similarity_original_source(checked, first, original_source)
        except (ValueError, TypeError, SchemaError):
            raise ControlPlaneError(
                "CONTROL_SIMILARITY_SOURCE_MISMATCH",
                "similarity anchor differs from original source",
            ) from None
        expected = canonical_json_bytes(first.model_dump(mode="json"))
        try:
            reader = PinnedArtifactReadContext(
                session, CatalogSettings(nas_artifact_root=canonical_artifact_root)
            )
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
            if member.payload != expected:
                raise ValueError("SIMILARITY_MATERIALIZATION_BYTES_INVALID")
            references = validate_similarity_materials(
                self.materials_reader.read_similarity_materials_in_session(
                    session, self.caller, first
                ),
                first,
            )
            late = self._current_context(session, checked, request)
            if late != first:
                raise ValueError("SIMILARITY_MATERIALIZATION_CURRENT_CHANGED")
            reader.revalidate_provenance()
            final_member = reader.read_pinned(**arguments)
            if final_member.payload != member.payload:
                raise ValueError("SIMILARITY_MATERIALIZATION_BYTES_CHANGED")
            return SimilarityWorkspaceMaterials(
                member.payload, canonical_json_bytes(references.model_dump(mode="json"))
            )
        except SimilarityContextReadError as error:
            if error.code in {"SOURCE_ACCESS_DENIED", "SOURCE_REVOKED"}:
                raise ControlPlaneError(
                    "CONTROL_SIMILARITY_AUTHORITY_DENIED", "reference source authorization failed"
                ) from None
            if error.code == "AUTHORITY_UNAVAILABLE":
                raise ControlPlaneError(
                    "CONTROL_SIMILARITY_AUTHORITY_UNAVAILABLE",
                    "reference source reader unavailable",
                ) from None
            raise ControlPlaneError(
                "CONTROL_SIMILARITY_CONTEXT_INVALID", "reference source projection differs"
            ) from None
        except (PinnedArtifactResolutionError, ValueError, TypeError, SchemaError):
            raise ControlPlaneError(
                "CONTROL_SIMILARITY_CONTEXT_INVALID", "similarity member or current scope is stale"
            ) from None
