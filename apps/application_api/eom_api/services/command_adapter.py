"""Application command adapter reusing established domain application services."""

from __future__ import annotations

import secrets
from typing import Any, Literal

from eom_api_contracts.content_packs import ActivateContentPackRequest
from eom_api_contracts.deliverables import CreateDeliverableRequest
from eom_api_contracts.items import ItemRetirementRequest, StructuredItemContentImportRequest
from eom_api_contracts.usage import CreateUsagePlanRequest, FulfillUsagePlanRequest
from eom_api_contracts.workflows import (
    ContentTeamItemBriefRequestV3,
    KnowledgeItemBriefRequestV2,
    WorkflowActionRequest,
    WorkflowStartRequest,
)
from eom_catalog_contracts import (
    CreateDeliverable,
    CreateItemProductionEvidenceCommand,
    CreateUsagePlan,
    EducationalRetrievalRequirement,
    FulfillUsagePlan,
    IntegratedScienceCurriculumContractError,
    IntegratedScienceCurriculumScope,
    ReviewedItemContentImportCommand,
    resolve_integrated_science_curriculum_scope,
)
from eom_catalog_service.content_pack_service import ContentPackService
from eom_catalog_service.registry_service import RegistryService
from eom_catalog_service.usage_service import UsageLedgerService
from eom_catalog_service.workflow_catalog import WorkflowCatalogService
from eom_identifiers import content_sha256
from eom_operator_identity import ActorContext
from eom_orchestrator.control_service import ResolvedPlanDependencyEvidence
from eom_orchestrator.database import build_session_factory, transaction
from eom_orchestrator.execution_resolver import (
    ExecutionStepRequirement,
    current_knowledge_backed_preset,
    resolve_execution_plan,
    resolve_knowledge_backed_execution_plan,
    validate_educational_retrieval_policy,
)
from eom_workflow import (
    AgentStep,
    ResolvedExecutionPlan,
    ResolvedExecutionPlanV3,
    WorkflowRequest,
    compile_definition_data,
)
from eom_workflow.control_plane import WorkerRole
from eom_workflow.schemas import result_schema_protocol
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


def _workflow_request_from_api(request: WorkflowStartRequest) -> WorkflowRequest:
    """Resolve presentation-only curriculum identity before any workflow side effect."""

    item_brief_data: dict[str, Any] | None = None
    curriculum_scope: IntegratedScienceCurriculumScope | None = None
    if request.item_brief is not None:
        item_brief_data = request.item_brief.model_dump(mode="json")
        if isinstance(
            request.item_brief,
            (KnowledgeItemBriefRequestV2, ContentTeamItemBriefRequestV3),
        ):
            item_brief_data.pop("curriculum_selected_unit_key")
            selected_unit_key = request.item_brief.curriculum_selected_unit_key
            if selected_unit_key is not None:
                try:
                    curriculum_scope = resolve_integrated_science_curriculum_scope(
                        selected_unit_key
                    )
                except IntegratedScienceCurriculumContractError as exc:
                    raise ApiError(
                        422,
                        "WORKFLOW_CURRICULUM_SELECTION_INVALID",
                        "Curriculum selection is invalid",
                        "The selected curriculum unit does not exist in the pinned outline.",
                    ) from exc
            item_brief_data["curriculum_scope"] = (
                curriculum_scope.model_dump(mode="json") if curriculum_scope is not None else None
            )
    retrieval_data = (
        request.educational_retrieval.model_dump(mode="json")
        if request.educational_retrieval is not None
        else None
    )
    if (
        isinstance(
            request.item_brief,
            (KnowledgeItemBriefRequestV2, ContentTeamItemBriefRequestV3),
        )
        and retrieval_data is not None
    ):
        if curriculum_scope is None:
            raise ApiError(
                422,
                "WORKFLOW_CURRICULUM_SELECTION_INVALID",
                "Curriculum selection is invalid",
                "Graph-grounded item authoring requires one curriculum selection.",
            )
        retrieval_data["curriculum_root_key"] = curriculum_scope.graph_root_stable_key
        retrieval_data["topic_keys"] = []
    if retrieval_data is not None:
        retrieval_data = EducationalRetrievalRequirement.model_validate(retrieval_data).model_dump(
            mode="json"
        )
    request_data: dict[str, Any] = {
        "request_name": request.request_name,
        "image_mode": request.image_mode,
        "execution_preset_key": request.execution_preset_key,
        "educational_retrieval": retrieval_data,
    }
    if request.pack_key is not None:
        knowledge_request = request.request_name == "KNOWLEDGE_ITEM_REQUEST"
        generated_request = request.request_name == "GENERATED_KNOWLEDGE_ITEM_REQUEST"
        content_team_request = isinstance(request.item_brief, ContentTeamItemBriefRequestV3)
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
                            "generated-knowledge-review" if generated_request else "review-default"
                        )
                    ),
                    "image": (
                        "fixed-stimulus-review"
                        if knowledge_request
                        else (
                            None
                            if content_team_request
                            else "generated-stimulus-drawing"
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
            assert item_brief_data is not None
            request_data["item_brief"] = item_brief_data
        if knowledge_request:
            assert request.stimulus_asset_key is not None
            request_data["stimulus_asset"] = {"asset_key": request.stimulus_asset_key}
    return WorkflowRequest.model_validate(request_data)


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
        workflow_request = _workflow_request_from_api(request)
        knowledge_preset = None
        knowledge_evidence = None
        preflight_definition_hash: str | None = None
        if workflow_request.educational_retrieval is not None:
            with self.sessions() as preflight_session:
                preflight_definition = preflight_session.scalar(
                    select(WorkflowDefinitionRecord).where(
                        WorkflowDefinitionRecord.definition_key == request.definition_key,
                        WorkflowDefinitionRecord.definition_version == request.definition_version,
                        WorkflowDefinitionRecord.active.is_(True),
                    )
                )
                if preflight_definition is None:
                    raise ApiError(
                        404,
                        "WORKFLOW_DEFINITION_NOT_FOUND",
                        "Workflow definition not found",
                        "The requested active workflow definition does not exist.",
                    )
                assert workflow_request.execution_preset_key is not None
                compiled_preflight = compile_definition_data(
                    preflight_definition.canonical_definition,
                    preflight_definition.source_path,
                    {"authoring", "image", "review", "item_management"},
                )
                role_protocols = {
                    result_schema_protocol(step.result_schema)
                    for step in compiled_preflight.definition.steps
                    if isinstance(step, AgentStep)
                }
                if len(role_protocols) != 1:
                    raise ApiError(
                        409,
                        "WORKFLOW_DEFINITION_INVALID",
                        "Workflow definition invalid",
                        "The workflow definition has inconsistent role protocols.",
                    )
                knowledge_preset = current_knowledge_backed_preset(
                    preflight_session,
                    preset_key=workflow_request.execution_preset_key,
                    workflow_role_schema_version=str(next(iter(role_protocols))),
                )
                validate_educational_retrieval_policy(
                    knowledge_preset, workflow_request.educational_retrieval
                )
                preflight_definition_hash = preflight_definition.definition_hash
            requester_role = self._knowledge_requester_role(actor)
            requester_permission_keys = tuple(
                sorted(permission.value for permission in actor.permissions)
            )
            command_value = {
                "operation": "CREATE_ITEM_PRODUCTION_EVIDENCE",
                "requirement": workflow_request.educational_retrieval.model_dump(mode="json"),
                "evidence_budget": knowledge_preset.retrieval_policy.maximum_budget.model_dump(
                    mode="json"
                ),
                "access_policy_revision_id": (
                    knowledge_preset.retrieval_policy.access_policy_revision_id
                ),
                "access_policy_sha256": knowledge_preset.retrieval_policy.access_policy_sha256,
                "requester_role": requester_role,
                "requester_permission_keys": list(requester_permission_keys),
                "requested_by": actor.actor_id,
            }
            evidence_command = CreateItemProductionEvidenceCommand(
                operation="CREATE_ITEM_PRODUCTION_EVIDENCE",
                requirement=workflow_request.educational_retrieval,
                evidence_budget=knowledge_preset.retrieval_policy.maximum_budget,
                access_policy_revision_id=(
                    knowledge_preset.retrieval_policy.access_policy_revision_id
                ),
                access_policy_sha256=knowledge_preset.retrieval_policy.access_policy_sha256,
                requester_role=requester_role,
                requester_permission_keys=requester_permission_keys,
                requested_by=actor.actor_id,
                idempotency_key=idempotency_key,
                submission_sha256=content_sha256(command_value),
            )
            knowledge_evidence = self.catalog_application.create_item_production_evidence(
                evidence_command
            )
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
            if (
                preflight_definition_hash is not None
                and definition.definition_hash != preflight_definition_hash
            ):
                raise ApiError(
                    409,
                    "WORKFLOW_DEFINITION_CHANGED",
                    "Workflow definition changed",
                    "The workflow definition changed during evidence resolution.",
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
                if workflow_request.execution_preset_key is not None:
                    if runtime_context is None:
                        raise ApiError(
                            409,
                            "CONTROL_PLAN_CONTEXT_MISSING",
                            "Execution plan context missing",
                            "The preset-backed request has no pinned Content Pack context.",
                        )
                    compiled = compile_definition_data(
                        definition.canonical_definition,
                        definition.source_path,
                        {"authoring", "image", "review", "item_management"},
                    )
                    requirements = tuple(
                        ExecutionStepRequirement(
                            step_key=step.key, role=WorkerRole(step.worker_role)
                        )
                        for step in compiled.definition.steps
                        if isinstance(step, AgentStep)
                    )
                    pack = runtime_context["content_pack"]
                    dependencies = ResolvedPlanDependencyEvidence(
                        workflow_id=workflow.workflow_id,
                        workflow_definition_key=definition.definition_key,
                        workflow_definition_version=definition.definition_version,
                        workflow_definition_sha256=definition.definition_hash,
                        workflow_role_schema_version=workflow.role_schema_version,
                        content_pack_release_id=str(pack["release_id"]),
                        content_pack_sha256=str(pack["release_sha256"]),
                        graph_snapshot_revision_id=(
                            knowledge_evidence.graph_snapshot.graph_snapshot_revision_id
                            if knowledge_evidence is not None
                            else None
                        ),
                        evidence_bundle_revision_id=(
                            knowledge_evidence.evidence_bundle_revision_id
                            if knowledge_evidence is not None
                            else None
                        ),
                    )
                    plan: ResolvedExecutionPlan | ResolvedExecutionPlanV3
                    if knowledge_evidence is not None:
                        assert knowledge_preset is not None
                        assert workflow_request.educational_retrieval is not None
                        plan = resolve_knowledge_backed_execution_plan(
                            session,
                            preset_revision_id=knowledge_preset.preset_revision_id,
                            requirement=workflow_request.educational_retrieval,
                            evidence=knowledge_evidence,
                            dependencies=dependencies,
                            steps=requirements,
                        )
                    else:
                        plan = resolve_execution_plan(
                            session,
                            preset_key=workflow_request.execution_preset_key,
                            dependencies=dependencies,
                            steps=requirements,
                        )
                    context = dict(workflow.runtime_context)
                    context["execution_plan"] = {
                        "plan_id": plan.plan_id,
                        "plan_sha256": plan.plan_sha256,
                        "preset_id": plan.preset_id,
                        "preset_revision_id": plan.preset_revision_id,
                    }
                    workflow.runtime_context = context
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

    @staticmethod
    def _knowledge_requester_role(
        actor: ActorContext,
    ) -> Literal["ADMIN", "EDITOR", "REVIEWER"]:
        from eom_operator_identity import PermissionKey

        if PermissionKey.KNOWLEDGE_GRAPH_RETRIEVE not in actor.permissions:
            raise ApiError(
                403,
                "KNOWLEDGE_RETRIEVAL_FORBIDDEN",
                "Knowledge retrieval forbidden",
                "The operator is not allowed to create graph-backed evidence.",
            )
        if actor.permissions == frozenset(PermissionKey):
            return "ADMIN"
        if PermissionKey.HWPX_BUILD_CREATE in actor.permissions:
            return "EDITOR"
        if PermissionKey.WORKFLOW_APPROVE in actor.permissions:
            return "REVIEWER"
        raise ApiError(
            403,
            "KNOWLEDGE_RETRIEVAL_ROLE_FORBIDDEN",
            "Knowledge retrieval role forbidden",
            "The operator role is not approved for graph-backed item production.",
        )

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
