"""Application API serve, doctor, and deterministic contract export commands."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from eom_api.app import create_app
from eom_api.health import active_admin_exists, readiness, runtime_database_privileges
from eom_api.lifespan import AppServices, build_services
from eom_api.logging import configure_logging
from eom_api.openapi import export_openapi
from eom_api.release_checks import packaged_openapi_valid
from eom_api.settings import load_settings

app = typer.Typer(no_args_is_help=True)
openapi_app = typer.Typer(no_args_is_help=True)
app.add_typer(openapi_app, name="openapi")


@app.command("serve")
def serve() -> None:
    import uvicorn

    settings = load_settings()
    if settings.server.workers != 1:
        raise typer.BadParameter("V0 process-local rate limiting requires one worker")
    configure_logging()
    uvicorn.run(
        create_app(),
        host=settings.server.host,
        port=settings.server.port,
        workers=1,
        access_log=False,
        server_header=False,
        date_header=False,
        proxy_headers=False,
    )


@openapi_app.command("export")
def openapi_export(
    output: Annotated[
        Path,
        typer.Option("--output", dir_okay=False),
    ] = Path("api/openapi/eom-api-v1.openapi.json"),
) -> None:
    services = build_services()
    try:
        digest = export_openapi(create_app(services), output)
    finally:
        services.engine.dispose()
    typer.echo(json.dumps({"output": str(output), "sha256": digest}, sort_keys=True))


@app.command("doctor")
def doctor() -> None:
    services = build_services()
    try:
        database_ready = readiness(services)
        active_admin = _safe_active_admin(services)
        checks = {
            "config": True,
            "secret_environment": _runtime_secret_environment(services),
            "token_hash_key": True,
            "database": database_ready,
            "runtime_database_role": _runtime_database_role(services),
            "runtime_database_privileges": runtime_database_privileges(services),
            "migration_head": database_ready,
            "builtin_rbac": database_ready,
            "active_admin": active_admin,
            "non_editable_import": "/home/eom/EOM" not in str(Path(__file__).resolve()),
            "loopback_bind": services.settings.server.host == "127.0.0.1"
            and services.settings.server.port == 8765,
            "allowed_hosts": set(services.settings.security.allowed_hosts)
            <= {"127.0.0.1", "localhost"},
            "cors_disabled": True,
            "openapi_hash": packaged_openapi_valid(),
            "system_user": _system_user(),
            "systemd_unit": Path("/etc/systemd/system/eom-api.service").is_file(),
            "repository_inaccessible": _unit_denies("/home/eom/EOM"),
            "nas_inaccessible": _unit_denies("/mnt/nas"),
            "docker_inaccessible": _unit_denies("/var/run/docker.sock"),
            "worker_home_inaccessible": _unit_denies("/srv/eom/worker-homes"),
            "codex_auth_inaccessible": _unit_denies("/root/.codex"),
        }
    finally:
        services.engine.dispose()
    typer.echo(json.dumps({"status": "PASS" if all(checks.values()) else "FAIL", **checks}))
    if not all(checks.values()):
        raise typer.Exit(1)


def _safe_active_admin(services: AppServices) -> bool:
    try:
        return active_admin_exists(services)
    except Exception:
        return False


def _runtime_database_role(services: AppServices) -> bool:
    try:
        with services.engine.connect() as connection:
            return str(connection.exec_driver_sql("SELECT current_user").scalar_one()) == (
                "eom_api_runtime"
            )
    except Exception:
        return False


def _runtime_secret_environment(services: AppServices) -> bool:
    values = (
        services.secrets.database_url.get_secret_value(),
        services.secrets.token_hash_key.get_secret_value(),
        services.secrets.fingerprint_key.get_secret_value(),
    )
    return all(value and "placeholder" not in value.casefold() for value in values)


def _system_user() -> bool:
    try:
        import pwd

        entry = pwd.getpwnam("eom-api")
        return (
            entry.pw_name == "eom-api"
            and entry.pw_dir == "/var/lib/eom-api"
            and entry.pw_shell == "/usr/sbin/nologin"
        )
    except (KeyError, OSError):
        return False


def _unit_denies(path: str) -> bool:
    try:
        unit = Path("/etc/systemd/system/eom-api.service").read_text(encoding="utf-8")
    except OSError:
        return False
    return f"InaccessiblePaths={path}" in unit


def main() -> None:
    app()
