"""Bounded local download receipts and bytes; synthetic inputs, no live account/profile."""

import asyncio
import json
import os
import tempfile
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from eom_kakao_archive_collector import manual_download as adapter
from eom_kakao_archive_collector.profile import BrowserRuntimeError
from eom_kakao_archive_contracts.manual_download import (
    SCHEMA_SHA256,
    ManualDownloadResult,
    ManualDownloadStart,
)
from eom_kakao_archive_contracts.render import sha256

from tests.unit.test_kakao_manual_browser_driver import fence


@contextmanager
def download_root():
    # These ancestors satisfy the actual protected_directory checks. No patched
    # path validator or permissive /tmp traversal stands in for the file boundary.
    with tempfile.TemporaryDirectory(
        prefix="eom-kakao-download-", dir=Path.home() / ".cache"
    ) as name:
        root = Path(name)
        root.chmod(0o2750)
        yield root


def results(manager):
    return [
        ManualDownloadResult.model_validate_json(path.read_bytes())
        for path in sorted(manager.run.glob("kakaodownload_*/result.json"))
    ]


async def drain(manager):
    tasks = tuple(manager._tasks)
    if tasks:
        await asyncio.gather(*tasks)
    await asyncio.sleep(0)


def transfer(manager, raw=b"DATE,USER,MESSAGE\n", *, filename="same.csv"):
    path = manager.incoming / ("incoming-" + os.urandom(8).hex())
    path.write_bytes(raw)
    path.chmod(0o600)
    return SimpleNamespace(
        suggested_filename=filename, path=AsyncMock(return_value=path), cancel=AsyncMock()
    )


def test_contract_canonical_mirror_hash_and_strict_metadata():
    root = Path(__file__).resolve().parents[2]
    path = "manual-download-v1.schema.json"
    raw = (root / "schemas/kakao-archive" / path).read_bytes()
    assert sha256(raw) == SCHEMA_SHA256
    assert (
        raw
        == (
            root / "packages/kakao_archive_contracts/eom_kakao_archive_contracts/schemas" / path
        ).read_bytes()
    )
    now = datetime.now(UTC)
    value = ManualDownloadStart(
        capture_id="kakaodownload_" + "1" * 32,
        profile_id=fence().profile_id,
        browser_run_id=fence().browser_run_id,
        fence_epoch=1,
        page_instance_id="kakaopage_" + "2" * 32,
        started_at=now,
    )
    for change in (
        {"room_id": "kakaoroom_" + "3" * 32},
        {"source_url": "https://private/?token=secret"},
        {"fence_epoch": True},
        {"started_at": now.replace(tzinfo=None)},
    ):
        with pytest.raises(ValueError):
            ManualDownloadStart.model_validate(value.model_dump() | change)
    result = value.model_dump() | dict(
        phase="FAILED",
        completed_at=now,
        member=None,
        suggested_filename=None,
        error_code="DOWNLOAD_FAILED",
    )
    assert ManualDownloadResult.model_validate(result)
    for change in (
        {"completed_at": now - timedelta(seconds=1)},
        {"phase": "RECEIVED"},
        {"error_code": "private arbitrary exception"},
        {"error_code": None},
    ):
        with pytest.raises(ValueError):
            ManualDownloadResult.model_validate(result | change)


def test_same_download_event_is_once_but_same_filename_does_not_deduplicate():
    async def run(root):
        manager = adapter.ManualDownloads(fence(), root=root)
        one = transfer(manager, b"first", filename="../../same.csv")
        page = "kakaopage_" + "4" * 32
        manager.receive(one, page)
        manager.receive(one, page)
        manager.receive(transfer(manager, b"second", filename="../../same.csv"), page)
        await drain(manager)
        receipts = results(manager)
        assert len(receipts) == 2 and all(r.phase == "RECEIVED" for r in receipts)
        assert {r.member.sha256 for r in receipts} == {sha256(b"first"), sha256(b"second")}
        assert all(r.suggested_filename == "../../same.csv" for r in receipts)
        for result in receipts:
            directory = manager.run / result.capture_id
            start = ManualDownloadStart.model_validate_json(
                (directory / "started.json").read_bytes()
            )
            assert start.phase == "STARTED" and result.started_at == start.started_at
            content = (directory / "payload.bin").read_bytes()
            assert sha256(content) == result.member.sha256
            assert (directory / "payload.bin").stat().st_mode & 0o777 == 0o640
            assert directory.stat().st_mode & 0o7777 == 0o750
            assert directory.stat().st_gid == root.stat().st_gid
            assert (directory / "payload.bin").stat().st_gid == root.stat().st_gid
        await manager.close()
        restarted = adapter.ManualDownloads(fence(), root=root)
        assert restarted._count == 2 and restarted._bytes == len(b"firstsecond")
        assert len(results(restarted)) == 2
        await restarted.close()

    with download_root() as root:
        asyncio.run(run(root))


@pytest.mark.parametrize(
    "fault,code",
    [
        ("empty", "DOWNLOAD_EMPTY"),
        ("timeout", "DOWNLOAD_TIMEOUT"),
        ("exception", "DOWNLOAD_FAILED"),
        ("missing", "DOWNLOAD_FAILED"),
        ("oversize", "DOWNLOAD_LIMIT"),
        ("outside", "DOWNLOAD_FILE_INVALID"),
        ("symlink", "DOWNLOAD_FAILED"),
        ("name", "DOWNLOAD_FILE_INVALID"),
    ],
)
def test_bad_or_incomplete_downloads_remain_failed_without_a_published_member(
    monkeypatch, fault, code
):
    async def run(root):
        manager = adapter.ManualDownloads(fence(), root=root)
        item = transfer(manager)
        path = await item.path()
        if fault == "empty":
            path.write_bytes(b"")
        elif fault == "timeout":
            item.path.side_effect = TimeoutError()
        elif fault == "exception":
            item.path.side_effect = RuntimeError("never log private url token")
        elif fault == "missing":
            item.path.return_value = None
        elif fault == "oversize":
            monkeypatch.setattr(adapter, "MAX_FILE_BYTES", 2)
        elif fault == "outside":
            outside = root / "not-incoming"
            outside.write_bytes(b"not allowed")
            item.path.return_value = outside
        elif fault == "symlink":
            linked = manager.incoming / "symbolic-link"
            linked.symlink_to(path)
            item.path.return_value = linked
        else:
            item.suggested_filename = "x" * 1025
        manager.receive(item, "kakaopage_" + "4" * 32)
        await drain(manager)
        (receipt,) = results(manager)
        assert receipt.phase == "FAILED" and receipt.error_code == code and receipt.member is None
        assert item.cancel.await_count == 1
        assert "private url" not in json.dumps(receipt.model_dump(mode="json"))
        assert not (manager.run / receipt.capture_id / "payload.bin").exists()
        await manager.close()

    with download_root() as root:
        asyncio.run(run(root))


def test_shutdown_cancels_running_transfer_and_keeps_start_and_terminal_records():
    async def run(root):
        manager = adapter.ManualDownloads(fence(), root=root)
        ready = asyncio.Event()

        async def wait():
            ready.set()
            await asyncio.Event().wait()

        item = SimpleNamespace(suggested_filename="pending.csv", path=wait, cancel=AsyncMock())
        manager.receive(item, "kakaopage_" + "4" * 32)
        await ready.wait()
        await manager.close()
        (receipt,) = results(manager)
        assert receipt.error_code == "DOWNLOAD_CANCELLED" and receipt.member is None
        assert (manager.run / receipt.capture_id / "started.json").is_file()
        assert manager.failure is None and item.cancel.await_count == 1

    with download_root() as root:
        asyncio.run(run(root))


def test_immediate_shutdown_does_not_strand_unstarted_reserved_task():
    async def run(root):
        manager = adapter.ManualDownloads(fence(), root=root)
        item = SimpleNamespace(
            suggested_filename="pending.csv", path=AsyncMock(), cancel=AsyncMock()
        )

        async def wait():
            await asyncio.Event().wait()

        item.path.side_effect = wait
        manager.receive(item, "kakaopage_" + "4" * 32)
        await manager.close()
        (receipt,) = results(manager)
        assert receipt.error_code == "DOWNLOAD_CANCELLED" and receipt.member is None
        assert manager.failure is None

    with download_root() as root:
        asyncio.run(run(root))


def test_page_subscriptions_and_byte_file_count_limits(monkeypatch):
    async def run(root):
        manager = adapter.ManualDownloads(fence(), root=root)
        callbacks = {}
        page = SimpleNamespace(on=lambda name, fn: callbacks.setdefault(name, []).append(fn))
        manager.subscribe(page)
        manager.subscribe(page)
        assert len(callbacks["download"]) == 1
        monkeypatch.setattr(adapter, "MAX_TOTAL_BYTES", 2)
        manager.receive(transfer(manager, b"abc"), "kakaopage_" + "4" * 32)
        await drain(manager)
        assert results(manager)[0].error_code == "DOWNLOAD_LIMIT"
        monkeypatch.setattr(adapter, "MAX_FILES", 1)
        manager.receive(transfer(manager, b"a"), "kakaopage_" + "4" * 32)
        assert manager.failure.code == "KAKAO_BROWSER_DOWNLOAD_LIMIT"
        assert len(results(manager)) == 1
        manager.failure = None
        manager.observe_incoming()
        assert manager.failure.code == "KAKAO_BROWSER_DOWNLOAD_LIMIT"
        manager.failure = None
        await manager.close()

    with download_root() as root:
        asyncio.run(run(root))


def test_path_permissions_fence_and_no_overwrite(monkeypatch):
    with download_root() as root:
        with pytest.raises(BrowserRuntimeError, match="MODE_INVALID"):
            adapter.ManualDownloads(fence("AUTO"), root=root)
        manager = adapter.ManualDownloads(fence(), root=root)
        with pytest.raises(BrowserRuntimeError, match="FENCE_STALE"):
            adapter.ManualDownloads(fence().model_copy(update={"fence_epoch": 2}), root=root)
        with pytest.raises(FileExistsError):
            adapter._write_once(manager.run / "run.json", b"replacement")
        assert json.loads((manager.run / "run.json").read_bytes())["fence_epoch"] == 1
        root.chmod(0o2770)
        with pytest.raises(BrowserRuntimeError, match="UNSAFE"):
            adapter.ManualDownloads(fence(), root=root)
