"""Visible-window coverage and partial file preservation; no Kakao account."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest
from eom_kakao_archive_collector import open_room_capture as capture
from eom_kakao_archive_collector.manual_capture_files import DownloadedFile
from eom_kakao_archive_collector.profile import BrowserRuntimeError
from eom_kakao_archive_collector.room_read_transfer import RoomTransfer
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
