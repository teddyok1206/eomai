"""Visible-window coverage and partial file preservation; no Kakao account."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest
from eom_kakao_archive_collector import open_room_capture as capture
from eom_kakao_archive_collector.manual_capture_files import DownloadedFile
from eom_kakao_archive_collector.profile import BrowserRuntimeError
from eom_kakao_archive_collector.room_read_transfer import (
    CompletedUnassociatedPhoto,
    RefusedPhotoAction,
    RoomTransfer,
)
from eom_kakao_archive_contracts.manual_observation import ManualDocument

PATH = "/space/work/channel/channel/chats"
FIRST = "/api/profiles/channel/chats/room/message/first/image"
SECOND = "/api/profiles/channel/chats/room/message/second/image"


def document(entries, *, truncated=False):
    nodes = []

    def node(parent, tag, classes, path=None):
        index = len(nodes)
        nodes.append(
            dict(
                index=index,
                parent_index=parent,
                tag=tag,
                classes=classes,
                role=None,
                label=None,
                text=None,
                link_path=path,
                is_image=False,
                identities={
                    name: None
                    for name in ("data-id", "data-chat-id", "data-message-id", "data-log-id")
                },
            )
        )
        return index

    popup = node(None, "div", ("chat_popup",))
    for path, album in entries:
        bubble = node(popup, "div", ("item_chat",))
        contents = node(bubble, "div", ("set_chat", "box_package") if album else ("set_chat",))
        node(contents, "a", ("link_pic",))
        if path:
            node(contents, "a", ("btn_save",), path)
    return ManualDocument.model_validate(
        dict(origin="https://business.kakao.com", path=PATH, nodes=nodes, truncated=truncated)
    )


def plan(value):
    return capture._visible_photo_plan(value, channel_key="channel", room_key="room")


def test_duplicated_unknown_and_album_bubbles_only_affect_coverage():
    value = document([(FIRST, False), (FIRST, False), (SECOND, False), (None, True), (None, False)])
    assert plan(value) == ((SECOND,), 4)


def test_visible_photo_limit_preserves_remaining_bubble_count():
    links = [FIRST.replace("/first/", f"/photo{i}/") for i in range(9)]
    assert plan(document([(link, False) for link in links])) == (tuple(links[:6]), 3)


@pytest.mark.parametrize(
    "value",
    [
        document([(FIRST, False), (SECOND.replace("/room/", "/other/"), False)]),
        document([(FIRST, False)], truncated=True),
        document([(None, True)]),
    ],
)
def test_ambiguous_room_or_truncated_dom_is_not_executed(value, monkeypatch):
    monkeypatch.setattr(capture, "observe_room_document", AsyncMock(return_value=value))
    reserved = Mock()
    monkeypatch.setattr(capture, "reserve_download_payload", reserved)
    with pytest.raises(BrowserRuntimeError, match="EVIDENCE_UNAVAILABLE"):
        asyncio.run(
            capture.capture_open_room(
                Mock(),
                channel_key="channel",
                room_key="room",
                incoming=Path("/synthetic/incoming"),
                outputs=Path("/synthetic/outputs"),
            )
        )
    reserved.assert_not_called()


def test_unknown_second_transfer_keeps_first_without_exporting_again(monkeypatch):
    value = document([(FIRST, False), (SECOND, False), (None, True)])
    received = RoomTransfer(DownloadedFile(10, "sha256:" + "a" * 64), value)
    monkeypatch.setattr(capture, "observe_room_document", AsyncMock(return_value=value))
    monkeypatch.setattr(capture, "reserve_download_payload", Mock())
    read = AsyncMock(side_effect=(received, BrowserRuntimeError("KAKAO_ROOM_TRANSFER_UNCERTAIN")))
    menu = AsyncMock()
    monkeypatch.setattr(capture, "receive_room_transfer", read)
    monkeypatch.setattr(capture, "trigger_room_read_action", menu)
    result = asyncio.run(
        capture.capture_open_room(
            Mock(),
            channel_key="channel",
            room_key="room",
            incoming=Path("/synthetic/incoming"),
            outputs=Path("/synthetic/outputs"),
        )
    )
    assert result.csv is None and result.error_code == "KAKAO_ROOM_TRANSFER_UNCERTAIN"
    assert result.unresolved_visible_bubbles == 2
    assert len(result.photos) == 1 and result.photos[0].image_path == FIRST
    assert result.photos[0].transfer is received
    assert [a.kwargs["image_path"] for a in read.await_args_list] == [FIRST, SECOND]
    menu.assert_not_awaited()


def test_completed_unbound_photo_preserves_verified_inputs_and_exports_csv_once(monkeypatch):
    third = SECOND.replace("/second/", "/third/")
    value = document([(FIRST, False), (SECOND, False), (third, False), (None, True)])
    photo = RoomTransfer(DownloadedFile(10, "sha256:" + "a" * 64), value)
    csv = RoomTransfer(DownloadedFile(20, "sha256:" + "b" * 64), value)
    monkeypatch.setattr(capture, "observe_room_document", AsyncMock(return_value=value))
    monkeypatch.setattr(capture, "reserve_download_payload", Mock())
    read = AsyncMock(
        side_effect=(photo, CompletedUnassociatedPhoto("KAKAO_ROOM_TRANSFER_UNASSOCIATED"), csv)
    )
    menu = AsyncMock(return_value=True)
    monkeypatch.setattr(capture, "receive_room_transfer", read)
    monkeypatch.setattr(capture, "trigger_room_read_action", menu)
    result = asyncio.run(
        capture.capture_open_room(
            Mock(),
            channel_key="channel",
            room_key="room",
            incoming=Path("/synthetic/incoming"),
            outputs=Path("/synthetic/outputs"),
        )
    )
    assert result.csv is csv and result.error_code is None
    assert result.unresolved_visible_bubbles == 3
    assert [stored.image_path for stored in result.photos] == [FIRST]
    assert [call.kwargs.get("image_path") for call in read.await_args_list] == [FIRST, SECOND, None]
    assert [call.args[1] for call in read.await_args_list] == [
        capture.RoomReadAction.DOWNLOAD_IMAGE,
        capture.RoomReadAction.DOWNLOAD_IMAGE,
        capture.RoomReadAction.EXPORT_CSV,
    ]
    menu.assert_awaited_once()


def test_refused_photo_keeps_its_position_and_collects_other_inputs(monkeypatch):
    value = document([(FIRST, False), (SECOND, False)])
    photo = RoomTransfer(DownloadedFile(10, "sha256:" + "a" * 64), value)
    csv = RoomTransfer(DownloadedFile(20, "sha256:" + "b" * 64), value)
    monkeypatch.setattr(capture, "observe_room_document", AsyncMock(return_value=value))
    monkeypatch.setattr(capture, "reserve_download_payload", Mock())
    read = AsyncMock(
        side_effect=(RefusedPhotoAction("KAKAO_ROOM_READ_ACTION_UNAVAILABLE"), photo, csv)
    )
    menu = AsyncMock(return_value=True)
    monkeypatch.setattr(capture, "receive_room_transfer", read)
    monkeypatch.setattr(capture, "trigger_room_read_action", menu)
    result = asyncio.run(
        capture.capture_open_room(
            Mock(),
            channel_key="channel",
            room_key="room",
            incoming=Path("/synthetic/incoming"),
            outputs=Path("/synthetic/outputs"),
        )
    )
    assert result.csv is csv and result.error_code is None
    assert result.unresolved_visible_bubbles == 1
    assert [(stored.image_path, stored.member_name) for stored in result.photos] == [
        (SECOND, "photo-2.bin")
    ]
    assert [args.kwargs["destination"].name for args in read.await_args_list] == [
        "photo-1.bin",
        "photo-2.bin",
        "source.csv",
    ]
    menu.assert_awaited_once()
