from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from eom_hwpx_builder.curated_package_merge import write_native_package
from eom_hwpx_builder.errors import HwpxError
from eom_hwpx_builder.native_hwp_preservation import verify_native_hwp_candidate
from eom_hwpx_builder.util import canonical_json_bytes, sha256_bytes, sha256_file
from eom_hwpx_contracts.native_conversion import NativeHwpShapeCounts
from eom_hwpx_contracts.validation import validate_contract
from jsonschema import ValidationError


def candidate(tmp_path: Path):
    hp = "http://www.hancom.co.kr/hwpml/2011/paragraph"
    section = f'''<hs:sec xmlns:hs="urn:section" xmlns:hp="{hp}">
      <hp:p><hp:run><hp:t>out er\u00a0</hp:t><hp:tbl rowCnt="1" colCnt="1">
        <hp:tr><hp:tc><hp:subList><hp:p><hp:run><hp:t>in ner</hp:t></hp:run></hp:p>
        </hp:subList><hp:cellAddr colAddr="0" rowAddr="0"/>
        <hp:cellSpan colSpan="1" rowSpan="1"/><hp:cellSz width="100" height="50"/>
        </hp:tc></hp:tr></hp:tbl><hp:equation><hp:script>x^2</hp:script></hp:equation>
        <hp:container><hp:pic/></hp:container></hp:run></hp:p></hs:sec>'''.encode()
    parts = {
        "mimetype": b"application/hwp+zip",
        "Contents/section0.xml": section,
        "BinData/picture.png": b"native picture bytes",
    }
    path = tmp_path / "candidate.hwpx"
    write_native_package(parts, path)
    value = {
        "schema_version": "native-hwp-conversion-evidence/1.0",
        "source_sha256": "sha256:" + "a" * 64,
        "candidate_sha256": sha256_file(path),
        "section_count": 1,
        "paragraph_sha256": sorted([sha256_bytes(b"outer"), sha256_bytes(b"inner")]),
        "table_sha256": [sha256_bytes(b"1,1;0,0,1,1,100,50;")],
        "equation_sha256": [sha256_bytes(b"x^2")],
        "binary_sha256": [sha256_bytes(parts["BinData/picture.png"])],
        "shape_counts": {
            name: int(name in {"pic", "container"}) for name in NativeHwpShapeCounts.model_fields
        },
    }
    return path, value


def test_source_evidence_matches_native_text_tables_equations_binaries_and_groups(tmp_path):
    path, value = candidate(tmp_path)
    before = path.read_bytes()
    result = verify_native_hwp_candidate(
        path, canonical_json_bytes(value), source_sha256=value["source_sha256"]
    )
    assert result.section_count == 1 and len(result.paragraph_sha256) == 2
    assert path.read_bytes() == before
    validate_contract("native-hwp-evidence", result.model_dump(mode="json"))


@pytest.mark.parametrize(
    "field",
    [
        "source_sha256",
        "candidate_sha256",
        "section_count",
        "paragraph_sha256",
        "table_sha256",
        "equation_sha256",
        "binary_sha256",
        "shape_counts",
    ],
)
def test_any_missing_or_changed_native_content_fails_before_publication(tmp_path, field):
    path, original = candidate(tmp_path)
    value = copy.deepcopy(original)
    if field.endswith("_sha256") and isinstance(value[field], list):
        value[field] = ["sha256:" + "0" * 64]
    elif field == "shape_counts":
        value[field]["container"] = 0
    elif field == "section_count":
        value[field] += 1
    else:
        value[field] = "sha256:" + "0" * 64
    with pytest.raises(HwpxError):
        verify_native_hwp_candidate(
            path, canonical_json_bytes(value), source_sha256=original["source_sha256"]
        )


def test_duplicate_evidence_keys_and_unknown_fields_are_not_trusted(tmp_path):
    path, value = candidate(tmp_path)
    duplicate = canonical_json_bytes(value).replace(
        b'"section_count":1', b'"section_count":1,"section_count":2'
    )
    with pytest.raises(ValueError):
        verify_native_hwp_candidate(path, duplicate, source_sha256=value["source_sha256"])
    value["ignore_loss"] = True
    with pytest.raises(ValidationError):
        verify_native_hwp_candidate(
            path, json.dumps(value).encode(), source_sha256=value["source_sha256"]
        )


@pytest.mark.parametrize(
    "name", ["hwpx-native-hwp-evidence-v1.schema.json", "hwpx-native-hwp-bundle-v1.schema.json"]
)
def test_native_converter_schema_mirrors(name):
    root = Path(__file__).resolve().parents[2]
    assert (root / "schemas/hwpx" / name).read_bytes() == (
        root / "packages/hwpx_contracts/eom_hwpx_contracts/schemas" / name
    ).read_bytes()
