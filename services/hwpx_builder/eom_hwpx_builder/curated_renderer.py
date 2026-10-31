"""Fixed local workspace entry point for preservation-checked native document assembly."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

from eom_hwpx_contracts.curated_document import (
    CuratedHwpxFailure,
    CuratedHwpxRenderRequest,
    CuratedHwpxRenderResult,
)
from eom_hwpx_contracts.validation import validate_contract

from eom_hwpx_builder.curated_package_merge import merge_native_hwpx
from eom_hwpx_builder.curated_resources import fail
from eom_hwpx_builder.handoff import finalize_failure_result, finalize_success_handoff
from eom_hwpx_builder.util import canonical_json_bytes, sha256_bytes


def _read_request(path: Path) -> bytes:
    descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or not 1 <= before.st_size <= 256 * 1024:
            fail("curated request file is invalid")
        with os.fdopen(os.dup(descriptor), "rb") as stream:
            data = stream.read(256 * 1024 + 1)
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


def _result_file(path: Path, result: CuratedHwpxRenderResult) -> None:
    value = result.model_dump(mode="json")
    validate_contract("curated-render-result", value)
    descriptor = os.open(
        path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_NOFOLLOW, 0o600
    )
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(canonical_json_bytes(value))


def render_curated_workspace(request_path: Path, result_path: Path) -> CuratedHwpxRenderResult:
    """No DB, network, NAS, arbitrary output path, conversion fallback or original-file write."""
    workspace = request_path.absolute().parent
    if (
        workspace.resolve(strict=True) != workspace
        or request_path.name != "request.json"
        or result_path.absolute() != workspace / "result.json"
        or result_path.exists()
        or result_path.is_symlink()
    ):
        fail("curated fixed workspace boundary is invalid")
    value = json.loads(_read_request(request_path))
    validate_contract("curated-render-request", value)
    request = CuratedHwpxRenderRequest.model_validate(value)
    request_sha = sha256_bytes(canonical_json_bytes(request.model_dump(mode="json")))
    inputs = workspace / "inputs"
    if inputs.is_symlink() or not inputs.is_dir():
        fail("curated input directory is invalid")
    output = workspace / "output/assembled.hwpx"
    # A fresh output directory is owned by this invocation. Never reuse an earlier result.
    output.parent.mkdir(mode=0o700)
    failure: CuratedHwpxFailure = "HWPX_CURATED_INPUT_INVALID"
    produced = False
    try:
        sources = []
        for segment in request.segments:
            source = workspace / segment.local_file
            metadata = source.lstat()
            if (
                not stat.S_ISREG(metadata.st_mode)
                or source.is_symlink()
                or metadata.st_size != segment.size_bytes
            ):
                fail("curated local source metadata differs")
            if segment.source_format != "HWPX":
                failure = "HWPX_CURATED_FORMAT_UNSUPPORTED"
                fail("native HWP requires a separately qualified lossless conversion profile")
            sources.append(source)
        failure = "HWPX_CURATED_PRESERVATION_FAILED"
        report = merge_native_hwpx(tuple(sources), output)
        produced = True
        if report.source_sha256 != tuple(segment.sha256 for segment in request.segments):
            failure = "HWPX_CURATED_INPUT_CHANGED"
            fail("curated source hash differs from the pinned request")
        result = CuratedHwpxRenderResult(
            schema_version="curated-hwpx-render-result/1.0",
            build_id=request.build_id,
            assembly_revision_id=request.assembly_revision_id,
            assembly_manifest_sha256=request.assembly_manifest_sha256,
            request_sha256=request_sha,
            profile=request.profile,
            status="SUCCEEDED",
            source_sha256=report.source_sha256,
            section_source_positions=report.section_source_positions,
            binary_count=report.binary_count,
            output_sha256=report.output_sha256,
            output_size_bytes=output.stat().st_size,
            failure_code=None,
        )
    except Exception:
        if produced:
            output.unlink()
        result = CuratedHwpxRenderResult(
            schema_version="curated-hwpx-render-result/1.0",
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
    _result_file(result_path, result)
    if result.status == "SUCCEEDED":
        finalize_success_handoff(workspace, result_path, output_file_names=("assembled.hwpx",))
    else:
        finalize_failure_result(workspace, result_path)
    return result
