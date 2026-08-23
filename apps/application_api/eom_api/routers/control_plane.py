"""ADMIN-only Codex account and immutable Execution Preset endpoints."""

from __future__ import annotations

from eom_api_contracts import CommandResult, ListResponse, SingleResponse
from eom_api_contracts.common import EmptyRequest
from eom_api_contracts.control_plane import (
    CodexAccountCommandRequest,
    CodexAccountView,
    CodexControlCommandView,
    CreateExecutionPresetDraftRequest,
    ExecutionPresetView,
)
from eom_operator_identity import PermissionKey
from fastapi import APIRouter, Depends, Request, Response

from eom_api.dependencies import (
    Auth,
    ExpectedVersion,
    IdempotencyKey,
    etag,
    require_permission,
)
from eom_api.routers.common import many, one, run_command

router = APIRouter(tags=["codex-control-plane"])


@router.get(
    "/codex-accounts",
    operation_id="codex_account_list",
    response_model=ListResponse[CodexAccountView],
    dependencies=[
        Depends(require_permission(PermissionKey.CODEX_ACCOUNT_READ, fresh=True, admin_only=True))
    ],
)
def list_codex_accounts(request: Request) -> ListResponse[CodexAccountView]:
    values = request.app.state.services.control_plane.list_accounts()
    return many(request, values, limit=200)


@router.get(
    "/codex-accounts/{binding_id}",
    operation_id="codex_account_get",
    response_model=SingleResponse[CodexAccountView],
    dependencies=[
        Depends(require_permission(PermissionKey.CODEX_ACCOUNT_READ, fresh=True, admin_only=True))
    ],
)
def get_codex_account(
    request: Request, binding_id: str, response: Response
) -> SingleResponse[CodexAccountView]:
    value = request.app.state.services.control_plane.account(binding_id)
    response.headers["ETag"] = etag(value.resource_version)
    return one(request, value)


@router.post(
    "/codex-accounts/{binding_id}/commands",
    operation_id="codex_account_command",
    status_code=202,
    response_model=SingleResponse[CommandResult],
    dependencies=[
        Depends(require_permission(PermissionKey.CODEX_ACCOUNT_MANAGE, fresh=True, admin_only=True))
    ],
)
def submit_codex_account_command(
    request: Request,
    binding_id: str,
    body: CodexAccountCommandRequest,
    authentication: Auth,
    idempotency_key: IdempotencyKey,
    expected_version: ExpectedVersion,
) -> SingleResponse[CommandResult]:
    del authentication

    def execute() -> CommandResult:
        actor = request.state.request_context.actor()
        submission_key = request.app.state.services.idempotency.submission_key(
            operator_id=actor.actor_id,
            endpoint_key="codex_account_command",
            raw_key=idempotency_key,
        )
        command = request.app.state.services.control_plane.enqueue_account_command(
            binding_id=binding_id,
            body=body,
            actor=actor,
            expected_version=expected_version,
            idempotency_key=submission_key,
        )
        return CommandResult(
            command_id=command.command_id,
            resource_type="codex_control_command",
            resource_id=command.command_id,
            status="ACCEPTED",
            resource_version=expected_version,
            status_url=f"/api/v1/codex-control-commands/{command.command_id}",
        )

    return one(
        request,
        run_command(
            request,
            raw_key=idempotency_key,
            body=body.model_dump(mode="json"),
            resource_type="codex_control_command",
            callback=execute,
            response_status=202,
        ),
    )


@router.get(
    "/codex-control-commands/{command_id}",
    operation_id="codex_control_command_get",
    response_model=SingleResponse[CodexControlCommandView],
    dependencies=[
        Depends(require_permission(PermissionKey.CODEX_ACCOUNT_READ, fresh=True, admin_only=True))
    ],
)
def get_codex_control_command(
    request: Request, command_id: str
) -> SingleResponse[CodexControlCommandView]:
    return one(request, request.app.state.services.control_plane.control_command(command_id))


@router.get(
    "/execution-presets",
    operation_id="execution_preset_list",
    response_model=ListResponse[ExecutionPresetView],
    dependencies=[
        Depends(
            require_permission(PermissionKey.EXECUTION_PRESET_READ, fresh=True, admin_only=True)
        )
    ],
)
def list_execution_presets(request: Request) -> ListResponse[ExecutionPresetView]:
    values = request.app.state.services.control_plane.list_presets()
    return many(request, values, limit=200)


@router.get(
    "/execution-presets/{preset_id}",
    operation_id="execution_preset_get",
    response_model=SingleResponse[ExecutionPresetView],
    dependencies=[
        Depends(
            require_permission(PermissionKey.EXECUTION_PRESET_READ, fresh=True, admin_only=True)
        )
    ],
)
def get_execution_preset(
    request: Request, preset_id: str, response: Response
) -> SingleResponse[ExecutionPresetView]:
    value = request.app.state.services.control_plane.preset(preset_id)
    version = max((item.revision_number for item in value.revisions), default=1)
    response.headers["ETag"] = etag(version)
    return one(request, value)


@router.post(
    "/execution-presets",
    operation_id="execution_preset_draft_create",
    status_code=201,
    response_model=SingleResponse[CommandResult],
    dependencies=[
        Depends(
            require_permission(PermissionKey.EXECUTION_PRESET_MANAGE, fresh=True, admin_only=True)
        )
    ],
)
def create_execution_preset_draft(
    request: Request,
    body: CreateExecutionPresetDraftRequest,
    authentication: Auth,
    idempotency_key: IdempotencyKey,
) -> SingleResponse[CommandResult]:
    del authentication

    def execute() -> CommandResult:
        value = request.app.state.services.control_plane.create_preset_draft(
            body=body, actor=request.state.request_context.actor()
        )
        return CommandResult(
            command_id=f"preset-draft-{value.preset_revision_id}",
            resource_type="execution_preset_revision",
            resource_id=value.preset_revision_id,
            status="COMPLETED",
            resource_version=value.revision_number,
            status_url=f"/api/v1/execution-presets/{value.preset_id}",
        )

    return one(
        request,
        run_command(
            request,
            raw_key=idempotency_key,
            body=body.model_dump(mode="json"),
            resource_type="execution_preset_revision",
            callback=execute,
            response_status=201,
        ),
    )


@router.post(
    "/execution-preset-revisions/{draft_revision_id}/releases",
    operation_id="execution_preset_release",
    response_model=SingleResponse[CommandResult],
    dependencies=[
        Depends(
            require_permission(PermissionKey.EXECUTION_PRESET_MANAGE, fresh=True, admin_only=True)
        )
    ],
)
def release_execution_preset(
    request: Request,
    draft_revision_id: str,
    body: EmptyRequest,
    authentication: Auth,
    idempotency_key: IdempotencyKey,
    expected_version: ExpectedVersion,
) -> SingleResponse[CommandResult]:
    del body, authentication

    def execute() -> CommandResult:
        value = request.app.state.services.control_plane.release_preset(
            draft_revision_id=draft_revision_id,
            actor=request.state.request_context.actor(),
            expected_version=expected_version,
        )
        return CommandResult(
            command_id=f"preset-release-{value.preset_revision_id}",
            resource_type="execution_preset_revision",
            resource_id=value.preset_revision_id,
            status="COMPLETED",
            resource_version=value.revision_number,
            status_url=f"/api/v1/execution-presets/{value.preset_id}",
        )

    return one(
        request,
        run_command(
            request,
            raw_key=idempotency_key,
            body={"draft_revision_id": draft_revision_id},
            resource_type="execution_preset_revision",
            callback=execute,
        ),
    )


@router.post(
    "/execution-presets/{preset_id}/deprecations",
    operation_id="execution_preset_deprecate",
    response_model=SingleResponse[CommandResult],
    dependencies=[
        Depends(
            require_permission(PermissionKey.EXECUTION_PRESET_MANAGE, fresh=True, admin_only=True)
        )
    ],
)
def deprecate_execution_preset(
    request: Request,
    preset_id: str,
    body: EmptyRequest,
    authentication: Auth,
    idempotency_key: IdempotencyKey,
    expected_version: ExpectedVersion,
) -> SingleResponse[CommandResult]:
    del body, authentication

    def execute() -> CommandResult:
        value = request.app.state.services.control_plane.deprecate_preset(
            preset_id=preset_id,
            actor=request.state.request_context.actor(),
            expected_version=expected_version,
        )
        return CommandResult(
            command_id=f"preset-deprecate-{value.preset_revision_id}",
            resource_type="execution_preset_revision",
            resource_id=value.preset_revision_id,
            status="COMPLETED",
            resource_version=value.revision_number,
            status_url=f"/api/v1/execution-presets/{preset_id}",
        )

    return one(
        request,
        run_command(
            request,
            raw_key=idempotency_key,
            body={"preset_id": preset_id},
            resource_type="execution_preset_revision",
            callback=execute,
        ),
    )
