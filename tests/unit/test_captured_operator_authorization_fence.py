"""Synthetic HMAC/current-row composition, never an installed Identity grant."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import cast

import pytest
from eom_identity_service import (
    AuthenticatedSessionFence,
    CapturedOperatorAuthorizationFence,
    OperatorAuthorizationFenceError,
)
from eom_operator_identity.contracts import PermissionKey
from sqlalchemy.orm import Session

from tests.unit.test_authenticated_session_fence import (
    PIN,
    SyntheticRoot,
    verified_capture,
)


def test_actual_capture_adapts_without_minting_permission_or_refreshing_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, capture = verified_capture(monkeypatch)
    adapter = CapturedOperatorAuthorizationFence(
        capture, AuthenticatedSessionFence(PIN), PermissionKey.WORKFLOW_START
    )
    before = source.api_session.last_seen_at, source.token.last_used_at
    adapter.fence_current_operator(cast(Session, source), capture.operator_id)
    assert source.order == ["OperatorRecord", "ApiSessionRecord", "ApiTokenRecord"]
    assert (source.api_session.last_seen_at, source.token.last_used_at) == before
    assert source.raw_token not in repr(adapter)
    assert source.token.verifier_hash not in repr(adapter)


def test_request_actor_cannot_replace_actual_captured_operator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, capture = verified_capture(monkeypatch)
    adapter = CapturedOperatorAuthorizationFence(
        capture, AuthenticatedSessionFence(PIN), PermissionKey.WORKFLOW_START
    )
    with pytest.raises(OperatorAuthorizationFenceError, match="FORBIDDEN"):
        adapter.fence_current_operator(cast(Session, source), "operator_" + "f" * 32)
    assert source.order == []


@pytest.mark.parametrize("mutation", ["permission", "disabled", "session", "access"])
def test_late_current_denial_is_not_cached(monkeypatch: pytest.MonkeyPatch, mutation: str) -> None:
    source, capture = verified_capture(monkeypatch)
    adapter = CapturedOperatorAuthorizationFence(
        capture, AuthenticatedSessionFence(PIN), PermissionKey.WORKFLOW_START
    )
    adapter.fence_current_operator(cast(Session, source), capture.operator_id)
    if mutation == "permission":
        source.permissions = frozenset()
    elif mutation == "disabled":
        source.operator.status = "DISABLED"
    elif mutation == "session":
        source.api_session.revoked_at = datetime.now(UTC)
    else:
        source.token.revoked_at = datetime.now(UTC)
    with pytest.raises(OperatorAuthorizationFenceError, match="FORBIDDEN"):
        adapter.fence_current_operator(cast(Session, source), capture.operator_id)


def test_savepoint_requires_original_root_and_next_root_rechecks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, capture = verified_capture(monkeypatch)
    adapter = CapturedOperatorAuthorizationFence(
        capture, AuthenticatedSessionFence(PIN), PermissionKey.WORKFLOW_START
    )
    source.nested = object()
    with pytest.raises(OperatorAuthorizationFenceError, match="CONTEXT_INVALID"):
        adapter.fence_current_operator(cast(Session, source), capture.operator_id)
    source.nested = None
    adapter.fence_current_operator(cast(Session, source), capture.operator_id)
    source.nested = object()
    adapter.fence_current_operator(cast(Session, source), capture.operator_id)
    source.nested = None
    source.root = SyntheticRoot()
    source.permissions = frozenset()
    with pytest.raises(OperatorAuthorizationFenceError, match="FORBIDDEN"):
        adapter.fence_current_operator(cast(Session, source), capture.operator_id)


def test_database_failure_does_not_escape_adapter(monkeypatch: pytest.MonkeyPatch) -> None:
    source, capture = verified_capture(monkeypatch)
    source.connection_value.fail = True
    adapter = CapturedOperatorAuthorizationFence(
        capture, AuthenticatedSessionFence(PIN), PermissionKey.WORKFLOW_START
    )
    with pytest.raises(OperatorAuthorizationFenceError) as failure:
        adapter.fence_current_operator(cast(Session, source), capture.operator_id)
    assert str(failure.value) == "OPERATOR_AUTHORIZATION_FENCE_UNAVAILABLE"


def test_constructor_does_not_accept_request_dto_as_capture() -> None:
    with pytest.raises(OperatorAuthorizationFenceError, match="CONFIGURATION_INVALID"):
        CapturedOperatorAuthorizationFence(  # type: ignore[arg-type]
            {"operator_id": "operator_" + "a" * 32},
            AuthenticatedSessionFence(PIN),
            PermissionKey.WORKFLOW_START,
        )
