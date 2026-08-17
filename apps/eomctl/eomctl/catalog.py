"""CLI adapters for manual intake, content packs, registry, and usage."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer
from eom_catalog_contracts import load_schema
from eom_catalog_service.intake_files import load_strict_json
from eom_catalog_service.intake_service import IntakeService
from eom_catalog_service.settings import CatalogSettings
from eom_orchestrator.database import build_engine
from sqlalchemy import Engine

content_app = typer.Typer(no_args_is_help=True)
intake_app = typer.Typer(no_args_is_help=True)
pack_app = typer.Typer(no_args_is_help=True)
content_app.add_typer(intake_app, name="intake")
content_app.add_typer(pack_app, name="pack")


def _emit(value: object) -> None:
    typer.echo(json.dumps(value, ensure_ascii=False, indent=2, default=str))


def _intake_service() -> tuple[IntakeService, Engine]:
    engine = build_engine()
    return IntakeService(engine), engine


@intake_app.command("create")
def intake_create(
    source_dir: Annotated[Path, typer.Option("--source-dir", exists=True, file_okay=False)],
    batch_name: Annotated[str, typer.Option("--batch-name")],
    received_by: Annotated[str, typer.Option("--received-by")],
    purpose: Annotated[str, typer.Option("--purpose")] = "PLACEHOLDER_PURPOSE",
) -> None:
    service, engine = _intake_service()
    try:
        record = service.create(
            source_dir,
            batch_name=batch_name,
            received_by=received_by,
            purpose=purpose,
        )
        _emit(service.batch_dict(record))
    finally:
        engine.dispose()


@intake_app.command("inspect")
def intake_inspect(batch_id: str) -> None:
    service, engine = _intake_service()
    try:
        _emit(service.inspect(batch_id))
    finally:
        engine.dispose()


@intake_app.command("attach-analysis")
def intake_attach_analysis(
    batch_id: str,
    analysis_report: Annotated[Path, typer.Option("--analysis-report", exists=True)],
    mapping_proposal: Annotated[Path, typer.Option("--mapping-proposal", exists=True)],
    uncertainties: Annotated[Path, typer.Option("--uncertainties", exists=True)],
) -> None:
    service, engine = _intake_service()
    try:
        record = service.attach_analysis(
            batch_id,
            analysis_report=analysis_report,
            mapping_proposal=mapping_proposal,
            uncertainties=uncertainties,
        )
        _emit(service.analysis_dict(record))
    finally:
        engine.dispose()


@intake_app.command("validate")
def intake_validate(batch_id: str) -> None:
    service, engine = _intake_service()
    try:
        _emit(service.batch_dict(service.validate(batch_id)))
    finally:
        engine.dispose()


@intake_app.command("decide")
def intake_decide(
    batch_id: str,
    decision: Annotated[str, typer.Option("--decision")],
    decision_file: Annotated[Path, typer.Option("--decision-file", exists=True)],
    actor_id: Annotated[str, typer.Option("--actor-id")],
) -> None:
    expected = decision.replace("-", "_").upper()
    raw_decision = load_strict_json(decision_file)
    actual_decision = str(raw_decision.get("decision", ""))
    if expected != actual_decision:
        raise typer.BadParameter("decision option does not match the decision file")
    service, engine = _intake_service()
    try:
        record = service.decide(batch_id, decision_file, actor_id=actor_id)
        _emit(service.batch_dict(record))
    finally:
        engine.dispose()


@intake_app.command("reject")
def intake_reject(
    batch_id: str,
    reason: str = typer.Option(..., "--reason"),
    actor_id: str = typer.Option(..., "--actor-id"),
) -> None:
    service, engine = _intake_service()
    try:
        _emit(service.batch_dict(service.reject(batch_id, reason=reason, actor_id=actor_id)))
    finally:
        engine.dispose()


@intake_app.command("list")
def intake_list(limit: int = typer.Option(50, min=1, max=200)) -> None:
    service, engine = _intake_service()
    try:
        _emit(service.list_batches(limit))
    finally:
        engine.dispose()


@intake_app.command("events")
def intake_events(batch_id: str) -> None:
    service, engine = _intake_service()
    try:
        _emit(service.events(batch_id))
    finally:
        engine.dispose()


@intake_app.command("doctor")
def intake_doctor() -> None:
    settings = CatalogSettings.from_environment()
    schema_names = (
        "intake-manifest",
        "mapping-proposal",
        "uncertainties",
        "human-decision",
    )
    checks = [
        {
            "name": "nas_intake_root",
            "status": "PASS" if settings.intake_root.is_dir() else "FAIL",
            "detail": "nas://content-intake",
        },
        {
            "name": "artifact_service",
            "status": "PASS" if settings.nas_artifact_root.is_dir() else "FAIL",
            "detail": "nas://artifacts",
        },
    ]
    for name in schema_names:
        try:
            load_schema(name)
            status = "PASS"
        except Exception:
            status = "FAIL"
        checks.append({"name": f"schema_{name}", "status": status, "detail": name})
    passed = all(check["status"] == "PASS" for check in checks)
    _emit({"passed": passed, "checks": checks})
    if not passed:
        raise typer.Exit(1)


@intake_app.command("generate-pack-source")
def intake_generate_pack_source(
    batch_id: str,
    pack_key: Annotated[str, typer.Option("--pack-key")],
    new_version: Annotated[str, typer.Option("--new-version")],
    output: Annotated[Path, typer.Option("--output")],
) -> None:
    raise typer.BadParameter(
        f"pack source generation is unavailable until the pack compiler stage: "
        f"{batch_id} {pack_key}@{new_version} -> {output}"
    )
