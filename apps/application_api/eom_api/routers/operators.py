"""Fresh ADMIN Operator management endpoints."""

from __future__ import annotations

from eom_api_contracts import CommandResult, ListResponse, SingleResponse
from eom_api_contracts.common import EmptyRequest
from eom_api_contracts.operators import (
    CreateOperatorRequest,
    OperatorView,
    ReasonRequest,
    RoleRevocationRequest,
)
from eom_identity_service.service import CreateOperatorCommand
from eom_operator_identity import PermissionKey, RoleKey
from fastapi import APIRouter, Depends, Query, Request, Response

from eom_api.dependencies import (
    Auth,
    ExpectedVersion,
    IdempotencyKey,
    etag,
    require_permission,
)
from eom_api.routers.common import many, one, run_command

router = APIRouter(prefix="/operators", tags=["operators"])
ADMIN_READ = require_permission(PermissionKey.OPERATOR_READ, fresh=True, admin_only=True)


def _view(projection) -> OperatorView:  # type: ignore[no-untyped-def]
    return OperatorView.model_validate(projection.model_dump(mode="python"))


@router.get(
    "",
    operation_id="operator_list",
    response_model=ListResponse[OperatorView],
    dependencies=[Depends(ADMIN_READ)],
)
def list_operators(
    request: Request,
    status: str | None = Query(default=None, pattern=r"^(ACTIVE|DISABLED)$"),
    role: str | None = Query(default=None, pattern=r"^(VIEWER|AUTHOR|REVIEWER|EDITOR|ADMIN)$"),
    username_prefix: str | None = Query(default=None, max_length=64),
    limit: int = Query(default=50, ge=1, le=200),
) -> ListResponse[OperatorView]:
    projections = request.app.state.services.operators.list_operators(limit=200)
    values = tuple(
        _view(value)
        for value in projections
        if (status is None or value.status.value == status)
        and (role is None or any(item.value == role for item in value.roles))
        and (username_prefix is None or value.username.startswith(username_prefix))
    )[:limit]
    return many(request, values, limit=limit)


@router.post(
    "",
    operation_id="operator_create",
    status_code=201,
    response_model=SingleResponse[CommandResult],
    dependencies=[
        Depends(require_permission(PermissionKey.OPERATOR_CREATE, fresh=True, admin_only=True))
    ],
)
def create_operator(
    request: Request,
    body: CreateOperatorRequest,
    authentication: Auth,
    idempotency_key: IdempotencyKey,
) -> SingleResponse[CommandResult]:
    def create() -> CommandResult:
        projection = request.app.state.services.operators.create_operator(
            CreateOperatorCommand(
                username=body.username,
                display_name=body.display_name,
                temporary_password=body.temporary_password.get_secret_value(),
                initial_roles=tuple(RoleKey(role) for role in body.initial_roles),
            ),
            request.state.request_context.actor(),
        )
        return CommandResult(
            command_id=f"operator-create-{projection.operator_id}",
            resource_type="operator",
            resource_id=projection.operator_id,
            status="COMPLETED",
            resource_version=projection.resource_version,
            status_url=f"/api/v1/operators/{projection.operator_id}",
        )

    result = run_command(
        request,
        raw_key=idempotency_key,
        body={
            "username": body.username,
            "display_name": body.display_name,
            "temporary_password_hash": request.app.state.services.idempotency.sensitive_value_hash(
                body.temporary_password.get_secret_value()
            ),
            "initial_roles": list(body.initial_roles),
        },
        resource_type="operator",
        callback=create,
        response_status=201,
    )
    return one(request, result)


@router.get(
    "/{operator_id}",
    operation_id="operator_get",
    response_model=SingleResponse[OperatorView],
    dependencies=[Depends(ADMIN_READ)],
)
def get_operator(
    request: Request, operator_id: str, response: Response
) -> SingleResponse[OperatorView]:
    value = _view(request.app.state.services.operators.inspect_operator(operator_id))
    response.headers["ETag"] = etag(value.resource_version)
    return one(request, value)


@router.post(
    "/{operator_id}/roles/{role_key}",
    operation_id="operator_assign_role",
    response_model=SingleResponse[CommandResult],
    dependencies=[
        Depends(require_permission(PermissionKey.OPERATOR_ASSIGN_ROLE, fresh=True, admin_only=True))
    ],
)
def assign_role(
    request: Request,
    operator_id: str,
    role_key: RoleKey,
    body: EmptyRequest,
    authentication: Auth,
    idempotency_key: IdempotencyKey,
    expected_version: ExpectedVersion,
) -> SingleResponse[CommandResult]:
    del body, authentication

    def assign() -> CommandResult:
        current = request.app.state.services.operators.inspect_operator(operator_id)
        if current.resource_version != expected_version:
            from eom_api.services.command_adapter import CommandAdapter

            CommandAdapter._version_mismatch()
        projection = request.app.state.services.operators.assign_role(
            operator_id, role_key, request.state.request_context.actor()
        )
        return CommandResult(
            command_id=f"role-assign-{projection.operator_id}-{projection.resource_version}",
            resource_type="operator",
            resource_id=projection.operator_id,
            status="COMPLETED",
            resource_version=projection.resource_version,
            status_url=f"/api/v1/operators/{projection.operator_id}",
        )

    result = run_command(
        request,
        raw_key=idempotency_key,
        body={"role_key": role_key.value},
        resource_type="operator",
        callback=assign,
    )
    return one(request, result)


@router.post(
    "/{operator_id}/role-revocations",
    operation_id="operator_revoke_role",
    response_model=SingleResponse[CommandResult],
    dependencies=[
        Depends(require_permission(PermissionKey.OPERATOR_REVOKE_ROLE, fresh=True, admin_only=True))
    ],
)
def revoke_role(
    request: Request,
    operator_id: str,
    body: RoleRevocationRequest,
    authentication: Auth,
    idempotency_key: IdempotencyKey,
    expected_version: ExpectedVersion,
) -> SingleResponse[CommandResult]:
    del authentication

    def revoke() -> CommandResult:
        current = request.app.state.services.operators.inspect_operator(operator_id)
        if current.resource_version != expected_version:
            from eom_api.services.command_adapter import CommandAdapter

            CommandAdapter._version_mismatch()
        projection = request.app.state.services.operators.revoke_role(
            operator_id,
            RoleKey(body.role_key),
            request.state.request_context.actor(),
            reason=body.reason,
        )
        return CommandResult(
            command_id=f"role-revoke-{projection.operator_id}-{projection.resource_version}",
            resource_type="operator",
            resource_id=projection.operator_id,
            status="COMPLETED",
            resource_version=projection.resource_version,
            status_url=f"/api/v1/operators/{projection.operator_id}",
        )

    return one(
        request,
        run_command(
            request,
            raw_key=idempotency_key,
            body=body.model_dump(mode="json"),
            resource_type="operator",
            callback=revoke,
        ),
    )


def _state_command(
    request: Request,
    operator_id: str,
    raw_key: str,
    expected_version: int,
    action: str,
    reason: str | None,
) -> CommandResult:
    def execute() -> CommandResult:
        current = request.app.state.services.operators.inspect_operator(operator_id)
        if current.resource_version != expected_version:
            from eom_api.services.command_adapter import CommandAdapter

            CommandAdapter._version_mismatch()
        service = request.app.state.services.operators
        actor = request.state.request_context.actor()
        projection = (
            service.disable(operator_id, actor, reason=reason or "")
            if action == "disable"
            else service.enable(operator_id, actor)
        )
        return CommandResult(
            command_id=f"operator-{action}-{operator_id}-{projection.resource_version}",
            resource_type="operator",
            resource_id=operator_id,
            status="COMPLETED",
            resource_version=projection.resource_version,
            status_url=f"/api/v1/operators/{operator_id}",
        )

    return run_command(
        request,
        raw_key=raw_key,
        body={"action": action, "reason": reason},
        resource_type="operator",
        callback=execute,
    )


@router.post(
    "/{operator_id}/disable",
    operation_id="operator_disable",
    response_model=SingleResponse[CommandResult],
    dependencies=[
        Depends(require_permission(PermissionKey.OPERATOR_DISABLE, fresh=True, admin_only=True))
    ],
)
def disable_operator(
    request: Request,
    operator_id: str,
    body: ReasonRequest,
    authentication: Auth,
    idempotency_key: IdempotencyKey,
    expected_version: ExpectedVersion,
) -> SingleResponse[CommandResult]:
    del authentication
    return one(
        request,
        _state_command(
            request, operator_id, idempotency_key, expected_version, "disable", body.reason
        ),
    )


@router.post(
    "/{operator_id}/enable",
    operation_id="operator_enable",
    response_model=SingleResponse[CommandResult],
    dependencies=[
        Depends(require_permission(PermissionKey.OPERATOR_ENABLE, fresh=True, admin_only=True))
    ],
)
def enable_operator(
    request: Request,
    operator_id: str,
    body: EmptyRequest,
    authentication: Auth,
    idempotency_key: IdempotencyKey,
    expected_version: ExpectedVersion,
) -> SingleResponse[CommandResult]:
    del body, authentication
    return one(
        request,
        _state_command(request, operator_id, idempotency_key, expected_version, "enable", None),
    )


@router.post(
    "/{operator_id}/revoke-sessions",
    operation_id="operator_revoke_sessions",
    response_model=SingleResponse[CommandResult],
    dependencies=[
        Depends(
            require_permission(PermissionKey.OPERATOR_REVOKE_SESSIONS, fresh=True, admin_only=True)
        )
    ],
)
def revoke_sessions(
    request: Request,
    operator_id: str,
    body: EmptyRequest,
    authentication: Auth,
    idempotency_key: IdempotencyKey,
) -> SingleResponse[CommandResult]:
    del body, authentication

    def execute() -> CommandResult:
        count = request.app.state.services.operators.revoke_sessions(
            operator_id, request.state.request_context.actor()
        )
        return CommandResult(
            command_id=f"session-revoke-{operator_id}-{count}",
            resource_type="operator_sessions",
            resource_id=operator_id,
            status="COMPLETED",
            resource_version=1,
            status_url=f"/api/v1/operators/{operator_id}",
        )

    return one(
        request,
        run_command(
            request,
            raw_key=idempotency_key,
            body={"action": "revoke_sessions"},
            resource_type="operator_sessions",
            callback=execute,
        ),
    )
