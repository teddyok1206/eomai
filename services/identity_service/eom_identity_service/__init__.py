"""Operator identity application and persistence service."""

from eom_identity_service.authenticated_session_fence import (
    AuthenticatedOperatorSession,
    AuthenticatedSessionFence,
    AuthenticatedSessionFenceError,
    AuthenticatedSessionFenceOwnerPin,
)
from eom_identity_service.operator_authorization_fence import OperatorAuthorizationFence
from eom_identity_service.operator_authorization_fence_sql import (
    OPERATOR_AUTHORIZATION_FENCE_BODY,
    OPERATOR_AUTHORIZATION_FENCE_BODY_SHA256,
    OPERATOR_AUTHORIZATION_FENCE_CALL_SQL,
    OPERATOR_AUTHORIZATION_FENCE_CREATE_SQL,
    OPERATOR_AUTHORIZATION_FENCE_EXECUTE_ROLE,
    OPERATOR_AUTHORIZATION_FENCE_FUNCTION,
    OPERATOR_AUTHORIZATION_FENCE_GRANT_SQL,
    OPERATOR_AUTHORIZATION_FENCE_REVOKE_PUBLIC_SQL,
    OPERATOR_AUTHORIZATION_FENCE_SIGNATURE,
    OperatorAuthorizationFenceError,
    OperatorAuthorizationFenceOwnerPin,
    require_operator_authorization_fence_installation,
)
from eom_identity_service.owner_session_transport import (
    OWNER_SESSION_TRANSPORT_SECONDS,
    FixedIdentityProviderPin,
    IdentityOwnerSessionProviderAdmission,
    OwnerSessionTransportError,
    OwnerSessionTransportObservation,
    assert_identity_provider_current,
    export_owner_session_capture,
    import_owner_session_capture,
    observe_owner_session_transport,
)
from eom_identity_service.postgres_operator_authorization_fence import (
    OPERATOR_AUTHORIZATION_FENCE_LOCK_TIMEOUT_MS,
    OPERATOR_AUTHORIZATION_FENCE_STATEMENT_TIMEOUT_MS,
    PostgresOperatorAuthorizationFence,
)

__all__ = [
    "OPERATOR_AUTHORIZATION_FENCE_BODY",
    "OPERATOR_AUTHORIZATION_FENCE_BODY_SHA256",
    "OPERATOR_AUTHORIZATION_FENCE_CALL_SQL",
    "OPERATOR_AUTHORIZATION_FENCE_CREATE_SQL",
    "OPERATOR_AUTHORIZATION_FENCE_EXECUTE_ROLE",
    "OPERATOR_AUTHORIZATION_FENCE_FUNCTION",
    "OPERATOR_AUTHORIZATION_FENCE_GRANT_SQL",
    "OPERATOR_AUTHORIZATION_FENCE_LOCK_TIMEOUT_MS",
    "OPERATOR_AUTHORIZATION_FENCE_REVOKE_PUBLIC_SQL",
    "OPERATOR_AUTHORIZATION_FENCE_SIGNATURE",
    "OPERATOR_AUTHORIZATION_FENCE_STATEMENT_TIMEOUT_MS",
    "OWNER_SESSION_TRANSPORT_SECONDS",
    "AuthenticatedOperatorSession",
    "AuthenticatedSessionFence",
    "AuthenticatedSessionFenceError",
    "AuthenticatedSessionFenceOwnerPin",
    "FixedIdentityProviderPin",
    "IdentityOwnerSessionProviderAdmission",
    "OperatorAuthorizationFence",
    "OperatorAuthorizationFenceError",
    "OperatorAuthorizationFenceOwnerPin",
    "OwnerSessionTransportError",
    "OwnerSessionTransportObservation",
    "PostgresOperatorAuthorizationFence",
    "assert_identity_provider_current",
    "export_owner_session_capture",
    "import_owner_session_capture",
    "observe_owner_session_transport",
    "require_operator_authorization_fence_installation",
]
