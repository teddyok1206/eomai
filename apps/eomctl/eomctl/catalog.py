"""CLI adapters for manual intake, content packs, registry, and usage."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer
from eom_catalog_contracts import load_schema
from eom_catalog_service.content_pack_files import build_pack, compile_pack, inspect_bundle
from eom_catalog_service.content_pack_service import ContentPackService
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


def _pack_service() -> tuple[ContentPackService, Engine]:
    engine = build_engine()
    return ContentPackService(engine), engine


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
    service, engine = _pack_service()
    try:
        _emit(
            service.generate_source(
                batch_id,
                pack_key=pack_key,
                version=new_version,
                output=output,
            )
        )
    finally:
        engine.dispose()


@pack_app.command("validate")
def pack_validate(pack_directory: Path) -> None:
    compiled = compile_pack(pack_directory)
    _emit(
        {
            "valid": True,
            "pack_key": compiled.manifest.pack.key,
            "version": compiled.manifest.pack.version,
            "source_tree_sha256": compiled.source_tree_sha256,
            "file_count": len(compiled.files),
        }
    )


@pack_app.command("build")
def pack_build(pack_directory: Path, output: Annotated[Path, typer.Option("--output")]) -> None:
    built = build_pack(pack_directory, output)
    _emit(
        {
            "bundle": str(built.bundle_path),
            "bundle_sha256": built.bundle_sha256,
            "manifest": str(built.manifest_path),
            "manifest_sha256": built.manifest_sha256,
        }
    )


@pack_app.command("import")
def pack_import(pack_directory: Path) -> None:
    service, engine = _pack_service()
    try:
        _emit(service.release_dict(service.import_source(pack_directory)))
    finally:
        engine.dispose()


@pack_app.command("release")
def pack_release(release_id: str, actor_id: Annotated[str, typer.Option("--actor-id")]) -> None:
    service, engine = _pack_service()
    try:
        _emit(service.release_dict(service.release(release_id, actor_id=actor_id)))
    finally:
        engine.dispose()


@pack_app.command("activate")
def pack_activate(
    release_id: str,
    environment: Annotated[str, typer.Option("--environment")],
    actor_id: Annotated[str, typer.Option("--actor-id")],
) -> None:
    service, engine = _pack_service()
    try:
        record = service.activate(release_id, environment=environment, actor_id=actor_id)
        _emit(
            {
                "activation_id": record.activation_id,
                "environment": record.environment,
                "pack_key": record.pack_key,
                "content_pack_release_id": record.content_pack_release_id,
                "active": record.active,
            }
        )
    finally:
        engine.dispose()


@pack_app.command("resolve")
def pack_resolve(
    pack_key: Annotated[str, typer.Option("--pack-key")],
    environment: Annotated[str, typer.Option("--environment")],
) -> None:
    service, engine = _pack_service()
    try:
        _emit(service.resolve(pack_key=pack_key, environment=environment))
    finally:
        engine.dispose()


@pack_app.command("list")
def pack_list() -> None:
    service, engine = _pack_service()
    try:
        _emit(service.list_releases())
    finally:
        engine.dispose()


@pack_app.command("inspect")
def pack_inspect(value: str) -> None:
    path = Path(value)
    if path.is_file():
        _emit(inspect_bundle(path))
        return
    if path.is_dir():
        compiled = compile_pack(path)
        _emit(compiled.canonical_manifest)
        return
    service, engine = _pack_service()
    try:
        _emit(service.inspect(value))
    finally:
        engine.dispose()


@pack_app.command("diff")
def pack_diff(left: Path, right: Path) -> None:
    left_pack = compile_pack(left)
    right_pack = compile_pack(right)
    left_files = {item.relative_path: item.sha256 for item in left_pack.files}
    right_files = {item.relative_path: item.sha256 for item in right_pack.files}
    _emit(
        {
            "added": sorted(right_files.keys() - left_files.keys()),
            "removed": sorted(left_files.keys() - right_files.keys()),
            "changed": sorted(
                path
                for path in left_files.keys() & right_files.keys()
                if left_files[path] != right_files[path]
            ),
        }
    )


@pack_app.command("doctor")
def pack_doctor() -> None:
    settings = CatalogSettings.from_environment()
    try:
        compiled = compile_pack(settings.placeholder_pack_source)
        built = build_pack(
            settings.placeholder_pack_source,
            settings.staging_root / "doctor-content-pack",
        )
        inspect_bundle(built.bundle_path)
        checks = {
            "schema": "PASS",
            "placeholder_pack": "PASS",
            "compiler": "PASS",
            "bundle_round_trip": "PASS",
            "profile_resolution": "PASS" if len(compiled.profiles) == 4 else "FAIL",
            "real_domain_content": "PENDING_MANUAL_ACTION",
        }
    except Exception:
        checks = {"compiler": "FAIL"}
    _emit({"passed": "FAIL" not in checks.values(), "checks": checks})
    if "FAIL" in checks.values():
        raise typer.Exit(1)
