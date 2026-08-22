from __future__ import annotations

from eom_api.app import create_app
from eom_api.openapi import AUTH_CONTROL_OPERATIONS, PUBLIC_OPERATIONS
from eom_operator_identity import ROLE_PERMISSIONS, PermissionKey, RoleKey

from tests.api.helpers import disconnected_services

HTTP_METHODS = {"get", "post", "put", "patch", "delete"}


def test_role_permission_matrix() -> None:
    assert PermissionKey.WORKFLOW_START not in ROLE_PERMISSIONS[RoleKey.VIEWER]
    assert PermissionKey.WORKFLOW_START in ROLE_PERMISSIONS[RoleKey.AUTHOR]
    assert PermissionKey.WORKFLOW_APPROVE in ROLE_PERMISSIONS[RoleKey.REVIEWER]
    assert PermissionKey.DELIVERABLE_CREATE in ROLE_PERMISSIONS[RoleKey.EDITOR]
    assert ROLE_PERMISSIONS[RoleKey.ADMIN] == frozenset(PermissionKey)


def test_deny_by_default_route_metadata_and_public_allowlist() -> None:
    services = disconnected_services()
    try:
        schema = create_app(services).openapi()
    finally:
        services.engine.dispose()
    public: set[str] = set()
    for path_item in schema["paths"].values():
        for method, operation in path_item.items():
            if method not in HTTP_METHODS:
                continue
            operation_id = operation["operationId"]
            if operation.get("x-eom-public"):
                public.add(operation_id)
                assert "security" not in operation
            elif operation_id in AUTH_CONTROL_OPERATIONS:
                assert operation.get("x-eom-auth-control")
                assert operation.get("security")
            else:
                assert operation.get("x-eom-permission")
                assert operation.get("security")
    assert public == set(PUBLIC_OPERATIONS)


def test_admin_only_operations_are_explicit() -> None:
    services = disconnected_services()
    try:
        schema = create_app(services).openapi()
    finally:
        services.engine.dispose()
    admin_operations = {
        operation["operationId"]
        for path_item in schema["paths"].values()
        for method, operation in path_item.items()
        if method in HTTP_METHODS and operation.get("x-eom-admin-only")
    }
    assert "operator_create" in admin_operations
    assert "operator_disable" in admin_operations
    assert "system_doctor" in admin_operations
    assert "workflow_reconcile" in admin_operations
    assert "item_structured_content_import" in admin_operations
