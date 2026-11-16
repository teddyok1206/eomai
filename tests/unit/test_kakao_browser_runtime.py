"""OS/process gate tests. Privileged systemd/Chromium installation remains a separate gate."""

from __future__ import annotations

import ast
import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_kakao_archive_collector import profile, supervisor
from eom_kakao_archive_contracts.kakao_remote import ProfileFence
from eom_orchestrator import kakao_browser_runtime as runtime

ROOT = Path(__file__).resolve().parents[2]
OWNER = os.getuid()
ALLOWED = frozenset({0, OWNER})
DIGEST = "sha256:" + "b" * 64
BOOT = "12345678-1234-1234-1234-123456789abc"


@pytest.fixture
def safe_dir():
    # The adapter deliberately refuses /tmp's world-writable parent; anonymous fixtures
    # live beneath this user's protected workspace and are removed after each test.
    with tempfile.TemporaryDirectory(prefix="kakao-browser-test-", dir=ROOT / "staging") as name:
        yield Path(name)


def fence(mode="AUTO", epoch=1, run="1"):
    return ProfileFence.model_validate(
        {
            "schema_version": "kakao-profile-fence/1.0",
            "profile_id": "kakaoprofile_" + "a" * 32,
            "browser_run_id": "kakaobrowserrun_" + run * 32,
            "fence_epoch": epoch,
            "mode": mode,
        }
    )


def lock_file(root):
    path = root / "profile.lock"
    path.touch(mode=0o640)
    path.chmod(0o640)
    return path


def test_owner_readonly_fd_can_hold_exclusive_lock_without_write_permission(safe_dir):
    lock = lock_file(safe_dir)
    program = """
import errno,fcntl,os,sys,time
fd=os.open(sys.argv[1],os.O_RDONLY|os.O_NOFOLLOW)
assert fcntl.fcntl(fd,fcntl.F_GETFL)&os.O_ACCMODE==os.O_RDONLY
fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
try:
    os.write(fd,b'forbidden')
except OSError as error:
    assert error.errno==errno.EBADF
else:raise AssertionError('readonly fd wrote')
print('READ_ONLY_HELD',flush=True)
time.sleep(30)
"""
    child = subprocess.Popen(
        [sys.executable, "-c", program, str(lock)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert child.stdout.readline().strip() == "READ_ONLY_HELD"
        with (
            pytest.raises(profile.BrowserRuntimeError, match="PROFILE_BUSY"),
            profile.profile_lock(lock, uid=OWNER, parent_uids=ALLOWED, gid=os.getgid()),
        ):
            pytest.fail("read-only owner lock did not exclude browser")
    finally:
        child.terminate()
        child.wait(timeout=5)
    assert lock.read_bytes() == b""
    with profile.profile_lock(lock, uid=OWNER, parent_uids=ALLOWED, gid=os.getgid()):
        pass


def test_actual_profile_flock_excludes_second_process_and_releases_on_exit(safe_dir):
    lock = lock_file(safe_dir)
    program = """
import os,sys,time
from pathlib import Path
from eom_kakao_archive_collector.profile import profile_lock
with profile_lock(Path(sys.argv[1]),uid=os.getuid(),parent_uids=frozenset({0,os.getuid()})):
    print('HELD',flush=True)
    time.sleep(30)
"""
    child = subprocess.Popen(
        [sys.executable, "-c", program, str(lock)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert child.stdout.readline().strip() == "HELD"
        with (
            pytest.raises(profile.BrowserRuntimeError, match="PROFILE_BUSY"),
            profile.profile_lock(lock, uid=OWNER, parent_uids=ALLOWED),
        ):
            pytest.fail("entered a concurrently held profile")
    finally:
        child.terminate()
        child.wait(timeout=3)
    with profile.profile_lock(lock, uid=OWNER, parent_uids=ALLOWED):
        assert lock.exists() and lock.stat().st_size == 0


@pytest.mark.parametrize("bad", ["symlink", "hardlink", "public", "content", "fifo", "parent"])
def test_profile_lock_rejects_unsafe_installed_file_without_replacing(safe_dir, bad):
    lock = lock_file(safe_dir)
    if bad == "symlink":
        lock.unlink()
        other = safe_dir / "other"
        other.touch(mode=0o600)
        lock.symlink_to(other)
    elif bad == "hardlink":
        os.link(lock, safe_dir / "second")
    elif bad == "public":
        lock.chmod(0o644)
    elif bad == "content":
        lock.write_text("untrusted")
    elif bad == "fifo":
        lock.unlink()
        os.mkfifo(lock, mode=0o600)
    else:
        safe_dir.chmod(0o777)
    with (
        pytest.raises((profile.BrowserRuntimeError, OSError)),
        profile.profile_lock(lock, uid=OWNER, parent_uids=ALLOWED),
    ):
        pytest.fail("unsafe profile lock accepted")
    assert lock.lstat()


def test_real_supervisor_retains_lock_through_graceful_driver_shutdown(safe_dir):
    lock = lock_file(safe_dir)
    stopping = threading.Event()
    children = []
    events = []
    marker = safe_dir / "driver-ready"
    closed = safe_dir / "driver-flushed"
    program = (
        "import signal,time,sys;from pathlib import Path;"
        "signal.signal(signal.SIGTERM,"
        "lambda *_:(Path(sys.argv[2]).write_text('flushed'),sys.exit(0)));"
        "Path(sys.argv[1]).write_text('ready');time.sleep(30)"
    )

    def launch():
        child = subprocess.Popen(
            [sys.executable, "-c", program, str(marker), str(closed)],
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        children.append(child)
        return child

    def ready():
        deadline = time.monotonic() + 3
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert marker.exists()
        with (
            pytest.raises(profile.BrowserRuntimeError, match="PROFILE_BUSY"),
            profile.profile_lock(lock, uid=OWNER, parent_uids=ALLOWED),
        ):
            pass
        events.append("ready-with-lock")
        stopping.set()

    assert (
        supervisor.supervise(
            launch,
            lock_path=lock,
            uid=OWNER,
            parent_uids=ALLOWED,
            stopping=stopping,
            notify_ready=ready,
            grace_seconds=1,
        )
        == 0
    )
    assert children[0].poll() == 0 and closed.read_text() == "flushed"
    assert events == ["ready-with-lock"]
    with profile.profile_lock(lock, uid=OWNER, parent_uids=ALLOWED):
        pass


def test_real_supervisor_bounds_unresponsive_driver_stop(safe_dir):
    lock = lock_file(safe_dir)
    stopping = threading.Event()
    marker = safe_dir / "ready"
    children = []

    def launch():
        child = subprocess.Popen(
            [
                sys.executable,
                "-c",
                "import signal,time,sys;from pathlib import Path;"
                "signal.signal(signal.SIGTERM,signal.SIG_IGN);"
                "Path(sys.argv[1]).touch();time.sleep(30)",
                str(marker),
            ],
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        children.append(child)
        return child

    def ready():
        deadline = time.monotonic() + 3
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert marker.exists()
        stopping.set()

    started = time.monotonic()
    with pytest.raises(profile.BrowserRuntimeError, match="CHILD_STOP_FORCED"):
        supervisor.supervise(
            launch,
            lock_path=lock,
            uid=OWNER,
            parent_uids=ALLOWED,
            stopping=stopping,
            notify_ready=ready,
            grace_seconds=0.1,
        )
    assert children[0].returncode == -signal.SIGKILL
    assert time.monotonic() - started < 4


@pytest.mark.parametrize(
    "handler,expected",
    [("signal.signal(signal.SIGTERM,lambda *_:sys.exit(7));", 7), ("", "unclean")],
)
def test_stop_does_not_mask_failed_flush_or_default_signal(safe_dir, handler, expected):
    lock = lock_file(safe_dir)
    stopping = threading.Event()
    marker = safe_dir / "driver-started"
    children = []

    def launch():
        child = subprocess.Popen(
            [
                sys.executable,
                "-c",
                "import signal,time,sys;from pathlib import Path;"
                + handler
                + "Path(sys.argv[1]).touch();time.sleep(30)",
                str(marker),
            ],
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        children.append(child)
        return child

    def ready():
        deadline = time.monotonic() + 3
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert marker.exists()
        stopping.set()

    def run():
        return supervisor.supervise(
            launch,
            lock_path=lock,
            uid=OWNER,
            parent_uids=ALLOWED,
            stopping=stopping,
            notify_ready=ready,
            grace_seconds=1,
        )

    if expected == "unclean":
        with pytest.raises(profile.BrowserRuntimeError, match="STOP_UNCLEAN"):
            run()
        assert children[0].returncode == -signal.SIGTERM
    else:
        assert run() == expected == children[0].returncode
    with profile.profile_lock(lock, uid=OWNER, parent_uids=ALLOWED):
        pass


def test_lock_contention_never_launches_driver(safe_dir):
    lock = lock_file(safe_dir)
    launch = Mock()
    with (
        profile.profile_lock(lock, uid=OWNER, parent_uids=ALLOWED),
        pytest.raises(profile.BrowserRuntimeError, match="PROFILE_BUSY"),
    ):
        supervisor.supervise(
            launch,
            lock_path=lock,
            uid=OWNER,
            parent_uids=ALLOWED,
            stopping=threading.Event(),
            notify_ready=Mock(),
        )
    launch.assert_not_called()


def test_notify_failure_closes_original_child_and_releases_lock(safe_dir):
    lock = lock_file(safe_dir)
    child = subprocess.Popen(
        [sys.executable, "-c", "import time;time.sleep(30)"], start_new_session=True
    )
    with pytest.raises(ValueError, match="notify unavailable"):
        supervisor.supervise(
            lambda: child,
            lock_path=lock,
            uid=OWNER,
            parent_uids=ALLOWED,
            stopping=threading.Event(),
            notify_ready=Mock(side_effect=ValueError("notify unavailable")),
            grace_seconds=0.1,
        )
    assert child.poll() is not None
    with profile.profile_lock(lock, uid=OWNER, parent_uids=ALLOWED):
        pass


def observed(**changes):
    values = {key: "" for key in runtime.PROPERTIES}
    values.update(
        {
            "LoadState": "loaded",
            "FragmentPath": str(runtime.TEMPLATE),
            "DropInPaths": "",
            "NeedDaemonReload": "no",
            "User": "eom-kakao",
            "Group": "eom-kakao",
            "Type": "notify",
            "NotifyAccess": "main",
            "KillMode": "mixed",
            "Restart": "no",
            "ActiveState": "active",
            "SubState": "running",
            "MainPID": "1234",
            "ControlPID": "0",
            "ExecMainPID": "1234",
            "ExecMainStartTimestampMonotonic": "123456",
            "InvocationID": "c" * 32,
            "ControlGroup": runtime.CGROUP,
            "StatusText": "KAKAO_BROWSER_STARTED:" + DIGEST,
            "Result": "success",
            "ExecMainCode": "1",
            "ExecMainStatus": "0",
        }
    )
    values.update(changes)
    return values


def inactive(**changes):
    return observed(ActiveState="inactive", SubState="dead", MainPID="0", **changes)


def new_observation():
    return observed(InvocationID="d" * 32, ExecMainStartTimestampMonotonic="223456")


def handle():
    return runtime.BrowserRunHandle(fence(), DIGEST, BOOT, "c" * 32, 1234, 123456, runtime.CGROUP)


@pytest.fixture
def gate(monkeypatch):
    monkeypatch.setattr(runtime, "_control_lock", lambda: nullcontext())
    monkeypatch.setattr(runtime, "_boot_id", lambda: BOOT)
    monkeypatch.setattr(runtime.FixedKakaoBrowserRuntime, "_installed", lambda self: None)
    monkeypatch.setattr(runtime.FixedKakaoBrowserRuntime, "_request", lambda self, value: DIGEST)
    monkeypatch.setattr(runtime, "_stage", lambda value, *, first: DIGEST)
    monkeypatch.setattr(runtime, "_has_history", lambda: False)
    monkeypatch.setattr(runtime, "_cgroup_closed", lambda: "EMPTY")
    return runtime.FixedKakaoBrowserRuntime(DIGEST, DIGEST)


def test_fixed_start_requires_prior_exact_stop_and_fresh_current_claim(gate, monkeypatch):
    next_fence = fence("MANUAL", 2, "2")
    current = Mock()
    run = Mock(return_value=subprocess.CompletedProcess([], 0))
    monkeypatch.setattr(runtime.subprocess, "run", run)
    monkeypatch.setattr(runtime, "_show", Mock(side_effect=[inactive(), new_observation()]))
    result = gate.start(next_fence, prior=handle(), assert_current=current)
    assert result.fence == next_fence and result.invocation_id == "d" * 32
    current.assert_called_once_with(next_fence)
    assert run.call_count == 1
    assert run.call_args.args[0] == [
        "/usr/bin/systemctl",
        "--no-ask-password",
        "start",
        runtime.UNIT,
    ]


@pytest.mark.parametrize(
    "bad",
    [
        {"MainPID": "22"},
        {"ControlPID": "22"},
        {"Job": "1472"},
        {"ActiveState": "active"},
        {"InvocationID": "d" * 32},
        {"ExecMainPID": "22"},
        {"ExecMainStartTimestampMonotonic": "44"},
        {"ControlGroup": "/system.slice/other.service"},
        {"StatusText": "KAKAO_BROWSER_STARTED:sha256:" + "c" * 64},
        {"FragmentPath": "/tmp/eom-kakao-browser.service"},
        {"DropInPaths": "/tmp/extra.conf"},
        {"NeedDaemonReload": "yes"},
        {"User": "root"},
        {"Restart": "always"},
    ],
)
def test_wrong_or_still_active_prior_never_starts_new_process(gate, monkeypatch, bad):
    monkeypatch.setattr(runtime, "_show", lambda: {**inactive(), **bad})
    run = Mock()
    monkeypatch.setattr(runtime.subprocess, "run", run)
    with pytest.raises(runtime.KakaoBrowserRuntimeError):
        gate.start(fence("MANUAL", 2, "2"), prior=handle(), assert_current=Mock())
    run.assert_not_called()


def test_lease_expiry_cannot_replace_live_cgroup(gate, monkeypatch):
    monkeypatch.setattr(runtime, "_show", lambda: inactive())
    monkeypatch.setattr(
        runtime,
        "_cgroup_closed",
        Mock(side_effect=runtime.KakaoBrowserRuntimeError("KAKAO_BROWSER_CGROUP_NOT_CLOSED")),
    )
    run = Mock()
    monkeypatch.setattr(runtime.subprocess, "run", run)
    with pytest.raises(runtime.KakaoBrowserRuntimeError, match="CGROUP_NOT_CLOSED"):
        gate.start(fence("MANUAL", 2, "2"), prior=handle(), assert_current=Mock())
    run.assert_not_called()


def test_start_timeout_is_observed_not_retried(gate, monkeypatch):
    monkeypatch.setattr(runtime, "_show", Mock(side_effect=[inactive(), new_observation()]))
    run = Mock(side_effect=subprocess.TimeoutExpired("systemctl", 20))
    monkeypatch.setattr(runtime.subprocess, "run", run)
    next_fence = fence("MANUAL", 2, "2")
    with pytest.raises(runtime.KakaoBrowserRuntimeError, match="START_UNCERTAIN"):
        gate.start(next_fence, prior=handle(), assert_current=Mock())
    assert gate.observe_run(next_fence).fence == next_fence
    assert run.call_count == 1


def test_stop_timeout_only_succeeds_after_actual_closure(gate, monkeypatch):
    run = Mock(side_effect=subprocess.TimeoutExpired("systemctl", 35))
    monkeypatch.setattr(runtime.subprocess, "run", run)
    monkeypatch.setattr(runtime, "_show", Mock(side_effect=[observed(), inactive()]))
    stopped = gate.stop(handle())
    assert stopped.cgroup_state == "EMPTY" and stopped.observed_at.utcoffset().total_seconds() == 0
    assert run.call_count == 1
    monkeypatch.setattr(runtime, "_show", lambda: observed())
    with pytest.raises(runtime.KakaoBrowserRuntimeError, match="STOP_UNCONFIRMED"):
        gate.stop(handle())
    assert run.call_count == 2


def test_foreign_invocation_cannot_be_stopped(gate, monkeypatch):
    monkeypatch.setattr(runtime, "_show", lambda: observed(InvocationID="d" * 32))
    run = Mock()
    monkeypatch.setattr(runtime.subprocess, "run", run)
    with pytest.raises(runtime.KakaoBrowserRuntimeError, match="RUN_MISMATCH"):
        gate.stop(handle())
    run.assert_not_called()


def test_reboot_requires_reconcile_not_stale_pid_acceptance(gate, monkeypatch):
    monkeypatch.setattr(runtime, "_boot_id", lambda: "abcdefab-1234-1234-1234-123456789abc")
    monkeypatch.setattr(runtime, "_show", lambda: inactive())
    with pytest.raises(runtime.KakaoBrowserRuntimeError, match="RUN_MISMATCH"):
        gate.observe_stopped(handle())


def test_unconfirmed_dispatch_recovers_exact_running_handle_without_launch(gate, monkeypatch):
    monkeypatch.setattr(runtime, "_show", lambda: observed())
    run = Mock()
    monkeypatch.setattr(runtime.subprocess, "run", run)
    result = gate.observe_dispatch(fence(), command_sha256=DIGEST, dispatched_boot_id=BOOT)
    assert result == handle()
    assert gate.boot_identity() == BOOT
    run.assert_not_called()


@pytest.mark.parametrize("reboot", [False, True])
def test_pre_ready_failure_and_reboot_are_closed_not_successful(gate, monkeypatch, reboot):
    monkeypatch.setattr(
        runtime,
        "_show",
        lambda: inactive(StatusText="", Result="exit-code", ExecMainStatus="78"),
    )
    if reboot:
        monkeypatch.setattr(runtime, "_boot_id", lambda: "abcdefab-1234-1234-1234-123456789abc")
    run, stage = Mock(), Mock()
    monkeypatch.setattr(runtime.subprocess, "run", run)
    monkeypatch.setattr(runtime, "_stage", stage)
    result = gate.observe_dispatch(fence(), command_sha256=DIGEST, dispatched_boot_id=BOOT)
    assert isinstance(result, runtime.ClosedBrowserDispatch)
    assert result.reason == ("REBOOT_UNCLEAN" if reboot else "START_NOT_CONFIRMED")
    assert result.unit_result == "exit-code" and result.main_exit_status == 78
    assert result.dispatched_boot_id == BOOT and result.cgroup_state == "EMPTY"
    stage.assert_not_called()
    run.assert_not_called()


@pytest.mark.parametrize(
    "bad",
    [
        {"MainPID": "44"},
        {"ControlPID": "44"},
        {"Job": "1472"},
        {"ActiveState": "activating", "SubState": "start"},
        {"ControlGroup": "/system.slice/foreign.service"},
        {"InvocationID": "invalid"},
        {"NeedDaemonReload": "yes"},
        {"FragmentPath": "/tmp/untrusted.service"},
    ],
)
def test_pending_dispatch_never_turns_unknown_or_live_process_into_closed(gate, monkeypatch, bad):
    monkeypatch.setattr(runtime, "_show", lambda: {**inactive(StatusText=""), **bad})
    run = Mock()
    monkeypatch.setattr(runtime.subprocess, "run", run)
    with pytest.raises(runtime.KakaoBrowserRuntimeError):
        gate.observe_dispatch(fence(), command_sha256=DIGEST, dispatched_boot_id=BOOT)
    run.assert_not_called()


def test_pending_dispatch_requires_matching_input_hash_and_empty_cgroup(gate, monkeypatch):
    monkeypatch.setattr(runtime, "_show", lambda: inactive(StatusText=""))
    with pytest.raises(runtime.KakaoBrowserRuntimeError, match="FENCE_MISMATCH"):
        gate.observe_dispatch(fence(), command_sha256="sha256:" + "0" * 64, dispatched_boot_id=BOOT)
    with pytest.raises(runtime.KakaoBrowserRuntimeError, match="FENCE_MISMATCH"):
        gate.observe_dispatch(fence(), command_sha256=DIGEST, dispatched_boot_id="invalid")
    monkeypatch.setattr(
        runtime,
        "_cgroup_closed",
        Mock(side_effect=runtime.KakaoBrowserRuntimeError("KAKAO_BROWSER_CGROUP_NOT_CLOSED")),
    )
    with pytest.raises(runtime.KakaoBrowserRuntimeError, match="CGROUP_NOT_CLOSED"):
        gate.observe_dispatch(fence(), command_sha256=DIGEST, dispatched_boot_id=BOOT)


def test_pre_ready_closure_allows_only_fresh_claim_and_reobserved_successor(gate, monkeypatch):
    monkeypatch.setattr(runtime, "_show", lambda: inactive(StatusText=""))
    prior = gate.observe_dispatch(fence(), command_sha256=DIGEST, dispatched_boot_id=BOOT)
    assert isinstance(prior, runtime.ClosedBrowserDispatch)
    start = Mock(return_value=subprocess.CompletedProcess([], 0))
    monkeypatch.setattr(runtime.subprocess, "run", start)
    monkeypatch.setattr(
        runtime, "_show", Mock(side_effect=[inactive(StatusText=""), new_observation()])
    )
    stage = Mock(return_value=DIGEST)
    monkeypatch.setattr(runtime, "_stage", stage)
    current = Mock()
    next_fence = fence("MANUAL", 2, "2")
    assert gate.start(next_fence, prior=prior, assert_current=current).fence == next_fence
    current.assert_called_once_with(next_fence)
    stage.assert_called_once_with(next_fence, first=False)
    assert start.call_count == 1
    assert prior.reason == "START_NOT_CONFIRMED"
    # A past closure observation never substitutes for a fresh physical check.
    monkeypatch.setattr(runtime, "_show", lambda: observed())
    with pytest.raises(runtime.KakaoBrowserRuntimeError, match="STOP_UNCONFIRMED"):
        gate.start(next_fence, prior=prior, assert_current=Mock())
    assert start.call_count == 1


def test_reboot_cannot_adopt_another_running_invocation(gate, monkeypatch):
    monkeypatch.setattr(runtime, "_show", lambda: observed())
    monkeypatch.setattr(runtime, "_boot_id", lambda: "abcdefab-1234-1234-1234-123456789abc")
    with pytest.raises(runtime.KakaoBrowserRuntimeError, match="RUN_MISMATCH"):
        gate.observe_dispatch(fence(), command_sha256=DIGEST, dispatched_boot_id=BOOT)


@pytest.mark.parametrize("history", [False, True])
def test_idle_inventory_reports_history_without_authorizing_or_repairing(
    gate, monkeypatch, history
):
    monkeypatch.setattr(
        runtime,
        "_show",
        lambda: inactive(
            ExecMainPID="0", ExecMainStartTimestampMonotonic="0", InvocationID="", StatusText=""
        ),
    )
    monkeypatch.setattr(runtime, "_has_history", lambda: history)
    run, stage = Mock(), Mock()
    monkeypatch.setattr(runtime.subprocess, "run", run)
    monkeypatch.setattr(runtime, "_stage", stage)
    result = gate.observe_idle()
    assert result.unit == runtime.UNIT and result.boot_id == BOOT
    assert result.never_dispatched is (not history) and result.cgroup_state == "EMPTY"
    run.assert_not_called()
    stage.assert_not_called()


@pytest.mark.parametrize(
    "change",
    [
        {"Job": "9"},
        {"MainPID": "9"},
        {"ControlPID": "9"},
        {"ActiveState": "failed", "SubState": "failed"},
        {"ActiveState": "active", "SubState": "running"},
        {"ControlGroup": "/other"},
    ],
)
def test_idle_inventory_needs_actual_quiescence(gate, monkeypatch, change):
    monkeypatch.setattr(runtime, "_show", lambda: {**inactive(), **change})
    with pytest.raises(runtime.KakaoBrowserRuntimeError, match="IDLE_UNCONFIRMED"):
        gate.observe_idle()


@pytest.mark.parametrize("case", ["missing", "duplicate", "unknown", "bad-pid", "huge"])
def test_systemd_observation_is_bounded_closed_and_unambiguous(case):
    values = observed()
    if case == "missing":
        values.pop("ControlPID")
    if case == "bad-pid":
        values["MainPID"] = "-1"
    raw = "\n".join(f"{key}={value}" for key, value in values.items()).encode()
    if case == "duplicate":
        raw += b"\nMainPID=1234"
    if case == "unknown":
        raw += b"\nprivateContent=must-not-appear"
    if case == "huge":
        raw += b"x" * 17000
    with pytest.raises(runtime.KakaoBrowserRuntimeError, match="OBSERVATION_INVALID"):
        runtime._parse_show(raw)


@pytest.mark.parametrize(
    "events,expected",
    [
        ("populated 0\nfrozen 0\n", "EMPTY"),
        ("populated 1\nfrozen 0\n", None),
        ("populated 0\npopulated 1\n", None),
        ("frozen 0\n", None),
    ],
)
def test_actual_cgroup_event_file_read_is_not_main_pid_only(
    safe_dir, monkeypatch, events, expected
):
    root = safe_dir / "cgroup"
    target = root / runtime.CGROUP.lstrip("/")
    root.mkdir(mode=0o700)
    target.parent.mkdir(mode=0o700)
    target.mkdir(mode=0o700)
    (target / "cgroup.events").write_text(events)
    monkeypatch.setattr(runtime, "CGROUP_ROOT", root)
    original = runtime._directory
    monkeypatch.setattr(runtime, "_directory", lambda path, **kw: original(path, owners=ALLOWED))
    if expected:
        assert runtime._cgroup_closed() == expected
    else:
        with pytest.raises(runtime.KakaoBrowserRuntimeError, match="CGROUP_NOT_CLOSED"):
            runtime._cgroup_closed()


def test_missing_events_is_not_disappeared_cgroup(safe_dir, monkeypatch):
    root = safe_dir / "cgroup"
    target = root / runtime.CGROUP.lstrip("/")
    root.mkdir(mode=0o700)
    target.parent.mkdir(mode=0o700)
    target.mkdir(mode=0o700)
    monkeypatch.setattr(runtime, "CGROUP_ROOT", root)
    original = runtime._directory
    monkeypatch.setattr(runtime, "_directory", lambda path, **kw: original(path, owners=ALLOWED))
    with pytest.raises(runtime.KakaoBrowserRuntimeError, match="CGROUP_UNKNOWN"):
        runtime._cgroup_closed()
    target.rmdir()
    assert runtime._cgroup_closed() == "ABSENT"
    target.parent.rmdir()
    with pytest.raises(FileNotFoundError):
        runtime._cgroup_closed()


@pytest.mark.parametrize("extra", ["--profile", "../../auth", "https://private.example", "AUTO"])
def test_fixed_cli_does_not_accept_paths_authority_or_log_arguments(extra):
    result = subprocess.run(
        [sys.executable, "-m", "eom_kakao_archive_collector.supervisor", extra],
        capture_output=True,
        check=False,
        timeout=10,
    )
    assert result.returncode == 78 and not result.stdout
    assert result.stderr == b"KAKAO_BROWSER_FIXED_INPUT_REQUIRED\n"


def test_driver_missing_is_explicit_unavailable_not_fake_browser_success(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["supervisor"])
    monkeypatch.setattr(supervisor.signal, "signal", Mock())
    monkeypatch.setattr(
        supervisor, "_prepare", Mock(side_effect=FileNotFoundError("private/secret"))
    )
    assert supervisor.main() == 78
    captured = capsys.readouterr()
    assert captured.out == "" and captured.err == "KAKAO_BROWSER_RUNTIME_UNAVAILABLE\n"


def test_unit_is_single_mode_fixed_private_lifetime_and_no_restart():
    text = (ROOT / "infra/systemd/eom-kakao-browser.service").read_text()
    for expected in [
        "Type=notify",
        "NotifyAccess=main",
        "Restart=no",
        "KillMode=mixed",
        "User=eom-kakao",
        "Group=eom-kakao",
        "NoNewPrivileges=yes",
        "PrivateTmp=yes",
        "ProtectSystem=strict",
        "ProtectHome=yes",
        "ProtectControlGroups=yes",
        "TimeoutStartSec=15",
        "TimeoutStopSec=30",
        "RuntimeDirectoryMode=0700",
        "RuntimeDirectoryPreserve=yes",
        "LimitCORE=0",
        "MemoryMax=2G",
        "CPUQuota=200%",
        "-I -B -m eom_kakao_archive_collector.supervisor",
        "InaccessiblePaths=/mnt/nas",
    ]:
        assert expected in text
    assert "%i" not in text and "no-sandbox" not in text and "SecurityTypes None" not in text
    assert "PrivateNetwork=yes" not in text


def test_collector_is_optional_and_has_no_core_pdf_or_persistence_imports():
    for source in (ROOT / "services/kakao_archive_collector/eom_kakao_archive_collector").glob(
        "*.py"
    ):
        tree = ast.parse(source.read_text())
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name.split(".")[0] for alias in node.names)
            if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                imports.append(node.module.split(".")[0])
        assert not set(imports) & {
            "sqlalchemy",
            "psycopg",
            "fitz",
            "pymupdf",
            "PIL",
            "eom_orchestrator",
            "eom_catalog_service",
            "requests",
            "httpx",
        }


def test_first_use_cannot_ignore_existing_durable_history(gate, monkeypatch):
    monkeypatch.setattr(runtime, "_has_history", lambda: True)
    monkeypatch.setattr(runtime, "_show", lambda: inactive(ExecMainStartTimestampMonotonic="0"))
    run = Mock()
    monkeypatch.setattr(runtime.subprocess, "run", run)
    with pytest.raises(runtime.KakaoBrowserRuntimeError, match="PRIOR_RUN_REQUIRED"):
        gate.start(fence(), prior=None, assert_current=Mock())
    run.assert_not_called()


@pytest.mark.parametrize("operation", ["first-start", "closed", "running", "prior-start"])
def test_scheduled_systemd_job_blocks_adoption_and_replacement(gate, monkeypatch, operation):
    # A start waiting for network-online may have no PID/cgroup yet. It still owns
    # the staged input; replacing that input would let the old job run a new fence.
    monkeypatch.setattr(runtime, "_show", lambda: inactive(StatusText=""))
    prior = gate.observe_dispatch(fence(), command_sha256=DIGEST, dispatched_boot_id=BOOT)
    pending = (
        observed(Job="1472")
        if operation == "running"
        else inactive(Job="1472", ExecMainStartTimestampMonotonic="0")
    )
    monkeypatch.setattr(runtime, "_show", lambda: pending)
    run, stage = Mock(), Mock()
    monkeypatch.setattr(runtime.subprocess, "run", run)
    monkeypatch.setattr(runtime, "_stage", stage)
    with pytest.raises(runtime.KakaoBrowserRuntimeError):
        if operation == "first-start":
            gate.start(fence(), prior=None, assert_current=Mock())
        elif operation == "closed":
            gate.observe_dispatch(fence(), command_sha256=DIGEST, dispatched_boot_id=BOOT)
        elif operation == "running":
            gate.observe_run(fence())
        else:
            gate.start(fence("MANUAL", 2, "2"), prior=prior, assert_current=Mock())
    run.assert_not_called()
    stage.assert_not_called()


def test_revoked_current_authority_prevents_staging_or_start(gate, monkeypatch):
    monkeypatch.setattr(runtime, "_show", lambda: inactive())
    stage = Mock()
    run = Mock()
    monkeypatch.setattr(runtime, "_stage", stage)
    monkeypatch.setattr(runtime.subprocess, "run", run)
    with pytest.raises(ValueError, match="revoked"):
        gate.start(
            fence("MANUAL", 2, "2"),
            prior=handle(),
            assert_current=Mock(side_effect=ValueError("revoked")),
        )
    stage.assert_not_called()
    run.assert_not_called()


@pytest.mark.parametrize(
    "bad", [fence("PAUSING"), fence("MANUAL", 1, "2"), fence("MANUAL", 2, "1")]
)
def test_unstartable_mode_same_run_or_nonincreasing_fence_cannot_launch(gate, monkeypatch, bad):
    monkeypatch.setattr(runtime, "_show", lambda: inactive())
    run = Mock()
    monkeypatch.setattr(runtime.subprocess, "run", run)
    with pytest.raises(runtime.KakaoBrowserRuntimeError):
        gate.start(bad, prior=handle(), assert_current=Mock())
    run.assert_not_called()


def test_fresh_start_cannot_mistake_original_invocation_for_new(gate, monkeypatch):
    monkeypatch.setattr(runtime, "_show", Mock(side_effect=[inactive(), observed()]))
    monkeypatch.setattr(
        runtime.subprocess, "run", Mock(return_value=subprocess.CompletedProcess([], 0))
    )
    with pytest.raises(runtime.KakaoBrowserRuntimeError, match="START_UNCONFIRMED"):
        gate.start(fence("MANUAL", 2, "2"), prior=handle(), assert_current=Mock())


def test_actual_staging_preserves_prior_and_replay_never_overwrites(safe_dir, monkeypatch):
    monkeypatch.setattr(runtime, "REQUEST", safe_dir / "request.json")
    monkeypatch.setattr(runtime.pwd, "getpwnam", lambda name: SimpleNamespace(pw_uid=OWNER))
    assert not runtime._has_history()
    first = fence()
    digest = runtime._stage(first, first=True)
    assert runtime._has_history()
    first_bytes = (safe_dir / f"{first.browser_run_id}.json").read_bytes()
    assert runtime._digest(first_bytes) == digest
    assert json.loads(first_bytes) == first.model_dump(mode="json")
    next_fence = fence("MANUAL", 2, "2")
    next_digest = runtime._stage(next_fence, first=False)
    assert next_digest != digest
    assert (safe_dir / f"{first.browser_run_id}.json").read_bytes() == first_bytes
    assert (safe_dir / "initialized.json").read_bytes() == first_bytes
    current = (safe_dir / "request.json").read_bytes()
    assert json.loads(current) == next_fence.model_dump(mode="json")
    with pytest.raises(runtime.KakaoBrowserRuntimeError, match="ALREADY_STAGED"):
        runtime._stage(next_fence, first=False)
    assert (safe_dir / "request.json").read_bytes() == current
    gate = runtime.FixedKakaoBrowserRuntime(DIGEST, DIGEST)
    assert gate._request(next_fence) == next_digest
    with pytest.raises(runtime.KakaoBrowserRuntimeError, match="FENCE_MISMATCH"):
        gate._request(first)


def test_staging_interrupt_preserves_marker_without_claiming_first_use_again(safe_dir, monkeypatch):
    monkeypatch.setattr(runtime, "REQUEST", safe_dir / "request.json")
    monkeypatch.setattr(runtime.pwd, "getpwnam", lambda name: SimpleNamespace(pw_uid=OWNER))
    monkeypatch.setattr(
        runtime.os, "rename", Mock(side_effect=OSError("simulated interrupted publish"))
    )
    with pytest.raises(OSError):
        runtime._stage(fence(), first=True)
    assert runtime._has_history()
    assert not (safe_dir / "request.json").exists()
    assert (safe_dir / f"{fence().browser_run_id}.json").exists()


@pytest.mark.parametrize("case", ["hash", "oversize", "symlink", "authority"])
def test_actual_protected_request_and_driver_validation(safe_dir, monkeypatch, case):
    profile_dir = safe_dir / "profile"
    private = safe_dir / "private"
    profile_dir.mkdir(mode=0o700)
    private.mkdir(mode=0o700)
    request = safe_dir / "request.json"
    request.write_text(json.dumps(fence().model_dump(mode="json")))
    request.chmod(0o640)
    driver = safe_dir / "driver"
    driver.write_text("#!/bin/sh\nexit 1\n")
    driver.chmod(0o750)
    env = safe_dir / "driver.env"
    env.write_text(f"EOM_KAKAO_BROWSER_DRIVER_SHA256={runtime._digest(driver.read_bytes())}\n")
    env.chmod(0o640)
    for name, value in (
        ("PROFILE", profile_dir),
        ("PRIVATE", private),
        ("REQUEST", request),
        ("DRIVER", driver),
        ("DRIVER_ENV", env),
    ):
        monkeypatch.setattr(supervisor, name, value)
    monkeypatch.setattr(
        supervisor.pwd, "getpwnam", lambda name: SimpleNamespace(pw_uid=OWNER, pw_gid=os.getgid())
    )
    original = supervisor.read_protected
    monkeypatch.setattr(
        supervisor,
        "read_protected",
        lambda path, **kw: original(path, uid=OWNER, limit=kw["limit"], allowed_uids=ALLOWED),
    )
    if case == "hash":
        env.write_text("EOM_KAKAO_BROWSER_DRIVER_SHA256=sha256:" + "a" * 64 + "\n")
    elif case == "oversize":
        request.write_bytes(b"x" * 4097)
    elif case == "symlink":
        request.unlink()
        request.symlink_to(driver)
    else:
        value = fence().model_dump(mode="json")
        value["is_admin"] = True
        request.write_text(json.dumps(value))
    with pytest.raises((ValueError, OSError)):
        supervisor._prepare()
    assert list(private.iterdir()) == []
