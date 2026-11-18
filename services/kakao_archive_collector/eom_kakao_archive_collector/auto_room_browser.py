"""Exact local AUTO request and fixed read-only navigation for one registered room."""

import asyncio
import os
import pwd
from pathlib import Path
from typing import Protocol

from eom_kakao_archive_contracts.auto_room_command import (
    MAX_AUTO_ROOM_COMMAND_BYTES,
    AutoRoomCommand,
)
from eom_kakao_archive_contracts.kakao_remote import ProfileFence

from .manual_capture_files import create_capture_directory
from .manual_observation import download_page_path
from .open_room_capture import capture_open_room_attempt
from .profile import BrowserRuntimeError, protected_directory, read_protected
from .room_read_transfer import RoomTransferPage
from .supervisor import REQUEST

DOWNLOADS = Path("/var/lib/eom-kakao/downloads")
ROOM_COMMAND_WAIT = 120.0
ROOM_LOAD_SECONDS = 10.0
_ORIGIN = "https://business.kakao.com"

# Deliberately no heuristics for unknown provider UI: a selected room is not a
# display name, and sending/control areas are never navigation targets.
_OPEN_ROOM = r"""({path, room, phase}) => {
  if (location.origin !== 'https://business.kakao.com' || location.pathname !== path ||
      window.top !== window || !document.body) return 'UNAVAILABLE';
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_ELEMENT);
  for (let count = 0; walker.nextNode(); count++) if (count === 8192) return 'UNAVAILABLE';
  const visible = node => node instanceof HTMLElement && node.isConnected &&
    !node.closest('[hidden],[inert],[aria-hidden="true"],[contenteditable],form') &&
    node.checkVisibility({visibilityProperty:true,opacityProperty:true});
  const popups = Array.from(document.querySelectorAll('.chat_popup')).filter(visible);
  if (popups.length > 1) return 'UNAVAILABLE';
  if (popups.length === 1) {
    const shownRoom = popups[0].getAttribute('data-chat-id');
    if (shownRoom !== null) return shownRoom === room ? 'OPENED' : 'UNAVAILABLE';
    const prefix = '/api/profiles/' + path.split('/')[4] + '/chats/' + room + '/';
    const links = Array.from(popups[0].querySelectorAll('.item_chat .set_chat a.btn_save'))
      .filter(visible);
    return links.some(link => {
      try {
        const url = new URL(link.href);
        return url.origin === location.origin && url.pathname.startsWith(prefix);
      } catch { return false; }
    }) ? 'OPENED' : 'PENDING';
  }
  if (phase === 'CONFIRM') return 'PENDING';
  const rows = Array.from(document.querySelectorAll('.list_chat li[data-chat-id]'))
    .filter(row => visible(row) && row.getAttribute('data-chat-id') === room &&
      !row.closest('.chat_popup'));
  if (!rows.length) return 'PENDING';
  if (rows.length !== 1) return 'UNAVAILABLE';
  const candidates = Array.from(rows[0].querySelectorAll(':scope > button[type="button"]'))
    .filter(node => visible(node) && !node.disabled && !node.form &&
      node.getAttribute('aria-disabled') !== 'true' &&
      node.getAttribute('data-chat-id') === room);
  if (candidates.length !== 1) return 'UNAVAILABLE';
  if (phase === 'PROBE') return 'READY';
  if (phase !== 'CLICK') return 'UNAVAILABLE';
  const target = candidates[0];
  target.scrollIntoView({block:'center',inline:'nearest',behavior:'instant'});
  const box = target.getBoundingClientRect();
  const hit = document.elementFromPoint(box.left+box.width/2,box.top+box.height/2);
  if (!box.width || !box.height || !visible(target) || !hit || !target.contains(hit))
    return 'UNAVAILABLE';
  target.click();
  return 'TRIGGERED';
}"""


class AutoRoomPage(RoomTransferPage, Protocol):
    async def goto(self, url: str, *, wait_until: str, timeout: float) -> object: ...


async def wait_for_room_command(
    fence: ProfileFence, stopping: asyncio.Event
) -> AutoRoomCommand | None:
    """Only the trusted installed owner may create this per-epoch input."""
    owner = pwd.getpwnam("eom-catalog-manager").pw_uid
    path = REQUEST.with_name(f"{fence.browser_run_id}.capture.json")
    loop = asyncio.get_running_loop()
    deadline = loop.time() + ROOM_COMMAND_WAIT
    while not stopping.is_set() and loop.time() < deadline:
        try:
            raw = read_protected(
                path,
                uid=owner,
                limit=MAX_AUTO_ROOM_COMMAND_BYTES,
                allowed_uids=frozenset({0, owner}),
                required_mode=0o640,
            )
        except FileNotFoundError:
            try:
                await asyncio.wait_for(stopping.wait(), timeout=0.25)
            except TimeoutError:
                continue
            break
        try:
            return AutoRoomCommand.decode(raw, fence)
        except ValueError:
            raise BrowserRuntimeError("KAKAO_AUTO_ROOM_COMMAND_INVALID") from None
    if stopping.is_set():
        return None
    raise BrowserRuntimeError("KAKAO_AUTO_ROOM_COMMAND_UNAVAILABLE")


def stage_room_workspace(command: AutoRoomCommand, *, root: Path = DOWNLOADS) -> tuple[Path, Path]:
    """Fixed worker-only filesystem materialization, not a new work claim."""
    attempt = root / command.command.execution.attempt_id
    try:
        with protected_directory(root, allowed_uids=frozenset({0, os.geteuid()})) as parent:
            if os.fstat(parent).st_uid != os.geteuid():
                raise BrowserRuntimeError("KAKAO_AUTO_ROOM_WORKSPACE_UNAVAILABLE")
            # Existing work (including failed acquisition) never gets reused or removed.
            os.mkdir(attempt.name, mode=0o750, dir_fd=parent)
    except FileExistsError:
        raise BrowserRuntimeError("KAKAO_AUTO_ROOM_ALREADY_STARTED") from None
    try:
        with protected_directory(attempt, allowed_uids=frozenset({0, os.geteuid()})) as own:
            os.fchmod(own, 0o750)
        incoming, outputs = attempt / ".incoming", attempt / "outputs"
        create_capture_directory(incoming, private=True)
        create_capture_directory(outputs)
    except OSError:
        raise BrowserRuntimeError("KAKAO_AUTO_ROOM_WORKSPACE_UNAVAILABLE") from None
    return incoming, outputs


async def read_registered_room(
    page: AutoRoomPage, command: AutoRoomCommand, *, incoming: Path, outputs: Path
) -> None:
    path = f"/space/{command.space_key}/channel/{command.channel_key}/chats"
    target = _ORIGIN + path
    try:
        await page.goto(target, wait_until="domcontentloaded", timeout=ROOM_LOAD_SECONDS * 1000)
    except Exception:
        raise BrowserRuntimeError("KAKAO_AUTO_CHANNEL_NAVIGATION_FAILED") from None
    if download_page_path(page) != path:
        raise BrowserRuntimeError("KAKAO_AUTO_CHANNEL_NOT_CONFIRMED")

    async def evaluate(candidate: AutoRoomPage, candidate_path: str, phase: str) -> object:
        return await asyncio.wait_for(
            candidate.evaluate(
                _OPEN_ROOM, {"path": candidate_path, "room": command.room_key, "phase": phase}
            ),
            timeout=ROOM_LOAD_SECONDS,
        )

    loop = asyncio.get_running_loop()
    until = loop.time() + ROOM_LOAD_SECONDS
    state: object = "PENDING"
    while state == "PENDING" and loop.time() < until:
        state = await evaluate(page, path, "PROBE")
        if state == "PENDING":
            await asyncio.sleep(0.2)

    selected = page
    if state == "READY":
        popups: list[AutoRoomPage] = []

        def opened(candidate: AutoRoomPage) -> None:
            if len(popups) < 2:
                popups.append(candidate)

        popup_path = f"{path}/{command.room_key}"
        page.on("popup", opened)
        try:
            state = await evaluate(page, path, "CLICK")
            if state == "TRIGGERED":
                state = "PENDING"
                until = loop.time() + ROOM_LOAD_SECONDS
                while state == "PENDING" and loop.time() < until:
                    if len(popups) > 1:
                        state = "UNAVAILABLE"
                    elif popups:
                        selected = popups[0]
                        if download_page_path(selected) == popup_path:
                            state = await evaluate(selected, popup_path, "CONFIRM")
                        elif selected.url != "about:blank":
                            state = "UNAVAILABLE"
                    else:
                        state = await evaluate(page, path, "CONFIRM")
                        if popups:
                            state = "PENDING"  # Prefer the newly created window, never both.
                    if state == "PENDING":
                        await asyncio.sleep(0.2)
                if len(popups) > 1:
                    state = "UNAVAILABLE"
        finally:
            page.remove_listener("popup", opened)
    if state != "OPENED":
        raise BrowserRuntimeError("KAKAO_AUTO_ROOM_SELECTOR_UNVERIFIED")
    result = await capture_open_room_attempt(
        selected,
        command.command,
        channel_key=command.channel_key,
        room_key=command.room_key,
        incoming=incoming,
        outputs=outputs,
    )
    if result.error_code is not None:
        raise BrowserRuntimeError(result.error_code)
