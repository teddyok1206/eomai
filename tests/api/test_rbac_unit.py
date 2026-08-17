from __future__ import annotations

from datetime import UTC, datetime

import pytest
from eom_operator_identity.contracts import (
    ROLE_PERMISSIONS,
    ActorContext,
    ActorSource,
    ActorType,
    PermissionKey,
    RoleKey,
    normalize_username,
    validate_display_name,
    validate_username,
)
from pydantic import ValidationError


@pytest.mark.parametrize(
    "username", ["admin", "reviewer01", "author.one", "editor_one", "viewer-01"]
)
def test_username_validation(username: str) -> None:
    assert validate_username(username) == username
    assert normalize_username(username) == username


@pytest.mark.parametrize(
    "username",
    ["ad", "Admin", "1admin", ".admin", "admin.", "admin..one", "admin__one", "관리자"],
)
def test_username_rejects_invalid_format(username: str) -> None:
    with pytest.raises(ValueError, match="username"):
        validate_username(username)


def test_display_name_accepts_korean_and_rejects_control_characters() -> None:
    assert validate_display_name("통합과학 검토자") == "통합과학 검토자"
    with pytest.raises(ValueError, match="control"):
        validate_display_name("검토자\n관리자")


def test_builtin_role_matrix_is_immutable_and_complete() -> None:
    assert set(ROLE_PERMISSIONS) == set(RoleKey)
    assert ROLE_PERMISSIONS[RoleKey.ADMIN] == frozenset(PermissionKey)
    assert PermissionKey.WORKFLOW_START in ROLE_PERMISSIONS[RoleKey.AUTHOR]
    assert PermissionKey.WORKFLOW_APPROVE not in ROLE_PERMISSIONS[RoleKey.AUTHOR]
    assert PermissionKey.WORKFLOW_APPROVE in ROLE_PERMISSIONS[RoleKey.REVIEWER]
    assert PermissionKey.USAGE_FULFILL_PLAN in ROLE_PERMISSIONS[RoleKey.EDITOR]
    with pytest.raises(TypeError):
        ROLE_PERMISSIONS[RoleKey.VIEWER] = frozenset()  # type: ignore[index]


def test_actor_context_requires_operator_and_api_session() -> None:
    with pytest.raises(ValidationError):
        ActorContext(
            actor_type=ActorType.OPERATOR,
            operator_id=None,
            session_id=None,
            request_id="req_test_context",
            authentication_time=datetime.now(UTC),
            permissions=frozenset(),
            source=ActorSource.CLI,
        )
    with pytest.raises(ValidationError):
        ActorContext(
            actor_type=ActorType.OPERATOR,
            operator_id="operator_" + "a" * 32,
            session_id=None,
            request_id="req_test_context",
            authentication_time=datetime.now(UTC),
            permissions=frozenset(),
            source=ActorSource.APPLICATION_API,
        )
