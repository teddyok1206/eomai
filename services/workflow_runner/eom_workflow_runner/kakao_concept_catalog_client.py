"""Narrow Catalog source read, composed with the existing Orchestrator Artifact reader."""

import grp
import pwd
from pathlib import Path

from eom_catalog_contracts import CATALOG_APPLICATION_SOCKET_PATH
from eom_catalog_contracts.kakao_concept_authorization import (
    CONCEPT_AUTHORIZATION_MAX_BYTES,
    KakaoConceptAuthorizationReply,
    KakaoConceptAuthorizationRequest,
)
from eom_identifiers import content_sha256
from eom_orchestrator.control_artifact_resolution import (
    ControlArtifactResolutionError,
    resolve_control_artifact_member,
)
from eom_orchestrator.control_models import ResolvedExecutionPlanRecord
from eom_orchestrator.control_service import ControlPlaneError
from eom_orchestrator.file_set_control_artifacts import ControlFileSetPublisher
from eom_orchestrator.general_chat_socket import (
    ChatSocketEndpoint,
    ChatTransportError,
    exchange_chat_frame,
)
from eom_orchestrator.kakao_concept_execution import KakaoConceptExecutionContext
from eom_orchestrator.kakao_concept_plan_resolution import validate_kakao_concept_execution_plan
from eom_workflow.kakao_concept_request import KakaoConceptWork, KakaoConceptWorkerRequest
from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import WorkflowInstanceRecord, WorkflowStepRunRecord


class CatalogKakaoConceptSourceReader:
    def __init__(
        self,
        selection: KakaoConceptAuthorizationRequest,
        work: KakaoConceptWork,
        *,
        endpoint: ChatSocketEndpoint | None = None,
    ) -> None:
        if selection.work_sha256 != content_sha256(work):
            raise ValueError("KAKAO_CONCEPT_AUTHORIZATION_INPUT_MISMATCH")
        self.selection, self.work, self.endpoint = selection, work, endpoint

    def __call__(self, work: KakaoConceptWork) -> None:
        try:
            if work != self.work:
                raise ValueError("concept input changed")
            endpoint = self.endpoint or ChatSocketEndpoint(
                Path(CATALOG_APPLICATION_SOCKET_PATH),
                pwd.getpwnam("eom-catalog-manager").pw_uid,
                grp.getgrnam("eom-api").gr_gid,
            )
            raw = exchange_chat_frame(
                endpoint,
                self.selection.model_dump(mode="json"),
                request_limit=CONCEPT_AUTHORIZATION_MAX_BYTES,
                reply_limit=CONCEPT_AUTHORIZATION_MAX_BYTES,
                timeout=30.0,
            )
            reply = KakaoConceptAuthorizationReply.model_validate(raw)
            reply.validate_for(self.selection)
            if reply.status != "SUCCESS":
                raise ControlPlaneError(
                    "CONTROL_KAKAO_CONCEPT_SOURCE_AUTHORIZATION_FAILED",
                    "Catalog rejected concept input",
                )
        except (OSError, KeyError, ChatTransportError) as error:
            raise ControlPlaneError(
                "CONTROL_KAKAO_CONCEPT_SOURCE_AUTHORITY_UNAVAILABLE",
                "Catalog concept reader unavailable",
            ) from error
        except (ValueError, TypeError, RecursionError) as error:
            raise ControlPlaneError(
                "CONTROL_KAKAO_CONCEPT_SOURCE_AUTHORIZATION_FAILED", "Catalog concept reply differs"
            ) from error


def prepare_kakao_concept_execution_context(
    session: Session,
    *,
    workflow: WorkflowInstanceRecord,
    step: WorkflowStepRunRecord,
    request: KakaoConceptWorkerRequest,
    publisher: ControlFileSetPublisher,
) -> KakaoConceptExecutionContext:
    if step.workflow_id != workflow.workflow_id:
        raise ControlPlaneError("CONTROL_KAKAO_CONCEPT_CONTEXT_INVALID", "concept step differs")
    plan = validate_kakao_concept_execution_plan(
        session.scalar(
            select(ResolvedExecutionPlanRecord).where(
                ResolvedExecutionPlanRecord.workflow_id == workflow.workflow_id
            )
        ),
        workflow_id=workflow.workflow_id,
        step_key=step.step_key,
        work=request.work_input,
    )
    reader = CatalogKakaoConceptSourceReader(
        KakaoConceptAuthorizationRequest(
            workflow_id=workflow.workflow_id,
            step_run_id=step.step_run_id,
            plan_id=plan.plan_id,
            plan_sha256=plan.plan_sha256,
            work_sha256=content_sha256(plan.work_input),
        ),
        request.work_input,
    )
    reader(request.work_input)
    try:
        payload = resolve_control_artifact_member(
            publisher.engine,
            request.work_input.request_member,
            maximum_bytes=request.work_input.request_bytes,
        )
        context = KakaoConceptExecutionContext(request.work_input, reader, payload)
    except (ControlArtifactResolutionError, ValueError) as error:
        raise ControlPlaneError(
            "CONTROL_KAKAO_CONCEPT_INPUT_UNAVAILABLE", "the exact private concept input is required"
        ) from error
    context.reauthorize(request)
    return context
