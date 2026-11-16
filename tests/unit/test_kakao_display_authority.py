"""Ephemeral local-display credentials only; no live VNC, browser, or account."""

from __future__ import annotations

import asyncio
import os
import stat
import struct
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest
from eom_kakao_archive_collector import driver_setup as setup
from eom_kakao_archive_collector import manual_driver as driver
from eom_kakao_archive_collector.profile import BrowserRuntimeError
from eom_kakao_archive_contracts.kakao_remote import ProfileFence

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def authority(monkeypatch):
    with tempfile.TemporaryDirectory(prefix="kakao-xauth-test-", dir=ROOT / "staging") as name:
        local = Path(name)
        private = local / "private"
        private.mkdir(mode=0o700)
        password = local / "vnc.passwd"
        password.write_bytes(b"FAKEONLY")
        password.chmod(0o600)
        for key, path in (
            ("PRIVATE", private),
            ("XAUTHORITY", private / "Xauthority"),
            ("PASSWORD", password),
            ("VNC_SOCKET", local / "vnc.sock"),
            ("X_SOCKET", local / "X94"),
            ("X_LOCK", local / "X94-lock"),
        ):
            monkeypatch.setattr(setup, key, path)
        monkeypatch.setattr(setup, "require_supervisor", Mock())
        monkeypatch.setattr(setup.socket, "gethostname", lambda: "anonymous-test-host")
        yield local


def decode_authority(raw):
    assert struct.unpack_from("!H", raw)[0] == 256
    fields = []
    offset = 2
    for _ in range(4):
        length = struct.unpack_from("!H", raw, offset)[0]
        offset += 2
        fields.append(raw[offset : offset + length])
        offset += length
    assert offset == len(raw)
    assert fields[:3] == [b"anonymous-test-host", b"94", b"MIT-MAGIC-COOKIE-1"]
    assert len(fields[3]) == 16
    return fields[3]


def test_first_boot_and_restart_rotate_only_display_authority(authority, capsys):
    password_before = (setup.PASSWORD.read_bytes(), setup.PASSWORD.stat())
    assert setup.prepare_xauthority() is None
    first = setup.XAUTHORITY.read_bytes()
    first_cookie = decode_authority(first)
    first_inode = setup.XAUTHORITY.stat().st_ino
    assert stat.S_IMODE(setup.XAUTHORITY.stat().st_mode) == 0o600
    assert setup.XAUTHORITY.stat().st_nlink == 1
    assert setup.prepare_xauthority() is None
    second_cookie = decode_authority(setup.XAUTHORITY.read_bytes())
    assert first_cookie != second_cookie and setup.XAUTHORITY.stat().st_ino != first_inode
    assert not (setup.PRIVATE / ".Xauthority.next").exists()
    password_after = setup.PASSWORD.stat()
    assert setup.PASSWORD.read_bytes() == password_before[0]
    assert (password_after.st_ino, password_after.st_mtime_ns) == (
        password_before[1].st_ino,
        password_before[1].st_mtime_ns,
    )
    assert not capsys.readouterr().out
    exposed = repr((setup.child_environment(), setup.xvnc_argv())).encode()
    assert first_cookie not in exposed and second_cookie not in exposed
    assert (
        first_cookie.hex().encode() not in exposed and second_cookie.hex().encode() not in exposed
    )
    assert setup.require_supervisor.call_count == 4


def test_generated_binary_is_accepted_by_installed_xauth(authority):
    setup.prepare_xauthority()
    raw = setup.XAUTHORITY.read_bytes()
    cookie = decode_authority(raw)
    # The independent parser prints only into this local test's captured pipe.
    checked = subprocess.run(
        ["/usr/bin/xauth", "-f", str(setup.XAUTHORITY), "list"],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        check=False,
        timeout=5,
        env={"PATH": "/usr/bin:/bin", "LANG": "C"},
    )
    assert checked.returncode == 0 and not checked.stderr
    assert b"anonymous-test-host/unix:94" in checked.stdout
    assert b"MIT-MAGIC-COOKIE-1" in checked.stdout and cookie.hex().encode() in checked.stdout
    assert setup.XAUTHORITY.read_bytes() == raw


@pytest.mark.parametrize(
    "kind", ["symlink", "dangling", "hardlink", "directory", "fifo", "public", "empty"]
)
def test_unsafe_prior_target_is_preserved_without_new_cookie(authority, monkeypatch, kind):
    outside = authority / "outside"
    outside.write_bytes(b"unrelated content")
    outside.chmod(0o600)
    target = setup.XAUTHORITY
    if kind in {"symlink", "dangling"}:
        target.symlink_to(outside if kind == "symlink" else authority / "missing")
    elif kind == "hardlink":
        os.link(outside, target)
    elif kind == "directory":
        target.mkdir()
    elif kind == "fifo":
        os.mkfifo(target, 0o600)
    else:
        target.write_bytes(b"" if kind == "empty" else b"unsafe")
        target.chmod(0o644 if kind == "public" else 0o600)
    original = target.lstat()
    random = Mock()
    monkeypatch.setattr(setup.secrets, "token_bytes", random)
    with pytest.raises(BrowserRuntimeError, match="XAUTHORITY_UNSAFE"):
        setup.prepare_xauthority()
    random.assert_not_called()
    assert target.lstat() == original and outside.read_bytes() == b"unrelated content"
    assert not (setup.PRIVATE / ".Xauthority.next").exists()


@pytest.mark.parametrize("kind", ["file", "symlink", "directory"])
def test_previous_incomplete_temporary_is_not_removed_or_accepted(authority, kind):
    temporary = setup.PRIVATE / ".Xauthority.next"
    if kind == "file":
        temporary.write_bytes(b"old partial bytes")
    elif kind == "symlink":
        temporary.symlink_to(authority / "missing")
    else:
        temporary.mkdir()
    before = temporary.lstat()
    with pytest.raises(BrowserRuntimeError, match="XAUTHORITY_CREATE_FAILED"):
        setup.prepare_xauthority()
    assert temporary.lstat() == before and not setup.XAUTHORITY.exists()


@pytest.mark.parametrize("endpoint", ["VNC_SOCKET", "X_SOCKET", "X_LOCK"])
def test_old_display_endpoint_blocks_cookie_rotation(authority, endpoint):
    target = getattr(setup, endpoint)
    target.symlink_to(authority / "missing")
    with pytest.raises(BrowserRuntimeError, match="RECONCILE_REQUIRED"):
        setup.prepare_xauthority()
    assert target.is_symlink() and not setup.XAUTHORITY.exists()


def test_unsupervised_driver_never_creates_authority(authority, monkeypatch):
    monkeypatch.setattr(
        setup,
        "require_supervisor",
        Mock(side_effect=BrowserRuntimeError("KAKAO_BROWSER_SUPERVISION_UNCONFIRMED")),
    )
    with pytest.raises(BrowserRuntimeError, match="SUPERVISION_UNCONFIRMED"):
        setup.prepare_xauthority()
    assert not tuple(setup.PRIVATE.iterdir())


def test_replaced_private_directory_link_is_not_followed(authority):
    private = setup.PRIVATE
    private.rmdir()
    outside = authority / "outside-directory"
    outside.mkdir(mode=0o700)
    private.symlink_to(outside)
    with pytest.raises(OSError):
        setup.prepare_xauthority()
    assert not tuple(outside.iterdir())


def test_nonprivate_directory_is_rejected_before_generation(authority):
    setup.PRIVATE.chmod(0o750)
    with pytest.raises(BrowserRuntimeError, match="DIRECTORY_UNSAFE"):
        setup.prepare_xauthority()
    assert not tuple(setup.PRIVATE.iterdir())


@pytest.mark.parametrize("failure", ["write", "replace", "lost-supervisor"])
def test_failure_preserves_prior_authority_and_removes_only_own_partial(
    authority, monkeypatch, failure
):
    setup.prepare_xauthority()
    before = setup.XAUTHORITY.read_bytes()
    if failure == "write":
        monkeypatch.setattr(setup.os, "fsync", Mock(side_effect=OSError("synthetic disk failure")))
    elif failure == "replace":
        monkeypatch.setattr(
            setup.os, "replace", Mock(side_effect=OSError("synthetic replace failure"))
        )
    else:
        setup.require_supervisor.side_effect = [
            None,
            BrowserRuntimeError("KAKAO_BROWSER_SUPERVISION_UNCONFIRMED"),
        ]
    with pytest.raises(BrowserRuntimeError):
        setup.prepare_xauthority()
    assert setup.XAUTHORITY.read_bytes() == before
    assert not (setup.PRIVATE / ".Xauthority.next").exists()
    assert setup.PASSWORD.read_bytes() == b"FAKEONLY"


def test_authority_preparation_failure_cannot_start_browser_or_display(authority, monkeypatch):
    error = BrowserRuntimeError("KAKAO_BROWSER_XAUTHORITY_CREATE_FAILED")
    monkeypatch.setattr(setup, "prepare_xauthority", Mock(side_effect=error))
    playwright = AsyncMock()
    display = Mock()
    monkeypatch.setattr(driver, "_start_playwright", playwright)
    monkeypatch.setattr(driver, "_start_xvnc", display)
    fence = ProfileFence.model_validate(
        {
            "schema_version": "kakao-profile-fence/1.0",
            "profile_id": "kakaoprofile_" + "a" * 32,
            "browser_run_id": "kakaobrowserrun_" + "b" * 32,
            "fence_epoch": 1,
            "mode": "MANUAL",
        }
    )
    config = setup.ManualSetup(fence, "sha256:" + "a" * 64, "sha256:" + "b" * 64)
    with pytest.raises(BrowserRuntimeError, match="XAUTHORITY_CREATE_FAILED"):
        asyncio.run(driver.run_manual(config, asyncio.Event()))
    playwright.assert_not_called()
    display.assert_not_called()


def test_target_change_before_atomic_publish_is_preserved(authority, monkeypatch):
    setup.prepare_xauthority()
    replacement = setup.PRIVATE / "replacement"
    replacement.write_bytes(b"unrelated replacement")
    replacement.chmod(0o600)
    calls = 0

    def supervisor():
        nonlocal calls
        calls += 1
        if calls == 2:
            replacement.replace(setup.XAUTHORITY)

    monkeypatch.setattr(setup, "require_supervisor", supervisor)
    with pytest.raises(BrowserRuntimeError, match="XAUTHORITY_CHANGED"):
        setup.prepare_xauthority()
    assert setup.XAUTHORITY.read_bytes() == b"unrelated replacement"
    assert not (setup.PRIVATE / ".Xauthority.next").exists()


def test_substituted_temporary_is_not_deleted(authority, monkeypatch):
    original = setup.PRIVATE / "retained-own-temporary"
    temporary = setup.PRIVATE / ".Xauthority.next"
    calls = 0

    def supervisor():
        nonlocal calls
        calls += 1
        if calls == 2:
            temporary.replace(original)
            temporary.write_bytes(b"unrelated interrupted work")
            temporary.chmod(0o600)

    monkeypatch.setattr(setup, "require_supervisor", supervisor)
    with pytest.raises(BrowserRuntimeError, match="XAUTHORITY_CHANGED"):
        setup.prepare_xauthority()
    assert temporary.read_bytes() == b"unrelated interrupted work"
    assert not setup.XAUTHORITY.exists()
    decode_authority(original.read_bytes())


def test_secure_random_failure_is_secret_safe_and_has_no_partial_file(
    authority, monkeypatch, capsys
):
    monkeypatch.setattr(setup.secrets, "token_bytes", Mock(side_effect=OSError("no entropy")))
    monkeypatch.setattr(setup, "validate_setup", lambda *_: None)
    monkeypatch.setattr(
        driver, "_run", AsyncMock(side_effect=lambda *_: setup.prepare_xauthority())
    )
    monkeypatch.setattr(
        driver.sys, "argv", ["driver", "--request", "/private", "--profile", "/profile"]
    )
    assert driver.main() == 78
    printed = capsys.readouterr()
    assert not printed.out and printed.err == "KAKAO_BROWSER_MANUAL_UNAVAILABLE\n"
    assert not tuple(setup.PRIVATE.iterdir())
