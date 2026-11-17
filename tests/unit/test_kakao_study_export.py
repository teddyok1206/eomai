"""New source-link transport preserves both released export response families."""

from pathlib import Path

import pytest
from eom_catalog_contracts.kakao_study_export import (
    KakaoStudyExport,
    KakaoStudyExportCreate,
    KakaoStudyExportMutation,
    KakaoStudyExportPin,
)
from eom_catalog_contracts.validation import CATALOG_SCHEMA_RESOURCES, validate_contract
from eom_identifiers import canonical_json_bytes, sha256_bytes

from tests.unit.test_kakao_export_store_contracts import pending_export
from tests.unit.test_kakao_study_export_contracts import study_export
from tests.unit.test_kakao_study_store import identity

ROOT = Path(__file__).resolve().parents[2]


def pin():
    return KakaoStudyExportPin(
        study_id=identity("kakaostudy"),
        study_revision_id=identity("kakaostudyrev"),
        manifest_sha256="sha256:" + "a" * 64,
    )


def command():
    return KakaoStudyExportCreate(source_binding_id=identity("kakaobinding"), study=pin())


def test_new_schema_hash_and_existing_export_family_roundtrip():
    raw = (ROOT / "schemas/kakao-archive/study-export-v1.schema.json").read_bytes()
    mirror = (
        ROOT
        / "packages/catalog_contracts/eom_catalog_contracts/resources/kakao-archive"
        / "study-export-v1.schema.json"
    )
    assert raw == mirror.read_bytes()
    assert sha256_bytes(raw) == CATALOG_SCHEMA_RESOURCES["kakao-study-export-v1"].sha256
    view = KakaoStudyExport(study=pin(), export=study_export())
    for value in (pin(), command(), view, KakaoStudyExportMutation(result=view, replayed=True)):
        validate_contract("kakao-study-export-v1", value.model_dump(mode="json"))
        assert type(value).model_validate_json(canonical_json_bytes(value)) == value


@pytest.mark.parametrize(
    "field,value",
    [
        ("packet_id", identity("kakaopacket")),
        ("student_id", identity("kakaostudent")),
        ("slot", "05"),
        ("path", "/mnt/nas/file.pdf"),
        ("latest", True),
    ],
)
def test_no_caller_scope_runtime_or_latest_override(field, value):
    with pytest.raises(ValueError):
        KakaoStudyExportCreate.model_validate(command().model_dump(mode="json") | {field: value})


def test_plain_layout_cannot_claim_saved_study_export():
    with pytest.raises(ValueError, match="STUDY_EXPORT_INVALID"):
        KakaoStudyExport(study=pin(), export=pending_export())
