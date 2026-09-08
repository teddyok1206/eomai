from __future__ import annotations

import os
from contextlib import nullcontext
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import typer
from eom_identity_service import local_admin_recovery as recovery_module
from eom_identity_service.local_admin_recovery import (
    EmergencyAdminPasswordResetCommand,
    EmergencyAdminPasswordResetReason,
    LocalAdminPasswordRecoveryService,
    LocalAdminRecoveryAuthorization,
)
from eom_operator_identity.errors import IdentityError, IdentityErrorCode
from eomctl import operator as operator_cli
from typer.testing import CliRunner

OPERATOR_ID = "operator_" + "a" * 32
TEMPORARY_PASSWORD = "TEST_ONLY emergency password 84"


def _command(**overrides: object) -> EmergencyAdminPasswordResetCommand:
    values: dict[str, object] = {
        "operator_id": OPERATOR_ID,
        "temporary_password": TEMPORARY_PASSWORD,
        "reason_code": EmergencyAdminPasswordResetReason.ADMIN_CREDENTIAL_LOSS,
        "request_id": "cli_" + "c" * 24,
    }
    values.update(overrides)
    return EmergencyAdminPasswordResetCommand(**values)  # type: ignore[arg-type]


def _service_fixture(
    monkeypatch: pytest.MonkeyPatch, *, role: str = "ADMIN", status: str = "ACTIVE"
) -> tuple[LocalAdminPasswordRecoveryService, SimpleNamespace, SimpleNamespace, Mock, Mock, Mock]:
    operator = SimpleNamespace(
        operator_id=OPERATOR_ID,
        username="admin",
        display_name="EOM Administrator",
        status=status,
        must_change_password=False,
        lock_version=7,
    )
    credential = SimpleNamespace(
        password_hash="old-hash",
        password_algorithm="argon2id",
        password_version=2,
        must_change_password=False,
        password_changed_at=datetime(2026, 1, 1, tzinfo=UTC),
        failed_login_count=4,
        first_failed_at=datetime(2026, 1, 2, tzinfo=UTC),
        last_failed_at=datetime(2026, 1, 3, tzinfo=UTC),
        locked_until=datetime(2026, 1, 4, tzinfo=UTC),
    )
    session = Mock()
    sessions = Mock()
    password_service = Mock()
    password_service.hash_password.return_value = "new-argon2id-hash"
    authorizer = Mock()
    authorizer.authorize.return_value = LocalAdminRecoveryAuthorization(
        os_principal="eom", os_uid=1000, os_gid=1000
    )
    reset_service = object.__new__(LocalAdminPasswordRecoveryService)
    reset_service.sessions = sessions
    reset_service.authorizer = authorizer
    reset_service.passwords = password_service
    monkeypatch.setattr(recovery_module, "transaction", lambda _: nullcontext(session))
    monkeypatch.setattr(recovery_module, "lock_identity_invariants", Mock())
    require_operator = Mock(return_value=operator)
    require_credential = Mock(return_value=credential)
    monkeypatch.setattr(recovery_module, "require_operator", require_operator)
    monkeypatch.setattr(recovery_module, "require_credential", require_credential)
    monkeypatch.setattr(
        recovery_module,
        "active_role_assignments",
        Mock(return_value=[(SimpleNamespace(), SimpleNamespace(role_key=role))]),
    )
    revoke = Mock(return_value=3)
    monkeypatch.setattr(recovery_module, "revoke_operator_sessions", revoke)
    event = Mock()
    monkeypatch.setattr(recovery_module, "add_operator_event", event)
    return reset_service, operator, credential, password_service, revoke, event


def test_emergency_reset_rotates_credential_revokes_sessions_and_audits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reset_service, operator, credential, password_service, revoke, event = _service_fixture(
        monkeypatch
    )

    result = reset_service.reset_admin_password(_command())

    assert result.operator_id == OPERATOR_ID
    assert result.password_version == 3
    assert result.revoked_sessions == 3
    assert result.must_change_password
    assert operator.must_change_password
    assert operator.lock_version == 8
    assert credential.password_hash == "new-argon2id-hash"
    assert credential.password_algorithm == "argon2id"
    assert credential.password_version == 3
    assert credential.must_change_password
    assert credential.failed_login_count == 0
    assert credential.first_failed_at is None
    assert credential.last_failed_at is None
    assert credential.locked_until is None
    password_service.hash_password.assert_called_once_with(
        TEMPORARY_PASSWORD,
        username="admin",
        display_name="EOM Administrator",
    )
    assert revoke.call_args.kwargs == {
        "actor_id": "system",
        "reason": "EMERGENCY_PASSWORD_RESET",
        "now": result.reset_at,
    }
    assert revoke.call_args.args[1] == OPERATOR_ID
    payload = event.call_args.kwargs["payload"]
    assert payload == {
        "actor_type": "SYSTEM",
        "source": "CLI",
        "os_principal": "eom",
        "os_uid": 1000,
        "os_gid": 1000,
        "password_version": 3,
        "reason_code": "ADMIN_CREDENTIAL_LOSS",
        "revoked_sessions": 3,
    }
    serialized = repr(payload)
    assert TEMPORARY_PASSWORD not in serialized
    assert "new-argon2id-hash" not in serialized


def test_emergency_reset_rejects_non_admin_target(monkeypatch: pytest.MonkeyPatch) -> None:
    reset_service, _, credential, _, revoke, _ = _service_fixture(monkeypatch, role="VIEWER")

    with pytest.raises(IdentityError) as raised:
        reset_service.reset_admin_password(_command())

    assert raised.value.code is IdentityErrorCode.OPERATOR_ADMIN_REQUIRED
    assert credential.password_hash == "old-hash"
    revoke.assert_not_called()


def test_emergency_reset_rejects_disabled_target(monkeypatch: pytest.MonkeyPatch) -> None:
    reset_service, _, credential, password_service, revoke, _ = _service_fixture(
        monkeypatch, status="DISABLED"
    )

    with pytest.raises(IdentityError) as raised:
        reset_service.reset_admin_password(_command())

    assert raised.value.code is IdentityErrorCode.OPERATOR_DISABLED
    assert credential.password_hash == "old-hash"
    password_service.hash_password.assert_not_called()
    revoke.assert_not_called()


def test_emergency_reset_rolls_back_on_password_policy_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reset_service, operator, credential, password_service, revoke, event = _service_fixture(
        monkeypatch
    )
    password_service.hash_password.side_effect = IdentityError(
        IdentityErrorCode.AUTH_PASSWORD_POLICY_FAILED,
        "password does not satisfy policy",
    )

    with pytest.raises(IdentityError) as raised:
        reset_service.reset_admin_password(_command(temporary_password="short"))

    assert raised.value.code is IdentityErrorCode.AUTH_PASSWORD_POLICY_FAILED
    assert operator.lock_version == 7
    assert credential.password_hash == "old-hash"
    revoke.assert_not_called()
    event.assert_not_called()


def test_emergency_command_rejects_arbitrary_reason_text() -> None:
    with pytest.raises(ValueError, match="reason code is invalid"):
        _command(reason_code="credential was secret")


def test_emergency_command_repr_omits_temporary_password() -> None:
    rendered = repr(_command())

    assert TEMPORARY_PASSWORD not in rendered
    assert "temporary_password" not in rendered


def _write_password(path: Path, *, mode: int = 0o600) -> None:
    path.write_text(TEMPORARY_PASSWORD + "\n", encoding="utf-8")
    path.chmod(mode)


def test_password_file_uses_exact_single_link_identity(tmp_path: Path) -> None:
    password_file = tmp_path / "password"
    _write_password(password_file)

    assert operator_cli._password_file(password_file) == TEMPORARY_PASSWORD

    second_link = tmp_path / "password-link"
    os.link(password_file, second_link)
    with pytest.raises(typer.BadParameter, match="single-link"):
        operator_cli._password_file(password_file)


def test_password_file_rejects_symlink_and_unsafe_mode(tmp_path: Path) -> None:
    password_file = tmp_path / "password"
    _write_password(password_file)
    symlink = tmp_path / "symlink"
    symlink.symlink_to(password_file)
    with pytest.raises(typer.BadParameter, match="opened safely"):
        operator_cli._password_file(symlink)

    password_file.chmod(0o640)
    with pytest.raises(typer.BadParameter, match="mode 0600"):
        operator_cli._password_file(password_file)


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        (b"", "single-link regular file"),
        (b"x" * (operator_cli.MAX_PASSWORD_FILE_BYTES + 1), "single-link regular file"),
        (b"not\nexact\n", "exactly one line"),
        (b"not\rvalid", "exactly one line"),
        (b"\xff", "valid UTF-8"),
    ],
)
def test_password_file_rejects_malformed_payloads(
    tmp_path: Path, payload: bytes, message: str
) -> None:
    password_file = tmp_path / "password"
    password_file.write_bytes(payload)
    password_file.chmod(0o600)

    with pytest.raises(typer.BadParameter, match=message):
        operator_cli._password_file(password_file)


def test_password_file_rejects_fifo_without_blocking(tmp_path: Path) -> None:
    password_file = tmp_path / "password-fifo"
    os.mkfifo(password_file, 0o600)
    password_file.chmod(0o600)

    with pytest.raises(typer.BadParameter, match="single-link regular file"):
        operator_cli._password_file(password_file)


def test_password_file_rejects_same_descriptor_mutation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    password_file = tmp_path / "password"
    _write_password(password_file)
    real_read = os.read
    reads = 0

    def mutate_after_read(descriptor: int, count: int) -> bytes:
        nonlocal reads
        data = real_read(descriptor, count)
        reads += 1
        if reads == 1:
            metadata = password_file.stat()
            os.utime(
                password_file,
                ns=(metadata.st_atime_ns, metadata.st_mtime_ns + 1_000_000),
            )
        return data

    monkeypatch.setattr("eomctl.operator.os.read", mutate_after_read)
    with pytest.raises(typer.BadParameter, match="changed while being read"):
        operator_cli._password_file(password_file)


def test_password_file_closes_descriptor_on_validation_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    password_file = tmp_path / "password"
    _write_password(password_file, mode=0o640)
    real_open = os.open
    opened_descriptor: int | None = None

    def capture_open(path: Path, flags: int) -> int:
        nonlocal opened_descriptor
        opened_descriptor = real_open(path, flags)
        return opened_descriptor

    monkeypatch.setattr("eomctl.operator.os.open", capture_open)
    with pytest.raises(typer.BadParameter, match="mode 0600"):
        operator_cli._password_file(password_file)

    assert opened_descriptor is not None
    with pytest.raises(OSError):
        os.fstat(opened_descriptor)


def test_posix_recovery_authorizer_rejects_root(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("eomctl.operator.os.getuid", lambda: 0)
    monkeypatch.setattr("eomctl.operator.os.geteuid", lambda: 0)
    monkeypatch.setattr("eomctl.operator.os.getgid", lambda: 0)
    monkeypatch.setattr("eomctl.operator.os.getegid", lambda: 0)
    monkeypatch.setattr(
        "eomctl.operator.pwd.getpwuid",
        lambda _: SimpleNamespace(pw_name="root", pw_uid=0, pw_gid=0),
    )

    with pytest.raises(IdentityError) as raised:
        operator_cli._PosixEomRecoveryAuthorizer().authorize()

    assert raised.value.code is IdentityErrorCode.EMERGENCY_RESET_UNAUTHORIZED


def test_recovery_composition_authorizes_before_database_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order: list[str] = []
    authorizer = Mock()

    def authorize() -> LocalAdminRecoveryAuthorization:
        order.append("authorize")
        return LocalAdminRecoveryAuthorization(os_principal="eom", os_uid=1000, os_gid=1000)

    authorizer.authorize.side_effect = authorize
    monkeypatch.setattr(operator_cli, "_PosixEomRecoveryAuthorizer", lambda: authorizer)
    engine = Mock()

    def build_engine() -> Mock:
        order.append("engine")
        return engine

    monkeypatch.setattr(operator_cli, "build_engine", build_engine)
    service = Mock()

    def build_service(_engine: object, _authorizer: object) -> Mock:
        order.append("service")
        return service

    monkeypatch.setattr(
        operator_cli,
        "LocalAdminPasswordRecoveryService",
        build_service,
    )

    assert operator_cli._emergency_recovery_service() is service
    assert order == ["authorize", "engine", "service"]


def test_recovery_service_authorizes_before_opening_transaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authorizer = Mock()
    authorizer.authorize.side_effect = IdentityError(
        IdentityErrorCode.EMERGENCY_RESET_UNAUTHORIZED,
        "not the trusted local principal",
    )
    reset_service = object.__new__(LocalAdminPasswordRecoveryService)
    reset_service.sessions = Mock()
    reset_service.authorizer = authorizer
    reset_service.passwords = Mock()
    transaction = Mock()
    monkeypatch.setattr(recovery_module, "transaction", transaction)

    with pytest.raises(IdentityError) as raised:
        reset_service.reset_admin_password(_command())

    assert raised.value.code is IdentityErrorCode.EMERGENCY_RESET_UNAUTHORIZED
    transaction.assert_not_called()


def test_emergency_cli_requires_exact_confirmation_and_emits_no_secret(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    password_file = tmp_path / "password"
    _write_password(password_file)
    service = Mock()
    service.reset_admin_password.return_value = SimpleNamespace(
        operator_id=OPERATOR_ID,
        password_version=4,
        revoked_sessions=2,
        reset_at=datetime(2026, 9, 8, tzinfo=UTC),
        must_change_password=True,
    )
    monkeypatch.setattr(operator_cli, "_emergency_recovery_service", lambda: service)

    result = CliRunner().invoke(
        operator_cli.operator_app,
        [
            "emergency-reset-admin-password",
            OPERATOR_ID,
            "--temporary-password-file",
            str(password_file),
            "--reason-code",
            "ADMIN_CREDENTIAL_LOSS",
            "--confirm-operator-id",
            OPERATOR_ID,
        ],
    )

    assert result.exit_code == 0, result.output
    assert TEMPORARY_PASSWORD not in result.output
    assert str(password_file) not in result.output
    submitted = service.reset_admin_password.call_args.args[0]
    assert submitted.operator_id == OPERATOR_ID
    assert submitted.temporary_password == TEMPORARY_PASSWORD
    assert submitted.reason_code is EmergencyAdminPasswordResetReason.ADMIN_CREDENTIAL_LOSS
    assert result.stdout.count(OPERATOR_ID) == 1
    assert '"password_version": 4' in result.stdout
    assert '"revoked_sessions": 2' in result.stdout

    mismatch = CliRunner().invoke(
        operator_cli.operator_app,
        [
            "emergency-reset-admin-password",
            OPERATOR_ID,
            "--temporary-password-file",
            str(password_file),
            "--reason-code",
            "ADMIN_CREDENTIAL_LOSS",
            "--confirm-operator-id",
            "operator_" + "b" * 32,
        ],
    )
    assert mismatch.exit_code != 0
    assert service.reset_admin_password.call_count == 1
