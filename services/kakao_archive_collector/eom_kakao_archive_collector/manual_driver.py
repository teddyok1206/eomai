"""MANUAL-only headed browser. No collection, selectors or persistent credential changes."""

from __future__ import annotations

import asyncio
import grp
import importlib
import importlib.metadata
import os
import signal
import socket
import stat
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Protocol, cast

from . import driver_setup as setup
from .manual_download import ManualDownloads, Page
from .profile import BrowserRuntimeError

START_SECONDS = 10.0
CLOSE_SECONDS = 8.0
PLAYWRIGHT_STOP_SECONDS = 2.0
XVNC_STOP_SECONDS = 3.0


class BrowserContext(Protocol):
    @property
    def pages(self) -> list[Page]: ...
    def on(self, event: str, callback: Callable[..., None]) -> None: ...
    async def close(self) -> None: ...


class BrowserType(Protocol):
    @property
    def executable_path(self) -> str: ...
    async def launch_persistent_context(
        self,
        user_data_dir: str,
        *,
        headless: bool,
        chromium_sandbox: bool,
        accept_downloads: bool,
        downloads_path: str,
        timeout: float,
        env: dict[str, str],
        handle_sigterm: bool,
        handle_sigint: bool,
        handle_sighup: bool,
        no_viewport: bool,
    ) -> BrowserContext: ...


class Playwright(Protocol):
    @property
    def chromium(self) -> BrowserType: ...
    async def stop(self) -> None: ...


class PlaywrightStarter(Protocol):
    async def start(self) -> Playwright: ...


async def _start_playwright() -> Playwright:
    if importlib.metadata.version("playwright") != setup.PLAYWRIGHT_VERSION:
        raise BrowserRuntimeError("KAKAO_BROWSER_PLAYWRIGHT_RELEASE_MISMATCH")
    # This process is dedicated and starts no unrelated work. Pin registry selection before
    # starting Playwright's transport; do not inherit arbitrary cache or debug environment.
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(setup.BROWSER_ROOT)
    module = importlib.import_module("playwright.async_api")
    starter = cast(PlaywrightStarter, module.async_playwright())
    return await asyncio.wait_for(starter.start(), timeout=START_SECONDS)


def _start_xvnc() -> subprocess.Popen[bytes]:
    return subprocess.Popen(
        setup.xvnc_argv(),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=setup.child_environment(),
        cwd=setup.PRIVATE,
        close_fds=True,
    )


async def _wait_xvnc(child: subprocess.Popen[bytes], stopping: asyncio.Event) -> None:
    deadline = asyncio.get_running_loop().time() + START_SECONDS
    while asyncio.get_running_loop().time() < deadline:
        if stopping.is_set():
            raise BrowserRuntimeError("KAKAO_BROWSER_START_CANCELLED")
        if child.poll() is not None:
            raise BrowserRuntimeError("KAKAO_BROWSER_XVNC_EXITED")
        try:
            metadata = setup.VNC_SOCKET.lstat()
        except FileNotFoundError:
            await asyncio.sleep(0.05)
            continue
        if (
            not stat.S_ISSOCK(metadata.st_mode)
            or metadata.st_uid != os.geteuid()
            or metadata.st_gid != grp.getgrnam("eom-kakao-vnc").gr_gid
            or stat.S_IMODE(metadata.st_mode) != 0o660
        ):
            raise BrowserRuntimeError("KAKAO_BROWSER_VNC_SOCKET_UNSAFE")
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(0.25)
            connection.connect(str(setup.VNC_SOCKET))
        # RFB listens before Xvnc finishes X11 initialization. Wait for an actual
        # authenticated X display; otherwise a crashing display looks ready to Chromium.
        if await _display_ready():
            if child.poll() is not None:
                raise BrowserRuntimeError("KAKAO_BROWSER_XVNC_EXITED")
            return
        await asyncio.sleep(0.05)
    raise BrowserRuntimeError("KAKAO_BROWSER_XVNC_NOT_READY")


async def _display_ready() -> bool:
    child = await asyncio.create_subprocess_exec(
        str(setup.XDPYINFO),
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
        env=setup.child_environment(),
    )
    try:
        await asyncio.wait_for(child.wait(), timeout=0.5)
    except BaseException:
        if child.returncode is None:
            child.kill()
        await child.wait()
        raise
    return child.returncode == 0


async def _stop_xvnc(child: subprocess.Popen[bytes]) -> None:
    observed = child.poll()
    if observed is not None:
        # An unexpected even-zero server exit is not a valid live display to hand off.
        raise BrowserRuntimeError("KAKAO_BROWSER_XVNC_EXITED")
    child.terminate()
    try:
        result = await asyncio.to_thread(child.wait, timeout=XVNC_STOP_SECONDS)
    except subprocess.TimeoutExpired:
        child.kill()
        await asyncio.to_thread(child.wait, timeout=1)
        raise BrowserRuntimeError("KAKAO_BROWSER_XVNC_STOP_FORCED") from None
    if result != 0:
        raise BrowserRuntimeError("KAKAO_BROWSER_XVNC_STOP_UNCLEAN")


async def run_manual(config: setup.ManualSetup, stopping: asyncio.Event) -> None:
    if config.fence.mode != "MANUAL":
        raise BrowserRuntimeError("KAKAO_BROWSER_AUTO_UNAVAILABLE")
    if stopping.is_set():
        raise BrowserRuntimeError("KAKAO_BROWSER_START_CANCELLED")
    child: subprocess.Popen[bytes] | None = None
    playwright: Playwright | None = None
    context: BrowserContext | None = None
    downloads: ManualDownloads | None = None
    closed = asyncio.Event()
    failure: BaseException | None = None
    try:
        setup.require_supervisor()
        setup.prepare_xauthority()
        playwright = await _start_playwright()
        setup.require_chromium(Path(playwright.chromium.executable_path), config.chromium_sha256)
        if stopping.is_set():
            raise BrowserRuntimeError("KAKAO_BROWSER_START_CANCELLED")
        child = _start_xvnc()
        await _wait_xvnc(child, stopping)
        if stopping.is_set():
            raise BrowserRuntimeError("KAKAO_BROWSER_START_CANCELLED")
        setup.require_supervisor()
        downloads = ManualDownloads(config.fence)
        opened = await asyncio.wait_for(
            playwright.chromium.launch_persistent_context(
                str(setup.PROFILE),
                headless=False,
                chromium_sandbox=True,
                accept_downloads=True,
                downloads_path=str(downloads.incoming),
                timeout=START_SECONDS * 1000,
                env=setup.child_environment(),
                handle_sigterm=False,
                handle_sigint=False,
                handle_sighup=False,
                no_viewport=True,
            ),
            timeout=START_SECONDS + 1,
        )
        context = opened
        opened.on("page", downloads.subscribe)
        for page in opened.pages:
            downloads.subscribe(page)
        opened.on("close", lambda *_: closed.set())
        while not stopping.is_set():
            if child.poll() is not None:
                raise BrowserRuntimeError("KAKAO_BROWSER_XVNC_EXITED")
            if closed.is_set():
                raise BrowserRuntimeError("KAKAO_BROWSER_CONTEXT_CLOSED")
            downloads.observe_incoming()
            if downloads.failure is not None:
                raise downloads.failure
            try:
                await asyncio.wait_for(stopping.wait(), timeout=0.1)
            except TimeoutError:
                continue
    except BaseException as error:
        failure = error
    finally:
        # Record incomplete transfers before context close removes SDK temp files.
        if downloads is not None:
            try:
                await downloads.close()
                if downloads.failure is not None:
                    failure = failure or downloads.failure
            except Exception:
                failure = failure or BrowserRuntimeError("KAKAO_BROWSER_DOWNLOAD_STOP_FAILED")
        # Do not close the display before the browser can flush its persistent profile.
        if context is not None:
            try:
                await asyncio.wait_for(context.close(), timeout=CLOSE_SECONDS)
            except Exception:
                failure = failure or BrowserRuntimeError("KAKAO_BROWSER_CONTEXT_CLOSE_FAILED")
        if playwright is not None:
            try:
                await asyncio.wait_for(playwright.stop(), timeout=PLAYWRIGHT_STOP_SECONDS)
            except Exception:
                failure = failure or BrowserRuntimeError("KAKAO_BROWSER_TRANSPORT_STOP_FAILED")
        if child is not None:
            try:
                await _stop_xvnc(child)
            except Exception:
                failure = failure or BrowserRuntimeError("KAKAO_BROWSER_XVNC_STOP_FAILED")
    if failure is not None:
        raise failure


async def _run(config: setup.ManualSetup) -> None:
    stopping = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(signum, stopping.set)
    await run_manual(config, stopping)


def main() -> int:
    if len(sys.argv) != 5 or sys.argv[1] != "--request" or sys.argv[3] != "--profile":
        print("KAKAO_BROWSER_FIXED_INPUT_REQUIRED", file=sys.stderr)
        return 78
    try:
        config = setup.validate_setup(Path(sys.argv[2]), Path(sys.argv[4]))
        asyncio.run(_run(config))
        return 0
    except BrowserRuntimeError as error:
        print(error.code, file=sys.stderr)
        return 78
    except Exception:
        print("KAKAO_BROWSER_MANUAL_UNAVAILABLE", file=sys.stderr)
        return 78


if __name__ == "__main__":
    raise SystemExit(main())
