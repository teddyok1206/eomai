"""Graph-pinned mock-exam assembly endpoints."""

from __future__ import annotations

from typing import Annotated

from eom_api_contracts import CommandResult, SingleResponse
from eom_api_contracts.assessment_assemblies import (
    CreateMockExamAssemblyRequest,
    CreatePlannedMockExamAssemblyRequest,
    MockExamAssemblyPlanView,
    MockExamAssemblyPolicyView,
    MockExamAssemblyViewContract,
    PreviewMockExamAssemblyPlanRequest,
)
from eom_operator_identity import PermissionKey
from fastapi import APIRouter, Depends, Request

from eom_api.dependencies import Auth, IdempotencyKey, require_permission
from eom_api.routers.common import one, run_command

router = APIRouter(prefix="/assessment-assemblies", tags=["assessment-assemblies"])


@router.get(
    "/policy",
    operation_id="mock_exam_assembly_policy_get",
    response_model=SingleResponse[MockExamAssemblyPolicyView],
    dependencies=[Depends(require_permission(PermissionKey.DELIVERABLE_READ))],
)
def get_policy(request: Request) -> SingleResponse[MockExamAssemblyPolicyView]:
    return one(request, request.app.state.services.queries.mock_exam_assembly_policy())


@router.get(
    "/plan",
    operation_id="mock_exam_assembly_plan_preview",
    response_model=SingleResponse[MockExamAssemblyPlanView],
    dependencies=[Depends(require_permission(PermissionKey.DELIVERABLE_READ))],
)
def preview_assembly_plan(
    request: Request,
    query: Annotated[PreviewMockExamAssemblyPlanRequest, Depends()],
) -> SingleResponse[MockExamAssemblyPlanView]:
    return one(
        request,
        request.app.state.services.queries.mock_exam_assembly_plan(query),
    )


@router.get(
    "/{assembly_revision_id}",
    operation_id="mock_exam_assembly_get",
    response_model=SingleResponse[MockExamAssemblyViewContract],
    dependencies=[Depends(require_permission(PermissionKey.DELIVERABLE_READ))],
)
def get_assembly(
    request: Request, assembly_revision_id: str
) -> SingleResponse[MockExamAssemblyViewContract]:
    return one(
        request,
        request.app.state.services.queries.mock_exam_assembly(assembly_revision_id),
    )


@router.post(
    "/planned",
    operation_id="planned_mock_exam_assembly_create",
    status_code=201,
    response_model=SingleResponse[CommandResult],
    dependencies=[Depends(require_permission(PermissionKey.DELIVERABLE_CREATE))],
)
def create_planned_assembly(
    request: Request,
    body: CreatePlannedMockExamAssemblyRequest,
    authentication: Auth,
    idempotency_key: IdempotencyKey,
) -> SingleResponse[CommandResult]:
    del authentication

    def execute() -> CommandResult:
        command_id, revision_id, version = (
            request.app.state.services.commands.create_planned_mock_exam_assembly(
                body, request.state.request_context.actor()
            )
        )
        return CommandResult(
            command_id=command_id,
            resource_type="assessment_assembly_revision",
            resource_id=revision_id,
            status="COMPLETED",
            resource_version=version,
            status_url=f"/api/v1/assessment-assemblies/{revision_id}",
        )

    return one(
        request,
        run_command(
            request,
            raw_key=idempotency_key,
            body=body.model_dump(mode="json"),
            resource_type="assessment_assembly_revision",
            callback=execute,
            response_status=201,
        ),
    )


@router.post(
    "",
    operation_id="mock_exam_assembly_create",
    status_code=201,
    response_model=SingleResponse[CommandResult],
    dependencies=[Depends(require_permission(PermissionKey.DELIVERABLE_CREATE))],
)
def create_assembly(
    request: Request,
    body: CreateMockExamAssemblyRequest,
    authentication: Auth,
    idempotency_key: IdempotencyKey,
) -> SingleResponse[CommandResult]:
    del authentication

    def execute() -> CommandResult:
        command_id, revision_id, version = (
            request.app.state.services.commands.create_mock_exam_assembly(
                body, request.state.request_context.actor()
            )
        )
        return CommandResult(
            command_id=command_id,
            resource_type="assessment_assembly_revision",
            resource_id=revision_id,
            status="COMPLETED",
            resource_version=version,
            status_url=f"/api/v1/assessment-assemblies/{revision_id}",
        )

    return one(
        request,
        run_command(
            request,
            raw_key=idempotency_key,
            body=body.model_dump(mode="json"),
            resource_type="assessment_assembly_revision",
            callback=execute,
            response_status=201,
        ),
    )
