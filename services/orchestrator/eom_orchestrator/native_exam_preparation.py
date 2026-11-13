"""Existing isolated CPU runner transport; Catalog remains the canonical commit owner."""

from __future__ import annotations

import io
import os
import stat
import zipfile
from dataclasses import dataclass
from pathlib import Path

from eom_hwpx_contracts.native_conversion_v2 import NativeHwpQualifiedConversionReceiptV2
from eom_hwpx_contracts.native_exam_preparation import (
    NATIVE_EXAM_MATERIAL_LIMIT,
    NATIVE_EXAM_REQUEST_LIMIT,
    NATIVE_EXAM_RESULT_LIMIT,
    NATIVE_EXAM_SOURCE_LIMIT,
    NATIVE_EXAM_ZIP_LIMIT,
    NativeExamFilePreparationRequest,
    NativeExamFilePreparationResult,
    native_exam_preparation_sha256,
)
from eom_hwpx_contracts.native_item_split import (
    NativeItemSelection,
    NativeItemSplitPlan,
    NativeItemSplitResult,
)
from eom_hwpx_contracts.validation import parse_json_object
from eom_identifiers import canonical_json_bytes, sha256_bytes

from eom_orchestrator.external_item_learning_page_render import (
    PdfToolRunner,
    _run_isolated,
    _trusted_executable,
)


@dataclass(frozen=True, slots=True)
class PreparedNativeExamFiles:
    result: NativeExamFilePreparationResult
    workspace: Path
    members: tuple[str, ...]
    split_results: tuple[NativeItemSplitResult, ...]
    conversion_receipt: NativeHwpQualifiedConversionReceiptV2 | None


def _installed_python(path: Path) -> Path:
    if not path.is_absolute():
        raise ValueError("NATIVE_EXAM_PREPARATION_RUNTIME_UNTRUSTED")
    executable = _trusted_executable(path)
    lexical = path.lstat()
    if (
        not (stat.S_ISREG(lexical.st_mode) or stat.S_ISLNK(lexical.st_mode))
        or lexical.st_uid != 0
        or lexical.st_gid != 0
        or (stat.S_ISREG(lexical.st_mode) and lexical.st_mode & 0o022)
    ):
        raise ValueError("NATIVE_EXAM_PREPARATION_RUNTIME_UNTRUSTED")
    # Validate the symlink target as executable, but keep the configured venv path:
    # invoking the resolved base binary would discard pyvenv.cfg and installed wheels.
    for directory in {*path.parents, *executable.parents}:
        metadata = directory.lstat()
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or metadata.st_uid != 0
            or metadata.st_gid != 0
            or metadata.st_mode & 0o022
        ):
            raise ValueError("NATIVE_EXAM_PREPARATION_RUNTIME_UNTRUSTED")
    return path


def prepare_native_exam_file(
    source_bytes: bytes,
    *,
    request: NativeExamFilePreparationRequest,
    workspace: Path,
    python: Path,
    run: PdfToolRunner = _run_isolated,
) -> PreparedNativeExamFiles:
    """Source authorization belongs to the caller, not fields inside a model request."""
    request = NativeExamFilePreparationRequest.model_validate(request.model_dump(mode="json"))
    if (
        not 0 < len(source_bytes) <= NATIVE_EXAM_SOURCE_LIMIT
        or sha256_bytes(source_bytes) != request.expected_source_sha256
        or not workspace.is_absolute()
        or os.path.lexists(workspace)
    ):
        raise ValueError("NATIVE_EXAM_PREPARATION_INPUT_INVALID")
    signature = (
        b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" if request.source_format == "HWP" else b"PK\x03\x04"
    )
    if not source_bytes.startswith(signature):
        raise ValueError("NATIVE_EXAM_PREPARATION_SOURCE_FORMAT_INVALID")
    encoded = canonical_json_bytes(request.model_dump(mode="json"))
    if len(encoded) > NATIVE_EXAM_REQUEST_LIMIT:
        raise ValueError("NATIVE_EXAM_PREPARATION_REQUEST_TOO_LARGE")
    # This is operator-installed configuration, never an executable path from the request.
    executable = _installed_python(python)
    payload = run(
        executable,
        (
            "-I",
            "-B",
            "-m",
            "eom_hwpx_builder.native_exam_tool",
            "--request-json",
            encoded.decode("utf-8"),
        ),
        source_bytes,
        timeout_seconds=115.0,
        maximum_stdout=NATIVE_EXAM_ZIP_LIMIT,
    )
    return unpack_native_exam_file_preparation(payload, request=request, workspace=workspace)


def _unpack_native_exam_file_preparation(
    payload: bytes,
    *,
    request: NativeExamFilePreparationRequest,
    workspace: Path,
) -> PreparedNativeExamFiles:
    """Validate ZIP/JSON/hash/role/number closure before creating any local candidate."""
    request = NativeExamFilePreparationRequest.model_validate(request.model_dump(mode="json"))
    if (
        not 0 < len(payload) <= NATIVE_EXAM_ZIP_LIMIT
        or not workspace.is_absolute()
        or os.path.lexists(workspace)
    ):
        raise ValueError("NATIVE_EXAM_PREPARATION_OUTPUT_INVALID")
    try:
        archive = zipfile.ZipFile(io.BytesIO(payload))
    except (zipfile.BadZipFile, OSError) as exc:
        raise ValueError("NATIVE_EXAM_PREPARATION_ZIP_INVALID") from exc
    with archive:
        infos = archive.infolist()
        names = [entry.filename for entry in infos]
        if (
            names != sorted(set(names))
            or len({name.casefold() for name in names}) != len(names)
            or len(names) > 2 * len(request.expected_numbers) + 2
            or "result.json" not in names
            or any(
                entry.is_dir()
                or entry.flag_bits & 1
                or entry.compress_type != zipfile.ZIP_STORED
                or stat.S_IFMT(entry.external_attr >> 16) not in {0, stat.S_IFREG}
                or not 0 < entry.file_size <= 64 * 1024 * 1024
                for entry in infos
            )
            or sum(entry.file_size for entry in infos)
            > NATIVE_EXAM_MATERIAL_LIMIT + NATIVE_EXAM_RESULT_LIMIT
            or archive.getinfo("result.json").file_size > NATIVE_EXAM_RESULT_LIMIT
        ):
            raise ValueError("NATIVE_EXAM_PREPARATION_ZIP_INVALID")
        result = NativeExamFilePreparationResult.model_validate(
            parse_json_object(archive.read("result.json"))
        )
        if (
            result.request_sha256 != native_exam_preparation_sha256(request.model_dump(mode="json"))
            or result.original_source_sha256 != request.expected_source_sha256
            or result.source_format != request.source_format
            or result.source_role != request.source_role
            or result.expected_numbers != request.expected_numbers
        ):
            raise ValueError("NATIVE_EXAM_PREPARATION_RESULT_IDENTITY_MISMATCH")
        expected = {
            member.member_path: member
            for item in result.items
            for member in (item.document, item.split_evidence)
        }
        if result.conversion is not None:
            expected[result.conversion.member_path] = result.conversion
        if set(names) != {"result.json", *expected}:
            raise ValueError("NATIVE_EXAM_PREPARATION_MEMBER_CLOSURE_INVALID")
        # Metadata only stays in memory. Large HWPX bytes are read for this explicit
        # validation boundary and then materialized once in the exclusive workspace.
        for member in expected.values():
            if archive.getinfo(member.member_path).file_size != member.bytes:
                raise ValueError("NATIVE_EXAM_PREPARATION_MEMBER_SIZE_MISMATCH")
            raw = archive.read(member.member_path)
            if sha256_bytes(raw) != member.sha256:
                raise ValueError("NATIVE_EXAM_PREPARATION_MEMBER_HASH_MISMATCH")
            if member.media_type == "application/vnd.hancom.hwpx" and not raw.startswith(
                b"PK\x03\x04"
            ):
                raise ValueError("NATIVE_EXAM_PREPARATION_HWPX_INVALID")
        splits = tuple(
            NativeItemSplitResult.model_validate(
                parse_json_object(archive.read(item.split_evidence.member_path))
            )
            for item in result.items
        )
        for item, split in zip(result.items, splits, strict=True):
            if (
                split.source_sha256 != result.native_source_sha256
                or split.plan_sha256 != result.plan_sha256
                or split.source_role != result.source_role
                or split.item_number != item.item_number
                or split.output_sha256 != item.document.sha256
                or split.output_size_bytes != item.document.bytes
            ):
                raise ValueError("NATIVE_EXAM_PREPARATION_SPLIT_CLOSURE_INVALID")
        NativeItemSplitPlan(
            source_sha256=result.native_source_sha256,
            source_role=result.source_role,
            items=tuple(
                NativeItemSelection(item_number=split.item_number, ranges=split.ranges)
                for split in splits
            ),
            plan_sha256=result.plan_sha256,
        )
        conversion = None
        if result.conversion is not None:
            conversion = NativeHwpQualifiedConversionReceiptV2.model_validate(
                parse_json_object(archive.read(result.conversion.member_path))
            )
            if (
                conversion.snapshot != request.converter
                or conversion.evidence.source_sha256 != result.original_source_sha256
                or conversion.normalization.output_sha256 != result.native_source_sha256
            ):
                raise ValueError("NATIVE_EXAM_PREPARATION_CONVERSION_CLOSURE_INVALID")
        workspace.mkdir(mode=0o700)
        for name in names:
            # All names have already been proven equal to the fixed typed manifest.
            path = workspace / name
            path.parent.mkdir(mode=0o700, exist_ok=True)
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(archive.read(name))
    return PreparedNativeExamFiles(result, workspace, tuple(names), splits, conversion)


def unpack_native_exam_file_preparation(
    payload: bytes,
    *,
    request: NativeExamFilePreparationRequest,
    workspace: Path,
) -> PreparedNativeExamFiles:
    """Translate malformed ZIP/CRC and failed exclusive writes to one stable adapter error."""
    try:
        return _unpack_native_exam_file_preparation(payload, request=request, workspace=workspace)
    except (zipfile.BadZipFile, zipfile.LargeZipFile, RuntimeError, OSError) as exc:
        raise ValueError("NATIVE_EXAM_PREPARATION_OUTPUT_INVALID") from exc
