"""Real local file validation only; no browser/profile/NAS/DB or live identities."""

from __future__ import annotations

import json
import os
import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from eom_kakao_archive_contracts.kakao_remote import ProfileFence
from eom_kakao_archive_contracts.manual_download import ManualDownloadStart
from eom_kakao_archive_contracts.render import canonical_bytes, sha256
from eom_orchestrator import kakao_runtime_os as runtime_os
from eom_orchestrator.kakao_download_inputs import (
    KakaoDownloadInputError,
    read_received_kakao_download,
)


@pytest.fixture
def received():
    with tempfile.TemporaryDirectory(
        prefix="kakao-owner-input-", dir=Path.home() / ".cache"
    ) as folder:
        root = Path(folder)
        root.chmod(0o2750)
        fence = ProfileFence.model_validate(
            dict(
                schema_version="kakao-profile-fence/1.0",
                profile_id="kakaoprofile_" + "a" * 32,
                browser_run_id="kakaobrowserrun_" + "b" * 32,
                fence_epoch=1,
                mode="MANUAL",
            )
        )
        capture_id = "kakaodownload_" + "c" * 32
        run = root / fence.browser_run_id
        run.mkdir()
        run.chmod(0o750)
        capture = run / capture_id
        capture.mkdir()
        capture.chmod(0o750)
        started = ManualDownloadStart(
            capture_id=capture_id,
            profile_id=fence.profile_id,
            browser_run_id=fence.browser_run_id,
            fence_epoch=1,
            page_instance_id="kakaopage_" + "d" * 32,
            started_at=datetime.now(UTC),
        )
        raw = b"untrusted synthetic photo or CSV bytes"
        result = started.model_dump(mode="json") | dict(
            phase="RECEIVED",
            completed_at=(started.started_at + timedelta(seconds=1)).isoformat(),
            suggested_filename="../../private-original-name.csv",
            member=dict(relative_path="payload.bin", size_bytes=len(raw), sha256=sha256(raw)),
            error_code=None,
        )
        files = {
            run / "run.json": canonical_bytes(fence.model_dump(mode="json")),
            capture / "started.json": canonical_bytes(started.model_dump(mode="json")),
            capture / "result.json": canonical_bytes(result),
            capture / "payload.bin": raw,
        }
        for path, value in files.items():
            path.write_bytes(value)
            path.chmod(0o640)
        arguments = dict(
            root=root,
            fence=fence,
            capture_id=capture_id,
            worker_uid=os.getuid(),
            control_gid=os.getgid(),
        )
        yield arguments, run, capture, raw


def edit(path, change):
    value = json.loads(path.read_bytes())
    change(value)
    path.write_bytes(canonical_bytes(value))


def test_received_after_browser_stop_is_read_only_repeatable_and_private(received):
    arguments, run, capture, raw = received
    before = {p: p.read_bytes() for p in run.rglob("*") if p.is_file()}
    one = read_received_kakao_download(**arguments)
    two = read_received_kakao_download(**arguments)
    assert one == two and one.payload == raw
    assert one.receipt.capture_id == arguments["capture_id"]
    assert one.receipt.suggested_filename == "../../private-original-name.csv"
    assert raw.decode() not in repr(one) and "private-original-name" not in repr(one)
    assert {p: p.read_bytes() for p in run.rglob("*") if p.is_file()} == before
    assert set(capture.iterdir()) == set(before) - {run / "run.json"}


@pytest.mark.parametrize(
    "field,value",
    [
        ("capture_id", "../outside"),
        ("capture_id", "kakaodownload_" + "a" * 32 + "/other"),
        ("capture_id", None),
        ("worker_uid", True),
        ("control_gid", -1),
    ],
)
def test_untrusted_identity_rejected_before_filesystem(received, field, value):
    arguments, *_ = received
    with pytest.raises(KakaoDownloadInputError, match="INPUT_INVALID"):
        read_received_kakao_download(**(arguments | {field: value}))


@pytest.mark.parametrize(
    "field,value",
    [
        ("profile_id", "kakaoprofile_" + "e" * 32),
        ("fence_epoch", 2),
        ("mode", "AUTO"),
    ],
)
def test_exact_run_fence_no_implicit_latest(received, field, value):
    arguments, *_ = received
    changed = arguments["fence"].model_copy(update={field: value})
    with pytest.raises(KakaoDownloadInputError, match=r"FENCE_STALE|INPUT_INVALID"):
        read_received_kakao_download(**(arguments | {"fence": changed}))


@pytest.mark.parametrize("which", ["run", "started.json", "result.json", "payload.bin"])
def test_missing_boundary_is_explicit_not_redownload(received, which):
    arguments, run, capture, _ = received
    target = run / "run.json" if which == "run" else capture / which
    target.unlink()
    with pytest.raises(KakaoDownloadInputError, match="INPUT_MISSING"):
        read_received_kakao_download(**arguments)


@pytest.mark.parametrize("which", ["run", "capture", "payload.bin", "result.json"])
def test_symlinked_path_rejected(received, which):
    arguments, run, capture, _ = received
    target = run if which == "run" else capture if which == "capture" else capture / which
    moved = target.with_name(target.name + "-retained")
    target.rename(moved)
    target.symlink_to(moved, target_is_directory=moved.is_dir())
    with pytest.raises(KakaoDownloadInputError, match="STAGING_UNSAFE"):
        read_received_kakao_download(**arguments)


@pytest.mark.parametrize(
    "which,mode",
    [
        ("root", 0o750),
        ("run", 0o770),
        ("capture", 0o755),
        ("result.json", 0o644),
        ("payload.bin", 0o600),
        ("payload.bin", 0o666),
    ],
)
def test_exact_installed_permissions_are_required(received, which, mode):
    arguments, run, capture, _ = received
    target = {"root": arguments["root"], "run": run, "capture": capture}.get(which, capture / which)
    target.chmod(mode)
    with pytest.raises(KakaoDownloadInputError, match="STAGING_UNSAFE"):
        read_received_kakao_download(**arguments)


def test_wrong_control_group_and_worker_owner_rejected(received):
    arguments, *_ = received
    for field in ("worker_uid", "control_gid"):
        with pytest.raises(KakaoDownloadInputError, match="STAGING_UNSAFE"):
            read_received_kakao_download(**(arguments | {field: arguments[field] + 1}))


@pytest.mark.parametrize(
    "field,value",
    [
        ("capture_id", "kakaodownload_" + "e" * 32),
        ("profile_id", "kakaoprofile_" + "e" * 32),
        ("browser_run_id", "kakaobrowserrun_" + "e" * 32),
        ("fence_epoch", 2),
        ("page_instance_id", "kakaopage_" + "e" * 32),
    ],
)
def test_terminal_receipt_cannot_switch_initial_identity(received, field, value):
    arguments, _, capture, _ = received
    edit(capture / "result.json", lambda result: result.update({field: value}))
    with pytest.raises(KakaoDownloadInputError, match="RECEIPT_INVALID"):
        read_received_kakao_download(**arguments)


def test_started_and_terminal_cannot_jointly_claim_a_different_capture(received):
    arguments, _, capture, _ = received
    for name in ("started.json", "result.json"):
        edit(capture / name, lambda result: result.update(capture_id="kakaodownload_" + "e" * 32))
    with pytest.raises(KakaoDownloadInputError, match="FENCE_STALE"):
        read_received_kakao_download(**arguments)


@pytest.mark.parametrize(
    "change",
    [
        lambda value: value.update(extra="private"),
        lambda value: value.update(member=value["member"] | {"relative_path": "../../outside"}),
        lambda value: value.update(member=value["member"] | {"size_bytes": 33 * 1024 * 1024}),
        lambda value: value.update(completed_at="2000-01-01T00:00:00Z"),
    ],
)
def test_invalid_receipt_no_payload_or_filename_disclosure(received, change):
    arguments, _, capture, _ = received
    edit(capture / "result.json", change)
    with pytest.raises(KakaoDownloadInputError, match="RECEIPT_INVALID") as error:
        read_received_kakao_download(**arguments)
    assert "private" not in str(error.value)


def test_failed_download_is_never_reinterpreted_or_retried(received):
    arguments, _, capture, _ = received
    edit(
        capture / "result.json",
        lambda value: value.update(phase="FAILED", member=None, error_code="DOWNLOAD_TIMEOUT"),
    )
    before = (capture / "result.json").read_bytes()
    with pytest.raises(KakaoDownloadInputError, match="NOT_RECEIVED"):
        read_received_kakao_download(**arguments)
    assert (capture / "result.json").read_bytes() == before


def test_same_size_hash_tamper_rejected(received):
    arguments, _, capture, raw = received
    (capture / "payload.bin").write_bytes(b"x" * len(raw))
    with pytest.raises(KakaoDownloadInputError, match="MEMBER_HASH_MISMATCH"):
        read_received_kakao_download(**arguments)


def test_hardlink_and_fifo_are_not_download_members(received):
    arguments, _, capture, _ = received
    payload = capture / "payload.bin"
    duplicate = capture / "extra.bin"
    os.link(payload, duplicate)
    with pytest.raises(KakaoDownloadInputError, match="STAGING_UNSAFE"):
        read_received_kakao_download(**arguments)
    duplicate.unlink()
    payload.unlink()
    os.mkfifo(payload, mode=0o640)
    with pytest.raises(KakaoDownloadInputError, match="STAGING_UNSAFE"):
        read_received_kakao_download(**arguments)


def test_mutation_during_actual_fd_read_is_rejected(received, monkeypatch):
    arguments, _, capture, _ = received
    payload = capture / "payload.bin"
    inode, calls = payload.stat().st_ino, 0
    original = runtime_os.os.fstat

    def fstat(fd):
        nonlocal calls
        info = original(fd)
        if info.st_ino == inode:
            calls += 1
            if calls == 2:
                with payload.open("ab") as stream:
                    stream.write(b"changed")
                info = original(fd)
        return info

    monkeypatch.setattr(runtime_os.os, "fstat", fstat)
    with pytest.raises(KakaoDownloadInputError, match="STAGING_UNSAFE"):
        read_received_kakao_download(**arguments)


def test_two_consumers_reuse_same_transfer_without_any_write(received):
    arguments, run, _, raw = received
    before = {p: p.read_bytes() for p in run.rglob("*") if p.is_file()}
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(read_received_kakao_download, **arguments) for _ in range(2)]
        outputs = [future.result() for future in futures]
    assert outputs[0] == outputs[1] and outputs[0].payload == raw
    assert {p: p.read_bytes() for p in run.rglob("*") if p.is_file()} == before
