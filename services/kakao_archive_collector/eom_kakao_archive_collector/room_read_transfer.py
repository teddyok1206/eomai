"""Bind one fixed room action to an actual protected local browser transfer."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from eom_kakao_archive_contracts.manual_observation import ManualDocument

from .download_origins import DownloadRequest, DownloadRequestOrigins
from .manual_capture_files import DownloadedFile, commit_download_payload, reserve_download_payload
from .manual_observation import (
    DOCUMENT_EXPRESSION,
    OBSERVATION_SECONDS,
    download_page_path,
    download_target,
)
from .profile import BrowserRuntimeError
from .room_read_actions import RoomReadAction, trigger_room_read_action

_EVENT_SECONDS = 8
_TRANSFER_SECONDS = 60


class BrowserDownload(Protocol):
    @property
    def url(self) -> str: ...
    async def path(self) -> Path | None: ...
    async def cancel(self) -> None: ...


class RoomTransferPage(Protocol):
    @property
    def url(self) -> str: ...
    async def evaluate(self, expression: str, arg: object = None) -> object: ...
    def on(self, event: str, callback: Callable[..., None]) -> None: ...
    def remove_listener(self, event: str, callback: Callable[..., None]) -> None: ...


@dataclass(frozen=True, slots=True)
class RoomTransfer:
    payload: DownloadedFile
    document: ManualDocument | None = field(repr=False)


async def _document(page: RoomTransferPage, path: str) -> ManualDocument | None:
    try:
        raw = await asyncio.wait_for(page.evaluate(DOCUMENT_EXPRESSION), OBSERVATION_SECONDS)
        value = ManualDocument.model_validate(raw)
    except Exception:
        return None
    return value if value.path == path and download_page_path(page) == path else None


async def receive_room_transfer(
    page: RoomTransferPage,
    action: RoomReadAction,
    *,
    channel_key: str,
    room_key: str,
    incoming: Path,
    destination: Path,
    image_path: str | None = None,
) -> RoomTransfer:
    """Use an exclusively owned page, one action, and one prevalidated attempt location.

    Reserve the output before triggering a click. An uncertain transfer is not
    permission to repeat it. The surrounding collector closes the original run.
    """
    if not isinstance(action, RoomReadAction) or action is RoomReadAction.OPEN_EXPORT_MENU:
        raise BrowserRuntimeError("KAKAO_ROOM_READ_ACTION_INVALID")
    path = download_page_path(page)
    if path is None:
        raise BrowserRuntimeError("KAKAO_ROOM_READ_ACTION_UNAVAILABLE")
    reserve_download_payload(incoming, destination)
    origins = DownloadRequestOrigins()
    loop = asyncio.get_running_loop()
    received: asyncio.Future[tuple[BrowserDownload, bool]] = loop.create_future()
    duplicates = closed = False
    image = action is RoomReadAction.DOWNLOAD_IMAGE

    def request_event(request: DownloadRequest) -> None:
        if image and not closed and not received.done():
            origins.observe("one-room", request, page_path=download_page_path(page))

    def download_event(download: BrowserDownload) -> None:
        nonlocal duplicates
        if closed:
            return
        if received.done():
            duplicates = True
            return
        matched = False
        try:
            url, observed_path = download.url, download_page_path(page)
            if isinstance(url, str) and observed_path == path:
                if image:
                    target = origins.consume("one-room", url, page_path=path)
                    matched = target is not None and target.path == image_path
                else:
                    matched = download_target(url).kind == "BLOB"
        except Exception:
            pass  # Missing SDK metadata is an unassociated transfer.
        received.set_result((download, matched))

    listeners: list[tuple[str, Callable[..., None]]] = []
    committed = False
    try:
        for name, callback in (("request", request_event), ("download", download_event)):
            page.on(name, callback)
            listeners.append((name, callback))
        await trigger_room_read_action(
            page, action, channel_key=channel_key, room_key=room_key, image_path=image_path
        )
        try:
            download, matched = await asyncio.wait_for(asyncio.shield(received), _EVENT_SECONDS)
            if duplicates or not matched:
                raise BrowserRuntimeError("KAKAO_ROOM_TRANSFER_UNASSOCIATED")
            document = await _document(page, path)
            local = await asyncio.wait_for(download.path(), _TRANSFER_SECONDS)
        except TimeoutError:
            raise BrowserRuntimeError("KAKAO_ROOM_TRANSFER_UNCERTAIN") from None
        except BrowserRuntimeError:
            raise
        except Exception:
            raise BrowserRuntimeError("KAKAO_ROOM_TRANSFER_FAILED") from None
        if duplicates or local is None or download_page_path(page) != path:
            raise BrowserRuntimeError("KAKAO_ROOM_TRANSFER_UNASSOCIATED")
        payload = commit_download_payload(
            local, incoming=incoming, destination=destination, limit=32 * 1024 * 1024
        )
        committed = True
        return RoomTransfer(payload, document)
    finally:
        closed = True
        for name, callback in reversed(listeners):
            with suppress(Exception):
                page.remove_listener(name, callback)
        origins.clear()
        if not committed and received.done() and not received.cancelled():
            with suppress(Exception):
                await asyncio.wait_for(received.result()[0].cancel(), 1)
        if not received.done():
            received.cancel()
