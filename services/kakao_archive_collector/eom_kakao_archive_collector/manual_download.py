"""Receive authorized manual browser downloads into local staging, never NAS or DB.

This adapter registers no click/keyboard code and asserts no provider-room identity.
The Catalog owner must separately validate the run fence and actual source association.
"""

from __future__ import annotations

import asyncio
import os
import stat
from collections.abc import Callable
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from eom_kakao_archive_contracts.kakao_remote import ProfileFence
from eom_kakao_archive_contracts.manual_download import (
    ManualDownloadMember,
    ManualDownloadResult,
    ManualDownloadStart,
)
from eom_kakao_archive_contracts.manual_observation import ManualDownloadTarget
from eom_kakao_archive_contracts.render import canonical_bytes

from .download_origins import DownloadRequestOrigins
from .manual_capture_files import commit_download_payload
from .manual_capture_files import create_capture_directory as _directory
from .manual_capture_files import write_capture_receipt as _write_once
from .manual_observation import ReadOnlyPage, download_page_path, observe_download_page
from .profile import BrowserRuntimeError, protected_directory, read_protected

ROOT = Path("/var/lib/eom-kakao/downloads")
MAX_FILES = 16
MAX_FILE_BYTES = 32 * 1024 * 1024
MAX_TOTAL_BYTES = 128 * 1024 * 1024
DOWNLOAD_SECONDS = 60.0
STOP_SECONDS = 3.0


class Download(Protocol):
    @property
    def url(self) -> str: ...
    @property
    def suggested_filename(self) -> str: ...
    async def path(self) -> Path | None: ...
    async def cancel(self) -> None: ...


class Page(ReadOnlyPage, Protocol):
    def on(self, event: str, callback: Callable[..., None]) -> None: ...


def _copy_payload(source: Path, directory: Path, incoming: Path) -> ManualDownloadMember:
    member = commit_download_payload(
        source, incoming=incoming, destination=directory / "payload.bin", limit=MAX_FILE_BYTES
    )
    return ManualDownloadMember(size_bytes=member.size_bytes, sha256=member.sha256)


class ManualDownloads:
    """One actual run: bounded page subscriptions and at most16 retained event identities."""

    def __init__(self, fence: ProfileFence, *, root: Path = ROOT) -> None:
        if fence.mode != "MANUAL":
            raise BrowserRuntimeError("KAKAO_BROWSER_DOWNLOAD_MODE_INVALID")
        with protected_directory(root, allowed_uids=frozenset({0, os.geteuid()})) as fd:
            info = os.fstat(fd)
            if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o2750:
                raise BrowserRuntimeError("KAKAO_BROWSER_DOWNLOAD_STAGING_UNSAFE")
        self._fence = fence
        self.run = root / fence.browser_run_id
        _directory(self.run)
        marker = self.run / "run.json"
        raw = canonical_bytes(fence.model_dump(mode="json"))
        try:
            _write_once(marker, raw)
        except FileExistsError:
            if (
                read_protected(
                    marker,
                    uid=os.geteuid(),
                    limit=4096,
                    allowed_uids=frozenset({0, os.geteuid()}),
                    required_mode=0o640,
                )
                != raw
            ):
                raise BrowserRuntimeError("KAKAO_BROWSER_DOWNLOAD_FENCE_STALE") from None
        self.incoming = self.run / ".incoming"
        _directory(self.incoming, private=True)
        self._pages: dict[int, Page] = {}
        self._events: dict[int, Download] = {}
        self._tasks: set[asyncio.Task[None]] = set()
        self._origins = DownloadRequestOrigins()
        self._closing = False
        self.failure: BrowserRuntimeError | None = None
        self._count, self._bytes = 0, 0
        # A resumed driver never forgets retained captures or regains a fresh run budget.
        for path in self.run.iterdir():
            if path.name.startswith("kakaodownload_"):
                self._count += 1
                result = path / "result.json"
                if result.is_file() and not result.is_symlink():
                    record = ManualDownloadResult.model_validate_json(
                        read_protected(
                            result,
                            uid=os.geteuid(),
                            limit=16384,
                            allowed_uids=frozenset({0, os.geteuid()}),
                            required_mode=0o640,
                        )
                    )
                    self._bytes += record.member.size_bytes if record.member else 0

    def subscribe(self, page: Page) -> None:
        if id(page) in self._pages:
            return
        if len(self._pages) >= 64:
            self.failure = BrowserRuntimeError("KAKAO_BROWSER_DOWNLOAD_PAGE_LIMIT")
            return
        self._pages[id(page)] = page
        page_id = "kakaopage_" + uuid4().hex
        page.on(
            "request",
            lambda request: (
                None
                if self._closing
                else self._origins.observe(page_id, request, page_path=download_page_path(page))
            ),
        )
        page.on("download", lambda download: self.receive(download, page_id, page=page))

    def receive(self, download: Download, page_id: str, *, page: Page | None = None) -> None:
        if id(download) in self._events:
            return
        if self._closing or self._count >= MAX_FILES:
            self.failure = BrowserRuntimeError("KAKAO_BROWSER_DOWNLOAD_LIMIT")
            return  # The driver closes its accepting context, cancelling any unhandled event.
        self._events[id(download)] = download
        self._count += 1
        started = ManualDownloadStart(
            capture_id="kakaodownload_" + uuid4().hex,
            page_instance_id=page_id,
            profile_id=self._fence.profile_id,
            browser_run_id=self._fence.browser_run_id,
            fence_epoch=self._fence.fence_epoch,
            started_at=datetime.now(UTC),
        )
        directory = self.run / started.capture_id
        try:
            _directory(directory)
            _write_once(
                directory / "started.json", canonical_bytes(started.model_dump(mode="json"))
            )
        except Exception:
            self.failure = BrowserRuntimeError("KAKAO_BROWSER_DOWNLOAD_RECEIPT_FAILED")
            return
        event_path = download_page_path(page) if page is not None else None
        try:
            download_url = download.url if page is not None else ""
        except Exception:
            download_url = ""
        if not isinstance(download_url, str):
            download_url = ""
        request_target = (
            self._origins.consume(page_id, download_url, page_path=event_path)
            if page is not None
            else None
        )
        task = asyncio.create_task(
            self._receive(
                download,
                started,
                directory,
                page=page,
                event_path=event_path,
                request_target=request_target,
                download_url=download_url,
            )
        )
        self._tasks.add(task)
        task.add_done_callback(self._done)

    def _done(self, task: asyncio.Task[None]) -> None:
        self._tasks.discard(task)
        if task.cancelled() or task.exception() is not None:
            self.failure = BrowserRuntimeError("KAKAO_BROWSER_DOWNLOAD_RECEIPT_FAILED")

    async def _receive(
        self,
        download: Download,
        started: ManualDownloadStart,
        directory: Path,
        *,
        page: Page | None,
        event_path: str | None,
        download_url: str,
        request_target: ManualDownloadTarget | None = None,
    ) -> None:
        member, error, name = None, None, None
        try:
            if page is not None:
                observation = await observe_download_page(
                    page,
                    started,
                    download_url=download_url,
                    event_path=event_path,
                    request_target=request_target,
                )
                _write_once(
                    directory / "page-observation.json",
                    canonical_bytes(observation.model_dump(mode="json", by_alias=True)),
                )
            raw_name = download.suggested_filename
            if not isinstance(raw_name, str) or not 1 <= len(raw_name) <= 1024:
                raise BrowserRuntimeError("DOWNLOAD_FILE_INVALID")
            name = raw_name
            path = await asyncio.wait_for(download.path(), timeout=DOWNLOAD_SECONDS)
            if path is None:
                raise BrowserRuntimeError("DOWNLOAD_FAILED")
            size = path.lstat().st_size
            if self._bytes + size > MAX_TOTAL_BYTES:
                raise BrowserRuntimeError("DOWNLOAD_LIMIT")
            # The small bounded streaming input boundary is synchronous: accepted-byte
            # accounting cannot race another coroutine between copy and reservation.
            member = _copy_payload(path, directory, self.incoming)
            self._bytes += member.size_bytes
        except TimeoutError:
            error = "DOWNLOAD_TIMEOUT"
        except asyncio.CancelledError:
            error = "DOWNLOAD_CANCELLED"
        except BrowserRuntimeError as failure:
            error = failure.code
        except Exception:
            error = "DOWNLOAD_FAILED"
        if error is not None:
            # Context close still cancels/reaps the SDK transfer if cancel fails.
            with suppress(Exception):
                await asyncio.wait_for(download.cancel(), timeout=1.0)
        result = ManualDownloadResult.model_validate(
            {
                **started.model_dump(mode="json"),
                "phase": "RECEIVED" if member else "FAILED",
                "completed_at": datetime.now(UTC),
                "suggested_filename": name,
                "member": member,
                "error_code": error,
            }
        )
        _write_once(directory / "result.json", canonical_bytes(result.model_dump(mode="json")))

    def observe_incoming(self) -> None:
        size = 0
        for count, entry in enumerate(self.incoming.iterdir(), 1):
            info = entry.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_nlink != 1:
                self.failure = BrowserRuntimeError("KAKAO_BROWSER_DOWNLOAD_FILE_INVALID")
                break
            size += info.st_size
            if count > MAX_FILES * 2 or info.st_size > MAX_FILE_BYTES or size > MAX_TOTAL_BYTES:
                self.failure = BrowserRuntimeError("KAKAO_BROWSER_DOWNLOAD_LIMIT")
                break

    async def close(self) -> None:
        self._closing = True
        self._origins.clear()
        # An event can arrive immediately before shutdown. Let each reserved task
        # enter its cancellation handler so STARTED is not stranded by cancel-before-start.
        await asyncio.sleep(0)
        tasks = tuple(self._tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.wait_for(asyncio.gather(*tasks), timeout=STOP_SECONDS)
