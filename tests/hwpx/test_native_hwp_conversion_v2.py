from __future__ import annotations

import copy
import os
import subprocess
from pathlib import Path

import pytest
from eom_hwpx_builder import native_hwp_converter as converter_adapter
from eom_hwpx_builder.curated_package_merge import write_native_package
from eom_hwpx_builder.errors import HwpxError
from eom_hwpx_builder.native_hwp_preservation_v2 import verify_native_hwp_candidate_v2
from eom_hwpx_builder.util import canonical_json_bytes, sha256_bytes, sha256_file
from eom_hwpx_contracts.native_conversion_v2 import (
    NATIVE_HWP_QUALIFIED_CONVERSION_REF,
    NativeHwpConversionEvidenceV2,
    NativeHwpConverterBundleV2,
    NativeHwpConverterSnapshotV2,
    NativeHwpNormalizationReceiptV2,
    NativeHwpQualifiedConversionReceiptV2,
)
from eom_hwpx_contracts.validation import validate_contract
from pydantic import ValidationError

from tests.hwpx.test_native_hwp_converter import bundle as v1_bundle
from tests.hwpx.test_native_hwp_preservation import candidate


def v2_candidate(tmp_path: Path):
    path, original = candidate(tmp_path)
    value = {
        **original,
        "schema_version": "native-hwp-conversion-evidence/2.0",
        "masterpage_count": 0,
        "memo_count": 0,
        "auxiliary_master_pages": [],
        "auxiliary_exceptions": [],
        "whole_paper_layout": "NOT_VERIFIED",
        "warnings": [],
    }
    return path, value


def test_v2_preserves_old_native_counts_without_claiming_layout(tmp_path: Path) -> None:
    path, value = v2_candidate(tmp_path)
    result = verify_native_hwp_candidate_v2(
        path, canonical_json_bytes(value), source_sha256=value["source_sha256"]
    )
    assert result.whole_paper_layout == "NOT_VERIFIED" and result.memo_count == 0
    validate_contract("native-hwp-evidence-v2", result.model_dump(mode="json"))


def test_v2_requires_native_master_and_memo_body_in_independent_proof(tmp_path: Path) -> None:
    import zipfile

    path, value = v2_candidate(tmp_path)
    with zipfile.ZipFile(path) as archive:
        parts = {name: archive.read(name) for name in archive.namelist()}
    hp = "http://www.hancom.co.kr/hwpml/2011/paragraph"
    parts["Contents/masterpage0.xml"] = (
        f'<hp:master xmlns:hp="{hp}"><hp:p><hp:run><hp:t>header</hp:t>'
        '<hp:ctrl><hp:fieldBegin id="memo1" type="MEMO"><hp:subList>'
        "<hp:p><hp:run><hp:t>memo body</hp:t></hp:run></hp:p>"
        "</hp:subList></hp:fieldBegin></hp:ctrl></hp:run></hp:p></hp:master>"
    ).encode()
    output = tmp_path / "with-master.hwpx"
    write_native_package(parts, output)
    value.update(
        {
            "candidate_sha256": sha256_file(output),
            "masterpage_count": 1,
            "memo_count": 1,
            "paragraph_sha256": [
                *value["paragraph_sha256"],
                sha256_bytes(b"header"),
                sha256_bytes(b"memobody"),
            ],
        }
    )
    verify_native_hwp_candidate_v2(
        output, canonical_json_bytes(value), source_sha256=value["source_sha256"]
    )
    changed = copy.deepcopy(value)
    changed["paragraph_sha256"].remove(sha256_bytes(b"memobody"))
    with pytest.raises(HwpxError, match="changed editable"):
        verify_native_hwp_candidate_v2(
            output, canonical_json_bytes(changed), source_sha256=value["source_sha256"]
        )


def exception_for(value: dict) -> dict:
    return {
        "source_section": 0,
        "kind": "TRAILING",
        "ordinal": 2,
        "flags": 0,
        "width": 100,
        "height": 100,
        "raw_record_sha256": "sha256:" + "b" * 64,
        "source_start": 10,
        "source_end": 30,
        "code": "AUXILIARY_MASTERPAGE_FIELD_INVALID",
        "paragraph_sha256": [sha256_bytes(b"old filename decoration")],
        "table_sha256": [],
        "equation_sha256": [],
        "shape_counts": {name: 0 for name in value["shape_counts"]},
    }


def test_auxiliary_exception_is_explicit_and_never_exempts_missing_core_content(
    tmp_path: Path,
) -> None:
    path, value = v2_candidate(tmp_path)
    value["auxiliary_exceptions"] = [exception_for(value)]
    value["warnings"] = ["AUXILIARY_MASTERPAGE_FIELD_INVALID"]
    result = verify_native_hwp_candidate_v2(
        path, canonical_json_bytes(value), source_sha256=value["source_sha256"]
    )
    assert result.auxiliary_exceptions[0].source_start == 10
    changed = copy.deepcopy(value)
    changed["paragraph_sha256"] = changed["paragraph_sha256"][:1]
    with pytest.raises(HwpxError, match="changed editable"):
        verify_native_hwp_candidate_v2(
            path, canonical_json_bytes(changed), source_sha256=value["source_sha256"]
        )
    value["warnings"] = []
    with pytest.raises(ValidationError, match="warning differs"):
        NativeHwpConversionEvidenceV2.model_validate(value)


def test_unbound_binary_is_explicit_original_only_and_never_exempts_a_bound_image(
    tmp_path: Path,
) -> None:
    path, value = v2_candidate(tmp_path)
    member = {
        "member_path": "BinData/BIN001A.png",
        "raw_sha256": sha256_bytes(b"opaque unused storage"),
        "size_bytes": 21,
    }
    value["unbound_binary_members"] = [member]
    value["warnings"] = ["UNBOUND_BINARY_MEMBERS_RETAINED_IN_SOURCE"]
    result = verify_native_hwp_candidate_v2(
        path, canonical_json_bytes(value), source_sha256=value["source_sha256"]
    )
    assert result.unbound_binary_members[0].member_path == member["member_path"]
    changed = copy.deepcopy(value)
    changed["binary_sha256"] = [sha256_bytes(b"missing bound image")]
    with pytest.raises(HwpxError, match="changed editable"):
        verify_native_hwp_candidate_v2(
            path, canonical_json_bytes(changed), source_sha256=value["source_sha256"]
        )
    duplicate = copy.deepcopy(value)
    duplicate["unbound_binary_members"].append({**member, "member_path": "BinData/BIN001a.PNG"})
    with pytest.raises(ValidationError, match="unbound member identity"):
        NativeHwpConversionEvidenceV2.model_validate(duplicate)
    value["warnings"] = []
    with pytest.raises(ValidationError, match="warning differs"):
        NativeHwpConversionEvidenceV2.model_validate(value)


@pytest.mark.parametrize(
    "field",
    [
        "source_sha256",
        "candidate_sha256",
        "section_count",
        "masterpage_count",
        "memo_count",
        "shape_counts",
    ],
)
def test_v2_rejects_mismatched_source_or_structure(tmp_path: Path, field: str) -> None:
    path, value = v2_candidate(tmp_path)
    expected = value["source_sha256"]
    if field.endswith("sha256"):
        value[field] = "sha256:" + "0" * 64
    elif field == "shape_counts":
        value[field]["pic"] = 0
    else:
        value[field] += 1
    with pytest.raises(HwpxError):
        verify_native_hwp_candidate_v2(path, canonical_json_bytes(value), source_sha256=expected)


@pytest.mark.parametrize("kind", ["bundle", "evidence"])
def test_v2_schema_mirror(kind: str) -> None:
    root = Path(__file__).resolve().parents[2]
    name = f"hwpx-native-hwp-{kind}-v2.schema.json"
    assert (root / "schemas/hwpx" / name).read_bytes() == (
        root / "packages/hwpx_contracts/eom_hwpx_contracts/schemas" / name
    ).read_bytes()


def test_java_reader_synthetic_records_and_precise_memo_allowlist(tmp_path: Path) -> None:
    bundle_value = os.environ.get("EOM_NATIVE_CONVERTER_TEST_BUNDLE")
    if not bundle_value:
        pytest.skip("opt-in fixed native converter dependency bundle required; no download")
    bundle = Path(bundle_value)
    from scripts.hwpx.build_native_hwp_converter import DEPENDENCIES

    for name, (_, expected) in DEPENDENCIES.items():
        assert sha256_file(bundle / name) == "sha256:" + expected
    root = Path(__file__).resolve().parents[2]
    java = Path("/usr/lib/jvm/java-21-openjdk-amd64/bin/java")
    classpath = os.pathsep.join(
        str(bundle / name) for name in ("converter.jar", "hwplib-1.1.10.jar", "hwpxlib-1.0.9.jar")
    )
    sources = [
        root / "services/hwpx_builder/native_hwp" / name
        for name in (
            "NativeHwpConverter.java",
            "NativeHwpReaderV2.java",
            "NativeHwpConverterV2.java",
            "NativeHwpWriterV2.java",
        )
    ]
    sources.append(root / "tests/hwpx/native_hwp/NativeHwpReaderV2Checks.java")
    environment = {"LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "PATH": "/usr/bin:/bin", "TZ": "UTC"}
    compiled = subprocess.run(
        [
            str(java),
            "--add-modules",
            "jdk.compiler",
            "-m",
            "jdk.compiler/com.sun.tools.javac.Main",
            "-proc:none",
            "-cp",
            classpath,
            "-d",
            str(tmp_path),
            *map(str, sources),
        ],
        capture_output=True,
        timeout=20,
        check=False,
        env=environment,
    )
    assert compiled.returncode == 0, compiled.stderr.decode()[:1500]
    result = subprocess.run(
        [
            str(java),
            "-Xmx128m",
            "-XX:ActiveProcessorCount=2",
            "-cp",
            str(tmp_path) + os.pathsep + classpath,
            "eom.hwpx.NativeHwpReaderV2Checks",
        ],
        capture_output=True,
        timeout=10,
        check=False,
        env=environment,
    )
    assert result.returncode == 0, result.stderr.decode()[:1500]
    assert result.stdout == b"native_hwp_reader_v2_synthetic=PASS\n"


def test_v2_bundle_and_entrypoint_are_explicit_and_do_not_replace_v1(
    tmp_path: Path, monkeypatch
) -> None:
    from types import SimpleNamespace

    old_root, _, original, _ = v1_bundle(tmp_path, monkeypatch)
    old_bytes = (old_root / "manifest.json").read_bytes()
    value = {
        **original,
        "schema_version": "native-hwp-converter-bundle/2.0",
        "profile": "HWP2HWPX_NATIVE_V2",
        "entrypoint": "eom.hwpx.NativeHwpConverterV2",
        "adapter_source_sha256": "sha256:" + "c" * 64,
    }
    value.pop("bundle_sha256")
    value["bundle_sha256"] = sha256_bytes(canonical_json_bytes(value))
    model = NativeHwpConverterBundleV2.model_validate(value)
    root = old_root.parent / model.bundle_sha256.removeprefix("sha256:")
    root.mkdir()
    for row in model.files:
        (root / row.filename).write_bytes(row.filename.encode())
    (root / "manifest.json").write_bytes(canonical_json_bytes(value))
    selected = converter_adapter.NativeHwpConverter(
        NativeHwpConverterSnapshotV2(
            source_commit=model.source_commit, bundle_sha256=model.bundle_sha256
        )
    )
    fixture = tmp_path / "candidate"
    fixture.mkdir()
    raw, evidence = v2_candidate(fixture)
    source = tmp_path / "source.hwp"
    source.write_bytes(b"immutable native source")
    evidence["source_sha256"] = sha256_file(source)
    observed = []

    def run(command, **kwargs):
        observed.append((command, kwargs))
        Path(command[-2]).write_bytes(raw.read_bytes())
        Path(command[-1]).write_bytes(canonical_json_bytes(evidence))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(converter_adapter.subprocess, "run", run)
    monkeypatch.setattr(
        converter_adapter, "normalize_hwp_conversion_package", lambda *args: "verified-v2"
    )
    assert (
        selected.convert(source, tmp_path / "output.hwpx", source_sha256=sha256_file(source))
        == "verified-v2"
    )
    assert observed[0][0][5] == "eom.hwpx.NativeHwpConverterV2"
    assert observed[0][1]["timeout"] == 90
    assert (old_root / "manifest.json").read_bytes() == old_bytes
    value["adapter_source_sha256"] = "sha256:" + "d" * 64
    with pytest.raises(ValidationError, match="bundle hash differs"):
        NativeHwpConverterBundleV2.model_validate(value)


def test_qualified_receipt_joins_original_candidate_and_normalized_output_once(
    tmp_path: Path, monkeypatch
) -> None:
    from eom_hwpx_builder.hwp_conversion_package import HwpConversionPackageReceipt

    raw, evidence = v2_candidate(tmp_path)
    source = tmp_path / "source.hwp"
    source.write_bytes(b"synthetic original HWP")
    evidence["source_sha256"] = sha256_file(source)
    selected = converter_adapter.NativeHwpConverter.__new__(converter_adapter.NativeHwpConverter)
    selected._snapshot = NativeHwpConverterSnapshotV2(
        source_commit="62d95b980a4e3a6766877dd3fb6f7f45f4afcf3d",
        bundle_sha256="sha256:" + "c" * 64,
    )
    calls = []

    def convert(source_path, output, *, source_sha256):
        calls.append((source_path, output, source_sha256))
        output.write_bytes(raw.read_bytes())
        output.with_suffix(".evidence.json").write_bytes(canonical_json_bytes(evidence))
        return HwpConversionPackageReceipt(evidence["candidate_sha256"], sha256_file(output), 1, 2)

    monkeypatch.setattr(selected, "convert", convert)
    output = tmp_path / "normalized.hwpx"
    receipt = selected.convert_qualified(source, output, source_sha256=sha256_file(source))
    assert len(calls) == 1
    assert receipt.evidence.source_sha256 == sha256_file(source)
    assert receipt.evidence.candidate_sha256 == receipt.normalization.candidate_sha256
    assert receipt.normalization.output_sha256 == sha256_file(output)
    assert receipt.core_native_preservation == "PASS"
    assert NATIVE_HWP_QUALIFIED_CONVERSION_REF.endswith("qualified-conversion/2.0")
    validate_contract("native-hwp-qualified-conversion-v2", receipt.model_dump(mode="json"))
    changed = receipt.normalization.model_dump()
    changed["candidate_sha256"] = "sha256:" + "0" * 64
    with pytest.raises(ValidationError, match="normalization candidate differs"):
        NativeHwpQualifiedConversionReceiptV2(
            snapshot=receipt.snapshot,
            evidence=receipt.evidence,
            normalization=NativeHwpNormalizationReceiptV2.model_validate(changed),
        )


def test_qualified_receipt_schema_mirror() -> None:
    root = Path(__file__).resolve().parents[2]
    name = "hwpx-native-hwp-qualified-conversion-v2.schema.json"
    assert (root / "schemas/hwpx" / name).read_bytes() == (
        root / "packages/hwpx_contracts/eom_hwpx_contracts/schemas" / name
    ).read_bytes()
