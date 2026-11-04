"""Fixed local workspace entry point for preservation-checked native document assembly."""

from __future__ import annotations

import os
import stat
from pathlib import Path

from eom_hwpx_contracts.curated_document import (
    CuratedHwpxFailure,
    CuratedHwpxRenderRequestV2,
    CuratedHwpxRenderResult,
    CuratedHwpxRenderResultV2,
    parse_curated_render_value,
)
from eom_hwpx_contracts.curated_mixed import CuratedMixedRenderRequest, CuratedMixedRenderResult
from eom_hwpx_contracts.validation import parse_json_object, validate_contract

from eom_hwpx_builder.curated_package_merge import merge_native_hwpx
from eom_hwpx_builder.curated_resources import NativeMergeProfile, fail
from eom_hwpx_builder.handoff import finalize_failure_result, finalize_success_handoff
from eom_hwpx_builder.native_hwp_converter import NativeHwpConverter
from eom_hwpx_builder.util import canonical_json_bytes, sha256_bytes, sha256_file


def _read_request(path: Path, *, maximum: int = 256 * 1024) -> bytes:
    descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or not 1 <= before.st_size <= maximum:
            fail("curated request file is invalid")
        with os.fdopen(os.dup(descriptor), "rb") as stream:
            data = stream.read(maximum + 1)
        after = os.fstat(descriptor)

        def identity(value: os.stat_result) -> tuple[int, ...]:
            return (
                value.st_dev,
                value.st_ino,
                value.st_mode,
                value.st_size,
                value.st_mtime_ns,
                value.st_ctime_ns,
            )

        if identity(before) != identity(after) or len(data) != before.st_size:
            fail("curated request changed during read")
        return data
    finally:
        os.close(descriptor)


def _result_file(
    path: Path,
    result: CuratedHwpxRenderResult | CuratedHwpxRenderResultV2 | CuratedMixedRenderResult,
) -> None:
    value = result.model_dump(mode="json")
    schema = (
        "curated-render-result-v3"
        if isinstance(result, CuratedMixedRenderResult)
        else (
            "curated-render-result-v2"
            if isinstance(result, CuratedHwpxRenderResultV2)
            else "curated-render-result"
        )
    )
    validate_contract(schema, value)
    descriptor = os.open(
        path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_NOFOLLOW, 0o600
    )
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(canonical_json_bytes(value))


def render_curated_workspace(
    request_path: Path, result_path: Path
) -> CuratedHwpxRenderResult | CuratedHwpxRenderResultV2 | CuratedMixedRenderResult:
    """No DB, network, NAS, arbitrary executable/output path or original-file write."""
    workspace = request_path.absolute().parent
    if (
        workspace.resolve(strict=True) != workspace
        or request_path.name != "request.json"
        or result_path.absolute() != workspace / "result.json"
        or result_path.exists()
        or result_path.is_symlink()
    ):
        fail("curated fixed workspace boundary is invalid")
    payload = _read_request(request_path, maximum=1024 * 1024)
    value = parse_json_object(payload)
    if value.get("schema_version") == "curated-hwpx-render-request/3.0":
        from eom_hwpx_builder.curated_mixed_renderer import render_mixed_curated_document

        validate_contract("curated-render-request-v3", value)
        mixed = CuratedMixedRenderRequest.model_validate(value)
        rendered = render_mixed_curated_document(workspace, mixed)
        _result_file(result_path, rendered.result)
        if rendered.result.status == "SUCCEEDED":
            finalize_success_handoff(
                workspace, result_path, output_file_names=rendered.handoff_files
            )
        else:
            finalize_failure_result(workspace, result_path)
        return rendered.result
    if len(payload) > 256 * 1024:
        fail("historical curated request byte budget exceeded")
    request = parse_curated_render_value(value)
    request_sha = sha256_bytes(canonical_json_bytes(request.model_dump(mode="json")))
    inputs = workspace / "inputs"
    if inputs.is_symlink() or not inputs.is_dir():
        fail("curated input directory is invalid")
    output = workspace / "output/assembled.hwpx"
    # A fresh output directory is owned by this invocation. Never reuse an earlier result.
    output.parent.mkdir(mode=0o700)
    failure: CuratedHwpxFailure = "HWPX_CURATED_INPUT_INVALID"
    produced = False
    result: CuratedHwpxRenderResult | CuratedHwpxRenderResultV2
    try:
        sources = []
        segment_hashes = []
        converter = None
        for segment in request.segments:
            source = workspace / segment.local_file
            metadata = source.lstat()
            if (
                not stat.S_ISREG(metadata.st_mode)
                or source.is_symlink()
                or metadata.st_size != segment.size_bytes
            ):
                fail("curated local source metadata differs")
            if sha256_file(source) != segment.sha256:
                failure = "HWPX_CURATED_INPUT_CHANGED"
                fail("curated source hash differs from the pinned request")
            if segment.source_format == "HWP":
                failure = "HWPX_CURATED_FORMAT_UNSUPPORTED"
                if not isinstance(request, CuratedHwpxRenderRequestV2) or request.converter is None:
                    fail("native HWP requires its qualified conversion profile")
                if converter is None:
                    converter = NativeHwpConverter(request.converter)
                    (workspace / "converted").mkdir(mode=0o700)
                failure = "HWPX_CURATED_PRESERVATION_FAILED"
                converted = workspace / f"converted/{segment.position:03d}.hwpx"
                receipt = converter.convert(source, converted, source_sha256=segment.sha256)
                segment_hashes.append(receipt.output_sha256)
                source = converted
            else:
                segment_hashes.append(segment.sha256)
            sources.append(source)
        failure = "HWPX_CURATED_PRESERVATION_FAILED"
        report = merge_native_hwpx(
            tuple(sources), output, profile=NativeMergeProfile(request.profile)
        )
        produced = True
        if report.source_sha256 != tuple(segment_hashes):
            failure = "HWPX_CURATED_INPUT_CHANGED"
            fail("curated source hash differs from the pinned request")
        common: dict[str, object] = dict(
            build_id=request.build_id,
            assembly_revision_id=request.assembly_revision_id,
            assembly_manifest_sha256=request.assembly_manifest_sha256,
            request_sha256=request_sha,
            profile=request.profile,
            status="SUCCEEDED",
            source_sha256=tuple(segment.sha256 for segment in request.segments),
            section_source_positions=report.section_source_positions,
            binary_count=report.binary_count,
            output_sha256=report.output_sha256,
            output_size_bytes=output.stat().st_size,
            failure_code=None,
        )
        if isinstance(request, CuratedHwpxRenderRequestV2):
            result = CuratedHwpxRenderResultV2.model_validate(
                {
                    "schema_version": "curated-hwpx-render-result/2.0",
                    **common,
                    "segment_sha256": report.source_sha256,
                    "warnings": report.warnings + (("HWP_CONVERTED_NATIVE",) if converter else ()),
                    "converter_bundle_sha256": (
                        request.converter.bundle_sha256 if request.converter else None
                    ),
                }
            )
        else:
            result = CuratedHwpxRenderResult.model_validate(
                {
                    "schema_version": "curated-hwpx-render-result/1.0",
                    **common,
                }
            )
    except Exception:
        if produced:
            output.unlink()
        common = dict(
            build_id=request.build_id,
            assembly_revision_id=request.assembly_revision_id,
            assembly_manifest_sha256=request.assembly_manifest_sha256,
            request_sha256=request_sha,
            profile=request.profile,
            status="FAILED",
            source_sha256=(),
            section_source_positions=(),
            binary_count=0,
            output_sha256=None,
            output_size_bytes=None,
            failure_code=failure,
        )
        if isinstance(request, CuratedHwpxRenderRequestV2):
            result = CuratedHwpxRenderResultV2.model_validate(
                {
                    "schema_version": "curated-hwpx-render-result/2.0",
                    **common,
                    "segment_sha256": (),
                    "warnings": (),
                    "converter_bundle_sha256": None,
                }
            )
        else:
            result = CuratedHwpxRenderResult.model_validate(
                {
                    "schema_version": "curated-hwpx-render-result/1.0",
                    **common,
                }
            )
    _result_file(result_path, result)
    if result.status == "SUCCEEDED":
        finalize_success_handoff(workspace, result_path, output_file_names=("assembled.hwpx",))
    else:
        finalize_failure_result(workspace, result_path)
    return result
