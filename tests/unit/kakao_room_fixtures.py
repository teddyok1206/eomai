"""Synthetic admitted-room values; fixtures are not source admission evidence."""

from eom_catalog_contracts.kakao_rooms import (
    KakaoRoom,
    KakaoRoomMap,
    KakaoRoomMapping,
    KakaoRoomUnmap,
    room_mapping_sha256,
)

from tests.unit.kakao_student_fixtures import NOW, STUDENT_ID
from tests.unit.kakao_student_fixtures import REVISION_ID as STUDENT_REVISION_ID

BINDING_ID = "kakaobinding_" + "1" * 32
ROOM_ID = "kakaoroom_" + "2" * 32
MAPPING_ID = "kakaomappingrev_" + "3" * 32
NEXT_MAPPING_ID = "kakaomappingrev_" + "4" * 32
KEY = "room-mapping-fixture-0001"


def room(*, mapped=False, changed=False):
    updated = mapped or changed
    student_id, display_id = (STUDENT_ID, STUDENT_REVISION_ID) if mapped else (None, None)
    reason = "합성 연결 변경" if updated else "합성 최초 확인"
    return KakaoRoom(
        source_binding_id=BINDING_ID,
        room_id=ROOM_ID,
        display_name="합성 대화방",
        state="ACTIVE",
        identity_level="MANUAL_CONFIRMED",
        resource_version=2 if updated else 1,
        created_at=NOW,
        last_observed_at=NOW,
        mapping=KakaoRoomMapping(
            mapping_revision_id=NEXT_MAPPING_ID if updated else MAPPING_ID,
            previous_revision_id=MAPPING_ID if updated else None,
            resource_version=2 if updated else 1,
            state="MAPPED" if mapped else "UNMAPPED",
            student_id=student_id,
            student_display_revision_id=display_id,
            student_display_name="합성 학생" if mapped else None,
            reason=reason,
            sha256=room_mapping_sha256(
                student_id=student_id, student_display_revision_id=display_id, reason=reason
            ),
            created_at=NOW,
        ),
    )


def map_command():
    return KakaoRoomMap(
        parent_revision_id=MAPPING_ID,
        expected_resource_version=1,
        student_id=STUDENT_ID,
        student_display_revision_id=STUDENT_REVISION_ID,
        reason="합성 연결 변경",
    )


def unmap_command():
    return KakaoRoomUnmap(
        parent_revision_id=MAPPING_ID, expected_resource_version=1, reason="합성 연결 변경"
    )
