"""Read/submit CLI adapter for the isolated HWPX POC."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Annotated, Any

import typer
from eom_hwpx_manager.doctor import doctor_payload, run_hwpx_doctor
from eom_hwpx_manager.models import HwpxBuildRecord, HwpxTemplateRevisionRecord
from eom_hwpx_manager.service import HwpxService
from eom_hwpx_manager.settings import HwpxSettings
from eom_orchestrator.database import build_engine, build_session_factory
from sqlalchemy import select

hwpx_app = typer.Typer(no_args_is_help=True, pretty_exceptions_enable=False)
template_app = typer.Typer(no_args_is_help=True)
build_app = typer.Typer(no_args_is_help=True)
manual_app = typer.Typer(no_args_is_help=True)
reference_kit_app = typer.Typer(no_args_is_help=True)
hwpx_app.add_typer(template_app, name="template")
hwpx_app.add_typer(build_app, name="build")
hwpx_app.add_typer(manual_app, name="manual-validation")
hwpx_app.add_typer(reference_kit_app, name="reference-kit")


def _emit(value: object) -> None:
    typer.echo(json.dumps(value, ensure_ascii=False, indent=2, default=str))


def _service() -> HwpxService:
    return HwpxService(build_engine())


def _build(build: HwpxBuildRecord) -> dict[str, Any]:
    return {
        "build_id": build.build_id,
        "template_revision_id": build.template_revision_id,
        "platform_job_id": build.platform_job_id,
        "status": build.status,
        "input_sha256": build.input_sha256,
        "renderer_version": build.renderer_version,
        "idempotency_key": build.idempotency_key,
        "output_artifact_id": build.output_artifact_id,
        "output_artifact_revision_id": build.output_artifact_revision_id,
        "output_sha256": build.output_sha256,
        "manual_validation_status": build.manual_validation_status,
        "failure_code": build.failure_code,
        "failure_summary": build.sanitized_failure_summary,
        "started_at": build.started_at,
        "completed_at": build.completed_at,
    }


def _revision(revision: HwpxTemplateRevisionRecord) -> dict[str, Any]:
    return {
        "template_revision_id": revision.template_revision_id,
        "template_id": revision.template_id,
        "source_artifact_id": revision.source_artifact_id,
        "source_artifact_revision_id": revision.source_artifact_revision_id,
        "source_sha256": revision.source_sha256,
        "binding_manifest_sha256": revision.binding_manifest_sha256,
        "owpml_version": revision.owpml_version,
        "hancom_version_declared": revision.hancom_version_declared,
        "package_profile": revision.package_profile,
        "analysis_summary": revision.analysis_summary,
        "approved_at": revision.approved_at,
        "immutable": revision.immutable,
    }


@hwpx_app.command("doctor")
def doctor() -> None:
    engine = build_engine()
    payload = doctor_payload(run_hwpx_doctor(engine, HwpxSettings.from_environment()))
    _emit(payload)
    if not payload["passed"]:
        raise typer.Exit(1)


@reference_kit_app.command("create")
def reference_kit_create() -> None:
    settings = HwpxSettings.from_environment()
    script = Path("/home/eom/EOM/scripts/hwpx/create_reference_kit.py")
    completed = subprocess.run(
        [str(settings.builder_python), str(script)],
        capture_output=True,
        check=False,
        timeout=60,
        env={"PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"},
    )
    if completed.returncode != 0:
        raise typer.Exit(1)
    _emit({"status": "PASS", "path": "nas://hwpx/poc-v0/reference-kit/v1"})


@template_app.command("inspect")
def template_inspect(path: Annotated[Path, typer.Argument(exists=True, dir_okay=False)]) -> None:
    _emit(_service().inspect_template(path))


@template_app.command("import")
def template_import(
    path: Annotated[Path, typer.Argument(exists=True, dir_okay=False)],
    name: Annotated[str, typer.Option("--name")],
    hancom_version: Annotated[str, typer.Option("--hancom-version")],
) -> None:
    _emit(
        _revision(
            _service().import_template(path, logical_name=name, hancom_version=hancom_version)
        )
    )


@template_app.command("list")
def template_list() -> None:
    engine = build_engine()
    sessions = build_session_factory(engine)
    with sessions() as session:
        revisions = list(
            session.scalars(
                select(HwpxTemplateRevisionRecord).order_by(HwpxTemplateRevisionRecord.created_at)
            )
        )
        values = [_revision(revision) for revision in revisions]
    _emit(values)


@template_app.command("inspect-revision")
def template_inspect_revision(template_revision_id: str) -> None:
    sessions = build_session_factory(build_engine())
    with sessions() as session:
        revision = session.get(HwpxTemplateRevisionRecord, template_revision_id)
        if revision is None:
            raise typer.BadParameter("unknown template revision")
        value = _revision(revision)
    _emit(value)


@build_app.callback(invoke_without_command=True)
def build_submit(
    ctx: typer.Context,
    template_revision: Annotated[str | None, typer.Option("--template-revision")] = None,
    input_path: Annotated[Path | None, typer.Option("--input", exists=True, dir_okay=False)] = None,
    idempotency_key: Annotated[str | None, typer.Option("--idempotency-key")] = None,
) -> None:
    if ctx.invoked_subcommand is not None:
        return
    if template_revision is None or input_path is None or idempotency_key is None:
        raise typer.BadParameter("--template-revision, --input, and --idempotency-key are required")
    _emit(_build(_service().build(template_revision, input_path, idempotency_key)))


@build_app.command("list")
def build_list(limit: Annotated[int, typer.Option(min=1, max=500)] = 50) -> None:
    _emit([_build(build) for build in _service().list_builds(limit)])


@build_app.command("inspect")
def build_inspect(build_id: str) -> None:
    service = _service()
    _emit(
        {
            "build": _build(service.get_build(build_id)),
            "validations": [
                {
                    "validation_id": item.validation_id,
                    "validation_type": item.validation_type,
                    "status": item.status,
                    "validator_version": item.validator_version,
                    "artifact_id": item.report_artifact_id,
                    "revision_id": item.report_artifact_revision_id,
                    "performed_at": item.performed_at,
                }
                for item in service.build_validations(build_id)
            ],
        }
    )


@build_app.command("locate")
def build_locate(build_id: str) -> None:
    build = _service().get_build(build_id)
    logical = (
        f"nas://artifacts/{build.output_artifact_id}/{build.output_artifact_revision_id}"
        if build.output_artifact_id and build.output_artifact_revision_id
        else None
    )
    _emit({"build_id": build_id, "artifact_uri": logical})


@hwpx_app.command("validate")
def validate(path: Annotated[Path, typer.Argument(exists=True, dir_okay=False)]) -> None:
    _emit(_service().validate_file(path))


@hwpx_app.command("extract-semantic")
def extract_semantic(path: Annotated[Path, typer.Argument(exists=True, dir_okay=False)]) -> None:
    _emit(_service().extract_file(path))


@manual_app.command("start")
def manual_start(build_id: str) -> None:
    _emit(_build(_service().start_manual_validation(build_id)))


@manual_app.command("complete")
def manual_complete(
    build_id: str,
    hancom_version: Annotated[str, typer.Option("--hancom-version")],
    windows_version: Annotated[str, typer.Option("--windows-version")],
    open_result: Annotated[str, typer.Option("--open-result")],
    save_result: Annotated[str, typer.Option("--save-result")],
    resaved_file: Annotated[Path, typer.Option("--resaved-file", exists=True, dir_okay=False)],
    performed_by: Annotated[str, typer.Option("--performed-by")],
    notes: Annotated[str, typer.Option("--notes")] = "",
) -> None:
    _emit(
        _build(
            _service().complete_manual_validation(
                build_id,
                hancom_version=hancom_version,
                windows_version=windows_version,
                open_result=open_result,
                save_result=save_result,
                resaved_file=resaved_file,
                performed_by=performed_by,
                notes=notes,
            )
        )
    )
