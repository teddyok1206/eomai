"""Catalog current-source reads for one persisted creative Workflow and step."""

from __future__ import annotations

from eom_catalog_contracts.external_item_learning_authorization import (
    ExternalItemLearningAuthorizationErrorCode,
    ExternalItemLearningAuthorizationReply,
    ExternalItemLearningAuthorizationRequest,
)
from eom_identifiers import content_sha256
from eom_orchestrator.control_models import ResolvedExecutionPlanRecord
from eom_orchestrator.control_service import ControlPlaneError
from eom_orchestrator.database import build_session_factory
from eom_orchestrator.external_item_learning_execution import (
    validate_external_item_learning_execution_plan,
)
from eom_workflow.creative_learning_profile import creative_learning_profile
from eom_workflow.models import ExternalItemLearningWorkerRequest
from eom_workflow_runner.actor_authorization import OPERATOR_ACTOR_PATTERN
from eom_workflow_runner.models import WorkflowInstanceRecord, WorkflowStepRunRecord
from eom_workflow_runner.repository import load_persisted_workflow_request
from jsonschema.exceptions import ValidationError as SchemaError
from sqlalchemy import Engine
from sqlalchemy.exc import SQLAlchemyError

from eom_catalog_service.external_creative_learning_source import (
    CatalogExternalItemLearningSourceAuthorizer,
    ExternalCreativeLearningSourceError,
)
from eom_catalog_service.external_creative_learning_targets import (
    ExternalCreativeLearningTargetError,
)
from eom_catalog_service.external_item_preview_projection import (
    ExternalItemPreviewProjectionService,
)


class ExternalItemLearningAuthorizationServiceError(ValueError):
    def __init__(self, code: ExternalItemLearningAuthorizationErrorCode) -> None:
        self.code = code
        super().__init__(code)


class CatalogExternalItemLearningAuthorizationService:
    """Derive the actor from stored history; this never creates/claims/launches work."""

    def __init__(self, engine: Engine, preview: ExternalItemPreviewProjectionService) -> None:
        self.sessions = build_session_factory(engine)
        self.source = CatalogExternalItemLearningSourceAuthorizer(preview)

    def authorize(
        self, request: ExternalItemLearningAuthorizationRequest
    ) -> ExternalItemLearningAuthorizationReply:
        request = ExternalItemLearningAuthorizationRequest.model_validate(request)
        selected = request.selection
        try:
            with self.sessions.begin() as session:
                workflow = session.get(
                    WorkflowInstanceRecord, selected.workflow_id, populate_existing=True
                )
                step = session.get(
                    WorkflowStepRunRecord, selected.step_run_id, populate_existing=True
                )
                if workflow is None or step is None:
                    raise ValueError("stored creative role binding is missing")
                profile = creative_learning_profile(workflow.definition_version)
                if (
                    workflow.definition_key != "external-item-learning"
                    or workflow.role_schema_version != profile.role_protocol
                    or workflow.created_actor_type != "human"
                    or OPERATOR_ACTOR_PATTERN.fullmatch(workflow.created_actor_id) is None
                    or workflow.stage
                    not in {"KNOWLEDGE_ANALYSIS", "COMPLETED", "FAILED", "CANCELLED"}
                    or step.workflow_id != workflow.workflow_id
                    or step.step_key != "extract"
                    or step.step_type != "agent"
                    or step.worker_role != "support"
                    or step.result_schema != profile.result_schema
                    or step.attempt != 1
                    or step.state not in {"READY", "RUNNING", "SUCCEEDED", "FAILED", "CANCELLED"}
                ):
                    raise ValueError("stored creative role binding differs")
                initial = load_persisted_workflow_request(workflow.initial_request)
                if initial != load_persisted_workflow_request(workflow.request_payload):
                    raise ValueError("creative original input changed")
                worker_request = initial.worker_request()
                if (
                    not isinstance(worker_request, ExternalItemLearningWorkerRequest)
                    or worker_request.work_input.request_sha256 != selected.work_input_sha256
                ):
                    raise ValueError("creative work input differs")
                plan = validate_external_item_learning_execution_plan(
                    session.get(
                        ResolvedExecutionPlanRecord, selected.plan_id, populate_existing=True
                    ),
                    workflow_id=workflow.workflow_id,
                    step_key=step.step_key,
                    request=worker_request,
                )
                if (
                    plan.plan_sha256 != selected.plan_sha256
                    or plan.workflow_definition_version != workflow.definition_version
                    or plan.workflow_definition_sha256 != workflow.definition_hash
                ):
                    raise ValueError("creative plan selection differs")
                original = worker_request.work_input.source
                current = self.source.reauthorize(
                    session, operator_id=workflow.created_actor_id, source=original
                )
                if current != original:
                    raise ValueError("creative source changed")
                return ExternalItemLearningAuthorizationReply(
                    schema_version="external-item-learning-authorization-reply/1.0",
                    operation="AUTHORIZE_EXTERNAL_ITEM_LEARNING_INPUT",
                    status="SUCCESS",
                    request_sha256=content_sha256(request.model_dump(mode="json")),
                    source_input_sha256=current.input_sha256,
                    error_code=None,
                )
        except ExternalCreativeLearningSourceError as exc:
            raise ExternalItemLearningAuthorizationServiceError(
                "EXTERNAL_CREATIVE_AUTHORIZATION_PERMISSION_DENIED"
                if exc.code == "EXTERNAL_CREATIVE_SOURCE_PERMISSION_DENIED"
                else "EXTERNAL_CREATIVE_AUTHORIZATION_SOURCE_STALE"
            ) from None
        except ExternalCreativeLearningTargetError:
            raise ExternalItemLearningAuthorizationServiceError(
                "EXTERNAL_CREATIVE_AUTHORIZATION_SOURCE_STALE"
            ) from None
        except SQLAlchemyError:
            raise ExternalItemLearningAuthorizationServiceError(
                "EXTERNAL_CREATIVE_AUTHORIZATION_UNAVAILABLE"
            ) from None
        except (ValueError, TypeError, KeyError, SchemaError, ControlPlaneError):
            raise ExternalItemLearningAuthorizationServiceError(
                "EXTERNAL_CREATIVE_AUTHORIZATION_BINDING_INVALID"
            ) from None
