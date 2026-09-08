from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Literal

import pytest
from eom_api.services.mock_exam_production_checkpoint_store import (
    AtomicJsonMockExamProductionCheckpointStore,
    MockExamCheckpointStoreError,
    _monotonic_successor,
)
from eom_api.services.mock_exam_production_coordinator import (
    CatalogReviewEligibilityReader,
    ExistingOneItemWorkflowOperations,
    MockExamProductionCoordinator,
    MockExamProductionCoordinatorError,
    WorkflowApprovalReceipt,
    WorkflowStartReceipt,
)
from eom_api.services.mock_exam_production_runner import MockExamProductionRunner
from eom_api_contracts.hwpx import HwpxBuildState, HwpxValidationState
from eom_api_contracts.mock_exam_execution import (
    MockExamAnalysisPolicyPointerV1,
    MockExamAssemblyIntentV1,
    MockExamExplicitAnalysisReviewV1,
    MockExamExplicitRatingV1,
    MockExamGenerationBlockResolutionV1,
    MockExamGenerationBlockResolutionV2,
    MockExamGraphPublicationInputV1,
    MockExamProductionExecutionV1,
    MockExamProductionExecutionV2,
    MockExamRatingPolicyPointerV1,
    MockExamReviewEligibilityObservationV1,
    build_mock_exam_explicit_analysis_review_set,
    build_mock_exam_explicit_rating_set,
    mock_exam_production_is_terminal,
)
from eom_api_contracts.workflows import (
    ContentTeamItemBriefRequestV3,
    WorkflowAcceptedResolutionView,
    WorkflowItemRegistrationView,
    WorkflowKnowledgeProvenanceView,
    WorkflowStartRequest,
    WorkflowView,
)
from eom_catalog_contracts.assessment_assembly import (
    load_integrated_science_mock_exam_layout_policy,
    load_integrated_science_mock_exam_policy,
    mock_exam_item_set_sha256,
    mock_exam_planned_placement_id,
)
from eom_catalog_contracts.curriculum import (
    load_integrated_science_editorial_outline,
    resolve_integrated_science_curriculum_scope,
)
from eom_catalog_contracts.item_review import (
    MockExamEligibilityFindingCounts,
    MockExamReviewEligibilityResult,
)
from eom_catalog_contracts.mock_exam_production_plan import (
    MockExamOneItemGenerationBlockV1,
    MockExamProductionPlanV1,
    build_integrated_science_mock_exam_production_plan,
    build_integrated_science_mock_exam_production_plan_v2,
)
from eom_identifiers import content_sha256
from eom_operator_identity import ActorContext, ActorSource, ActorType
from jsonschema import Draft202012Validator, FormatChecker
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 9, 8, 1, 2, 3, tzinfo=UTC)
OPERATOR_ID = "operator_" + "a" * 32
PRODUCTION_REQUEST_ID = "productionreq_" + "b" * 32
ANALYSIS_POLICY = MockExamAnalysisPolicyPointerV1(
    risk_policy_revision_id="analysisriskrev_" + "c" * 32,
    risk_policy_sha256="sha256:" + "c" * 64,
)


def _graph_input(authorized_at: datetime) -> MockExamGraphPublicationInputV1:
    value = {
        "current_graph_snapshot_revision_id": "graphrev_" + "d" * 32,
        "current_graph_snapshot_sha256": "sha256:" + "d" * 64,
        "access_policy_revision_id": "accessrev_" + "e" * 32,
        "access_policy_sha256": "sha256:" + "e" * 64,
        "authorized_at": authorized_at.isoformat().replace("+00:00", "Z"),
        "supersedes_authorization_sha256": None,
    }
    return MockExamGraphPublicationInputV1.model_validate(
        {**value, "authorization_sha256": content_sha256(value)}
    )


GRAPH_INPUT = _graph_input(NOW)
RATING_POLICY = MockExamRatingPolicyPointerV1(
    rating_policy_revision_id="ratingpolicyrev_" + "f" * 32,
    rating_policy_sha256="sha256:" + "f" * 64,
)


def _hex_id(prefix: str, value: int) -> str:
    return prefix + f"{value:032x}"


def _sha(value: int) -> str:
    return "sha256:" + f"{value:064x}"


def _fake_assembly_item_set_sha256() -> str:
    assembly_revision_id = _hex_id("assemblyrev_", 1)
    return mock_exam_item_set_sha256(
        tuple(
            (
                position,
                mock_exam_planned_placement_id(
                    assembly_revision_id,
                    f"slot-{position:02d}",
                    _hex_id("itemrev_", position),
                ),
                _hex_id("item_", position),
                _hex_id("itemrev_", position),
                _sha(850 + position),
            )
            for position in range(1, 26)
        )
    )


def _plan() -> MockExamProductionPlanV1:
    return build_integrated_science_mock_exam_production_plan(
        policy=load_integrated_science_mock_exam_policy(),
        layout_policy=load_integrated_science_mock_exam_layout_policy(),
        outline=load_integrated_science_editorial_outline(),
    )


def _actor() -> ActorContext:
    return ActorContext(
        actor_type=ActorType.OPERATOR,
        operator_id=OPERATOR_ID,
        session_id=None,
        request_id="mock-exam-test",
        authentication_time=NOW,
        permissions=frozenset(),
        source=ActorSource.CLI,
    )


class FakeWorkflowOperations:
    def __init__(
        self,
        *,
        blocking_positions: frozenset[int] = frozenset(),
        lose_first_start_response: bool = False,
        approved_operator_id: str = OPERATOR_ID,
        approved_at: datetime = NOW,
        provenance_resolved_at: datetime = NOW,
        accepted_resolution_drift_positions: frozenset[int] = frozenset(),
        legacy_null_provenance_roots: bool = False,
        workflow_failed_positions: frozenset[int] = frozenset(),
    ) -> None:
        self.blocking_positions = blocking_positions
        self.lose_first_start_response = lose_first_start_response
        self.approved_operator_id = approved_operator_id
        self.approved_at = approved_at
        self.provenance_resolved_at = provenance_resolved_at
        self.accepted_resolution_drift_positions = accepted_resolution_drift_positions
        self.legacy_null_provenance_roots = legacy_null_provenance_roots
        self.workflow_failed_positions = workflow_failed_positions
        self.provenance_drift_positions: set[int] = set()
        self.provenance_root_drift_positions: set[int] = set()
        self.start_requests: list[WorkflowStartRequest] = []
        self.start_keys: list[str] = []
        self.get_keys: list[str] = []
        self.approval_keys: list[str] = []
        self._start_by_key: dict[str, WorkflowStartReceipt] = {}
        self._position_by_workflow: dict[str, int] = {}
        self._request_by_workflow: dict[str, WorkflowStartRequest] = {}
        self._approved: set[str] = set()
        self._lost_keys: set[str] = set()

    def resolve_generation_block(
        self, block: MockExamOneItemGenerationBlockV1
    ) -> MockExamGenerationBlockResolutionV1:
        resolution_type = (
            MockExamGenerationBlockResolutionV2
            if block.block_revision == "2.0"
            else MockExamGenerationBlockResolutionV1
        )
        return resolution_type(
            generation_block_key=block.block_key,
            generation_block_revision=block.block_revision,
            generation_block_sha256=block.block_sha256,
            workflow_definition_key=block.workflow_definition_key,
            workflow_definition_version=block.workflow_definition_version,
            workflow_definition_sha256=_sha(10),
            content_pack_release_id=_hex_id("packrel_", 10),
            content_pack_key=block.content_pack_key,
            content_pack_version=block.content_pack_version,
            content_pack_release_sha256=_sha(11),
            content_pack_source_tree_sha256=block.content_pack_source_tree_sha256,
            execution_preset_id=_hex_id("execpreset_", 10),
            execution_preset_revision_id=_hex_id("execpresetrev_", 10),
            execution_preset_key=block.execution_preset_key,
            execution_preset_sha256=_sha(12),
            resolved_at=NOW,
        )

    def start(
        self,
        request: WorkflowStartRequest,
        actor: ActorContext,
        *,
        idempotency_key: str,
    ) -> WorkflowStartReceipt:
        assert actor.actor_id == OPERATOR_ID
        assert request.item_id is None and request.base_revision_id is None
        assert isinstance(request.item_brief, ContentTeamItemBriefRequestV3)
        assert request.item_brief.mock_exam_slot is not None
        assert request.registry_mode == "CREATE_ITEM"
        assert request.definition_key == "generic-item-development"
        assert request.definition_version == "1.8.0"
        assert request.production_occurrence is not None
        assert request.production_occurrence.production_request_id == PRODUCTION_REQUEST_ID
        assert request.expected_resolution is not None
        assert request.item_brief.authoring_guidance.startswith("검토된 요청 범위")
        self.start_requests.append(request)
        self.start_keys.append(idempotency_key)
        receipt = self._start_by_key.get(idempotency_key)
        if receipt is None:
            position = request.item_brief.mock_exam_slot.position
            workflow_id = _hex_id("workflow_", position)
            receipt = WorkflowStartReceipt(
                command_id=f"start-command-{position}",
                workflow_id=workflow_id,
                resource_version=1,
            )
            self._start_by_key[idempotency_key] = receipt
            self._position_by_workflow[workflow_id] = position
            self._request_by_workflow[workflow_id] = request
        if (
            self.lose_first_start_response
            and idempotency_key not in self._lost_keys
            and self._position_by_workflow[receipt.workflow_id] == 1
        ):
            self._lost_keys.add(idempotency_key)
            raise RuntimeError("simulated response loss")
        return receipt

    def get(self, workflow_id: str) -> WorkflowView:
        self.get_keys.append(workflow_id)
        position = self._position_by_workflow[workflow_id]
        request = self._request_by_workflow[workflow_id]
        assert request.expected_resolution is not None
        assert isinstance(request.item_brief, ContentTeamItemBriefRequestV3)
        selected_unit_key = request.item_brief.curriculum_selected_unit_key
        assert selected_unit_key is not None
        curriculum_root_key: str | None = resolve_integrated_science_curriculum_scope(
            selected_unit_key
        ).graph_root_stable_key
        if self.legacy_null_provenance_roots:
            curriculum_root_key = None
        elif position in self.provenance_root_drift_positions:
            curriculum_root_key = "curriculum.eom.editorial.integrated-science.tampered"
        completed = workflow_id in self._approved
        failed = position in self.workflow_failed_positions
        accepted_resolution = WorkflowAcceptedResolutionView.model_validate(
            request.expected_resolution.model_dump(mode="json")
        )
        if position in self.accepted_resolution_drift_positions:
            accepted_resolution = accepted_resolution.model_copy(
                update={"workflow_definition_sha256": _sha(999)}
            )
        return WorkflowView(
            workflow_id=workflow_id,
            definition_key="generic-item-development",
            definition_version="1.8.0",
            state=("FAILED" if failed else "COMPLETED" if completed else "AWAITING_HUMAN_APPROVAL"),
            stage="registration" if completed else "review",
            current_step_key="register" if completed else "review",
            resource_version=2 if completed else 1,
            rework_cycle_count=0,
            created_at=NOW,
            updated_at=NOW,
            completed_at=NOW if completed else None,
            failure_code="WORKFLOW_EXECUTION_FAILED" if failed else None,
            accepted_resolution=accepted_resolution,
            knowledge_provenance=WorkflowKnowledgeProvenanceView(
                plan_id=_hex_id("execplan_", position),
                plan_sha256=(
                    _sha(999)
                    if position in self.provenance_drift_positions
                    else _sha(50 + position)
                ),
                preset_revision_id=request.expected_resolution.execution_preset_revision_id,
                corpus_key="integrated-science-textbooks",
                query_kind="ITEM_PREPARATION",
                curriculum_root_key=curriculum_root_key,
                required_item_elements=("choice", "paragraph"),
                source_classes=("APPROVED_ITEM", "PAST_EXAM", "TEXTBOOK"),
                graph_snapshot_revision_id=_hex_id("graphrev_", 50 + position),
                evidence_bundle_revision_id=_hex_id("evidencerev_", 50 + position),
                retrieval_request_id=_hex_id("retrieval_", 50 + position),
                retrieval_request_sha256=_sha(150 + position),
                access_policy_revision_id=_hex_id("accessrev_", 50 + position),
                access_policy_sha256=_sha(250 + position),
                evidence_manifest_sha256=_sha(350 + position),
                resolved_at=self.provenance_resolved_at,
            ),
            item_registration=(
                WorkflowItemRegistrationView(
                    item_id=_hex_id("item_", position),
                    item_revision_id=_hex_id("itemrev_", position),
                    revision_number=1,
                    manifest_artifact_id=_hex_id("artifact_", 100 + position),
                    manifest_artifact_revision_id=_hex_id("rev_", 100 + position),
                    manifest_sha256=_sha(100 + position),
                )
                if completed
                else None
            ),
        )

    def review_eligibility(self, workflow_id: str) -> MockExamReviewEligibilityObservationV1:
        position = self._position_by_workflow[workflow_id]
        blocking = position in self.blocking_positions
        approved = workflow_id in self._approved
        return MockExamReviewEligibilityObservationV1(
            schema_version="mock-exam-review-eligibility/1.0",
            workflow_id=workflow_id,
            workflow_resource_version=2 if approved else 1,
            approval_request_id=_hex_id("approval_", position),
            approval_resource_version=2 if approved else 1,
            approval_state="APPROVED" if approved else "PENDING",
            reviewer_operator_id=self.approved_operator_id if approved else None,
            approved_at=self.approved_at if approved else None,
            eligibility="BLOCKED" if blocking else "ELIGIBLE",
            step_run_id=_hex_id("steprun_", position),
            artifact_id=_hex_id("artifact_", 200 + position),
            artifact_revision_id=_hex_id("rev_", 200 + position),
            sha256=_sha(200 + position),
            result_schema="review-result@8.0",
            worker_decision="ready_for_human",
            finding_info_count=0,
            finding_warning_count=0,
            finding_blocking_count=1 if blocking else 0,
        )

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
        assert actor.actor_id == OPERATOR_ID
        assert expected_version == 1
        position = self._position_by_workflow[workflow_id]
        assert approval_request_id == _hex_id("approval_", position)
        assert approval_resource_version == 1
        self.approval_keys.append(idempotency_key)
        self._approved.add(workflow_id)
        return WorkflowApprovalReceipt(
            command_id=f"approval-command-{self._position_by_workflow[workflow_id]}",
            resource_version=2,
        )

    @property
    def occurrence_count(self) -> int:
        return len(self._position_by_workflow)


class FakeAnalysisOperations:
    def __init__(
        self,
        *,
        review_positions: frozenset[int] = frozenset(),
        lose_first_review_response: bool = False,
    ) -> None:
        self.review_positions = review_positions
        self.lose_first_review_response = lose_first_review_response
        self.start_commands: list[Any] = []
        self.reconcile_commands: list[Any] = []
        self.review_commands: list[Any] = []
        self._source_by_run: dict[str, str] = {}
        self._reviewed: set[str] = set()
        self._lost_review_keys: set[str] = set()

    def start(self, command: Any) -> Any:
        self.start_commands.append(command)
        item_revision_id = command.source.item_revision_id
        position = int(item_revision_id.removeprefix("itemrev_"), 16)
        analysis_run_id = _hex_id("analysisrun_", position)
        self._source_by_run[analysis_run_id] = item_revision_id
        return self._view(analysis_run_id, "QUEUED")

    def reconcile(self, command: Any) -> Any:
        self.reconcile_commands.append(command)
        position = int(command.analysis_run_id.removeprefix("analysisrun_"), 16)
        state = (
            "NEEDS_REVIEW"
            if position in self.review_positions and command.analysis_run_id not in self._reviewed
            else "ACCEPTED"
        )
        return self._view(command.analysis_run_id, state)

    def review(self, command: Any) -> Any:
        self.review_commands.append(command)
        self._reviewed.add(command.analysis_run_id)
        result = self._view(
            command.analysis_run_id,
            "ACCEPTED" if command.decision == "APPROVE" else "REJECTED",
        )
        if (
            self.lose_first_review_response
            and command.idempotency_key not in self._lost_review_keys
        ):
            self._lost_review_keys.add(command.idempotency_key)
            raise RuntimeError("simulated analysis-review response loss")
        return result

    def get(self, analysis_run_id: str) -> Any:
        return self._view(analysis_run_id, "ACCEPTED")

    def _view(self, analysis_run_id: str, state: str) -> Any:
        position = int(analysis_run_id.removeprefix("analysisrun_"), 16)
        accepted = state == "ACCEPTED"
        return SimpleNamespace(
            analysis_run_id=analysis_run_id,
            request_sha256=_sha(300 + position),
            source_kind="APPROVED_ITEM_REVISION",
            source_revision_id=self._source_by_run[analysis_run_id],
            risk_policy_revision_id=ANALYSIS_POLICY.risk_policy_revision_id,
            risk_policy_sha256=ANALYSIS_POLICY.risk_policy_sha256,
            state=state,
            resource_version=2 if accepted else 1,
            accepted_result_artifact_id=(
                _hex_id("artifact_", 300 + position) if accepted else None
            ),
            accepted_result_artifact_revision_id=(
                _hex_id("rev_", 300 + position) if accepted else None
            ),
            accepted_result_sha256=_sha(400 + position) if accepted else None,
            error_code=None,
        )


class FakeGraphOperations:
    def __init__(
        self,
        *,
        lose_first_response: bool = False,
        stale_first_attempt: bool = False,
    ) -> None:
        self.commands: list[Any] = []
        self.lose_first_response = lose_first_response
        self.stale_first_attempt = stale_first_attempt
        self._result_by_key: dict[str, Any] = {}
        self._lost_keys: set[str] = set()
        self._stale_emitted = False

    def publish(self, command: Any) -> Any:
        self.commands.append(command)
        if self.stale_first_attempt and not self._stale_emitted:
            self._stale_emitted = True
            error = RuntimeError("simulated concurrent Graph advance")
            error.code = "KNOWLEDGE_GRAPH_STALE_CURRENT"  # type: ignore[attr-defined]
            raise error
        existing = self._result_by_key.get(command.idempotency_key)
        if existing is not None:
            return existing
        batch = len(self._result_by_key) + 1
        item_revision_ids = tuple(
            _hex_id(
                "itemrev_",
                int(run_id.removeprefix("analysisrun_"), 16),
            )
            for run_id in command.accepted_analysis_run_ids
        )
        result = SimpleNamespace(
            publication_id=_hex_id("graphpub_", batch),
            accepted_analysis_run_ids=command.accepted_analysis_run_ids,
            expected_workflow_ids=command.expected_workflow_ids,
            item_revision_ids=item_revision_ids,
            previous_graph_snapshot_revision_id=(
                command.expected_current_graph_snapshot_revision_id
            ),
            previous_graph_snapshot_sha256=(command.expected_current_graph_snapshot_sha256),
            graph_snapshot=SimpleNamespace(
                graph_snapshot_revision_id=_hex_id("graphrev_", 500 + batch)
            ),
            graph_snapshot_sha256=_sha(500 + batch),
            authorized_at=command.authorized_at,
            outcome="CREATED",
            result_sha256=_sha(600 + batch),
            published_at=command.authorized_at,
        )
        self._result_by_key[command.idempotency_key] = result
        if self.lose_first_response and command.idempotency_key not in self._lost_keys:
            self._lost_keys.add(command.idempotency_key)
            raise RuntimeError("simulated Graph publication response loss")
        return result


class FakeRatingOperations:
    def __init__(self) -> None:
        self.commands: list[Any] = []

    def publish(self, command: Any) -> Any:
        self.commands.append(command)
        position = int(command.item_revision_id.removeprefix("itemrev_"), 16)
        return SimpleNamespace(
            item_review_record_id=_hex_id("itemreview_", position),
            item_revision_id=command.item_revision_id,
            workflow_id=command.expected_workflow_id,
            human_approval_request_id=_hex_id("approval_", position),
            decision_sha256=_sha(700 + position),
            final_rating=command.final_rating,
            reviewer_operator_id=command.reviewer_operator_id,
            rating_policy_revision_id=command.rating_policy_revision_id,
            rating_policy_sha256=command.rating_policy_sha256,
        )


class FakeAssemblyOperations:
    def __init__(self) -> None:
        self.preview_requests: list[Any] = []
        self.create_requests: list[Any] = []
        self._preview: Any = None

    def preview(self, request: Any) -> Any:
        self.preview_requests.append(request)
        # The exact-cohort contract is added by the assembly boundary and consumed below once set.
        cohort = getattr(request, "cohort", None)
        if cohort is not None:
            item_revision_ids = tuple(row.item_revision_id for row in cohort.members)
        else:
            item_revision_ids = tuple(_hex_id("itemrev_", value) for value in range(1, 26))
        self._preview = SimpleNamespace(
            status="READY",
            placements=tuple(
                SimpleNamespace(
                    slot_id=f"slot-{position:02d}",
                    position=position,
                    item_id=_hex_id("item_", position),
                    item_revision_id=value,
                    item_manifest_sha256=_sha(850 + position),
                )
                for position, value in enumerate(item_revision_ids, start=1)
            ),
            plan_sha256=_sha(800),
            policy_revision_id=request.policy_revision_id,
            policy_sha256=request.policy_sha256,
            graph_snapshot_revision_id=request.graph_snapshot_revision_id,
            graph_snapshot_sha256=request.graph_snapshot_sha256,
            planned_at=NOW + timedelta(minutes=5),
            cohort=cohort,
        )
        return self._preview

    def create(
        self,
        request: Any,
        actor: ActorContext,
        *,
        idempotency_key: str,
    ) -> Any:
        assert actor.actor_id == OPERATOR_ID
        assert idempotency_key.startswith("mockexam:")
        self.create_requests.append(request)
        return SimpleNamespace(
            schema_version="mock-exam-assembly-manifest/2.0",
            plan=self._preview,
            assessment_assembly_id=_hex_id("assembly_", 1),
            assessment_assembly_revision_id=_hex_id("assemblyrev_", 1),
            deliverable_id=request.deliverable_id,
            deliverable_revision_id=request.deliverable_revision_id,
            form_key=request.form_key,
            display_label=request.display_label,
            created_by=actor.actor_id,
            manifest_sha256=_sha(801),
            created_at=NOW + timedelta(minutes=5),
        )


class FakeHwpxOperations:
    def __init__(self) -> None:
        self.starts: list[tuple[str, str, str]] = []
        self.view: Any = None

    def start(
        self,
        assembly_revision_id: str,
        *,
        operator_id: str,
        idempotency_key: str,
    ) -> Any:
        self.starts.append((assembly_revision_id, operator_id, idempotency_key))
        self.view = SimpleNamespace(
            build_id=_hex_id("hwpxbuild_", 1),
            assessment_assembly_id=_hex_id("assembly_", 1),
            assessment_assembly_revision_id=assembly_revision_id,
            assembly_manifest_sha256=_sha(801),
            policy_revision_id=_plan().policy_revision_id,
            policy_sha256=_plan().policy_sha256,
            graph_snapshot_revision_id=_hex_id("graphrev_", 501),
            graph_snapshot_sha256=_sha(501),
            item_set_sha256=_fake_assembly_item_set_sha256(),
            renderer="content-team-exam",
            renderer_version="2.0.0",
            state=HwpxBuildState.SUCCEEDED,
            validation_state=HwpxValidationState.PASS,
            item_count=25,
            section_count=25,
            output_artifact_id=_hex_id("artifact_", 900),
            output_artifact_revision_id=_hex_id("rev_", 900),
            output_sha256=_sha(900),
            download_available=True,
            resource_version=2,
            failure_code=None,
            created_by_operator_id=operator_id,
            created_at=NOW + timedelta(minutes=6),
            completed_at=NOW + timedelta(minutes=6),
        )
        return self.view

    def get(self, build_id: str) -> Any:
        assert self.view is not None and self.view.build_id == build_id
        return self.view


def _coordinator(
    *,
    workflows: FakeWorkflowOperations | None = None,
    analyses: FakeAnalysisOperations | None = None,
    graph: FakeGraphOperations | None = None,
) -> tuple[
    MockExamProductionCoordinator,
    FakeWorkflowOperations,
    FakeAnalysisOperations,
    FakeGraphOperations,
    FakeRatingOperations,
    FakeAssemblyOperations,
    FakeHwpxOperations,
]:
    workflow_ops = workflows or FakeWorkflowOperations()
    analysis_ops = analyses or FakeAnalysisOperations()
    graph_ops = graph or FakeGraphOperations()
    ratings = FakeRatingOperations()
    assemblies = FakeAssemblyOperations()
    hwpx = FakeHwpxOperations()
    coordinator = MockExamProductionCoordinator(
        workflows=workflow_ops,
        analyses=analysis_ops,
        graph=graph_ops,
        ratings=ratings,
        assemblies=assemblies,
        hwpx=hwpx,
    )
    return coordinator, workflow_ops, analysis_ops, graph_ops, ratings, assemblies, hwpx


def _registered_checkpoint(
    coordinator: MockExamProductionCoordinator,
    workflows: FakeWorkflowOperations,
    *,
    registered_at: datetime = NOW + timedelta(seconds=1),
) -> tuple[MockExamProductionPlanV1, MockExamProductionExecutionV1]:
    plan = _plan()
    checkpoint = coordinator.initialize(
        plan,
        production_request_id=PRODUCTION_REQUEST_ID,
        operator_id=OPERATOR_ID,
        at=NOW,
    )
    checkpoint = coordinator.advance_items(plan, checkpoint, _actor(), at=NOW)
    assert checkpoint.generation_block_resolution is not None
    checkpoint = coordinator.advance_items(plan, checkpoint, _actor(), at=NOW)
    assert all(row.state == "APPROVAL_SUBMITTED" for row in checkpoint.item_runs)
    checkpoint = coordinator.advance_items(plan, checkpoint, _actor(), at=registered_at)
    assert all(row.state == "REGISTERED" for row in checkpoint.item_runs)
    assert workflows.occurrence_count == 25
    return plan, checkpoint


def test_exact_25_new_workflows_then_full_pointer_pipeline() -> None:
    (
        coordinator,
        workflows,
        analyses,
        graph,
        ratings,
        assemblies,
        hwpx,
    ) = _coordinator()
    plan, checkpoint = _registered_checkpoint(coordinator, workflows)

    assert len(workflows.start_keys) == len(set(workflows.start_keys)) == 25
    assert tuple(
        request.item_brief.mock_exam_slot.position  # type: ignore[union-attr]
        for request in workflows.start_requests
    ) == tuple(range(1, 26))
    assert tuple(
        request.production_occurrence.workflow_call_id  # type: ignore[union-attr]
        for request in workflows.start_requests
    ) == tuple(call.workflow_call_id for call in plan.workflow_calls)
    assert all(request.expected_resolution is not None for request in workflows.start_requests)
    assert all(row.registration is not None for row in checkpoint.item_runs)
    assert all(row.human_approval is not None for row in checkpoint.item_runs)
    assert all(row.knowledge_provenance is not None for row in checkpoint.item_runs)

    checkpoint = coordinator.advance_analyses(
        plan,
        checkpoint,
        _actor(),
        ANALYSIS_POLICY,
        at=NOW + timedelta(minutes=1),
    )
    checkpoint = coordinator.advance_analyses(
        plan,
        checkpoint,
        _actor(),
        ANALYSIS_POLICY,
        at=NOW + timedelta(minutes=1),
    )
    assert len(analyses.start_commands) == len(analyses.reconcile_commands) == 25
    assert all(row.state == "ANALYSIS_ACCEPTED" for row in checkpoint.item_runs)

    checkpoint = coordinator.publish_next_graph_batch(
        plan,
        checkpoint,
        _actor(),
        GRAPH_INPUT,
        at=NOW + timedelta(minutes=2),
    )
    assert checkpoint.graph_publication_authorization is not None
    assert graph.commands == []
    checkpoint = coordinator.publish_next_graph_batch(
        plan,
        checkpoint,
        _actor(),
        GRAPH_INPUT,
        at=NOW + timedelta(minutes=3),
    )
    assert tuple(len(command.accepted_analysis_run_ids) for command in graph.commands) == (25,)
    assert graph.commands[0].expected_workflow_ids == tuple(
        row.workflow_id for row in checkpoint.item_runs
    )
    assert graph.commands[0].authorized_at == NOW
    assert len(checkpoint.graph_publications) == 1

    assignments = tuple(
        MockExamExplicitRatingV1(
            workflow_call_id=row.workflow_call_id,
            position=row.position,
            item_revision_id=row.registration.item_revision_id,  # type: ignore[union-attr]
            final_rating="C",
        )
        for row in checkpoint.item_runs
    )
    explicit_ratings = build_mock_exam_explicit_rating_set(
        execution_id=checkpoint.execution_id,
        operator_id=OPERATOR_ID,
        assignments=assignments,
        authorized_at=NOW + timedelta(minutes=4),
    )
    checkpoint = coordinator.publish_ratings(
        plan,
        checkpoint,
        _actor(),
        explicit_ratings,
        RATING_POLICY,
        at=NOW + timedelta(minutes=4),
    )
    assert checkpoint.rating_authorization is not None
    assert ratings.commands == []
    checkpoint = coordinator.publish_ratings(
        plan,
        checkpoint,
        _actor(),
        explicit_ratings,
        RATING_POLICY,
        at=NOW + timedelta(minutes=4),
    )
    assert len(ratings.commands) == 25
    assert tuple(command.final_rating for command in ratings.commands) == ("C",) * 25
    assert tuple(command.expected_workflow_id for command in ratings.commands) == tuple(
        row.workflow_id for row in checkpoint.item_runs
    )

    assembly_observed_at = NOW + timedelta(minutes=4, seconds=59)
    checkpoint = coordinator.advance_assembly(
        plan,
        checkpoint,
        _actor(),
        MockExamAssemblyIntentV1(
            deliverable_id=_hex_id("deliverable_", 1),
            deliverable_revision_id=_hex_id("delivrev_", 1),
            form_key="sample-2026-09",
            display_label="통합과학 샘플 모의고사",
        ),
        at=assembly_observed_at,
    )
    assert checkpoint.assembly_intent is not None
    assert assemblies.preview_requests == assemblies.create_requests == []
    checkpoint = coordinator.advance_assembly(
        plan,
        checkpoint,
        _actor(),
        checkpoint.assembly_intent,
        at=assembly_observed_at,
    )
    assert checkpoint.assembly_plan is not None
    assert len(assemblies.preview_requests) == 1
    assert assemblies.create_requests == []
    checkpoint = coordinator.advance_assembly(
        plan,
        checkpoint,
        _actor(),
        checkpoint.assembly_intent,
        at=assembly_observed_at,
    )
    assert checkpoint.assembly is not None
    assert len(assemblies.preview_requests) == len(assemblies.create_requests) == 1
    preview_cohort = assemblies.preview_requests[0].cohort
    create_cohort = assemblies.create_requests[0].cohort
    assert preview_cohort == create_cohort
    assert tuple(row.item_revision_id for row in preview_cohort.members) == tuple(
        row.registration.item_revision_id  # type: ignore[union-attr]
        for row in checkpoint.item_runs
    )
    assert checkpoint.assembly_plan is not None
    assert checkpoint.assembly_plan.cohort_sha256 == preview_cohort.cohort_sha256
    assert checkpoint.checkpointed_at == NOW + timedelta(minutes=5)
    assembled = checkpoint
    checkpoint = coordinator.advance_assembly(
        plan,
        checkpoint,
        _actor(),
        checkpoint.assembly_intent,
        at=assembly_observed_at,
    )
    assert checkpoint == assembled
    assert len(assemblies.create_requests) == 1

    hwpx_observed_at = NOW + timedelta(minutes=5, seconds=59)
    checkpoint = coordinator.advance_hwpx(
        plan,
        checkpoint,
        _actor(),
        at=hwpx_observed_at,
    )
    assert checkpoint.state == "COMPLETED"
    assert checkpoint.hwpx_build is not None
    assert checkpoint.hwpx_build.item_count == checkpoint.hwpx_build.section_count == 25
    assert checkpoint.checkpointed_at == NOW + timedelta(minutes=6)
    assert len(hwpx.starts) == 1
    completed = checkpoint
    checkpoint = coordinator.advance_hwpx(
        plan,
        checkpoint,
        _actor(),
        at=hwpx_observed_at,
    )
    assert checkpoint == completed
    assert len(hwpx.starts) == 1

    assert not _monotonic_successor(
        completed, completed.model_copy(update={"graph_publications": ()})
    )
    substituted_graph = completed.graph_publications[0].model_copy(
        update={"publication_id": _hex_id("graphpub_", 99)}
    )
    assert not _monotonic_successor(
        completed,
        completed.model_copy(update={"graph_publications": (substituted_graph,)}),
    )
    assert not _monotonic_successor(completed, completed.model_copy(update={"hwpx_build": None}))
    for field in (
        "rating_authorization",
        "assembly_intent",
        "assembly_plan",
        "assembly",
    ):
        assert not _monotonic_successor(
            completed,
            completed.model_copy(update={field: None}),
        )
    assert completed.hwpx_build is not None
    with pytest.raises(ValidationError, match="download"):
        type(completed.hwpx_build).model_validate(
            completed.hwpx_build.model_dump(mode="json") | {"download_available": False}
        )
    hwpx.view.item_set_sha256 = _sha(998)
    mismatched_hwpx = coordinator.advance_hwpx(
        plan,
        completed,
        _actor(),
        at=NOW + timedelta(minutes=7),
    )
    assert mismatched_hwpx.hwpx_build == completed.hwpx_build
    assert mismatched_hwpx.failure is not None
    assert mismatched_hwpx.failure.code == "HWPX_ITEM_SET_POINTER_MISMATCH"

    assert completed.graph_publication_authorization is not None
    backdated_graph_authorization = completed.graph_publication_authorization.model_dump(
        mode="json", exclude={"authorization_sha256"}
    ) | {"authorized_at": (NOW - timedelta(seconds=1)).isoformat().replace("+00:00", "Z")}
    backdated_graph_authorization["authorization_sha256"] = content_sha256(
        backdated_graph_authorization
    )
    tampered = completed.model_dump(mode="json")
    tampered["graph_publication_authorization"] = backdated_graph_authorization
    with pytest.raises(ValidationError, match="authorization precedes"):
        type(completed).model_validate(tampered)


def test_stale_graph_base_requires_explicit_write_ahead_supersession() -> None:
    graph = FakeGraphOperations(stale_first_attempt=True)
    coordinator, workflows, _analyses, _, _, _, _ = _coordinator(graph=graph)
    plan, checkpoint = _registered_checkpoint(coordinator, workflows)
    checkpoint = coordinator.advance_analyses(
        plan,
        checkpoint,
        _actor(),
        ANALYSIS_POLICY,
        at=NOW + timedelta(minutes=1),
    )
    checkpoint = coordinator.advance_analyses(
        plan,
        checkpoint,
        _actor(),
        ANALYSIS_POLICY,
        at=NOW + timedelta(minutes=1),
    )

    pinned = coordinator.publish_next_graph_batch(
        plan,
        checkpoint,
        _actor(),
        GRAPH_INPUT,
        at=NOW + timedelta(minutes=2),
    )
    stale = coordinator.publish_next_graph_batch(
        plan,
        pinned,
        _actor(),
        GRAPH_INPUT,
        at=NOW + timedelta(minutes=3),
    )
    assert stale.failure is not None
    assert stale.failure.code == "KNOWLEDGE_GRAPH_STALE_CURRENT"
    assert stale.graph_publications == ()
    assert len(graph.commands) == 1

    replacement_value = {
        "current_graph_snapshot_revision_id": _hex_id("graphrev_", 777),
        "current_graph_snapshot_sha256": _sha(777),
        "access_policy_revision_id": GRAPH_INPUT.access_policy_revision_id,
        "access_policy_sha256": GRAPH_INPUT.access_policy_sha256,
        "authorized_at": (NOW + timedelta(minutes=4)).isoformat().replace("+00:00", "Z"),
        "supersedes_authorization_sha256": GRAPH_INPUT.authorization_sha256,
    }
    replacement = MockExamGraphPublicationInputV1.model_validate(
        {
            **replacement_value,
            "authorization_sha256": content_sha256(replacement_value),
        }
    )
    replacement_without_link_value = {
        **replacement_value,
        "supersedes_authorization_sha256": None,
    }
    replacement_without_link = MockExamGraphPublicationInputV1.model_validate(
        {
            **replacement_without_link_value,
            "authorization_sha256": content_sha256(replacement_without_link_value),
        }
    )
    with pytest.raises(
        MockExamProductionCoordinatorError,
        match="pinned Graph publication authorization",
    ):
        coordinator.publish_next_graph_batch(
            plan,
            stale,
            _actor(),
            replacement_without_link,
            at=NOW + timedelta(minutes=4),
        )

    rebased = coordinator.publish_next_graph_batch(
        plan,
        stale,
        _actor(),
        replacement,
        at=NOW + timedelta(minutes=4),
    )
    assert rebased.graph_publication_authorization is not None
    assert rebased.graph_publication_authorization.model_dump(
        mode="json"
    ) == replacement.model_dump(mode="json")
    assert rebased.failure is None
    assert rebased.graph_publications == ()
    assert len(graph.commands) == 1
    assert _monotonic_successor(stale, rebased)

    published = coordinator.publish_next_graph_batch(
        plan,
        rebased,
        _actor(),
        replacement,
        at=NOW + timedelta(minutes=5),
    )
    assert len(published.graph_publications) == 1
    assert len(graph.commands) == 2
    assert graph.commands[0].idempotency_key != graph.commands[1].idempotency_key
    assert published.graph_publications[0].previous_graph_snapshot_revision_id == _hex_id(
        "graphrev_", 777
    )
    assert not _monotonic_successor(
        stale,
        rebased.model_copy(
            update={
                "graph_publications": published.graph_publications,
                "item_runs": published.item_runs,
            }
        ),
    )


def test_graph_response_loss_replays_exact_authorized_atomic_25_command(
    tmp_path: Path,
) -> None:
    graph = FakeGraphOperations(lose_first_response=True)
    coordinator, _workflows, _, _, _, _, _ = _coordinator(graph=graph)
    store = AtomicJsonMockExamProductionCheckpointStore(tmp_path / "graph-checkpoints")
    runner = MockExamProductionRunner(coordinator=coordinator, checkpoints=store)
    plan = _plan()
    checkpoint = runner.initialize(
        plan,
        _actor(),
        production_request_id=PRODUCTION_REQUEST_ID,
        at=NOW,
    )
    for seconds in (1, 2, 3):
        checkpoint = runner.advance_items(
            plan,
            checkpoint.execution_id,
            _actor(),
            at=NOW + timedelta(seconds=seconds),
        )
    for seconds in (4, 5):
        checkpoint = runner.advance_analyses(
            plan,
            checkpoint.execution_id,
            _actor(),
            ANALYSIS_POLICY,
            at=NOW + timedelta(seconds=seconds),
        )

    pinned = runner.publish_next_graph_batch(
        plan,
        checkpoint.execution_id,
        _actor(),
        GRAPH_INPUT,
        at=NOW + timedelta(minutes=2),
    )
    assert pinned.graph_publication_authorization is not None
    assert graph.commands == []
    restarted = MockExamProductionRunner(coordinator=coordinator, checkpoints=store)
    failed = restarted.publish_next_graph_batch(
        plan,
        pinned.execution_id,
        _actor(),
        GRAPH_INPUT,
        at=NOW + timedelta(minutes=2),
    )
    assert failed.failure is not None
    restarted = MockExamProductionRunner(coordinator=coordinator, checkpoints=store)
    replayed = restarted.publish_next_graph_batch(
        plan,
        failed.execution_id,
        _actor(),
        GRAPH_INPUT,
        at=NOW + timedelta(minutes=3),
    )

    assert replayed.failure is None
    assert len(replayed.graph_publications) == 1
    assert len(graph.commands) == 2
    assert graph.commands[0].submission_sha256 == graph.commands[1].submission_sha256
    assert graph.commands[0].authorized_at == graph.commands[1].authorized_at == NOW
    assert graph.commands[0].expected_workflow_ids == graph.commands[1].expected_workflow_ids


def test_graph_authorization_is_self_hashed_and_within_execution_timeline() -> None:
    invalid = GRAPH_INPUT.model_dump(mode="json")
    invalid["authorized_at"] = (NOW + timedelta(hours=1)).isoformat().replace("+00:00", "Z")
    with pytest.raises(ValidationError, match="authorization SHA-256"):
        MockExamGraphPublicationInputV1.model_validate(invalid)

    coordinator, workflows, _, graph, _, _, _ = _coordinator()
    plan, checkpoint = _registered_checkpoint(coordinator, workflows)
    checkpoint = coordinator.advance_analyses(
        plan, checkpoint, _actor(), ANALYSIS_POLICY, at=NOW + timedelta(minutes=1)
    )
    checkpoint = coordinator.advance_analyses(
        plan, checkpoint, _actor(), ANALYSIS_POLICY, at=NOW + timedelta(minutes=1)
    )
    with pytest.raises(Exception, match="authorization must follow"):
        coordinator.publish_next_graph_batch(
            plan,
            checkpoint,
            _actor(),
            _graph_input(NOW + timedelta(minutes=3)),
            at=NOW + timedelta(minutes=2),
        )
    assert graph.commands == []


def test_graph_authorization_cannot_predate_any_item_approval() -> None:
    approval_at = NOW + timedelta(seconds=10)
    workflows = FakeWorkflowOperations(approved_at=approval_at)
    coordinator, *_ = _coordinator(workflows=workflows)
    plan, checkpoint = _registered_checkpoint(
        coordinator,
        workflows,
        registered_at=approval_at + timedelta(seconds=1),
    )
    checkpoint = coordinator.advance_analyses(
        plan,
        checkpoint,
        _actor(),
        ANALYSIS_POLICY,
        at=approval_at + timedelta(seconds=2),
    )
    checkpoint = coordinator.advance_analyses(
        plan,
        checkpoint,
        _actor(),
        ANALYSIS_POLICY,
        at=approval_at + timedelta(seconds=3),
    )

    with pytest.raises(Exception, match="authorization must follow"):
        coordinator.publish_next_graph_batch(
            plan,
            checkpoint,
            _actor(),
            _graph_input(NOW + timedelta(seconds=5)),
            at=approval_at + timedelta(seconds=4),
        )


def test_start_response_loss_resumes_same_idempotent_occurrence() -> None:
    workflows = FakeWorkflowOperations(lose_first_start_response=True)
    coordinator, *_ = _coordinator(workflows=workflows)
    plan = _plan()
    checkpoint = coordinator.initialize(
        plan,
        production_request_id=PRODUCTION_REQUEST_ID,
        operator_id=OPERATOR_ID,
        at=NOW,
    )
    checkpoint = coordinator.advance_items(plan, checkpoint, _actor(), at=NOW)
    checkpoint = coordinator.advance_items(plan, checkpoint, _actor(), at=NOW)
    assert checkpoint.item_runs[0].state == "START_UNCONFIRMED"
    first_key = workflows.start_keys[0]

    checkpoint = coordinator.advance_items(
        plan, checkpoint, _actor(), at=NOW + timedelta(seconds=1)
    )
    assert workflows.start_keys.count(first_key) == 2
    assert len(set(workflows.start_keys)) == 25
    assert workflows.occurrence_count == 25
    assert checkpoint.item_runs[0].state == "APPROVAL_SUBMITTED"


def test_workflow_resolution_drift_blocks_before_approval() -> None:
    workflows = FakeWorkflowOperations(accepted_resolution_drift_positions=frozenset({1}))
    coordinator, *_ = _coordinator(workflows=workflows)
    plan = _plan()
    checkpoint = coordinator.initialize(
        plan,
        production_request_id=PRODUCTION_REQUEST_ID,
        operator_id=OPERATOR_ID,
        at=NOW,
    )

    checkpoint = coordinator.advance_items(plan, checkpoint, _actor(), at=NOW)
    checkpoint = coordinator.advance_items(plan, checkpoint, _actor(), at=NOW)

    drifted = checkpoint.item_runs[0]
    assert drifted.state == "FAILED"
    assert drifted.failure is not None
    assert drifted.failure.code == "WORKFLOW_ACCEPTED_RESOLUTION_MISMATCH"
    assert _hex_id("workflow_", 1) not in workflows._approved


def test_historical_curriculum_root_false_negative_recovers_exact_cohort_without_restart(
    tmp_path: Path,
) -> None:
    workflows = FakeWorkflowOperations(legacy_null_provenance_roots=True)
    coordinator, *_ = _coordinator(workflows=workflows)
    store = AtomicJsonMockExamProductionCheckpointStore(tmp_path / "provenance-recovery")
    runner = MockExamProductionRunner(coordinator=coordinator, checkpoints=store)
    plan = _plan()
    checkpoint = runner.initialize(
        plan,
        _actor(),
        production_request_id=PRODUCTION_REQUEST_ID,
        at=NOW,
    )
    checkpoint = runner.advance_items(
        plan, checkpoint.execution_id, _actor(), at=NOW + timedelta(seconds=1)
    )
    failed = runner.advance_items(
        plan, checkpoint.execution_id, _actor(), at=NOW + timedelta(seconds=2)
    )

    assert all(row.state == "FAILED" for row in failed.item_runs)
    assert all(
        row.failure is not None
        and row.failure.code == "WORKFLOW_KNOWLEDGE_PROVENANCE_MISMATCH"
        and not row.failure.retryable
        for row in failed.item_runs
    )
    # Deployment admission deliberately retains the historical terminal classification so an
    # emergency recovery release cannot strand itself between installation attempts.
    assert mock_exam_production_is_terminal(failed) is True
    assert len(workflows.start_keys) == 25
    assert workflows.approval_keys == []
    failed_revision_path = (
        tmp_path
        / "provenance-recovery"
        / failed.execution_id
        / f"{failed.execution_revision_id}.json"
    )
    assert failed_revision_path.is_file()

    workflows.legacy_null_provenance_roots = False
    recovered = runner.advance_items(
        plan, failed.execution_id, _actor(), at=NOW + timedelta(seconds=3)
    )

    assert recovered.predecessor_execution_revision_id == failed.execution_revision_id
    assert all(row.state == "WORKFLOW_ACTIVE" for row in recovered.item_runs)
    assert all(row.failure is None for row in recovered.item_runs)
    expected_roots = {
        call.workflow_call_id: resolve_integrated_science_curriculum_scope(
            call.item_brief.curriculum_selected_unit_key
        ).graph_root_stable_key
        for call in plan.workflow_calls
    }
    assert all(
        row.knowledge_provenance is not None
        and row.knowledge_provenance.curriculum_root_key == expected_roots[row.workflow_call_id]
        for row in recovered.item_runs
    )
    assert len(workflows.start_keys) == 25
    assert workflows.approval_keys == []
    assert _monotonic_successor(failed, recovered)
    assert failed_revision_path.is_file()
    partial = recovered.model_copy(
        update={"item_runs": (recovered.item_runs[0], *failed.item_runs[1:])}
    )
    assert not _monotonic_successor(failed, partial)
    policy_smuggling = recovered.model_copy(
        update={
            "analysis_policy": ANALYSIS_POLICY,
            "analysis_general_knowledge_mode": "DISABLED",
        }
    )
    assert not _monotonic_successor(failed, policy_smuggling)

    advanced = runner.advance_items(
        plan, recovered.execution_id, _actor(), at=NOW + timedelta(seconds=4)
    )
    assert all(row.state == "APPROVAL_SUBMITTED" for row in advanced.item_runs)
    assert len(workflows.start_keys) == 25
    assert len(workflows.approval_keys) == 25


def test_provenance_recovery_root_mismatch_is_atomic_and_resumable(tmp_path: Path) -> None:
    workflows = FakeWorkflowOperations(legacy_null_provenance_roots=True)
    coordinator, *_ = _coordinator(workflows=workflows)
    store = AtomicJsonMockExamProductionCheckpointStore(tmp_path / "provenance-recovery-mismatch")
    runner = MockExamProductionRunner(coordinator=coordinator, checkpoints=store)
    plan = _plan()
    checkpoint = runner.initialize(
        plan,
        _actor(),
        production_request_id=PRODUCTION_REQUEST_ID,
        at=NOW,
    )
    checkpoint = runner.advance_items(plan, checkpoint.execution_id, _actor(), at=NOW)
    failed = runner.advance_items(plan, checkpoint.execution_id, _actor(), at=NOW)
    workflows.legacy_null_provenance_roots = False
    workflows.provenance_root_drift_positions.add(13)

    with pytest.raises(MockExamProductionCoordinatorError) as captured:
        runner.advance_items(plan, failed.execution_id, _actor(), at=NOW + timedelta(seconds=1))

    assert captured.value.code == "WORKFLOW_KNOWLEDGE_PROVENANCE_MISMATCH"
    assert store.load(failed.execution_id) == failed
    assert all(row.state == "FAILED" for row in store.load(failed.execution_id).item_runs)
    assert len(workflows.start_keys) == 25
    assert workflows.approval_keys == []

    workflows.provenance_root_drift_positions.clear()
    recovered = runner.advance_items(
        plan, failed.execution_id, _actor(), at=NOW + timedelta(seconds=2)
    )
    assert all(row.state == "WORKFLOW_ACTIVE" for row in recovered.item_runs)
    assert len(workflows.start_keys) == 25
    assert workflows.approval_keys == []


def test_unrelated_terminal_workflow_failures_are_never_reopened() -> None:
    workflows = FakeWorkflowOperations(workflow_failed_positions=frozenset(range(1, 26)))
    coordinator, *_ = _coordinator(workflows=workflows)
    plan = _plan()
    checkpoint = coordinator.initialize(
        plan,
        production_request_id=PRODUCTION_REQUEST_ID,
        operator_id=OPERATOR_ID,
        at=NOW,
    )
    checkpoint = coordinator.advance_items(plan, checkpoint, _actor(), at=NOW)
    failed = coordinator.advance_items(plan, checkpoint, _actor(), at=NOW)
    get_count = len(workflows.get_keys)

    unchanged = coordinator.advance_items(plan, failed, _actor(), at=NOW + timedelta(seconds=1))

    assert unchanged == failed
    assert all(
        row.state == "FAILED"
        and row.failure is not None
        and row.failure.code == "WORKFLOW_EXECUTION_FAILED"
        for row in unchanged.item_runs
    )
    assert len(workflows.get_keys) == get_count
    assert len(workflows.start_keys) == 25
    assert workflows.approval_keys == []
    forged_recovery = failed.model_copy(
        update={
            "item_runs": tuple(
                row.model_copy(update={"state": "WORKFLOW_ACTIVE", "failure": None})
                for row in failed.item_runs
            )
        }
    )
    assert not _monotonic_successor(failed, forged_recovery)


def test_checkpointed_knowledge_provenance_cannot_change_after_approval() -> None:
    workflows = FakeWorkflowOperations()
    coordinator, *_ = _coordinator(workflows=workflows)
    plan = _plan()
    checkpoint = coordinator.initialize(
        plan,
        production_request_id=PRODUCTION_REQUEST_ID,
        operator_id=OPERATOR_ID,
        at=NOW,
    )
    checkpoint = coordinator.advance_items(plan, checkpoint, _actor(), at=NOW)
    checkpoint = coordinator.advance_items(plan, checkpoint, _actor(), at=NOW)
    original = checkpoint.item_runs[0].knowledge_provenance
    assert original is not None
    workflows.provenance_drift_positions.add(1)

    checkpoint = coordinator.advance_items(
        plan, checkpoint, _actor(), at=NOW + timedelta(seconds=1)
    )

    drifted = checkpoint.item_runs[0]
    assert drifted.state == "FAILED"
    assert drifted.failure is not None
    assert drifted.failure.code == "WORKFLOW_KNOWLEDGE_PROVENANCE_CHANGED"
    assert drifted.knowledge_provenance == original
    assert drifted.registration is None


def test_blocking_review_is_never_approved_or_registered() -> None:
    workflows = FakeWorkflowOperations(blocking_positions=frozenset({1}))
    coordinator, *_ = _coordinator(workflows=workflows)
    plan = _plan()
    checkpoint = coordinator.initialize(
        plan,
        production_request_id=PRODUCTION_REQUEST_ID,
        operator_id=OPERATOR_ID,
        at=NOW,
    )
    checkpoint = coordinator.advance_items(plan, checkpoint, _actor(), at=NOW)
    checkpoint = coordinator.advance_items(plan, checkpoint, _actor(), at=NOW)
    blocked = checkpoint.item_runs[0]
    assert checkpoint.state == "BLOCKED"
    assert blocked.state == "REVIEW_BLOCKED"
    assert blocked.review is None and blocked.registration is None
    assert len(workflows.approval_keys) == 24


def test_postapproval_evidence_requires_the_same_operator() -> None:
    workflows = FakeWorkflowOperations(approved_operator_id="operator_" + "9" * 32)
    coordinator, *_ = _coordinator(workflows=workflows)
    plan = _plan()
    checkpoint = coordinator.initialize(
        plan,
        production_request_id=PRODUCTION_REQUEST_ID,
        operator_id=OPERATOR_ID,
        at=NOW,
    )
    checkpoint = coordinator.advance_items(plan, checkpoint, _actor(), at=NOW)
    checkpoint = coordinator.advance_items(plan, checkpoint, _actor(), at=NOW)
    checkpoint = coordinator.advance_items(
        plan, checkpoint, _actor(), at=NOW + timedelta(seconds=1)
    )
    assert checkpoint.state == "BLOCKED"
    assert all(row.state == "FAILED" for row in checkpoint.item_runs)
    assert all(row.registration is None for row in checkpoint.item_runs)
    assert all(
        row.failure is not None and row.failure.code == "WORKFLOW_APPROVER_MISMATCH"
        for row in checkpoint.item_runs
    )


def test_catalog_review_reader_projects_pending_and_approved_gate_atomically() -> None:
    pending = MockExamReviewEligibilityResult(
        workflow_id=_hex_id("workflow_", 1),
        workflow_lock_version=4,
        approval_request_id=_hex_id("approval_", 1),
        approval_lock_version=2,
        approval_state="PENDING",
        reviewer_operator_id=None,
        approved_at=None,
        review_step_run_id=_hex_id("steprun_", 1),
        review_artifact_id=_hex_id("artifact_", 1),
        review_artifact_revision_id=_hex_id("rev_", 1),
        review_sha256=_sha(1),
        review_result_schema="review-result@8.0",
        decision="ready_for_human",
        review_summary="zero blocking",
        findings=(),
        finding_counts=MockExamEligibilityFindingCounts(info=0, warning=0, blocking=0),
        eligible=True,
        eligibility_reason="ELIGIBLE",
    )

    class Catalog:
        def __init__(self, result: MockExamReviewEligibilityResult) -> None:
            self.result = result

        def inspect_mock_exam_review_eligibility(self, query: Any) -> Any:
            assert query.workflow_id == self.result.workflow_id
            return self.result

    catalog = Catalog(pending)
    reader = CatalogReviewEligibilityReader(catalog)
    observation = reader.review_eligibility(pending.workflow_id)
    assert observation.approval_state == "PENDING"
    assert observation.approved_pointer().approval_request_id == pending.approval_request_id
    with pytest.raises(ValueError, match="pending approval"):
        observation.human_approval_pointer()

    catalog.result = pending.model_copy(
        update={
            "workflow_lock_version": 5,
            "approval_lock_version": 3,
            "approval_state": "APPROVED",
            "reviewer_operator_id": OPERATOR_ID,
            "approved_at": NOW,
        }
    )
    approved = reader.review_eligibility(pending.workflow_id)
    assert approved.human_approval_pointer().reviewer_operator_id == OPERATOR_ID


def test_existing_workflow_adapter_pins_observed_approval_expectation() -> None:
    captured: dict[str, Any] = {}

    class Commands:
        def start_workflow(self, *args: Any, **kwargs: Any) -> Any:
            raise AssertionError("not used")

        def workflow_action(
            self,
            workflow_id: str,
            action: Any,
            request: Any,
            actor: ActorContext,
            **kwargs: Any,
        ) -> tuple[str, int]:
            captured.update(
                workflow_id=workflow_id,
                action=action,
                request=request,
                actor=actor,
                kwargs=kwargs,
            )
            return "approval-command", 8

    class Queries:
        def workflow(self, workflow_id: str) -> Any:
            raise AssertionError("not used")

    class Resolver:
        def resolve_generation_block(self, block: Any) -> Any:
            raise AssertionError("not used")

    class Evidence:
        def review_eligibility(self, workflow_id: str) -> Any:
            raise AssertionError("not used")

    operations = ExistingOneItemWorkflowOperations(
        Commands(),
        Queries(),
        Resolver(),
        Evidence(),  # type: ignore[arg-type]
    )
    workflow_id = _hex_id("workflow_", 1)
    approval_request_id = _hex_id("approval_", 1)
    receipt = operations.approve(
        workflow_id,
        _actor(),
        expected_version=7,
        approval_request_id=approval_request_id,
        approval_resource_version=3,
        idempotency_key="approval-key",
    )

    expectation = captured["request"].approval_expectation
    assert receipt.resource_version == 8
    assert expectation.approval_request_id == approval_request_id
    assert expectation.approval_resource_version == 3
    assert captured["kwargs"] == {
        "expected_version": 7,
        "idempotency_key": "approval-key",
    }


def test_analysis_needs_review_resumes_only_from_explicit_operator_decision() -> None:
    analyses = FakeAnalysisOperations(review_positions=frozenset({1}))
    coordinator, workflows, *_ = _coordinator(analyses=analyses)
    plan, checkpoint = _registered_checkpoint(coordinator, workflows)
    checkpoint = coordinator.advance_analyses(
        plan,
        checkpoint,
        _actor(),
        ANALYSIS_POLICY,
        at=NOW + timedelta(minutes=1),
    )
    checkpoint = coordinator.advance_analyses(
        plan,
        checkpoint,
        _actor(),
        ANALYSIS_POLICY,
        at=NOW + timedelta(minutes=1),
    )
    review_required = checkpoint.item_runs[0]
    assert checkpoint.state == "BLOCKED"
    assert review_required.state == "ANALYSIS_REVIEW_REQUIRED"
    assert review_required.analysis is not None
    assert analyses.review_commands == []

    review_set = build_mock_exam_explicit_analysis_review_set(
        execution_id=checkpoint.execution_id,
        operator_id=OPERATOR_ID,
        assignments=(
            MockExamExplicitAnalysisReviewV1(
                workflow_call_id=review_required.workflow_call_id,
                position=review_required.position,
                analysis_run_id=review_required.analysis.analysis_run_id,
                expected_resource_version=review_required.analysis.resource_version,
                decision="APPROVE",
                notes="샘플 운영자가 검토 결과를 명시적으로 승인함",
            ),
        ),
        authorized_at=NOW + timedelta(minutes=2),
    )
    checkpoint = coordinator.review_analyses(
        plan,
        checkpoint,
        _actor(),
        review_set,
        ANALYSIS_POLICY,
        at=NOW + timedelta(minutes=2),
    )
    assert len(checkpoint.analysis_review_authorizations) == 1
    assert analyses.review_commands == []
    checkpoint = coordinator.review_analyses(
        plan,
        checkpoint,
        _actor(),
        review_set,
        ANALYSIS_POLICY,
        at=NOW + timedelta(minutes=2),
    )
    assert len(analyses.review_commands) == 1
    assert analyses.review_commands[0].decision == "APPROVE"
    assert all(
        row.analysis is not None and row.analysis.state == "ACCEPTED"
        for row in checkpoint.item_runs
    )
    assert checkpoint.state == "GRAPH_PUBLICATION"


def test_analysis_review_authorization_survives_response_loss_and_runner_restart(
    tmp_path: Path,
) -> None:
    analyses = FakeAnalysisOperations(
        review_positions=frozenset({1}),
        lose_first_review_response=True,
    )
    coordinator, _, *_ = _coordinator(analyses=analyses)
    store = AtomicJsonMockExamProductionCheckpointStore(tmp_path / "analysis-review-checkpoints")
    runner = MockExamProductionRunner(coordinator=coordinator, checkpoints=store)
    plan = _plan()
    checkpoint = runner.initialize(
        plan,
        _actor(),
        production_request_id=PRODUCTION_REQUEST_ID,
        at=NOW,
    )
    for seconds in (1, 2, 3):
        checkpoint = runner.advance_items(
            plan,
            checkpoint.execution_id,
            _actor(),
            at=NOW + timedelta(seconds=seconds),
        )
    for seconds in (4, 5):
        checkpoint = runner.advance_analyses(
            plan,
            checkpoint.execution_id,
            _actor(),
            ANALYSIS_POLICY,
            at=NOW + timedelta(seconds=seconds),
        )
    review_required = checkpoint.item_runs[0]
    assert review_required.analysis is not None
    review_set = build_mock_exam_explicit_analysis_review_set(
        execution_id=checkpoint.execution_id,
        operator_id=OPERATOR_ID,
        assignments=(
            MockExamExplicitAnalysisReviewV1(
                workflow_call_id=review_required.workflow_call_id,
                position=review_required.position,
                analysis_run_id=review_required.analysis.analysis_run_id,
                expected_resource_version=review_required.analysis.resource_version,
                decision="APPROVE",
                notes="샘플 운영자의 명시적 분석 승인",
            ),
        ),
        authorized_at=NOW + timedelta(seconds=6),
    )

    pinned = runner.review_analyses(
        plan,
        checkpoint.execution_id,
        _actor(),
        review_set,
        ANALYSIS_POLICY,
        at=NOW + timedelta(seconds=6),
    )
    assert len(pinned.analysis_review_authorizations) == 1
    assert analyses.review_commands == []

    restarted = MockExamProductionRunner(coordinator=coordinator, checkpoints=store)
    uncertain = restarted.review_analyses(
        plan,
        pinned.execution_id,
        _actor(),
        review_set,
        ANALYSIS_POLICY,
        at=NOW + timedelta(seconds=7),
    )
    assert uncertain.item_runs[0].state == "ANALYSIS_UNCONFIRMED"
    restarted = MockExamProductionRunner(coordinator=coordinator, checkpoints=store)
    accepted = restarted.review_analyses(
        plan,
        uncertain.execution_id,
        _actor(),
        review_set,
        ANALYSIS_POLICY,
        at=NOW + timedelta(seconds=8),
    )
    assert accepted.item_runs[0].analysis is not None
    assert accepted.item_runs[0].analysis.state == "ACCEPTED"
    assert len(analyses.review_commands) == 2
    assert (
        analyses.review_commands[0].idempotency_key == analyses.review_commands[1].idempotency_key
    )


def test_analysis_policy_and_general_knowledge_mode_are_immutable_on_resume() -> None:
    coordinator, workflows, *_ = _coordinator()
    plan, checkpoint = _registered_checkpoint(coordinator, workflows)
    checkpoint = coordinator.advance_analyses(
        plan,
        checkpoint,
        _actor(),
        ANALYSIS_POLICY,
        at=NOW + timedelta(minutes=1),
        general_knowledge_mode="DISABLED",
    )
    changed_policy = MockExamAnalysisPolicyPointerV1(
        risk_policy_revision_id=_hex_id("analysisriskrev_", 99),
        risk_policy_sha256=_sha(99),
    )

    with pytest.raises(Exception, match="differs from the execution analysis policy"):
        coordinator.advance_analyses(
            plan,
            checkpoint,
            _actor(),
            changed_policy,
            at=NOW + timedelta(minutes=2),
            general_knowledge_mode="DISABLED",
        )
    with pytest.raises(Exception, match="differs from the execution analysis policy"):
        coordinator.advance_analyses(
            plan,
            checkpoint,
            _actor(),
            ANALYSIS_POLICY,
            at=NOW + timedelta(minutes=2),
            general_knowledge_mode="AUXILIARY_UNATTRIBUTED",
        )


def test_explicit_rating_set_rejects_missing_or_foreign_item() -> None:
    coordinator, workflows, *_ = _coordinator()
    plan, checkpoint = _registered_checkpoint(coordinator, workflows)
    assignments = tuple(
        MockExamExplicitRatingV1(
            workflow_call_id=row.workflow_call_id,
            position=row.position,
            item_revision_id=(
                _hex_id("itemrev_", 999)
                if row.position == 25
                else row.registration.item_revision_id  # type: ignore[union-attr]
            ),
            final_rating="A",
        )
        for row in checkpoint.item_runs
    )
    rating_set = build_mock_exam_explicit_rating_set(
        execution_id=checkpoint.execution_id,
        operator_id=OPERATOR_ID,
        assignments=assignments,
        authorized_at=NOW,
    )
    checkpoint = coordinator.advance_analyses(plan, checkpoint, _actor(), ANALYSIS_POLICY, at=NOW)
    checkpoint = coordinator.advance_analyses(plan, checkpoint, _actor(), ANALYSIS_POLICY, at=NOW)
    checkpoint = coordinator.publish_next_graph_batch(
        plan, checkpoint, _actor(), GRAPH_INPUT, at=NOW
    )
    checkpoint = coordinator.publish_next_graph_batch(
        plan, checkpoint, _actor(), GRAPH_INPUT, at=NOW
    )
    with pytest.raises(Exception, match="explicit ratings differ"):
        coordinator.publish_ratings(
            plan,
            checkpoint,
            _actor(),
            rating_set,
            RATING_POLICY,
            at=NOW,
        )


def test_published_rating_set_authorization_cannot_change_on_replay() -> None:
    coordinator, workflows, *_ = _coordinator()
    plan, checkpoint = _registered_checkpoint(coordinator, workflows)
    checkpoint = coordinator.advance_analyses(
        plan,
        checkpoint,
        _actor(),
        ANALYSIS_POLICY,
        at=NOW + timedelta(minutes=1),
    )
    checkpoint = coordinator.advance_analyses(
        plan,
        checkpoint,
        _actor(),
        ANALYSIS_POLICY,
        at=NOW + timedelta(minutes=1),
    )
    checkpoint = coordinator.publish_next_graph_batch(
        plan, checkpoint, _actor(), GRAPH_INPUT, at=NOW + timedelta(minutes=2)
    )
    checkpoint = coordinator.publish_next_graph_batch(
        plan, checkpoint, _actor(), GRAPH_INPUT, at=NOW + timedelta(minutes=3)
    )

    def rating_set(value: Literal["A", "C"]) -> Any:
        return build_mock_exam_explicit_rating_set(
            execution_id=checkpoint.execution_id,
            operator_id=OPERATOR_ID,
            assignments=tuple(
                MockExamExplicitRatingV1(
                    workflow_call_id=row.workflow_call_id,
                    position=row.position,
                    item_revision_id=row.registration.item_revision_id,  # type: ignore[union-attr]
                    final_rating=value,
                )
                for row in checkpoint.item_runs
            ),
            authorized_at=NOW + timedelta(minutes=4),
        )

    checkpoint = coordinator.publish_ratings(
        plan,
        checkpoint,
        _actor(),
        rating_set("C"),
        RATING_POLICY,
        at=NOW + timedelta(minutes=4),
    )
    checkpoint = coordinator.publish_ratings(
        plan,
        checkpoint,
        _actor(),
        rating_set("C"),
        RATING_POLICY,
        at=NOW + timedelta(minutes=4),
    )
    with pytest.raises(Exception, match="pinned explicit rating authorization"):
        coordinator.publish_ratings(
            plan,
            checkpoint,
            _actor(),
            rating_set("A"),
            RATING_POLICY,
            at=NOW + timedelta(minutes=5),
        )


def test_execution_schema_and_packaged_mirror_validate_checkpoint() -> None:
    coordinator, _workflows, *_ = _coordinator()
    checkpoint = coordinator.initialize(
        _plan(),
        production_request_id=PRODUCTION_REQUEST_ID,
        operator_id=OPERATOR_ID,
        at=NOW,
    )
    assert checkpoint.schema_version == "mock-exam-production-execution/2.0"
    canonical = ROOT / "schemas/api/v1/mock-exam-production-execution-v2.schema.json"
    packaged = (
        ROOT
        / "packages/api_contracts/eom_api_contracts/schemas"
        / "mock-exam-production-execution-v2.schema.json"
    )
    assert canonical.read_bytes() == packaged.read_bytes()
    schema = json.loads(canonical.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(
        checkpoint.model_dump(mode="json")
    )
    plan = _plan()
    checkpoint = coordinator.advance_items(plan, checkpoint, _actor(), at=NOW)
    registered = coordinator.advance_items(
        plan, checkpoint, _actor(), at=NOW + timedelta(seconds=1)
    )
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(
        registered.model_dump(mode="json")
    )

    review_canonical = ROOT / "schemas/api/v1/mock-exam-explicit-analysis-review-set-v1.schema.json"
    review_packaged = (
        ROOT
        / "packages/api_contracts/eom_api_contracts/schemas"
        / "mock-exam-explicit-analysis-review-set-v1.schema.json"
    )
    assert review_canonical.read_bytes() == review_packaged.read_bytes()
    review_schema = json.loads(review_canonical.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(review_schema)


def test_plan_v2_pins_execution_v2_and_generation_v2_before_workflow_side_effects() -> None:
    coordinator, workflows, *_ = _coordinator()
    plan = build_integrated_science_mock_exam_production_plan_v2(
        policy=load_integrated_science_mock_exam_policy(),
        layout_policy=load_integrated_science_mock_exam_layout_policy(),
        outline=load_integrated_science_editorial_outline(),
    )
    initial = coordinator.initialize(
        plan,
        production_request_id=PRODUCTION_REQUEST_ID,
        operator_id=OPERATOR_ID,
        at=NOW,
    )
    pinned = coordinator.advance_items(plan, initial, _actor(), at=NOW)

    assert isinstance(pinned, MockExamProductionExecutionV2)
    assert isinstance(pinned.generation_block_resolution, MockExamGenerationBlockResolutionV2)
    assert pinned.generation_block_resolution.workflow_definition_version == "1.9.0"
    assert pinned.generation_block_resolution.content_pack_version == "1.14.0"
    assert workflows.occurrence_count == 0


def test_execution_v2_rejects_mixed_generation_and_review_families() -> None:
    coordinator, workflows, *_ = _coordinator()
    _plan_value, checkpoint = _registered_checkpoint(coordinator, workflows)
    value = checkpoint.model_dump(mode="json")
    assert value["generation_block_resolution"] is not None
    value["generation_block_resolution"] |= {
        "generation_block_revision": "2.0",
        "workflow_definition_version": "1.9.0",
        "content_pack_version": "1.14.0",
    }
    identity = {
        key: child
        for key, child in value.items()
        if key not in {"execution_revision_id", "checkpoint_sha256"}
    }
    checkpoint_sha256 = content_sha256(identity)
    value["execution_revision_id"] = (
        "productionexecrev_" + checkpoint_sha256.removeprefix("sha256:")[:32]
    )
    value["checkpoint_sha256"] = checkpoint_sha256

    with pytest.raises(ValidationError, match="mix protocol families"):
        MockExamProductionExecutionV2.model_validate(value)


def test_atomic_runner_persists_revision_chain_and_rejects_tampering(
    tmp_path: Path,
) -> None:
    coordinator, workflows, *_ = _coordinator()
    root = tmp_path / "mock-exam-checkpoints"
    store = AtomicJsonMockExamProductionCheckpointStore(root)
    runner = MockExamProductionRunner(coordinator=coordinator, checkpoints=store)
    plan = _plan()
    initial = runner.initialize(
        plan,
        _actor(),
        production_request_id=PRODUCTION_REQUEST_ID,
        at=NOW,
    )
    pinned = runner.advance_items(
        plan,
        initial.execution_id,
        _actor(),
        at=NOW + timedelta(seconds=1),
    )
    assert pinned.generation_block_resolution is not None
    assert workflows.occurrence_count == 0

    # A fresh runner process resumes from the durable resolution pin. No Workflow start can
    # precede that checkpoint, and replay uses the exact pinned release/preset identities.
    restarted = MockExamProductionRunner(coordinator=coordinator, checkpoints=store)
    advanced = restarted.advance_items(
        plan,
        pinned.execution_id,
        _actor(),
        at=NOW + timedelta(seconds=2),
    )
    assert pinned.predecessor_execution_revision_id == initial.execution_revision_id
    assert advanced.predecessor_execution_revision_id == pinned.execution_revision_id
    directory = root / initial.execution_id
    assert (directory / f"{initial.execution_revision_id}.json").is_file()
    assert (directory / f"{pinned.execution_revision_id}.json").is_file()
    assert (directory / f"{advanced.execution_revision_id}.json").is_file()
    assert restarted.get(initial.execution_id) == advanced
    assert workflows.occurrence_count == 25

    current_path = directory / "current.json"
    value = json.loads(current_path.read_text(encoding="utf-8"))
    value["operator_id"] = "operator_" + "0" * 32
    current_path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(MockExamCheckpointStoreError) as error:
        restarted.get(initial.execution_id)
    assert error.value.code == "CHECKPOINT_CONTRACT_INVALID"


def test_analysis_policy_is_durable_before_analysis_side_effects_and_restart(
    tmp_path: Path,
) -> None:
    coordinator, _workflows, analyses, *_ = _coordinator()
    store = AtomicJsonMockExamProductionCheckpointStore(tmp_path / "analysis-checkpoints")
    runner = MockExamProductionRunner(coordinator=coordinator, checkpoints=store)
    plan = _plan()
    checkpoint = runner.initialize(
        plan,
        _actor(),
        production_request_id=PRODUCTION_REQUEST_ID,
        at=NOW,
    )
    for seconds in (1, 2, 3):
        checkpoint = runner.advance_items(
            plan,
            checkpoint.execution_id,
            _actor(),
            at=NOW + timedelta(seconds=seconds),
        )
    assert all(row.state == "REGISTERED" for row in checkpoint.item_runs)

    pinned = runner.advance_analyses(
        plan,
        checkpoint.execution_id,
        _actor(),
        ANALYSIS_POLICY,
        at=NOW + timedelta(seconds=4),
        general_knowledge_mode="DISABLED",
    )
    assert pinned.analysis_policy == ANALYSIS_POLICY
    assert pinned.analysis_general_knowledge_mode == "DISABLED"
    assert analyses.start_commands == []

    restarted = MockExamProductionRunner(coordinator=coordinator, checkpoints=store)
    accepted = restarted.advance_analyses(
        plan,
        pinned.execution_id,
        _actor(),
        ANALYSIS_POLICY,
        at=NOW + timedelta(seconds=5),
        general_knowledge_mode="DISABLED",
    )
    assert len(analyses.start_commands) == 25
    assert all(row.state == "ANALYSIS_ACCEPTED" for row in accepted.item_runs)


@pytest.mark.parametrize("unsafe_pointer", ["symlink", "fifo"])
def test_checkpoint_store_rejects_non_regular_current_pointer(
    tmp_path: Path,
    unsafe_pointer: str,
) -> None:
    coordinator, *_ = _coordinator()
    root = tmp_path / f"unsafe-{unsafe_pointer}"
    store = AtomicJsonMockExamProductionCheckpointStore(root)
    runner = MockExamProductionRunner(coordinator=coordinator, checkpoints=store)
    checkpoint = runner.initialize(
        _plan(),
        _actor(),
        production_request_id=PRODUCTION_REQUEST_ID,
        at=NOW,
    )
    directory = root / checkpoint.execution_id
    current = directory / "current.json"
    current.unlink()
    if unsafe_pointer == "symlink":
        current.symlink_to(f"{checkpoint.execution_revision_id}.json")
    else:
        os.mkfifo(current, mode=0o640)

    with pytest.raises(MockExamCheckpointStoreError) as error:
        runner.get(checkpoint.execution_id)
    assert error.value.code == "CHECKPOINT_FILE_INVALID"


def test_checkpoint_store_rejects_unsafe_directory_modes(tmp_path: Path) -> None:
    unsafe_root = tmp_path / "unsafe-root"
    unsafe_root.mkdir(mode=0o750)
    unsafe_root.chmod(0o777)
    with pytest.raises(MockExamCheckpointStoreError) as root_error:
        AtomicJsonMockExamProductionCheckpointStore(unsafe_root)
    assert root_error.value.code == "CHECKPOINT_DIRECTORY_INVALID"

    coordinator, *_ = _coordinator()
    root = tmp_path / "safe-root"
    store = AtomicJsonMockExamProductionCheckpointStore(root)
    runner = MockExamProductionRunner(coordinator=coordinator, checkpoints=store)
    checkpoint = runner.initialize(
        _plan(),
        _actor(),
        production_request_id=PRODUCTION_REQUEST_ID,
        at=NOW,
    )
    (root / checkpoint.execution_id).chmod(0o755)
    with pytest.raises(MockExamCheckpointStoreError) as execution_error:
        runner.get(checkpoint.execution_id)
    assert execution_error.value.code == "CHECKPOINT_DIRECTORY_INVALID"


def test_checkpoint_store_rejects_immutable_revision_mismatch(tmp_path: Path) -> None:
    coordinator, *_ = _coordinator()
    root = tmp_path / "revision-mismatch"
    store = AtomicJsonMockExamProductionCheckpointStore(root)
    runner = MockExamProductionRunner(coordinator=coordinator, checkpoints=store)
    checkpoint = runner.initialize(
        _plan(),
        _actor(),
        production_request_id=PRODUCTION_REQUEST_ID,
        at=NOW,
    )
    revision = root / checkpoint.execution_id / f"{checkpoint.execution_revision_id}.json"
    revision.write_bytes(revision.read_bytes() + b" ")

    with pytest.raises(MockExamCheckpointStoreError) as error:
        runner.get(checkpoint.execution_id)
    assert error.value.code == "CHECKPOINT_CURRENT_CACHE_MISMATCH"


def test_production_request_id_creates_distinct_authorized_occurrences() -> None:
    coordinator, *_ = _coordinator()
    plan = _plan()
    first = coordinator.initialize(
        plan,
        production_request_id="productionreq_" + "1" * 32,
        operator_id=OPERATOR_ID,
        at=NOW,
    )
    second = coordinator.initialize(
        plan,
        production_request_id="productionreq_" + "2" * 32,
        operator_id=OPERATOR_ID,
        at=NOW,
    )
    assert first.execution_id != second.execution_id
    with pytest.raises(ValidationError):
        type(first).model_validate(
            first.model_dump(mode="json") | {"production_request_id": second.production_request_id}
        )


def test_production_request_id_is_globally_reserved_across_operators(tmp_path: Path) -> None:
    coordinator, *_ = _coordinator()
    plan = _plan()
    first = coordinator.initialize(
        plan,
        production_request_id=PRODUCTION_REQUEST_ID,
        operator_id=OPERATOR_ID,
        at=NOW,
    )
    second = coordinator.initialize(
        plan,
        production_request_id=PRODUCTION_REQUEST_ID,
        operator_id="operator_" + "9" * 32,
        at=NOW,
    )
    assert first.execution_id == second.execution_id
    assert first.checkpoint_sha256 != second.checkpoint_sha256

    store = AtomicJsonMockExamProductionCheckpointStore(tmp_path / "global-occurrence")
    store.create(first)
    with pytest.raises(MockExamCheckpointStoreError) as raised:
        store.create(second)
    assert raised.value.code == "CHECKPOINT_EXECUTION_ALREADY_EXISTS"


def test_resolution_checkpoint_time_includes_resolver_commit_time() -> None:
    coordinator, workflows, *_ = _coordinator()
    plan = _plan()
    checkpoint = coordinator.initialize(
        plan,
        production_request_id=PRODUCTION_REQUEST_ID,
        operator_id=OPERATOR_ID,
        at=NOW,
    )

    pinned = coordinator.advance_items(
        plan,
        checkpoint,
        _actor(),
        at=NOW - timedelta(seconds=1),
    )
    assert pinned.generation_block_resolution is not None
    assert pinned.checkpointed_at == pinned.generation_block_resolution.resolved_at == NOW
    assert workflows.occurrence_count == 0


def test_item_checkpoint_commit_floors_time_at_later_workflow_children(
    tmp_path: Path,
) -> None:
    provenance_at = NOW + timedelta(seconds=5)
    approval_at = NOW + timedelta(seconds=6)
    workflows = FakeWorkflowOperations(
        approved_at=approval_at,
        provenance_resolved_at=provenance_at,
    )
    coordinator, *_ = _coordinator(workflows=workflows)
    store = AtomicJsonMockExamProductionCheckpointStore(tmp_path / "item-time-checkpoints")
    runner = MockExamProductionRunner(coordinator=coordinator, checkpoints=store)
    plan = _plan()
    checkpoint = runner.initialize(
        plan,
        _actor(),
        production_request_id=PRODUCTION_REQUEST_ID,
        at=NOW,
    )

    checkpoint = runner.advance_items(plan, checkpoint.execution_id, _actor(), at=NOW)
    checkpoint = runner.advance_items(plan, checkpoint.execution_id, _actor(), at=NOW)
    assert checkpoint.checkpointed_at == provenance_at
    assert all(row.state == "APPROVAL_SUBMITTED" for row in checkpoint.item_runs)

    checkpoint = runner.advance_items(plan, checkpoint.execution_id, _actor(), at=NOW)
    assert checkpoint.checkpointed_at == approval_at
    assert all(row.state == "REGISTERED" for row in checkpoint.item_runs)
    assert store.load(checkpoint.execution_id) == checkpoint


def test_checkpoint_lifecycle_rejects_pointer_clear_and_analysis_regression() -> None:
    coordinator, workflows, *_ = _coordinator()
    plan, registered = _registered_checkpoint(coordinator, workflows)
    cleared_registration = registered.item_runs[0].model_copy(
        update={"state": "WORKFLOW_ACTIVE", "registration": None}
    )
    cleared = registered.model_copy(
        update={"item_runs": (cleared_registration, *registered.item_runs[1:])}
    )
    assert not _monotonic_successor(registered, cleared)

    accepted = coordinator.advance_analyses(
        plan,
        registered,
        _actor(),
        ANALYSIS_POLICY,
        at=NOW + timedelta(minutes=1),
    )
    accepted = coordinator.advance_analyses(
        plan,
        accepted,
        _actor(),
        ANALYSIS_POLICY,
        at=NOW + timedelta(minutes=1),
    )
    current_analysis = accepted.item_runs[0].analysis
    assert current_analysis is not None
    regressed_analysis = current_analysis.model_copy(
        update={
            "state": "RUNNING",
            "resource_version": current_analysis.resource_version + 1,
            "accepted_result_artifact_id": None,
            "accepted_result_artifact_revision_id": None,
            "accepted_result_sha256": None,
        }
    )
    regressed_run = accepted.item_runs[0].model_copy(
        update={"state": "ANALYSIS_ACTIVE", "analysis": regressed_analysis}
    )
    regressed = accepted.model_copy(update={"item_runs": (regressed_run, *accepted.item_runs[1:])})
    assert not _monotonic_successor(accepted, regressed)
