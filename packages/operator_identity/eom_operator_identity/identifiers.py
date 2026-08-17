"""Opaque identity identifiers."""

import secrets


def _new(prefix: str) -> str:
    return f"{prefix}{secrets.token_hex(16)}"


def new_operator_id() -> str:
    return _new("operator_")


def new_credential_id() -> str:
    return _new("opcred_")


def new_role_id() -> str:
    return _new("role_")


def new_permission_id() -> str:
    return _new("permission_")


def new_role_assignment_id() -> str:
    return _new("roleassign_")


def new_operator_event_id() -> str:
    return _new("opevent_")


def new_api_session_id() -> str:
    return _new("apisession_")


def new_token_family_id() -> str:
    return _new("tokenfamily_")


def new_api_token_id() -> str:
    return _new("apitoken_")


def new_idempotency_record_id() -> str:
    return _new("apiidem_")


def new_api_audit_event_id() -> str:
    return _new("apiaudit_")
