"""File-only CLI for the isolated HWPX builder."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer

from eom_hwpx_builder.analyzer import analyze_package
from eom_hwpx_builder.bindings import compile_bindings
from eom_hwpx_builder.doctor import run_doctor
from eom_hwpx_builder.errors import HwpxError
from eom_hwpx_builder.kordoc_renderer import failed_kordoc_result, render_kordoc_workspace
from eom_hwpx_builder.kordoc_runtime import KordocRuntime
from eom_hwpx_builder.models import BindingManifest
from eom_hwpx_builder.reference import prepare_content_team_reference
from eom_hwpx_builder.renderer import failed_result, render_workspace
from eom_hwpx_builder.semantic import compare_semantic, extract_semantic
from eom_hwpx_builder.util import write_json
from eom_hwpx_builder.validation import validate_structure

app = typer.Typer(no_args_is_help=True, pretty_exceptions_enable=False)


def _echo(value: object) -> None:
    typer.echo(json.dumps(value, ensure_ascii=False, indent=2, default=str))


@app.command("doctor")
def doctor() -> None:
    result = run_doctor()
    _echo(result)
    if not result["passed"]:
        raise typer.Exit(1)


@app.command("inspect-package")
def inspect_package(
    input_path: Annotated[Path, typer.Option("--input", exists=True, dir_okay=False)],
    output: Annotated[Path, typer.Option("--output", dir_okay=False)],
) -> None:
    analysis = analyze_package(input_path)
    write_json(output, analysis.model_dump(mode="json"))
    _echo({"status": "PASS", "output": output.name, "entries": len(analysis.entries)})


@app.command("validate-package")
def validate_package(
    input_path: Annotated[Path, typer.Option("--input", exists=True, dir_okay=False)],
    output: Annotated[Path, typer.Option("--output", dir_okay=False)],
) -> None:
    report = validate_structure(input_path)
    write_json(output, report.model_dump(mode="json"))
    _echo({"status": report.status, "output": output.name})
    if report.status != "PASS":
        raise typer.Exit(1)


@app.command("prepare-content-team-reference")
def prepare_reference(
    input_path: Annotated[Path, typer.Option("--input", exists=True, dir_okay=False)],
    reference_image: Annotated[
        Path, typer.Option("--reference-image", exists=True, dir_okay=False)
    ],
    output: Annotated[Path, typer.Option("--output", dir_okay=False)],
) -> None:
    result = prepare_content_team_reference(input_path, reference_image, output)
    _echo(result)


@app.command("compile-bindings")
def bindings_command(
    input_path: Annotated[Path, typer.Option("--input", exists=True, dir_okay=False)],
    output: Annotated[Path, typer.Option("--output", dir_okay=False)],
    template_id: Annotated[str, typer.Option("--template-id")],
    template_revision_id: Annotated[str, typer.Option("--template-revision-id")],
    reference_image_sha256: Annotated[str, typer.Option("--reference-image-sha256")],
) -> None:
    bindings = compile_bindings(
        input_path,
        template_id=template_id,
        template_revision_id=template_revision_id,
        reference_image_sha256=reference_image_sha256,
    )
    write_json(output, bindings.model_dump(mode="json"))
    _echo({"status": "PASS", "bindings": len(bindings.bindings), "output": output.name})


@app.command("render")
def render(
    request: Annotated[Path, typer.Option("--request", exists=True, dir_okay=False)],
    result: Annotated[Path, typer.Option("--result", dir_okay=False)],
) -> None:
    started = datetime.now(UTC)
    try:
        build_result = render_workspace(request, result)
    except Exception as exc:
        failed = failed_result(request, result, started, exc)
        code = exc.code.value if isinstance(exc, HwpxError) else "HWPX_PACKAGE_BUILD_FAILED"
        _echo({"status": "FAILED", "error_code": code, "result_written": failed is not None})
        raise typer.Exit(1) from None
    _echo({"status": build_result.status.value, "result": result.name})


@app.command("kordoc-capabilities")
def kordoc_capabilities() -> None:
    try:
        capability = KordocRuntime().capabilities()
    except HwpxError as exc:
        _echo({"status": "UNAVAILABLE", "error_code": exc.code.value})
        raise typer.Exit(1) from None
    _echo(capability.model_dump(mode="json"))


@app.command("render-kordoc")
def render_kordoc(
    request: Annotated[Path, typer.Option("--request", exists=True, dir_okay=False)],
    result: Annotated[Path, typer.Option("--result", dir_okay=False)],
) -> None:
    started = datetime.now(UTC)
    try:
        build_result = render_kordoc_workspace(request, result)
    except Exception as exc:
        failed = failed_kordoc_result(request, result, started, exc)
        code = exc.code.value if isinstance(exc, HwpxError) else "HWPX_KORDOC_RENDER_FAILED"
        _echo({"status": "FAILED", "error_code": code, "result_written": failed is not None})
        raise typer.Exit(1) from None
    _echo({"status": build_result.status, "result": result.name})


def _bindings(path: Path | None, input_path: Path) -> BindingManifest:
    actual = path or input_path.parent / "template-bindings.json"
    return BindingManifest.model_validate_json(actual.read_text(encoding="utf-8"))


@app.command("extract-semantic")
def extract_semantic_command(
    input_path: Annotated[Path, typer.Option("--input", exists=True, dir_okay=False)],
    output: Annotated[Path, typer.Option("--output", dir_okay=False)],
    bindings: Annotated[Path | None, typer.Option("--bindings")] = None,
) -> None:
    view = extract_semantic(input_path, _bindings(bindings, input_path))
    write_json(output, view)
    _echo({"status": "PASS", "output": output.name})


@app.command("compare-semantic")
def compare_semantic_command(
    expected: Annotated[Path, typer.Option("--expected", exists=True, dir_okay=False)],
    actual_hwpx: Annotated[Path, typer.Option("--actual-hwpx", exists=True, dir_okay=False)],
    bindings: Annotated[Path | None, typer.Option("--bindings")] = None,
    output: Annotated[Path | None, typer.Option("--output")] = None,
) -> None:
    expected_value = json.loads(expected.read_text(encoding="utf-8"))
    report = compare_semantic(expected_value, actual_hwpx, _bindings(bindings, actual_hwpx))
    if output is not None:
        write_json(output, report.model_dump(mode="json"))
    _echo(report.model_dump(mode="json"))
    if report.status != "PASS":
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
