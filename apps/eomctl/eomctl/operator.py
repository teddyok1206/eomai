"""Emergency and bootstrap CLI adapter for Operator identity."""

from __future__ import annotations

import json
import os
import stat
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer
from eom_identity_service.service import CreateOperatorCommand, OperatorService
from eom_operator_identity.contracts import (
    ActorContext,
    ActorSource,
    ActorType,
    PermissionKey,
    RoleKey,
)
from eom_operator_identity.errors import IdentityError
from eom_orchestrator.database import build_engine

operator_app = typer.Typer(no_args_is_help=True)
INITIAL_ADMIN_FILE = Path("/home/eom/.eom-api-initial-admin")


def _emit(value: object) -> None:
    typer.echo(json.dumps(value, ensure_ascii=False, indent=2, default=str))


def _service() -> OperatorService:
    return OperatorService(build_engine())


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
    metadata = path.lstat()
    if not stat.S_ISREG(metadata.st_mode) or path.is_symlink():
        raise typer.BadParameter("temporary password file must be a regular file")
    if metadata.st_uid != os.getuid() or stat.S_IMODE(metadata.st_mode) & 0o077:
        raise typer.BadParameter("temporary password file must be owned by eom with mode 0600")
    value = path.read_text(encoding="utf-8")
    if value.endswith("\n"):
        value = value[:-1]
        if value.endswith("\r"):
            value = value[:-1]
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
