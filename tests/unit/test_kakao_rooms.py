"""Room identity, immutable mapping and bounded metadata contracts without side effects."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from eom_catalog_contracts.kakao_rooms import (
    KakaoRoom,
    KakaoRoomMap,
    KakaoRoomMapping,
    KakaoRoomObservation,
    KakaoRoomPage,
    room_mapping_sha256,
)
from eom_catalog_contracts.kakao_students import student_display_sha256
from eom_catalog_contracts.validation import validate_contract
from eom_catalog_service.kakao_archive_authorization import KakaoArchiveError
from eom_catalog_service.kakao_room_models import (
    KakaoRoomAdmissionRecord,
    KakaoRoomMappingRevisionRecord,
    KakaoRoomRecord,
)
from eom_catalog_service.kakao_room_service import _view
from eom_catalog_service.kakao_student_models import KakaoStudentDisplayRevisionRecord
from eom_protocol.artifact_members import ArtifactMemberPointer
from sqlalchemy import ForeignKeyConstraint, UniqueConstraint


def mapping(**changes) -> KakaoRoomMapping:
    value = dict(
        mapping_revision_id="kakaomappingrev_" + uuid4().hex,
        previous_revision_id=None,
        resource_version=1,
        state="UNMAPPED",
        student_id=None,
        student_display_revision_id=None,
        student_display_name=None,
        reason="연결 전",
        sha256=room_mapping_sha256(
            student_id=None, student_display_revision_id=None, reason="연결 전"
        ),
        created_at=datetime(2026, 11, 16, tzinfo=UTC),
    )
    value.update(changes)
    return KakaoRoomMapping.model_validate(value)


def room(**changes) -> KakaoRoom:
    value = dict(
        source_binding_id="kakaobinding_" + "b" * 32,
        room_id="kakaoroom_" + uuid4().hex,
        display_name="같은 대화방 이름",
        state="ACTIVE",
        identity_level="MANUAL_CONFIRMED",
        resource_version=1,
        created_at=datetime(2026, 11, 16, tzinfo=UTC),
        last_observed_at=datetime(2026, 11, 16, tzinfo=UTC),
        mapping=mapping(),
    )
    value.update(changes)
    return KakaoRoom.model_validate(value)


def test_names_are_not_room_or_student_identity() -> None:
    first, second = room(), room()
    assert first.display_name == second.display_name
    assert first.room_id != second.room_id
    assert first.mapping.student_id is None
    validate_contract("kakao-room-directory-v1", first.model_dump(mode="json"))


@pytest.mark.parametrize("name", ["", " ", "\n", "A\x7f", "x" * 129])
def test_names_reject_empty_control_or_unbounded_values(name) -> None:
    with pytest.raises(ValueError):
        room(display_name=name)


@pytest.mark.parametrize("version", [True, "1", 1.5, 0, 2147483648])
def test_mapping_cas_version_not_coerced(version) -> None:
    with pytest.raises(ValueError):
        KakaoRoomMap.model_validate(
            dict(
                parent_revision_id="kakaomappingrev_" + "1" * 32,
                expected_resource_version=version,
                student_id="kakaostudent_" + "2" * 32,
                student_display_revision_id="kakaostudentrev_" + "3" * 32,
                reason="확인",
            )
        )


def test_mapping_student_exact_pins_hash_and_lineage() -> None:
    student, display = "kakaostudent_" + "a" * 32, "kakaostudentrev_" + "b" * 32
    digest = room_mapping_sha256(
        student_id=student, student_display_revision_id=display, reason="확인"
    )
    value = mapping(
        state="MAPPED",
        student_id=student,
        student_display_revision_id=display,
        student_display_name="학생",
        reason="확인",
        sha256=digest,
    )
    assert value.student_id == student
    for changes in (
        {"student_id": None},
        {"student_display_revision_id": None},
        {"student_display_name": None},
        {"state": "UNMAPPED"},
        {"sha256": "sha256:" + "0" * 64},
        {"resource_version": 2},
    ):
        with pytest.raises(ValueError):
            KakaoRoomMapping.model_validate(value.model_dump(mode="json") | changes)
    assert digest != room_mapping_sha256(
        student_id=student, student_display_revision_id="kakaostudentrev_" + "c" * 32, reason="확인"
    )
    with pytest.raises(ValueError, match="ROOM_REVISION"):
        room(resource_version=2)


def test_pages_are_bounded_ordered_unique_and_one_binding() -> None:
    a, b = sorted((room(), room()), key=lambda x: x.room_id)
    assert len(KakaoRoomPage(items=(a, b), next_cursor=b.room_id).items) == 2
    for items, cursor in (((b, a), None), ((a, a), None), ((a,), b.room_id)):
        with pytest.raises(ValueError, match="PAGE_INVALID"):
            KakaoRoomPage(items=items, next_cursor=cursor)
    with pytest.raises(ValueError):
        KakaoRoomPage(items=(a,) * 101, next_cursor=None)
    with pytest.raises(ValueError, match="PAGE_INVALID"):
        KakaoRoomPage(
            items=tuple(
                sorted(
                    (a, room(source_binding_id="kakaobinding_" + "c" * 32)), key=lambda x: x.room_id
                )
            ),
            next_cursor=None,
        )


def test_observation_is_not_provider_authority_and_path_is_not_identity() -> None:
    pointer = ArtifactMemberPointer(
        artifact_id="artifact_" + "1" * 32,
        artifact_revision_id="rev_" + "2" * 32,
        schema_ref="eom://schemas/kakao-archive/worker-collection-v1/1.0",
        media_type="application/json",
        member_path="result.json",
        sha256="sha256:" + "3" * 64,
    )
    observation = KakaoRoomObservation(
        source_binding_id="kakaobinding_" + "4" * 32,
        proposed_room_id=None,
        identity_level="SOURCE_VERIFIED",
        source_identity_sha256="sha256:" + "5" * 64,
        display_name="대화방",
        observed_at=datetime(2026, 11, 16, tzinfo=UTC),
        source_evidence=pointer,
    )
    for changes in (
        {"identity_level": "UNKNOWN"},
        {"operator_id": "admin"},
        {"display_name": "\x00"},
    ):
        with pytest.raises(ValueError):
            KakaoRoomObservation.model_validate(observation.model_dump(mode="json") | changes)


def test_storage_is_small_metadata_and_exact_composite_pointers() -> None:
    tables = [
        t.__table__
        for t in (KakaoRoomRecord, KakaoRoomMappingRevisionRecord, KakaoRoomAdmissionRecord)
    ]
    assert not any(
        str(c.type).startswith(("JSON", "TEXT", "BYTEA", "BLOB")) for t in tables for c in t.columns
    )
    assert not any(
        c.name in {"body", "messages", "token", "password"} for t in tables for c in t.columns
    )
    keys = {
        tuple(c.columns.keys()) for c in tables[0].constraints if isinstance(c, UniqueConstraint)
    }
    assert ("source_binding_id", "identity_level", "source_identity_sha256") in keys
    assert not any("display_name" in key for key in keys)
    current = next(
        c
        for c in tables[0].constraints
        if isinstance(c, ForeignKeyConstraint) and c.name == "fk_kakao_room_current_mapping"
    )
    assert current.deferrable and current.initially == "DEFERRED"
    assert {c.name for c in tables[1].constraints if isinstance(c, ForeignKeyConstraint)} >= {
        "fk_kakao_mapping_room_owner",
        "fk_kakao_mapping_previous",
        "fk_kakao_mapping_student_owner",
        "fk_kakao_mapping_student_display",
    }


@pytest.mark.parametrize("corruption", ["name", "hash", "state", "revision"])
def test_projection_rejects_corrupt_historical_student_pin_without_exposing_name(
    corruption,
) -> None:
    now = datetime(2026, 11, 16, tzinfo=UTC)
    owner, binding, rid = (
        "operator_" + "a" * 32,
        "kakaobinding_" + "b" * 32,
        "kakaoroom_" + "c" * 32,
    )
    mid, sid, did = (
        "kakaomappingrev_" + "d" * 32,
        "kakaostudent_" + "e" * 32,
        "kakaostudentrev_" + "f" * 32,
    )
    stored_room = KakaoRoomRecord(
        room_id=rid,
        owner_operator_id=owner,
        source_binding_id=binding,
        current_mapping_revision_id=mid,
        resource_version=1,
        display_name="대화방",
        state="ACTIVE",
        identity_level="SOURCE_VERIFIED",
        created_at=now,
        last_observed_at=now,
    )
    stored_mapping = KakaoRoomMappingRevisionRecord(
        mapping_revision_id=mid,
        room_id=rid,
        source_binding_id=binding,
        owner_operator_id=owner,
        previous_revision_id=None,
        revision_number=1,
        state="MAPPED",
        student_id=sid,
        student_display_revision_id=did,
        reason="확인",
        sha256=room_mapping_sha256(student_id=sid, student_display_revision_id=did, reason="확인"),
        created_at=now,
    )
    display = KakaoStudentDisplayRevisionRecord(
        display_revision_id=did,
        student_id=sid,
        display_name="민감한 학생 이름",
        state="ACTIVE",
        sha256=student_display_sha256("민감한 학생 이름", "ACTIVE"),
    )
    assert (
        _view(stored_room, stored_mapping, display).mapping.student_display_name
        == display.display_name
    )
    if corruption == "name":
        display.display_name = "변조한 이름"
    elif corruption == "hash":
        display.sha256 = "sha256:" + "0" * 64
    elif corruption == "state":
        display.state = "RETIRED"
    else:
        display.display_revision_id = "kakaostudentrev_" + "0" * 32
    with pytest.raises(KakaoArchiveError) as captured:
        _view(stored_room, stored_mapping, display)
    assert str(captured.value) == "KAKAO_ARCHIVE_STORED_ROOM_INVALID"
