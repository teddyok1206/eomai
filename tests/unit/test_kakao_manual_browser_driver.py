"""Anonymous subprocess and launcher tests; no installed browser, Kakao access or real secret."""

from __future__ import annotations

import asyncio
import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from eom_kakao_archive_collector import driver_setup as setup
from eom_kakao_archive_collector import manual_driver as driver
from eom_kakao_archive_collector import supervisor
from eom_kakao_archive_collector.profile import BrowserRuntimeError
from eom_kakao_archive_contracts.kakao_remote import ProfileFence

ROOT = Path(__file__).resolve().parents[2]
SHA = "sha256:" + "a" * 64


def test_supervised_driver_and_chromium_use_private_writable_home(monkeypatch):
    monkeypatch.setenv("HOME", "/root/not-the-browser-home")
    monkeypatch.setattr(sys, "argv", ["eom-kakao-browser-supervisor"])
    monkeypatch.setattr(
        supervisor, "_prepare", Mock(return_value=(Path("/run/synthetic.json"), SHA))
    )
    monkeypatch.setattr(supervisor.signal, "signal", Mock())
    monkeypatch.setattr(supervisor.grp, "getgrnam", lambda _: SimpleNamespace(gr_gid=999))
    launched = Mock()
    monkeypatch.setattr(supervisor.subprocess, "Popen", launched)

    def supervised(launch, **_kwargs):
        launch()
        return 0

    monkeypatch.setattr(supervisor, "supervise", supervised)
    assert supervisor.main() == 0
    assert launched.call_args.kwargs["env"]["HOME"] == str(setup.PROFILE)
    assert setup.child_environment()["HOME"] == str(setup.PROFILE)


def fence(mode="MANUAL"):
    return ProfileFence.model_validate(
        {
            "schema_version": "kakao-profile-fence/1.0",
            "profile_id": "kakaoprofile_" + "a" * 32,
            "browser_run_id": "kakaobrowserrun_" + "b" * 32,
            "fence_epoch": 1,
            "mode": mode,
        }
    )


@pytest.fixture
def local():
    with tempfile.TemporaryDirectory(prefix="kakao-manual-test-", dir=ROOT / "staging") as name:
        yield Path(name)


def start_child(local, *, stop_code=0, ignore=False):
    ready = local / "child-ready"
    events = local / "events"
    program = r"""
import signal,sys,time
from pathlib import Path
def stop(*_):
    with Path(sys.argv[2]).open('a') as stream: stream.write('xvnc-stop\n')
    sys.exit(int(sys.argv[3]))
signal.signal(signal.SIGTERM,signal.SIG_IGN if sys.argv[4]=='ignore' else stop)
Path(sys.argv[1]).touch()
time.sleep(30)
"""
    child = subprocess.Popen(
        [
            sys.executable,
            "-c",
            program,
            str(ready),
            str(events),
            str(stop_code),
            "ignore" if ignore else "handle",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    deadline = time.monotonic() + 3
    while not ready.exists() and child.poll() is None and time.monotonic() < deadline:
        time.sleep(0.01)
    assert ready.exists()
    return child


@pytest.fixture
def manual(local, monkeypatch):
    events = local / "events"

    def record(value):
        with events.open("a") as stream:
            stream.write(value + "\n")

    stopping = asyncio.Event()
    child = start_child(local)
    callbacks = {}

    async def close():
        record("context-close")
        callbacks["close"](object())

    context = SimpleNamespace(
        close=AsyncMock(side_effect=close),
        on=lambda event, callback: callbacks.update({event: callback}) or stopping.set(),
    )
    chromium = SimpleNamespace(
        executable_path="/opt/pinned/chrome",
        launch_persistent_context=AsyncMock(return_value=context),
    )
    playwright = SimpleNamespace(
        chromium=chromium, stop=AsyncMock(side_effect=lambda: record("playwright-stop"))
    )
    monkeypatch.setattr(driver, "_start_playwright", AsyncMock(return_value=playwright))
    monkeypatch.setattr(driver, "_start_xvnc", Mock(return_value=child))
    monkeypatch.setattr(driver, "_wait_xvnc", AsyncMock())
    monkeypatch.setattr(setup, "require_supervisor", Mock())
    monkeypatch.setattr(setup, "prepare_xauthority", Mock())
    monkeypatch.setattr(setup, "require_chromium", Mock())
    config = setup.ManualSetup(fence(), SHA, SHA)
    try:
        yield config, stopping, playwright, context, child, events, callbacks
    finally:
        if child.poll() is None:
            child.kill()
        child.wait(timeout=3)


def test_manual_headed_sandbox_and_close_flush_precede_xvnc_stop(manual):
    config, stopping, playwright, context, child, events, _ = manual
    asyncio.run(driver.run_manual(config, stopping))
    assert events.read_text().splitlines() == ["context-close", "playwright-stop", "xvnc-stop"]
    assert child.returncode == 0 and context.close.await_count == 1
    call = playwright.chromium.launch_persistent_context.call_args
    assert call.args == (str(setup.PROFILE),)
    assert call.kwargs["env"]["HOME"] == str(setup.PROFILE)
    assert call.kwargs == {
        "headless": False,
        "chromium_sandbox": True,
        "accept_downloads": False,
        "timeout": driver.START_SECONDS * 1000,
        "env": setup.child_environment(),
        "handle_sigterm": False,
        "handle_sigint": False,
        "handle_sighup": False,
        "no_viewport": True,
    }
    assert not {"args", "record_video_dir", "record_har_path", "traces_dir"} & call.kwargs.keys()


def test_context_launch_failure_still_stops_transport_and_display(manual):
    config, stopping, playwright, context, child, events, _ = manual
    playwright.chromium.launch_persistent_context.side_effect = ValueError("private details")
    with pytest.raises(ValueError):
        asyncio.run(driver.run_manual(config, stopping))
    assert child.poll() == 0 and context.close.await_count == 0
    assert events.read_text().splitlines() == ["playwright-stop", "xvnc-stop"]


@pytest.mark.parametrize("failing", ["close", "transport"])
def test_cleanup_failure_stays_failure_and_does_not_skip_display_stop(manual, failing):
    config, stopping, playwright, context, child, events, _ = manual
    if failing == "close":
        context.close.side_effect = ValueError("private-url-and-cookie")
    else:
        playwright.stop.side_effect = ValueError("private-url-and-cookie")
    with pytest.raises(BrowserRuntimeError, match=r"CLOSE_FAILED|TRANSPORT_STOP_FAILED"):
        asyncio.run(driver.run_manual(config, stopping))
    assert child.poll() == 0 and "xvnc-stop" in events.read_text()


def test_bounded_context_close_timeout_still_closes_display(manual, monkeypatch):
    config, stopping, _, context, child, _, _ = manual

    async def hanging():
        await asyncio.Event().wait()

    context.close.side_effect = hanging
    monkeypatch.setattr(driver, "CLOSE_SECONDS", 0.02)
    with pytest.raises(BrowserRuntimeError, match="CONTEXT_CLOSE_FAILED"):
        asyncio.run(driver.run_manual(config, stopping))
    assert child.poll() == 0


def test_unexpected_context_close_is_not_success(manual):
    config, stopping, _, context, child, _, callbacks = manual
    context.on = lambda event, callback: callbacks.update({event: callback}) or callback(object())
    with pytest.raises(BrowserRuntimeError, match="CONTEXT_CLOSED"):
        asyncio.run(driver.run_manual(config, stopping))
    assert child.poll() == 0


def test_xvnc_exit_during_manual_is_failure_even_if_exit_zero(manual):
    config, stopping, _, context, child, _, callbacks = manual

    def started(event, callback):
        callbacks[event] = callback
        child.terminate()
        child.wait(timeout=3)

    context.on = started
    with pytest.raises(BrowserRuntimeError, match="XVNC_EXITED"):
        asyncio.run(driver.run_manual(config, stopping))
    assert context.close.await_count == 1


@pytest.mark.parametrize("mode", ["AUTO", "PAUSING", "AUTH_REQUIRED", "ERROR"])
def test_no_auto_adapter_means_explicit_unavailable_without_process(monkeypatch, mode):
    create = Mock()
    monkeypatch.setattr(driver, "_start_xvnc", create)
    with pytest.raises(BrowserRuntimeError, match="AUTO_UNAVAILABLE"):
        asyncio.run(driver.run_manual(setup.ManualSetup(fence(mode), SHA, SHA), asyncio.Event()))
    create.assert_not_called()


@pytest.mark.parametrize(
    "code,ignore,error", [(7, False, "STOP_UNCLEAN"), (0, True, "STOP_FORCED")]
)
def test_actual_xvnc_stop_failure_is_not_success(local, monkeypatch, code, ignore, error):
    child = start_child(local, stop_code=code, ignore=ignore)
    monkeypatch.setattr(driver, "XVNC_STOP_SECONDS", 0.05)
    try:
        with pytest.raises(BrowserRuntimeError, match=error):
            asyncio.run(driver._stop_xvnc(child))
        assert child.poll() is not None
    finally:
        if child.poll() is None:
            child.kill()
        child.wait(timeout=2)


def test_fixed_launch_has_no_secret_value_and_no_tcp_listener(monkeypatch):
    monkeypatch.setenv("TEST_PRIVATE_TOKEN", "never-inherit")
    run = Mock()
    monkeypatch.setattr(driver.subprocess, "Popen", run)
    driver._start_xvnc()
    args = run.call_args.args[0]
    assert args == setup.xvnc_argv()
    assert args[args.index("-SecurityTypes") + 1] == "VncAuth"
    assert args[args.index("-PasswordFile") + 1] == str(setup.PASSWORD)
    assert args[args.index("-rfbport") + 1] == "-1"
    assert args[args.index("-nolisten") + 1] == "tcp"
    assert args[args.index("-rfbunixmode") + 1] == "0660"
    assert args[args.index("-extension") + 1] == "GLX"
    assert "None" not in args and "--no-sandbox" not in args and "-ac" not in args
    assert "never-inherit" not in repr(run.call_args)
    assert run.call_args.kwargs["stdout"] == run.call_args.kwargs["stderr"] == subprocess.DEVNULL


def test_playwright_exact_version_is_required_before_import(monkeypatch):
    monkeypatch.setattr(driver.importlib.metadata, "version", lambda name: "1.55.0")
    importer = Mock()
    monkeypatch.setattr(driver.importlib, "import_module", importer)
    with pytest.raises(BrowserRuntimeError, match="PLAYWRIGHT_RELEASE_MISMATCH"):
        asyncio.run(driver._start_playwright())
    importer.assert_not_called()


@pytest.mark.parametrize("case", ["own-cgroup", "parent-cgroup", "parent-command", "unlocked"])
def test_direct_or_unsupervised_driver_never_uses_profile(local, monkeypatch, case):
    lock = local / "profile.lock"
    lock.touch(mode=0o640)
    lock.chmod(0o640)
    monkeypatch.setattr(setup, "LOCK", lock)
    monkeypatch.setattr(setup.grp, "getgrnam", lambda name: SimpleNamespace(gr_gid=os.getgid()))
    monkeypatch.setattr(setup.os, "getppid", lambda: 1234)

    def read(path):
        if path.name == "cmdline":
            parts = [str(setup.PYTHON), "-I", "-B", "-m", "eom_kakao_archive_collector.supervisor"]
            if case == "parent-command":
                parts[-1] = "some-other-command"
            return "\0".join(parts).encode() + b"\0"
        if (case == "own-cgroup" and "self" in path.parts) or (
            case == "parent-cgroup" and "1234" in path.parts
        ):
            return b"0::/user.slice/wrong.service\n"
        return setup.CGROUP.encode() + b"\n"

    monkeypatch.setattr(setup, "_kernel_read", read)

    @contextmanager
    def unlocked(*args, **kwargs):
        yield

    monkeypatch.setattr(setup, "profile_lock", unlocked)
    with pytest.raises(BrowserRuntimeError, match="SUPERVISION_UNCONFIRMED"):
        setup.require_supervisor()


@pytest.mark.parametrize("case", ["plain", "symlink", "hardlink", "writable", "not-executable"])
def test_streaming_binary_hash_checks_local_file_identity(local, case):
    binary = local / "chromium"
    binary.write_bytes(b"anonymous executable fixture" * 10000)
    binary.chmod(0o750)
    if case == "symlink":
        link = local / "link"
        link.symlink_to(binary)
        binary = link
    elif case == "hardlink":
        os.link(binary, local / "linked")
    elif case == "writable":
        binary.chmod(0o770)
    elif case == "not-executable":
        binary.chmod(0o640)
    if case == "plain":
        assert setup.hash_executable(binary, uid=os.getuid()).startswith("sha256:")
    else:
        with pytest.raises((BrowserRuntimeError, OSError)):
            setup.hash_executable(binary, uid=os.getuid())


@pytest.mark.parametrize("existing_authority", [False, True])
def test_protected_setup_requires_exact_snapshot_and_preserves_credentials(
    local, monkeypatch, existing_authority
):
    private = local / "private"
    profile = local / "profile"
    vnc = local / "vnc"
    for directory in (private, profile, vnc):
        directory.mkdir(mode=0o700)
    vnc.chmod(0o2750)
    request = private / f"{fence().browser_run_id}.json"
    request.write_text(json.dumps(fence().model_dump(mode="json")))
    request.chmod(0o400)
    xauth = private / "Xauthority"
    if existing_authority:
        xauth.write_bytes(b"synthetic-not-real-authority")
        xauth.chmod(0o600)
    password = local / "vnc.passwd"
    password.write_bytes(b"FAKEONLY")
    password.chmod(0o600)
    release = local / "driver.env"
    release.write_text(f"EOM_KAKAO_XVNC_SHA256={SHA}\nEOM_KAKAO_CHROMIUM_SHA256={SHA}\n")
    release.chmod(0o640)
    for key, path in (
        ("PRIVATE", private),
        ("PROFILE", profile),
        ("VNC_SOCKET", vnc / "vnc.sock"),
        ("XAUTHORITY", xauth),
        ("PASSWORD", password),
        ("RELEASE", release),
        ("X_SOCKET", local / "X94"),
        ("X_LOCK", local / "X94-lock"),
    ):
        monkeypatch.setattr(setup, key, path)
    monkeypatch.setattr(
        setup.pwd, "getpwnam", lambda name: SimpleNamespace(pw_uid=os.getuid(), pw_gid=os.getgid())
    )
    monkeypatch.setattr(setup.grp, "getgrnam", lambda name: SimpleNamespace(gr_gid=os.getgid()))
    monkeypatch.setattr(setup, "require_supervisor", Mock())
    monkeypatch.setattr(setup, "hash_executable", lambda path: SHA)
    original = setup.read_protected
    monkeypatch.setattr(
        setup,
        "read_protected",
        lambda path, **kw: original(
            path,
            uid=os.getuid(),
            limit=kw["limit"],
            allowed_uids=frozenset({0, os.getuid()}),
            required_mode=kw.get("required_mode"),
        ),
    )
    before = (xauth.read_bytes() if existing_authority else None, password.read_bytes())
    assert setup.validate_setup(request, profile).fence == fence()
    password.chmod(0o640)
    with pytest.raises(BrowserRuntimeError, match="MEMBER_UNSAFE"):
        setup.validate_setup(request, profile)
    password.chmod(0o600)
    endpoint = vnc / "vnc.sock"
    endpoint.symlink_to(local / "nonexistent")
    with pytest.raises(BrowserRuntimeError, match="RECONCILE_REQUIRED"):
        setup.validate_setup(request, profile)
    assert endpoint.is_symlink()
    assert (xauth.read_bytes() if xauth.exists() else None, password.read_bytes()) == before


@pytest.mark.parametrize(
    "bad", [[], ["--profile", "/private"], ["--request", "/tmp/a", "--profile", "/tmp/b"]]
)
def test_driver_cli_never_echoes_private_argv(bad):
    completed = subprocess.run(
        [sys.executable, "-m", "eom_kakao_archive_collector.manual_driver", *bad],
        capture_output=True,
        check=False,
        timeout=10,
    )
    assert completed.returncode == 78 and not completed.stdout
    assert b"/private" not in completed.stderr and b"/tmp/" not in completed.stderr
    assert completed.stderr.strip() in {
        b"KAKAO_BROWSER_FIXED_INPUT_REQUIRED",
        b"KAKAO_BROWSER_MANUAL_UNAVAILABLE",
    }


def test_socket_readiness_requires_live_owned_unix_endpoint(local, monkeypatch):
    path = local / "vnc.sock"
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(path))
    server.listen(1)
    path.chmod(0o660)
    monkeypatch.setattr(setup, "VNC_SOCKET", path)
    monkeypatch.setattr(driver.grp, "getgrnam", lambda name: SimpleNamespace(gr_gid=os.getgid()))
    display = AsyncMock(side_effect=[False, True])
    monkeypatch.setattr(driver, "_display_ready", display)
    child = Mock(poll=lambda: None)
    try:
        asyncio.run(driver._wait_xvnc(child, asyncio.Event()))
        assert display.await_count == 2
        connection, _ = server.accept()
        connection.close()
        path.chmod(0o666)
        with pytest.raises(BrowserRuntimeError, match="VNC_SOCKET_UNSAFE"):
            asyncio.run(driver._wait_xvnc(child, asyncio.Event()))
    finally:
        server.close()


@pytest.mark.parametrize("status", [0, 1])
def test_display_readiness_checks_real_auth_with_no_output_or_ambient_env(monkeypatch, status):
    child = SimpleNamespace(returncode=status, wait=AsyncMock(return_value=status))
    create = AsyncMock(return_value=child)
    monkeypatch.setattr(driver.asyncio, "create_subprocess_exec", create)
    monkeypatch.setenv("TEST_PRIVATE_TOKEN", "never-inherit")
    assert asyncio.run(driver._display_ready()) is (status == 0)
    assert create.call_args.args == (str(setup.XDPYINFO),)
    assert create.call_args.kwargs == {
        "stdin": asyncio.subprocess.DEVNULL,
        "stdout": asyncio.subprocess.DEVNULL,
        "stderr": asyncio.subprocess.DEVNULL,
        "env": setup.child_environment(),
    }


def test_display_probe_cancel_kills_and_reaps_before_propagating(monkeypatch):
    child = SimpleNamespace(
        returncode=None,
        wait=AsyncMock(side_effect=[asyncio.CancelledError(), 0]),
        kill=Mock(),
    )
    monkeypatch.setattr(driver.asyncio, "create_subprocess_exec", AsyncMock(return_value=child))
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(driver._display_ready())
    child.kill.assert_called_once()
    assert child.wait.await_count == 2


def test_x11_directory_prepared_once_inside_private_tmp(local, monkeypatch):
    path = local / ".X11-unix"
    monkeypatch.setattr(setup, "X11_DIRECTORY", path)
    monkeypatch.setattr(setup, "X_SOCKET", path / "X94")
    supervised = Mock()
    monkeypatch.setattr(setup, "require_supervisor", supervised)
    setup.prepare_x11_directory()
    assert path.stat().st_mode & 0o7777 == 0o1777
    inode = path.stat().st_ino
    setup.prepare_x11_directory()
    assert path.stat().st_ino == inode
    assert supervised.call_count == 2


def test_x11_directory_never_follows_existing_symlink_or_chmods_target(local, monkeypatch):
    path = local / ".X11-unix"
    target = local / "preserve"
    target.mkdir(mode=0o700)
    path.symlink_to(target, target_is_directory=True)
    monkeypatch.setattr(setup, "X11_DIRECTORY", path)
    monkeypatch.setattr(setup, "X_SOCKET", path / "X94")
    monkeypatch.setattr(setup, "require_supervisor", Mock())
    with pytest.raises(OSError):
        setup.prepare_x11_directory()
    assert target.stat().st_mode & 0o7777 == 0o700 and path.is_symlink()


def test_x11_directory_requires_supervision_before_any_creation(local, monkeypatch):
    path = local / ".X11-unix"
    monkeypatch.setattr(setup, "X11_DIRECTORY", path)
    monkeypatch.setattr(setup, "X_SOCKET", path / "X94")
    monkeypatch.setattr(
        setup, "require_supervisor", Mock(side_effect=BrowserRuntimeError("UNSUPERVISED"))
    )
    with pytest.raises(BrowserRuntimeError, match="UNSUPERVISED"):
        setup.prepare_x11_directory()
    assert not path.exists()


def test_actual_driver_sigterm_closes_context_before_display(local):
    events = local / "signal-events"
    program = r"""
import asyncio,sys,subprocess,time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from eom_kakao_archive_collector import manual_driver as d
from eom_kakao_archive_collector import driver_setup as s
from eom_kakao_archive_contracts.kakao_remote import ProfileFence
events=Path(sys.argv[1]); ready=events.with_suffix('.ready')
def record(value):
    with events.open('a') as f:f.write(value+'\n')
child_program="import signal,sys,time;from pathlib import Path;"\
    "signal.signal(signal.SIGTERM,lambda *_:("\
    "Path(sys.argv[1]).open('a').write('display\\n'),sys.exit(0)));"\
    "Path(sys.argv[2]).touch();time.sleep(30)"
child=subprocess.Popen([sys.executable,'-c',child_program,str(events),str(ready)])
deadline=time.monotonic()+3
while not ready.exists() and child.poll() is None and time.monotonic()<deadline:time.sleep(.01)
assert ready.exists()
class Context:
    def on(self,*args):print('READY',flush=True)
    async def close(self):record('context')
ctx=Context()
p=SimpleNamespace(chromium=SimpleNamespace(executable_path='/opt/pinned/chrome',
    launch_persistent_context=AsyncMock(return_value=ctx)),stop=AsyncMock(side_effect=lambda:record('transport')))
d._start_playwright=AsyncMock(return_value=p);d._start_xvnc=lambda:child;d._wait_xvnc=AsyncMock()
s.require_supervisor=lambda:None;s.require_chromium=lambda *args:None
s.prepare_xauthority=lambda:None
f=ProfileFence.model_validate({'schema_version':'kakao-profile-fence/1.0','profile_id':'kakaoprofile_'+'a'*32,
    'browser_run_id':'kakaobrowserrun_'+'b'*32,'fence_epoch':1,'mode':'MANUAL'})
asyncio.run(d._run(s.ManualSetup(f,'sha256:'+'a'*64,'sha256:'+'b'*64)))
assert child.returncode==0
"""
    process = subprocess.Popen(
        [sys.executable, "-c", program, str(events)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    try:
        assert process.stdout.readline().strip() == "READY"
        process.send_signal(signal.SIGTERM)
        assert process.wait(timeout=5) == 0, process.stderr.read()
        assert events.read_text().splitlines() == ["context", "transport", "display"]
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=2)
