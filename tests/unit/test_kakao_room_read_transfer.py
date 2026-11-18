"""Timeout/replay and wrong download events, without touching a provider or profile."""

import asyncio
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from eom_kakao_archive_collector import room_read_transfer as transfer
from eom_kakao_archive_collector.profile import BrowserRuntimeError
from eom_kakao_archive_collector.room_read_actions import RoomReadAction


@pytest.fixture
def workspace():
    with tempfile.TemporaryDirectory(prefix="kakao-transfer-", dir=Path.home() / ".cache") as name:
        root = Path(name)
        incoming, outputs = root / "incoming", root / "outputs"
        incoming.mkdir(mode=0o700)
        outputs.mkdir(mode=0o750)
        outputs.chmod(0o750)
        yield incoming, outputs / "source.csv"


class Page:
    url = "https://business.kakao.com/space/scope/channel/channel/chats"

    def __init__(self):
        self.listeners = {}
        self.evaluate = AsyncMock()

    def on(self, event, callback):
        assert event not in self.listeners
        self.listeners[event] = callback

    def remove_listener(self, event, callback):
        assert self.listeners.pop(event) is callback


async def fetch(page, workspace, *, image=False):
    incoming, destination = workspace
    return await transfer.receive_room_transfer(
        page,
        RoomReadAction.DOWNLOAD_IMAGE if image else RoomReadAction.EXPORT_CSV,
        channel_key="channel",
        room_key="room",
        incoming=incoming,
        destination=destination,
        image_path="/api/profiles/channel/chats/room/message/file/image" if image else None,
    )


def test_uncertain_transfer_keeps_start_fence_and_never_clicks_again(workspace, monkeypatch):
    _, destination = workspace
    page = Page()
    trigger = AsyncMock(return_value=True)
    monkeypatch.setattr(transfer, "trigger_room_read_action", trigger)
    monkeypatch.setattr(transfer, "_EVENT_SECONDS", 0)
    with pytest.raises(BrowserRuntimeError, match="TRANSFER_UNCERTAIN"):
        asyncio.run(fetch(page, workspace))
    assert destination.with_suffix(".started").is_file() and not destination.exists()
    assert not page.listeners and not page.evaluate.called
    with pytest.raises(BrowserRuntimeError, match="TRANSFER_ALREADY_STARTED"):
        asyncio.run(fetch(page, workspace))
    trigger.assert_awaited_once()


@pytest.mark.parametrize("duplicate", [False, True])
def test_unrelated_or_duplicate_event_never_materializes_payload(workspace, monkeypatch, duplicate):
    _, destination = workspace
    page = Page()
    download = SimpleNamespace(
        url=(
            "blob:https://business.kakao.com/synthetic" if duplicate else "https://other.invalid/"
        ),
        path=AsyncMock(),
        cancel=AsyncMock(),
    )

    async def emit(*_args, **_kwargs):
        page.listeners["download"](download)
        if duplicate:
            page.listeners["download"](SimpleNamespace(url=download.url, path=Mock()))
        return True

    monkeypatch.setattr(transfer, "trigger_room_read_action", emit)
    with pytest.raises(BrowserRuntimeError, match="TRANSFER_UNASSOCIATED"):
        asyncio.run(fetch(page, workspace))
    download.path.assert_not_awaited()
    download.cancel.assert_awaited_once()
    assert not page.listeners and not destination.exists()


@pytest.mark.parametrize(
    ("outcome", "expected_type", "code"),
    [
        ("completed", transfer.CompletedUnassociatedPhoto, "TRANSFER_UNASSOCIATED"),
        ("duplicate", BrowserRuntimeError, "TRANSFER_UNASSOCIATED"),
        ("moved", BrowserRuntimeError, "TRANSFER_UNASSOCIATED"),
        ("failed", BrowserRuntimeError, "TRANSFER_FAILED"),
        ("wrong_path", BrowserRuntimeError, "DOWNLOAD_FILE_INVALID"),
        ("missing_request", BrowserRuntimeError, "TRANSFER_UNASSOCIATED"),
    ],
)
def test_only_completed_single_cdn_get_is_a_separable_photo(
    outcome, expected_type, code, workspace, monkeypatch
):
    incoming, destination = workspace
    page = Page()

    async def finished():
        if outcome == "duplicate":
            page.listeners["download"](download)
        if outcome == "moved":
            page.url += "/other"
        if outcome == "failed":
            raise OSError("failed SDK download")
        return (destination.parent if outcome == "wrong_path" else incoming) / "fixture"

    download = SimpleNamespace(
        url="https://k.kakaocdn.net/fixture",
        path=AsyncMock(side_effect=finished),
        cancel=AsyncMock(),
    )

    async def emit(*_args, **_kwargs):
        if outcome != "missing_request":
            page.listeners["request"](
                SimpleNamespace(url=download.url, method="GET", redirected_from=None)
            )
        page.listeners["download"](download)
        return True

    monkeypatch.setattr(transfer, "trigger_room_read_action", emit)
    with pytest.raises(expected_type, match=code) as failure:
        asyncio.run(fetch(page, workspace, image=True))
    assert type(failure.value) is expected_type
    assert not page.listeners and not destination.exists()
