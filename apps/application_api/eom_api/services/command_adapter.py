"""Application command adapter reusing established domain application services."""

from __future__ import annotations

import secrets
from typing import Any

from eom_api_contracts.content_packs import ActivateContentPackRequest
from eom_api_contracts.deliverables import CreateDeliverableRequest
from eom_api_contracts.items import ItemRetirementRequest, StructuredItemContentImportRequest
from eom_api_contracts.usage import CreateUsagePlanRequest, FulfillUsagePlanRequest
from eom_api_contracts.workflows import WorkflowActionRequest, WorkflowStartRequest
from eom_catalog_contracts import (
    CreateDeliverable,
    CreateUsagePlan,
    FulfillUsagePlan,
    ReviewedItemContentImportCommand,
)
from eom_catalog_service.content_pack_service import ContentPackService
from eom_catalog_service.registry_service import RegistryService
from eom_catalog_service.usage_service import UsageLedgerService
from eom_catalog_service.workflow_catalog import WorkflowCatalogService
from eom_operator_identity import ActorContext
from eom_orchestrator.database import build_session_factory, transaction
from eom_workflow import WorkflowRequest
from eom_workflow_runner.errors import WorkflowError, WorkflowErrorCode
from eom_workflow_runner.models import WorkflowCommandRecord, WorkflowDefinitionRecord
from eom_workflow_runner.repository import (
    CommandType,
    active_approval,
    create_workflow_instance,
    enqueue_command,
)
from sqlalchemy import Engine, select

from eom_api.errors import ApiError
from eom_api.services.catalog_application_client import CatalogApplicationClient


def new_api_command_id() -> str:
    return f"apicmd_{secrets.token_hex(16)}"


class CommandAdapter:
    def __init__(
        self,
        engine: Engine,
        *,
        catalog_application: CatalogApplicationClient | None = None,
    ) -> None:
        self.engine = engine
        self.sessions = build_session_factory(engine)
        self.catalog = WorkflowCatalogService(engine)
        self.content_packs = ContentPackService(engine)
        self.registry = RegistryService(engine)
        self.catalog_application = catalog_application or CatalogApplicationClient()
        self.usage = UsageLedgerService(engine)

    def start_workflow(
        self,
        request: WorkflowStartRequest,
        actor: ActorContext,
        *,
        idempotency_key: str,
    ) -> tuple[str, str, int]:
        request_data: dict[str, Any] = {
            "request_name": request.request_name,
            "image_mode": request.image_mode,
        }
        if request.pack_key is not None:
            knowledge_request = request.request_name == "KNOWLEDGE_ITEM_REQUEST"
            generated_request = request.request_name == "GENERATED_KNOWLEDGE_ITEM_REQUEST"
            request_data.update(
                {
                    "content_pack": {
                        "pack_key": request.pack_key,
                        "environment": request.environment,
                    },
                    "profiles": {
                        "authoring": (
                            "knowledge-authoring"
                            if knowledge_request
                            else (
                                "generated-knowledge-authoring"
                                if generated_request
                                else "authoring-default"
                            )
                        ),
                        "review": (
                            "knowledge-review"
                            if knowledge_request
                            else (
                                "generated-knowledge-review"
                                if generated_request
                                else "review-default"
                            )
                        ),
                        "image": (
                            "fixed-stimulus-review"
                            if knowledge_request
                            else (
                                "generated-stimulus-drawing"
                                if generated_request
                                else "image-placeholder"
                            )
                        ),
                        "registration": (
                            "structured-registration"
                            if knowledge_request
                            else (
                                "generated-structured-registration"
                                if generated_request
                                else "registration-default"
                            )
                        ),
                    },
                    "source_intake": {"batch_ids": list(request.source_intake_batch_ids)},
                    "registry_intent": {
                        "mode": request.registry_mode,
                        "item_id": request.item_id,
                        "base_revision_id": request.base_revision_id,
                    },
                }
            )
            if knowledge_request or generated_request:
                assert request.item_brief is not None
                request_data["item_brief"] = request.item_brief.model_dump(mode="json")
            if knowledge_request:
                assert request.stimulus_asset_key is not None
                request_data["stimulus_asset"] = {"asset_key": request.stimulus_asset_key}
        workflow_request = WorkflowRequest.model_validate(request_data)
        with transaction(self.sessions) as session:
            definition = session.scalar(
                select(WorkflowDefinitionRecord).where(
                    WorkflowDefinitionRecord.definition_key == request.definition_key,
                    WorkflowDefinitionRecord.definition_version == request.definition_version,
                    WorkflowDefinitionRecord.active.is_(True),
                )
            )
            if definition is None:
                raise ApiError(
                    404,
                    "WORKFLOW_DEFINITION_NOT_FOUND",
                    "Workflow definition not found",
                    "The requested active workflow definition does not exist.",
                )
            runtime_context = (
                self.catalog.bind_request(
                    workflow_request,
                    definition_key=definition.definition_key,
                    definition_version=definition.definition_version,
                )
                if workflow_request.content_pack is not None
                else None
            )
            workflow, created = create_workflow_instance(
                session,
                definition=definition,
                request=workflow_request,
                idempotency_key=idempotency_key,
                actor_type="human",
                actor_id=actor.actor_id,
                runtime_context=runtime_context,
            )
            command: WorkflowCommandRecord | None
            if created:
                command, _ = enqueue_command(
                    session,
                    workflow_id=workflow.workflow_id,
                    command_type=CommandType.START_WORKFLOW,
                    payload={},
                    actor_type="human",
                    actor_id=actor.actor_id,
                    source="application_api",
                    idempotency_key=f"start:{workflow.workflow_id}",
                )
            else:
                command = session.scalar(
                    select(WorkflowCommandRecord)
                    .where(
                        WorkflowCommandRecord.workflow_id == workflow.workflow_id,
                        WorkflowCommandRecord.command_type == CommandType.START_WORKFLOW.value,
                    )
                    .order_by(
                        WorkflowCommandRecord.created_at,
                        WorkflowCommandRecord.command_id,
                    )
                    .limit(1)
                )
                if command is None:
                    raise WorkflowError(
                        WorkflowErrorCode.WORKFLOW_CONCURRENCY_CONFLICT,
                        "existing workflow occurrence has no start command",
                    )
            assert command is not None
            command_id = command.command_id
            return command_id, workflow.workflow_id, workflow.lock_version

    def workflow_action(
        self,
        workflow_id: str,
        action: CommandType,
        request: WorkflowActionRequest,
        actor: ActorContext,
        *,
        expected_version: int,
        idempotency_key: str,
    ) -> tuple[str, int]:
        with transaction(self.sessions) as session:
            from eom_workflow_runner.models import WorkflowInstanceRecord

            workflow = session.scalar(
                select(WorkflowInstanceRecord)
                .where(WorkflowInstanceRecord.workflow_id == workflow_id)
                .with_for_update()
            )
            if workflow is None:
                raise ApiError(
                    404,
                    "WORKFLOW_NOT_FOUND",
                    "Workflow not found",
                    "The requested workflow does not exist.",
                )
            if workflow.lock_version != expected_version:
                self._version_mismatch()
            payload: dict[str, Any] = {}
            if action in {CommandType.APPROVE_WORKFLOW, CommandType.REQUEST_REWORK}:
                approval = active_approval(session, workflow_id)
                if approval is None:
                    raise ApiError(
                        409,
                        "WORKFLOW_APPROVAL_NOT_PENDING",
                        "Approval is not pending",
                        "The workflow does not have an active approval request.",
                    )
                payload.update(
                    {
                        "approval_request_id": approval.approval_request_id,
                        "approval_lock_version": approval.lock_version,
                    }
                )
            if request.reason:
                payload["reason"] = request.reason
            if action is CommandType.REQUEST_REWORK:
                payload["target"] = "authoring"
            command, _ = enqueue_command(
                session,
                workflow_id=workflow_id,
                command_type=action,
                payload=payload,
                actor_type="human",
                actor_id=actor.actor_id,
                source="application_api",
                idempotency_key=idempotency_key,
            )
            return command.command_id, workflow.lock_version

    def release_pack(
        self, release_id: str, actor: ActorContext, *, expected_version: int
    ) -> tuple[str, int]:
        self._check_pack_version(release_id, expected_version)
        row = self.content_packs.release(release_id, actor_id=actor.actor_id)
        return new_api_command_id(), row.lock_version

    def activate_pack(
        self,
        release_id: str,
        request: ActivateContentPackRequest,
        actor: ActorContext,
        *,
        expected_version: int,
    ) -> tuple[str, str, int]:
        self._check_pack_version(release_id, expected_version)
        row = self.content_packs.activate(
            release_id, environment=request.environment, actor_id=actor.actor_id
        )
        return new_api_command_id(), row.activation_id, row.lock_version

    def retire_item(
        self,
        item_id: str,
        request: ItemRetirementRequest,
        actor: ActorContext,
        *,
        expected_version: int,
    ) -> tuple[str, int]:
        from eom_catalog_service.models import ItemRecord

        self._check_version(ItemRecord, item_id, expected_version, "ITEM_NOT_FOUND")
        row = self.registry.retire(item_id, actor_id=actor.actor_id, reason=request.reason)
        return new_api_command_id(), row.lock_version

    def import_structured_item_content(
        self,
        base_revision_id: str,
        request: StructuredItemContentImportRequest,
        actor: ActorContext,
        *,
        expected_version: int,
    ) -> tuple[str, str, int]:
        result = self.catalog_application.import_reviewed(
            ReviewedItemContentImportCommand(
                base_revision_id=base_revision_id,
                expected_version=expected_version,
                reviewed_by=actor.actor_id,
                review_reason=request.review_reason,
                content=request.content,
            )
        )
        return new_api_command_id(), result.item_revision_id, result.resource_version

    def create_deliverable(
        self, request: CreateDeliverableRequest, actor: ActorContext
    ) -> tuple[str, str, int]:
        row, revision = self.usage.create_deliverable(
            CreateDeliverable(**request.model_dump(), metadata={}, actor_id=actor.actor_id)
        )
        return new_api_command_id(), row.deliverable_id, revision.revision_number

    def create_usage_plan(
        self, request: CreateUsagePlanRequest, actor: ActorContext
    ) -> tuple[str, str, int]:
        row = self.usage.create_plan(
            CreateUsagePlan(**request.model_dump(), actor_id=actor.actor_id)
        )
        return new_api_command_id(), row.usage_plan_id, row.lock_version

    def reserve_usage_plan(
        self, plan_id: str, actor: ActorContext, *, expected_version: int
    ) -> tuple[str, int]:
        from eom_catalog_service.models import UsagePlanRecord

        self._check_version(UsagePlanRecord, plan_id, expected_version, "USAGE_PLAN_NOT_FOUND")
        row = self.usage.reserve(plan_id, actor_id=actor.actor_id)
        return new_api_command_id(), row.lock_version

    def cancel_usage_plan(
        self, plan_id: str, actor: ActorContext, *, expected_version: int
    ) -> tuple[str, int]:
        from eom_catalog_service.models import UsagePlanRecord

        self._check_version(UsagePlanRecord, plan_id, expected_version, "USAGE_PLAN_NOT_FOUND")
        row = self.usage.cancel(plan_id, actor_id=actor.actor_id)
        return new_api_command_id(), row.lock_version

    def fulfill_usage_plan(
        self,
        plan_id: str,
        request: FulfillUsagePlanRequest,
        actor: ActorContext,
        *,
        expected_version: int,
    ) -> tuple[str, str, int]:
        from eom_catalog_service.models import UsagePlanRecord

        self._check_version(UsagePlanRecord, plan_id, expected_version, "USAGE_PLAN_NOT_FOUND")
        row = self.usage.fulfill(
            FulfillUsagePlan(
                usage_plan_id=plan_id,
                actor_id=actor.actor_id,
                page=request.page,
                usage_role=request.usage_role,
                metadata={},
            )
        )
        return new_api_command_id(), row.usage_record_id, expected_version + 1

    def _check_pack_version(self, release_id: str, expected_version: int) -> None:
        from eom_catalog_service.models import ContentPackReleaseRecord

        self._check_version(
            ContentPackReleaseRecord,
            release_id,
            expected_version,
            "CONTENT_PACK_NOT_FOUND",
        )

    def _check_version(
        self, model: Any, identifier: str, expected: int, not_found_code: str
    ) -> None:
        with self.sessions() as session:
            row = session.get(model, identifier)
            if row is None:
                raise ApiError(
                    404,
                    not_found_code,
                    "Resource not found",
                    "The requested resource does not exist.",
                )
            if row.lock_version != expected:
                self._version_mismatch()

    @staticmethod
    def _version_mismatch() -> None:
        raise ApiError(
            412,
            "API_PRECONDITION_FAILED",
            "Precondition failed",
            "The resource has changed since it was read.",
        )
