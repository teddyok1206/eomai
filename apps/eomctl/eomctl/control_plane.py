"""Reviewed operator commands for the Codex execution control plane."""

from __future__ import annotations

import json
from pathlib import Path

import typer
from eom_orchestrator.control_bootstrap import (
    bootstrap_knowledge_analysis_control_plane,
    bootstrap_standard_control_plane,
)
from eom_orchestrator.control_service import ControlPlaneError
from eom_orchestrator.database import build_engine
from eom_orchestrator.knowledge_item_bootstrap import bootstrap_knowledge_item_control_plane
from eom_orchestrator.legacy_item_extraction_bootstrap import (
    bootstrap_legacy_item_extraction_control_plane,
)
from eom_orchestrator.settings import Settings

control_plane_app = typer.Typer(no_args_is_help=True)
STANDARD_CONFIG_DIRECTORY_OPTION = typer.Option(
    ...,
    "--config-directory",
    exists=True,
    file_okay=False,
    dir_okay=True,
    resolve_path=True,
    help="Reviewed absolute standard-item bootstrap directory",
)
KNOWLEDGE_ANALYSIS_CONFIG_DIRECTORY_OPTION = typer.Option(
    ...,
    "--config-directory",
    exists=True,
    file_okay=False,
    dir_okay=True,
    resolve_path=True,
    help="Reviewed absolute knowledge-analysis bootstrap directory",
)
KNOWLEDGE_ITEM_CONFIG_DIRECTORY_OPTION = typer.Option(
    ...,
    "--config-directory",
    exists=True,
    file_okay=False,
    dir_okay=True,
    resolve_path=True,
    help="Reviewed absolute knowledge-grounded-item bootstrap directory",
)
LEGACY_ITEM_EXTRACTION_CONFIG_DIRECTORY_OPTION = typer.Option(
    ...,
    "--config-directory",
    exists=True,
    file_okay=False,
    dir_okay=True,
    resolve_path=True,
    help="Reviewed absolute legacy-item-extraction bootstrap directory",
)
STANDARD_CONTENT_DIRECTORY_OPTION = typer.Option(
    None,
    "--content-directory",
    exists=True,
    file_okay=False,
    dir_okay=True,
    resolve_path=True,
    help=(
        "Reviewed canonical content directory required by standard-item "
        "reviewed-reference bootstraps"
    ),
)


@control_plane_app.command("bootstrap-standard")
def bootstrap_standard(
    source_commit: str = typer.Option(..., "--source-commit"),
    actor_id: str = typer.Option(..., "--actor-id"),
    evaluation_cases_total: int = typer.Option(..., "--evaluation-cases-total", min=1, max=10000),
    config_directory: Path = STANDARD_CONFIG_DIRECTORY_OPTION,
    content_directory: Path | None = STANDARD_CONTENT_DIRECTORY_OPTION,
) -> None:
    """Publish the reviewed standard preset and stale-by-default fixed account bindings."""

    engine = build_engine()
    try:
        result = bootstrap_standard_control_plane(
            engine,
            config_directory=config_directory,
            content_directory=content_directory,
            source_commit=source_commit,
            actor_id=actor_id,
            evaluation_cases_total=evaluation_cases_total,
            settings=Settings.from_environment(),
        )
    except ControlPlaneError as exc:
        typer.echo(json.dumps({"status": "FAILED", "error_code": exc.code}, sort_keys=True))
        raise typer.Exit(1) from None
    finally:
        engine.dispose()
    typer.echo(
        json.dumps(
            {"status": "SUCCEEDED", **result.model_dump(mode="json")},
            ensure_ascii=True,
            sort_keys=True,
        )
    )


@control_plane_app.command("bootstrap-knowledge-analysis")
def bootstrap_knowledge_analysis(
    source_commit: str = typer.Option(..., "--source-commit"),
    actor_id: str = typer.Option(..., "--actor-id"),
    evaluation_cases_total: int = typer.Option(..., "--evaluation-cases-total", min=1, max=10000),
    config_directory: Path = KNOWLEDGE_ANALYSIS_CONFIG_DIRECTORY_OPTION,
) -> None:
    """Publish the reviewed support-only knowledge-analysis preset without running Codex."""

    engine = build_engine()
    try:
        result = bootstrap_knowledge_analysis_control_plane(
            engine,
            config_directory=config_directory,
            source_commit=source_commit,
            actor_id=actor_id,
            evaluation_cases_total=evaluation_cases_total,
            settings=Settings.from_environment(),
        )
    except ControlPlaneError as exc:
        typer.echo(json.dumps({"status": "FAILED", "error_code": exc.code}, sort_keys=True))
        raise typer.Exit(1) from None
    finally:
        engine.dispose()
    typer.echo(
        json.dumps(
            {"status": "SUCCEEDED", **result.model_dump(mode="json")},
            ensure_ascii=True,
            sort_keys=True,
        )
    )


@control_plane_app.command("bootstrap-legacy-item-extraction")
def bootstrap_legacy_item_extraction(
    source_commit: str = typer.Option(..., "--source-commit"),
    actor_id: str = typer.Option(..., "--actor-id"),
    evaluation_cases_total: int = typer.Option(..., "--evaluation-cases-total", min=1, max=10000),
    config_directory: Path = LEGACY_ITEM_EXTRACTION_CONFIG_DIRECTORY_OPTION,
) -> None:
    """Publish the reviewed source-only extraction preset without invoking Codex."""

    engine = build_engine()
    try:
        result = bootstrap_legacy_item_extraction_control_plane(
            engine,
            config_directory=config_directory,
            source_commit=source_commit,
            actor_id=actor_id,
            evaluation_cases_total=evaluation_cases_total,
            settings=Settings.from_environment(),
        )
    except ControlPlaneError as exc:
        typer.echo(json.dumps({"status": "FAILED", "error_code": exc.code}, sort_keys=True))
        raise typer.Exit(1) from None
    finally:
        engine.dispose()
    typer.echo(
        json.dumps(
            {"status": "SUCCEEDED", **result.model_dump(mode="json")},
            ensure_ascii=True,
            sort_keys=True,
        )
    )


@control_plane_app.command("bootstrap-knowledge-item")
def bootstrap_knowledge_item(
    source_commit: str = typer.Option(..., "--source-commit"),
    actor_id: str = typer.Option(..., "--actor-id"),
    evaluation_cases_total: int = typer.Option(..., "--evaluation-cases-total", min=1, max=10000),
    config_directory: Path = KNOWLEDGE_ITEM_CONFIG_DIRECTORY_OPTION,
) -> None:
    """Publish the reviewed Graph-backed item preset without invoking Codex."""

    engine = build_engine()
    try:
        result = bootstrap_knowledge_item_control_plane(
            engine,
            config_directory=config_directory,
            source_commit=source_commit,
            actor_id=actor_id,
            evaluation_cases_total=evaluation_cases_total,
            settings=Settings.from_environment(),
        )
    except ControlPlaneError as exc:
        typer.echo(json.dumps({"status": "FAILED", "error_code": exc.code}, sort_keys=True))
        raise typer.Exit(1) from None
    finally:
        engine.dispose()
    typer.echo(
        json.dumps(
            {"status": "SUCCEEDED", **result.model_dump(mode="json")},
            ensure_ascii=True,
            sort_keys=True,
        )
    )
