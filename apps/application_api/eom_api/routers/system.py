"""Sanitized system information, capabilities, and doctor endpoints."""

from __future__ import annotations

from datetime import UTC, datetime

from eom_api_contracts import SingleResponse
from eom_api_contracts.system import Capabilities, DoctorStatus, SystemInfo
from eom_operator_identity import PermissionKey
from fastapi import APIRouter, Depends, Request
from sqlalchemy import text

from eom_api.build_info import get_build_info
from eom_api.dependencies import require_permission
from eom_api.health import active_admin_exists, readiness
from eom_api.routers.common import one

router = APIRouter(prefix="/system", tags=["system"])


@router.get(
    "/capabilities",
    operation_id="system_capabilities",
    response_model=SingleResponse[Capabilities],
    dependencies=[Depends(require_permission(PermissionKey.SYSTEM_READ))],
)
def capabilities(request: Request) -> SingleResponse[Capabilities]:
    return one(request, Capabilities())


@router.get(
    "/info",
    operation_id="system_info",
    response_model=SingleResponse[SystemInfo],
    dependencies=[Depends(require_permission(PermissionKey.SYSTEM_READ))],
)
def system_info(request: Request) -> SingleResponse[SystemInfo]:
    services = request.app.state.services
    build = get_build_info()
    with services.engine.connect() as connection:
        revision = str(connection.scalar(text("SELECT version_num FROM alembic_version")))
    return one(
        request,
        SystemInfo(
            build_version=build.package_version,
            source_commit=build.source_commit,
            migration_revision=revision,
            capabilities=Capabilities(),
            server_time=datetime.now(UTC),
        ),
    )


@router.get(
    "/doctor",
    operation_id="system_doctor",
    response_model=SingleResponse[DoctorStatus],
    dependencies=[
        Depends(require_permission(PermissionKey.SYSTEM_DOCTOR, fresh=True, admin_only=True))
    ],
)
def doctor(request: Request) -> SingleResponse[DoctorStatus]:
    services = request.app.state.services
    ready = readiness(services)
    admin = active_admin_exists(services)
    return one(
        request,
        DoctorStatus(
            status="PASS" if ready and admin else "FAIL",
            config=True,
            database=ready,
            migration=ready,
            builtin_rbac=ready,
            active_admin=admin,
        ),
    )
