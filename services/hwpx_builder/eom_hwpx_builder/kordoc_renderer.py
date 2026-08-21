"""Deterministic Kordoc Markdown-to-HWPX renderer profile."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from eom_hwpx_contracts import KordocBuildResult, KordocRenderRequest, validate_contract
from pydantic import ValidationError

from eom_hwpx_builder import KORDOC_RENDERER_VERSION
from eom_hwpx_builder.archive import canonicalize_package, read_package
from eom_hwpx_builder.errors import HwpxError, HwpxErrorCode
from eom_hwpx_builder.kordoc_markdown import inspect_kordoc_markdown
from eom_hwpx_builder.kordoc_runtime import (
    KORDOC_VERSION,
    KordocRenderRuntime,
    KordocRuntime,
)
from eom_hwpx_builder.util import sha256_file, write_json
from eom_hwpx_builder.validation import (
    kordoc_native_structure_counts,
    validate_kordoc_structure,
)


def _workspace_path(workspace: Path, relative: str) -> Path:
    root = workspace.resolve(strict=True)
    target = (workspace / relative).resolve(strict=False)
    if not target.is_relative_to(root):
        raise HwpxError(HwpxErrorCode.HWPX_REFERENCE_UNSAFE, "workspace path escaped root")
    return target


def _manifest(
    output: Path, request: KordocRenderRequest, equations: int, tables: int
) -> dict[str, Any]:
    package = read_package(output)
    return {
        "manifest_version": "1.0",
        "renderer_profile": request.renderer_profile,
        "renderer_version": KORDOC_RENDERER_VERSION,
        "renderer_dependency": request.renderer_dependency.model_dump(mode="json"),
        "source": request.source.model_dump(mode="json"),
        "file_name": output.name,
        "media_type": "application/hwp+zip",
        "package_sha256": package.package_sha256,
        "native_equation_count": equations,
        "native_table_count": tables,
        "entries": [record.model_dump(mode="json") for record in package.records()],
    }


def render_kordoc_workspace(
    request_path: Path,
    result_path: Path,
    runtime: KordocRenderRuntime | None = None,
) -> KordocBuildResult:
    started = datetime.now(UTC)
    workspace = request_path.parent.resolve(strict=True)
    if result_path.resolve(strict=False).parent != workspace:
        raise HwpxError(HwpxErrorCode.HWPX_REFERENCE_UNSAFE, "result path must be in workspace")
    try:
        request_raw: dict[str, Any] = json.loads(request_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise HwpxError(HwpxErrorCode.HWPX_REFERENCE_UNSAFE, "render request is invalid") from exc
    validate_contract("kordoc-render-request", request_raw)
    request = KordocRenderRequest.model_validate(request_raw)

    source = _workspace_path(workspace, request.source.file)
    try:
        source_data = source.read_bytes()
    except OSError as exc:
        raise HwpxError(HwpxErrorCode.HWPX_REFERENCE_MISSING, "Markdown source is missing") from exc
    if source.is_symlink() or sha256_file(source) != request.source.sha256:
        raise HwpxError(HwpxErrorCode.HWPX_TEMPLATE_HASH_MISMATCH, "Markdown pointer mismatch")
    profile = inspect_kordoc_markdown(source_data)
    if (
        profile.display_equation_count != request.expected_structure.display_equation_count
        or profile.table_count != request.expected_structure.table_count
    ):
        raise HwpxError(
            HwpxErrorCode.HWPX_KORDOC_MARKDOWN_UNSAFE,
            "declared Markdown structure does not match source bytes",
        )

    output_dir = _workspace_path(workspace, request.output_directory)
    if output_dir.exists():
        raise HwpxError(HwpxErrorCode.HWPX_PACKAGE_BUILD_FAILED, "output directory must be fresh")
    raw_output = workspace / ".kordoc-generated.hwpx"
    raw_report = workspace / ".kordoc-report.json"
    if raw_output.exists() or raw_report.exists():
        raise HwpxError(HwpxErrorCode.HWPX_PACKAGE_BUILD_FAILED, "Kordoc workspace is not fresh")

    bridge = (runtime or KordocRuntime()).render(workspace, request.options.gongmun_preset)
    if (
        bridge.kordoc_version != request.renderer_dependency.version
        or bridge.source_sha256 != request.source.sha256
        or bridge.output_sha256 != sha256_file(raw_output)
        or not bridge.validation_ok
        or bridge.validation_issue_count != 0
        or not bridge.parse_success
        or bridge.parsed_table_count != profile.table_count
    ):
        raise HwpxError(
            HwpxErrorCode.HWPX_KORDOC_VALIDATION_FAILED,
            "Kordoc renderer did not satisfy the pinned result contract",
        )

    output_dir.mkdir(mode=0o700)
    output = output_dir / "kordoc_document.hwpx"
    canonicalize_package(raw_output, output)
    equations, tables = kordoc_native_structure_counts(output)
    structural = validate_kordoc_structure(
        output,
        expected_equation_count=profile.display_equation_count,
        expected_table_count=profile.table_count,
    )
    if structural.status != "PASS":
        raise HwpxError(
            HwpxErrorCode.HWPX_KORDOC_VALIDATION_FAILED,
            "Kordoc HWPX failed the generated-package profile",
        )

    warnings = (
        (f"KORDOC_PARSE_WARNINGS:{bridge.parse_warning_count}",)
        if bridge.parse_warning_count
        else ()
    )
    write_json(output_dir / "structural-validation.json", structural.model_dump(mode="json"))
    write_json(output_dir / "kordoc-validation.json", bridge.model_dump(mode="json"))
    write_json(output_dir / "package-manifest.json", _manifest(output, request, equations, tables))
    result = KordocBuildResult(
        build_id=request.build_id,
        source_artifact_id=request.source.artifact_id,
        source_artifact_revision_id=request.source.artifact_revision_id,
        source_sha256=request.source.sha256,
        renderer_version=KORDOC_RENDERER_VERSION,
        kordoc_version=KORDOC_VERSION,
        status="PENDING_MANUAL_HANCOM_VALIDATION",
        output_file="output/kordoc_document.hwpx",
        output_sha256=sha256_file(output),
        package_manifest_file="output/package-manifest.json",
        validation_report_file="output/structural-validation.json",
        renderer_report_file="output/kordoc-validation.json",
        native_equation_count=equations,
        native_table_count=tables,
        warnings=warnings,
        errors=(),
        started_at=started,
        completed_at=datetime.now(UTC),
    )
    validate_contract("kordoc-build-result", result.model_dump(mode="json"))
    write_json(result_path, result.model_dump(mode="json"))
    raw_output.unlink()
    raw_report.unlink()
    return result


def failed_kordoc_result(
    request_path: Path, result_path: Path, started: datetime, error: Exception
) -> KordocBuildResult | None:
    try:
        request = KordocRenderRequest.model_validate_json(request_path.read_text(encoding="utf-8"))
    except (OSError, ValidationError, ValueError):
        return None
    code = (
        error.code.value
        if isinstance(error, HwpxError)
        else HwpxErrorCode.HWPX_KORDOC_RENDER_FAILED.value
    )
    result = KordocBuildResult(
        build_id=request.build_id,
        source_artifact_id=request.source.artifact_id,
        source_artifact_revision_id=request.source.artifact_revision_id,
        source_sha256=request.source.sha256,
        status="FAILED",
        output_file=None,
        output_sha256=None,
        package_manifest_file=None,
        validation_report_file=None,
        renderer_report_file=None,
        native_equation_count=0,
        native_table_count=0,
        warnings=(),
        errors=(code,),
        started_at=started,
        completed_at=datetime.now(UTC),
    )
    validate_contract("kordoc-build-result", result.model_dump(mode="json"))
    write_json(result_path, result.model_dump(mode="json"))
    return result
