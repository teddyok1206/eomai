"""Early owner-install rejection; no production DB, grants or SQL execution."""

from __future__ import annotations

from typing import cast
from unittest.mock import Mock

import pytest
from eom_identity_service import (
    OperatorAuthorizationFenceError,
    OperatorAuthorizationFenceOwnerPin,
    install_operator_authorization_fence,
)
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

OWNER = OperatorAuthorizationFenceOwnerPin("synthetic_owner", 12345)


def test_invalid_owner_is_rejected_before_session_or_connection_access():
    session = Mock()
    with pytest.raises(OperatorAuthorizationFenceError, match="CONFIGURATION_INVALID"):
        install_operator_authorization_fence(
            session, cast(OperatorAuthorizationFenceOwnerPin, object())
        )
    assert not session.mock_calls


def test_explicit_root_is_required_before_connection_access():
    with Session() as session:
        with pytest.raises(OperatorAuthorizationFenceError, match="CONTEXT_INVALID"):
            install_operator_authorization_fence(session, OWNER)
        assert not session.in_transaction()


def test_autobegin_is_not_an_explicit_owner_installation_root():
    with Session(create_engine("sqlite://")) as session:
        session.execute(text("SELECT 1"))
        with pytest.raises(OperatorAuthorizationFenceError, match="CONTEXT_INVALID"):
            install_operator_authorization_fence(session, OWNER)


def test_nested_first_entry_is_not_an_owner_installation_root():
    with (
        Session(create_engine("sqlite://")) as session,
        session.begin(),
        session.begin_nested(),
        pytest.raises(OperatorAuthorizationFenceError, match="CONTEXT_INVALID"),
    ):
        install_operator_authorization_fence(session, OWNER)


def test_sqlite_cannot_supply_a_postgresql_owner_installation():
    with (
        Session(create_engine("sqlite://")) as session,
        session.begin(),
        pytest.raises(OperatorAuthorizationFenceError, match="CONTEXT_INVALID"),
    ):
        install_operator_authorization_fence(session, OWNER)


def test_pending_orm_state_is_not_flushed_by_installation():
    from eom_identity_service.models import OperatorRecord

    with Session() as session, session.begin():
        session.add(OperatorRecord())
        with pytest.raises(OperatorAuthorizationFenceError, match="CONTEXT_INVALID"):
            install_operator_authorization_fence(session, OWNER)
        assert session.new
        session.rollback()


def test_public_identity_owner_exposes_installation_not_a_runtime_self_grant():
    from eom_identity_service import OperatorAuthorizationFenceInstallationResult
    from eom_identity_service.operator_authorization_fence_installation import (
        OperatorAuthorizationFenceInstallationResult as Result,
    )

    assert OperatorAuthorizationFenceInstallationResult is Result
    assert Result("REPLAYED", OWNER, "sha256:" + "1" * 64).owner == OWNER
