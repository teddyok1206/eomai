from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import Mock

import pytest
from eom_identity_service.approved_login_id_recovery import (
    APPROVED_PAIR_PINS,
    ApprovedLoginIdPasswordResetResult,
)
from eom_operator_identity.errors import IdentityError, IdentityErrorCode
from eomctl import operator as operator_cli
from typer.testing import CliRunner

PINS = sorted(APPROVED_PAIR_PINS)


def _arguments(pins: list[tuple[str, int]] | None = None) -> list[str]:
    targets = PINS if pins is None else pins
    arguments = ["approved-reset-login-id-passwords"]
    for operator_id, version in targets:
        arguments.extend(("--approved-target", f"{operator_id}:{version}"))
        arguments.extend(("--confirm-operator-id", operator_id))
    return arguments


@pytest.mark.parametrize(
    "pins",
    [
        PINS[:1],
        [PINS[0], PINS[0]],
        [(operator_id, 2) for operator_id, _ in PINS],
        [("operator_" + "a" * 32, 1), ("operator_" + "b" * 32, 1)],
    ],
)
def test_cli_rejects_unapproved_pins_before_authorization_or_engine(
    monkeypatch: pytest.MonkeyPatch, pins: list[tuple[str, int]]
) -> None:
    authorize = Mock()
    engine = Mock()
    monkeypatch.setattr(operator_cli, "_local_recovery_authorizer", authorize)
    monkeypatch.setattr(operator_cli, "build_engine", engine)

    result = CliRunner().invoke(operator_cli.operator_app, _arguments(pins))

    assert result.exit_code != 0
    authorize.assert_not_called()
    engine.assert_not_called()


def test_cli_rejects_os_authorization_before_opening_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authorize = Mock(
        side_effect=IdentityError(IdentityErrorCode.EMERGENCY_RESET_UNAUTHORIZED, "denied")
    )
    engine = Mock()
    monkeypatch.setattr(operator_cli, "_local_recovery_authorizer", authorize)
    monkeypatch.setattr(operator_cli, "build_engine", engine)

    result = CliRunner().invoke(operator_cli.operator_app, _arguments())

    assert result.exit_code == 1
    assert "EMERGENCY_RESET_UNAUTHORIZED" in result.output
    engine.assert_not_called()


def test_cli_invokes_only_approved_pair_and_prints_no_password(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authorize = Mock()
    service = Mock()
    service.reset_approved_pair.return_value = tuple(
        ApprovedLoginIdPasswordResetResult(operator_id, 2, 2, 0, datetime.now(UTC), True)
        for operator_id, _ in PINS
    )
    monkeypatch.setattr(operator_cli, "_local_recovery_authorizer", authorize)
    monkeypatch.setattr(operator_cli, "build_engine", Mock())
    factory = Mock(return_value=service)
    monkeypatch.setattr(operator_cli, "ApprovedLoginIdPasswordRecoveryService", factory)

    result = CliRunner().invoke(operator_cli.operator_app, _arguments())

    assert result.exit_code == 0, result.output
    command = service.reset_approved_pair.call_args.args[0]
    assert {
        (target.operator_id, target.expected_resource_version) for target in command.targets
    } == (APPROVED_PAIR_PINS)
    assert '"must_change_password": true' in result.output
    assert "username" not in result.output
    assert "temporary_password" not in result.output
    assert "password_hash" not in result.output
