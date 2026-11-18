"""Capture a bounded visible slice of one independently pinned, already open room."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from eom_kakao_archive_contracts.manual_observation import ManualDocument

from .manual_capture_files import reserve_download_payload
from .profile import BrowserRuntimeError
from .room_read_actions import RoomReadAction, trigger_room_read_action
from .room_read_transfer import (
    RoomTransfer,
    RoomTransferPage,
    observe_room_document,
    receive_room_transfer,
)

_MAX_PHOTOS = 6
_SEGMENT = r"[A-Za-z0-9_-]{1,128}"
_CHANNEL = re.compile(rf"/space/{_SEGMENT}/channel/({_SEGMENT})/chats(?:/|$)")
_IMAGE_ROUTE = re.compile(
    rf"/api/profiles/({_SEGMENT})/chats/({_SEGMENT})/{_SEGMENT}/{_SEGMENT}/image"
)


@dataclass(frozen=True, slots=True)
class OpenRoomPhoto:
    member_name: str
    image_path: str = field(repr=False)
    transfer: RoomTransfer = field(repr=False)


@dataclass(frozen=True, slots=True)
class OpenRoomCapture:
    csv: RoomTransfer | None = field(repr=False)
    photos: tuple[OpenRoomPhoto, ...] = field(repr=False)
    unresolved_visible_bubbles: int
    error_code: str | None


@dataclass(slots=True)
class _Bubble:
    pictures: int = 0
    album: bool = False
    links: list[str] = field(default_factory=list, repr=False)


def _visible_photo_plan(
    document: ManualDocument, *, channel_key: str, room_key: str
) -> tuple[tuple[str, ...], int]:
    channel = _CHANNEL.match(document.path)
    popups = [node.index for node in document.nodes if "chat_popup" in node.classes]
    if channel is None or channel[1] != channel_key or len(popups) != 1 or document.truncated:
        raise BrowserRuntimeError("KAKAO_OPEN_ROOM_EVIDENCE_UNAVAILABLE")
    branches: dict[int | None, _Bubble | None] = {popups[0]: None}
    bubbles: list[_Bubble] = []
    for node in document.nodes[popups[0] + 1 :]:
        if node.parent_index not in branches:
            continue
        bubble = branches[node.parent_index]
        if "item_chat" in node.classes:
            if bubble is not None:
                raise BrowserRuntimeError("KAKAO_OPEN_ROOM_EVIDENCE_UNAVAILABLE")
            bubble = _Bubble()
            bubbles.append(bubble)
        if bubble is not None:
            if "box_package" in node.classes:
                bubble.album = True
            if node.tag == "a" and "link_pic" in node.classes:
                bubble.pictures += 1
            if node.tag == "a" and "btn_save" in node.classes and node.link_path:
                match = _IMAGE_ROUTE.fullmatch(node.link_path)
                if match is None or match.groups() != (channel_key, room_key):
                    raise BrowserRuntimeError("KAKAO_OPEN_ROOM_EVIDENCE_UNAVAILABLE")
                bubble.links.append(node.link_path)
        branches[node.index] = bubble
    counts = Counter(link for bubble in bubbles for link in bubble.links)
    if not counts:
        raise BrowserRuntimeError("KAKAO_OPEN_ROOM_EVIDENCE_UNAVAILABLE")
    candidates: list[str] = []
    unresolved = 0
    for bubble in bubbles:
        if not (bubble.album or bubble.pictures or bubble.links):
            continue
        if (
            not bubble.album
            and bubble.pictures == len(bubble.links) == 1
            and counts[bubble.links[0]] == 1
            and len(candidates) < _MAX_PHOTOS
        ):
            candidates.append(bubble.links[0])
        else:
            unresolved += 1
    return tuple(candidates), unresolved


async def capture_open_room(
    page: RoomTransferPage,
    *,
    channel_key: str,
    room_key: str,
    incoming: Path,
    outputs: Path,
) -> OpenRoomCapture:
    """No login, room navigation, DOM scrolling for history, or source admission."""
    document = await observe_room_document(page)
    if document is None:
        raise BrowserRuntimeError("KAKAO_OPEN_ROOM_EVIDENCE_UNAVAILABLE")
    targets, unresolved = _visible_photo_plan(document, channel_key=channel_key, room_key=room_key)
    reserve_download_payload(incoming, outputs / "room.capture")
    photos = []
    try:
        for ordinal, target in enumerate(targets, 1):
            name = f"photo-{ordinal}.bin"  # Decoder verifies media type downstream.
            received = await receive_room_transfer(
                page,
                RoomReadAction.DOWNLOAD_IMAGE,
                channel_key=channel_key,
                room_key=room_key,
                incoming=incoming,
                destination=outputs / name,
                image_path=target,
            )
            photos.append(OpenRoomPhoto(name, target, received))
        if not await trigger_room_read_action(
            page, RoomReadAction.OPEN_EXPORT_MENU, channel_key=channel_key, room_key=room_key
        ):
            raise BrowserRuntimeError("KAKAO_OPEN_ROOM_MENU_ALREADY_OPEN")
        csv = await receive_room_transfer(
            page,
            RoomReadAction.EXPORT_CSV,
            channel_key=channel_key,
            room_key=room_key,
            incoming=incoming,
            destination=outputs / "source.csv",
        )
    except BrowserRuntimeError as error:
        # Keep known files. Unknown action outcome may not start another transfer.
        return OpenRoomCapture(
            None, tuple(photos), unresolved + len(targets) - len(photos), error.code
        )
    return OpenRoomCapture(csv, tuple(photos), unresolved, None)
