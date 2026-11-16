"""Closed export requests and bounded, pinned output descriptors."""

from datetime import UTC, datetime
from pathlib import Path

import pytest
from eom_catalog_contracts.kakao_export_store import (
    KakaoExport,
    KakaoExportCreate,
    KakaoExportMutation,
    KakaoExportPage,
    KakaoExportProfile,
)
from eom_catalog_contracts.validation import CATALOG_SCHEMA_RESOURCES, validate_contract

from tests.unit.test_kakao_question_editing import identity, pointer


def export_request():
    return KakaoExportCreate(
        source_binding_id=identity("kakaobinding", 1),
        packet_id=identity("kakaopacket", 1),
        packet_revision_id=identity("kakaopacketrev", 1),
        student_id=identity("kakaostudent", 1),
    )


def pending_export():
    return KakaoExport.model_validate(
        export_request().model_dump(mode="json")
        | dict(
            schema_version="kakao-export/1.0",
            export_id=identity("kakaoexport", 1),
            profile=KakaoExportProfile(
                renderer_release_sha256="sha256:" + "a" * 64,
                font_sha256="sha256:" + "b" * 64,
                font_size_bytes=100,
            ),
            subset_sha256="sha256:" + "c" * 64,
            mode="DRAFT",
            state="PENDING",
            created_at=datetime(2026, 11, 16, tzinfo=UTC),
            completed_at=None,
            export_revision_id=None,
            pdf=None,
            layout=None,
            page_count=0,
            error_code=None,
        )
    )


def test_export_messages_are_schema_mirrored_and_strict():
    entry = CATALOG_SCHEMA_RESOURCES["kakao-export-store-v1"]
    root = Path(__file__).resolve().parents[2]
    assert (root / entry.canonical_path).read_bytes() == (
        root / "packages/catalog_contracts/eom_catalog_contracts" / entry.resource_path
    ).read_bytes()
    pending = pending_export()
    for model in (
        export_request(),
        pending,
        KakaoExportMutation(export=pending, replayed=False),
        KakaoExportPage(items=(pending,), next_cursor=None),
    ):
        validate_contract("kakao-export-store-v1", model.model_dump(mode="json"))


@pytest.mark.parametrize(
    "field,value",
    [
        ("actor_id", identity("operator", 1)),
        ("profile", {}),
        ("font_path", "/private/font.otf"),
        ("worker_uid", 0),
        ("source_path", "/private/student.csv"),
        ("student_id", "latest"),
        ("packet_revision_id", "latest"),
        ("approved", True),
    ],
)
def test_request_never_accepts_runtime_or_identity_authority(field, value):
    with pytest.raises(ValueError):
        KakaoExportCreate.model_validate(export_request().model_dump(mode="json") | {field: value})


@pytest.mark.parametrize(
    "changes",
    [
        {"state": "COMPLETED"},
        {"page_count": True},
        {"page_count": 1},
        {"state": "FAILED"},
        {"error_code": "private message"},
        {"completed_at": "2026-11-17T00:00:00Z"},
        {"export_revision_id": identity("kakaoexportrev", 1)},
        {"pdf": pointer("wrong", b"pdf")},
        {"state": "latest"},
    ],
)
def test_incomplete_or_incoherent_outputs_are_not_downloadable(changes):
    with pytest.raises(ValueError):
        KakaoExport.model_validate(pending_export().model_dump(mode="json") | changes)


@pytest.mark.parametrize(
    "bad_profile",
    [
        {"font_size_bytes": True},
        {"font_size_bytes": 0},
        {"font_size_bytes": 33554433},
        {"renderer_release_sha256": "latest"},
        {"layout_policy": "guess"},
    ],
)
def test_runtime_profile_pins_are_bounded(bad_profile):
    with pytest.raises(ValueError):
        KakaoExportProfile.model_validate(
            pending_export().profile.model_dump(mode="json") | bad_profile
        )


def test_metadata_pages_do_not_allow_duplicate_export_ids_or_stale_cursors():
    item = pending_export()
    with pytest.raises(ValueError):
        KakaoExportPage(items=(item, item), next_cursor=None)
    with pytest.raises(ValueError):
        KakaoExportPage(items=(item,), next_cursor=identity("kakaoexport", 2))
