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


async def fetch(page, workspace):
    incoming, destination = workspace
    return await transfer.receive_room_transfer(
        page,
        RoomReadAction.EXPORT_CSV,
        channel_key="channel",
        room_key="room",
        incoming=incoming,
        destination=destination,
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
