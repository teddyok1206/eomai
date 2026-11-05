"""Exact material role context at the existing Orchestrator execution boundary."""

from collections.abc import Callable
from dataclasses import dataclass

from eom_catalog_contracts.material_learning import (
    MaterialArtifactMember,
    MaterialDiscoveryResult,
    validate_material_discovery,
    validate_material_extraction,
)
from eom_catalog_contracts.office_item_learning import validate_source_office_visual_bindings
from eom_image_contracts.office_picture_uses import OfficePictureUseCatalog
from eom_workflow.control_plane import ResolvedExecutionPlanV33
from eom_workflow.material_learning_request import MaterialLearningWorkerRequest
from eom_workflow.models import MaterialLearningRoleResult

from eom_orchestrator.control_models import ResolvedExecutionPlanRecord
from eom_orchestrator.control_service import ControlPlaneError


@dataclass(frozen=True, slots=True)
class MaterialLearningExecutionContext:
    source_authorizer: Callable[[MaterialLearningWorkerRequest], None]
    catalog_reader: Callable[[MaterialArtifactMember], OfficePictureUseCatalog]

    def reauthorize(self, request: MaterialLearningWorkerRequest) -> None:
        try:
            self.source_authorizer(request)
        except ValueError as error:
            raise ControlPlaneError(
                "CONTROL_MATERIAL_SOURCE_AUTHORIZATION_FAILED",
                "material source authorization failed",
            ) from error

    def validate_result(
        self, request: MaterialLearningWorkerRequest, result: MaterialLearningRoleResult
    ) -> None:
        observed = result.output.learning_result
        if isinstance(observed, MaterialDiscoveryResult):
            if request.work_input.task_kind != "DISCOVER":
                raise ValueError("MATERIAL_LEARNING_RESULT_TASK_MISMATCH")
            validate_material_discovery(observed, request.work_input)
        else:
            if request.work_input.task_kind != "EXTRACT_ITEM":
                raise ValueError("MATERIAL_LEARNING_RESULT_TASK_MISMATCH")
            validate_material_extraction(observed, request.work_input)
            if observed.office_bindings is not None:
                roles = {anchor.source_role for anchor in request.work_input.question.anchors}
                sources = tuple(
                    source
                    for source in request.work_input.sources
                    if source.source_role in roles and source.office_catalog is not None
                )
                if len(sources) != 1:
                    raise ValueError("MATERIAL_LEARNING_OFFICE_BINDINGS_SOURCE_INVALID")
                source = sources[0]
                assert source.office_catalog is not None
                validate_source_office_visual_bindings(
                    observed.office_bindings,
                    result=observed,
                    catalog=self.catalog_reader(source.office_catalog),
                    expected_catalog_sha256=source.office_catalog.sha256,
                    expected_source_sha256=source.original.sha256,
                )


def validate_material_learning_execution_plan(
    record: ResolvedExecutionPlanRecord | None,
    *,
    workflow_id: str,
    step_key: str,
    request: MaterialLearningWorkerRequest,
) -> ResolvedExecutionPlanV33:
    try:
        if record is None:
            raise ValueError("material plan missing")
        plan = ResolvedExecutionPlanV33.model_validate(record.canonical_document)
        if (
            plan.workflow_id != workflow_id
            or step_key != "learn"
            or plan.work_input != request.work_input
            or (
                record.plan_id,
                record.workflow_id,
                record.preset_id,
                record.preset_revision_id,
                record.capacity_policy_revision_id,
                record.graph_snapshot_revision_id,
                record.evidence_bundle_revision_id,
                record.plan_sha256,
                record.resolver_version,
                record.resolved_at,
            )
            != (
                plan.plan_id,
                plan.workflow_id,
                plan.preset_id,
                plan.preset_revision_id,
                plan.capacity_policy_revision_id,
                None,
                None,
                plan.plan_sha256,
                plan.resolver_version,
                plan.resolved_at,
            )
        ):
            raise ValueError("material plan row differs")
    except ValueError as error:
        raise ControlPlaneError(
            "CONTROL_MATERIAL_PLAN_UNAVAILABLE", "the exact material execution plan is required"
        ) from error
    return plan
