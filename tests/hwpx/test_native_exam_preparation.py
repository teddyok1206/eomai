from __future__ import annotations

import io
import json
import os
import sys
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from eom_hwpx_builder import native_exam_tool
from eom_hwpx_builder.native_exam_tool import main, prepare_native_exam_bytes
from eom_hwpx_builder.util import canonical_json_bytes, sha256_bytes
from eom_hwpx_contracts.native_conversion_v2 import (
    NativeHwpConversionEvidenceV2,
    NativeHwpConverterSnapshotV2,
    NativeHwpNormalizationReceiptV2,
    NativeHwpQualifiedConversionReceiptV2,
)
from eom_hwpx_contracts.native_exam_preparation import NativeExamFilePreparationRequest
from eom_hwpx_contracts.validation import validate_contract
from eom_orchestrator.native_exam_preparation import unpack_native_exam_file_preparation

from tests.hwpx.test_native_hwp_conversion_v2 import v2_candidate
from tests.hwpx.test_native_item_split import source


def native_input(tmp_path: Path):
    data = source(tmp_path).read_bytes()
    request = NativeExamFilePreparationRequest(
        expected_source_sha256=sha256_bytes(data),
        source_format="HWPX",
        source_role="MAIN",
        expected_numbers=(1, 2),
        converter=None,
    )
    return data, request


def prepared_payload(tmp_path: Path):
    data, request = native_input(tmp_path)
    output = io.BytesIO()
    result = prepare_native_exam_bytes(data, request=request, output=output)
    return data, request, result, output.getvalue()


def test_tool_and_transport_preserve_native_files_and_exact_role_closure(tmp_path: Path) -> None:
    data, request, result, payload = prepared_payload(tmp_path)
    assert result.original_source_sha256 == result.native_source_sha256 == sha256_bytes(data)
    assert result.expected_numbers == (1, 2) and result.conversion is None
    validate_contract("native-exam-file-preparation", result.model_dump(mode="json"))
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        assert archive.namelist() == [
            "items/001.hwpx",
            "items/002.hwpx",
            "result.json",
            "splits/001.json",
            "splits/002.json",
        ]
        assert all(member.compress_type == zipfile.ZIP_STORED for member in archive.infolist())
        assert all(member.date_time == (1980, 1, 1, 0, 0, 0) for member in archive.infolist())
        assert not any(".pdf" in name or ".png" in name for name in archive.namelist())
    prepared = unpack_native_exam_file_preparation(
        payload, request=request, workspace=tmp_path / "received"
    )
    assert prepared.result == result
    assert prepared.conversion_receipt is None
    assert prepared.split_results[0].counts.equations == 1
    assert prepared.split_results[0].counts.tables == 1
    for item in result.items:
        assert (
            sha256_bytes((prepared.workspace / item.document.member_path).read_bytes())
            == item.document.sha256
        )


def test_preparation_transport_zip_is_deterministic(tmp_path: Path) -> None:
    data, request = native_input(tmp_path)
    first, second = io.BytesIO(), io.BytesIO()
    assert prepare_native_exam_bytes(
        data, request=request, output=first
    ) == prepare_native_exam_bytes(data, request=request, output=second)
    assert first.getvalue() == second.getvalue()


def test_source_mismatch_fails_before_any_transport_bytes(tmp_path: Path) -> None:
    data, request = native_input(tmp_path)
    output = io.BytesIO()
    with pytest.raises(ValueError, match="SOURCE_CHANGED"):
        prepare_native_exam_bytes(data + b"changed", request=request, output=output)
    assert output.getvalue() == b""


def test_cli_uses_fixed_stdin_stdout_and_does_not_print_source_errors(
    tmp_path: Path, monkeypatch
) -> None:
    data, request = native_input(tmp_path)
    output, error = io.BytesIO(), io.StringIO()
    monkeypatch.setattr(sys, "stdin", SimpleNamespace(buffer=io.BytesIO(data)))
    monkeypatch.setattr(sys, "stdout", SimpleNamespace(buffer=output))
    monkeypatch.setattr(sys, "stderr", error)
    previous = os.umask(0o077)
    try:
        assert (
            main(["--request-json", canonical_json_bytes(request.model_dump(mode="json")).decode()])
            == 0
        )
        assert zipfile.is_zipfile(io.BytesIO(output.getvalue()))
        assert error.getvalue() == ""
        invalid = json.dumps(
            {**request.model_dump(mode="json"), "executable": "SECRET-UNTRUSTED-PATH"}
        )
        output.seek(0)
        output.truncate()
        assert main(["--request-json", invalid]) == 1
        assert output.getvalue() == b"" and "SECRET" not in error.getvalue()
        assert "NATIVE_EXAM_FILE_PREPARATION_FAILED" in error.getvalue()
    finally:
        os.umask(previous)


def test_request_and_result_schema_mirror() -> None:
    root = Path(__file__).resolve().parents[2]
    name = "hwpx-native-exam-file-preparation-v1.schema.json"
    assert (root / "schemas/hwpx" / name).read_bytes() == (
        root / "packages/hwpx_contracts/eom_hwpx_contracts/schemas" / name
    ).read_bytes()


def test_hwp_preparation_uses_exact_converter_and_keeps_original_to_native_proof(
    tmp_path: Path, monkeypatch
) -> None:
    native = source(tmp_path).read_bytes()
    original = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1synthetic-HWP"
    snapshot = NativeHwpConverterSnapshotV2(
        source_commit="62d95b980a4e3a6766877dd3fb6f7f45f4afcf3d",
        bundle_sha256="sha256:" + "a" * 64,
    )
    fixture = tmp_path / "proof"
    fixture.mkdir()
    _, value = v2_candidate(fixture)
    value.update(source_sha256=sha256_bytes(original), candidate_sha256=sha256_bytes(native))
    receipt = NativeHwpQualifiedConversionReceiptV2(
        snapshot=snapshot,
        evidence=NativeHwpConversionEvidenceV2.model_validate(value),
        normalization=NativeHwpNormalizationReceiptV2(
            candidate_sha256=sha256_bytes(native),
            output_sha256=sha256_bytes(native),
            empty_style_attribute_count=0,
            expanded_size_attribute_count=0,
            rebuilt_intent_box_count=0,
        ),
    )
    calls = []

    class Converter:
        def __init__(self, selected):
            assert selected == snapshot

        def convert_qualified(self, incoming, outgoing, *, source_sha256):
            assert incoming.read_bytes() == original
            assert source_sha256 == sha256_bytes(original)
            calls.append(source_sha256)
            outgoing.write_bytes(native)
            return receipt

    monkeypatch.setattr(native_exam_tool, "NativeHwpConverter", Converter)
    request = NativeExamFilePreparationRequest(
        expected_source_sha256=sha256_bytes(original),
        source_format="HWP",
        source_role="SOLUTIONS",
        expected_numbers=(1, 2),
        converter=snapshot,
    )
    output = io.BytesIO()
    result = prepare_native_exam_bytes(original, request=request, output=output)
    assert calls == [sha256_bytes(original)]
    assert result.original_source_sha256 != result.native_source_sha256
    prepared = unpack_native_exam_file_preparation(
        output.getvalue(), request=request, workspace=tmp_path / "received"
    )
    assert prepared.conversion_receipt == receipt
    assert prepared.split_results[0].source_role == "SOLUTIONS"
    assert prepared.result.conversion.member_path == "conversion.json"


def test_cli_rejects_duplicate_json_keys_without_source_disclosure(
    tmp_path: Path, monkeypatch
) -> None:
    data, request = native_input(tmp_path)
    encoded = canonical_json_bytes(request.model_dump(mode="json")).decode()
    encoded = encoded.replace('"source_role":"MAIN"', '"source_role":"MAIN","source_role":"MAIN"')
    output, error = io.BytesIO(), io.StringIO()
    monkeypatch.setattr(sys, "stdin", SimpleNamespace(buffer=io.BytesIO(data)))
    monkeypatch.setattr(sys, "stdout", SimpleNamespace(buffer=output))
    monkeypatch.setattr(sys, "stderr", error)
    assert main(["--request-json", encoded]) == 1
    assert output.getvalue() == b""
    assert error.getvalue().strip().endswith("NATIVE_EXAM_FILE_PREPARATION_FAILED")
