"""Exact local AUTO request and fixed read-only navigation for one registered room."""

import asyncio
import os
import pwd
from pathlib import Path
from typing import Protocol
from urllib.parse import urlsplit

from eom_kakao_archive_contracts.auto_room_command import (
    MAX_AUTO_ROOM_COMMAND_BYTES,
    AutoRoomInput,
    AutoRoomPopupCommand,
    decode_auto_room_input,
)
from eom_kakao_archive_contracts.capture import (
    ROOM_AUTH_REFUSAL_NAME,
    CaptureResult,
    validate_capture_contract,
)
from eom_kakao_archive_contracts.kakao_remote import ProfileFence
from eom_kakao_archive_contracts.render import canonical_bytes, sha256

from .manual_capture_files import create_capture_directory, write_capture_receipt
from .manual_observation import download_page_path
from .open_room_capture import capture_open_room_attempt
from .profile import BrowserRuntimeError, protected_directory, read_protected
from .room_read_transfer import RoomTransferPage
from .supervisor import REQUEST

DOWNLOADS = Path("/var/lib/eom-kakao/downloads")
ROOM_COMMAND_WAIT = 120.0
ROOM_LOAD_SECONDS = 10.0
LIST_DIAGNOSTIC_SECONDS = 2.0
_ORIGIN = "https://business.kakao.com"
_ACCOUNT_REQUIRED = "KAKAO_AUTO_POPUP_AND_LIST_TO_ACCOUNT_ORIGIN"
_DOM_FAILURES = frozenset(
    {
        "KAKAO_AUTO_ROOM_DOM_SCOPE_UNAVAILABLE",
        "KAKAO_AUTO_ROOM_DOM_LIMIT",
        "KAKAO_AUTO_ROOM_POPUP_CONFLICT",
        "KAKAO_AUTO_ROOM_LIST_ROWS_AMBIGUOUS",
        "KAKAO_AUTO_ROOM_LIST_BUTTON_UNCONFIRMED",
    }
)

# Deliberately no heuristics for unknown provider UI: a selected room is not a
# display name, and sending/control areas are never navigation targets.
_OPEN_ROOM = r"""({path, room, phase}) => {
  if (location.origin !== 'https://business.kakao.com' || location.pathname !== path)
    return 'PAGE_MOVED';
  if (window.top !== window) return 'KAKAO_AUTO_ROOM_DOM_SCOPE_UNAVAILABLE';
  if (!document.body || document.readyState === 'loading') return 'PENDING';
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_ELEMENT);
  for (let count = 0; walker.nextNode(); count++)
    if (count === 8192) return 'KAKAO_AUTO_ROOM_DOM_LIMIT';
  const visible = node => node instanceof HTMLElement && node.isConnected &&
    !node.closest('[hidden],[inert],[aria-hidden="true"],[contenteditable],form') &&
    node.checkVisibility({visibilityProperty:true,opacityProperty:true});
  const popups = Array.from(document.querySelectorAll('.chat_popup')).filter(visible);
  if (popups.length > 1) return 'KAKAO_AUTO_ROOM_POPUP_CONFLICT';
  if (popups.length === 1) {
    const shownRoom = popups[0].getAttribute('data-chat-id');
    if (shownRoom !== null) return shownRoom === room ? 'OPENED' : 'KAKAO_AUTO_ROOM_POPUP_CONFLICT';
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
  if (rows.length !== 1) return 'KAKAO_AUTO_ROOM_LIST_ROWS_AMBIGUOUS';
  const candidates = Array.from(rows[0].querySelectorAll(':scope > button[type="button"]'))
    .filter(node => visible(node) && !node.disabled && !node.form &&
      node.getAttribute('aria-disabled') !== 'true' &&
      node.getAttribute('data-chat-id') === room);
  if (candidates.length !== 1) return 'KAKAO_AUTO_ROOM_LIST_BUTTON_UNCONFIRMED';
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


def _account_origin(page: AutoRoomPage) -> bool:
    try:
        url = urlsplit(page.url)
        return (
            url.scheme == "https"
            and url.hostname == "accounts.kakao.com"
            and url.port in {None, 443}
            and url.username is None
            and url.password is None
        )
    except (TypeError, ValueError):
        return False


def _dom_failure(result: object, fallback: str) -> str:
    return result if isinstance(result, str) and result in _DOM_FAILURES else fallback


async def wait_for_room_command(
    fence: ProfileFence, stopping: asyncio.Event
) -> AutoRoomInput | None:
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
            return decode_auto_room_input(raw, fence)
        except ValueError:
            raise BrowserRuntimeError("KAKAO_AUTO_ROOM_COMMAND_INVALID") from None
    if stopping.is_set():
        return None
    raise BrowserRuntimeError("KAKAO_AUTO_ROOM_COMMAND_UNAVAILABLE")


def stage_room_workspace(command: AutoRoomInput, *, root: Path = DOWNLOADS) -> tuple[Path, Path]:
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
    page: AutoRoomPage, command: AutoRoomInput, *, incoming: Path, outputs: Path
) -> None:
    path = f"/space/{command.space_key}/channel/{command.channel_key}/chats"
    popup_path = f"{path}/{command.room_key}"
    direct = isinstance(command, AutoRoomPopupCommand)
    destination = popup_path if direct else path
    rejection = (
        "KAKAO_AUTO_VERIFIED_POPUP_NOT_CONFIRMED" if direct else "KAKAO_AUTO_CHANNEL_NOT_CONFIRMED"
    )
    try:
        await page.goto(
            _ORIGIN + destination, wait_until="domcontentloaded", timeout=ROOM_LOAD_SECONDS * 1000
        )
    except Exception:
        raise BrowserRuntimeError("KAKAO_AUTO_CHANNEL_NAVIGATION_FAILED") from None

    async def evaluate(candidate: AutoRoomPage, candidate_path: str, phase: str) -> object:
        return await asyncio.wait_for(
            candidate.evaluate(
                _OPEN_ROOM, {"path": candidate_path, "room": command.room_key, "phase": phase}
            ),
            timeout=ROOM_LOAD_SECONDS,
        )

    async def observe(candidate_path: str, phase: str, seconds: float) -> object:
        """A read-only evaluation may straddle SPA navigation, never a click replay."""
        latest: object = "PENDING"
        try:
            async with asyncio.timeout(seconds):
                while True:
                    if download_page_path(page) != candidate_path:
                        return "PAGE_MOVED"
                    try:
                        latest = await evaluate(page, candidate_path, phase)
                    except Exception:
                        # The old document's execution context can disappear mid-read.
                        latest = "PENDING"
                    if latest not in ("PENDING", "PAGE_MOVED"):
                        return latest
                    await asyncio.sleep(0.2)
        except TimeoutError:
            return latest

    async def popup_rejection() -> str:
        observed = download_page_path(page)
        if observed == popup_path:
            return rejection
        if observed != path:
            if not _account_origin(page):
                return "KAKAO_AUTO_POPUP_TO_OTHER_DESTINATION"
            # After an account redirect, a read-only visit to the known list can
            # distinguish a room-only block from account gating on both routes.
            # This never retries, clicks, or changes the outcome to a capture.
            try:
                async with asyncio.timeout(LIST_DIAGNOSTIC_SECONDS):
                    await page.goto(
                        _ORIGIN + path,
                        wait_until="domcontentloaded",
                        timeout=LIST_DIAGNOSTIC_SECONDS * 1000,
                    )
                    probe = await observe(path, "PROBE", LIST_DIAGNOSTIC_SECONDS)
            except Exception:
                return "KAKAO_AUTO_POPUP_TO_ACCOUNT_ORIGIN"
            if probe in ("READY", "OPENED") and download_page_path(page) == path:
                return "KAKAO_AUTO_POPUP_ACCOUNT_REDIRECT_WITH_VERIFIED_LIST"
            if _account_origin(page):
                return _ACCOUNT_REQUIRED
            return "KAKAO_AUTO_POPUP_TO_ACCOUNT_ORIGIN"
        # A return to the exact known list is useful evidence, never fallback authority.
        probe = await observe(path, "PROBE", LIST_DIAGNOSTIC_SECONDS)
        message = {
            "READY": "KAKAO_AUTO_POPUP_TO_LIST_TARGET_VERIFIED",
            "OPENED": "KAKAO_AUTO_POPUP_TO_LIST_ALREADY_OPEN",
        }.get(probe if isinstance(probe, str) else "")
        return message or _dom_failure(probe, "KAKAO_AUTO_POPUP_TO_LIST_TARGET_NOT_OBSERVED")

    state = await observe(destination, "CONFIRM" if direct else "PROBE", ROOM_LOAD_SECONDS)
    if state == "PAGE_MOVED":
        reason = await popup_rejection() if direct else rejection
        if reason == _ACCOUNT_REQUIRED:
            bound = command.command
            refusal = CaptureResult(
                execution=bound.execution,
                run_id=bound.run_id,
                source_binding_id=bound.source_binding_id,
                room_id=bound.room_id,
                command_sha256=sha256(canonical_bytes(bound.model_dump(mode="json"))),
                adapter_release_sha256=bound.adapter_release_sha256,
                capability_revision_id=bound.capability_revision_id,
                status="FAILED",
                error_code="AUTH_REQUIRED",
                report=None,
            ).model_dump(mode="json")
            validate_capture_contract("result", refusal)
            write_capture_receipt(outputs / ROOM_AUTH_REFUSAL_NAME, canonical_bytes(refusal))
        raise BrowserRuntimeError(reason)

    selected = page
    if not direct and state == "READY":
        popups: list[AutoRoomPage] = []

        def opened(candidate: AutoRoomPage) -> None:
            if len(popups) < 2:
                popups.append(candidate)

        page.on("popup", opened)
        try:
            state = await evaluate(page, path, "CLICK")
            if state == "TRIGGERED":
                state = "PENDING"
                loop = asyncio.get_running_loop()
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
        raise BrowserRuntimeError(
            _dom_failure(state, rejection if direct else "KAKAO_AUTO_ROOM_SELECTOR_UNVERIFIED")
        )
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
