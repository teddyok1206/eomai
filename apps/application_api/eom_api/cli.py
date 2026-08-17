"""Application API serve, doctor, and deterministic contract export commands."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from eom_api.app import create_app
from eom_api.health import active_admin_exists, readiness
from eom_api.lifespan import build_services
from eom_api.logging import configure_logging
from eom_api.openapi import export_openapi
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
        checks = {
            "config": True,
            "database": readiness(services),
            "migration_head": readiness(services),
            "builtin_rbac": readiness(services),
            "active_admin": active_admin_exists(services),
            "non_editable_import": "/home/eom/EOM" not in str(Path(__file__).resolve()),
            "loopback_bind": services.settings.server.host in {"127.0.0.1", "localhost", "::1"},
            "cors_disabled": True,
        }
    finally:
        services.engine.dispose()
    typer.echo(json.dumps({"status": "PASS" if all(checks.values()) else "FAIL", **checks}))
    if not all(checks.values()):
        raise typer.Exit(1)


def main() -> None:
    app()
