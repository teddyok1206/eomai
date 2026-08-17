"""Permission resolution facade kept separate from HTTP dependencies."""

from eom_operator_identity import PermissionKey


def has_permission(permissions: frozenset[PermissionKey], required: PermissionKey) -> bool:
    return required in permissions
