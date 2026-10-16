"""Shared current-account guard; permissions remain explicit per read use case."""

from collections.abc import Set

from eom_identity_service.tokens import AccessAuthentication
from eom_operator_identity import PermissionKey

from eom_api.errors import ApiError


def authorize_current_operator_read(
    authentication: AccessAuthentication, required: Set[PermissionKey]
) -> None:
    """No session renewal or authority grant; Catalog still resolves actual source rights."""
    if (
        authentication.operator.status != "ACTIVE"
        or authentication.operator.must_change_password
        or authentication.password_change_required
        or not required <= authentication.permissions
    ):
        raise ApiError(403, "PERMISSION_DENIED", "Permission denied", "Comparison read denied.")
