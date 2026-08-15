"""Operator CLI for the independent observability service."""

from __future__ import annotations

import json
import logging
import os
import pwd
from pathlib import Path

import typer
import uvicorn

from eom_observe.app import build_services, create_app
from eom_observe.database import build_readonly_engine
from eom_observe.doctor import run_doctor
from eom_observe.logging import configure_logging
from eom_observe.repository import ObserveRepository
from eom_observe.security import generate_access_token, hash_access_token
from eom_observe.settings import (
    DEFAULT_SECRET_PATH,
    load_secrets,
    load_settings,
    parse_environment_file,
)
from eom_observe.snapshot import SnapshotBuilder

app = typer.Typer(no_args_is_help=True, help="Read-only EOM observability console")
auth_app = typer.Typer(no_args_is_help=True)
config_app = typer.Typer(no_args_is_help=True)
app.add_typer(auth_app, name="auth")
app.add_typer(config_app, name="config")
INITIAL_TOKEN_PATH = Path("/home/eom/.eom-observe-initial-token")


@app.command("doctor")
def doctor() -> None:
    result = run_doctor()
    typer.echo(json.dumps(result, indent=2))
    if not result["passed"]:
        raise typer.Exit(1)


@app.command("serve")
def serve() -> None:
    configure_logging()
    settings = load_settings()
    logging.getLogger("eom_observe.service").info(
        "observability service starting",
        extra={"event": "SERVICE_START"},
    )
    services = build_services(settings)
    uvicorn.run(
        create_app(services),
        host=settings.server.host,
        port=settings.server.port,
        log_config=None,
        access_log=False,
        server_header=False,
    )


@app.command("snapshot")
def snapshot_command() -> None:
    settings = load_settings()
    secrets_config = load_secrets()
    engine = build_readonly_engine(secrets_config.database_url, settings.snapshot.query_timeout_ms)
    try:
        snapshot = SnapshotBuilder(
            ObserveRepository(engine, event_limit=settings.snapshot.recent_event_limit), settings
        ).build()
        typer.echo(snapshot.model_dump_json(indent=2))
    finally:
        engine.dispose()


@config_app.command("validate")
def validate_config() -> None:
    settings = load_settings()
    typer.echo(
        json.dumps(
            {
                "valid": True,
                "host": settings.server.host,
                "port": settings.server.port,
                "root_path": settings.server.root_path,
            },
            indent=2,
        )
    )


def _write_token_file(token: str, path: Path) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(descriptor, f"{token}\n".encode())
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    try:
        account = pwd.getpwnam("eom")
        os.chown(path, account.pw_uid, account.pw_gid)
    except KeyError:
        pass
    os.chmod(path, 0o600)


def rotate_token(
    secret_path: Path = DEFAULT_SECRET_PATH, output_path: Path = INITIAL_TOKEN_PATH
) -> Path:
    values = parse_environment_file(secret_path)
    token = generate_access_token()
    values["EOM_OBSERVE_ACCESS_TOKEN_HASH"] = hash_access_token(token)
    required_order = (
        "EOM_OBSERVE_DATABASE_URL",
        "EOM_OBSERVE_ACCESS_TOKEN_HASH",
        "EOM_OBSERVE_SESSION_SECRET",
    )
    if not all(values.get(key) for key in required_order):
        raise RuntimeError("observability secret file is incomplete")
    temporary = secret_path.with_name(f".{secret_path.name}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o640)
    try:
        content = "".join(f"{key}='{values[key]}'\n" for key in required_order)
        os.write(descriptor, content.encode("utf-8"))
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    if secret_path.exists():
        os.chown(temporary, secret_path.stat().st_uid, secret_path.stat().st_gid)
    os.replace(temporary, secret_path)
    _write_token_file(token, output_path)
    return output_path


@auth_app.command("rotate-token")
def rotate_token_command() -> None:
    path = rotate_token()
    typer.echo(json.dumps({"rotated": True, "one_time_token_file": str(path)}, indent=2))


@app.command("verify-readonly")
def verify_readonly() -> None:
    settings = load_settings()
    secrets_config = load_secrets()
    engine = build_readonly_engine(secrets_config.database_url, settings.snapshot.query_timeout_ms)
    repository = ObserveRepository(engine)
    result = {
        "select": repository.ping(),
        "default_transaction_read_only": repository.database_is_readonly(),
        "required_tables": len(repository.required_tables()) == 9,
    }
    engine.dispose()
    typer.echo(json.dumps(result, indent=2))
    if not all(result.values()):
        raise typer.Exit(1)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
