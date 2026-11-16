"""Strict room RPC correlation keeps binding, mapping and display pins together."""

import json
from unittest.mock import Mock

import pytest
from eom_catalog_contracts.kakao_room_rpc import (
    CommandKakaoRoomRequest,
    ListKakaoRoomsRequest,
    ReadKakaoRoomRequest,
    parse_kakao_room_reply,
)
from eom_catalog_contracts.kakao_rooms import KakaoRoomMutation, KakaoRoomPage
from eom_catalog_service.kakao_room_dispatch import dispatch_kakao_room
from eom_catalog_service.kakao_room_service import KakaoRoomService

from tests.unit.kakao_room_fixtures import (
    BINDING_ID,
    KEY,
    MAPPING_ID,
    NOW,
    ROOM_ID,
    map_command,
    room,
    unmap_command,
)

IDENTITY = {
    "actor_id": "operator_" + "4" * 32,
    "session_id": "apisession_" + "5" * 32,
    "request_id": "webreq_room_fixture",
    "authentication_time": NOW,
    "source_binding_id": BINDING_ID,
}


@pytest.mark.parametrize("action", ["map", "unmap", "read", "pinned-read", "list"])
def test_dispatch_uses_public_owner_methods_without_authority_claims(action):
    owner = Mock(spec=KakaoRoomService)
    if action in {"map", "unmap"}:
        request = CommandKakaoRoomRequest(
            **IDENTITY,
            room_id=ROOM_ID,
            idempotency_key=KEY,
            command=map_command() if action == "map" else unmap_command(),
        )
        method = owner.command_room
        method.return_value = KakaoRoomMutation(
            room=room(mapped=action == "map", changed=True), replayed=True
        )
    elif action == "list":
        request = ListKakaoRoomsRequest(**IDENTITY)
        method = owner.list_rooms
        method.return_value = KakaoRoomPage(items=(room(),), next_cursor=None)
    else:
        request = ReadKakaoRoomRequest(
            **IDENTITY,
            room_id=ROOM_ID,
            mapping_revision_id=MAPPING_ID if action == "pinned-read" else None,
        )
        method = owner.get_room
        method.return_value = room()
    reply = parse_kakao_room_reply(
        json.loads(dispatch_kakao_room(owner, request.model_dump(mode="json")))
    )
    assert reply.status == "OK", reply
    actor = method.call_args.args[0]
    assert actor.operator_id == IDENTITY["actor_id"] and not actor.permissions
    assert method.call_args.args[1] == BINDING_ID
    if action in {"map", "unmap"}:
        assert method.call_args.kwargs["idempotency_key"] == KEY
    if action == "pinned-read":
        assert method.call_args.kwargs["mapping_revision_id"] == MAPPING_ID


@pytest.mark.parametrize(
    "field,value",
    [
        ("roles", ["ADMIN"]),
        ("permissions", ["write"]),
        ("profile_path", "/private"),
        ("source_binding_id", "latest"),
    ],
)
def test_invalid_request_never_calls_owner(field, value):
    owner = Mock(spec=KakaoRoomService)
    payload = {
        **ReadKakaoRoomRequest(**IDENTITY, room_id=ROOM_ID).model_dump(mode="json"),
        field: value,
    }
    reply = json.loads(dispatch_kakao_room(owner, payload))
    assert reply["error_code"] == "KAKAO_ARCHIVE_REQUEST_INVALID" and not owner.mock_calls


@pytest.mark.parametrize(
    "case",
    [
        "binding",
        "room",
        "revision",
        "page-binding",
        "page-cursor",
        "parent",
        "student",
        "display",
        "reason",
    ],
)
def test_valid_but_unrelated_private_result_is_redacted(case):
    owner = Mock(spec=KakaoRoomService)
    value = room()
    if case in {"page-binding", "page-cursor"}:
        request = ListKakaoRoomsRequest(
            **IDENTITY, cursor=ROOM_ID if case == "page-cursor" else None
        )
        if case == "page-binding":
            value = value.model_copy(update={"source_binding_id": "kakaobinding_" + "9" * 32})
        owner.list_rooms.return_value = KakaoRoomPage(items=(value,), next_cursor=None)
    elif case in {"parent", "student", "display", "reason"}:
        command = map_command()
        field = {
            "parent": "parent_revision_id",
            "student": "student_id",
            "display": "student_display_revision_id",
            "reason": "reason",
        }[case]
        changed = {
            "parent": "kakaomappingrev_",
            "student": "kakaostudent_",
            "display": "kakaostudentrev_",
        }.get(case, "") + "9" * 32
        command = command.model_copy(update={field: changed})
        request = CommandKakaoRoomRequest(
            **IDENTITY, room_id=ROOM_ID, idempotency_key=KEY, command=command
        )
        owner.command_room.return_value = KakaoRoomMutation(room=room(mapped=True), replayed=True)
    else:
        request = ReadKakaoRoomRequest(
            **IDENTITY,
            room_id=ROOM_ID,
            mapping_revision_id="kakaomappingrev_" + "9" * 32 if case == "revision" else None,
        )
        if case == "binding":
            value = value.model_copy(update={"source_binding_id": "kakaobinding_" + "9" * 32})
        if case == "room":
            value = value.model_copy(update={"room_id": "kakaoroom_" + "9" * 32})
        owner.get_room.return_value = value
    reply = json.loads(dispatch_kakao_room(owner, request.model_dump(mode="json")))
    assert reply["error_code"] == "KAKAO_ARCHIVE_RESULT_INVALID" and reply["result"] is None


def test_no_owner_and_arbitrary_errors_are_not_private_output():
    request = ReadKakaoRoomRequest(**IDENTITY, room_id=ROOM_ID).model_dump(mode="json")
    assert (
        json.loads(dispatch_kakao_room(None, request))["error_code"]
        == "CATALOG_APPLICATION_UNAVAILABLE"
    )
    owner = Mock(spec=KakaoRoomService)
    owner.get_room.side_effect = RuntimeError("private name token")
    result = dispatch_kakao_room(owner, request)
    assert (
        b"private name token" not in result
        and json.loads(result)["error_code"] == "CATALOG_APPLICATION_INTERNAL_ERROR"
    )
