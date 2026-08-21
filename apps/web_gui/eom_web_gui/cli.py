"""CLI entry point for EOM Scientific Studio."""

from __future__ import annotations

import typer
import uvicorn

from eom_web_gui.settings import load_settings

app = typer.Typer(add_completion=False, no_args_is_help=False)


@app.callback(invoke_without_command=True)
def serve() -> None:
    settings = load_settings()
    uvicorn.run(
        "eom_web_gui.app:create_app",
        factory=True,
        host=settings.server.host,
        port=settings.server.port,
        workers=settings.server.workers,
        access_log=False,
    )


def main() -> None:
    app()
