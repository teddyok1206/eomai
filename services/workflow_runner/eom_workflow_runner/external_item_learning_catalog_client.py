"""Runner socket adapter: Catalog derives the actual creative task owner."""

from __future__ import annotations

import grp
import pwd
from pathlib import Path

from eom_catalog_contracts import CATALOG_APPLICATION_SOCKET_PATH
from eom_catalog_contracts.external_item_learning_authorization import (
    MAX_EXTERNAL_ITEM_LEARNING_AUTHORIZATION_BYTES,
    ExternalItemLearningAuthorizationReply,
    ExternalItemLearningAuthorizationRequest,
    ExternalItemLearningRoleSelection,
    validate_external_item_learning_authorization_reply,
)
from eom_orchestrator.control_models import ResolvedExecutionPlanRecord
from eom_orchestrator.control_service import ControlPlaneError
from eom_orchestrator.external_item_learning_execution import (
    ExternalItemLearningExecutionContext,
    validate_external_item_learning_execution_plan,
)
from eom_orchestrator.file_set_control_artifacts import ControlFileSetPublisher
from eom_orchestrator.general_chat_socket import (
    ChatSocketEndpoint,
    ChatTransportError,
    exchange_chat_frame,
)
from eom_workflow.models import ExternalItemLearningWorkerRequest
from jsonschema.exceptions import ValidationError as SchemaError
from sqlalchemy import select
from sqlalchemy.orm import Session

from eom_workflow_runner.models import WorkflowInstanceRecord, WorkflowStepRunRecord


class CatalogExternalItemLearningSourceReader:
    """Each check is a new bounded read; a previous success is never permission."""

    def __init__(
        self,
        selection: ExternalItemLearningRoleSelection,
        original_request: ExternalItemLearningWorkerRequest,
        *,
        endpoint: ChatSocketEndpoint | None = None,
    ) -> None:
        self.selection = ExternalItemLearningRoleSelection.model_validate(selection)
        self.original_request = ExternalItemLearningWorkerRequest.model_validate(
            original_request.model_dump(mode="json")
        )
        self.endpoint = endpoint
        if self.selection.work_input_sha256 != self.original_request.work_input.request_sha256:
            raise ValueError("EXTERNAL_CREATIVE_AUTHORIZATION_BINDING_INVALID")

    def __call__(self, request: ExternalItemLearningWorkerRequest) -> None:
        try:
            if request != self.original_request:
                raise ValueError("creative execution changed its input")
            wire = ExternalItemLearningAuthorizationRequest(
                schema_version="external-item-learning-authorization-request/1.0",
                operation="AUTHORIZE_EXTERNAL_ITEM_LEARNING_INPUT",
                selection=self.selection,
            )
            endpoint = self.endpoint or ChatSocketEndpoint(
                Path(CATALOG_APPLICATION_SOCKET_PATH),
                pwd.getpwnam("eom-catalog-manager").pw_uid,
                grp.getgrnam("eom-api").gr_gid,
            )
            raw = exchange_chat_frame(
                endpoint,
                wire.model_dump(mode="json"),
                request_limit=MAX_EXTERNAL_ITEM_LEARNING_AUTHORIZATION_BYTES,
                reply_limit=MAX_EXTERNAL_ITEM_LEARNING_AUTHORIZATION_BYTES,
                timeout=30.0,
            )
            reply = ExternalItemLearningAuthorizationReply.model_validate(raw)
            validate_external_item_learning_authorization_reply(
                wire,
                reply,
                expected_source_input_sha256=request.work_input.source.input_sha256,
            )
            if reply.status == "FAILED":
                raise ControlPlaneError(
                    "CONTROL_CREATIVE_SOURCE_AUTHORITY_UNAVAILABLE"
                    if reply.error_code == "EXTERNAL_CREATIVE_AUTHORIZATION_UNAVAILABLE"
                    else "CONTROL_CREATIVE_SOURCE_AUTHORIZATION_FAILED",
                    "Catalog current creative source authorization failed",
                )
        except (ChatTransportError, KeyError, OSError):
            raise ControlPlaneError(
                "CONTROL_CREATIVE_SOURCE_AUTHORITY_UNAVAILABLE", "Catalog source reader unavailable"
            ) from None
        except (ValueError, TypeError, SchemaError, RecursionError):
            raise ControlPlaneError(
                "CONTROL_CREATIVE_CONTEXT_INVALID", "Catalog creative source reply differs"
            ) from None


def prepare_external_item_learning_execution_context(
    session: Session,
    *,
    workflow: WorkflowInstanceRecord,
    step: WorkflowStepRunRecord,
    request: ExternalItemLearningWorkerRequest,
    publisher: ControlFileSetPublisher,
) -> ExternalItemLearningExecutionContext:
    """Pin local expectations; only the socket callback reauthorizes source reads."""

    if step.workflow_id != workflow.workflow_id:
        raise ControlPlaneError("CONTROL_CREATIVE_CONTEXT_INVALID", "creative step differs")
    plan = validate_external_item_learning_execution_plan(
        session.scalar(
            select(ResolvedExecutionPlanRecord).where(
                ResolvedExecutionPlanRecord.workflow_id == workflow.workflow_id
            )
        ),
        workflow_id=workflow.workflow_id,
        step_key=step.step_key,
        request=request,
    )
    return ExternalItemLearningExecutionContext(
        source_authorizer=CatalogExternalItemLearningSourceReader(
            ExternalItemLearningRoleSelection(
                workflow_id=workflow.workflow_id,
                step_run_id=step.step_run_id,
                plan_id=plan.plan_id,
                plan_sha256=plan.plan_sha256,
                work_input_sha256=request.work_input.request_sha256,
            ),
            request,
        ),
        page_publisher=publisher,
    )
