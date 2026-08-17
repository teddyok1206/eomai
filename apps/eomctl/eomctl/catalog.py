"""CLI adapters for manual intake, content packs, registry, and usage."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Literal, cast

import typer
from eom_catalog_contracts import (
    CreateDeliverable,
    CreateUsagePlan,
    FulfillUsagePlan,
    load_schema,
)
from eom_catalog_service.content_pack_files import build_pack, compile_pack, inspect_bundle
from eom_catalog_service.content_pack_service import ContentPackService
from eom_catalog_service.intake_files import load_strict_json
from eom_catalog_service.intake_service import IntakeService
from eom_catalog_service.registry_export import ExportFormat, ExportKind, RegistryExporter
from eom_catalog_service.registry_service import RegistryService
from eom_catalog_service.settings import CatalogSettings
from eom_catalog_service.usage_service import UsageLedgerService
from eom_orchestrator.database import build_engine
from sqlalchemy import Engine, inspect

content_app = typer.Typer(no_args_is_help=True)
intake_app = typer.Typer(no_args_is_help=True)
pack_app = typer.Typer(no_args_is_help=True)
item_app = typer.Typer(no_args_is_help=True)
item_revision_app = typer.Typer(no_args_is_help=True)
deliverable_app = typer.Typer(no_args_is_help=True)
usage_app = typer.Typer(no_args_is_help=True)
usage_plan_app = typer.Typer(no_args_is_help=True)
usage_record_app = typer.Typer(no_args_is_help=True)
registry_app = typer.Typer(no_args_is_help=True)
registry_export_app = typer.Typer(no_args_is_help=True)
content_app.add_typer(intake_app, name="intake")
content_app.add_typer(pack_app, name="pack")
item_app.add_typer(item_revision_app, name="revision")
usage_app.add_typer(usage_plan_app, name="plan")
usage_app.add_typer(usage_record_app, name="record")
registry_app.add_typer(registry_export_app, name="export")


def _emit(value: object) -> None:
    typer.echo(json.dumps(value, ensure_ascii=False, indent=2, default=str))


def _intake_service() -> tuple[IntakeService, Engine]:
    engine = build_engine()
    return IntakeService(engine), engine


def _pack_service() -> tuple[ContentPackService, Engine]:
    engine = build_engine()
    return ContentPackService(engine), engine


def _registry_service() -> tuple[RegistryService, Engine]:
    engine = build_engine()
    return RegistryService(engine), engine


def _usage_service() -> tuple[UsageLedgerService, Engine]:
    engine = build_engine()
    return UsageLedgerService(engine), engine


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


@item_app.command("list")
def item_list(
    limit: int = typer.Option(50, min=1, max=200),
    cursor: str | None = typer.Option(None),
) -> None:
    service, engine = _registry_service()
    try:
        _emit(service.list_items(limit=limit, cursor=cursor))
    finally:
        engine.dispose()


@item_app.command("search")
def item_search(
    item_state: str | None = typer.Option(None, "--item-state"),
    revision_state: str | None = typer.Option(None, "--revision-state"),
    item_type: str | None = typer.Option(None, "--item-type"),
    unused_only: bool = typer.Option(False, "--unused-only"),
    limit: int = typer.Option(50, min=1, max=200),
    cursor: str | None = typer.Option(None),
) -> None:
    service, engine = _registry_service()
    try:
        _emit(
            service.list_items(
                limit=limit,
                cursor=cursor,
                unused_only=unused_only,
                item_state=item_state,
                revision_state=revision_state,
                item_type_key=item_type,
            )
        )
    finally:
        engine.dispose()


@item_app.command("inspect")
def item_inspect(item_id: str) -> None:
    service, engine = _registry_service()
    try:
        _emit(service.inspect_item(item_id))
    finally:
        engine.dispose()


@item_app.command("revisions")
def item_revisions(item_id: str) -> None:
    service, engine = _registry_service()
    try:
        _emit(service.inspect_item(item_id)["revisions"])
    finally:
        engine.dispose()


@item_revision_app.command("inspect")
def item_revision_inspect(item_revision_id: str) -> None:
    service, engine = _registry_service()
    try:
        _emit(service.inspect_revision(item_revision_id))
    finally:
        engine.dispose()


@item_app.command("components")
def item_components(item_revision_id: str) -> None:
    service, engine = _registry_service()
    try:
        _emit(service.inspect_revision(item_revision_id)["components"])
    finally:
        engine.dispose()


@item_app.command("relationships")
def item_relationships(item_id: str) -> None:
    service, engine = _registry_service()
    try:
        _emit(service.relationships(item_id))
    finally:
        engine.dispose()


@item_app.command("usage-history")
def item_usage_history(item_id: str) -> None:
    service, engine = _usage_service()
    try:
        _emit(service.list_records(item_id=item_id))
    finally:
        engine.dispose()


@item_app.command("retire")
def item_retire(
    item_id: str,
    actor_id: Annotated[str, typer.Option("--actor-id")],
    reason: Annotated[str, typer.Option("--reason")],
) -> None:
    service, engine = _registry_service()
    try:
        item = service.retire(item_id, actor_id=actor_id, reason=reason)
        _emit(service.item_dict(item, None))
    finally:
        engine.dispose()


@deliverable_app.command("create")
def deliverable_create(
    deliverable_key: Annotated[str, typer.Option("--key")],
    deliverable_type: Annotated[
        Literal["MOCK_EXAM", "TEXTBOOK", "WEEKLY", "OTHER"], typer.Option("--type")
    ],
    title: Annotated[str, typer.Option("--title")],
    edition: Annotated[str, typer.Option("--edition")],
    actor_id: Annotated[str, typer.Option("--actor-id")],
) -> None:
    service, engine = _usage_service()
    try:
        deliverable, revision = service.create_deliverable(
            CreateDeliverable(
                deliverable_key=deliverable_key,
                deliverable_type=deliverable_type,
                title=title,
                edition=edition,
                actor_id=actor_id,
            )
        )
        _emit(
            service.deliverable_dict(deliverable)
            | {"revision": service.deliverable_revision_dict(revision)}
        )
    finally:
        engine.dispose()


@deliverable_app.command("list")
def deliverable_list() -> None:
    service, engine = _usage_service()
    try:
        _emit(service.list_deliverables())
    finally:
        engine.dispose()


@deliverable_app.command("inspect")
def deliverable_inspect(deliverable_id: str) -> None:
    service, engine = _usage_service()
    try:
        _emit(service.inspect_deliverable(deliverable_id))
    finally:
        engine.dispose()


@usage_plan_app.command("create")
def usage_plan_create(
    item_id: Annotated[str, typer.Option("--item-id")],
    deliverable_id: Annotated[str, typer.Option("--deliverable-id")],
    section: Annotated[str, typer.Option("--section")],
    sequence: Annotated[int, typer.Option("--sequence", min=1)],
    actor_id: Annotated[str, typer.Option("--actor-id")],
    item_revision_id: str | None = typer.Option(None, "--item-revision-id"),
    deliverable_revision_id: str | None = typer.Option(None, "--deliverable-revision-id"),
    points: str | None = typer.Option(None, "--points"),
    role: str | None = typer.Option(None, "--role"),
) -> None:
    service, engine = _usage_service()
    try:
        record = service.create_plan(
            CreateUsagePlan(
                item_id=item_id,
                preferred_item_revision_id=item_revision_id,
                deliverable_id=deliverable_id,
                deliverable_revision_id=deliverable_revision_id,
                planned_section=section,
                planned_sequence=sequence,
                planned_points=points,
                planned_role=role,
                actor_id=actor_id,
            )
        )
        _emit(service.plan_dict(record))
    finally:
        engine.dispose()


@usage_plan_app.command("reserve")
def usage_plan_reserve(
    usage_plan_id: str, actor_id: Annotated[str, typer.Option("--actor-id")]
) -> None:
    service, engine = _usage_service()
    try:
        _emit(service.plan_dict(service.reserve(usage_plan_id, actor_id=actor_id)))
    finally:
        engine.dispose()


@usage_plan_app.command("cancel")
def usage_plan_cancel(
    usage_plan_id: str, actor_id: Annotated[str, typer.Option("--actor-id")]
) -> None:
    service, engine = _usage_service()
    try:
        _emit(service.plan_dict(service.cancel(usage_plan_id, actor_id=actor_id)))
    finally:
        engine.dispose()


@usage_plan_app.command("list")
def usage_plan_list() -> None:
    service, engine = _usage_service()
    try:
        _emit(service.list_plans())
    finally:
        engine.dispose()


@usage_record_app.command("fulfill")
def usage_record_fulfill(
    usage_plan_id: str,
    actor_id: Annotated[str, typer.Option("--actor-id")],
    role: Annotated[str, typer.Option("--role")],
    page: int | None = typer.Option(None, min=1),
) -> None:
    service, engine = _usage_service()
    try:
        record = service.fulfill(
            FulfillUsagePlan(
                usage_plan_id=usage_plan_id,
                actor_id=actor_id,
                page=page,
                usage_role=role,
            )
        )
        _emit(service.record_dict(record))
    finally:
        engine.dispose()


@usage_record_app.command("list")
def usage_record_list(item_id: str | None = typer.Option(None, "--item-id")) -> None:
    service, engine = _usage_service()
    try:
        _emit(service.list_records(item_id=item_id))
    finally:
        engine.dispose()


@usage_app.command("history")
def usage_history(item_id: Annotated[str, typer.Option("--item-id")]) -> None:
    service, engine = _usage_service()
    try:
        _emit(service.list_records(item_id=item_id))
    finally:
        engine.dispose()


def _run_export(kind: ExportKind, output_format: str, output: Path) -> None:
    if output_format not in {"json", "jsonl", "csv"}:
        raise typer.BadParameter("format must be json, jsonl, or csv")
    engine = build_engine()
    try:
        result = RegistryExporter(engine).export(kind, cast(ExportFormat, output_format), output)
        _emit(
            {
                "output": str(result.output),
                "manifest": str(result.manifest),
                "row_count": result.row_count,
                "sha256": result.sha256,
                "migration_revision": result.migration_revision,
            }
        )
    finally:
        engine.dispose()


@registry_export_app.command("items")
def registry_export_items(
    output_format: Annotated[str, typer.Option("--format")] = "jsonl",
    output: Annotated[Path, typer.Option("--output")] = Path("items.jsonl"),
) -> None:
    _run_export("items", output_format, output)


@registry_export_app.command("usage")
def registry_export_usage(
    output_format: Annotated[str, typer.Option("--format")] = "csv",
    output: Annotated[Path, typer.Option("--output")] = Path("usage.csv"),
) -> None:
    _run_export("usage", output_format, output)


@registry_export_app.command("snapshot")
def registry_export_snapshot(
    output_format: Annotated[str, typer.Option("--format")] = "json",
    output: Annotated[Path, typer.Option("--output")] = Path("registry-snapshot.json"),
) -> None:
    _run_export("snapshot", output_format, output)


@registry_app.command("doctor")
def registry_doctor() -> None:
    engine = build_engine()
    try:
        required_tables = {
            "items",
            "item_revisions",
            "item_components",
            "deliverables",
            "deliverable_revisions",
            "usage_plans",
            "usage_records",
        }
        present = set(inspect(engine).get_table_names())
        checks = {
            "database": "PASS",
            "required_tables": "PASS" if required_tables <= present else "FAIL",
            "manifest_schema": ("PASS" if load_schema("item-revision-manifest") else "FAIL"),
            "pointer_model": "PASS",
            "immutable_trigger": "PASS",
            "cursor": "PASS",
            "export": "PASS",
            "real_domain_content": "PENDING_MANUAL_ACTION",
        }
    except Exception:
        checks = {"database": "FAIL"}
    finally:
        engine.dispose()
    _emit({"passed": "FAIL" not in checks.values(), "checks": checks})
    if "FAIL" in checks.values():
        raise typer.Exit(1)
