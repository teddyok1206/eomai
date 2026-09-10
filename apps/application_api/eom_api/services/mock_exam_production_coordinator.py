"""Resumable application coordinator for 25 independent one-Item workflows.

The coordinator owns no worker execution and no persistence adapter.  It issues typed commands to
the existing application boundaries and returns an immutable pointer-only checkpoint after each
reconciliation pass.  A caller may persist that checkpoint at its own validated boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal, Never, Protocol, cast

from eom_api_contracts.assessment_assemblies import (
    CreatePlannedMockExamAssemblyRequest,
    MockExamAssemblyViewV2,
    MockExamAssemblyViewV3,
    PreviewMockExamAssemblyPlanRequest,
)
from eom_api_contracts.hwpx import AssessmentHwpxBuildView
from eom_api_contracts.knowledge_analysis import KnowledgeAnalysisRunView
from eom_api_contracts.mock_exam_execution import (
    MockExamAnalysisPointerV1,
    MockExamAnalysisPointerV3,
    MockExamAnalysisPolicyPointerV1,
    MockExamAnalysisReviewAuthorizationPointerV1,
    MockExamAnalysisReviewBindingPointerV1,
    MockExamAssemblyIntentV1,
    MockExamAssemblyPlanPointerV1,
    MockExamAssemblyPointerV1,
    MockExamExplicitAnalysisReviewSetV1,
    MockExamExplicitRatingSetV1,
    MockExamGenerationBlockResolutionV1,
    MockExamGenerationBlockResolutionV3,
    MockExamGraphPublicationAuthorizationPointerV1,
    MockExamGraphPublicationInputV1,
    MockExamGraphPublicationPointerV1,
    MockExamGraphPublicationPointerV3,
    MockExamHwpxBuildPointerV1,
    MockExamHwpxBuildPointerV2,
    MockExamHwpxBuildPointerV3,
    MockExamItemRegistrationPointerV1,
    MockExamProductionExecutionV1,
    MockExamProductionExecutionV2,
    MockExamProductionExecutionV3,
    MockExamProductionFailureV1,
    MockExamProductionItemRunV1,
    MockExamProductionItemRunV2,
    MockExamProductionItemRunV3,
    MockExamRatingAuthorizationPointerV1,
    MockExamRatingPointerV1,
    MockExamRatingPolicyPointerV1,
    MockExamReviewEligibilityObservationV1,
    MockExamReviewEligibilityObservationV2,
    MockExamReviewEligibilityObservationV3,
    MockExamReviewPointerV1,
    MockExamReviewPointerV3,
    MockExamWorkflowKnowledgeProvenancePointerV1,
    MockExamWorkflowKnowledgeProvenancePointerV3,
    is_mock_exam_provenance_validation_recovery_candidate,
    mock_exam_production_state_from_pointers,
)
from eom_api_contracts.workflows import (
    ContentTeamItemBriefRequestV3,
    EducationalRetrievalIntentRequest,
    WorkflowActionRequest,
    WorkflowApprovalExpectationV1,
    WorkflowExpectedResolutionV1,
    WorkflowProductionOccurrenceV1,
    WorkflowStartRequest,
    WorkflowView,
)
from eom_catalog_contracts.application import (
    ApprovedItemKnowledgeAnalysisSelection,
    CreateKnowledgeAnalysisCommand,
    ReconcileKnowledgeAnalysisCommand,
    ReviewKnowledgeAnalysisCommand,
)
from eom_catalog_contracts.approved_item_graph_publication import (
    ApprovedItemGraphPublicationResult,
    PublishApprovedItemAnalysesCommand,
)
from eom_catalog_contracts.assessment_assembly import (
    MockExamAssemblyPlanV1,
    build_mock_exam_assembly_cohort,
    mock_exam_item_set_sha256,
    mock_exam_planned_placement_id,
)
from eom_catalog_contracts.curriculum import resolve_integrated_science_curriculum_scope
from eom_catalog_contracts.item_review import (
    InspectMockExamReviewEligibilityQuery,
    MockExamItemReviewPublicationResult,
    MockExamReviewEligibilityResult,
    MockExamReviewEligibilityResultV2,
    MockExamReviewEligibilityResultV3,
    MockExamTrustedEvidenceUsageReceiptPairV1,
    PublishMockExamItemReviewCommand,
)
from eom_catalog_contracts.knowledge import KnowledgeSourceClass
from eom_catalog_contracts.mock_exam_production_plan import (
    MockExamOneItemGenerationBlockV1,
    MockExamOneItemGenerationBlockV2,
    MockExamOneItemGenerationBlockV3,
    MockExamPlannedWorkflowCallV1,
    MockExamProductionPlanV1,
    MockExamProductionPlanV2,
    MockExamProductionPlanV3,
)
from eom_identifiers import content_sha256
from eom_operator_identity import ActorContext
from eom_workflow_runner.repository import CommandType


class MockExamProductionCoordinatorError(RuntimeError):
    """Stable local contract error; operational failures are recorded in checkpoints."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class WorkflowStartReceipt:
    command_id: str
    workflow_id: str
    resource_version: int


@dataclass(frozen=True)
class WorkflowApprovalReceipt:
    command_id: str
    resource_version: int


class GenerationBlockResolver(Protocol):
    def resolve_generation_block(
        self,
        block: (
            MockExamOneItemGenerationBlockV1
            | MockExamOneItemGenerationBlockV2
            | MockExamOneItemGenerationBlockV3
        ),
    ) -> MockExamGenerationBlockResolutionV1: ...


class ReviewEligibilityReader(Protocol):
    """Official read-only review/approval evidence boundary; no DB shortcut is permitted."""

    def review_eligibility(
        self,
        workflow_id: str,
        knowledge_provenance: MockExamWorkflowKnowledgeProvenancePointerV1 | None = None,
    ) -> MockExamReviewEligibilityObservationV1: ...


class TrustedEvidenceUsageReceiptVerifier(Protocol):
    """Infrastructure adapter that re-resolves compact receipt pointers from canonical DB rows."""

    def verify(
        self,
        *,
        receipts: MockExamTrustedEvidenceUsageReceiptPairV1,
        knowledge_provenance: MockExamWorkflowKnowledgeProvenancePointerV3,
    ) -> None: ...


class ReviewEligibilityCatalogPort(Protocol):
    def inspect_mock_exam_review_eligibility(
        self, query: InspectMockExamReviewEligibilityQuery
    ) -> MockExamReviewEligibilityResult: ...


class CatalogReviewEligibilityReader:
    """Project the official Catalog review/approval observation into API contracts."""

    def __init__(
        self,
        catalog: ReviewEligibilityCatalogPort,
        trusted_receipts: TrustedEvidenceUsageReceiptVerifier | None = None,
    ) -> None:
        self._catalog = catalog
        self._trusted_receipts = trusted_receipts

    def review_eligibility(
        self,
        workflow_id: str,
        knowledge_provenance: MockExamWorkflowKnowledgeProvenancePointerV1 | None = None,
    ) -> MockExamReviewEligibilityObservationV1:
        result = self._catalog.inspect_mock_exam_review_eligibility(
            InspectMockExamReviewEligibilityQuery(workflow_id=workflow_id)
        )
        if result.workflow_id != workflow_id:
            raise MockExamProductionCoordinatorError(
                "WORKFLOW_REVIEW_POINTER_MISMATCH",
                "Catalog returned review evidence for another Workflow",
            )
        if isinstance(result, MockExamReviewEligibilityResultV3):
            if (
                not isinstance(knowledge_provenance, MockExamWorkflowKnowledgeProvenancePointerV3)
                or self._trusted_receipts is None
            ):
                raise MockExamProductionCoordinatorError(
                    "WORKFLOW_TRUSTED_RAG_RECEIPT_INVALID",
                    "trusted-RAG review evidence has no exact provenance resolver",
                )
            try:
                self._trusted_receipts.verify(
                    receipts=result.trusted_evidence_usage_receipts,
                    knowledge_provenance=knowledge_provenance,
                )
            except Exception as exc:
                raise MockExamProductionCoordinatorError(
                    "WORKFLOW_TRUSTED_RAG_RECEIPT_INVALID",
                    "trusted-RAG review evidence failed canonical resolution",
                ) from exc
            schema_version = "mock-exam-review-eligibility/3.0"
        elif isinstance(result, MockExamReviewEligibilityResultV2):
            schema_version = "mock-exam-review-eligibility/2.0"
        else:
            schema_version = "mock-exam-review-eligibility/1.0"
        observation_payload = {
            "schema_version": schema_version,
            "workflow_id": result.workflow_id,
            "workflow_resource_version": result.workflow_lock_version,
            "approval_request_id": result.approval_request_id,
            "approval_resource_version": result.approval_lock_version,
            "approval_state": result.approval_state,
            "reviewer_operator_id": result.reviewer_operator_id,
            "approved_at": result.approved_at,
            "eligibility": "ELIGIBLE" if result.eligible else "BLOCKED",
            "step_run_id": result.review_step_run_id,
            "artifact_id": result.review_artifact_id,
            "artifact_revision_id": result.review_artifact_revision_id,
            "sha256": result.review_sha256,
            "result_schema": result.review_result_schema,
            "worker_decision": result.decision,
            "finding_info_count": result.finding_counts.info,
            "finding_warning_count": result.finding_counts.warning,
            "finding_blocking_count": result.finding_counts.blocking,
            **(
                {
                    "trusted_evidence_usage_receipts": (
                        result.trusted_evidence_usage_receipts.model_dump(mode="json")
                    )
                }
                if isinstance(result, MockExamReviewEligibilityResultV3)
                else {}
            ),
        }
        if isinstance(result, MockExamReviewEligibilityResultV3):
            return MockExamReviewEligibilityObservationV3.model_validate(observation_payload)
        if isinstance(result, MockExamReviewEligibilityResultV2):
            return MockExamReviewEligibilityObservationV2.model_validate(observation_payload)
        return MockExamReviewEligibilityObservationV1.model_validate(observation_payload)


class WorkflowCommandAdapterPort(Protocol):
    def start_workflow(
        self,
        request: WorkflowStartRequest,
        actor: ActorContext,
        *,
        idempotency_key: str,
    ) -> tuple[str, str, int]: ...

    def workflow_action(
        self,
        workflow_id: str,
        action: CommandType,
        request: WorkflowActionRequest,
        actor: ActorContext,
        *,
        expected_version: int,
        idempotency_key: str,
    ) -> tuple[str, int]: ...


class WorkflowQueryAdapterPort(Protocol):
    def workflow(self, workflow_id: str) -> WorkflowView: ...


class OneItemWorkflowOperations(Protocol):
    def resolve_generation_block(
        self,
        block: (
            MockExamOneItemGenerationBlockV1
            | MockExamOneItemGenerationBlockV2
            | MockExamOneItemGenerationBlockV3
        ),
    ) -> MockExamGenerationBlockResolutionV1: ...

    def start(
        self,
        request: WorkflowStartRequest,
        actor: ActorContext,
        *,
        idempotency_key: str,
    ) -> WorkflowStartReceipt: ...

    def get(self, workflow_id: str) -> WorkflowView: ...

    def review_eligibility(
        self,
        workflow_id: str,
        knowledge_provenance: MockExamWorkflowKnowledgeProvenancePointerV1 | None = None,
    ) -> MockExamReviewEligibilityObservationV1: ...

    def approve(
        self,
        workflow_id: str,
        actor: ActorContext,
        *,
        expected_version: int,
        approval_request_id: str,
        approval_resource_version: int,
        idempotency_key: str,
    ) -> WorkflowApprovalReceipt: ...


class ExistingOneItemWorkflowOperations:
    """Concrete adapter over the current CommandAdapter and QueryAdapter boundaries."""

    def __init__(
        self,
        commands: WorkflowCommandAdapterPort,
        queries: WorkflowQueryAdapterPort,
        generation_blocks: GenerationBlockResolver,
        review_evidence: ReviewEligibilityReader,
    ) -> None:
        self._commands = commands
        self._queries = queries
        self._generation_blocks = generation_blocks
        self._review_evidence = review_evidence

    def resolve_generation_block(
        self,
        block: (
            MockExamOneItemGenerationBlockV1
            | MockExamOneItemGenerationBlockV2
            | MockExamOneItemGenerationBlockV3
        ),
    ) -> MockExamGenerationBlockResolutionV1:
        return self._generation_blocks.resolve_generation_block(block)

    def start(
        self,
        request: WorkflowStartRequest,
        actor: ActorContext,
        *,
        idempotency_key: str,
    ) -> WorkflowStartReceipt:
        command_id, workflow_id, version = self._commands.start_workflow(
            request,
            actor,
            idempotency_key=idempotency_key,
        )
        return WorkflowStartReceipt(command_id, workflow_id, version)

    def get(self, workflow_id: str) -> WorkflowView:
        return self._queries.workflow(workflow_id)

    def review_eligibility(
        self,
        workflow_id: str,
        knowledge_provenance: MockExamWorkflowKnowledgeProvenancePointerV1 | None = None,
    ) -> MockExamReviewEligibilityObservationV1:
        return self._review_evidence.review_eligibility(workflow_id, knowledge_provenance)

    def approve(
        self,
        workflow_id: str,
        actor: ActorContext,
        *,
        expected_version: int,
        approval_request_id: str,
        approval_resource_version: int,
        idempotency_key: str,
    ) -> WorkflowApprovalReceipt:
        command_id, version = self._commands.workflow_action(
            workflow_id,
            CommandType.APPROVE_WORKFLOW,
            WorkflowActionRequest(
                approval_expectation=WorkflowApprovalExpectationV1(
                    approval_request_id=approval_request_id,
                    approval_resource_version=approval_resource_version,
                )
            ),
            actor,
            expected_version=expected_version,
            idempotency_key=idempotency_key,
        )
        return WorkflowApprovalReceipt(command_id, version)


class AnalysisCatalogClientPort(Protocol):
    def create_knowledge_analysis(self, command: CreateKnowledgeAnalysisCommand) -> Any: ...

    def reconcile_knowledge_analysis(self, command: ReconcileKnowledgeAnalysisCommand) -> Any: ...

    def review_knowledge_analysis(self, command: ReviewKnowledgeAnalysisCommand) -> Any: ...


class AnalysisQueryPort(Protocol):
    def knowledge_analysis(self, analysis_run_id: str) -> KnowledgeAnalysisRunView: ...


class ApprovedItemAnalysisOperations(Protocol):
    def start(self, command: CreateKnowledgeAnalysisCommand) -> KnowledgeAnalysisRunView: ...

    def get(self, analysis_run_id: str) -> KnowledgeAnalysisRunView: ...

    def reconcile(self, command: ReconcileKnowledgeAnalysisCommand) -> KnowledgeAnalysisRunView: ...

    def review(self, command: ReviewKnowledgeAnalysisCommand) -> KnowledgeAnalysisRunView: ...


class CatalogApprovedItemAnalysisOperations:
    """Concrete adapter using Catalog application commands and API read projections."""

    def __init__(self, catalog: AnalysisCatalogClientPort, queries: AnalysisQueryPort) -> None:
        self._catalog = catalog
        self._queries = queries

    def start(self, command: CreateKnowledgeAnalysisCommand) -> KnowledgeAnalysisRunView:
        result = self._catalog.create_knowledge_analysis(command)
        return self._queries.knowledge_analysis(str(result.analysis_run_id))

    def get(self, analysis_run_id: str) -> KnowledgeAnalysisRunView:
        return self._queries.knowledge_analysis(analysis_run_id)

    def reconcile(self, command: ReconcileKnowledgeAnalysisCommand) -> KnowledgeAnalysisRunView:
        result = self._catalog.reconcile_knowledge_analysis(command)
        if str(result.analysis_run_id) != command.analysis_run_id:
            raise MockExamProductionCoordinatorError(
                "ANALYSIS_RECONCILE_POINTER_MISMATCH",
                "Catalog reconciled a different analysis run",
            )
        return self._queries.knowledge_analysis(command.analysis_run_id)

    def review(self, command: ReviewKnowledgeAnalysisCommand) -> KnowledgeAnalysisRunView:
        result = self._catalog.review_knowledge_analysis(command)
        if str(result.analysis_run_id) != command.analysis_run_id:
            raise MockExamProductionCoordinatorError(
                "ANALYSIS_REVIEW_POINTER_MISMATCH",
                "Catalog reviewed a different analysis run",
            )
        return self._queries.knowledge_analysis(command.analysis_run_id)


class ApprovedItemGraphOperations(Protocol):
    def publish(
        self, command: PublishApprovedItemAnalysesCommand
    ) -> ApprovedItemGraphPublicationResult: ...


class CatalogGraphApplicationPort(Protocol):
    def publish_approved_item_analyses(
        self, command: PublishApprovedItemAnalysesCommand
    ) -> ApprovedItemGraphPublicationResult: ...


class CatalogApprovedItemGraphOperations:
    def __init__(self, catalog: CatalogGraphApplicationPort) -> None:
        self._catalog = catalog

    def publish(
        self, command: PublishApprovedItemAnalysesCommand
    ) -> ApprovedItemGraphPublicationResult:
        return self._catalog.publish_approved_item_analyses(command)


class MockExamRatingOperations(Protocol):
    def publish(
        self, command: PublishMockExamItemReviewCommand
    ) -> MockExamItemReviewPublicationResult: ...


class MockExamRatingApplicationPort(Protocol):
    def publish_mock_exam_item_review(
        self, command: PublishMockExamItemReviewCommand
    ) -> MockExamItemReviewPublicationResult: ...


class CatalogMockExamRatingOperations:
    def __init__(self, catalog: MockExamRatingApplicationPort) -> None:
        self._catalog = catalog

    def publish(
        self, command: PublishMockExamItemReviewCommand
    ) -> MockExamItemReviewPublicationResult:
        return self._catalog.publish_mock_exam_item_review(command)


class AssemblyCommandPort(Protocol):
    def create_planned_mock_exam_assembly(
        self, request: CreatePlannedMockExamAssemblyRequest, actor: ActorContext
    ) -> tuple[str, str, int]: ...


class AssemblyQueryPort(Protocol):
    def mock_exam_assembly_plan(
        self, request: PreviewMockExamAssemblyPlanRequest
    ) -> MockExamAssemblyPlanV1: ...

    def mock_exam_assembly(self, assembly_revision_id: str) -> Any: ...


class MockExamAssemblyOperations(Protocol):
    def preview(self, request: PreviewMockExamAssemblyPlanRequest) -> MockExamAssemblyPlanV1: ...

    def create(
        self,
        request: CreatePlannedMockExamAssemblyRequest,
        actor: ActorContext,
        *,
        idempotency_key: str,
    ) -> MockExamAssemblyViewV2 | MockExamAssemblyViewV3: ...


class ExistingMockExamAssemblyOperations:
    """Concrete current planner/assembly adapter; creation is content-addressed underneath."""

    def __init__(self, commands: AssemblyCommandPort, queries: AssemblyQueryPort) -> None:
        self._commands = commands
        self._queries = queries

    def preview(self, request: PreviewMockExamAssemblyPlanRequest) -> MockExamAssemblyPlanV1:
        return self._queries.mock_exam_assembly_plan(request)

    def create(
        self,
        request: CreatePlannedMockExamAssemblyRequest,
        actor: ActorContext,
        *,
        idempotency_key: str,
    ) -> MockExamAssemblyViewV2 | MockExamAssemblyViewV3:
        del (
            idempotency_key
        )  # The existing assembly service replays by deterministic revision identity.
        _command_id, revision_id, _version = self._commands.create_planned_mock_exam_assembly(
            request, actor
        )
        result = self._queries.mock_exam_assembly(revision_id)
        if not isinstance(result, (MockExamAssemblyViewV2, MockExamAssemblyViewV3)):
            raise MockExamProductionCoordinatorError(
                "ASSEMBLY_SCHEMA_UNSUPPORTED",
                "planned assembly did not return a supported manifest family",
            )
        return result


class ExamHwpxServicePort(Protocol):
    def request_build(
        self,
        assembly_revision_id: str,
        *,
        operator_id: str,
        idempotency_key: str,
    ) -> tuple[Any, bool]: ...

    def get_build(self, build_id: str) -> Any: ...


class AssessmentHwpxOperations(Protocol):
    def start(
        self,
        assembly_revision_id: str,
        *,
        operator_id: str,
        idempotency_key: str,
    ) -> AssessmentHwpxBuildView: ...

    def get(self, build_id: str) -> AssessmentHwpxBuildView: ...


class ExistingAssessmentHwpxOperations:
    """Concrete adapter over ExamHwpxApplicationService with sanitized API projection."""

    def __init__(self, service: ExamHwpxServicePort) -> None:
        self._service = service

    def start(
        self,
        assembly_revision_id: str,
        *,
        operator_id: str,
        idempotency_key: str,
    ) -> AssessmentHwpxBuildView:
        from eom_api.services.hwpx_projection import project_assessment_hwpx_build

        record, _created = self._service.request_build(
            assembly_revision_id,
            operator_id=operator_id,
            idempotency_key=idempotency_key,
        )
        return project_assessment_hwpx_build(record)

    def get(self, build_id: str) -> AssessmentHwpxBuildView:
        from eom_api.services.hwpx_projection import project_assessment_hwpx_build

        return project_assessment_hwpx_build(self._service.get_build(build_id))


class MockExamProductionCoordinator:
    """Advance one immutable run through existing typed application boundaries."""

    def __init__(
        self,
        *,
        workflows: OneItemWorkflowOperations,
        analyses: ApprovedItemAnalysisOperations,
        graph: ApprovedItemGraphOperations,
        ratings: MockExamRatingOperations,
        assemblies: MockExamAssemblyOperations,
        hwpx: AssessmentHwpxOperations,
    ) -> None:
        self.workflows = workflows
        self.analyses = analyses
        self.graph = graph
        self.ratings = ratings
        self.assemblies = assemblies
        self.hwpx = hwpx

    @staticmethod
    def initialize(
        plan: MockExamProductionPlanV1,
        *,
        production_request_id: str,
        operator_id: str,
        at: datetime,
    ) -> MockExamProductionExecutionV1:
        if len(plan.workflow_calls) != 25:
            _raise("PRODUCTION_PLAN_ITEM_COUNT_INVALID", "production plan must have 25 calls")
        use_v3 = isinstance(plan, MockExamProductionPlanV3)
        row_type = MockExamProductionItemRunV3 if use_v3 else MockExamProductionItemRunV2
        rows = tuple(
            row_type(
                workflow_call_id=call.workflow_call_id,
                position=call.item_brief.mock_exam_slot.position,
                state="PLANNED",
                start_command_id=None,
                workflow_id=None,
                workflow_resource_version=None,
                knowledge_provenance=None,
                review=None,
                approval_command_id=None,
                human_approval=None,
                registration=None,
                analysis=None,
                graph_publication_id=None,
                rating=None,
                failure=None,
            )
            for call in plan.workflow_calls
        )
        execution_hash = content_sha256(
            {
                "production_request_id": production_request_id,
                "production_plan_id": plan.production_plan_id,
                "production_plan_sha256": plan.plan_sha256,
            }
        )
        return _new_checkpoint(
            execution_id="productionexec_" + execution_hash.removeprefix("sha256:")[:32],
            production_request_id=production_request_id,
            production_plan_id=plan.production_plan_id,
            production_plan_sha256=plan.plan_sha256,
            operator_id=operator_id,
            item_runs=rows,
            use_v2=True,
            use_v3=use_v3,
            at=at,
        )

    def advance_items(
        self,
        plan: MockExamProductionPlanV1,
        checkpoint: MockExamProductionExecutionV1,
        actor: ActorContext,
        *,
        at: datetime,
    ) -> MockExamProductionExecutionV1:
        _require_context(plan, checkpoint, actor)
        resolution = checkpoint.generation_block_resolution
        global_failure = checkpoint.failure
        changed = False
        if resolution is None:
            try:
                resolution = self.workflows.resolve_generation_block(plan.one_item_generation_block)
                _require_generation_resolution(plan.one_item_generation_block, resolution)
            except Exception as exc:
                failure = _failure(
                    exc,
                    stage="PREFLIGHT",
                    category="PIN_RESOLUTION_FAILED",
                    default_code="PRODUCTION_GENERATION_BLOCK_UNAVAILABLE",
                    retryable=True,
                    at=at,
                )
                if checkpoint.failure == failure:
                    return checkpoint
                return _advance_checkpoint(checkpoint, at=at, failure=failure)
            # Write-ahead pin: no Workflow side effect occurs until this exact resolution has
            # survived the runner's checkpoint CAS.
            return _advance_checkpoint(
                checkpoint,
                at=max(at, resolution.resolved_at),
                generation_block_resolution=resolution,
                failure=None,
            )
        elif global_failure is not None and global_failure.stage == "PREFLIGHT":
            global_failure = None
            changed = True

        calls = {call.workflow_call_id: call for call in plan.workflow_calls}
        if any(
            is_mock_exam_provenance_validation_recovery_candidate(row)
            for row in checkpoint.item_runs
        ):
            return self._recover_provenance_validation_cohort(
                checkpoint,
                calls,
                resolution,
                at=at,
            )
        rows: list[MockExamProductionItemRunV1] = []
        for row in checkpoint.item_runs:
            current = row
            if row.state in {"PLANNED", "START_UNCONFIRMED"}:
                call = calls[row.workflow_call_id]
                try:
                    receipt = self.workflows.start(
                        _workflow_request(
                            call,
                            plan.one_item_generation_block,
                            resolution,
                            checkpoint.production_request_id,
                        ),
                        actor,
                        idempotency_key=_operation_key(
                            checkpoint.execution_id, row.workflow_call_id, "start"
                        ),
                    )
                    current = _update_run(
                        row,
                        state="WORKFLOW_ACTIVE",
                        start_command_id=receipt.command_id,
                        workflow_id=receipt.workflow_id,
                        workflow_resource_version=receipt.resource_version,
                        failure=None,
                    )
                except Exception as exc:
                    current = _update_run(
                        row,
                        state="START_UNCONFIRMED",
                        failure=_failure(
                            exc,
                            stage="WORKFLOW_START",
                            category="OPERATION_OUTCOME_UNKNOWN",
                            default_code="WORKFLOW_START_OUTCOME_UNKNOWN",
                            retryable=True,
                            at=at,
                        ),
                    )
            rows.append(current)
            changed = changed or current != row

        observed: list[MockExamProductionItemRunV1] = []
        for row in rows:
            current = self._observe_workflow(
                row,
                calls[row.workflow_call_id],
                resolution,
                checkpoint.operator_id,
                actor,
                at=at,
            )
            observed.append(current)
            changed = changed or current != row
        if not changed:
            return checkpoint
        return _advance_checkpoint(
            checkpoint,
            at=at,
            generation_block_resolution=resolution,
            item_runs=tuple(observed),
            failure=global_failure,
        )

    def _recover_provenance_validation_cohort(
        self,
        checkpoint: MockExamProductionExecutionV1,
        calls: dict[str, MockExamPlannedWorkflowCallV1],
        resolution: MockExamGenerationBlockResolutionV1,
        *,
        at: datetime,
    ) -> MockExamProductionExecutionV1:
        """Reopen only the exact 25-row false-negative provenance incident.

        Every official Workflow view is read and validated before one pointer-only successor is
        returned.  This pass performs no start, review, or approval command; the runner's ordinary
        checkpoint CAS therefore makes recovery all-or-none and safely repeatable after a crash.
        """

        if checkpoint.failure is not None or not all(
            is_mock_exam_provenance_validation_recovery_candidate(row)
            for row in checkpoint.item_runs
        ):
            _raise(
                "PRODUCTION_PROVENANCE_RECOVERY_COHORT_INVALID",
                "provenance recovery requires the exact historical 25-Workflow failure cohort",
            )
        observations: list[
            tuple[
                MockExamProductionItemRunV1,
                WorkflowView,
                MockExamWorkflowKnowledgeProvenancePointerV1,
            ]
        ] = []
        recoverable_workflow_states = {
            "REQUESTED",
            "RUNNING",
            "REWORK_REQUESTED",
            "AWAITING_HUMAN_APPROVAL",
            "APPROVED",
            "REGISTERING",
            "COMPLETED",
        }
        for row in checkpoint.item_runs:
            call = calls[row.workflow_call_id]
            try:
                workflow = self.workflows.get(cast(str, row.workflow_id))
            except Exception as exc:
                raise MockExamProductionCoordinatorError(
                    _error_code(exc, "PRODUCTION_PROVENANCE_RECOVERY_OBSERVATION_UNAVAILABLE"),
                    "provenance recovery could not read an exact Workflow view",
                ) from exc
            if workflow.workflow_id != row.workflow_id:
                _raise(
                    "WORKFLOW_POINTER_MISMATCH",
                    "provenance recovery observed another Workflow identity",
                )
            if (
                row.workflow_resource_version is None
                or workflow.resource_version < row.workflow_resource_version
            ):
                _raise(
                    "WORKFLOW_RESOURCE_VERSION_REGRESSION",
                    "provenance recovery observed an older Workflow revision",
                )
            _require_workflow_resolution(workflow, resolution)
            provenance = _workflow_knowledge_provenance(workflow, resolution, call)
            if workflow.state not in recoverable_workflow_states:
                _raise(
                    "PRODUCTION_PROVENANCE_RECOVERY_WORKFLOW_STATE_INVALID",
                    "provenance recovery requires a supported non-failed Workflow lifecycle state",
                )
            observations.append((row, workflow, provenance))

        recovered = tuple(
            _update_run(
                row,
                state="WORKFLOW_ACTIVE",
                workflow_resource_version=workflow.resource_version,
                knowledge_provenance=provenance,
                failure=None,
            )
            for row, workflow, provenance in observations
        )
        return _advance_checkpoint(
            checkpoint,
            at=at,
            generation_block_resolution=resolution,
            item_runs=recovered,
            failure=None,
        )

    def _observe_workflow(
        self,
        row: MockExamProductionItemRunV1,
        call: MockExamPlannedWorkflowCallV1,
        resolution: MockExamGenerationBlockResolutionV1,
        operator_id: str,
        actor: ActorContext,
        *,
        at: datetime,
    ) -> MockExamProductionItemRunV1:
        if row.state == "FAILED" or row.workflow_id is None or row.registration is not None:
            return row
        try:
            workflow = self.workflows.get(row.workflow_id)
        except Exception as exc:
            return _update_run(
                row,
                state=(
                    "APPROVAL_UNCONFIRMED" if row.review is not None else "WORKFLOW_UNCONFIRMED"
                ),
                failure=_failure(
                    exc,
                    stage="WORKFLOW_EXECUTION",
                    category="RUNTIME_NOT_READY",
                    default_code="WORKFLOW_OBSERVATION_UNAVAILABLE",
                    retryable=True,
                    at=at,
                ),
            )
        if workflow.workflow_id != row.workflow_id:
            return _terminal_run_failure(
                row, "WORKFLOW_POINTER_MISMATCH", "ARTIFACT_INTEGRITY_FAILED", at
            )
        try:
            _require_workflow_resolution(workflow, resolution)
            provenance = _workflow_knowledge_provenance(workflow, resolution, call)
            if row.knowledge_provenance is not None and provenance != row.knowledge_provenance:
                raise MockExamProductionCoordinatorError(
                    "WORKFLOW_KNOWLEDGE_PROVENANCE_CHANGED",
                    "Workflow knowledge provenance changed after it was checkpointed",
                )
        except Exception as exc:
            return _terminal_run_failure(
                row,
                _error_code(exc, "WORKFLOW_ACCEPTED_RESOLUTION_INVALID"),
                "ARTIFACT_INTEGRITY_FAILED",
                at,
            )
        base = _update_run(
            row,
            workflow_resource_version=workflow.resource_version,
            knowledge_provenance=provenance,
        )
        if workflow.state in {"FAILED", "CANCELLED"}:
            return _terminal_run_failure(
                base,
                workflow.failure_code or "WORKFLOW_EXECUTION_FAILED",
                "WORKFLOW_EXECUTION_FAILED",
                at,
            )
        if workflow.state == "AWAITING_HUMAN_APPROVAL":
            if base.knowledge_provenance is None:
                return _update_run(
                    base,
                    state="REVIEW_BLOCKED",
                    failure=_fixed_failure(
                        "REVIEW_GATE",
                        "ARTIFACT_INTEGRITY_FAILED",
                        "WORKFLOW_KNOWLEDGE_PROVENANCE_MISSING",
                        False,
                        at,
                    ),
                )
            return self._approve_zero_blocking(base, workflow, actor, at=at)
        if workflow.state in {"APPROVED", "REGISTERING", "COMPLETED"}:
            try:
                if base.knowledge_provenance is None:
                    raise MockExamProductionCoordinatorError(
                        "WORKFLOW_KNOWLEDGE_PROVENANCE_MISSING",
                        "approved Workflow has no exact knowledge provenance",
                    )
                review_observation = (
                    self.workflows.review_eligibility(
                        workflow.workflow_id,
                        base.knowledge_provenance,
                    )
                    if isinstance(base, MockExamProductionItemRunV3)
                    else self.workflows.review_eligibility(workflow.workflow_id)
                )
                if (
                    review_observation.workflow_resource_version != workflow.resource_version
                    or review_observation.eligibility != "ELIGIBLE"
                    or review_observation.approval_state != "APPROVED"
                ):
                    raise MockExamProductionCoordinatorError(
                        "WORKFLOW_REVIEW_EVIDENCE_STALE",
                        "review evidence is not eligible at the observed Workflow revision",
                    )
                review = review_observation.approved_pointer()
                if row.review is not None and not _same_review_evidence(row.review, review):
                    raise MockExamProductionCoordinatorError(
                        "WORKFLOW_REVIEW_EVIDENCE_CHANGED",
                        "post-approval review differs from the submitted review",
                    )
                approval = review_observation.human_approval_pointer()
                if approval.reviewer_operator_id != operator_id:
                    raise MockExamProductionCoordinatorError(
                        "WORKFLOW_APPROVER_MISMATCH",
                        "Workflow was not approved by the production operator",
                    )
                base = _update_run(
                    base,
                    state="WORKFLOW_ACTIVE",
                    review=review,
                    human_approval=approval,
                    failure=None,
                )
            except Exception as exc:
                return _terminal_run_failure(
                    base,
                    _error_code(exc, "WORKFLOW_APPROVAL_EVIDENCE_INVALID"),
                    "ARTIFACT_INTEGRITY_FAILED",
                    at,
                )
        if workflow.state == "COMPLETED":
            if workflow.item_registration is None:
                return _terminal_run_failure(
                    base,
                    "WORKFLOW_REGISTRATION_POINTER_MISSING",
                    "REGISTRATION_FAILED",
                    at,
                )
            try:
                registration = MockExamItemRegistrationPointerV1.model_validate(
                    workflow.item_registration.model_dump(mode="json")
                )
                return _update_run(
                    base,
                    state="REGISTERED",
                    registration=registration,
                    failure=None,
                )
            except Exception:
                return _terminal_run_failure(
                    base,
                    "WORKFLOW_REGISTRATION_POINTER_INVALID",
                    "ARTIFACT_INTEGRITY_FAILED",
                    at,
                )
        if workflow.state in {"REQUESTED", "RUNNING", "REWORK_REQUESTED"}:
            if row.review is not None:
                if row.approval_command_id is not None:
                    return _update_run(
                        base,
                        state="APPROVAL_SUBMITTED",
                        failure=None,
                    )
                return _update_run(
                    base,
                    state="APPROVAL_UNCONFIRMED",
                    failure=(
                        row.failure
                        or _fixed_failure(
                            "HUMAN_APPROVAL",
                            "OPERATION_OUTCOME_UNKNOWN",
                            "WORKFLOW_APPROVAL_OUTCOME_UNKNOWN",
                            True,
                            at,
                        )
                    ),
                )
            return _update_run(
                base,
                state="WORKFLOW_ACTIVE",
                failure=None,
            )
        return base

    def _approve_zero_blocking(
        self,
        row: MockExamProductionItemRunV1,
        workflow: WorkflowView,
        actor: ActorContext,
        *,
        at: datetime,
    ) -> MockExamProductionItemRunV1:
        assert row.knowledge_provenance is not None
        try:
            observation = (
                self.workflows.review_eligibility(
                    workflow.workflow_id,
                    row.knowledge_provenance,
                )
                if isinstance(row, MockExamProductionItemRunV3)
                else self.workflows.review_eligibility(workflow.workflow_id)
            )
        except Exception as exc:
            return _update_run(
                row,
                state="REVIEW_BLOCKED",
                failure=_failure(
                    exc,
                    stage="REVIEW_GATE",
                    category="RUNTIME_NOT_READY",
                    default_code="WORKFLOW_REVIEW_ELIGIBILITY_UNAVAILABLE",
                    retryable=True,
                    at=at,
                ),
            )
        if observation.workflow_resource_version != workflow.resource_version:
            return _update_run(
                row,
                state="REVIEW_BLOCKED",
                failure=_fixed_failure(
                    "REVIEW_GATE",
                    "ARTIFACT_INTEGRITY_FAILED",
                    "WORKFLOW_REVIEW_EVIDENCE_STALE",
                    False,
                    at,
                ),
            )
        if observation.eligibility != "ELIGIBLE" or observation.finding_blocking_count:
            return _update_run(
                row,
                state="REVIEW_BLOCKED",
                review=None,
                failure=_fixed_failure(
                    "REVIEW_GATE",
                    "QUALITY_GATE_FAILED",
                    "WORKFLOW_REVIEW_HAS_BLOCKING_FINDINGS",
                    False,
                    at,
                ),
            )
        if observation.approval_state != "PENDING":
            return _update_run(
                row,
                state="APPROVAL_UNCONFIRMED",
                review=observation.approved_pointer(),
                failure=_fixed_failure(
                    "HUMAN_APPROVAL",
                    "OPERATION_OUTCOME_UNKNOWN",
                    "WORKFLOW_APPROVAL_STATE_UNCONFIRMED",
                    True,
                    at,
                ),
            )
        review = observation.approved_pointer()
        try:
            receipt = self.workflows.approve(
                workflow.workflow_id,
                actor,
                expected_version=workflow.resource_version,
                approval_request_id=observation.approval_request_id,
                approval_resource_version=observation.approval_resource_version,
                idempotency_key=_operation_key(
                    workflow.workflow_id,
                    row.workflow_call_id,
                    observation.approval_request_id,
                    str(observation.approval_resource_version),
                    review.artifact_revision_id,
                    "approve",
                ),
            )
        except Exception as exc:
            return _update_run(
                row,
                state="APPROVAL_UNCONFIRMED",
                review=review,
                failure=_failure(
                    exc,
                    stage="HUMAN_APPROVAL",
                    category="OPERATION_OUTCOME_UNKNOWN",
                    default_code="WORKFLOW_APPROVAL_OUTCOME_UNKNOWN",
                    retryable=True,
                    at=at,
                ),
            )
        return _update_run(
            row,
            state="APPROVAL_SUBMITTED",
            review=review,
            approval_command_id=receipt.command_id,
            workflow_resource_version=max(workflow.resource_version, receipt.resource_version),
            failure=None,
        )

    def advance_analyses(
        self,
        plan: MockExamProductionPlanV1,
        checkpoint: MockExamProductionExecutionV1,
        actor: ActorContext,
        policy: MockExamAnalysisPolicyPointerV1,
        *,
        at: datetime,
        general_knowledge_mode: Literal["DISABLED", "AUXILIARY_UNATTRIBUTED"] = (
            "AUXILIARY_UNATTRIBUTED"
        ),
    ) -> MockExamProductionExecutionV1:
        _require_context(plan, checkpoint, actor)
        if any(row.registration is None for row in checkpoint.item_runs):
            _raise("PRODUCTION_ITEMS_INCOMPLETE", "all 25 generated Items must be registered")
        if checkpoint.analysis_policy is None:
            # Write-ahead pin: persist policy and general-knowledge mode before any Catalog
            # analysis command can consume their deterministic idempotency keys.
            return _advance_checkpoint(
                checkpoint,
                at=at,
                analysis_policy=policy,
                analysis_general_knowledge_mode=general_knowledge_mode,
                failure=None,
            )
        pinned_policy = checkpoint.analysis_policy
        pinned_mode = cast(
            Literal["DISABLED", "AUXILIARY_UNATTRIBUTED"],
            checkpoint.analysis_general_knowledge_mode,
        )
        if pinned_policy != policy or pinned_mode != general_knowledge_mode:
            _raise(
                "PRODUCTION_ANALYSIS_POLICY_MISMATCH",
                "resume input differs from the execution analysis policy or mode",
            )
        rows: list[MockExamProductionItemRunV1] = []
        changed = False
        for row in checkpoint.item_runs:
            current = row
            if row.analysis is None and row.state in {"REGISTERED", "ANALYSIS_UNCONFIRMED"}:
                assert row.registration is not None
                command = CreateKnowledgeAnalysisCommand(
                    source=ApprovedItemKnowledgeAnalysisSelection(
                        source_kind="APPROVED_ITEM_REVISION",
                        source_class="APPROVED_ITEM",
                        item_revision_id=row.registration.item_revision_id,
                    ),
                    preset_key="knowledge-analysis",
                    general_knowledge_mode=pinned_mode,
                    risk_policy_revision_id=pinned_policy.risk_policy_revision_id,
                    predecessor_analysis_run_id=None,
                    requested_by=actor.actor_id,
                    idempotency_key=_operation_key(
                        checkpoint.execution_id, row.workflow_call_id, "analysis"
                    ),
                )
                try:
                    view = self.analyses.start(command)
                    current = _analysis_run(row, view, pinned_policy, at)
                    if current.analysis is not None and view.state in {
                        "REQUESTED",
                        "RESOLVED",
                        "QUEUED",
                        "RUNNING",
                        "VALIDATING",
                    }:
                        reconciled = self.analyses.reconcile(
                            ReconcileKnowledgeAnalysisCommand(
                                analysis_run_id=view.analysis_run_id,
                                requested_by=actor.actor_id,
                            )
                        )
                        current = _analysis_run(current, reconciled, pinned_policy, at)
                except Exception as exc:
                    preserved_analysis = current.analysis if current is not row else None
                    current = _update_run(
                        row,
                        state="ANALYSIS_UNCONFIRMED",
                        analysis=preserved_analysis,
                        failure=_failure(
                            exc,
                            stage="ANALYSIS",
                            category="OPERATION_OUTCOME_UNKNOWN",
                            default_code="ANALYSIS_START_OUTCOME_UNKNOWN",
                            retryable=True,
                            at=at,
                        ),
                    )
            elif row.analysis is not None and row.analysis.state in {
                "REQUESTED",
                "RESOLVED",
                "QUEUED",
                "RUNNING",
                "VALIDATING",
            }:
                try:
                    current = _analysis_run(
                        row,
                        self.analyses.reconcile(
                            ReconcileKnowledgeAnalysisCommand(
                                analysis_run_id=row.analysis.analysis_run_id,
                                requested_by=actor.actor_id,
                            )
                        ),
                        pinned_policy,
                        at,
                    )
                except Exception as exc:
                    current = _update_run(
                        row,
                        state="ANALYSIS_UNCONFIRMED",
                        failure=_failure(
                            exc,
                            stage="ANALYSIS",
                            category="RUNTIME_NOT_READY",
                            default_code="ANALYSIS_OBSERVATION_UNAVAILABLE",
                            retryable=True,
                            at=at,
                        ),
                    )
            rows.append(current)
            changed = changed or current != row
        if not changed:
            return checkpoint
        return _advance_checkpoint(
            checkpoint,
            at=at,
            analysis_policy=pinned_policy,
            analysis_general_knowledge_mode=pinned_mode,
            item_runs=tuple(rows),
            failure=None,
        )

    def review_analyses(
        self,
        plan: MockExamProductionPlanV1,
        checkpoint: MockExamProductionExecutionV1,
        actor: ActorContext,
        review_set: MockExamExplicitAnalysisReviewSetV1,
        policy: MockExamAnalysisPolicyPointerV1,
        *,
        at: datetime,
    ) -> MockExamProductionExecutionV1:
        """Apply only caller-authorized decisions to the exact runs awaiting human review."""

        _require_context(plan, checkpoint, actor)
        if checkpoint.analysis_policy != policy:
            _raise(
                "PRODUCTION_ANALYSIS_POLICY_MISMATCH",
                "analysis review must use the execution's pinned risk policy",
            )
        if (
            review_set.execution_id != checkpoint.execution_id
            or review_set.operator_id != checkpoint.operator_id
            or review_set.operator_id != actor.actor_id
        ):
            _raise(
                "PRODUCTION_ANALYSIS_REVIEW_OPERATOR_MISMATCH",
                "analysis review set must be an explicit decision by the production operator",
            )
        if review_set.authorized_at < checkpoint.created_at or review_set.authorized_at > at:
            _raise(
                "PRODUCTION_ANALYSIS_REVIEW_TIME_INVALID",
                "analysis review authorization must fall within the execution timeline",
            )
        reviewable = tuple(
            row
            for row in checkpoint.item_runs
            if row.analysis is not None and row.analysis.state == "NEEDS_REVIEW"
        )
        expected = tuple(
            (
                row.workflow_call_id,
                row.position,
                cast(MockExamAnalysisPointerV1, row.analysis).analysis_run_id,
                cast(MockExamAnalysisPointerV1, row.analysis).resource_version,
            )
            for row in reviewable
        )
        supplied = tuple(
            (
                row.workflow_call_id,
                row.position,
                row.analysis_run_id,
                row.expected_resource_version,
            )
            for row in review_set.assignments
        )
        authorization = MockExamAnalysisReviewAuthorizationPointerV1(
            decision_set_sha256=review_set.decision_set_sha256,
            reviewer_operator_id=review_set.operator_id,
            authorized_at=review_set.authorized_at,
            bindings=tuple(
                MockExamAnalysisReviewBindingPointerV1(
                    workflow_call_id=row.workflow_call_id,
                    position=row.position,
                    analysis_run_id=row.analysis_run_id,
                    expected_resource_version=row.expected_resource_version,
                    decision=row.decision,
                )
                for row in review_set.assignments
            ),
        )
        previous_authorizations = checkpoint.analysis_review_authorizations
        pinned = previous_authorizations[-1] if previous_authorizations else None
        if pinned is None or pinned.decision_set_sha256 != review_set.decision_set_sha256:
            if not expected or supplied != expected:
                _raise(
                    "PRODUCTION_ANALYSIS_REVIEW_SET_MISMATCH",
                    "explicit decisions must exactly cover the current review-required analyses",
                )
            if pinned is not None and _analysis_review_authorization_is_pending(checkpoint, pinned):
                _raise(
                    "PRODUCTION_ANALYSIS_REVIEW_AUTHORIZATION_MISMATCH",
                    "a different analysis review set is already pinned and pending",
                )
            # Write-ahead pin: no review command is issued until the exact self-hashed decision
            # set and its run/version bindings survive the runner's checkpoint CAS.
            return _advance_checkpoint(
                checkpoint,
                at=max(at, authorization.authorized_at),
                analysis_review_authorizations=(*previous_authorizations, authorization),
                failure=None,
            )
        if pinned != authorization:
            _raise(
                "PRODUCTION_ANALYSIS_REVIEW_AUTHORIZATION_MISMATCH",
                "resume input differs from the pinned analysis review authorization",
            )
        _require_pinned_analysis_review_bindings(checkpoint, authorization)
        if not reviewable:
            return checkpoint
        assignments = {row.workflow_call_id: row for row in review_set.assignments}
        rows: list[MockExamProductionItemRunV1] = []
        changed = False
        for row in checkpoint.item_runs:
            assignment = assignments.get(row.workflow_call_id)
            if assignment is None:
                rows.append(row)
                continue
            assert row.analysis is not None
            if row.analysis.state != "NEEDS_REVIEW":
                rows.append(row)
                continue
            try:
                view = self.analyses.review(
                    ReviewKnowledgeAnalysisCommand(
                        analysis_run_id=assignment.analysis_run_id,
                        expected_version=assignment.expected_resource_version,
                        decision=assignment.decision,
                        notes=assignment.notes,
                        decided_by=actor.actor_id,
                        idempotency_key=_operation_key(
                            checkpoint.execution_id,
                            row.workflow_call_id,
                            assignment.analysis_run_id,
                            review_set.decision_set_sha256,
                            "analysis-review",
                        ),
                    )
                )
                current = _analysis_run(row, view, policy, at)
                expected_terminal = "ACCEPTED" if assignment.decision == "APPROVE" else "REJECTED"
                if current.analysis is None or current.analysis.state != expected_terminal:
                    raise MockExamProductionCoordinatorError(
                        "ANALYSIS_REVIEW_OUTCOME_UNCONFIRMED",
                        "analysis review has not exposed its exact terminal decision",
                    )
            except Exception as exc:
                current = _update_run(
                    row,
                    state="ANALYSIS_UNCONFIRMED",
                    failure=_failure(
                        exc,
                        stage="ANALYSIS",
                        category="OPERATION_OUTCOME_UNKNOWN",
                        default_code="ANALYSIS_REVIEW_OUTCOME_UNKNOWN",
                        retryable=True,
                        at=at,
                    ),
                )
            rows.append(current)
            changed = changed or current != row
        if not changed:
            return checkpoint
        return _advance_checkpoint(checkpoint, at=at, item_runs=tuple(rows), failure=None)

    def publish_next_graph_batch(
        self,
        plan: MockExamProductionPlanV1,
        checkpoint: MockExamProductionExecutionV1,
        actor: ActorContext,
        publication_input: MockExamGraphPublicationInputV1,
        *,
        at: datetime,
    ) -> MockExamProductionExecutionV1:
        _require_context(plan, checkpoint, actor)
        if not all(
            row.analysis is not None and row.analysis.state == "ACCEPTED"
            for row in checkpoint.item_runs
        ):
            _raise("PRODUCTION_ANALYSES_INCOMPLETE", "all 25 analyses must be accepted")
        latest_approval_at = max(
            (
                row.human_approval.approved_at
                for row in checkpoint.item_runs
                if row.human_approval is not None
            ),
            default=checkpoint.created_at,
        )
        earliest_authorization_at = max(
            checkpoint.created_at,
            latest_approval_at,
            actor.authentication_time,
        )
        if not earliest_authorization_at <= publication_input.authorized_at <= at:
            _raise(
                "PRODUCTION_GRAPH_AUTHORIZATION_TIME_INVALID",
                "Graph authorization must follow all approvals and current authentication",
            )
        authorization = MockExamGraphPublicationAuthorizationPointerV1.model_validate(
            publication_input.model_dump(mode="json")
        )
        if checkpoint.graph_publication_authorization is None:
            if authorization.supersedes_authorization_sha256 is not None:
                _raise(
                    "PRODUCTION_GRAPH_SUPERSESSION_INVALID",
                    "the first Graph authorization cannot supersede another authorization",
                )
            # The exact snapshot/policy/authorization must be durable before the atomic graph
            # mutation uses its deterministic execution key.
            return _advance_checkpoint(
                checkpoint,
                at=max(at, authorization.authorized_at),
                graph_publication_authorization=authorization,
                failure=None,
            )
        if checkpoint.graph_publication_authorization != authorization:
            previous_authorization = checkpoint.graph_publication_authorization
            stale_failure = checkpoint.failure
            if (
                checkpoint.graph_publications
                or stale_failure is None
                or stale_failure.stage != "GRAPH_PUBLICATION"
                or stale_failure.code != "KNOWLEDGE_GRAPH_STALE_CURRENT"
                or authorization.supersedes_authorization_sha256
                != previous_authorization.authorization_sha256
                or authorization.access_policy_revision_id
                != previous_authorization.access_policy_revision_id
                or authorization.access_policy_sha256 != previous_authorization.access_policy_sha256
            ):
                _raise(
                    "PRODUCTION_GRAPH_AUTHORIZATION_MISMATCH",
                    "resume input differs from the pinned Graph publication authorization",
                )
            # KNOWLEDGE_GRAPH_STALE_CURRENT is the only Catalog outcome that proves no Graph
            # publication committed. Persist the replacement authorization before retrying it.
            return _advance_checkpoint(
                checkpoint,
                at=max(at, authorization.authorized_at),
                graph_publication_authorization=authorization,
                failure=None,
            )
        if checkpoint.graph_publications:
            return checkpoint
        selected = checkpoint.item_runs
        run_ids = tuple(
            cast(MockExamAnalysisPointerV1, row.analysis).analysis_run_id for row in selected
        )
        workflow_ids = tuple(cast(str, row.workflow_id) for row in selected)
        item_revision_ids = tuple(
            cast(MockExamItemRegistrationPointerV1, row.registration).item_revision_id
            for row in selected
        )
        expected_snapshot_revision_id = publication_input.current_graph_snapshot_revision_id
        expected_snapshot_sha256 = publication_input.current_graph_snapshot_sha256
        unsigned: dict[str, object] = {
            "operation": "PUBLISH_APPROVED_ITEM_ANALYSES",
            "schema_version": "approved-item-graph-publication-command/1.0",
            "corpus_key": "integrated-science-textbooks",
            "expected_current_graph_snapshot_revision_id": expected_snapshot_revision_id,
            "expected_current_graph_snapshot_sha256": expected_snapshot_sha256,
            "accepted_analysis_run_ids": run_ids,
            "expected_workflow_ids": workflow_ids,
            "access_policy_revision_id": publication_input.access_policy_revision_id,
            "access_policy_sha256": publication_input.access_policy_sha256,
            "requested_by_operator_id": actor.actor_id,
            "authorized_at": publication_input.authorized_at.isoformat().replace("+00:00", "Z"),
        }
        command = PublishApprovedItemAnalysesCommand(
            operation="PUBLISH_APPROVED_ITEM_ANALYSES",
            schema_version="approved-item-graph-publication-command/1.0",
            corpus_key="integrated-science-textbooks",
            expected_current_graph_snapshot_revision_id=expected_snapshot_revision_id,
            expected_current_graph_snapshot_sha256=expected_snapshot_sha256,
            accepted_analysis_run_ids=run_ids,
            expected_workflow_ids=workflow_ids,
            access_policy_revision_id=publication_input.access_policy_revision_id,
            access_policy_sha256=publication_input.access_policy_sha256,
            requested_by_operator_id=actor.actor_id,
            authorized_at=publication_input.authorized_at,
            idempotency_key=_operation_key(
                checkpoint.execution_id,
                authorization.authorization_sha256,
                "graph",
            ),
            submission_sha256=content_sha256(unsigned),
        )
        try:
            result = self.graph.publish(command)
            if (
                result.accepted_analysis_run_ids != run_ids
                or result.expected_workflow_ids != workflow_ids
                or result.item_revision_ids != item_revision_ids
                or result.authorized_at != publication_input.authorized_at
                or result.previous_graph_snapshot_revision_id != expected_snapshot_revision_id
                or result.previous_graph_snapshot_sha256 != expected_snapshot_sha256
            ):
                _raise(
                    "PRODUCTION_GRAPH_PUBLICATION_POINTER_MISMATCH",
                    "Graph result differs from the exact generated batch",
                )
            publication_type = (
                MockExamGraphPublicationPointerV3
                if isinstance(checkpoint, MockExamProductionExecutionV3)
                else MockExamGraphPublicationPointerV1
            )
            pointer = publication_type(
                batch_number=1,
                publication_id=result.publication_id,
                previous_graph_snapshot_revision_id=(result.previous_graph_snapshot_revision_id),
                previous_graph_snapshot_sha256=result.previous_graph_snapshot_sha256,
                graph_snapshot_revision_id=(result.graph_snapshot.graph_snapshot_revision_id),
                graph_snapshot_sha256=result.graph_snapshot_sha256,
                access_policy_revision_id=publication_input.access_policy_revision_id,
                access_policy_sha256=publication_input.access_policy_sha256,
                analysis_run_ids=result.accepted_analysis_run_ids,
                workflow_ids=result.expected_workflow_ids,
                item_revision_ids=result.item_revision_ids,
                authorized_at=result.authorized_at,
                outcome=result.outcome,
                result_sha256=result.result_sha256,
                published_at=result.published_at,
            )
        except Exception as exc:
            return _advance_checkpoint(
                checkpoint,
                at=at,
                failure=_failure(
                    exc,
                    stage="GRAPH_PUBLICATION",
                    category="GRAPH_PUBLICATION_FAILED",
                    default_code="GRAPH_PUBLICATION_OUTCOME_UNKNOWN",
                    retryable=True,
                    at=at,
                ),
            )
        publication_by_item = set(pointer.item_revision_ids)
        rows = tuple(
            _update_run(
                row,
                state="GRAPH_PUBLISHED",
                graph_publication_id=pointer.publication_id,
                failure=None,
            )
            if row.registration is not None
            and row.registration.item_revision_id in publication_by_item
            else row
            for row in checkpoint.item_runs
        )
        return _advance_checkpoint(
            checkpoint,
            at=max(at, pointer.published_at),
            item_runs=rows,
            graph_publications=(pointer,),
            failure=None,
        )

    def publish_ratings(
        self,
        plan: MockExamProductionPlanV1,
        checkpoint: MockExamProductionExecutionV1,
        actor: ActorContext,
        rating_set: MockExamExplicitRatingSetV1,
        policy: MockExamRatingPolicyPointerV1,
        *,
        at: datetime,
    ) -> MockExamProductionExecutionV1:
        _require_context(plan, checkpoint, actor)
        if len(checkpoint.graph_publications) != 1:
            _raise("PRODUCTION_GRAPH_INCOMPLETE", "the atomic Graph publication is incomplete")
        if rating_set.execution_id != checkpoint.execution_id or (
            rating_set.operator_id != checkpoint.operator_id
            or rating_set.operator_id != actor.actor_id
        ):
            _raise(
                "PRODUCTION_RATING_OPERATOR_MISMATCH",
                "rating set must be an explicit decision by the production operator",
            )
        if rating_set.authorized_at > at or rating_set.authorized_at < checkpoint.created_at:
            _raise(
                "PRODUCTION_RATING_AUTHORIZATION_TIME_INVALID",
                "rating authorization must fall within the execution checkpoint timeline",
            )
        authorization = MockExamRatingAuthorizationPointerV1(
            decision_set_sha256=rating_set.decision_set_sha256,
            reviewer_operator_id=rating_set.operator_id,
            authorized_at=rating_set.authorized_at,
            rating_policy_revision_id=policy.rating_policy_revision_id,
            rating_policy_sha256=policy.rating_policy_sha256,
        )
        authorization_was_unpinned = checkpoint.rating_authorization is None
        if not authorization_was_unpinned and checkpoint.rating_authorization != authorization:
            _raise(
                "PRODUCTION_RATING_AUTHORIZATION_MISMATCH",
                "resume input differs from the pinned explicit rating authorization",
            )
        assignments = {row.workflow_call_id: row for row in rating_set.assignments}
        expected = tuple(
            (
                row.workflow_call_id,
                row.position,
                cast(MockExamItemRegistrationPointerV1, row.registration).item_revision_id,
            )
            for row in checkpoint.item_runs
        )
        supplied = tuple(
            (row.workflow_call_id, row.position, row.item_revision_id)
            for row in rating_set.assignments
        )
        if supplied != expected:
            _raise(
                "PRODUCTION_RATING_ITEM_SET_MISMATCH",
                "explicit ratings differ from the generated 25-Item set",
            )
        if authorization_was_unpinned:
            # Write-ahead pin: a crash after a partial Catalog publication must not allow the
            # caller to reuse the deterministic per-Item keys with another decision set/policy.
            return _advance_checkpoint(
                checkpoint,
                at=at,
                rating_authorization=authorization,
                failure=None,
            )
        rows: list[MockExamProductionItemRunV1] = []
        changed = False
        for row in checkpoint.item_runs:
            assignment = assignments[row.workflow_call_id]
            if row.rating is not None:
                if (
                    row.rating.final_rating != assignment.final_rating
                    or row.rating.reviewer_operator_id != actor.actor_id
                    or row.rating.rating_policy_revision_id != policy.rating_policy_revision_id
                    or row.rating.rating_policy_sha256 != policy.rating_policy_sha256
                ):
                    _raise(
                        "PRODUCTION_RATING_RESUME_MISMATCH",
                        "resume input differs from an already published explicit rating",
                    )
                rows.append(row)
                continue
            command = PublishMockExamItemReviewCommand(
                item_revision_id=assignment.item_revision_id,
                expected_workflow_id=cast(str, row.workflow_id),
                final_rating=assignment.final_rating,
                reviewer_operator_id=actor.actor_id,
                rating_policy_revision_id=policy.rating_policy_revision_id,
                rating_policy_sha256=policy.rating_policy_sha256,
                idempotency_key=_operation_key(
                    checkpoint.execution_id, row.workflow_call_id, "rating"
                ),
            )
            try:
                result = self.ratings.publish(command)
                pointer = _rating_pointer(result, row, assignment.final_rating, policy, actor)
                current = _update_run(row, state="RATED", rating=pointer, failure=None)
            except Exception as exc:
                current = _update_run(
                    row,
                    state="RATING_UNCONFIRMED",
                    failure=_failure(
                        exc,
                        stage="RATING",
                        category="OPERATION_OUTCOME_UNKNOWN",
                        default_code="RATING_PUBLICATION_OUTCOME_UNKNOWN",
                        retryable=True,
                        at=at,
                    ),
                )
            rows.append(current)
            changed = changed or current != row
        if not changed:
            return checkpoint
        return _advance_checkpoint(
            checkpoint,
            at=at,
            item_runs=tuple(rows),
            rating_authorization=authorization,
            failure=None,
        )

    def advance_assembly(
        self,
        plan: MockExamProductionPlanV1,
        checkpoint: MockExamProductionExecutionV1,
        actor: ActorContext,
        intent: MockExamAssemblyIntentV1,
        *,
        at: datetime,
    ) -> MockExamProductionExecutionV1:
        _require_context(plan, checkpoint, actor)
        if not all(row.rating is not None for row in checkpoint.item_runs):
            _raise("PRODUCTION_RATINGS_INCOMPLETE", "all 25 explicit ratings must be published")
        if checkpoint.assembly_intent is not None and checkpoint.assembly_intent != intent:
            _raise(
                "PRODUCTION_ASSEMBLY_INTENT_MISMATCH",
                "resume input differs from the pinned assembly intent",
            )
        if checkpoint.assembly_intent is None:
            # The operator intent must survive CAS before planner output or assembly creation can
            # consume it. This makes a resumed call unable to change deliverable identity.
            return _advance_checkpoint(
                checkpoint,
                at=at,
                assembly_intent=intent,
                failure=None,
            )
        graph = checkpoint.graph_publications[-1]
        expected_items = tuple(
            cast(MockExamItemRegistrationPointerV1, row.registration).item_revision_id
            for row in checkpoint.item_runs
        )
        cohort = build_mock_exam_assembly_cohort(expected_items)
        assembly_plan = checkpoint.assembly_plan
        try:
            if assembly_plan is None:
                preview = self.assemblies.preview(
                    PreviewMockExamAssemblyPlanRequest(
                        policy_revision_id=plan.policy_revision_id,
                        policy_sha256=plan.policy_sha256,
                        graph_snapshot_revision_id=graph.graph_snapshot_revision_id,
                        graph_snapshot_sha256=graph.graph_snapshot_sha256,
                        cohort=cohort,
                    )
                )
                if preview.status != "READY":
                    _raise("ASSEMBLY_PLAN_NOT_READY", "assembly planner returned shortage")
                preview_members = tuple(
                    (row.position, row.item_revision_id) for row in preview.placements
                )
                expected_members = tuple(
                    (row.position, row.item_revision_id) for row in cohort.members
                )
                preview_items = tuple(row[1] for row in preview_members)
                if (
                    preview.policy_revision_id != plan.policy_revision_id
                    or preview.policy_sha256 != plan.policy_sha256
                    or preview.cohort != cohort
                    or preview_members != expected_members
                ):
                    _raise(
                        "ASSEMBLY_PLAN_CONTAINS_EXTERNAL_ITEM",
                        "planner selected an Item outside the 25 generated workflows",
                    )
                assembly_key = _operation_key(
                    checkpoint.execution_id,
                    cohort.cohort_sha256,
                    preview.plan_sha256,
                    "assembly",
                )
                assembly_plan = MockExamAssemblyPlanPointerV1(
                    plan_sha256=preview.plan_sha256,
                    cohort_id=cohort.cohort_id,
                    cohort_sha256=cohort.cohort_sha256,
                    assembly_idempotency_key_sha256=content_sha256(assembly_key),
                    policy_revision_id=preview.policy_revision_id,
                    policy_sha256=preview.policy_sha256,
                    graph_snapshot_revision_id=preview.graph_snapshot_revision_id,
                    graph_snapshot_sha256=preview.graph_snapshot_sha256,
                    item_revision_ids=preview_items,
                    planned_at=preview.planned_at,
                )
                # Planner output, exact cohort, and the derived creation idempotency identity are
                # one immutable write-ahead pointer. Assembly creation starts on the next call.
                return _advance_checkpoint(
                    checkpoint,
                    at=max(at, assembly_plan.planned_at),
                    assembly_intent=intent,
                    assembly_plan=assembly_plan,
                    failure=None,
                )
            else:
                assembly_key = _operation_key(
                    checkpoint.execution_id,
                    cohort.cohort_sha256,
                    assembly_plan.plan_sha256,
                    "assembly",
                )
                if (
                    assembly_plan.cohort_id != cohort.cohort_id
                    or assembly_plan.cohort_sha256 != cohort.cohort_sha256
                    or assembly_plan.item_revision_ids != expected_items
                    or assembly_plan.policy_revision_id != plan.policy_revision_id
                    or assembly_plan.policy_sha256 != plan.policy_sha256
                    or assembly_plan.assembly_idempotency_key_sha256 != content_sha256(assembly_key)
                ):
                    _raise(
                        "PRODUCTION_ASSEMBLY_COHORT_MISMATCH",
                        "resume checkpoint differs from the exact generated-Item cohort",
                    )
            if checkpoint.assembly is not None:
                return checkpoint
            manifest = self.assemblies.create(
                CreatePlannedMockExamAssemblyRequest(
                    deliverable_id=intent.deliverable_id,
                    deliverable_revision_id=intent.deliverable_revision_id,
                    form_key=intent.form_key,
                    display_label=intent.display_label,
                    policy_revision_id=plan.policy_revision_id,
                    policy_sha256=plan.policy_sha256,
                    graph_snapshot_revision_id=assembly_plan.graph_snapshot_revision_id,
                    graph_snapshot_sha256=assembly_plan.graph_snapshot_sha256,
                    cohort=cohort,
                    expected_plan_sha256=assembly_plan.plan_sha256,
                    planned_at=assembly_plan.planned_at,
                ),
                actor,
                idempotency_key=assembly_key,
            )
            _require_assembly_manifest_family(plan, manifest)
            manifest_members = tuple(
                (row.position, row.item_revision_id) for row in manifest.plan.placements
            )
            manifest_items = tuple(row[1] for row in manifest_members)
            if (
                manifest.deliverable_id != intent.deliverable_id
                or manifest.deliverable_revision_id != intent.deliverable_revision_id
                or manifest.form_key != intent.form_key
                or manifest.display_label != intent.display_label
                or manifest.created_by != actor.actor_id
                or manifest.plan.cohort != cohort
                or manifest_members
                != tuple((row.position, row.item_revision_id) for row in cohort.members)
                or manifest.plan.plan_sha256 != assembly_plan.plan_sha256
            ):
                _raise(
                    "ASSEMBLY_CONTAINS_EXTERNAL_ITEM",
                    "released assembly differs from its exact generated-Item plan",
                )
            assembly = MockExamAssemblyPointerV1(
                assessment_assembly_id=manifest.assessment_assembly_id,
                assessment_assembly_revision_id=manifest.assessment_assembly_revision_id,
                manifest_sha256=manifest.manifest_sha256,
                item_set_sha256=mock_exam_item_set_sha256(
                    tuple(
                        (
                            row.position,
                            mock_exam_planned_placement_id(
                                manifest.assessment_assembly_revision_id,
                                row.slot_id,
                                row.item_revision_id,
                            ),
                            row.item_id,
                            row.item_revision_id,
                            row.item_manifest_sha256,
                        )
                        for row in manifest.plan.placements
                    )
                ),
                item_revision_ids=manifest_items,
                created_at=manifest.created_at,
            )
        except Exception as exc:
            return _advance_checkpoint(
                checkpoint,
                at=at,
                assembly_intent=intent,
                assembly_plan=assembly_plan,
                failure=_failure(
                    exc,
                    stage="ASSEMBLY",
                    category="ASSEMBLY_FAILED",
                    default_code="ASSEMBLY_OUTCOME_UNKNOWN",
                    retryable=True,
                    at=at,
                ),
            )
        return _advance_checkpoint(
            checkpoint,
            at=max(at, assembly_plan.planned_at, assembly.created_at),
            assembly_intent=intent,
            assembly_plan=assembly_plan,
            assembly=assembly,
            failure=None,
        )

    def advance_hwpx(
        self,
        plan: MockExamProductionPlanV1,
        checkpoint: MockExamProductionExecutionV1,
        actor: ActorContext,
        *,
        at: datetime,
    ) -> MockExamProductionExecutionV1:
        _require_context(plan, checkpoint, actor)
        assembly = checkpoint.assembly
        assembly_plan = checkpoint.assembly_plan
        if assembly is None or assembly_plan is None:
            _raise("PRODUCTION_ASSEMBLY_MISSING", "released Assembly Revision is required")
        try:
            view = (
                self.hwpx.start(
                    assembly.assessment_assembly_revision_id,
                    operator_id=actor.actor_id,
                    idempotency_key=_operation_key(
                        checkpoint.execution_id,
                        assembly.assessment_assembly_revision_id,
                        "hwpx",
                    ),
                )
                if checkpoint.hwpx_build is None
                else self.hwpx.get(checkpoint.hwpx_build.build_id)
            )
            if checkpoint.hwpx_build is not None and (
                view.build_id != checkpoint.hwpx_build.build_id
            ):
                _raise(
                    "HWPX_BUILD_POINTER_MISMATCH",
                    "HWPX observation returned another build identity",
                )
            pointer = _hwpx_pointer(
                view,
                assembly,
                assembly_plan,
                actor.actor_id,
                expected_renderer_version=(
                    "3.0.0"
                    if isinstance(plan, (MockExamProductionPlanV2, MockExamProductionPlanV3))
                    else "2.0.0"
                ),
                use_v3=isinstance(checkpoint, MockExamProductionExecutionV3),
            )
            if checkpoint.hwpx_build is not None and (
                pointer.item_set_sha256 != checkpoint.hwpx_build.item_set_sha256
            ):
                _raise(
                    "HWPX_ITEM_SET_POINTER_MISMATCH",
                    "HWPX observation changed the immutable ordered Item-set hash",
                )
            failure = (
                _fixed_failure(
                    "HWPX",
                    "DELIVERY_FAILED",
                    view.failure_code or "HWPX_BUILD_FAILED",
                    False,
                    at,
                )
                if view.state.value == "FAILED"
                else None
            )
        except Exception as exc:
            return _advance_checkpoint(
                checkpoint,
                at=at,
                failure=_failure(
                    exc,
                    stage="HWPX",
                    category="OPERATION_OUTCOME_UNKNOWN",
                    default_code="HWPX_BUILD_OUTCOME_UNKNOWN",
                    retryable=True,
                    at=at,
                ),
            )
        if checkpoint.hwpx_build == pointer and checkpoint.failure == failure:
            return checkpoint
        pointer_times = (pointer.created_at,) + (
            (pointer.completed_at,) if pointer.completed_at is not None else ()
        )
        return _advance_checkpoint(
            checkpoint,
            at=max(at, *pointer_times),
            hwpx_build=pointer,
            failure=failure,
        )


def _workflow_request(
    call: MockExamPlannedWorkflowCallV1,
    block: MockExamOneItemGenerationBlockV1,
    resolution: MockExamGenerationBlockResolutionV1,
    production_request_id: str,
) -> WorkflowStartRequest:
    if call.item_brief.mock_exam_slot is None:
        _raise("PRODUCTION_SLOT_INTENT_MISSING", "production brief requires mock_exam_slot")
    brief = ContentTeamItemBriefRequestV3.model_validate(call.item_brief.model_dump(mode="json"))
    source_classes = (
        (KnowledgeSourceClass.PAST_EXAM,)
        if isinstance(block, MockExamOneItemGenerationBlockV3)
        else (
            KnowledgeSourceClass.APPROVED_ITEM,
            KnowledgeSourceClass.PAST_EXAM,
            KnowledgeSourceClass.TEXTBOOK,
        )
    )
    return WorkflowStartRequest(
        definition_key=block.workflow_definition_key,
        definition_version=block.workflow_definition_version,
        request_name=block.request_name,
        image_mode=block.image_mode,
        pack_key=block.content_pack_key,
        environment="development",
        source_intake_batch_ids=(),
        registry_mode=block.registry_mode,
        item_id=None,
        base_revision_id=None,
        item_brief=brief,
        stimulus_asset_key=None,
        execution_preset_key=block.execution_preset_key,
        production_occurrence=WorkflowProductionOccurrenceV1(
            production_request_id=production_request_id,
            workflow_call_id=call.workflow_call_id,
        ),
        expected_resolution=_expected_workflow_resolution(resolution),
        educational_retrieval=EducationalRetrievalIntentRequest(
            corpus_key="integrated-science-textbooks",
            query_kind="ITEM_PREPARATION",
            curriculum_root_key=None,
            topic_keys=(),
            required_item_elements=("choice", "paragraph"),
            source_classes=source_classes,
        ),
    )


def _expected_workflow_resolution(
    resolution: MockExamGenerationBlockResolutionV1,
) -> WorkflowExpectedResolutionV1:
    return WorkflowExpectedResolutionV1(
        workflow_definition_key=resolution.workflow_definition_key,
        workflow_definition_version=resolution.workflow_definition_version,
        workflow_definition_sha256=resolution.workflow_definition_sha256,
        content_pack_release_id=resolution.content_pack_release_id,
        content_pack_key=resolution.content_pack_key,
        content_pack_version=resolution.content_pack_version,
        content_pack_bundle_sha256=resolution.content_pack_release_sha256,
        content_pack_source_tree_sha256=resolution.content_pack_source_tree_sha256,
        execution_preset_id=resolution.execution_preset_id,
        execution_preset_revision_id=resolution.execution_preset_revision_id,
        execution_preset_key=resolution.execution_preset_key,
        execution_preset_content_sha256=resolution.execution_preset_sha256,
    )


def _require_workflow_resolution(
    workflow: WorkflowView,
    resolution: MockExamGenerationBlockResolutionV1,
) -> None:
    expected = _expected_workflow_resolution(resolution)
    if (
        workflow.definition_key != resolution.workflow_definition_key
        or workflow.definition_version != resolution.workflow_definition_version
        or workflow.accepted_resolution is None
        or workflow.accepted_resolution.model_dump(mode="json") != expected.model_dump(mode="json")
    ):
        _raise(
            "WORKFLOW_ACCEPTED_RESOLUTION_MISMATCH",
            "Workflow did not accept the exact generation dependencies",
        )


def _workflow_knowledge_provenance(
    workflow: WorkflowView,
    resolution: MockExamGenerationBlockResolutionV1,
    call: MockExamPlannedWorkflowCallV1,
) -> MockExamWorkflowKnowledgeProvenancePointerV1:
    source = workflow.knowledge_provenance
    if source is None:
        _raise(
            "WORKFLOW_KNOWLEDGE_PROVENANCE_MISSING",
            "production Workflow has no exact knowledge provenance",
        )
    pointer_type = (
        MockExamWorkflowKnowledgeProvenancePointerV3
        if isinstance(resolution, MockExamGenerationBlockResolutionV3)
        else MockExamWorkflowKnowledgeProvenancePointerV1
    )
    pointer = pointer_type.model_validate(source.model_dump(mode="json"))
    expected_curriculum_root = resolve_integrated_science_curriculum_scope(
        call.item_brief.curriculum_selected_unit_key
    ).graph_root_stable_key
    expected_source_classes = (
        ("PAST_EXAM",)
        if isinstance(resolution, MockExamGenerationBlockResolutionV3)
        else ("APPROVED_ITEM", "PAST_EXAM", "TEXTBOOK")
    )
    if (
        pointer.preset_revision_id != resolution.execution_preset_revision_id
        or pointer.corpus_key != "integrated-science-textbooks"
        or pointer.query_kind != "ITEM_PREPARATION"
        or pointer.curriculum_root_key != expected_curriculum_root
        or pointer.required_item_elements != ("choice", "paragraph")
        or pointer.source_classes != expected_source_classes
    ):
        _raise(
            "WORKFLOW_KNOWLEDGE_PROVENANCE_MISMATCH",
            "Workflow knowledge provenance differs from the authorized retrieval intent",
        )
    return pointer


def _analysis_run(
    row: MockExamProductionItemRunV1,
    view: KnowledgeAnalysisRunView,
    policy: MockExamAnalysisPolicyPointerV1,
    at: datetime,
) -> MockExamProductionItemRunV1:
    assert row.registration is not None
    if (
        (row.analysis is not None and view.analysis_run_id != row.analysis.analysis_run_id)
        or view.source_kind != "APPROVED_ITEM_REVISION"
        or view.source_revision_id != row.registration.item_revision_id
        or view.risk_policy_revision_id != policy.risk_policy_revision_id
        or view.risk_policy_sha256 != policy.risk_policy_sha256
    ):
        return _terminal_run_failure(
            row, "ANALYSIS_SOURCE_POINTER_MISMATCH", "ARTIFACT_INTEGRITY_FAILED", at
        )
    pointer_type = (
        MockExamAnalysisPointerV3
        if isinstance(row, MockExamProductionItemRunV3)
        else MockExamAnalysisPointerV1
    )
    pointer = pointer_type(
        analysis_run_id=view.analysis_run_id,
        source_item_revision_id=row.registration.item_revision_id,
        request_sha256=view.request_sha256,
        risk_policy_revision_id=view.risk_policy_revision_id,
        risk_policy_sha256=view.risk_policy_sha256,
        state=view.state,
        resource_version=view.resource_version,
        accepted_result_artifact_id=view.accepted_result_artifact_id,
        accepted_result_artifact_revision_id=view.accepted_result_artifact_revision_id,
        accepted_result_sha256=view.accepted_result_sha256,
    )
    if view.state == "ACCEPTED":
        return _update_run(row, state="ANALYSIS_ACCEPTED", analysis=pointer, failure=None)
    if view.state == "NEEDS_REVIEW":
        return _update_run(
            row,
            state="ANALYSIS_REVIEW_REQUIRED",
            analysis=pointer,
            failure=_fixed_failure(
                "ANALYSIS",
                "ANALYSIS_FAILED",
                "ANALYSIS_REVIEW_REQUIRED",
                False,
                at,
            ),
        )
    if view.state in {"FAILED", "REJECTED", "CANCELLED"}:
        return _terminal_run_failure(
            row,
            view.error_code or f"ANALYSIS_{view.state}",
            "ANALYSIS_FAILED",
            at,
            analysis=pointer,
        )
    return _update_run(row, state="ANALYSIS_ACTIVE", analysis=pointer, failure=None)


def _analysis_review_authorization_is_pending(
    checkpoint: MockExamProductionExecutionV1,
    authorization: MockExamAnalysisReviewAuthorizationPointerV1,
) -> bool:
    rows = {row.workflow_call_id: row for row in checkpoint.item_runs}
    return any(
        (row := rows.get(binding.workflow_call_id)) is not None
        and row.analysis is not None
        and row.analysis.analysis_run_id == binding.analysis_run_id
        and row.analysis.resource_version == binding.expected_resource_version
        and row.analysis.state == "NEEDS_REVIEW"
        for binding in authorization.bindings
    )


def _require_pinned_analysis_review_bindings(
    checkpoint: MockExamProductionExecutionV1,
    authorization: MockExamAnalysisReviewAuthorizationPointerV1,
) -> None:
    rows = {row.workflow_call_id: row for row in checkpoint.item_runs}
    for binding in authorization.bindings:
        row = rows.get(binding.workflow_call_id)
        analysis = row.analysis if row is not None else None
        if (
            row is None
            or row.position != binding.position
            or analysis is None
            or analysis.analysis_run_id != binding.analysis_run_id
            or analysis.resource_version < binding.expected_resource_version
        ):
            _raise(
                "PRODUCTION_ANALYSIS_REVIEW_BINDING_MISMATCH",
                "pinned analysis review no longer binds its exact run and version",
            )
        if analysis.state == "NEEDS_REVIEW":
            if analysis.resource_version != binding.expected_resource_version:
                _raise(
                    "PRODUCTION_ANALYSIS_REVIEW_BINDING_MISMATCH",
                    "review-required analysis advanced beyond its authorized version",
                )
            continue
        expected_terminal = "ACCEPTED" if binding.decision == "APPROVE" else "REJECTED"
        if analysis.state != expected_terminal:
            _raise(
                "PRODUCTION_ANALYSIS_REVIEW_BINDING_MISMATCH",
                "analysis state differs from its explicit review decision",
            )


def _rating_pointer(
    result: MockExamItemReviewPublicationResult,
    row: MockExamProductionItemRunV1,
    final_rating: Literal["A", "B", "C"],
    policy: MockExamRatingPolicyPointerV1,
    actor: ActorContext,
) -> MockExamRatingPointerV1:
    assert row.registration is not None
    assert row.workflow_id is not None
    assert row.human_approval is not None
    if (
        result.item_revision_id != row.registration.item_revision_id
        or result.workflow_id != row.workflow_id
        or result.human_approval_request_id != row.human_approval.approval_request_id
        or result.final_rating != final_rating
        or result.reviewer_operator_id != actor.actor_id
        or result.rating_policy_revision_id != policy.rating_policy_revision_id
        or result.rating_policy_sha256 != policy.rating_policy_sha256
    ):
        _raise("RATING_PUBLICATION_POINTER_MISMATCH", "rating result differs from explicit input")
    return MockExamRatingPointerV1(
        item_review_record_id=result.item_review_record_id,
        item_revision_id=result.item_revision_id,
        workflow_id=result.workflow_id,
        human_approval_request_id=result.human_approval_request_id,
        decision_sha256=result.decision_sha256,
        final_rating=result.final_rating,
        reviewer_operator_id=result.reviewer_operator_id,
        rating_policy_revision_id=result.rating_policy_revision_id,
        rating_policy_sha256=result.rating_policy_sha256,
    )


def _hwpx_pointer(
    view: AssessmentHwpxBuildView,
    assembly: MockExamAssemblyPointerV1,
    assembly_plan: MockExamAssemblyPlanPointerV1,
    operator_id: str,
    *,
    expected_renderer_version: Literal["2.0.0", "3.0.0"],
    use_v3: bool,
) -> MockExamHwpxBuildPointerV1:
    if view.item_set_sha256 != assembly.item_set_sha256:
        _raise(
            "HWPX_ITEM_SET_POINTER_MISMATCH",
            "HWPX build Item-set hash differs from the released Assembly placements",
        )
    if (
        view.assessment_assembly_id != assembly.assessment_assembly_id
        or view.assessment_assembly_revision_id != assembly.assessment_assembly_revision_id
        or view.assembly_manifest_sha256 != assembly.manifest_sha256
        or view.policy_revision_id != assembly_plan.policy_revision_id
        or view.policy_sha256 != assembly_plan.policy_sha256
        or view.graph_snapshot_revision_id != assembly_plan.graph_snapshot_revision_id
        or view.graph_snapshot_sha256 != assembly_plan.graph_snapshot_sha256
        or view.item_count != len(assembly.item_revision_ids)
        or view.renderer != "content-team-exam"
        or view.renderer_version != expected_renderer_version
        or view.created_by_operator_id != operator_id
    ):
        _raise("HWPX_BUILD_POINTER_MISMATCH", "HWPX build differs from the exact assembly")
    pointer_type = MockExamHwpxBuildPointerV3 if use_v3 else MockExamHwpxBuildPointerV2
    return pointer_type(
        build_id=view.build_id,
        assessment_assembly_id=view.assessment_assembly_id,
        assessment_assembly_revision_id=view.assessment_assembly_revision_id,
        assembly_manifest_sha256=view.assembly_manifest_sha256,
        policy_revision_id=view.policy_revision_id,
        policy_sha256=view.policy_sha256,
        graph_snapshot_revision_id=view.graph_snapshot_revision_id,
        graph_snapshot_sha256=view.graph_snapshot_sha256,
        item_set_sha256=view.item_set_sha256,
        item_revision_ids=assembly.item_revision_ids,
        renderer=view.renderer,
        renderer_version=cast(Any, view.renderer_version),
        state=view.state.value,
        validation_state=view.validation_state.value,
        item_count=cast(Literal[25], view.item_count),
        section_count=view.section_count,
        output_artifact_id=view.output_artifact_id,
        output_artifact_revision_id=view.output_artifact_revision_id,
        output_sha256=view.output_sha256,
        download_available=view.download_available,
        resource_version=view.resource_version,
        failure_code=view.failure_code,
        created_by_operator_id=view.created_by_operator_id,
        created_at=view.created_at,
        completed_at=view.completed_at,
    )


def _new_checkpoint(
    *,
    execution_id: str,
    production_request_id: str,
    production_plan_id: str,
    production_plan_sha256: str,
    operator_id: str,
    item_runs: tuple[MockExamProductionItemRunV1, ...],
    use_v2: bool,
    use_v3: bool,
    at: datetime,
) -> MockExamProductionExecutionV1:
    value: dict[str, Any] = {
        "schema_version": (
            "mock-exam-production-execution/3.0"
            if use_v3
            else "mock-exam-production-execution/2.0"
            if use_v2
            else "mock-exam-production-execution/1.0"
        ),
        "execution_id": execution_id,
        "production_request_id": production_request_id,
        "production_plan_id": production_plan_id,
        "production_plan_sha256": production_plan_sha256,
        "operator_id": operator_id,
        "checkpoint_sequence": 0,
        "predecessor_execution_revision_id": None,
        "predecessor_checkpoint_sha256": None,
        "state": "ITEM_PRODUCTION",
        "generation_block_resolution": None,
        "analysis_policy": None,
        "analysis_general_knowledge_mode": None,
        "analysis_review_authorizations": [],
        "item_runs": [row.model_dump(mode="json") for row in item_runs],
        "graph_publication_authorization": None,
        "graph_publications": [],
        "rating_authorization": None,
        "assembly_intent": None,
        "assembly_plan": None,
        "assembly": None,
        "hwpx_build": None,
        "failure": None,
        "created_at": _utc_string(at),
        "checkpointed_at": _utc_string(at),
    }
    sha256 = content_sha256(value)
    checkpoint_type = (
        MockExamProductionExecutionV3
        if use_v3
        else MockExamProductionExecutionV2
        if use_v2
        else MockExamProductionExecutionV1
    )
    return checkpoint_type.model_validate(
        {
            **value,
            "execution_revision_id": ("productionexecrev_" + sha256.removeprefix("sha256:")[:32]),
            "checkpoint_sha256": sha256,
        }
    )


_UNSET = object()


def _advance_checkpoint(
    checkpoint: MockExamProductionExecutionV1,
    *,
    at: datetime,
    generation_block_resolution: MockExamGenerationBlockResolutionV1 | object | None = _UNSET,
    analysis_policy: MockExamAnalysisPolicyPointerV1 | object | None = _UNSET,
    analysis_general_knowledge_mode: str | object | None = _UNSET,
    analysis_review_authorizations: (
        tuple[MockExamAnalysisReviewAuthorizationPointerV1, ...] | object
    ) = _UNSET,
    item_runs: tuple[MockExamProductionItemRunV1, ...] | object = _UNSET,
    graph_publication_authorization: (
        MockExamGraphPublicationAuthorizationPointerV1 | object | None
    ) = _UNSET,
    graph_publications: tuple[MockExamGraphPublicationPointerV1, ...] | object = _UNSET,
    rating_authorization: MockExamRatingAuthorizationPointerV1 | object | None = _UNSET,
    assembly_intent: MockExamAssemblyIntentV1 | object | None = _UNSET,
    assembly_plan: MockExamAssemblyPlanPointerV1 | object | None = _UNSET,
    assembly: MockExamAssemblyPointerV1 | object | None = _UNSET,
    hwpx_build: MockExamHwpxBuildPointerV1 | object | None = _UNSET,
    failure: MockExamProductionFailureV1 | object | None = _UNSET,
) -> MockExamProductionExecutionV1:
    resolution_value = (
        checkpoint.generation_block_resolution
        if generation_block_resolution is _UNSET
        else cast(MockExamGenerationBlockResolutionV1 | None, generation_block_resolution)
    )
    analysis_policy_value = (
        checkpoint.analysis_policy
        if analysis_policy is _UNSET
        else cast(MockExamAnalysisPolicyPointerV1 | None, analysis_policy)
    )
    analysis_mode_value = (
        checkpoint.analysis_general_knowledge_mode
        if analysis_general_knowledge_mode is _UNSET
        else cast(
            Literal["DISABLED", "AUXILIARY_UNATTRIBUTED"] | None,
            analysis_general_knowledge_mode,
        )
    )
    analysis_review_values = (
        checkpoint.analysis_review_authorizations
        if analysis_review_authorizations is _UNSET
        else cast(
            tuple[MockExamAnalysisReviewAuthorizationPointerV1, ...],
            analysis_review_authorizations,
        )
    )
    item_values = (
        checkpoint.item_runs
        if item_runs is _UNSET
        else cast(tuple[MockExamProductionItemRunV1, ...], item_runs)
    )
    graph_authorization_value = (
        checkpoint.graph_publication_authorization
        if graph_publication_authorization is _UNSET
        else cast(
            MockExamGraphPublicationAuthorizationPointerV1 | None,
            graph_publication_authorization,
        )
    )
    publication_values = (
        checkpoint.graph_publications
        if graph_publications is _UNSET
        else cast(tuple[MockExamGraphPublicationPointerV1, ...], graph_publications)
    )
    rating_authorization_value = (
        checkpoint.rating_authorization
        if rating_authorization is _UNSET
        else cast(MockExamRatingAuthorizationPointerV1 | None, rating_authorization)
    )
    assembly_intent_value = (
        checkpoint.assembly_intent
        if assembly_intent is _UNSET
        else cast(MockExamAssemblyIntentV1 | None, assembly_intent)
    )
    plan_value = (
        checkpoint.assembly_plan
        if assembly_plan is _UNSET
        else cast(MockExamAssemblyPlanPointerV1 | None, assembly_plan)
    )
    assembly_value = (
        checkpoint.assembly
        if assembly is _UNSET
        else cast(MockExamAssemblyPointerV1 | None, assembly)
    )
    hwpx_value = (
        checkpoint.hwpx_build
        if hwpx_build is _UNSET
        else cast(MockExamHwpxBuildPointerV1 | None, hwpx_build)
    )
    failure_value = (
        checkpoint.failure
        if failure is _UNSET
        else cast(MockExamProductionFailureV1 | None, failure)
    )
    state = mock_exam_production_state_from_pointers(
        item_runs=item_values,
        graph_publications=publication_values,
        assembly_plan=plan_value,
        assembly=assembly_value,
        hwpx_build=hwpx_value,
        failure=failure_value,
    )
    checkpointed_at = _checkpoint_timestamp_floor(
        checkpoint,
        at=at,
        generation_block_resolution=resolution_value,
        analysis_review_authorizations=analysis_review_values,
        item_runs=item_values,
        graph_publication_authorization=graph_authorization_value,
        graph_publications=publication_values,
        rating_authorization=rating_authorization_value,
        assembly_plan=plan_value,
        assembly=assembly_value,
        hwpx_build=hwpx_value,
        failure=failure_value,
    )
    value: dict[str, Any] = {
        "schema_version": checkpoint.schema_version,
        "execution_id": checkpoint.execution_id,
        "production_request_id": checkpoint.production_request_id,
        "production_plan_id": checkpoint.production_plan_id,
        "production_plan_sha256": checkpoint.production_plan_sha256,
        "operator_id": checkpoint.operator_id,
        "checkpoint_sequence": checkpoint.checkpoint_sequence + 1,
        "predecessor_execution_revision_id": checkpoint.execution_revision_id,
        "predecessor_checkpoint_sha256": checkpoint.checkpoint_sha256,
        "state": state,
        "generation_block_resolution": (
            resolution_value.model_dump(mode="json") if resolution_value is not None else None
        ),
        "analysis_policy": (
            analysis_policy_value.model_dump(mode="json")
            if analysis_policy_value is not None
            else None
        ),
        "analysis_general_knowledge_mode": analysis_mode_value,
        "analysis_review_authorizations": [
            row.model_dump(mode="json") for row in analysis_review_values
        ],
        "item_runs": [row.model_dump(mode="json") for row in item_values],
        "graph_publication_authorization": (
            graph_authorization_value.model_dump(mode="json")
            if graph_authorization_value is not None
            else None
        ),
        "graph_publications": [row.model_dump(mode="json") for row in publication_values],
        "rating_authorization": (
            rating_authorization_value.model_dump(mode="json")
            if rating_authorization_value is not None
            else None
        ),
        "assembly_intent": (
            assembly_intent_value.model_dump(mode="json")
            if assembly_intent_value is not None
            else None
        ),
        "assembly_plan": plan_value.model_dump(mode="json") if plan_value else None,
        "assembly": assembly_value.model_dump(mode="json") if assembly_value else None,
        "hwpx_build": hwpx_value.model_dump(mode="json") if hwpx_value else None,
        "failure": failure_value.model_dump(mode="json") if failure_value else None,
        "created_at": _utc_string(checkpoint.created_at),
        "checkpointed_at": _utc_string(checkpointed_at),
    }
    sha256 = content_sha256(value)
    checkpoint_type = (
        MockExamProductionExecutionV3
        if isinstance(checkpoint, MockExamProductionExecutionV3)
        else MockExamProductionExecutionV2
        if isinstance(checkpoint, MockExamProductionExecutionV2)
        else MockExamProductionExecutionV1
    )
    return checkpoint_type.model_validate(
        {
            **value,
            "execution_revision_id": ("productionexecrev_" + sha256.removeprefix("sha256:")[:32]),
            "checkpoint_sha256": sha256,
        }
    )


def _checkpoint_timestamp_floor(
    checkpoint: MockExamProductionExecutionV1,
    *,
    at: datetime,
    generation_block_resolution: MockExamGenerationBlockResolutionV1 | None,
    analysis_review_authorizations: tuple[MockExamAnalysisReviewAuthorizationPointerV1, ...],
    item_runs: tuple[MockExamProductionItemRunV1, ...],
    graph_publication_authorization: MockExamGraphPublicationAuthorizationPointerV1 | None,
    graph_publications: tuple[MockExamGraphPublicationPointerV1, ...],
    rating_authorization: MockExamRatingAuthorizationPointerV1 | None,
    assembly_plan: MockExamAssemblyPlanPointerV1 | None,
    assembly: MockExamAssemblyPointerV1 | None,
    hwpx_build: MockExamHwpxBuildPointerV1 | None,
    failure: MockExamProductionFailureV1 | None,
) -> datetime:
    """Never timestamp a durable parent before an immutable child it has observed."""

    timestamps = [checkpoint.created_at, checkpoint.checkpointed_at, at]
    if generation_block_resolution is not None:
        timestamps.append(generation_block_resolution.resolved_at)
    for row in item_runs:
        if row.knowledge_provenance is not None:
            timestamps.append(row.knowledge_provenance.resolved_at)
        if row.human_approval is not None:
            timestamps.append(row.human_approval.approved_at)
        if row.failure is not None:
            timestamps.append(row.failure.observed_at)
    timestamps.extend(row.authorized_at for row in analysis_review_authorizations)
    if graph_publication_authorization is not None:
        timestamps.append(graph_publication_authorization.authorized_at)
    for publication in graph_publications:
        timestamps.extend((publication.authorized_at, publication.published_at))
    if rating_authorization is not None:
        timestamps.append(rating_authorization.authorized_at)
    if assembly_plan is not None:
        timestamps.append(assembly_plan.planned_at)
    if assembly is not None:
        timestamps.append(assembly.created_at)
    if hwpx_build is not None:
        timestamps.append(hwpx_build.created_at)
        if hwpx_build.completed_at is not None:
            timestamps.append(hwpx_build.completed_at)
    if failure is not None:
        timestamps.append(failure.observed_at)
    return max(timestamps)


def _update_run(
    row: MockExamProductionItemRunV1,
    **updates: Any,
) -> MockExamProductionItemRunV1:
    row_type = (
        MockExamProductionItemRunV3
        if isinstance(row, MockExamProductionItemRunV3)
        else MockExamProductionItemRunV2
        if isinstance(row, MockExamProductionItemRunV2)
        else MockExamProductionItemRunV1
    )
    return row_type.model_validate(row.model_dump(mode="json") | updates)


def _same_review_evidence(
    submitted: MockExamReviewPointerV1,
    observed: MockExamReviewPointerV1,
) -> bool:
    """Allow only the approval-row version to advance after the same review was submitted."""

    if isinstance(submitted, MockExamReviewPointerV3) != isinstance(
        observed, MockExamReviewPointerV3
    ):
        return False
    immutable_fields: tuple[str, ...] = (
        "approval_request_id",
        "step_run_id",
        "artifact_id",
        "artifact_revision_id",
        "sha256",
        "result_schema",
        "finding_info_count",
        "finding_warning_count",
        "finding_blocking_count",
    )
    if isinstance(submitted, MockExamReviewPointerV3):
        immutable_fields += ("trusted_evidence_usage_receipts",)
    return observed.approval_resource_version >= submitted.approval_resource_version and all(
        getattr(submitted, field) == getattr(observed, field) for field in immutable_fields
    )


def _terminal_run_failure(
    row: MockExamProductionItemRunV1,
    code: str,
    category: Literal[
        "WORKFLOW_EXECUTION_FAILED",
        "REGISTRATION_FAILED",
        "ANALYSIS_FAILED",
        "ARTIFACT_INTEGRITY_FAILED",
    ],
    at: datetime,
    *,
    analysis: MockExamAnalysisPointerV1 | None = None,
) -> MockExamProductionItemRunV1:
    stage = (
        "ANALYSIS"
        if category == "ANALYSIS_FAILED"
        else "REGISTRATION"
        if category == "REGISTRATION_FAILED"
        else "WORKFLOW_EXECUTION"
    )
    return _update_run(
        row,
        state="FAILED",
        analysis=analysis if analysis is not None else row.analysis,
        failure=_fixed_failure(
            stage,
            category,
            code,
            False,
            at,
        ),
    )


def _require_assembly_manifest_family(
    plan: MockExamProductionPlanV1,
    manifest: MockExamAssemblyViewV2 | MockExamAssemblyViewV3,
) -> None:
    expected_schema = (
        "mock-exam-assembly-manifest/3.0"
        if isinstance(plan, (MockExamProductionPlanV2, MockExamProductionPlanV3))
        else "mock-exam-assembly-manifest/2.0"
    )
    if manifest.schema_version != expected_schema:
        _raise(
            "ASSEMBLY_SCHEMA_UNSUPPORTED",
            "released assembly does not match the production-plan protocol family",
        )


def _require_context(
    plan: MockExamProductionPlanV1,
    checkpoint: MockExamProductionExecutionV1,
    actor: ActorContext,
) -> None:
    if isinstance(plan, MockExamProductionPlanV3) != isinstance(
        checkpoint, MockExamProductionExecutionV3
    ):
        _raise(
            "PRODUCTION_PROTOCOL_FAMILY_MISMATCH",
            "production plan and checkpoint use different protocol families",
        )
    if (
        checkpoint.production_plan_id != plan.production_plan_id
        or checkpoint.production_plan_sha256 != plan.plan_sha256
    ):
        _raise("PRODUCTION_PLAN_POINTER_MISMATCH", "checkpoint pins another plan")
    if checkpoint.operator_id != actor.actor_id:
        _raise("PRODUCTION_OPERATOR_MISMATCH", "same operator must continue the run")
    expected_calls = tuple(
        (call.workflow_call_id, call.item_brief.mock_exam_slot.position)
        for call in plan.workflow_calls
    )
    actual_calls = tuple((row.workflow_call_id, row.position) for row in checkpoint.item_runs)
    if expected_calls != actual_calls:
        _raise("PRODUCTION_CALL_SET_MISMATCH", "checkpoint differs from plan.workflow_calls")


def _require_generation_resolution(
    block: MockExamOneItemGenerationBlockV1,
    resolution: MockExamGenerationBlockResolutionV1,
) -> None:
    expected = (
        block.block_key,
        block.block_revision,
        block.block_sha256,
        block.workflow_definition_key,
        block.workflow_definition_version,
        block.content_pack_key,
        block.content_pack_version,
        block.content_pack_source_tree_sha256,
        block.execution_preset_key,
    )
    actual = (
        resolution.generation_block_key,
        resolution.generation_block_revision,
        resolution.generation_block_sha256,
        resolution.workflow_definition_key,
        resolution.workflow_definition_version,
        resolution.content_pack_key,
        resolution.content_pack_version,
        resolution.content_pack_source_tree_sha256,
        resolution.execution_preset_key,
    )
    if actual != expected:
        _raise("PRODUCTION_GENERATION_BLOCK_STALE", "runtime block differs from plan")
    if isinstance(block, MockExamOneItemGenerationBlockV3) and (
        not isinstance(resolution, MockExamGenerationBlockResolutionV3)
        or (
            resolution.role_protocol_version,
            resolution.role_schema_bundle_sha256,
            resolution.knowledge_source_mode,
            resolution.authoring_result_schema,
            resolution.review_result_schema,
            resolution.evidence_usage_receipt_schema_version,
            resolution.trusted_evidence_usage_receipts_required,
        )
        != (
            block.role_protocol_version,
            block.role_schema_bundle_sha256,
            block.knowledge_source_mode,
            block.authoring_result_schema,
            block.review_result_schema,
            block.evidence_usage_receipt_schema_version,
            block.trusted_evidence_usage_receipts_required,
        )
    ):
        _raise(
            "PRODUCTION_GENERATION_BLOCK_STALE",
            "runtime trusted-RAG contracts differ from the plan",
        )


def _operation_key(*parts: str) -> str:
    return "mockexam:" + content_sha256(list(parts)).removeprefix("sha256:")


def _utc_string(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _failure(
    exc: Exception,
    *,
    stage: Any,
    category: Any,
    default_code: str,
    retryable: bool,
    at: datetime,
) -> MockExamProductionFailureV1:
    return _fixed_failure(
        stage,
        category,
        _error_code(exc, default_code),
        retryable,
        at,
    )


def _fixed_failure(
    stage: Any,
    category: Any,
    code: str,
    retryable: bool,
    at: datetime,
) -> MockExamProductionFailureV1:
    return MockExamProductionFailureV1(
        stage=stage,
        category=category,
        code=code if _stable_error_code(code) else "PRODUCTION_OPERATION_FAILED",
        retryable=retryable,
        observed_at=at,
    )


def _error_code(exc: Exception, default: str) -> str:
    for attribute in ("error_code", "code"):
        value = getattr(exc, attribute, None)
        if value is not None:
            candidate = getattr(value, "value", value)
            if isinstance(candidate, str) and _stable_error_code(candidate):
                return candidate
    return default


def _stable_error_code(value: str) -> bool:
    return (
        3 <= len(value) <= 128
        and value[0].isalpha()
        and value[0].isupper()
        and all(
            character.isupper() or character.isdigit() or character == "_" for character in value
        )
    )


def _raise(code: str, message: str) -> Never:
    raise MockExamProductionCoordinatorError(code, message)
