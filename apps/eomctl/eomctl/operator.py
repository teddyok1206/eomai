"""Emergency and bootstrap CLI adapter for Operator identity."""

from __future__ import annotations

import json
import os
import pwd
import stat
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer
from eom_identity_service.local_admin_recovery import (
    EmergencyAdminPasswordResetCommand,
    EmergencyAdminPasswordResetReason,
    LocalAdminPasswordRecoveryService,
    LocalAdminRecoveryAuthorization,
)
from eom_identity_service.service import CreateOperatorCommand, OperatorService
from eom_operator_identity.contracts import (
    ActorContext,
    ActorSource,
    ActorType,
    PermissionKey,
    RoleKey,
)
from eom_operator_identity.errors import IdentityError, IdentityErrorCode
from eom_orchestrator.database import build_engine

operator_app = typer.Typer(no_args_is_help=True)
INITIAL_ADMIN_FILE = Path("/home/eom/.eom-api-initial-admin")
MAX_PASSWORD_FILE_BYTES = 257


def _stable_file_identity(metadata: os.stat_result) -> tuple[int, ...]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mode,
        metadata.st_uid,
        metadata.st_gid,
        metadata.st_nlink,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


def _emit(value: object) -> None:
    typer.echo(json.dumps(value, ensure_ascii=False, indent=2, default=str))


def _service() -> OperatorService:
    return OperatorService(build_engine())


class _PosixEomRecoveryAuthorizer:
    """Derive the trusted principal from the process credentials at call time."""

    def authorize(self) -> LocalAdminRecoveryAuthorization:
        if os.getuid() != os.geteuid() or os.getgid() != os.getegid():
            raise IdentityError(
                IdentityErrorCode.EMERGENCY_RESET_UNAUTHORIZED,
                "emergency password reset rejects set-id execution",
            )
        try:
            principal = pwd.getpwuid(os.geteuid())
        except KeyError as exc:
            raise IdentityError(
                IdentityErrorCode.EMERGENCY_RESET_UNAUTHORIZED,
                "invoking operating-system principal is unknown",
            ) from exc
        if (
            principal.pw_name != "eom"
            or principal.pw_uid != os.geteuid()
            or principal.pw_gid != os.getegid()
            or principal.pw_uid == 0
        ):
            raise IdentityError(
                IdentityErrorCode.EMERGENCY_RESET_UNAUTHORIZED,
                "emergency password reset must run as the local eom user",
            )
        return LocalAdminRecoveryAuthorization(
            os_principal=principal.pw_name,
            os_uid=principal.pw_uid,
            os_gid=principal.pw_gid,
        )


def _emergency_recovery_service() -> LocalAdminPasswordRecoveryService:
    authorizer = _PosixEomRecoveryAuthorizer()
    # Reject an untrusted process before opening the database or reading credential bytes.
    if not isinstance(authorizer.authorize(), LocalAdminRecoveryAuthorization):
        raise IdentityError(
            IdentityErrorCode.EMERGENCY_RESET_UNAUTHORIZED,
            "local recovery authorization adapter returned an invalid result",
        )
    return LocalAdminPasswordRecoveryService(build_engine(), authorizer)


def _actor(operator_id: str) -> ActorContext:
    return ActorContext(
        actor_type=ActorType.OPERATOR,
        operator_id=operator_id,
        session_id=None,
        request_id=f"cli_{os.urandom(12).hex()}",
        authentication_time=datetime.now(UTC),
        permissions=frozenset(PermissionKey),
        source=ActorSource.CLI,
    )


def _password_file(path: Path) -> str:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    flags |= getattr(os, "O_NONBLOCK", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise typer.BadParameter("password file cannot be opened safely") from exc
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_uid != os.geteuid()
            or stat.S_IMODE(before.st_mode) != 0o600
            or before.st_nlink != 1
            or not 0 < before.st_size <= MAX_PASSWORD_FILE_BYTES
        ):
            raise typer.BadParameter(
                "password file must be a single-link regular file owned by the invoking user "
                "with mode 0600"
            )
        payload = bytearray()
        while len(payload) < before.st_size:
            chunk = os.read(descriptor, before.st_size - len(payload))
            if not chunk:
                raise typer.BadParameter("password file changed while being read")
            payload.extend(chunk)
        if os.read(descriptor, 1):
            raise typer.BadParameter("password file exceeds its validated size")
        after = os.fstat(descriptor)
        if _stable_file_identity(before) != _stable_file_identity(after):
            raise typer.BadParameter("password file changed while being read")
    finally:
        os.close(descriptor)
    if payload.endswith(b"\n"):
        del payload[-1:]
    if b"\n" in payload or b"\r" in payload:
        raise typer.BadParameter("password file must contain exactly one line")
    try:
        value = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise typer.BadParameter("password file must contain valid UTF-8") from exc
    finally:
        payload[:] = b"\0" * len(payload)
    return value


def _write_initial_admin_file(operator_id: str, username: str, password: str) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(INITIAL_ADMIN_FILE, flags, 0o600)
    try:
        payload = {
            "operator_id": operator_id,
            "username": username,
            "temporary_password": password,
            "created_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        }
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            descriptor = -1
            json.dump(payload, stream, ensure_ascii=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _identity_error(exc: IdentityError) -> None:
    _emit({"ok": False, "error_code": exc.code.value, "detail": str(exc)})
    raise typer.Exit(1)


@operator_app.command("bootstrap-admin")
def bootstrap_admin(
    username: str = typer.Option("admin", "--username"),
    display_name: str = typer.Option("EOM Administrator", "--display-name"),
) -> None:
    if INITIAL_ADMIN_FILE.exists():
        raise typer.BadParameter("initial admin credential file already exists")
    try:
        result = _service().bootstrap_admin(username=username, display_name=display_name)
        _write_initial_admin_file(
            result.operator.operator_id, result.operator.username, result.temporary_password
        )
    except IdentityError as exc:
        _identity_error(exc)
        return
    _emit(
        {
            "operator_id": result.operator.operator_id,
            "username": result.operator.username,
            "initial_credential_file": str(INITIAL_ADMIN_FILE),
            "must_change_password": True,
            "instruction": "Delete the one-time file after the first password change.",
        }
    )


@operator_app.command("create")
def create_operator(
    username: Annotated[str, typer.Option("--username")],
    display_name: Annotated[str, typer.Option("--display-name")],
    role: Annotated[RoleKey, typer.Option("--role")],
    temporary_password_file: Annotated[
        Path, typer.Option("--temporary-password-file", exists=True, dir_okay=False)
    ],
    actor_id: Annotated[str, typer.Option("--actor-id")],
) -> None:
    try:
        projection = _service().create_operator(
            CreateOperatorCommand(
                username=username,
                display_name=display_name,
                temporary_password=_password_file(temporary_password_file),
                initial_roles=(role,),
            ),
            _actor(actor_id),
        )
    except IdentityError as exc:
        _identity_error(exc)
        return
    _emit(projection.model_dump(mode="json"))


@operator_app.command("list")
def list_operators() -> None:
    _emit([item.model_dump(mode="json") for item in _service().list_operators()])


@operator_app.command("inspect")
def inspect_operator(operator_id: str) -> None:
    try:
        projection = _service().inspect_operator(operator_id)
    except IdentityError as exc:
        _identity_error(exc)
        return
    _emit(projection.model_dump(mode="json"))


@operator_app.command("roles")
def operator_roles(operator_id: str) -> None:
    try:
        projection = _service().inspect_operator(operator_id)
    except IdentityError as exc:
        _identity_error(exc)
        return
    _emit({"operator_id": projection.operator_id, "roles": projection.roles})


@operator_app.command("assign-role")
def assign_role(
    operator_id: str,
    role: Annotated[RoleKey, typer.Option("--role")],
    actor_id: str = typer.Option(..., "--actor-id"),
) -> None:
    try:
        projection = _service().assign_role(operator_id, role, _actor(actor_id))
    except IdentityError as exc:
        _identity_error(exc)
        return
    _emit(projection.model_dump(mode="json"))


@operator_app.command("revoke-role")
def revoke_role(
    operator_id: str,
    role: Annotated[RoleKey, typer.Option("--role")],
    actor_id: str = typer.Option(..., "--actor-id"),
    reason: str = typer.Option(..., "--reason"),
) -> None:
    try:
        projection = _service().revoke_role(operator_id, role, _actor(actor_id), reason=reason)
    except IdentityError as exc:
        _identity_error(exc)
        return
    _emit(projection.model_dump(mode="json"))


@operator_app.command("disable")
def disable_operator(
    operator_id: str,
    actor_id: str = typer.Option(..., "--actor-id"),
    reason: str = typer.Option(..., "--reason"),
) -> None:
    try:
        projection = _service().disable(operator_id, _actor(actor_id), reason=reason)
    except IdentityError as exc:
        _identity_error(exc)
        return
    _emit(projection.model_dump(mode="json"))


@operator_app.command("enable")
def enable_operator(operator_id: str, actor_id: str = typer.Option(..., "--actor-id")) -> None:
    try:
        projection = _service().enable(operator_id, _actor(actor_id))
    except IdentityError as exc:
        _identity_error(exc)
        return
    _emit(projection.model_dump(mode="json"))


@operator_app.command("revoke-sessions")
def revoke_sessions(operator_id: str, actor_id: str = typer.Option(..., "--actor-id")) -> None:
    try:
        count = _service().revoke_sessions(operator_id, _actor(actor_id))
    except IdentityError as exc:
        _identity_error(exc)
        return
    _emit({"operator_id": operator_id, "revoked_sessions": count})


@operator_app.command("emergency-reset-admin-password")
def emergency_reset_admin_password(
    operator_id: str,
    temporary_password_file: Annotated[
        Path, typer.Option("--temporary-password-file", exists=True, dir_okay=False)
    ],
    reason_code: Annotated[EmergencyAdminPasswordResetReason, typer.Option("--reason-code")],
    confirm_operator_id: Annotated[str, typer.Option("--confirm-operator-id")],
) -> None:
    """Issue a forced-change credential from the trusted local eom recovery boundary."""

    if confirm_operator_id != operator_id:
        raise typer.BadParameter("confirmed Operator ID does not match the reset target")
    try:
        result = _emergency_recovery_service().reset_admin_password(
            EmergencyAdminPasswordResetCommand(
                operator_id=operator_id,
                temporary_password=_password_file(temporary_password_file),
                reason_code=reason_code,
                request_id=f"cli_{os.urandom(12).hex()}",
            )
        )
    except IdentityError as exc:
        _identity_error(exc)
        return
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    _emit(
        {
            "operator_id": result.operator_id,
            "password_version": result.password_version,
            "revoked_sessions": result.revoked_sessions,
            "reset_at": result.reset_at,
            "must_change_password": result.must_change_password,
        }
    )
