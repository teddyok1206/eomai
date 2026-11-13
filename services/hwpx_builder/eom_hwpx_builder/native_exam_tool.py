"""CPU-only file preparation inside the existing untrusted-document sandbox."""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Any, BinaryIO

from eom_hwpx_contracts.native_exam_preparation import (
    NATIVE_EXAM_MATERIAL_LIMIT,
    NATIVE_EXAM_REQUEST_LIMIT,
    NATIVE_EXAM_RESULT_LIMIT,
    NATIVE_EXAM_SOURCE_LIMIT,
    NATIVE_EXAM_ZIP_LIMIT,
    NativeExamFilePreparationRequest,
    NativeExamFilePreparationResult,
    NativeExamPreparedItem,
    NativeExamPreparedMember,
    native_exam_preparation_sha256,
)
from eom_hwpx_contracts.validation import parse_json_object

from eom_hwpx_builder.archive import FIXED_ZIP_TIMESTAMP
from eom_hwpx_builder.native_hwp_converter import NativeHwpConverter
from eom_hwpx_builder.native_item_split import discover_native_item_split, split_native_exam
from eom_hwpx_builder.util import canonical_json_bytes, sha256_bytes, sha256_file


def _write_json(path: Path, value: dict[str, Any], *, maximum: int) -> NativeExamPreparedMember:
    encoded = canonical_json_bytes(value)
    if not 0 < len(encoded) <= maximum:
        raise ValueError("NATIVE_EXAM_PREPARATION_JSON_SIZE_INVALID")
    with path.open("xb") as stream:
        stream.write(encoded)
    return NativeExamPreparedMember(
        member_path=path.parent.name + "/" + path.name
        if path.parent.name == "splits"
        else path.name,
        sha256=sha256_bytes(encoded),
        bytes=len(encoded),
        media_type="application/json",
    )


def prepare_native_exam_bytes(
    source_bytes: bytes,
    *,
    request: NativeExamFilePreparationRequest,
    output: BinaryIO,
) -> NativeExamFilePreparationResult:
    """Only temporary input/output files; original Artifact ownership stays outside."""
    request = NativeExamFilePreparationRequest.model_validate(request.model_dump(mode="json"))
    if (
        not 0 < len(source_bytes) <= NATIVE_EXAM_SOURCE_LIMIT
        or sha256_bytes(source_bytes) != request.expected_source_sha256
    ):
        raise ValueError("NATIVE_EXAM_PREPARATION_SOURCE_CHANGED")
    signature = (
        b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" if request.source_format == "HWP" else b"PK\x03\x04"
    )
    if not source_bytes.startswith(signature):
        raise ValueError("NATIVE_EXAM_PREPARATION_SOURCE_FORMAT_INVALID")
    with tempfile.TemporaryDirectory(prefix="native-exam-files-") as temporary:
        root = Path(temporary)
        source = root / ("original." + request.source_format.lower())
        with source.open("xb") as stream:
            stream.write(source_bytes)
        conversion = None
        if request.source_format == "HWP":
            assert request.converter is not None
            native = root / "native.hwpx"
            qualified = NativeHwpConverter(request.converter).convert_qualified(
                source, native, source_sha256=request.expected_source_sha256
            )
            conversion = _write_json(
                root / "conversion.json",
                qualified.model_dump(mode="json"),
                maximum=16 * 1024 * 1024,
            )
            native_sha256 = qualified.normalization.output_sha256
        else:
            native, native_sha256 = source, request.expected_source_sha256
        plan = discover_native_item_split(
            native,
            expected_source_sha256=native_sha256,
            source_role=request.source_role,
            expected_numbers=request.expected_numbers,
        )
        receipts = split_native_exam(native, root / "items", plan=plan)
        (root / "splits").mkdir(mode=0o700)
        items = []
        for receipt in receipts:
            label = f"{receipt.item_number:03d}"
            evidence = _write_json(
                root / "splits" / (label + ".json"),
                receipt.model_dump(mode="json"),
                maximum=4 * 1024 * 1024,
            )
            items.append(
                NativeExamPreparedItem(
                    item_number=receipt.item_number,
                    document=NativeExamPreparedMember(
                        member_path=f"items/{label}.hwpx",
                        sha256=receipt.output_sha256,
                        bytes=receipt.output_size_bytes,
                        media_type="application/vnd.hancom.hwpx",
                    ),
                    split_evidence=evidence,
                )
            )
        total = sum(item.document.bytes + item.split_evidence.bytes for item in items)
        total += 0 if conversion is None else conversion.bytes
        if total > NATIVE_EXAM_MATERIAL_LIMIT:
            raise ValueError("NATIVE_EXAM_PREPARATION_MATERIAL_SIZE_INVALID")
        result = NativeExamFilePreparationResult(
            request_sha256=native_exam_preparation_sha256(request.model_dump(mode="json")),
            original_source_sha256=request.expected_source_sha256,
            native_source_sha256=native_sha256,
            source_format=request.source_format,
            source_role=request.source_role,
            expected_numbers=request.expected_numbers,
            plan_sha256=plan.plan_sha256,
            items=tuple(items),
            conversion=conversion,
            materialized_bytes=total,
        )
        encoded = canonical_json_bytes(result.model_dump(mode="json"))
        if (
            len(encoded) > NATIVE_EXAM_RESULT_LIMIT
            or sha256_file(source) != request.expected_source_sha256
        ):
            raise ValueError("NATIVE_EXAM_PREPARATION_RESULT_INVALID")
        with (root / "result.json").open("xb") as stream:
            stream.write(encoded)
        members = {
            "result.json",
            *(
                member.member_path
                for item in result.items
                for member in (item.document, item.split_evidence)
            ),
        }
        if conversion is not None:
            members.add(conversion.member_path)
        # A seekable private transport file fixes ZIP headers even when stdout is a pipe.
        # It is temporary materialization, never another canonical source Artifact.
        with tempfile.TemporaryFile(dir=root) as transport:
            with zipfile.ZipFile(
                transport, "w", compression=zipfile.ZIP_STORED, allowZip64=False
            ) as archive:
                for member in sorted(members):
                    info = zipfile.ZipInfo(member, FIXED_ZIP_TIMESTAMP)
                    info.compress_type = zipfile.ZIP_STORED
                    info.external_attr = 0o100600 << 16
                    info.create_system = 3
                    with (
                        (root / member).open("rb") as incoming,
                        archive.open(info, "w") as outgoing,
                    ):
                        shutil.copyfileobj(incoming, outgoing, length=1024 * 1024)
            if transport.tell() > NATIVE_EXAM_ZIP_LIMIT:
                raise ValueError("NATIVE_EXAM_PREPARATION_ZIP_SIZE_INVALID")
            transport.seek(0)
            shutil.copyfileobj(transport, output, length=1024 * 1024)
        return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request-json", required=True)
    args = parser.parse_args(argv)
    try:
        if len(args.request_json.encode("utf-8")) > NATIVE_EXAM_REQUEST_LIMIT:
            raise ValueError("NATIVE_EXAM_PREPARATION_REQUEST_TOO_LARGE")
        request = NativeExamFilePreparationRequest.model_validate(
            parse_json_object(args.request_json)
        )
        source = sys.stdin.buffer.read(NATIVE_EXAM_SOURCE_LIMIT + 1)
        os.umask(0o077)
        prepare_native_exam_bytes(source, request=request, output=sys.stdout.buffer)
        return 0
    except Exception:
        # Never include untrusted Hancom text, parser tracebacks or full inputs on stderr.
        print(
            "native_exam_preparation=FAILED code=NATIVE_EXAM_FILE_PREPARATION_FAILED",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
