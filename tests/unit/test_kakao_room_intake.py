"""Manual identity contracts do not grant automatic capture or source authority."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from eom_catalog_contracts.kakao_room_intake import (
    ConfirmKakaoManualRoom,
    KakaoManualRoomEvidence,
    manual_room_identity_sha256,
    observed_manual_room_keys,
)
from eom_catalog_contracts.validation import CATALOG_SCHEMA_RESOURCES
from eom_identifiers import canonical_json_bytes, sha256_bytes


def confirmation():
    return ConfirmKakaoManualRoom(
        source_binding_id="kakaobinding_" + "a" * 32,
        manual_lease_id="kakaoremotelease_" + "b" * 32,
        capture_id="kakaodownload_" + "c" * 32,
        expected_channel_key="channel-one",
        expected_room_key="room-one",
        display_name="같은 이름도 다른 방일 수 있음",
        expected_binding_version=1,
    )


def evidence():
    command, now = confirmation(), datetime.now(UTC)
    return dict(
        owner_operator_id="operator_" + "d" * 32,
        confirmation=command,
        request_sha256=sha256_bytes(canonical_json_bytes(command.model_dump(mode="json"))),
        profile_id="kakaoprofile_" + "e" * 32,
        browser_run_id="kakaobrowserrun_" + "f" * 32,
        fence_epoch=1,
        page_instance_id="kakaopage_" + "0" * 32,
        capture_started_at=now,
        observed_at=now,
        capture_completed_at=now + timedelta(seconds=1),
        payload_sha256="sha256:" + "1" * 64,
        payload_bytes=123,
        receipt_sha256="sha256:" + "2" * 64,
        observation_sha256="sha256:" + "3" * 64,
        source_identity_sha256=manual_room_identity_sha256("channel-one", "room-one"),
    )


def test_manual_room_schema_bytes_and_mirror_frozen_values():
    root = Path(__file__).resolve().parents[2]
    item = CATALOG_SCHEMA_RESOURCES["kakao-manual-room-intake-v1"]
    raw = (root / item.canonical_path).read_bytes()
    assert sha256_bytes(raw) == item.sha256
    assert (
        raw
        == (
            root / "packages/catalog_contracts/eom_catalog_contracts" / item.resource_path
        ).read_bytes()
    )
    value = KakaoManualRoomEvidence.model_validate(evidence())
    assert KakaoManualRoomEvidence.model_validate_json(value.model_dump_json()) == value
    with pytest.raises(ValueError):
        value.confirmation.expected_room_key = "different"


@pytest.mark.parametrize(
    "field,value",
    [
        ("approved", True),
        ("path", "/private"),
        ("actor_role", "ADMIN"),
        ("expected_room_key", "../other"),
        ("expected_channel_key", "name?token=secret"),
        ("expected_binding_version", True),
        ("display_name", "bad\nname"),
    ],
)
def test_request_cannot_claim_authority_or_storage(field, value):
    raw = confirmation().model_dump(mode="json") | {field: value}
    with pytest.raises(ValueError):
        ConfirmKakaoManualRoom.model_validate(raw)


@pytest.mark.parametrize(
    "field,value",
    [
        ("request_sha256", "sha256:" + "0" * 64),
        ("source_identity_sha256", "sha256:" + "0" * 64),
        ("capture_completed_at", datetime(2000, 1, 1, tzinfo=UTC)),
        ("identity_method", "SOURCE_VERIFIED"),
    ],
)
def test_evidence_is_exact_and_does_not_overstate_identity(field, value):
    with pytest.raises(ValueError):
        KakaoManualRoomEvidence.model_validate(evidence() | {field: value})


@pytest.mark.parametrize(
    "document,target,expected",
    [
        (
            "/space/workspace/channel/channel-one/chats",
            "/api/profiles/channel-one/chats/room-one/logs/photo/image",
            ("channel-one", "room-one"),
        ),
        (
            "/space/workspace/channel/another/chats",
            "/api/profiles/channel-one/chats/room-one/logs/photo/image",
            None,
        ),
        ("/space/workspace/channel/channel-one/chats", "", None),
        (
            "/space/workspace/channel/channel-one/chats",
            "/api/profiles/channel-one/chats/room-one/logs/photo/image?signature=secret",
            None,
        ),
        (
            "/space/workspace/channel/channel-one/chats",
            "/api/profiles/channel-one/chats/room-one/logs/../image",
            None,
        ),
        (
            "/space/workspace/channel/channel-one/chats",
            "https://business.kakao.com/api/profiles/channel-one/chats/room-one/logs/photo/image",
            None,
        ),
    ],
)
def test_only_observed_path_structure_no_filename_or_guessed_document_room(
    document, target, expected
):
    assert observed_manual_room_keys(document, target) == expected
