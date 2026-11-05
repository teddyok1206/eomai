"""Runner-only read port; Catalog derives actual owner from the saved role identity."""

import grp
import pwd
from pathlib import Path

from eom_catalog_contracts import CATALOG_APPLICATION_SOCKET_PATH
from eom_catalog_contracts.material_knowledge_analysis import KnowledgeAnalysisRequestV12
from eom_catalog_contracts.material_learning import MaterialArtifactMember
from eom_catalog_contracts.material_learning_authorization import (
    MATERIAL_AUTHORIZATION_MAX_BYTES,
    MaterialLearningAuthorizationReply,
    MaterialLearningAuthorizationRequest,
)
from eom_image_contracts.office_picture_uses import OfficePictureUseCatalog
from eom_orchestrator.control_artifact_resolution import resolve_control_artifact_member
from eom_orchestrator.control_models import ResolvedExecutionPlanRecord
from eom_orchestrator.control_service import ControlPlaneError
from eom_orchestrator.file_set_control_artifacts import ControlFileSetPublisher
from eom_orchestrator.general_chat_socket import (
    ChatSocketEndpoint,
    ChatTransportError,
    exchange_chat_frame,
)
from eom_orchestrator.material_learning_execution import (
    MaterialLearningExecutionContext,
    validate_material_learning_execution_plan,
)
from eom_protocol.artifact_members import ArtifactMemberPointer
from eom_workflow.control_plane import ResolvedExecutionPlanV34
from eom_workflow.material_learning_request import MaterialLearningWorkerRequest
from eom_workflow.models import KnowledgeAnalysisWorkerRequest
from sqlalchemy import select
from sqlalchemy.orm import Session

from eom_workflow_runner.models import WorkflowInstanceRecord, WorkflowStepRunRecord


class CatalogMaterialLearningSourceReader:
    def __init__(
        self,
        selection: MaterialLearningAuthorizationRequest,
        original: MaterialLearningWorkerRequest | KnowledgeAnalysisWorkerRequest,
        *,
        endpoint: ChatSocketEndpoint | None = None,
    ) -> None:
        self.selection = selection
        self.original = original
        self.endpoint = endpoint
        input_sha = (
            original.work_input.input_sha256
            if isinstance(original, MaterialLearningWorkerRequest)
            else original.analysis_request.request_sha256
        )
        if not isinstance(original, MaterialLearningWorkerRequest) and not isinstance(
            original.analysis_request, KnowledgeAnalysisRequestV12
        ):
            raise ValueError("MATERIAL_LEARNING_AUTHORIZATION_PURPOSE_INVALID")
        if selection.input_sha256 != input_sha:
            raise ValueError("MATERIAL_LEARNING_AUTHORIZATION_INPUT_MISMATCH")

    def __call__(
        self, request: MaterialLearningWorkerRequest | KnowledgeAnalysisWorkerRequest
    ) -> None:
        try:
            if request != self.original:
                raise ValueError("material source changed")
            endpoint = self.endpoint or ChatSocketEndpoint(
                Path(CATALOG_APPLICATION_SOCKET_PATH),
                pwd.getpwnam("eom-catalog-manager").pw_uid,
                grp.getgrnam("eom-api").gr_gid,
            )
            raw = exchange_chat_frame(
                endpoint,
                self.selection.model_dump(mode="json"),
                request_limit=MATERIAL_AUTHORIZATION_MAX_BYTES,
                reply_limit=MATERIAL_AUTHORIZATION_MAX_BYTES,
                timeout=30.0,
            )
            reply = MaterialLearningAuthorizationReply.model_validate(raw)
            reply.validate_for(self.selection)
            if reply.status != "SUCCESS":
                raise ControlPlaneError(
                    "CONTROL_MATERIAL_SOURCE_AUTHORIZATION_FAILED",
                    "Catalog rejected material input",
                )
        except (OSError, KeyError, ChatTransportError) as error:
            raise ControlPlaneError(
                "CONTROL_MATERIAL_SOURCE_AUTHORITY_UNAVAILABLE",
                "Catalog material reader unavailable",
            ) from error
        except (ValueError, TypeError, RecursionError) as error:
            raise ControlPlaneError(
                "CONTROL_MATERIAL_SOURCE_AUTHORIZATION_FAILED", "Catalog material reply differs"
            ) from error


def prepare_material_knowledge_source_reader(
    session: Session,
    *,
    workflow: WorkflowInstanceRecord,
    step: WorkflowStepRunRecord,
    request: KnowledgeAnalysisWorkerRequest,
) -> CatalogMaterialLearningSourceReader:
    if (
        not isinstance(request.analysis_request, KnowledgeAnalysisRequestV12)
        or step.workflow_id != workflow.workflow_id
    ):
        raise ControlPlaneError(
            "CONTROL_MATERIAL_CONTEXT_INVALID", "uploaded knowledge context differs"
        )
    row = session.scalar(
        select(ResolvedExecutionPlanRecord).where(
            ResolvedExecutionPlanRecord.workflow_id == workflow.workflow_id
        )
    )
    if row is None:
        raise ControlPlaneError("CONTROL_PLAN_MISSING", "uploaded knowledge plan missing")
    plan = ResolvedExecutionPlanV34.model_validate(row.canonical_document)
    if (
        plan.analysis_request_sha256 != request.analysis_request.request_sha256
        or plan.document_source != request.analysis_request.source
    ):
        raise ControlPlaneError(
            "CONTROL_MATERIAL_CONTEXT_INVALID", "uploaded knowledge source differs"
        )
    return CatalogMaterialLearningSourceReader(
        MaterialLearningAuthorizationRequest(
            workflow_id=workflow.workflow_id,
            step_run_id=step.step_run_id,
            plan_id=plan.plan_id,
            plan_sha256=plan.plan_sha256,
            input_sha256=request.analysis_request.request_sha256,
        ),
        request,
    )


def prepare_material_learning_execution_context(
    session: Session,
    *,
    workflow: WorkflowInstanceRecord,
    step: WorkflowStepRunRecord,
    request: MaterialLearningWorkerRequest,
    publisher: ControlFileSetPublisher,
) -> MaterialLearningExecutionContext:
    if step.workflow_id != workflow.workflow_id:
        raise ControlPlaneError("CONTROL_MATERIAL_CONTEXT_INVALID", "material step differs")
    plan = validate_material_learning_execution_plan(
        session.scalar(
            select(ResolvedExecutionPlanRecord).where(
                ResolvedExecutionPlanRecord.workflow_id == workflow.workflow_id
            )
        ),
        workflow_id=workflow.workflow_id,
        step_key=step.step_key,
        request=request,
    )

    def read_catalog(pointer: MaterialArtifactMember) -> OfficePictureUseCatalog:
        payload = resolve_control_artifact_member(
            publisher.engine,
            ArtifactMemberPointer(**pointer.model_dump(exclude={"bytes"})),
            maximum_bytes=8 * 1024 * 1024,
        )
        if len(payload) != pointer.bytes:
            raise ValueError("MATERIAL_LEARNING_OFFICE_CATALOG_SIZE_MISMATCH")
        return OfficePictureUseCatalog.model_validate_json(payload)

    return MaterialLearningExecutionContext(
        source_authorizer=CatalogMaterialLearningSourceReader(
            MaterialLearningAuthorizationRequest(
                workflow_id=workflow.workflow_id,
                step_run_id=step.step_run_id,
                plan_id=plan.plan_id,
                plan_sha256=plan.plan_sha256,
                input_sha256=request.work_input.input_sha256,
            ),
            request,
        ),
        catalog_reader=read_catalog,
    )
