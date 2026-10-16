"""Current authorized immutable Assembly read composed with the existing DOCUMENT owner."""

from __future__ import annotations

from eom_catalog_contracts import (
    MockExamAssemblyManifestV1,
    build_mock_exam_assembly_cohort,
)
from eom_catalog_contracts.exam_similarity_observation import ExamSimilarityObservation
from eom_catalog_contracts.exam_similarity_read import (
    ExamObservationReadErrorCode,
    ExamObservationReadRequest,
    ExamObservationReadSelection,
)
from eom_identity_service import OperatorAuthorizationFenceError
from eom_identity_service.models import OperatorRecord
from eom_identity_service.operator_authorization_fence import OperatorAuthorizationFence
from eom_identity_service.repository import effective_permissions
from eom_operator_identity import PermissionKey
from eom_orchestrator.database import build_session_factory
from jsonschema.exceptions import ValidationError as SchemaError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from eom_catalog_service.embedding_registry_catalog_adapter import CatalogEmbeddingRegistryVerifier
from eom_catalog_service.embedding_registry_ports import EmbeddingRegistryCaller
from eom_catalog_service.mock_exam_assembly_service import (
    MockExamAssemblyError,
    MockExamAssemblyService,
)
from eom_catalog_service.similarity_context_ports import SimilarityContextReadError


class ExamObservationReadError(ValueError):
    def __init__(self, code: ExamObservationReadErrorCode) -> None:
        self.code = code
        super().__init__(code)


class CatalogExamSimilarityReadService:
    """One caller/root/immutable selection; never creates an exam or submits a job."""

    def __init__(
        self, catalog: CatalogEmbeddingRegistryVerifier, identity: OperatorAuthorizationFence
    ) -> None:
        self.catalog, self.identity = catalog, identity
        self.sessions = build_session_factory(catalog.engine)

    def _authorize_assembly_read(self, session: Session, actor_id: str) -> None:
        self.identity.fence_current_operator(session, actor_id)
        operator = session.get(OperatorRecord, actor_id, populate_existing=True)
        if (
            operator is None
            or operator.status != "ACTIVE"
            or operator.deleted_at is not None
            or operator.must_change_password
            or PermissionKey.DELIVERABLE_READ not in effective_permissions(session, actor_id)
        ):
            raise ExamObservationReadError("SOURCE_ACCESS_DENIED")

    @staticmethod
    def _inspect_selection(session: Session, selection: ExamObservationReadSelection) -> None:
        manifest = MockExamAssemblyService.inspect_observation_source(
            session, selection.assembly_revision_id
        )
        if manifest is None:
            raise ExamObservationReadError("ASSEMBLY_REVISION_NOT_FOUND")
        value = manifest if isinstance(manifest, MockExamAssemblyManifestV1) else manifest.plan
        cohort = build_mock_exam_assembly_cohort(
            tuple(placement.item_revision_id for placement in value.placements)
        )
        request = selection.observation_request
        if (
            manifest.assessment_assembly_revision_id != selection.assembly_revision_id
            or manifest.manifest_sha256 != selection.assembly_manifest_sha256
            or cohort != request.cohort
        ):
            raise ExamObservationReadError("ASSEMBLY_OBSERVATION_PIN_MISMATCH")

    def read(self, request: ExamObservationReadRequest) -> ExamSimilarityObservation:
        request = ExamObservationReadRequest.model_validate(request)
        caller = EmbeddingRegistryCaller(request.actor_id)
        try:
            with self.sessions.begin() as session:
                root = session.get_transaction()
                self._authorize_assembly_read(session, request.actor_id)
                self._inspect_selection(session, request.selection)
                result = self.catalog.observe_exam_similarity_in_session(
                    session, caller, request.selection.observation_request
                )
                self._authorize_assembly_read(session, request.actor_id)
                self._inspect_selection(session, request.selection)
                if (
                    root is None
                    or not root.is_active
                    or session.get_transaction() is not root
                    or session.in_nested_transaction()
                ):
                    raise ExamObservationReadError("AUTHORITY_UNAVAILABLE")
                return result
        except ExamObservationReadError:
            raise
        except SimilarityContextReadError as error:
            raise ExamObservationReadError(error.code) from None
        except OperatorAuthorizationFenceError:
            raise ExamObservationReadError("AUTHORITY_UNAVAILABLE") from None
        except SQLAlchemyError:
            raise ExamObservationReadError("EXAM_OBSERVATION_UNAVAILABLE") from None
        except MockExamAssemblyError as error:
            raise ExamObservationReadError(
                "SOURCE_REVOKED"
                if error.code == "ASSEMBLY_REVISION_INELIGIBLE"
                else "ASSEMBLY_OBSERVATION_PIN_MISMATCH"
            ) from None
        except (ValueError, TypeError, KeyError, SchemaError):
            raise ExamObservationReadError("ASSEMBLY_OBSERVATION_PIN_MISMATCH") from None
